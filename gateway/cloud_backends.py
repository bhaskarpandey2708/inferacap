"""Cloud Render and Remote GPU Cluster Adapters for InferaCap.

Supports connecting Kaggle GPU instances, Google Colab nodes, Runpod,
and remote vLLM/SGLang/Ollama clusters into the InferaCap regional federation.
"""

from __future__ import annotations

import json
import logging
import urllib.request
import urllib.error
from dataclasses import dataclass
from typing import Dict, List, Optional

logger = logging.getLogger("inferacap.cloud_backends")


@dataclass
class CloudRenderNode:
    node_id: str
    provider: str  # "kaggle", "colab", "runpod", "self_hosted", "aws", "gcp"
    region: str    # "US", "EU", "ASIA", etc.
    base_url: str
    gpu_type: str  # "T4", "P100", "L4", "A100", "H100"
    gpu_count: int
    hourly_cost_usd: float  # 0.0 for free Kaggle/Colab, or on-demand rate
    auth_token: Optional[str] = None
    is_healthy: bool = False
    active_models: List[str] = None

    def check_health(self, timeout_seconds: float = 5.0) -> bool:
        """Ping remote OpenAI-compatible /v1/models or /health endpoint."""
        url = self.base_url.rstrip("/") + "/v1/models"
        headers = {"User-Agent": "InferaCap-Cloud-Probe/1.0"}
        if self.auth_token:
            headers["Authorization"] = f"Bearer {self.auth_token}"

        req = urllib.request.Request(url, headers=headers, method="GET")
        try:
            with urllib.request.urlopen(req, timeout=timeout_seconds) as resp:
                if resp.status == 200:
                    data = json.loads(resp.read().decode("utf-8"))
                    self.active_models = [m.get("id") for m in data.get("data", [])]
                    self.is_healthy = True
                    logger.info(f"Node [{self.node_id}] healthy. Models: {self.active_models}")
                    return True
        except Exception as e:
            self.is_healthy = False
            logger.warning(f"Node [{self.node_id}] unreachable at {self.base_url}: {e}")
            return False
        return False


class CloudRenderFleetManager:
    """Manages multi-cloud render nodes and registers them into InferaCap regions."""

    def __init__(self):
        self.nodes: Dict[str, CloudRenderNode] = {}

    def register_node(
        self,
        node_id: str,
        provider: str,
        region: str,
        base_url: str,
        gpu_type: str = "T4",
        gpu_count: int = 1,
        hourly_cost_usd: float = 0.0,
        auth_token: Optional[str] = None,
    ) -> CloudRenderNode:
        node = CloudRenderNode(
            node_id=node_id,
            provider=provider,
            region=region.upper(),
            base_url=base_url,
            gpu_type=gpu_type,
            gpu_count=gpu_count,
            hourly_cost_usd=hourly_cost_usd,
            auth_token=auth_token,
            active_models=[],
        )
        self.nodes[node_id] = node
        return node

    def get_nodes_for_region(self, region: str) -> List[CloudRenderNode]:
        return [n for n in self.nodes.values() if n.region == region.upper() and n.is_healthy]

    def export_gateway_region_config(self) -> Dict:
        """Export dynamic backend configuration compatible with GatewayConfig."""
        regions = {}
        for node in self.nodes.values():
            r = node.region
            if r not in regions:
                regions[r] = {
                    "backends": [],
                    "models": set(),
                    "capacity_concurrent_requests": 0,
                    "billing_type": "owned" if node.hourly_cost_usd == 0 else "on_demand",
                    "on_demand_rate_gpu_hour": node.hourly_cost_usd,
                    "committed_gpus": node.gpu_count,
                }
            regions[r]["backends"].append(node.base_url)
            if node.active_models:
                regions[r]["models"].update(node.active_models)
            regions[r]["capacity_concurrent_requests"] += (node.gpu_count * 4)

        # Convert sets to lists
        for r, data in regions.items():
            data["models"] = list(data["models"]) or ["llama-3.1-8b"]
        return regions
