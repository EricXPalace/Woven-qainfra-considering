#!/usr/bin/env python3
"""
AI-Driven Root Cause Analysis (RCA) & Triage Agent for Cyber-Physical Systems.

Triggered upon Pytest test failures. Formats failed test tracebacks and black-box telemetry dumps
into a structured LLM prompt, queries a local LLM API (e.g., Ollama / Gemma), and enforces
strict JSON schema validation via Pydantic v2.
"""

import json
import logging
import os
import sys
from enum import Enum
from typing import Dict, Any, Optional
from pydantic import BaseModel, Field, ValidationError
import requests

logger = logging.getLogger("AITriageAgent")


class FailureCategory(str, Enum):
    HARDWARE_FAULT = "Hardware Fault"
    THERMAL_THROTTLING_TIMEOUT = "Thermal Throttling Timeout"
    NETWORK_DROP = "Network Drop"
    SAFETY_VELOCITY_VIOLATION = "Safety Velocity Violation"
    BRAKE_LATENCY_EXCEEDED = "Brake Latency Exceeded"
    OTA_ROLLBACK_FAILURE = "OTA Rollback Failure"
    UNKNOWN_ANOMALY = "Unknown Anomaly"


class AITriageReport(BaseModel):
    """
    Pydantic v2 model defining the strict JSON output schema expected from the LLM.
    """

    failure_category: FailureCategory = Field(
        ...,
        description="Standardized category of the detected cyber-physical failure",
    )
    confidence_score: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Confidence score of the AI triage diagnosis (between 0.0 and 1.0)",
    )
    summary: str = Field(
        ...,
        description="Brief high-level summary of the root cause diagnosis",
    )
    root_cause_analysis: str = Field(
        ...,
        description="Detailed technical breakdown explaining why the failure occurred",
    )
    suggested_fix: str = Field(
        ...,
        description="Actionable fix or remediation steps for DevOps and QA infrastructure engineers",
    )
    telemetry_anomaly_timestamp: Optional[str] = Field(
        None,
        description="Timestamp (ISO-8601) within the 60s buffer where anomaly was first observed",
    )


class AITriageAgent:
    """
    Smart QA Agent for performing automated AI Root Cause Analysis on test failures.
    """

    def __init__(
        self,
        endpoint: Optional[str] = None,
        model_name: str = "gemma2",
        mock_mode: bool = True,
    ):
        self.endpoint = endpoint or os.getenv("LLM_ENDPOINT", "http://localhost:11434/api/generate")
        self.model_name = model_name
        self.mock_mode = mock_mode

    def format_prompt(self, traceback_text: str, telemetry_payload: Dict[str, Any]) -> str:
        """
        Formats Pytest failure traceback and blackbox telemetry JSON into a structured prompt.
        """
        schema_json = json.dumps(AITriageReport.model_json_schema(), indent=2)
        telemetry_snippet = json.dumps(telemetry_payload, indent=2)

        prompt = f"""
You are an expert Cyber-Physical System QA & DevOps Root Cause Analysis (RCA) Engineer.

A automated safety test suite has FAILED during execution. Analyze the provided Pytest traceback and the blackbox telemetry payload to diagnose the root cause.

=== PYTEST FAILURE TRACEBACK ===
{traceback_text}

=== BLACKBOX TELEMETRY PAYLOAD ===
{telemetry_snippet}

=== REQUIRED OUTPUT JSON SCHEMA ===
Your response MUST be valid JSON adhering strictly to this JSON Schema:
{schema_json}

Provide your analysis in JSON format only.
""".strip()
        return prompt

    def _mock_llm_inference(self, traceback_text: str, telemetry_payload: Dict[str, Any]) -> Dict[str, Any]:
        """
        Simulates local LLM (Ollama/Gemma) inference output based on failure context,
        returning structured JSON data adhering to AITriageReport schema.
        """
        tb_lower = traceback_text.lower()
        telemetry_frames = telemetry_payload.get("telemetry", [])

        # Default fallback timestamp
        anomaly_ts = telemetry_frames[-1].get("timestamp") if telemetry_frames else "2026-08-05T12:00:00Z"

        if "throttling" in tb_lower or "thermal" in tb_lower or "cpu_freq" in tb_lower:
            return {
                "failure_category": FailureCategory.THERMAL_THROTTLING_TIMEOUT.value,
                "confidence_score": 0.95,
                "summary": "Mock device CPU frequency failed to throttle within 3.0s threshold following heat spike.",
                "root_cause_analysis": (
                    "The mock hardware agent received an 85°C thermal fault, but the event loop or state machine "
                    "delayed publishing the 'throttling_active' status message to MQTT topic 'edge/status', exceeding the 3.0s timeout."
                ),
                "suggested_fix": (
                    "Inspect thermal monitoring thread scheduling and ensure MQTT publish callbacks are non-blocking. "
                    "Increase thermal polling frequency or adjust test timeout threshold."
                ),
                "telemetry_anomaly_timestamp": anomaly_ts,
            }
        elif "brake" in tb_lower or "deceleration" in tb_lower:
            return {
                "failure_category": FailureCategory.BRAKE_LATENCY_EXCEEDED.value,
                "confidence_score": 0.92,
                "summary": "Vehicle speed did not decrease after high brake pressure actuation.",
                "root_cause_analysis": (
                    "Brake pressure exceeded 150 PSI at frame 12, but wheel speed RPM remained elevated. "
                    "Possible physical brake actuator fault or sensor calibration skew."
                ),
                "suggested_fix": "Recalibrate brake pressure sensor mapping and verify brake actuator response curve.",
                "telemetry_anomaly_timestamp": anomaly_ts,
            }
        elif "rollback" in tb_lower or "slot" in tb_lower or "ota" in tb_lower:
            return {
                "failure_category": FailureCategory.OTA_ROLLBACK_FAILURE.value,
                "confidence_score": 0.98,
                "summary": "OTA update encountered fatal error but device failed to fallback to Slot A.",
                "root_cause_analysis": (
                    "The device received an OTA update command to Slot B simultaneously with a fatal error fault, "
                    "but state machine pending_ota_slot lock prevented slot rollback completion."
                ),
                "suggested_fix": (
                    "Ensure fatal error interrupt handler overrides in-flight OTA state transactions immediately "
                    "and forces partition table fallback to Slot A."
                ),
                "telemetry_anomaly_timestamp": anomaly_ts,
            }
        else:
            return {
                "failure_category": FailureCategory.HARDWARE_FAULT.value,
                "confidence_score": 0.85,
                "summary": "Unspecified cyber-physical safety boundary violation in telemetry stream.",
                "root_cause_analysis": f"Pytest assertion failure observed: {traceback_text[:200]}...",
                "suggested_fix": "Review edge telemetry buffer frames and verify sensor threshold parameters.",
                "telemetry_anomaly_timestamp": anomaly_ts,
            }

    def analyze_failure(self, traceback_text: str, telemetry_payload: Dict[str, Any]) -> AITriageReport:
        """
        Main entry point: Formats prompt, queries LLM (or mock API), and validates response against Pydantic schema.
        """
        prompt = self.format_prompt(traceback_text, telemetry_payload)
        logger.info("Executing AI Triage Analysis on failed test...")

        if self.mock_mode:
            logger.info("🤖 Mock Mode enabled: Generating simulated local LLM (Ollama/Gemma) response...")
            raw_dict = self._mock_llm_inference(traceback_text, telemetry_payload)
        else:
            try:
                logger.info(f"Querying local LLM endpoint at '{self.endpoint}'...")
                response = requests.post(
                    self.endpoint,
                    json={
                        "model": self.model_name,
                        "prompt": prompt,
                        "stream": False,
                        "format": "json",
                    },
                    timeout=15,
                )
                response.raise_for_status()
                res_data = response.json()
                raw_dict = json.loads(res_data.get("response", "{}"))
            except Exception as e:
                logger.warning(f"Local LLM API call failed ({e}). Falling back to mock LLM diagnosis...")
                raw_dict = self._mock_llm_inference(traceback_text, telemetry_payload)

        # Enforce strict Pydantic v2 validation
        try:
            report = AITriageReport.model_validate(raw_dict)
            logger.info(
                f"✅ AI Triage Completed! Category: '{report.failure_category.value}' "
                f"| Confidence: {report.confidence_score * 100:.1f}%"
            )
            return report
        except ValidationError as val_err:
            logger.error(f"❌ LLM output failed Pydantic schema validation: {val_err}")
            raise val_err


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)

    sample_tb = "AssertionError: Device failed to publish throttling status within 3 seconds deadline"
    sample_telemetry = {
        "event_id": "demo-event-123",
        "telemetry": [{"timestamp": "2026-08-05T20:00:00Z", "speed_kmh": 85.0}],
    }

    agent = AITriageAgent(mock_mode=True)
    report = agent.analyze_failure(sample_tb, sample_telemetry)
    print("\n--- GENERATED AI TRIAGE REPORT (Pydantic Validated) ---")
    print(report.model_dump_json(indent=2))
