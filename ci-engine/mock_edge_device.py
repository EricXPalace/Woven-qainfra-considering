#!/usr/bin/env python3
"""
Mock Edge Device State Machine for Chaos & Hardware Constraint Testing.

Maintains hardware state:
  - current_slot: 'A' or 'B'
  - cpu_freq: 'Normal' or 'Throttled'

Subscribes to MQTT topics ('edge/faults', 'edge/ota/command') and reacts to:
  1. Thermal Spikes (temperature >= 80°C) -> sets cpu_freq='Throttled' & publishes {"status": "throttling_active"}
  2. Failed OTA Updates (command='update' + fatal_error payload) -> rolls back & publishes {"fallback_to_slot_a": true}
"""

import json
import logging
import os
import threading
import time
from typing import Optional
import paho.mqtt.client as mqtt

logger = logging.getLogger("MockEdgeDevice")


class MockEdgeDevice:
    """
    Simulated Edge Device maintaining firmware slot and CPU frequency state over MQTT.
    """

    def __init__(
        self,
        host: Optional[str] = None,
        port: Optional[int] = None,
        client_id: str = "mock-edge-device",
    ):
        self.host = host or os.getenv("MQTT_BROKER_HOST", os.getenv("MQTT_HOST", "mosquitto"))
        self.port = port or int(os.getenv("MQTT_PORT", "1883"))
        self.client_id = client_id

        # Internal Device Hardware State
        self.current_slot: str = "A"
        self.cpu_freq: str = "Normal"
        self.pending_ota_slot: Optional[str] = None

        self.client = mqtt.Client(client_id=self.client_id, clean_session=True)
        self.client.on_connect = self._on_connect
        self.client.on_message = self._on_message

        self._lock = threading.Lock()
        self._is_running = False

    def _on_connect(self, client, userdata, flags, rc):
        if rc == 0:
            logger.info(f"MockEdgeDevice connected to MQTT at {self.host}:{self.port}")
            client.subscribe("edge/faults", qos=1)
            client.subscribe("edge/ota/command", qos=1)
            logger.info("Subscribed to 'edge/faults' and 'edge/ota/command'")
        else:
            logger.error(f"MockEdgeDevice connection failed with code {rc}")

    def _on_message(self, client, userdata, msg):
        try:
            payload = json.loads(msg.payload.decode("utf-8"))
            topic = msg.topic
            logger.info(f"MockEdgeDevice received on '{topic}': {payload}")

            if topic == "edge/faults":
                self._handle_fault(payload)
            elif topic == "edge/ota/command":
                self._handle_ota_command(payload)

        except Exception as e:
            logger.error(f"Error handling message on '{msg.topic}': {e}", exc_info=True)

    def _handle_fault(self, payload: dict):
        with self._lock:
            # 1. Thermal Throttling Detection
            if payload.get("sensor") == "temperature" and payload.get("value", 0) >= 80:
                logger.warning(f"🔥 Thermal Spike Detected ({payload.get('value')}°C)! Throttling CPU...")
                self.cpu_freq = "Throttled"
                response = {"status": "throttling_active", "cpu_freq": self.cpu_freq}
                self.client.publish("edge/status", json.dumps(response), qos=1)

            # 2. Fatal Error Handling during OTA
            if payload.get("event") == "fatal_error":
                logger.error("🚨 Fatal Error Payload Received!")
                if self.pending_ota_slot is not None or self.current_slot != "A":
                    logger.warning("OTA update failed due to fatal error! Rolling back to Slot A...")
                    self.current_slot = "A"
                    self.pending_ota_slot = None
                    response = {"fallback_to_slot_a": True, "current_slot": self.current_slot}
                    self.client.publish("edge/status", json.dumps(response), qos=1)

    def _handle_ota_command(self, payload: dict):
        with self._lock:
            if payload.get("command") == "update":
                target_slot = payload.get("slot", "B")
                logger.info(f"Received OTA update command for target slot '{target_slot}'")
                self.pending_ota_slot = target_slot

                # If fatal error was already triggered/present, handle rollback immediately
                if payload.get("fatal_error", False):
                    logger.warning("OTA command includes fatal error signal. Triggering rollback...")
                    self.current_slot = "A"
                    self.pending_ota_slot = None
                    response = {"fallback_to_slot_a": True, "current_slot": self.current_slot}
                    self.client.publish("edge/status", json.dumps(response), qos=1)
                else:
                    # In normal operation without fatal error, slot updates after delay
                    def _complete_update():
                        time.sleep(0.5)
                        with self._lock:
                            if self.pending_ota_slot == target_slot:
                                self.current_slot = target_slot
                                self.pending_ota_slot = None
                                response = {"status": "update_success", "current_slot": self.current_slot}
                                self.client.publish("edge/status", json.dumps(response), qos=1)

                    threading.Thread(target=_complete_update, daemon=True).start()

    def start(self):
        """
        Starts the device MQTT client loop in background thread.
        """
        if not self._is_running:
            self.client.connect(self.host, self.port, keepalive=60)
            self.client.loop_start()
            self._is_running = True
            logger.info("MockEdgeDevice started.")

    def stop(self):
        """
        Stops the device MQTT client loop.
        """
        if self._is_running:
            self.client.loop_stop()
            self.client.disconnect()
            self._is_running = False
            logger.info("MockEdgeDevice stopped.")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    device = MockEdgeDevice()
    device.start()
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        device.stop()
