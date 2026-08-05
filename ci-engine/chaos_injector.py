#!/usr/bin/env python3
"""
Chaos Injector Helper Module for Cyber-Physical Edge QA Testing.

Uses paho-mqtt to asynchronously inject environmental faults (e.g. thermal spikes,
hardware fatal errors) and trigger edge cases during automated Pytest execution.
"""

import json
import logging
import os
import time
from typing import Dict, Any, Optional
import paho.mqtt.client as mqtt

logger = logging.getLogger("ChaosInjector")


class ChaosInjector:
    """
    Helper class for injecting hardware chaos payloads into the MQTT broker.
    Supports context manager pattern ('with ChaosInjector() as injector:').
    """

    def __init__(
        self,
        host: Optional[str] = None,
        port: Optional[int] = None,
        client_id: str = "chaos-injector-client",
    ):
        self.host = host or os.getenv("MQTT_BROKER_HOST", os.getenv("MQTT_HOST", "mosquitto"))
        self.port = port or int(os.getenv("MQTT_PORT", "1883"))
        self.client_id = client_id
        self.client = mqtt.Client(client_id=self.client_id, clean_session=True)
        self._is_connected = False

    def connect(self, timeout: float = 10.0) -> "ChaosInjector":
        """
        Establishes connection to the MQTT broker.
        """
        if self._is_connected:
            return self

        logger.info(f"Connecting ChaosInjector to MQTT broker at {self.host}:{self.port}...")
        start_time = time.time()
        while time.time() - start_time < timeout:
            try:
                self.client.connect(self.host, self.port, keepalive=60)
                self.client.loop_start()
                self._is_connected = True
                logger.info("ChaosInjector connected successfully.")
                return self
            except Exception as e:
                logger.warning(f"Connection attempt failed: {e}. Retrying...")
                time.sleep(0.5)

        raise ConnectionError(f"Could not connect ChaosInjector to {self.host}:{self.port} within {timeout}s")

    def disconnect(self):
        """
        Disconnects from the MQTT broker.
        """
        if self._is_connected:
            self.client.loop_stop()
            self.client.disconnect()
            self._is_connected = False
            logger.info("ChaosInjector disconnected.")

    def __enter__(self) -> "ChaosInjector":
        self.connect()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.disconnect()

    def inject_fault(self, payload: Dict[str, Any], topic: str = "edge/faults", qos: int = 1):
        """
        Asynchronously publishes an arbitrary hardware fault payload to the specified topic.
        """
        if not self._is_connected:
            self.connect()

        payload_bytes = json.dumps(payload).encode("utf-8")
        logger.info(f"💥 Injecting Chaos Fault to '{topic}': {payload}")
        info = self.client.publish(topic, payload_bytes, qos=qos)
        info.wait_for_publish(timeout=3.0)

    def inject_thermal_spike(self, temperature: float = 85.0, topic: str = "edge/faults"):
        """
        Convenience method to simulate a sudden thermal heat spike.
        Example payload: {"sensor": "temperature", "value": 85}
        """
        payload = {"sensor": "temperature", "value": temperature}
        self.inject_fault(payload, topic=topic)

    def inject_fatal_error(self, event_type: str = "fatal_error", topic: str = "edge/faults"):
        """
        Convenience method to simulate a fatal hardware / system error.
        Example payload: {"event": "fatal_error"}
        """
        payload = {"event": event_type}
        self.inject_fault(payload, topic=topic)

    def publish_command(self, command_payload: Dict[str, Any], topic: str = "edge/ota/command"):
        """
        Publishes a control or OTA update command payload to the edge device.
        Example payload: {"command": "update", "slot": "B"}
        """
        if not self._is_connected:
            self.connect()

        payload_bytes = json.dumps(command_payload).encode("utf-8")
        logger.info(f"📡 Publishing Command to '{topic}': {command_payload}")
        info = self.client.publish(topic, payload_bytes, qos=1)
        info.wait_for_publish(timeout=3.0)
