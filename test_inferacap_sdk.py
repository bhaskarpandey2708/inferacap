"""Unit tests for the official InferaCap Python SDK."""

import asyncio
import json
import threading
import time
import unittest

from gateway.config import GatewayConfig
from gateway.router import LiveEconomicRouter
from gateway.server import LiveGatewayServer
from gateway.mock_backend import MockRegionalServer
from inferacap import InferaCap, InferaCapResponse, InferaCapStreamChunk, InferaCapError


class TestInferaCapSDK(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # 1. Start Mock Server
        cls.mock_backend = MockRegionalServer("US")
        cls.mock_backend.start()
        time.sleep(0.1)

        # 2. Start Gateway
        cls.config_dict = {
            "gateway_id": "sdk-test-gateway",
            "listen_host": "127.0.0.1",
            "listen_port": 0,
            "default_ttft_budget_ms": 400.0,
            "default_e2e_budget_ms": 3000.0,
            "request_timeout_seconds": 5.0,
            "regions": {
                "US": {
                    "backends": [cls.mock_backend.url],
                    "models": ["llama-3.1-8b"],
                    "capacity_concurrent_requests": 10,
                    "billing_type": "on_demand",
                    "on_demand_rate_gpu_hour": 3.99,
                    "committed_gpus": 0,
                    "overflow_rate_gpu_hour": 3.99,
                    "requests_per_gpu_hour": 3600.0,
                }
            },
            "allowed_routes": [],
        }
        config = GatewayConfig.from_dict(cls.config_dict)
        cls.router = LiveEconomicRouter(config)
        cls.server = LiveGatewayServer(config, cls.router)

        cls.loop = asyncio.new_event_loop()
        def _run_gw():
            asyncio.set_event_loop(cls.loop)
            cls.loop.run_until_complete(cls.server.start())
            cls.loop.run_forever()

        cls.gw_thread = threading.Thread(target=_run_gw, daemon=True)
        cls.gw_thread.start()

        deadline = time.time() + 3.0
        while time.time() < deadline:
            if cls.server.server and cls.server.server.sockets:
                cls.port = cls.server.server.sockets[0].getsockname()[1]
                break
            time.sleep(0.05)

        cls.base_url = f"http://127.0.0.1:{cls.port}/v1"
        cls.client = InferaCap(base_url=cls.base_url, origin_region="US")

    @classmethod
    def tearDownClass(cls):
        fut = asyncio.run_coroutine_threadsafe(cls.server.stop(), cls.loop)
        try:
            fut.result(timeout=2.0)
        except Exception:
            pass
        cls.loop.call_soon_threadsafe(cls.loop.stop)
        cls.mock_backend.stop()

    def test_01_health_probe(self):
        self.assertTrue(self.client.health())

    def test_02_chat_completion(self):
        resp = self.client.chat(
            model="llama-3.1-8b",
            messages=[{"role": "user", "content": "SDK test prompt"}],
        )
        self.assertIsInstance(resp, InferaCapResponse)
        self.assertIn("Hello from regional backend [US]", resp.content)
        self.assertEqual(resp.origin_region, "US")
        self.assertEqual(resp.served_region, "US")
        self.assertEqual(resp.route_type, "LOCAL")

    def test_03_chat_stream(self):
        chunks = list(self.client.chat_stream(
            model="llama-3.1-8b",
            messages=[{"role": "user", "content": "SDK streaming prompt"}],
        ))
        self.assertGreaterEqual(len(chunks), 3)
        self.assertIsInstance(chunks[0], InferaCapStreamChunk)
        self.assertIsNotNone(chunks[0].delta)
        # Verify first chunk measured TTFT
        self.assertIsNotNone(chunks[0].ttft_ms)
        self.assertGreater(chunks[0].ttft_ms, 0.0)

    def test_04_metrics_and_analytics(self):
        metrics = self.client.get_metrics()
        self.assertIn("gateway_id", metrics)
        self.assertIn("metrics", metrics)

        analytics = self.client.get_analytics()
        self.assertIn("feature_counts", analytics)
        self.assertIn("recommendations", analytics)


if __name__ == "__main__":
    unittest.main()
