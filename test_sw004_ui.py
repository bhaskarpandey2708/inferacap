"""HTTP boundary checks for the localhost-only simulator interface."""

from __future__ import annotations

import json
import copy
import socket
import threading
import time
import unittest
from http.server import HTTPServer
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from sw004_ui import BoundedHTTPServer, Handler, MAX_HTTP_WORKERS


class QuietHandler(Handler):
    token = "test-only-session-token"

    def log_message(self, format, *args):
        pass


class ShortTimeoutHandler(QuietHandler):
    request_timeout_seconds = 0.15


class LongTimeoutHandler(QuietHandler):
    request_timeout_seconds = 2


class UITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = BoundedHTTPServer(("127.0.0.1", 0), QuietHandler)
        cls.base = f"http://127.0.0.1:{cls.server.server_port}"
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=3)

    def get(self, path):
        with urlopen(self.base + path, timeout=3) as response:
            return response.read().decode("utf-8")

    def post(self, payload, *, token="test-only-session-token", origin=None, path="/run"):
        request = Request(
            self.base + path, data=json.dumps(payload).encode("utf-8"), method="POST",
            headers={"Content-Type": "application/json", "Origin": origin or self.base, "X-SW004-Token": token},
        )
        with urlopen(request, timeout=3) as response:
            return json.loads(response.read())

    def test_serves_only_fixed_local_interface_resources(self):
        self.assertEqual(self.server.server_address[0], "127.0.0.1")
        self.assertIn("test-only-session-token", self.get("/"))
        self.assertIn("fetch(\"/run\"", self.get("/sw004_ui.js"))
        self.assertEqual(json.loads(self.get("/health"))["local_only"], True)
        with self.assertRaises(HTTPError) as failed:
            self.get("/../../etc/passwd")
        self.assertEqual(failed.exception.code, 404)

    def test_sample_csv_run_returns_dated_reports(self):
        config = json.loads(self.get("/sample-config"))
        observations = self.get("/sample-observations")
        result = self.post({"scenario": config, "observations_csv": observations})
        report = result["report"]
        self.assertEqual(report["baseline_compute_usd"], "574.56")
        self.assertEqual(report["perfect_pooling_compute_lower_bound_usd"], "287.28")
        self.assertEqual(report["net_current_cash_delta_usd"], "279.28")
        self.assertTrue(report["exported_utc"].endswith("Z"))
        self.assertIn(report["exported_utc"], result["report_csv"])
        raw_result = self.post({"scenario_json": self.get("/sample-config"), "observations_csv": observations})
        self.assertEqual(raw_result["report"]["scenario_sha256"], report["scenario_sha256"])

    def test_rejects_cross_origin_or_wrong_token(self):
        payload = {"scenario": json.loads(self.get("/sample-config")), "observations_csv": self.get("/sample-observations")}
        for kwargs in ({"token": "wrong"}, {"origin": "http://evil.example"}):
            with self.assertRaises(HTTPError) as failed:
                self.post(payload, **kwargs)
            self.assertEqual(failed.exception.code, 403)

    def test_input_errors_are_returned_without_report(self):
        with self.assertRaises(HTTPError) as failed:
            self.post({"scenario_json": '{"scenario_id":"first","scenario_id":"second"}'})
        self.assertEqual(failed.exception.code, 400)
        self.assertIn("duplicate field", failed.exception.read().decode("utf-8"))
        with self.assertRaises(HTTPError) as failed:
            self.post({"scenario_json": "[" * 10_000 + "0" + "]" * 10_000})
        self.assertEqual(failed.exception.code, 400)
        self.assertIn("nesting exceeds parser limit", failed.exception.read().decode("utf-8"))
        with self.assertRaises(HTTPError) as failed:
            self.post({"scenario_json": json.dumps(json.loads(self.get("/sample-config"))), "observations_csv": self.get("/sample-observations"), "scenario": {}})
        self.assertEqual(failed.exception.code, 400)
        with self.assertRaises(HTTPError) as failed:
            self.post({"scenario": {"scenario_id": "bad"}})
        self.assertEqual(failed.exception.code, 400)
        self.assertIn("schema_version", failed.exception.read().decode("utf-8"))
        with self.assertRaises(HTTPError) as failed:
            self.post({"scenario": {"schema_version": 1, "scenario_id": "bad"}})
        self.assertEqual(failed.exception.code, 400)
        self.assertIn("currency", failed.exception.read().decode("utf-8"))
        config = json.loads(self.get("/sample-config"))
        config["regions"][0]["price_usd_gpu_hour"] = "1e100"
        with self.assertRaises(HTTPError) as failed:
            self.post({"scenario": config, "observations_csv": self.get("/sample-observations")})
        self.assertEqual(failed.exception.code, 400)
        self.assertIn("numeric range", failed.exception.read().decode("utf-8"))
        oversized_integer = b'{"scenario":{"hours":' + b'9' * 5000 + b'}}'
        request = Request(
            self.base + "/run", data=oversized_integer, method="POST",
            headers={"Content-Type": "application/json", "Origin": self.base, "X-SW004-Token": "test-only-session-token"},
        )
        with self.assertRaises(HTTPError) as failed:
            urlopen(request, timeout=3)
        self.assertEqual(failed.exception.code, 400)

    def test_browser_comparison_reports_downside_and_rejects_bad_origin(self):
        base = json.loads(self.get("/sample-config"))
        observations = self.get("/sample-observations")
        from sw004_simulator import parse_observations_csv
        base["observations"] = parse_observations_csv(observations)
        downside = copy.deepcopy(base)
        downside["software_usd"] = "1000"
        payload = {"cases": [{"name": "base", "scenario": base}, {"name": "downside", "scenario": downside}]}
        report = self.post(payload, path="/compare")["comparison"]
        self.assertEqual(report["minimum_net_current_cash_delta_usd"], "-712.72")
        self.assertEqual(report["maximum_net_current_cash_delta_usd"], "279.28")
        self.assertTrue(report["exported_utc"].endswith("Z"))
        self.assertIn("Compare scenarios", self.get("/"))
        raw_cases = {"cases": [{"name": case["name"], "scenario_json": json.dumps(case["scenario"])} for case in payload["cases"]]}
        self.assertEqual(self.post(raw_cases, path="/compare")["comparison"]["case_count"], 2)
        with self.assertRaises(HTTPError) as failed:
            self.post(payload, path="/compare", origin="http://evil.example")
        self.assertEqual(failed.exception.code, 403)
        payload["cases"][0]["name"] = 42
        with self.assertRaises(HTTPError) as failed:
            self.post(payload, path="/compare")
        self.assertEqual(failed.exception.code, 400)

    def test_stalled_local_request_releases_single_threaded_server(self):
        server = HTTPServer(("127.0.0.1", 0), ShortTimeoutHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        base = f"http://127.0.0.1:{server.server_port}"
        try:
            with socket.create_connection(("127.0.0.1", server.server_port), timeout=3) as client:
                client.settimeout(3)
                request = (
                    f"POST /run HTTP/1.1\r\nHost: 127.0.0.1:{server.server_port}\r\n"
                    f"Origin: {base}\r\nX-SW004-Token: test-only-session-token\r\n"
                    "Content-Type: application/json\r\nContent-Length: 100\r\n\r\n{}"
                )
                client.sendall(request.encode("ascii"))
                self.assertIn(b"408 Request Timeout", client.recv(4096))
            with urlopen(base + "/health", timeout=3) as response:
                self.assertEqual(json.loads(response.read())["status"], "ok")
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=3)

    def test_slow_header_peer_does_not_block_health(self):
        server = BoundedHTTPServer(("127.0.0.1", 0), LongTimeoutHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        base = f"http://127.0.0.1:{server.server_port}"
        try:
            with socket.create_connection(("127.0.0.1", server.server_port), timeout=3) as client:
                client.sendall(b"GET /health HTTP/1.1\r\nHost: 127.0.0.1:")
                deadline = time.monotonic() + 1
                while server._worker_slots._value == MAX_HTTP_WORKERS and time.monotonic() < deadline:
                    time.sleep(0.005)
                self.assertEqual(server._worker_slots._value, MAX_HTTP_WORKERS - 1)
                with urlopen(base + "/health", timeout=0.5) as response:
                    self.assertEqual(json.loads(response.read())["status"], "ok")
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=3)

    def test_excess_local_request_gets_503(self):
        server = BoundedHTTPServer(("127.0.0.1", 0), ShortTimeoutHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        for _ in range(MAX_HTTP_WORKERS):
            server._worker_slots.acquire()
        try:
            with self.assertRaises(HTTPError) as failed:
                urlopen(f"http://127.0.0.1:{server.server_port}/health", timeout=3)
            self.assertEqual(failed.exception.code, 503)
        finally:
            for _ in range(MAX_HTTP_WORKERS):
                server._worker_slots.release()
            server.shutdown()
            server.server_close()
            thread.join(timeout=3)


    def test_sample_logs_and_demo_video_endpoints(self):
        sample_logs = self.get("/sample-logs")
        self.assertIn("timestamp,origin_region,model", sample_logs)
        demo_html = self.get("/demo-video")
        self.assertIn("INFERACAP INTERACTIVE SHOWCASE", demo_html)

    def test_scan_logs_and_prompt_tester_post_endpoints(self):
        sample_logs = self.get("/sample-logs")
        res = self.post({"logs_csv": sample_logs[:1500]}, path="/scan-logs")
        self.assertEqual(res["status"], "ok")
        self.assertIn("baseline_compute_usd", res)
        self.assertIn("net_savings_usd", res)

        prompt_res = self.post({"prompt": "Test query", "origin_region": "US", "ttft_budget_ms": 300}, path="/test-gateway-prompt")
        self.assertEqual(prompt_res["status"], "success")
        self.assertIn("served_region", prompt_res)


if __name__ == "__main__":
    unittest.main()
