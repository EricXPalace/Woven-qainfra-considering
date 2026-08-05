# Closed-Loop Safety & Audit Pipeline for Cyber-Physical Systems

An end-to-end, automated QA infrastructure and safety audit pipeline built for Cyber-Physical Systems (e.g., Autonomous Vehicles). 

When an emergency or crash condition occurs on an Edge hardware node, a **Kill Switch** triggers an immediate dump of the rolling 60-second in-memory telemetry buffer. The dump is published over an **MQTT Broker** to a containerized **Python CI/QA Engine**, which automatically executes safety audit test suites (`pytest`) using `testcontainers`.

---

## 📐 Architecture Overview

```mermaid
sequenceDiagram
    autonumber
    participant Gen as Mock Sensor Generator
    participant Edge as Edge Node (Rust)
    participant Broker as Mosquitto MQTT Broker
    participant CI as Python CI/QA Engine
    participant QA as Pytest Audit Suite

    Note over Edge: Maintains 60s rolling telemetry buffer in RAM
    Gen->>Edge: POST /telemetry (speed, brake, steering, RPM)
    Note over Gen,Edge: Continuous streaming...

    rect rgb(240, 220, 220)
    Gen->>Edge: POST /kill-switch (Emergency Trigger)
    end

    Note over Edge: Packages 60s telemetry buffer into JSON payload
    Edge->>Broker: Publish JSON to topic 'safety/blackbox/dump'
    Broker->>CI: Deliver MQTT payload
    CI->>CI: Save payload & invoke pytest
    CI->>QA: Run test_pipeline.py (Audit Rules & Testcontainers)
    QA-->>CI: Audit Report (Pass/Fail)
```

---

## 🛠️ Components

### 1. Edge Node (Rust)
* **Location**: `./edge-node`
* **Framework**: `axum`, `tokio`, `serde`, `rumqttc`, `chrono`
* **Logic**:
  * Thread-safe rolling buffer using `Arc<Mutex<VecDeque<TelemetryFrame>>>`.
  * Automatically prunes telemetry entries older than 60 seconds.
  * `POST /telemetry`: Ingests real-time vehicle telemetry frames.
  * `POST /kill-switch` or `POST /trigger-dump`: Packages the 60s telemetry window into a UUID-tagged blackbox JSON payload and publishes to MQTT.

### 2. Message Broker (Eclipse Mosquitto)
* **Location**: `./mosquitto`
* **Container**: `eclipse-mosquitto:2.0`
* **Config**: `./mosquitto/config/mosquitto.conf` allowing local QA MQTT communication on port `1883`.

### 3. CI/QA Engine (Python)
* **Location**: `./ci-engine`
* **Framework**: `paho-mqtt`, `pytest`, `testcontainers`, `pydantic`
* **Logic**:
  * `app.py`: Persistent MQTT client listening to topic `safety/blackbox/dump`.
  * On receipt of a blackbox dump payload, saves the payload and programmatically executes `pytest tests/test_pipeline.py`.
  * `test_pipeline.py`: Pytest suite verifying:
    1. **Payload Schema Integrity**: Metadata, frame count, field presence.
    2. **Telemetry Chronology**: Timestamp monotonicity across the 60s buffer.
    3. **Brake System Response**: Deceleration compliance during high brake pressure events.
    4. **Physical Limits**: Speed and steering lock boundary compliance.
    5. **Testcontainers Integration**: Isolated container fixture support for auxiliary audit services.

### 4. Mock Telemetry Generator (Python)
* **Location**: `./edge-node/mock_telemetry_generator.py`
* **Description**: CLI utility simulating dynamic vehicle dynamics (fluctuating speed, brake taps, steering oscillations) and streaming sensor data to the Edge Node REST endpoint with options to trigger the Kill Switch.

---

## 📋 JSON Blackbox Payload Schema

Below is the JSON structure published over MQTT topic `safety/blackbox/dump`:

```json
{
  "event_id": "9b1deb4d-3b7d-4bad-9bdd-2b0d7b3dcb6d",
  "timestamp": "2026-08-05T12:00:00Z",
  "trigger_reason": "KILL_SWITCH_MANUAL_TRIGGER",
  "buffer_duration_seconds": 60,
  "frame_count": 300,
  "telemetry": [
    {
      "timestamp": "2026-08-05T11:59:00.123Z",
      "speed_kmh": 65.4,
      "brake_status": true,
      "brake_pressure_psi": 220.5,
      "steering_angle_deg": -2.1,
      "wheel_speed_rpm": 578.3
    }
  ]
}
```

---

## 🚀 Quickstart & Deployment

### 1. Spin up the Architecture via Docker Compose

```bash
docker-compose up --build
```

This will launch:
* `mosquitto_broker` on `1883`
* `rust_edge_node` on `http://localhost:8080`
* `python_ci_engine` listening for MQTT messages

---

### 2. Stream Mock Telemetry & Trigger Kill Switch

In a separate terminal, launch the mock data generator:

```bash
python edge-node/mock_telemetry_generator.py --url http://localhost:8080 --rate 5 --trigger-kill 10
```

* Flags:
  * `--url`: Edge Node endpoint (default: `http://localhost:8080`).
  * `--rate`: Telemetry frequency in Hz (default: `5`).
  * `--trigger-kill`: Automatically trigger Kill Switch after 10 seconds of streaming.

---

### 3. Observe Automated QA Audit Trigger

Inspect the `python_ci_engine` logs to observe blackbox payload ingestion and automated pytest execution:

```bash
docker logs -f python_ci_engine
```

Sample output:
```text
[INFO] CI-Engine: 📥 Received MQTT message on topic 'safety/blackbox/dump' (18420 bytes)
[INFO] CI-Engine: Blackbox Payload ID: 9b1deb4d-3b7d-4bad-9bdd-2b0d7b3dcb6d | Frames: 50 | Trigger: MOCK_GENERATOR_KILL_SWITCH_TEST
[INFO] CI-Engine: ⚡ Triggering Pytest Audit Execution...
PASSED tests/test_pipeline.py::test_payload_integrity
PASSED tests/test_pipeline.py::test_frame_chronology
PASSED tests/test_pipeline.py::test_brake_system_response
PASSED tests/test_pipeline.py::test_physical_limits
[INFO] CI-Engine: ✅ SAFETY AUDIT PASSED: Vehicle telemetry meets safety bounds!
```

---

## 📂 Project Repository

Git Remote: `https://github.com/EricXPalace/Woven-qainfra-considering.git`
