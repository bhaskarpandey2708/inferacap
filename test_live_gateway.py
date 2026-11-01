"""Integration and unit tests for the InferaCap Live Online Inference Load Balancer."""

from __future__ import annotations

import asyncio
import json
import threading
import time
import unittest
import urllib.request
import urllib.error
from pathlib import Path

from gateway.config import GatewayConfig
from gateway.router import LiveEconomicRouter
from gateway.server import LiveGatewayServer
from gateway.mock_backend import MockRegionalServer, MockLLMHandler


class LiveGatewayIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # 1. Start Mock Regional LLM Backends
        cls.mock_us = MockRegionalServer("US")
        cls.mock_eu = MockRegionalServer("EU")
        cls.mock_asia = MockRegionalServer("ASIA")

        cls.mock_us.start()
        cls.mock_eu.start()
        cls.mock_asia.start()

        time.sleep(0.1)  # Allow mock servers to bind

        # 2. Build Test Gateway Config pointing to mock servers
        cls.config_dict = {
            "gateway_id": "test-gateway-01",
            "listen_host": "127.0.0.1",
            "listen_port": 0,  # OS assigned port
            "default_ttft_budget_ms": 300.0,
            "default_e2e_budget_ms": 2000.0,
            "request_timeout_seconds": 5.0,
            "regions": {
                "US": {
                    "backends": [cls.mock_us.url],
                    "models": ["llama-3.1-8b", "gpt-4o-mini"],
                    "capacity_concurrent_requests": 2,
                    "billing_type": "on_demand",
                    "on_demand_rate_gpu_hour": 4.00,
                    "committed_gpus": 0,
                    "overflow_rate_gpu_hour": 4.00,
                    "requests_per_gpu_hour": 3600.0,
                },
                "EU": {
                    "backends": [cls.mock_eu.url],
                    "models": ["llama-3.1-8b", "gpt-4o-mini"],
                    "capacity_concurrent_requests": 5,
                    "billing_type": "reservation",
                    "on_demand_rate_gpu_hour": 3.50,
                    "committed_gpus": 4,
                    "overflow_rate_gpu_hour": 3.50,
                    "requests_per_gpu_hour": 3600.0,
                },
                "ASIA": {
                    "backends": [cls.mock_asia.url],
                    "models": ["llama-3.1-8b"],
                    "capacity_concurrent_requests": 5,
                    "billing_type": "owned",
                    "on_demand_rate_gpu_hour": 0.00,
                    "committed_gpus": 0,
                    "overflow_rate_gpu_hour": 0.00,
                    "requests_per_gpu_hour": 3600.0,
                },
            },
            "allowed_routes": [
                {
                    "origin_region": "US",
                    "destination_region": "EU",
                    "model": "*",
                    "residency_permission": True,
                    "estimated_rtt_ms": 75.0,
                    "max_allowed_ttft_ms": 250.0,
                    "egress_cost_per_gb": 0.02,
                },
                {
                    "origin_region": "US",
                    "destination_region": "ASIA",
                    "model": "*",
                    "residency_permission": True,
                    "estimated_rtt_ms": 180.0,
                    "max_allowed_ttft_ms": 250.0,
                    "egress_cost_per_gb": 0.05,
                },
                {
                    "origin_region": "EU",
                    "destination_region": "US",
                    "model": "*",
                    "residency_permission": False,  # Prohibited by policy
                    "estimated_rtt_ms": 75.0,
                    "max_allowed_ttft_ms": 250.0,
                    "egress_cost_per_gb": 0.02,
                },
            ],
        }

        cls.config = GatewayConfig.from_dict(cls.config_dict)
        cls.router = LiveEconomicRouter(cls.config)
        cls.server = LiveGatewayServer(cls.config, cls.router)

        # Start Gateway Server in asyncio event loop in background thread
        cls.loop = asyncio.new_event_loop()

        def run_loop():
            asyncio.set_event_loop(cls.loop)
            cls.loop.run_until_complete(cls.server.start())
            cls.loop.run_forever()

        cls.server_thread = threading.Thread(target=run_loop, daemon=True)
        cls.server_thread.start()

        # Wait for server to bind and capture assigned port
        deadline = time.time() + 3.0
        while time.time() < deadline:
            if cls.server.server and cls.server.server.sockets:
                cls.port = cls.server.server.sockets[0].getsockname()[1]
                break
            time.sleep(0.05)

        cls.base_url = f"http://127.0.0.1:{cls.port}"

    @classmethod
    def tearDownClass(cls):
        # Stop Gateway Server
        future = asyncio.run_coroutine_threadsafe(cls.server.stop(), cls.loop)
        try:
            future.result(timeout=3.0)
        except Exception:
            pass
        cls.loop.call_soon_threadsafe(cls.loop.stop)
        cls.server_thread.join(timeout=3.0)

        # Stop Mock Servers
        cls.mock_us.stop()
        cls.mock_eu.stop()
        cls.mock_asia.stop()

    def _post_chat(self, payload: dict, headers: dict = None) -> tuple[int, dict, dict]:
        url = f"{self.base_url}/v1/chat/completions"
        data = json.dumps(payload).encode("utf-8")
        req_headers = {"Content-Type": "application/json"}
        if headers:
            req_headers.update(headers)
        req = urllib.request.Request(url, data=data, headers=req_headers, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=5.0) as resp:
                resp_body = json.loads(resp.read().decode("utf-8"))
                return resp.status, dict(resp.getheaders()), resp_body
        except urllib.error.HTTPError as e:
            return e.code, dict(e.headers), json.loads(e.read().decode("utf-8"))

    def _post_json(self, path: str, payload: dict) -> tuple[int, dict, dict]:
        url = f"{self.base_url}{path}"
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"}, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=5.0) as resp:
                resp_body = json.loads(resp.read().decode("utf-8"))
                return resp.status, dict(resp.getheaders()), resp_body
        except urllib.error.HTTPError as e:
            return e.code, dict(e.headers), json.loads(e.read().decode("utf-8"))

    def _get(self, path: str) -> tuple[int, dict]:
        url = f"{self.base_url}{path}"
        with urllib.request.urlopen(url, timeout=5.0) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))

    def test_01_health_and_models(self):
        status, data = self._get("/v1/health")
        self.assertEqual(status, 200)
        self.assertEqual(data["status"], "healthy")
        self.assertEqual(data["gateway_id"], "test-gateway-01")

        status, models_data = self._get("/v1/models")
        self.assertEqual(status, 200)
        ids = [m["id"] for m in models_data["data"]]
        self.assertIn("llama-3.1-8b", ids)
        self.assertIn("gpt-4o-mini", ids)

    def test_02_local_routing_under_normal_load(self):
        """When local region has capacity, route directly to local backend with zero egress."""
        payload = {
            "model": "llama-3.1-8b",
            "messages": [{"role": "user", "content": "What is the capital of France?"}],
        }
        status, headers, body = self._post_chat(payload, headers={"X-Region": "US"})
        self.assertEqual(status, 200)
        self.assertEqual(headers["X-InferaCap-Origin-Region"], "US")
        self.assertEqual(headers["X-InferaCap-Served-Region"], "US")
        self.assertEqual(headers["X-InferaCap-Route-Type"], "LOCAL")
        self.assertIn("Hello from regional backend [US]", body["choices"][0]["message"]["content"])

    def test_03_cross_region_economic_routing_on_saturation(self):
        """When US region is saturated, route dynamically to EU where idle reservation capacity exists."""
        payload = {
            "model": "llama-3.1-8b",
            "messages": [{"role": "user", "content": "Tell me a joke."}],
        }

        # Artificially occupy US capacity
        self.router.active_concurrency["US"] = 2  # Max capacity is 2

        try:
            status, headers, body = self._post_chat(payload, headers={"X-Region": "US"})
            self.assertEqual(status, 200)
            self.assertEqual(headers["X-InferaCap-Origin-Region"], "US")
            self.assertEqual(headers["X-InferaCap-Served-Region"], "EU")
            self.assertEqual(headers["X-InferaCap-Route-Type"], "CROSS_REGION_ECONOMIC")
            savings = float(headers["X-InferaCap-Estimated-Savings-USD"])
            self.assertGreater(savings, 0.0)
            self.assertIn("Hello from regional backend [EU]", body["choices"][0]["message"]["content"])
        finally:
            self.router.active_concurrency["US"] = 0

    def test_04_data_residency_enforcement(self):
        """When EU is saturated, EU -> US transfer is strictly prohibited by residency_permission=False."""
        payload = {
            "model": "llama-3.1-8b",
            "messages": [{"role": "user", "content": "Confidential GDPR data"}],
        }

        # Saturate EU capacity
        self.router.active_concurrency["EU"] = 5

        try:
            status, headers, body = self._post_chat(payload, headers={"X-Region": "EU"})
            # Must reject with 503 rather than illegally transferring to US
            self.assertEqual(status, 503)
            self.assertEqual(headers["X-InferaCap-Status"], "REJECTED")
            self.assertIn("residency allowlists", body["error"]["message"])
        finally:
            self.router.active_concurrency["EU"] = 0

    def test_05_latency_budget_enforcement(self):
        """When local region is full, remote route is denied if WAN RTT breaches client TTFT budget."""
        payload = {
            "model": "llama-3.1-8b",
            "messages": [{"role": "user", "content": "Real-time voice agent prompt"}],
        }

        # Saturate US capacity
        self.router.active_concurrency["US"] = 2

        try:
            # Client requires max 50ms TTFT budget (EU has 75ms RTT, Asia has 180ms RTT)
            status, headers, body = self._post_chat(
                payload, headers={"X-Region": "US", "X-TTFT-Budget-MS": "50"}
            )
            self.assertEqual(status, 503)
            self.assertIn("latency budget", body["error"]["message"])
        finally:
            self.router.active_concurrency["US"] = 0

    def test_06_metrics_endpoint(self):
        """Validate live metrics ledger tracking."""
        status, data = self._get("/v1/metrics")
        self.assertEqual(status, 200)
        metrics = data["metrics"]
        self.assertGreaterEqual(metrics["total_requests"], 3)
        self.assertGreaterEqual(metrics["local_requests"], 1)
        self.assertIn("requests_by_region", metrics)

    def test_07_cloud_render_fleet_manager(self):
        """Verify dynamic registration of Kaggle and Colab GPU render nodes."""
        from gateway.cloud_backends import CloudRenderFleetManager

        mgr = CloudRenderFleetManager()
        # Register a Kaggle T4 GPU node
        node_kaggle = mgr.register_node(
            node_id="kaggle-node-01",
            provider="kaggle",
            region="US",
            base_url="http://127.0.0.1:8001",
            gpu_type="T4",
            gpu_count=2,
            hourly_cost_usd=0.0,
        )
        node_kaggle.is_healthy = True
        node_kaggle.active_models = ["llama-3.1-8b"]

        # Register a Colab GPU node
        node_colab = mgr.register_node(
            node_id="colab-node-01",
            provider="colab",
            region="EU",
            base_url="http://127.0.0.1:8002",
            gpu_type="T4",
            gpu_count=1,
            hourly_cost_usd=0.0,
        )
        node_colab.is_healthy = True
        node_colab.active_models = ["llama-3.1-8b"]

        fleet_config = mgr.export_gateway_region_config()
        self.assertIn("US", fleet_config)
        self.assertIn("EU", fleet_config)
        self.assertEqual(fleet_config["US"]["billing_type"], "owned")
        self.assertEqual(fleet_config["US"]["capacity_concurrent_requests"], 8)
        self.assertEqual(fleet_config["EU"]["capacity_concurrent_requests"], 4)

    def test_08_dynamic_node_registration_and_routing(self):
        """Validate dynamic self-registration via /v1/nodes/register and immediate routing."""
        reg_payload = {
            "node_id": "kaggle-cloud-t4",
            "provider": "kaggle",
            "region": "KAGGLE",
            "base_url": self.mock_asia.url,  # reuse active mock server
            "gpu_type": "T4",
            "gpu_count": 2,
            "models": ["llama-3.1-8b", "qwen2.5-coder"],
            "capacity": 8,
            "billing_type": "owned",
            "hourly_cost_usd": 0.0,
            "estimated_rtt_ms": 50.0,
        }

        # 1. Register node via Gateway HTTP API
        status, headers, body = self._post_json("/v1/nodes/register", reg_payload)
        self.assertEqual(status, 200)
        self.assertEqual(body["status"], "registered")
        self.assertEqual(body["region"], "KAGGLE")
        self.assertIn("KAGGLE", self.router.config.regions)

        # 2. Check /v1/nodes endpoint
        status, nodes_data = self._get("/v1/nodes")
        self.assertEqual(status, 200)
        self.assertIn("KAGGLE", nodes_data["regions"])
        self.assertEqual(nodes_data["regions"]["KAGGLE"]["capacity"], 8)
        self.assertEqual(nodes_data["regions"]["KAGGLE"]["billing_type"], "owned")

        # 3. Route request from US to KAGGLE when US is full
        self.router.active_concurrency["US"] = 2  # Saturate US
        # Also saturate EU so KAGGLE is preferred
        self.router.active_concurrency["EU"] = 5

        try:
            chat_req = {
                "model": "qwen2.5-coder",
                "messages": [{"role": "user", "content": "Write quicksort in python"}],
            }
            # Only KAGGLE has qwen2.5-coder in this test
            status, hdrs, res = self._post_chat(chat_req, headers={"X-Region": "US"})
            self.assertEqual(status, 200)
            self.assertEqual(hdrs["X-InferaCap-Served-Region"], "KAGGLE")
            self.assertEqual(hdrs["X-InferaCap-Route-Type"], "CROSS_REGION_ECONOMIC")
        finally:
            self.router.active_concurrency["US"] = 0
            self.router.active_concurrency["EU"] = 0

    def test_09_sse_token_streaming(self):
        """Validate live SSE token chunk streaming with stream: true."""
        req_payload = {
            "model": "llama-3.1-8b",
            "messages": [{"role": "user", "content": "Stream poem"}],
            "stream": True,
        }
        data = json.dumps(req_payload).encode("utf-8")
        req = urllib.request.Request(
            f"{self.base_url}/v1/chat/completions",
            data=data,
            headers={"Content-Type": "application/json", "X-Region": "US"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=5.0) as resp:
            self.assertEqual(resp.status, 200)
            self.assertIn("text/event-stream", resp.getheader("Content-Type"))
            self.assertEqual(resp.getheader("X-InferaCap-Served-Region"), "US")

            chunks = []
            while True:
                line = resp.readline().decode("utf-8")
                if not line:
                    break
                if line.startswith("data: ") and not line.strip() == "data: [DONE]":
                    chunk_obj = json.loads(line[6:].strip())
                    chunks.append(chunk_obj)
            self.assertGreaterEqual(len(chunks), 3)
            self.assertIn("choices", chunks[0])

    def test_10_circuit_breaker_tripping_and_failover(self):
        """When local backend fails 3 consecutive times, circuit breaker trips to OPEN and routes fail over."""
        local_backend = self.mock_us.url
        cb = self.router._get_circuit_breaker(local_backend, "US")
        self.assertEqual(cb.state, "CLOSED")

        # Simulate 3 consecutive failures
        cb.record_failure("Connection refused")
        cb.record_failure("Connection refused")
        cb.record_failure("Connection refused")

        self.assertEqual(cb.state, "OPEN")
        self.assertFalse(cb.is_available())

        # Request from US should now fail over to EU because local backend is OPEN
        chat_req = {
            "model": "llama-3.1-8b",
            "messages": [{"role": "user", "content": "Failover prompt"}],
        }
        status, hdrs, body = self._post_chat(chat_req, headers={"X-Region": "US"})
        self.assertEqual(status, 200)
        self.assertIn(hdrs["X-InferaCap-Served-Region"], ("EU", "KAGGLE"))
        self.assertEqual(hdrs["X-InferaCap-Route-Type"], "CROSS_REGION_ECONOMIC")

        # Recover local circuit breaker
        cb.record_success(latency_ms=10.0)
        self.assertEqual(cb.state, "CLOSED")

    def test_11_telemetry_analytics(self):
        """Verify telemetry analytics and drop/merge recommendation output."""
        self.router.record_feature_interaction("offline_simulator")
        self.router.record_feature_interaction("live_routing")
        self.router.record_feature_interaction("live_routing")
        self.router.record_feature_interaction("live_routing")

        status, data = self._get("/v1/analytics")
        self.assertEqual(status, 200)
        self.assertIn("feature_counts", data)
        self.assertIn("feature_distribution_pct", data)
        self.assertIn("recommendations", data)
        self.assertGreaterEqual(data["total_interactions"], 4)


if __name__ == "__main__":
    unittest.main()
