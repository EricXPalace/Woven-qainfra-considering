"""
Pytest Configuration, Readiness Checks & Failure Hook Integration for AI Triage Agent.

Features:
  1. Container Readiness Check (wait_for_mqtt_broker): Session-scoped autouse fixture
     that polls the target MQTT broker container port before any tests run.
  2. Rerun & Retry Integration: Works with pytest-rerunfailures.
  3. AI Triage Hook: Intercepts test failures ONLY when the final retry attempt fails,
     extracting traceback + telemetry context and generating Pydantic-validated RCA reports.
"""

import json
import logging
import os
import socket
import time
import pytest
from ai_triage_agent import AITriageAgent

logger = logging.getLogger("Pytest-CI-Config")


@pytest.fixture(scope="session", autouse=True)
def wait_for_mqtt_broker():
    """
    Session-scoped autouse fixture ensuring the MQTT broker container is ready
    and accepting TCP connections before any Pytest test cases execute.
    """
    host = os.getenv("MQTT_BROKER_HOST", os.getenv("MQTT_HOST", "mosquitto"))
    port = int(os.getenv("MQTT_PORT", "1883"))
    timeout = float(os.getenv("CONTAINER_WAIT_TIMEOUT", "30.0"))

    logger.info(f"⏳ Waiting for MQTT broker container ({host}:{port}) to become ready (Timeout: {timeout}s)...")
    start_time = time.time()
    connected = False

    while time.time() - start_time < timeout:
        try:
            with socket.create_connection((host, port), timeout=1.0):
                connected = True
                logger.info(f"✅ Connection established to MQTT broker at {host}:{port}!")
                break
        except (socket.error, OSError):
            time.sleep(0.5)

    if not connected:
        logger.warning(
            f"⚠️ Could not reach MQTT broker at {host}:{port} within {timeout}s. "
            f"Tests will proceed with fallback/mock fixtures."
        )


@pytest.hookimpl(tryfirst=True, hookwrapper=True)
def pytest_runtest_makereport(item, call):
    """
    Pytest hook executed for each test phase (setup, call, teardown).
    Intercepts failed tests on their FINAL attempt to trigger AI Triage.
    """
    outcome = yield
    report = outcome.get_result()

    # Trigger AI Triage ONLY when a test fails during execution ('call' phase)
    if report.when == "call" and report.failed:
        # Check if pytest-rerunfailures is managing retries for this test
        execution_count = getattr(item, "execution_count", 1)
        reruns_limit = getattr(item, "reruns", 0)
        has_more_retries = hasattr(report, "rerun") and report.rerun > 0

        # If more retries remain, skip triage until the final attempt fails
        if has_more_retries or (reruns_limit > 0 and execution_count < reruns_limit + 1):
            logger.info(
                f"🔄 Test '{item.name}' failed attempt {execution_count}/{reruns_limit + 1}. "
                f"Retrying... (AI Triage deferred until final attempt)"
            )
            return

        logger.warning(f"🚨 Final Test Failure Reached in '{item.name}'! Triggering AI Triage Agent...")

        # 1. Extract traceback text from test failure
        traceback_text = str(report.longrepr) if report.longrepr else "No traceback captured"

        # 2. Retrieve blackbox telemetry payload from test fixture or payload file
        telemetry_payload = {}
        if "blackbox_payload" in item.fixturenames and hasattr(item, "funcargs"):
            telemetry_payload = item.funcargs.get("blackbox_payload", {})

        if not telemetry_payload:
            payload_path = os.getenv("BLACKBOX_PAYLOAD_PATH", "received_payload.json")
            if os.path.exists(payload_path):
                try:
                    with open(payload_path, "r", encoding="utf-8") as f:
                        telemetry_payload = json.load(f)
                except Exception:
                    pass

        if not telemetry_payload:
            telemetry_payload = {
                "event_id": f"fallback-{item.name}",
                "trigger_reason": "PYTEST_FINAL_FAILURE_REACHED",
                "telemetry": [{"timestamp": "2026-08-05T20:00:00Z", "speed_kmh": 0.0}],
            }

        # 3. Invoke AITriageAgent to generate Pydantic-validated RCA report
        try:
            agent = AITriageAgent(mock_mode=True)
            triage_report = agent.analyze_failure(traceback_text, telemetry_payload)

            # 4. Save AI Triage Report to disk as JSON artifact
            report_filename = f"triage_report_{item.name}.json"
            output_dir = os.getenv("TRIAGE_OUTPUT_DIR", ".")
            filepath = os.path.join(output_dir, report_filename)

            with open(filepath, "w", encoding="utf-8") as f:
                f.write(triage_report.model_dump_json(indent=2))

            logger.info(f"📄 AI Triage Report saved to '{filepath}'")

            # Attach triage summary to Pytest report output
            report.sections.append((
                "AI Triage RCA Summary",
                f"Category: {triage_report.failure_category.value}\n"
                f"Confidence: {triage_report.confidence_score * 100:.1f}%\n"
                f"Summary: {triage_report.summary}\n"
                f"Suggested Fix: {triage_report.suggested_fix}"
            ))

        except Exception as e:
            logger.error(f"Failed to execute AI Triage hook for '{item.name}': {e}", exc_info=True)
