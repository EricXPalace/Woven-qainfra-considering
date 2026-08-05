#!/usr/bin/env python3
"""
Dynamic Test Sharded Orchestrator for Cyber-Physical Telemetry & Crash Logs.

Scans a directory of incoming telemetry JSON files, calculates cumulative data volume,
and dynamically partitions test files across N parallel test shards (e.g., 10MB per shard).
Outputs a JSON configuration mapping test files to specific shard IDs.
"""

import argparse
import json
import math
import os
import sys
from pathlib import Path
from typing import Dict, List, Any, Optional


class TelemetrySharder:
    """
    Orchestrator for analyzing telemetry log volume and calculating balanced test shards.
    """

    def __init__(self, target_shard_size_mb: float = 10.0):
        self.target_shard_bytes: float = target_shard_size_mb * 1024 * 1024
        self.target_shard_size_mb: float = target_shard_size_mb

    def get_telemetry_files(self, log_dir: str) -> List[Dict[str, Any]]:
        """
        Scans directory for .json telemetry log files and retrieves file sizes in bytes.
        """
        directory = Path(log_dir)
        if not directory.exists() or not directory.is_dir():
            raise FileNotFoundError(f"Directory '{log_dir}' does not exist or is not a valid directory.")

        files_info: List[Dict[str, Any]] = []
        for file_path in directory.glob("*.json"):
            size_bytes = file_path.stat().st_size
            files_info.append({
                "file_path": str(file_path.resolve()),
                "file_name": file_path.name,
                "size_bytes": size_bytes,
                "size_mb": round(size_bytes / (1024 * 1024), 4),
            })

        # Sort files descending by size for optimal bin-packing allocation
        files_info.sort(key=lambda x: x["size_bytes"], reverse=True)
        return files_info

    def calculate_shards(self, log_dir: str) -> Dict[str, Any]:
        """
        Calculates required shard count and maps telemetry log files into balanced shards.
        """
        files_info = self.get_telemetry_files(log_dir)
        total_size_bytes = sum(f["size_bytes"] for f in files_info)
        total_size_mb = round(total_size_bytes / (1024 * 1024), 4)

        if not files_info:
            return {
                "total_files": 0,
                "total_size_bytes": 0,
                "total_size_mb": 0.0,
                "target_shard_size_mb": self.target_shard_size_mb,
                "num_shards": 0,
                "shards": {},
            }

        # Calculate number of shards (minimum 1 shard)
        num_shards = max(1, math.ceil(total_size_bytes / self.target_shard_bytes))

        # Bin-packing distribution into shards
        shards: Dict[str, List[Dict[str, Any]]] = {f"shard_{i}": [] for i in range(num_shards)}
        shard_sizes: Dict[str, int] = {f"shard_{i}": 0 for i in range(num_shards)}

        for file_item in files_info:
            # Pick the shard currently having the least total byte size
            min_shard_id = min(shard_sizes, key=lambda k: shard_sizes[k])
            shards[min_shard_id].append(file_item)
            shard_sizes[min_shard_id] += file_item["size_bytes"]

        # Format output payload
        shard_summary: Dict[str, Any] = {}
        for shard_id, item_list in shards.items():
            shard_bytes = shard_sizes[shard_id]
            shard_summary[shard_id] = {
                "file_count": len(item_list),
                "total_size_bytes": shard_bytes,
                "total_size_mb": round(shard_bytes / (1024 * 1024), 4),
                "files": [item["file_name"] for item in item_list],
                "file_paths": [item["file_path"] for item in item_list],
            }

        return {
            "total_files": len(files_info),
            "total_size_bytes": total_size_bytes,
            "total_size_mb": total_size_mb,
            "target_shard_size_mb": self.target_shard_size_mb,
            "num_shards": num_shards,
            "shards": shard_summary,
        }

    def save_shard_config(self, log_dir: str, output_path: str) -> Dict[str, Any]:
        """
        Executes shard calculation and writes JSON mapping configuration to file.
        """
        shard_config = self.calculate_shards(log_dir)
        output_file = Path(output_path)
        output_file.parent.mkdir(parents=True, exist_ok=True)

        with open(output_file, "w", encoding="utf-8") as f:
            json.dump(shard_config, f, indent=2)

        print(f"✅ Shard configuration saved to '{output_file.resolve()}'")
        print(f"   Total Files: {shard_config['total_files']} | Total Size: {shard_config['total_size_mb']} MB")
        print(f"   Calculated Shards: {shard_config['num_shards']} (Target: {self.target_shard_size_mb} MB/shard)")
        return shard_config


def main():
    parser = argparse.ArgumentParser(description="Dynamic Telemetry Test Sharder")
    parser.add_argument(
        "--dir",
        required=True,
        help="Path to directory containing telemetry JSON crash log files",
    )
    parser.add_argument(
        "--target-mb",
        type=float,
        default=10.0,
        help="Target size per shard in MB (default: 10.0 MB)",
    )
    parser.add_argument(
        "--out",
        default="shard_config.json",
        help="Output path for generated shard configuration JSON (default: shard_config.json)",
    )

    args = parser.parse_args()

    try:
        sharder = TelemetrySharder(target_shard_size_mb=args.target_mb)
        sharder.save_shard_config(args.dir, args.out)
    except Exception as e:
        print(f"❌ Error performing test sharding: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
