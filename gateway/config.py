"""Configuration definitions and validation for InferaCap Live Gateway."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional


class GatewayConfigError(ValueError):
    """Raised when gateway configuration fails validation."""
    pass


@dataclass
class RegionConfig:
    name: str
    backends: List[str]
    models: List[str]
    capacity_concurrent_requests: int
    billing_type: str = "on_demand"  # on_demand, reservation, owned
    on_demand_rate_gpu_hour: float = 3.99
    committed_gpus: int = 0
    overflow_rate_gpu_hour: float = 3.99
    requests_per_gpu_hour: float = 3600.0

    def __post_init__(self):
        if not self.name or not isinstance(self.name, str):
            raise GatewayConfigError("Region name must be a non-empty string")
        if not self.backends or not isinstance(self.backends, list):
            raise GatewayConfigError(f"Region {self.name} must specify at least one backend URL")
        if not self.models or not isinstance(self.models, list):
            raise GatewayConfigError(f"Region {self.name} must specify at least one model")
        if self.capacity_concurrent_requests <= 0:
            raise GatewayConfigError(f"Region {self.name} capacity must be a positive integer")
        if self.billing_type not in ("on_demand", "reservation", "owned"):
            raise GatewayConfigError(f"Region {self.name} billing_type must be on_demand, reservation, or owned")


@dataclass
class RouteRule:
    origin_region: str
    destination_region: str
    model: str
    residency_permission: bool
    estimated_rtt_ms: float
    max_allowed_ttft_ms: float
    egress_cost_per_gb: float = 0.02

    def __post_init__(self):
        if not self.origin_region or not self.destination_region:
            raise GatewayConfigError("Route rule must specify origin and destination regions")
        if self.estimated_rtt_ms < 0:
            raise GatewayConfigError("Estimated RTT must be non-negative")


@dataclass
class GatewayConfig:
    gateway_id: str
    regions: Dict[str, RegionConfig]
    allowed_routes: List[RouteRule]
    default_ttft_budget_ms: float = 400.0
    default_e2e_budget_ms: float = 3000.0
    listen_host: str = "127.0.0.1"
    listen_port: int = 8080
    request_timeout_seconds: float = 30.0

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "GatewayConfig":
        if not isinstance(data, dict):
            raise GatewayConfigError("Configuration must be a JSON object")
        
        gateway_id = data.get("gateway_id", "inferacap-gateway-01")
        regions_raw = data.get("regions", {})
        if not regions_raw:
            raise GatewayConfigError("Configuration must define at least one region")
        
        regions = {}
        for r_name, r_val in regions_raw.items():
            regions[r_name] = RegionConfig(
                name=r_name,
                backends=r_val.get("backends", []),
                models=r_val.get("models", []),
                capacity_concurrent_requests=int(r_val.get("capacity_concurrent_requests", 20)),
                billing_type=r_val.get("billing_type", "on_demand"),
                on_demand_rate_gpu_hour=float(r_val.get("on_demand_rate_gpu_hour", 3.99)),
                committed_gpus=int(r_val.get("committed_gpus", 0)),
                overflow_rate_gpu_hour=float(r_val.get("overflow_rate_gpu_hour", 3.99)),
                requests_per_gpu_hour=float(r_val.get("requests_per_gpu_hour", 3600.0)),
            )

        routes_raw = data.get("allowed_routes", [])
        routes = []
        for rule in routes_raw:
            routes.append(RouteRule(
                origin_region=rule["origin_region"],
                destination_region=rule["destination_region"],
                model=rule.get("model", "*"),
                residency_permission=bool(rule.get("residency_permission", False)),
                estimated_rtt_ms=float(rule.get("estimated_rtt_ms", 50.0)),
                max_allowed_ttft_ms=float(rule.get("max_allowed_ttft_ms", 500.0)),
                egress_cost_per_gb=float(rule.get("egress_cost_per_gb", 0.02)),
            ))

        return cls(
            gateway_id=gateway_id,
            regions=regions,
            allowed_routes=routes,
            default_ttft_budget_ms=float(data.get("default_ttft_budget_ms", 400.0)),
            default_e2e_budget_ms=float(data.get("default_e2e_budget_ms", 3000.0)),
            listen_host=data.get("listen_host", "127.0.0.1"),
            listen_port=int(data.get("listen_port", 8080)),
            request_timeout_seconds=float(data.get("request_timeout_seconds", 30.0)),
        )

    @classmethod
    def from_file(cls, path: str | Path) -> "GatewayConfig":
        with open(path, "r", encoding="utf-8") as f:
            return cls.from_dict(json.load(f))
