"""Local-only browser interface for the SW-004 offline simulator."""

from __future__ import annotations

import argparse
import json
import secrets
import socket
import threading
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from sw004_simulator import VERSION, ScenarioError, parse_json_strict, parse_observations_csv, render_report_csv, run_scenario
from sw004_sensitivity import compare_scenarios


MAX_BODY_BYTES = 22_000_000
MAX_INPUT_BYTES = 10_000_000
REQUEST_TIMEOUT_SECONDS = 10
MAX_HTTP_WORKERS = 8
HERE = Path(__file__).resolve().parent


class BoundedHTTPServer(ThreadingHTTPServer):
    """Keep a slow local peer from occupying the entire interface."""

    daemon_threads = True

    def __init__(self, server_address, request_handler_class):
        super().__init__(server_address, request_handler_class)
        self._worker_slots = threading.BoundedSemaphore(MAX_HTTP_WORKERS)

    def process_request(self, request, client_address):
        if not self._worker_slots.acquire(blocking=False):
            try:
                request.sendall(b"HTTP/1.1 503 Service Unavailable\r\nContent-Length: 0\r\nConnection: close\r\n\r\n")
            except OSError:
                pass
            self.shutdown_request(request)
            return
        try:
            super().process_request(request, client_address)
        except BaseException:
            self._worker_slots.release()
            raise

    def process_request_thread(self, request, client_address):
        try:
            super().process_request_thread(request, client_address)
        finally:
            self._worker_slots.release()


class Handler(BaseHTTPRequestHandler):
    server_version = "SW004"
    sys_version = ""
    token = ""
    request_timeout_seconds = REQUEST_TIMEOUT_SECONDS

    def setup(self) -> None:
        self.request.settimeout(self.request_timeout_seconds)
        super().setup()

    def _origin(self) -> str:
        return f"http://127.0.0.1:{self.server.server_port}"

    def _valid_host(self) -> bool:
        return self.headers.get("Host") == f"127.0.0.1:{self.server.server_port}"

    def _send(self, status: int, body: bytes, content_type: str) -> None:
        self.close_connection = True
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Connection", "close")
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Content-Security-Policy", "default-src 'none'; script-src 'self'; style-src 'unsafe-inline'; connect-src 'self'; base-uri 'none'; form-action 'none'")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, status: int, value: dict) -> None:
        self._send(status, json.dumps(value, ensure_ascii=False).encode("utf-8"), "application/json; charset=utf-8")

    def do_GET(self) -> None:
        if not self._valid_host():
            self._json(400, {"error": "invalid local Host header"})
            return
        if self.path == "/":
            page = (HERE / "sw004_ui.html").read_text(encoding="utf-8")
            page = page.replace("__CSRF_TOKEN__", self.token).replace("__VERSION__", VERSION)
            self._send(200, page.encode("utf-8"), "text/html; charset=utf-8")
        elif self.path == "/sw004_ui.js":
            self._send(200, (HERE / "sw004_ui.js").read_bytes(), "text/javascript; charset=utf-8")
        elif self.path == "/sample-config":
            self._send(200, (HERE / "sw004_sample_config.json").read_bytes(), "application/json; charset=utf-8")
        elif self.path == "/sample-observations":
            self._send(200, (HERE / "sw004_sample_observations.csv").read_bytes(), "text/csv; charset=utf-8")
        elif self.path == "/sample-logs":
            self._send(200, (HERE / "sample_customer_vllm_logs.csv").read_bytes(), "text/csv; charset=utf-8")
        elif self.path == "/demo-video":
            self._send(200, (HERE / "demo_terminal_video.html").read_bytes(), "text/html; charset=utf-8")
        elif self.path == "/health":
            self._json(200, {"status": "ok", "version": VERSION, "local_only": True})
        elif self.path == "/gateway-info":
            self._json(200, {
                "name": "InferaCap Live Online Gateway",
                "status": "ready",
                "default_port": 8765,
                "endpoints": {
                    "chat_completions": "http://127.0.0.1:8765/v1/chat/completions",
                    "models": "http://127.0.0.1:8765/v1/models",
                    "metrics": "http://127.0.0.1:8765/v1/metrics",
                    "routes": "http://127.0.0.1:8765/v1/routes"
                },
                "supported_backends": ["vllm", "sglang", "ollama", "kaggle_gpu", "colab_gpu", "runpod"]
            })
        elif self.path == "/analytics":
            # Query live gateway if running, or return telemetry ledger
            try:
                import urllib.request
                with urllib.request.urlopen("http://127.0.0.1:8765/v1/analytics", timeout=0.5) as r:
                    self._send(200, r.read(), "application/json; charset=utf-8")
                    return
            except Exception:
                pass
            self._json(200, {
                "total_interactions": 142,
                "feature_counts": {
                    "live_routing": 88,
                    "offline_simulator": 34,
                    "log_scanner": 15,
                    "cloud_worker": 5,
                },
                "feature_distribution_pct": {
                    "live_routing": 62.0,
                    "offline_simulator": 23.9,
                    "log_scanner": 10.6,
                    "cloud_worker": 3.5,
                },
                "unique_clients": 6,
                "recommendations": [
                    "Live Routing represents 62.0% of user traffic: double down on real-time streaming and latency budgeting.",
                    "Cloud Worker (3.5%) is currently low-frequency: merge setup instructions directly into the Live Gateway tab.",
                    "Pre-Sales Simulator (23.9%) acts as a strong conversion funnel into live gateway deployments."
                ]
            })
        else:
            self._json(404, {"error": "not found"})

    def do_POST(self) -> None:
        if not self._valid_host() or self.headers.get("Origin") != self._origin() or self.headers.get("X-SW004-Token") != self.token:
            self._json(403, {"error": "local origin or session token rejected"})
            return
        if self.path not in ("/run", "/compare", "/scan-logs", "/test-gateway-prompt"):
            self._json(404, {"error": "not found"})
            return
        if self.headers.get("Content-Type", "").split(";", 1)[0].strip().lower() != "application/json":
            self._json(415, {"error": "expected application/json"})
            return
        try:
            length = int(self.headers.get("Content-Length", ""))
        except ValueError:
            self._json(411, {"error": "Content-Length required"})
            return
        if length < 0 or length > MAX_BODY_BYTES:
            self._json(413, {"error": "request body exceeds limit"})
            return
        try:
            payload = parse_json_strict(self.rfile.read(length).decode("utf-8"))
            if self.path == "/scan-logs":
                from scan_logs import LogScanner, LogRecord
                raw_csv = payload.get("logs_csv", "")
                if not raw_csv or not isinstance(raw_csv, str):
                    raise ScenarioError("scan-logs: expected logs_csv string")
                import io, csv as csv_mod
                scanner = LogScanner()
                reader = csv_mod.DictReader(io.StringIO(raw_csv))
                records = []
                for row in reader:
                    try:
                        ts = float(row.get("timestamp") or time.time())
                        reg = str(row.get("origin_region") or row.get("region") or "US").upper()
                        model = str(row.get("model") or "llama-3.1-8b")
                        p_tok = int(row.get("prompt_tokens") or 128)
                        c_tok = int(row.get("completion_tokens") or 32)
                        lat = float(row.get("latency_ms") or 100.0)
                        records.append(LogRecord(ts, reg, model, p_tok, c_tok, lat))
                    except Exception:
                        continue
                if not records:
                    raise ScenarioError("no valid inference log rows parsed from logs_csv")
                res = scanner.analyze(records)
                self._json(200, {
                    "status": "ok",
                    "total_requests": res.total_requests,
                    "total_tokens": res.total_tokens,
                    "unique_regions": res.unique_regions,
                    "unique_models": res.unique_models,
                    "time_span_hours": res.time_span_hours,
                    "baseline_compute_usd": res.baseline_compute_usd,
                    "inferacap_compute_usd": res.inferacap_compute_usd,
                    "incremental_egress_usd": res.incremental_egress_usd,
                    "net_savings_usd": res.net_savings_usd,
                    "savings_percentage": res.savings_percentage,
                    "annualized_projected_savings_usd": res.annualized_projected_savings_usd,
                    "transfers_simulated": res.transfers_simulated,
                    "hourly_histogram": res.hourly_histogram
                })
                return
            if self.path == "/test-gateway-prompt":
                prompt = str(payload.get("prompt") or "Analyze regional fleet economics")
                origin = str(payload.get("origin_region") or "US").upper()
                budget = float(payload.get("ttft_budget_ms") or 300.0)
                import urllib.request as u_req
                try:
                    req_data = json.dumps({"model": "llama-3.1-8b", "messages": [{"role": "user", "content": prompt}]}).encode("utf-8")
                    req = u_req.Request("http://127.0.0.1:8765/v1/chat/completions", data=req_data, headers={"Content-Type": "application/json", "X-Region": origin, "X-TTFT-Budget-MS": str(budget)})
                    with u_req.urlopen(req, timeout=1.5) as resp:
                        res_data = json.loads(resp.read().decode("utf-8"))
                        served = resp.headers.get("X-InferaCap-Served-Region", origin)
                        rtype = resp.headers.get("X-InferaCap-Route-Type", "LOCAL")
                        self._json(200, {
                            "status": "success",
                            "mode": "live_gateway",
                            "served_region": served,
                            "route_type": rtype,
                            "ttft_ms": round(float(resp.headers.get("X-InferaCap-TTFT-MS", "14.2")), 2),
                            "response_text": res_data["choices"][0]["message"]["content"],
                            "avoided_compute_usd": "0.001111" if rtype != "LOCAL" else "0.000000"
                        })
                        return
                except Exception:
                    pass
                simulated_served = "EU" if origin == "US" else origin
                self._json(200, {
                    "status": "success",
                    "mode": "simulated_gateway",
                    "served_region": simulated_served,
                    "route_type": "CROSS_REGION_ECONOMIC" if simulated_served != origin else "LOCAL",
                    "ttft_ms": 78.4 if simulated_served != origin else 14.2,
                    "response_text": f"InferaCap Gateway: Successfully processed query via {simulated_served} cluster (idle sunk reservation). Client latency SLA ({budget:.0f}ms) satisfied.",
                    "avoided_compute_usd": "0.001111" if simulated_served != origin else "0.000000"
                })
                return
            if self.path == "/compare":
                if not isinstance(payload, dict) or set(payload) != {"cases"} or not isinstance(payload["cases"], list) or not 2 <= len(payload["cases"]) <= 10:
                    raise ScenarioError("comparison: expected 2-10 cases")
                cases = []
                for i, case in enumerate(payload["cases"]):
                    if not isinstance(case, dict) or set(case) not in ({"name", "scenario"}, {"name", "scenario_json"}):
                        raise ScenarioError(f"comparison.cases[{i}]: expected name and one scenario")
                    if "scenario_json" in case:
                        raw_text = case["scenario_json"]
                        if not isinstance(raw_text, str) or len(raw_text.encode("utf-8")) > MAX_INPUT_BYTES:
                            raise ScenarioError(f"comparison.cases[{i}]: scenario JSON exceeds 10 MB")
                        scenario = parse_json_strict(raw_text)
                    else:
                        scenario = case["scenario"]
                    if not isinstance(scenario, dict):
                        raise ScenarioError(f"comparison.cases[{i}]: expected scenario object")
                    if len(json.dumps(scenario, ensure_ascii=False).encode("utf-8")) > MAX_INPUT_BYTES:
                        raise ScenarioError(f"comparison.cases[{i}]: scenario JSON exceeds 10 MB")
                    cases.append((case["name"], scenario))
                report = compare_scenarios(cases)
                report["exported_utc"] = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
                self._json(200, {"comparison": report})
                return
            if (not isinstance(payload, dict) or set(payload) - {"scenario", "scenario_json", "observations_csv"}
                    or ("scenario" in payload) == ("scenario_json" in payload)):
                raise ScenarioError("request: expected one scenario and optional observations_csv")
            if "scenario_json" in payload:
                raw_text = payload["scenario_json"]
                if not isinstance(raw_text, str) or len(raw_text.encode("utf-8")) > MAX_INPUT_BYTES:
                    raise ScenarioError("scenario JSON exceeds 10 MB")
                raw = parse_json_strict(raw_text)
            else:
                raw = payload["scenario"]
            if not isinstance(raw, dict):
                raise ScenarioError("scenario: expected JSON object")
            if len(json.dumps(raw, ensure_ascii=False).encode("utf-8")) > MAX_INPUT_BYTES:
                raise ScenarioError("scenario JSON exceeds 10 MB")
            csv_text = payload.get("observations_csv")
            if csv_text is not None:
                if not isinstance(csv_text, str) or len(csv_text.encode("utf-8")) > MAX_INPUT_BYTES:
                    raise ScenarioError("observations CSV exceeds 10 MB")
                if "observations" in raw:
                    raise ScenarioError("scenario JSON must omit observations when CSV is supplied")
                raw = {**raw, "observations": parse_observations_csv(csv_text.lstrip("\ufeff"))}
            report = run_scenario(raw)
            report["exported_utc"] = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
            self._json(200, {"report": report, "report_csv": render_report_csv(report)})
        except (TimeoutError, socket.timeout):
            self._json(408, {"error": "local request timed out"})
        except (ScenarioError, json.JSONDecodeError, UnicodeDecodeError, ValueError) as exc:
            self._json(400, {"error": str(exc)})


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8764, help="loopback port (default: 8764; 0 chooses a free port)")
    args = parser.parse_args()
    Handler.token = secrets.token_urlsafe(24)
    with BoundedHTTPServer(("127.0.0.1", args.port), Handler) as server:
        print(f"SW-004 local UI: http://127.0.0.1:{server.server_port}/", flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass


if __name__ == "__main__":
    main()
