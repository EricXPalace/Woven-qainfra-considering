"""
Pytest Configuration & Failure Hook Integration for AI Triage Agent.

Hooks into Pytest's test report generation (`pytest_runtest_makereport`).
If a test fails, extracts the failure traceback and blackbox telemetry context,
runs AITriageAgent to perform automated Root Cause Analysis, and saves the
Pydantic-validated JSON triage report.
"""

import json
import logging
import os
import pytest
from ai_triage_agent import AITriageAgent

logger = logging.getLogger("Pytest-AITriage-Hook")


@pytest.hookimpl(tryfirst=True, hookwrapper=True)
def pytest_runtest_makereport(item, call):
    """
    Pytest hook executed for each test phase (setup, call, teardown).
    Intercepts failed tests during the 'call' execution phase to trigger AI Triage.
    """
    # Execute all other hooks to obtain the report object
    outcome = yield
    report = outcome.get_result()

    # Trigger AI Triage ONLY when a test fails during execution ('call' phase)
    if report.when == "call" and report.failed:
        logger.warning(f"🚨 Test Failure Detected in '{item.name}'! Triggering AI Triage Agent...")

        # 1. Extract traceback text from test failure
        traceback_text = str(report.longrepr) if report.longrepr else "No traceback captured"

        # 2. Retrieve blackbox telemetry payload from test fixture or payload file
        telemetry_payload = {}

        # Check if blackbox_payload fixture is available on the test item
        if "blackbox_payload" in item.fixturenames and hasattr(item, "funcargs"):
            telemetry_payload = item.funcargs.get("blackbox_payload", {})

        # Fallback to reading received_payload.json if present
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
                "trigger_reason": "PYTEST_FAILURE_FALLBACK",
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
