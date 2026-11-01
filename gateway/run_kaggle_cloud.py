#!/usr/bin/env python3
"""Automated Kaggle Cloud GPU Fleet Orchestrator for InferaCap.

Orchestrates pushing, tracking, and registering live Kaggle GPU workers
into the InferaCap multi-region federation.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import re
import subprocess
import sys
import time
import urllib.request
import urllib.error
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] Kaggle-Orchestrator: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("inferacap.kaggle_cloud")

KAGGLE_BIN = "/Users/bhaskarpandey/.local/bin/kaggle"
if not os.path.exists(KAGGLE_BIN):
    KAGGLE_BIN = "kaggle"


def check_kaggle_cli() -> bool:
    try:
        res = subprocess.run([KAGGLE_BIN, "--version"], capture_output=True, text=True)
        return res.returncode == 0
    except Exception:
        return False


def get_kernel_id(gateway_dir: Path) -> str:
    meta_file = gateway_dir / "kernel-metadata.json"
    if meta_file.exists():
        with open(meta_file, "r") as f:
            data = json.load(f)
            return data.get("id", "bhaskarpandeymth/inferacap-cloud-gpu-worker")
    return "bhaskarpandeymth/inferacap-cloud-gpu-worker"


def push_kernel(gateway_dir: Path) -> bool:
    logger.info(f"Pushing Kaggle GPU Worker from {gateway_dir}...")
    res = subprocess.run(
        [KAGGLE_BIN, "kernels", "push", "-p", str(gateway_dir)],
        capture_output=True,
        text=True,
    )
    if res.returncode == 0:
        logger.info(f"✅ Push Successful: {res.stdout.strip()}")
        return True
    else:
        logger.error(f"❌ Push Failed: {res.stderr.strip()}")
        return False


def get_kernel_status(kernel_id: str) -> str:
    res = subprocess.run(
        [KAGGLE_BIN, "kernels", "status", kernel_id],
        capture_output=True,
        text=True,
    )
    if res.returncode == 0:
        out = res.stdout.strip()
        logger.info(f"Status: {out}")
        return out
    return "UNKNOWN"


def fetch_kernel_output(kernel_id: str, dest_dir: Path) -> Optional[str]:
    os.makedirs(dest_dir, exist_ok=True)
    res = subprocess.run(
        [KAGGLE_BIN, "kernels", "output", kernel_id, "-p", str(dest_dir)],
        capture_output=True,
        text=True,
    )
    if res.returncode == 0:
        for fname in os.listdir(dest_dir):
            if fname.endswith(".log") or fname.endswith(".txt"):
                with open(dest_dir / fname, "r") as f:
                    content = f.read()
                    pattern = re.compile(r"https://[a-zA-Z0-9\-]+\.trycloudflare\.com")
                    match = pattern.search(content)
                    if match:
                        return match.group(0)
    return None


def register_node_with_inferacap(gateway_url: str, base_url: str, region: str = "KAGGLE") -> bool:
    reg_url = gateway_url.rstrip("/") + "/v1/nodes/register"
    payload = json.dumps({
        "node_id": f"kaggle-cloud-worker-{int(time.time()) % 10000}",
        "provider": "kaggle",
        "region": region,
        "base_url": base_url,
        "gpu_type": "T4",
        "gpu_count": 2,
        "models": ["llama-3.1-8b", "qwen2.5-coder", "mistral-7b-instruct"],
        "capacity": 8,
        "billing_type": "owned",
        "hourly_cost_usd": 0.0,
        "estimated_rtt_ms": 75.0,
    }).encode("utf-8")

    req = urllib.request.Request(
        reg_url,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=5.0) as resp:
            if resp.status == 200:
                logger.info(f"🎉 Successfully federated Kaggle node {base_url} into InferaCap [{region}] region!")
                return True
    except Exception as e:
        logger.warning(f"Registration request failed: {e}")
    return False


def main():
    parser = argparse.ArgumentParser(description="InferaCap Kaggle Cloud Fleet Runner")
    parser.add_argument("--push", action="store_true", help="Push latest notebook to Kaggle before polling")
    parser.add_argument("--status", action="store_true", help="Check live status of Kaggle worker kernel")
    parser.add_argument("--gateway-url", default="http://127.0.0.1:8765", help="InferaCap Live Gateway endpoint")
    args = parser.parse_args()

    if not check_kaggle_cli():
        logger.error("Kaggle CLI not available or authenticated. Please verify ~/.kaggle/credentials.json")
        sys.exit(1)

    gw_dir = Path(__file__).parent
    kernel_id = get_kernel_id(gw_dir)

    print("=" * 75)
    print("⚡ INFERACAP: KAGGLE CLOUD GPU FLEET ORCHESTRATOR")
    print(f"📦 Target Kernel: {kernel_id}")
    print("=" * 75)

    if args.push:
        push_kernel(gw_dir)

    status = get_kernel_status(kernel_id)
    print(f"📡 Current Remote Status: {status}")

    # Check output
    output_dir = gw_dir / "kaggle_output"
    tunnel_url = fetch_kernel_output(kernel_id, output_dir)
    if tunnel_url:
        print(f"✨ Found Cloudflare Ingress Tunnel: {tunnel_url}")
        if args.gateway_url:
            register_node_with_inferacap(args.gateway_url, tunnel_url)
    else:
        print("ℹ️  Worker is compiling or initializing tunnel. Run again in ~60 seconds to inspect tunnel URL.")


if __name__ == "__main__":
    main()
