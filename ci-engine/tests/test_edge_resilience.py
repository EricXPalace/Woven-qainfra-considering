"""
Pytest Suite for Chaos Engineering & Edge Resilience Testing.

Scenarios Covered:
  1. Thermal Throttling Test: Verifies mock device throttles CPU and publishes
     {"status": "throttling_active"} within 3.0 seconds upon receiving an 85°C heat spike.
  2. A/B Rollback Test: Verifies mock device falls back to slot A and publishes
     {"fallback_to_slot_a": true} when an OTA update to slot B encounters a fatal error.
"""

import json
import os
import queue
import sys
import time
import pytest
import paho.mqtt.client as mqtt

# Ensure parent directory is in sys.path for importing chaos_injector and mock_edge_device
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from chaos_injector import ChaosInjector
from mock_edge_device import MockEdgeDevice


@pytest.fixture(scope="module")
def mqtt_broker_config():
    """
    Fixture providing MQTT host and port configuration.
    """
    return {
        "host": os.getenv("MQTT_HOST", "localhost"),
        "port": int(os.getenv("MQTT_PORT", "1883")),
    }


@pytest.fixture(scope="module")
def mock_device(mqtt_broker_config):
    """
    Fixture initializing and starting the Mock Edge Device state machine.
    """
    device = MockEdgeDevice(
        host=mqtt_broker_config["host"],
        port=mqtt_broker_config["port"],
        client_id="pytest-mock-edge-device",
    )
    device.start()
    time.sleep(0.5)  # Allow MQTT subscription setup
    yield device
    device.stop()


@pytest.fixture(scope="function")
def chaos_injector(mqtt_broker_config):
    """
    Fixture initializing the ChaosInjector helper for each test function.
    """
    with ChaosInjector(
        host=mqtt_broker_config["host"],
        port=mqtt_broker_config["port"],
        client_id="pytest-chaos-injector",
    ) as injector:
        yield injector


@pytest.fixture(scope="function")
def status_listener(mqtt_broker_config):
    """
    Fixture providing a thread-safe message queue listening to topic 'edge/status'.
    """
    status_queue = queue.Queue()

    def on_message(client, userdata, msg):
        try:
            payload = json.loads(msg.payload.decode("utf-8"))
            status_queue.put(payload)
        except Exception:
            pass

    client = mqtt.Client(client_id="pytest-status-listener", clean_session=True)
    client.on_message = on_message
    client.connect(mqtt_broker_config["host"], mqtt_broker_config["port"], keepalive=60)
    client.subscribe("edge/status", qos=1)
    client.loop_start()

    yield status_queue

    client.loop_stop()
    client.disconnect()


def test_thermal_throttling(mock_device, chaos_injector, status_listener):
    """
    Scenario 1: Thermal Throttling Test Case
    Story:
      - Arrange: Ensure edge device is in 'Normal' CPU state.
      - Act: Inject thermal fault payload {"sensor": "temperature", "value": 85}.
      - Assert: Expect {"status": "throttling_active"} published to 'edge/status' within 3 seconds.
    """
    # --- ARRANGE ---
    assert mock_device.cpu_freq == "Normal", "Edge device must start in 'Normal' CPU frequency state"

    # --- ACT ---
    print("\n[Act] Injecting thermal heat spike (85°C)...")
    chaos_injector.inject_thermal_spike(temperature=85.0, topic="edge/faults")

    # --- ASSERT ---
    print("[Assert] Waiting up to 3.0s for device status response on 'edge/status'...")
    received_msg = None
    start_wait = time.time()

    while time.time() - start_wait < 3.0:
        try:
            msg = status_listener.get(timeout=0.5)
            if msg.get("status") == "throttling_active":
                received_msg = msg
                break
        except queue.Empty:
            continue

    assert received_msg is not None, "Device failed to publish throttling status within 3 seconds deadline"
    assert received_msg.get("status") == "throttling_active", "Status must equal 'throttling_active'"
    assert mock_device.cpu_freq == "Throttled", "Mock device state cpu_freq must be 'Throttled'"
    print("✅ Thermal Throttling Test Passed!")


def test_ab_rollback_on_failed_ota(mock_device, chaos_injector, status_listener):
    """
    Scenario 2: A/B Rollback Test Case
    Story:
      - Arrange: Ensure edge device starts in Slot 'A'.
      - Act: Publish OTA update command {"command": "update", "slot": "B"}
             and simultaneously inject Fatal Error payload {"event": "fatal_error"}.
      - Assert: Device must output {"fallback_to_slot_a": true} and retain Slot 'A'.
    """
    # --- ARRANGE ---
    mock_device.current_slot = "A"
    mock_device.pending_ota_slot = None
    assert mock_device.current_slot == "A", "Edge device must start in Slot A"

    # --- ACT ---
    print("\n[Act] Issuing OTA Update command to Slot B alongside Fatal Error injection...")
    # Simultaneously issue update command and inject fatal error fault
    chaos_injector.publish_command({"command": "update", "slot": "B"}, topic="edge/ota/command")
    chaos_injector.inject_fatal_error(event_type="fatal_error", topic="edge/faults")

    # --- ASSERT ---
    print("[Assert] Waiting up to 3.0s for A/B rollback fallback message on 'edge/status'...")
    received_msg = None
    start_wait = time.time()

    while time.time() - start_wait < 3.0:
        try:
            msg = status_listener.get(timeout=0.5)
            if msg.get("fallback_to_slot_a") is True:
                received_msg = msg
                break
        except queue.Empty:
            continue

    assert received_msg is not None, "Device failed to output fallback message within timeout"
    assert received_msg.get("fallback_to_slot_a") is True, "Fallback response must be true"
    assert mock_device.current_slot == "A", "Mock device state current_slot must remain 'A'"
    print("✅ A/B Rollback Test Passed!")
