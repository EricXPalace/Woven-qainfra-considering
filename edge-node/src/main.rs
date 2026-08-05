use axum::{
    extract::State,
    http::StatusCode,
    routing::{get, post},
    Json, Router,
};
use chrono::{DateTime, Duration, Utc};
use rumqttc::{AsyncClient, MqttOptions, QoS};
use serde::{Deserialize, Serialize};
use std::{
    collections::VecDeque,
    env,
    net::SocketAddr,
    sync::{Arc, Mutex},
    time::Duration as StdDuration,
};
use tracing::{error, info};
use tracing_subscriber::{layer::SubscriberExt, util::SubscriberInitExt};
use uuid::Uuid;

/// Telemetry frame structure representing vehicle sensor state.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct TelemetryFrame {
    #[serde(default = "Utc::now")]
    pub timestamp: DateTime<Utc>,
    pub speed_kmh: f64,
    pub brake_status: bool,
    pub brake_pressure_psi: f64,
    pub steering_angle_deg: f64,
    pub wheel_speed_rpm: f64,
}

/// Complete Blackbox Dump Payload generated when Kill Switch is engaged.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct BlackboxPayload {
    pub event_id: String,
    pub timestamp: DateTime<Utc>,
    pub trigger_reason: String,
    pub buffer_duration_seconds: u64,
    pub frame_count: usize,
    pub telemetry: Vec<TelemetryFrame>,
}

/// Request body for triggering the kill switch manually.
#[derive(Debug, Deserialize)]
pub struct KillSwitchRequest {
    #[serde(default = "default_reason")]
    pub reason: String,
}

fn default_reason() -> String {
    "KILL_SWITCH_MANUAL_TRIGGER".to_string()
}

/// Shared application state holding rolling buffer and MQTT client.
#[derive(Clone)]
pub struct AppState {
    pub buffer: Arc<Mutex<VecDeque<TelemetryFrame>>>,
    pub mqtt_client: AsyncClient,
    pub mqtt_topic: String,
    pub max_buffer_duration_secs: i64,
}

impl AppState {
    /// Memory-safe buffer pruning: removes entries older than 60 seconds.
    pub fn prune_buffer(buffer: &mut VecDeque<TelemetryFrame>, max_secs: i64) {
        let cutoff = Utc::now() - Duration::seconds(max_secs);
        while let Some(front) = buffer.front() {
            if front.timestamp < cutoff {
                buffer.pop_front();
            } else {
                break;
            }
        }
    }
}

#[tokio::main]
async fn main() {
    // Initialize structured tracing logs
    tracing_subscriber::registry()
        .with(tracing_subscriber::EnvFilter::new(
            env::var("RUST_LOG").unwrap_or_else(|_| "info,edge_node=debug".into()),
        ))
        .with(tracing_subscriber::fmt::layer())
        .init();

    info!("Starting Edge Node Safety Agent...");

    // Environment variables
    let mqtt_host = env::var("MQTT_HOST").unwrap_or_else(|_| "mosquitto".to_string());
    let mqtt_port: u16 = env::var("MQTT_PORT")
        .unwrap_or_else(|_| "1883".to_string())
        .parse()
        .expect("MQTT_PORT must be a valid number");
    let mqtt_topic = env::var("MQTT_TOPIC").unwrap_or_else(|_| "safety/blackbox/dump".to_string());
    let server_port: u16 = env::var("PORT")
        .unwrap_or_else(|_| "8080".to_string())
        .parse()
        .expect("PORT must be a valid number");

    // Configure rumqttc MQTT client
    let mut mqtt_options = MqttOptions::new("edge-node-agent", mqtt_host.clone(), mqtt_port);
    mqtt_options.set_keep_alive(StdDuration::from_secs(5));

    let (mqtt_client, mut eventloop) = AsyncClient::new(mqtt_options, 10);

    // Spawn background task to process MQTT eventloop
    tokio::spawn(async move {
        loop {
            match eventloop.poll().await {
                Ok(_notification) => {}
                Err(e) => {
                    error!("MQTT Loop Error: {:?}", e);
                    tokio::time::sleep(StdDuration::from_secs(2)).await;
                }
            }
        }
    });

    info!("Connected to MQTT broker at {}:{}", mqtt_host, mqtt_port);

    let state = AppState {
        buffer: Arc::new(Mutex::new(VecDeque::new())),
        mqtt_client,
        mqtt_topic,
        max_buffer_duration_secs: 60,
    };

    // Axum HTTP router definition
    let app = Router::new()
        .route("/health", get(health_check))
        .route("/telemetry", post(ingest_telemetry))
        .route("/kill-switch", post(trigger_kill_switch))
        .route("/trigger-dump", post(trigger_kill_switch))
        .with_state(state);

    let addr = SocketAddr::from(([0, 0, 0, 0], server_port));
    info!("Edge Node REST API listening on http://{}", addr);

    let listener = tokio::net::TcpListener::bind(addr).await.unwrap();
    axum::serve(listener, app).await.unwrap();
}

/// GET /health - Liveness probe endpoint
async fn health_check() -> (StatusCode, &'static str) {
    (StatusCode::OK, "OK")
}

/// POST /telemetry - Ingest sensor frame into 60-second rolling buffer
async fn ingest_telemetry(
    State(state): State<AppState>,
    Json(mut frame): Json<TelemetryFrame>,
) -> (StatusCode, Json<serde_json::Value>) {
    // Default timestamp to Utc::now() if uninitialized
    if frame.timestamp > Utc::now() + Duration::seconds(5) {
        frame.timestamp = Utc::now();
    }

    let mut lock = state.buffer.lock().unwrap();
    lock.push_back(frame);

    // Prune buffer to retain only last 60 seconds
    AppState::prune_buffer(&mut lock, state.max_buffer_duration_secs);

    let current_len = lock.len();

    (
        StatusCode::OK,
        Json(serde_json::json!({
            "status": "buffered",
            "buffer_size": current_len
        })),
    )
}

/// POST /kill-switch or POST /trigger-dump
/// Packages the 60s rolling buffer into a blackbox dump payload and publishes to MQTT.
async fn trigger_kill_switch(
    State(state): State<AppState>,
    body: Option<Json<KillSwitchRequest>>,
) -> (StatusCode, Json<serde_json::Value>) {
    let reason = body
        .map(|b| b.reason.clone())
        .unwrap_or_else(|| "KILL_SWITCH_ENGAGED".to_string());

    let mut lock = state.buffer.lock().unwrap();
    AppState::prune_buffer(&mut lock, state.max_buffer_duration_secs);

    let telemetry_frames: Vec<TelemetryFrame> = lock.iter().cloned().collect();
    let frame_count = telemetry_frames.len();
    let event_id = Uuid::new_v4().to_string();
    let now = Utc::now();

    let payload = BlackboxPayload {
        event_id: event_id.clone(),
        timestamp: now,
        trigger_reason: reason.clone(),
        buffer_duration_seconds: state.max_buffer_duration_secs as u64,
        frame_count,
        telemetry: telemetry_frames,
    };

    let payload_bytes = serde_json::to_vec(&payload).unwrap();

    info!(
        "Kill Switch Triggered! Publishing {} frames to MQTT topic '{}'",
        frame_count, state.mqtt_topic
    );

    match state
        .mqtt_client
        .publish(
            state.mqtt_topic.clone(),
            QoS::AtLeastOnce,
            false,
            payload_bytes,
        )
        .await
    {
        Ok(_) => {
            info!("Successfully published blackbox dump payload (ID: {})", event_id);
            (
                StatusCode::OK,
                Json(serde_json::json!({
                    "status": "triggered",
                    "event_id": event_id,
                    "trigger_reason": reason,
                    "frames_dumped": frame_count,
                    "published_topic": state.mqtt_topic
                })),
            )
        }
        Err(e) => {
            error!("Failed to publish payload to MQTT: {:?}", e);
            (
                StatusCode::INTERNAL_SERVER_ERROR,
                Json(serde_json::json!({
                    "error": format!("MQTT publish error: {:?}", e)
                })),
            )
        }
    }
}
