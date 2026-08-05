#!/usr/bin/env python3
"""
Mock Telemetry Generator for Cyber-Physical System (Autonomous Vehicle Edge Node).

Continuously generates simulated vehicle sensor telemetry (speed, brake status, brake pressure,
steering angle, wheel speed) and streams it to the Edge Node REST endpoint via HTTP POST.
Can optionally send a Kill Switch trigger request to test blackbox dump packaging.
"""

import argparse
import math
import random
import sys
import time
from datetime import datetime, timezone
import requests


def generate_telemetry_frame(t_step: float) -> dict:
    """
    Generates realistic dynamic vehicle telemetry parameters.
    """
    # Base speed with sine wave variation + small noise
    base_speed = 60.0 + 25.0 * math.sin(t_step * 0.1)
    noise = random.uniform(-1.5, 1.5)
    speed_kmh = max(0.0, round(base_speed + noise, 2))

    # Periodic braking simulation
    brake_status = (int(t_step) % 15) in [12, 13, 14]
    brake_pressure_psi = round(random.uniform(150.0, 350.0), 2) if brake_status else 0.0

    # Steering angle oscillation
    steering_angle_deg = round(15.0 * math.sin(t_step * 0.05) + random.uniform(-0.5, 0.5), 2)

    # Wheel speed RPM roughly proportional to speed (assume 0.3m wheel radius)
    wheel_speed_rpm = round((speed_kmh * 1000 / 3600) / (2 * math.pi * 0.3) * 60, 2)

    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "speed_kmh": speed_kmh,
        "brake_status": brake_status,
        "brake_pressure_psi": brake_pressure_psi,
        "steering_angle_deg": steering_angle_deg,
        "wheel_speed_rpm": wheel_speed_rpm,
    }


def stream_telemetry(target_url: str, rate_hz: float, duration_sec: float, trigger_kill_after: float):
    endpoint = f"{target_url.rstrip('/')}/telemetry"
    kill_endpoint = f"{target_url.rstrip('/')}/kill-switch"

    interval = 1.0 / rate_hz
    start_time = time.time()
    t_step = 0.0
    sent_count = 0

    print(f"🚀 Starting Telemetry Stream -> {endpoint}")
    print(f"   Rate: {rate_hz} Hz ({interval:.3f}s interval) | Duration: {duration_sec}s")
    if trigger_kill_after > 0:
        print(f"   ⚠️ Will trigger Kill Switch after {trigger_kill_after} seconds")

    kill_triggered = False

    try:
        while True:
            elapsed = time.time() - start_time
            if duration_sec > 0 and elapsed >= duration_sec:
                print(f"⏱️ Target duration of {duration_sec}s reached.")
                break

            # Trigger kill switch if configured
            if trigger_kill_after > 0 and elapsed >= trigger_kill_after and not kill_triggered:
                print(f"\n🚨 TRIGGERING KILL SWITCH via POST {kill_endpoint}...")
                try:
                    res = requests.post(
                        kill_endpoint,
                        json={"reason": "MOCK_GENERATOR_KILL_SWITCH_TEST"},
                        timeout=5,
                    )
                    print(f"Response ({res.status_code}): {res.json()}")
                except Exception as e:
                    print(f"❌ Error triggering kill switch: {e}", file=sys.stderr)
                kill_triggered = True

            frame = generate_telemetry_frame(t_step)
            try:
                res = requests.post(endpoint, json=frame, timeout=2)
                if res.status_code == 200:
                    sent_count += 1
                    buf_size = res.json().get("buffer_size", "?")
                    print(
                        f"\r[{sent_count}] Streamed frame: Speed={frame['speed_kmh']} km/h, "
                        f"Brake={frame['brake_status']}, Steering={frame['steering_angle_deg']}° "
                        f"(Edge Buffer Size: {buf_size})",
                        end="",
                        flush=True,
                    )
                else:
                    print(f"\n⚠️ HTTP {res.status_code}: {res.text}")
            except requests.exceptions.RequestException as e:
                print(f"\n❌ Connection error: {e}")

            t_step += interval
            time.sleep(interval)

    except KeyboardInterrupt:
        print("\n🛑 Telemetry generator stopped by user.")

    print(f"\nFinished. Total frames sent: {sent_count}")


def main():
    parser = argparse.ArgumentParser(description="Mock Telemetry Generator for Autonomous Vehicle Edge Node")
    parser.add_argument(
        "--url",
        default="http://localhost:8080",
        help="Target Edge Node base URL (default: http://localhost:8080)",
    )
    parser.add_argument(
        "--rate",
        type=float,
        default=5.0,
        help="Stream frequency in Hz (default: 5.0)",
    )
    parser.add_argument(
        "--duration",
        type=float,
        default=0.0,
        help="Run duration in seconds (0 = run indefinitely, default: 0)",
    )
    parser.add_argument(
        "--trigger-kill",
        type=float,
        default=0.0,
        help="Trigger kill switch after N seconds of streaming (0 = disabled)",
    )

    args = parser.parse_args()
    stream_telemetry(args.url, args.rate, args.duration, args.trigger_kill)


if __name__ == "__main__":
    main()
