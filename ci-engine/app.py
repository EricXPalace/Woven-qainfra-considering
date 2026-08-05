#!/usr/bin/env python3
"""
CI/QA Engine Listener for Cyber-Physical Closed-Loop Safety & Audit Pipeline.

Subscribes to the Mosquitto MQTT broker topic (default: safety/blackbox/dump).
Upon receiving a black-box telemetry dump payload:
  1. Validates and stores the payload.
  2. Triggers an automated Pytest audit suite (test_pipeline.py).
  3. Reports QA audit results.
"""

import json
import logging
import os
import sys
import time
import subprocess
import paho.mqtt.client as mqtt

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("CI-Engine")

MQTT_HOST = os.getenv("MQTT_HOST", "mosquitto")
MQTT_PORT = int(os.getenv("MQTT_PORT", "1883"))
MQTT_TOPIC = os.getenv("MQTT_TOPIC", "safety/blackbox/dump")
PAYLOAD_SAVE_PATH = os.getenv("PAYLOAD_SAVE_PATH", "/app/received_payload.json")


def on_connect(client, userdata, flags, rc):
    if rc == 0:
        logger.info(f"Connected to Mosquitto broker at {MQTT_HOST}:{MQTT_PORT}")
        client.subscribe(MQTT_TOPIC, qos=1)
        logger.info(f"Subscribed to topic: '{MQTT_TOPIC}'")
    else:
        logger.error(f"Failed to connect to MQTT broker with return code {rc}")


def trigger_pytest_suite(payload_filepath: str):
    """
    Executes the Pytest safety audit suite against the received blackbox payload.
    """
    logger.info("⚡ Triggering Pytest Audit Execution...")
    
    # Environment variable passed to pytest so fixture knows payload path
    env = os.environ.copy()
    env["BLACKBOX_PAYLOAD_PATH"] = payload_filepath

    test_target = os.path.join(os.path.dirname(__file__), "tests", "test_pipeline.py")

    cmd = [
        sys.executable,
        "-m",
        "pytest",
        "-v",
        "--tb=short",
        test_target,
    ]

    start_time = time.time()
    result = subprocess.run(cmd, env=env, capture_output=True, text=True)
    duration = time.time() - start_time

    logger.info(f"--- Pytest Execution Completed in {duration:.2f}s ---")
    logger.info(f"Exit Code: {result.returncode}")
    print("\n--- STDOUT ---")
    print(result.stdout)
    if result.stderr:
        print("\n--- STDERR ---")
        print(result.stderr)

    if result.returncode == 0:
        logger.info("✅ SAFETY AUDIT PASSED: Vehicle telemetry meets safety bounds!")
    else:
        logger.error("❌ SAFETY AUDIT FAILED: Violations detected in telemetry dump!")


def on_message(client, userdata, msg):
    logger.info(f"📥 Received MQTT message on topic '{msg.topic}' ({len(msg.payload)} bytes)")

    try:
        payload_data = json.loads(msg.payload.decode("utf-8"))
        event_id = payload_data.get("event_id", "UNKNOWN_EVENT")
        frame_count = payload_data.get("frame_count", len(payload_data.get("telemetry", [])))
        reason = payload_data.get("trigger_reason", "N/A")

        logger.info(f"Blackbox Payload ID: {event_id} | Frames: {frame_count} | Trigger: {reason}")

        # Ensure directory exists and write payload to disk
        os.makedirs(os.path.dirname(os.path.abspath(PAYLOAD_SAVE_PATH)), exist_ok=True)
        with open(PAYLOAD_SAVE_PATH, "w", encoding="utf-8") as f:
            json.dump(payload_data, f, indent=2)

        logger.info(f"Saved blackbox dump to '{PAYLOAD_SAVE_PATH}'")

        # Trigger QA Test Pipeline
        trigger_pytest_suite(PAYLOAD_SAVE_PATH)

    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse JSON payload: {e}")
    except Exception as e:
        logger.error(f"Unexpected error handling message: {e}", exc_info=True)


def main():
    logger.info("Starting CI/QA Engine Listener...")
    client = mqtt.Client(client_id="ci-qa-engine", clean_session=True)
    client.on_connect = on_connect
    client.on_message = on_message

    retry_count = 0
    max_retries = 30

    while retry_count < max_retries:
        try:
            logger.info(f"Connecting to MQTT broker {MQTT_HOST}:{MQTT_PORT} (Attempt {retry_count + 1})...")
            client.connect(MQTT_HOST, MQTT_PORT, keepalive=60)
            break
        except Exception as e:
            logger.warning(f"Broker connection failed ({e}). Retrying in 2s...")
            time.sleep(2)
            retry_count += 1

    if retry_count >= max_retries:
        logger.critical("Could not connect to MQTT broker. Exiting.")
        sys.exit(1)

    logger.info("Entering MQTT network loop...")
    client.loop_forever()


if __name__ == "__main__":
    main()
