"""Unit tests for InferaCap Kaggle GPU Worker."""

import json
import threading
import time
import unittest
import urllib.request
import urllib.error

from gateway.inferacap_kaggle_worker import InferaCapWorkerHandler, http


class TestInferaCapKaggleWorker(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        InferaCapWorkerHandler.node_id = "test-kaggle-worker"
        InferaCapWorkerHandler.region = "KAGGLE"
        InferaCapWorkerHandler.gpu_info = {
            "gpu_available": True,
            "gpu_count": 2,
            "gpu_devices": [{"index": 0, "name": "Tesla T4", "vram_gb": 16.0}],
            "total_vram_gb": 32.0,
        }
        cls.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), InferaCapWorkerHandler)
        cls.port = cls.server.server_address[1]
        cls.base_url = f"http://127.0.0.1:{cls.port}"
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        time.sleep(0.1)

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=2.0)

    def test_01_health_endpoint(self):
        req = urllib.request.Request(f"{self.base_url}/health")
        with urllib.request.urlopen(req, timeout=3.0) as resp:
            self.assertEqual(resp.status, 200)
            data = json.loads(resp.read().decode("utf-8"))
            self.assertEqual(data["status"], "healthy")
            self.assertEqual(data["region"], "KAGGLE")
            self.assertEqual(data["gpu"]["gpu_count"], 2)

    def test_02_models_endpoint(self):
        req = urllib.request.Request(f"{self.base_url}/v1/models")
        with urllib.request.urlopen(req, timeout=3.0) as resp:
            self.assertEqual(resp.status, 200)
            data = json.loads(resp.read().decode("utf-8"))
            model_ids = [m["id"] for m in data["data"]]
            self.assertIn("llama-3.1-8b", model_ids)
            self.assertIn("qwen2.5-coder", model_ids)

    def test_03_chat_completions(self):
        payload = json.dumps({
            "model": "llama-3.1-8b",
            "messages": [{"role": "user", "content": "Hello Kaggle Worker"}],
        }).encode("utf-8")
        req = urllib.request.Request(
            f"{self.base_url}/v1/chat/completions",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=3.0) as resp:
            self.assertEqual(resp.status, 200)
            self.assertEqual(resp.getheader("X-InferaCap-Worker-Region"), "KAGGLE")
            data = json.loads(resp.read().decode("utf-8"))
            self.assertIn("choices", data)
            content = data["choices"][0]["message"]["content"]
            self.assertIn("InferaCap Worker: test-kaggle-worker", content)


if __name__ == "__main__":
    unittest.main()
