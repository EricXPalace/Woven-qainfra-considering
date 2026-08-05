"""
Pytest Suite for Cyber-Physical Vehicle Safety & Audit Pipeline.

Ingests the MQTT blackbox payload via a Pytest fixture and performs key safety checks:
  1. Payload Integrity & JSON Schema Verification
  2. Telemetry Chronology & Timestamp Continuity
  3. Brake System Response & Deceleration Safety Audit
  4. Steering Angle & Speed Physical Bound Audit
Includes a Testcontainers fixture template for isolated integration testing against mock audit services.
"""

import json
import os
from datetime import datetime
import pytest
from testcontainers.core.container import DockerContainer


@pytest.fixture(scope="session")
def blackbox_payload():
    """
    Pytest fixture ingesting the MQTT blackbox telemetry dump payload from file.
    """
    payload_path = os.getenv("BLACKBOX_PAYLOAD_PATH", "received_payload.json")

    if not os.path.exists(payload_path):
        # Fallback sample payload for standalone fixture testing
        return {
            "event_id": "00000000-0000-0000-0000-000000000000",
            "timestamp": "2026-08-05T12:00:00Z",
            "trigger_reason": "STANDALONE_FIXTURE_FALLBACK",
            "buffer_duration_seconds": 60,
            "frame_count": 3,
            "telemetry": [
                {
                    "timestamp": "2026-08-05T11:59:00Z",
                    "speed_kmh": 80.0,
                    "brake_status": False,
                    "brake_pressure_psi": 0.0,
                    "steering_angle_deg": 2.0,
                    "wheel_speed_rpm": 708.0,
                },
                {
                    "timestamp": "2026-08-05T11:59:30Z",
                    "speed_kmh": 70.0,
                    "brake_status": True,
                    "brake_pressure_psi": 250.0,
                    "steering_angle_deg": 1.5,
                    "wheel_speed_rpm": 620.0,
                },
                {
                    "timestamp": "2026-08-05T12:00:00Z",
                    "speed_kmh": 40.0,
                    "brake_status": True,
                    "brake_pressure_psi": 300.0,
                    "steering_angle_deg": 0.0,
                    "wheel_speed_rpm": 354.0,
                },
            ],
        }

    with open(payload_path, "r", encoding="utf-8") as f:
        return json.load(f)


@pytest.fixture(scope="module")
def audit_db_container():
    """
    Testcontainers fixture template demonstrating how to spin up isolated containerized services
    (e.g., mock audit database or validation engine) during safety test execution.
    """
    # Uses alpine container as lightweight testcontainer demo
    container = DockerContainer("alpine:latest").with_command("sleep 300")
    try:
        container.start()
        yield container
    finally:
        container.stop()


def test_payload_integrity(blackbox_payload):
    """
    Audit 1: Verify presence of all required metadata fields and schema structure.
    """
    required_fields = ["event_id", "timestamp", "trigger_reason", "buffer_duration_seconds", "frame_count", "telemetry"]
    for field in required_fields:
        assert field in blackbox_payload, f"Missing required field '{field}' in payload metadata"

    telemetry = blackbox_payload["telemetry"]
    assert isinstance(telemetry, list), "Telemetry field must be an array of frames"
    assert len(telemetry) == blackbox_payload["frame_count"], "frame_count mismatch with telemetry array length"


def test_frame_chronology(blackbox_payload):
    """
    Audit 2: Ensure timestamps in telemetry frames are monotonically increasing.
    """
    telemetry = blackbox_payload["telemetry"]
    if len(telemetry) < 2:
        pytest.skip("Not enough frames to verify chronology")

    timestamps = []
    for frame in telemetry:
        ts_str = frame["timestamp"].replace("Z", "+00:00")
        timestamps.append(datetime.fromisoformat(ts_str))

    for i in range(len(timestamps) - 1):
        assert timestamps[i] <= timestamps[i + 1], f"Timestamp inversion detected at index {i}"


def test_brake_system_response(blackbox_payload):
    """
    Audit 3: Verify vehicle deceleration response when brake status is engaged.
    """
    telemetry = blackbox_payload["telemetry"]

    for i in range(len(telemetry) - 1):
        curr = telemetry[i]
        nxt = telemetry[i + 1]

        # If brake is engaged with significant pressure, speed should not spike
        if curr["brake_status"] and curr["brake_pressure_psi"] > 150.0:
            speed_delta = nxt["speed_kmh"] - curr["speed_kmh"]
            assert speed_delta <= 5.0, (
                f"Unsafe acceleration ({speed_delta:.2f} km/h) detected while braking "
                f"at timestamp {curr['timestamp']}"
            )


def test_physical_limits(blackbox_payload):
    """
    Audit 4: Enforce physical boundaries on speed and steering inputs.
    """
    telemetry = blackbox_payload["telemetry"]

    MAX_SPEED_KMH = 160.0  # Max safe velocity
    MAX_STEERING_DEG = 45.0  # Max steering lock

    for frame in telemetry:
        speed = frame["speed_kmh"]
        steering = frame["steering_angle_deg"]

        assert 0.0 <= speed <= MAX_SPEED_KMH, f"Speed {speed} km/h out of safe envelope [0, {MAX_SPEED_KMH}]"
        assert -MAX_STEERING_DEG <= steering <= MAX_STEERING_DEG, (
            f"Steering angle {steering}° exceeds mechanical lock limit [-{MAX_STEERING_DEG}, {MAX_STEERING_DEG}]"
        )
