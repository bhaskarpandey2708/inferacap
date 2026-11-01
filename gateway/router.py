"""Real-time Economic and Latency-Aware Router for InferaCap."""

from __future__ import annotations

import asyncio
import logging
import random
import time
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

from .config import GatewayConfig, RegionConfig, RouteRule

logger = logging.getLogger("inferacap.router")


@dataclass
class CircuitBreakerState:
    backend_url: str
    region: str
    state: str = "CLOSED"  # "CLOSED", "OPEN", "HALF_OPEN"
    consecutive_failures: int = 0
    consecutive_successes: int = 0
    last_failure_time: float = 0.0
    last_success_time: float = 0.0
    last_latency_ms: float = 0.0
    failure_threshold: int = 3
    recovery_timeout_seconds: float = 15.0

    def record_success(self, latency_ms: float = 0.0):
        self.consecutive_successes += 1
        self.consecutive_failures = 0
        self.last_success_time = time.time()
        self.last_latency_ms = latency_ms
        if self.state in ("OPEN", "HALF_OPEN"):
            logger.info(f"Circuit Breaker for {self.backend_url} ({self.region}) RECOVERED -> CLOSED")
            self.state = "CLOSED"

    def record_failure(self, error: str = ""):
        self.consecutive_failures += 1
        self.consecutive_successes = 0
        self.last_failure_time = time.time()
        if self.consecutive_failures >= self.failure_threshold and self.state != "OPEN":
            self.state = "OPEN"
            logger.warning(
                f"🚨 Circuit Breaker TRIPPED for {self.backend_url} ({self.region}) -> OPEN "
                f"({self.consecutive_failures} failures: {error})"
            )

    def is_available(self) -> bool:
        if self.state == "CLOSED":
            return True
        if self.state == "OPEN":
            # Check if recovery timeout has passed
            if time.time() - self.last_failure_time > self.recovery_timeout_seconds:
                self.state = "HALF_OPEN"
                logger.info(f"Circuit Breaker for {self.backend_url} ({self.region}) entering HALF_OPEN trial")
                return True
            return False
        if self.state == "HALF_OPEN":
            return True
        return False


class AnalyticsLedger:
    """Tracks customer interactions across features to inform drop/merge decisions."""

    def __init__(self):
        self.feature_interactions: Dict[str, int] = {
            "offline_simulator": 0,
            "live_routing": 0,
            "log_scanner": 0,
            "cloud_worker": 0,
        }
        self.client_origins: Dict[str, int] = {}
        self.start_time = time.time()

    def record_interaction(self, feature_name: str, client_ip: str = "127.0.0.1"):
        if feature_name in self.feature_interactions:
            self.feature_interactions[feature_name] += 1
        self.client_origins[client_ip] = self.client_origins.get(client_ip, 0) + 1

    def get_summary(self) -> Dict:
        total = sum(self.feature_interactions.values())
        norm_total = max(total, 1)
        distribution = {k: round((v / norm_total) * 100, 1) for k, v in self.feature_interactions.items()}

        sorted_features = sorted(self.feature_interactions.items(), key=lambda x: x[1], reverse=True)
        top_feature, top_count = sorted_features[0]
        least_feature, least_count = sorted_features[-1]

        recommendations = []
        if total >= 5:
            if least_count == 0 or (least_count / norm_total) < 0.05:
                recommendations.append(
                    f"Feature '{least_feature}' accounts for <5% of usage. "
                    f"Candidate for merging into '{top_feature}' or deprecating to streamline maintenance."
                )
            if distribution.get("live_routing", 0) > 40:
                recommendations.append(
                    "Live Routing is high traction. Prioritize SSE streaming and WAN latency tuning."
                )
        else:
            recommendations.append("Initial telemetry baseline active. Accumulating user interaction events.")

        return {
            "total_interactions": total,
            "feature_counts": dict(self.feature_interactions),
            "feature_distribution_pct": distribution,
            "unique_clients": len(self.client_origins),
            "recommendations": recommendations,
        }


@dataclass
class RouteDecision:
    target_backend_url: str
    target_region: str
    origin_region: str
    route_type: str  # "LOCAL", "CROSS_REGION_ECONOMIC", "CROSS_REGION_OVERFLOW"
    estimated_savings_usd: float
    estimated_egress_usd: float
    estimated_rtt_ms: float
    model: str
    rejection_reason: Optional[str] = None


class LiveEconomicRouter:
    """Maintains regional state and executes economic, latency, and residency routing."""

    def __init__(self, config: GatewayConfig):
        self.config = config
        self._lock = asyncio.Lock()
        
        # Concurrency counters per region
        self.active_concurrency: Dict[str, int] = {r: 0 for r in config.regions}
        self.circuit_breakers: Dict[str, CircuitBreakerState] = {}
        self.analytics = AnalyticsLedger()
        
        # Metrics
        self.metrics = {
            "total_requests": 0,
            "local_requests": 0,
            "cross_region_requests": 0,
            "rejected_requests": 0,
            "total_estimated_savings_usd": 0.0,
            "total_estimated_egress_usd": 0.0,
            "requests_by_region": {r: 0 for r in config.regions},
            "requests_by_model": {},
        }

    def _get_circuit_breaker(self, backend_url: str, region: str) -> CircuitBreakerState:
        if backend_url not in self.circuit_breakers:
            self.circuit_breakers[backend_url] = CircuitBreakerState(backend_url=backend_url, region=region)
        return self.circuit_breakers[backend_url]

    def report_backend_failure(self, backend_url: str, region: str, error: str = ""):
        cb = self._get_circuit_breaker(backend_url, region)
        cb.record_failure(error)

    def report_backend_success(self, backend_url: str, region: str, latency_ms: float = 0.0):
        cb = self._get_circuit_breaker(backend_url, region)
        cb.record_success(latency_ms)

    def record_feature_interaction(self, feature_name: str, client_ip: str = "127.0.0.1"):
        self.analytics.record_interaction(feature_name, client_ip)

    def get_analytics(self) -> Dict:
        return self.analytics.get_summary()

    def _find_route_rule(self, origin: str, destination: str, model: str) -> Optional[RouteRule]:
        for rule in self.config.allowed_routes:
            if rule.origin_region == origin and rule.destination_region == destination:
                if rule.model in (model, "*"):
                    return rule
        return None

    async def select_route(
        self,
        origin_region: str,
        model: str,
        ttft_budget_ms: Optional[float] = None,
        estimated_payload_bytes: int = 4096,
    ) -> RouteDecision:
        """Select the optimal backend adhering to capacity, residency, latency, and cash economics."""
        budget = ttft_budget_ms or self.config.default_ttft_budget_ms

        async with self._lock:
            self.metrics["total_requests"] += 1
            if model not in self.metrics["requests_by_model"]:
                self.metrics["requests_by_model"][model] = 0
            self.metrics["requests_by_model"][model] += 1

            if origin_region not in self.config.regions:
                # Default to the first available region if unknown
                origin_region = next(iter(self.config.regions.keys()))

            local_reg = self.config.regions[origin_region]
            local_active = self.active_concurrency.get(origin_region, 0)
            model_supported_locally = model in local_reg.models
            available_local_backends = [b for b in local_reg.backends if self._get_circuit_breaker(b, origin_region).is_available()]

            # 1. Evaluate Local Route
            if model_supported_locally and local_active < local_reg.capacity_concurrent_requests and available_local_backends:
                backend = random.choice(available_local_backends)
                self.active_concurrency[origin_region] += 1
                self.metrics["local_requests"] += 1
                self.metrics["requests_by_region"][origin_region] += 1
                return RouteDecision(
                    target_backend_url=backend,
                    target_region=origin_region,
                    origin_region=origin_region,
                    route_type="LOCAL",
                    estimated_savings_usd=0.0,
                    estimated_egress_usd=0.0,
                    estimated_rtt_ms=0.0,
                    model=model,
                )

            # 2. Local Region is Saturated or does not host the model -> Evaluate Remote Candidates
            candidates: List[Tuple[float, RegionConfig, RouteRule, float, float, List[str]]] = []

            # Estimate cost of adding on-demand capacity locally
            local_marginal_cost_per_req = (
                local_reg.on_demand_rate_gpu_hour / max(local_reg.requests_per_gpu_hour, 1.0)
            )

            for cand_name, cand_reg in self.config.regions.items():
                if cand_name == origin_region:
                    continue
                if model not in cand_reg.models:
                    continue

                cand_active = self.active_concurrency.get(cand_name, 0)
                if cand_active >= cand_reg.capacity_concurrent_requests:
                    continue  # Candidate is also full

                # Check Circuit Breaker availability on candidate backends
                avail_cand_backends = [b for b in cand_reg.backends if self._get_circuit_breaker(b, cand_name).is_available()]
                if not avail_cand_backends:
                    continue  # All backends in this region have tripped circuit breakers

                # Check Residency & Allowed Route
                rule = self._find_route_rule(origin_region, cand_name, model)
                if not rule or not rule.residency_permission:
                    continue  # Legally prohibited

                # Check Latency Budget
                if rule.estimated_rtt_ms > budget or rule.estimated_rtt_ms > rule.max_allowed_ttft_ms:
                    continue  # Breaches latency SLA

                # Calculate Incremental Economics
                # If remote region has idle committed reservation or owned capacity:
                if cand_reg.billing_type in ("owned", "reservation"):
                    remote_compute_cost = 0.0  # Already paid / sunk cost
                else:
                    remote_compute_cost = cand_reg.on_demand_rate_gpu_hour / max(cand_reg.requests_per_gpu_hour, 1.0)

                # Cross-region network egress cost ($/GB * GB)
                gb = estimated_payload_bytes / (1024 * 1024 * 1024)
                egress_cost = gb * rule.egress_cost_per_gb

                # Net avoidable savings = Local overflow avoided - (Remote compute + Egress)
                net_savings = local_marginal_cost_per_req - (remote_compute_cost + egress_cost)

                candidates.append((net_savings, cand_reg, rule, egress_cost, rule.estimated_rtt_ms, avail_cand_backends))

            # 3. Pick the best candidate with positive economic savings or least latency
            if candidates:
                # Sort primarily by net savings (highest first), then by lowest RTT
                candidates.sort(key=lambda x: (x[0], -x[4]), reverse=True)
                best_savings, best_cand, best_rule, best_egress, best_rtt, cand_backends = candidates[0]
                
                backend = random.choice(cand_backends)
                self.active_concurrency[best_cand.name] += 1
                self.metrics["cross_region_requests"] += 1
                self.metrics["requests_by_region"][best_cand.name] += 1
                self.metrics["total_estimated_savings_usd"] += max(0.0, best_savings)
                self.metrics["total_estimated_egress_usd"] += best_egress

                return RouteDecision(
                    target_backend_url=backend,
                    target_region=best_cand.name,
                    origin_region=origin_region,
                    route_type="CROSS_REGION_ECONOMIC",
                    estimated_savings_usd=max(0.0, best_savings),
                    estimated_egress_usd=best_egress,
                    estimated_rtt_ms=best_rtt,
                    model=model,
                )

            # 4. Infeasible: No region could legally and economically serve within budget
            self.metrics["rejected_requests"] += 1
            reason = (
                f"No eligible backend found for model '{model}' from origin '{origin_region}'. "
                f"Local region saturated (concurrency {local_active}/{local_reg.capacity_concurrent_requests}), "
                f"and remote regions either lack capacity, breach residency allowlists, or exceed latency budget ({budget}ms)."
            )
            return RouteDecision(
                target_backend_url="",
                target_region="",
                origin_region=origin_region,
                route_type="REJECTED",
                estimated_savings_usd=0.0,
                estimated_egress_usd=0.0,
                estimated_rtt_ms=0.0,
                model=model,
                rejection_reason=reason,
            )

    async def register_dynamic_node(
        self,
        node_id: str,
        region_name: str,
        base_url: str,
        models: List[str],
        capacity: int = 4,
        billing_type: str = "owned",
        hourly_cost: float = 0.0,
        estimated_rtt_ms: float = 80.0,
    ) -> Dict:
        """Dynamically register or update a remote worker node into the routing matrix."""
        region_name = region_name.upper()
        async with self._lock:
            if region_name not in self.config.regions:
                # Create a new region
                self.config.regions[region_name] = RegionConfig(
                    name=region_name,
                    backends=[base_url],
                    models=list(models),
                    capacity_concurrent_requests=capacity,
                    billing_type=billing_type,
                    on_demand_rate_gpu_hour=hourly_cost,
                    committed_gpus=max(1, capacity // 4),
                    overflow_rate_gpu_hour=hourly_cost,
                    requests_per_gpu_hour=3600.0,
                )
                self.active_concurrency[region_name] = 0
                self.metrics["requests_by_region"][region_name] = 0

                # Add bidirectional routes between existing regions and new region
                for existing_region in list(self.config.regions.keys()):
                    if existing_region != region_name:
                        self.config.allowed_routes.append(
                            RouteRule(
                                origin_region=existing_region,
                                destination_region=region_name,
                                model="*",
                                residency_permission=True,
                                estimated_rtt_ms=estimated_rtt_ms,
                                max_allowed_ttft_ms=500.0,
                                egress_cost_per_gb=0.01,
                            )
                        )
            else:
                # Update existing region
                reg = self.config.regions[region_name]
                if base_url not in reg.backends:
                    reg.backends.append(base_url)
                    reg.capacity_concurrent_requests += capacity
                for m in models:
                    if m not in reg.models:
                        reg.models.append(m)

            logger.info(f"Dynamically registered node [{node_id}] in region [{region_name}] -> {base_url}")
            return {
                "status": "registered",
                "node_id": node_id,
                "region": region_name,
                "backends": self.config.regions[region_name].backends,
                "capacity": self.config.regions[region_name].capacity_concurrent_requests,
                "models": self.config.regions[region_name].models,
            }

    async def release_route(self, region_name: str) -> None:
        """Release active concurrency after request finishes."""
        async with self._lock:
            if region_name in self.active_concurrency:
                self.active_concurrency[region_name] = max(0, self.active_concurrency[region_name] - 1)

    def get_metrics(self) -> Dict:
        """Return a snapshot of real-time routing metrics."""
        return {
            "gateway_id": self.config.gateway_id,
            "timestamp": time.time(),
            "metrics": dict(self.metrics),
            "active_concurrency": dict(self.active_concurrency),
            "regional_limits": {r: reg.capacity_concurrent_requests for r, reg in self.config.regions.items()},
            "circuit_breakers": {
                url: {
                    "region": cb.region,
                    "state": cb.state,
                    "consecutive_failures": cb.consecutive_failures,
                    "last_latency_ms": cb.last_latency_ms,
                }
                for url, cb in self.circuit_breakers.items()
            },
            "analytics": self.analytics.get_summary(),
        }
