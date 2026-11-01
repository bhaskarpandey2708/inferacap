"""High-Performance Async Live Gateway Server for InferaCap."""

from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Optional
from urllib.parse import urlparse
import urllib.request
import urllib.error

from .config import GatewayConfig
from .router import LiveEconomicRouter, RouteDecision

logger = logging.getLogger("inferacap.server")


class LiveGatewayServer:
    """Async HTTP Reverse Proxy and Router compatible with OpenAI API specifications."""

    def __init__(self, config: GatewayConfig, router: Optional[LiveEconomicRouter] = None):
        self.config = config
        self.router = router or LiveEconomicRouter(config)
        self.start_time = time.time()
        self.server: Optional[asyncio.AbstractServer] = None

    async def start(self) -> None:
        """Start the async HTTP server listening for client connections."""
        self.server = await asyncio.start_server(
            self._handle_client,
            self.config.listen_host,
            self.config.listen_port,
        )
        logger.info(
            f"InferaCap Live Gateway running on http://{self.config.listen_host}:{self.config.listen_port}"
        )

    async def stop(self) -> None:
        """Gracefully stop the server."""
        if self.server:
            self.server.close()
            await self.server.wait_closed()
            logger.info("InferaCap Live Gateway stopped.")

    async def _handle_client(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        """Parse HTTP/1.1 request and dispatch to corresponding handler."""
        try:
            line = await reader.readline()
            if not line:
                writer.close()
                await writer.wait_closed()
                return

            request_line = line.decode("iso-8859-1").strip()
            parts = request_line.split(" ")
            if len(parts) < 2:
                writer.close()
                await writer.wait_closed()
                return

            method, path = parts[0], parts[1]

            # Parse headers
            headers = {}
            while True:
                header_line = await reader.readline()
                if not header_line or header_line in (b"\r\n", b"\n"):
                    break
                decoded = header_line.decode("iso-8859-1").strip()
                if ":" in decoded:
                    k, v = decoded.split(":", 1)
                    headers[k.strip().lower()] = v.strip()

            content_length = int(headers.get("content-length", 0))
            body = b""
            if content_length > 0:
                body = await reader.readexactly(content_length)

            # Routing endpoints
            if method == "GET" and path in ("/health", "/v1/health"):
                await self._send_json(
                    writer, 200, {
                        "status": "healthy",
                        "gateway_id": self.config.gateway_id,
                        "uptime_seconds": time.time() - self.start_time,
                    }
                )
            elif method == "GET" and path in ("/v1/metrics", "/metrics"):
                await self._send_json(writer, 200, self.router.get_metrics())
            elif method == "GET" and path in ("/v1/analytics", "/analytics"):
                await self._send_json(writer, 200, self.router.get_analytics())
            elif method == "GET" and path == "/v1/models":
                models = set()
                for reg in self.config.regions.values():
                    models.update(reg.models)
                model_list = [
                    {"id": m, "object": "model", "owned_by": "inferacap-federation"}
                    for m in sorted(models)
                ]
                await self._send_json(writer, 200, {"object": "list", "data": model_list})
            elif method == "GET" and path == "/v1/routes":
                routes_data = [
                    {
                        "origin": r.origin_region,
                        "destination": r.destination_region,
                        "model": r.model,
                        "residency_permission": r.residency_permission,
                        "estimated_rtt_ms": r.estimated_rtt_ms,
                        "egress_cost_per_gb": r.egress_cost_per_gb,
                    }
                    for r in self.config.allowed_routes
                ]
                await self._send_json(writer, 200, {"allowed_routes": routes_data})
            elif method == "GET" and path in ("/v1/nodes", "/nodes"):
                nodes_info = {}
                for r_name, r_cfg in self.config.regions.items():
                    nodes_info[r_name] = {
                        "backends": r_cfg.backends,
                        "models": r_cfg.models,
                        "capacity": r_cfg.capacity_concurrent_requests,
                        "active_concurrency": self.router.active_concurrency.get(r_name, 0),
                        "billing_type": r_cfg.billing_type,
                        "hourly_cost_usd": r_cfg.on_demand_rate_gpu_hour,
                    }
                await self._send_json(writer, 200, {"regions": nodes_info})
            elif method == "POST" and path == "/v1/nodes/register":
                try:
                    payload = json.loads(body.decode("utf-8")) if body else {}
                    node_id = payload.get("node_id", f"node-{int(time.time())}")
                    region = payload.get("region", "KAGGLE")
                    base_url = payload.get("base_url")
                    if not base_url:
                        await self._send_json(writer, 400, {"error": "Missing 'base_url' in registration payload"})
                        return
                    models = payload.get("models", ["llama-3.1-8b"])
                    capacity = int(payload.get("capacity", 4))
                    billing_type = payload.get("billing_type", "owned")
                    hourly_cost = float(payload.get("hourly_cost_usd", 0.0))
                    estimated_rtt_ms = float(payload.get("estimated_rtt_ms", 80.0))

                    reg_res = await self.router.register_dynamic_node(
                        node_id=node_id,
                        region_name=region,
                        base_url=base_url,
                        models=models,
                        capacity=capacity,
                        billing_type=billing_type,
                        hourly_cost=hourly_cost,
                        estimated_rtt_ms=estimated_rtt_ms,
                    )
                    await self._send_json(writer, 200, reg_res)
                except Exception as ex:
                    await self._send_json(writer, 400, {"error": f"Invalid registration payload: {ex}"})
            elif method == "POST" and path in ("/v1/chat/completions", "/v1/completions"):
                await self._handle_completion(reader, writer, path, headers, body)
            else:
                await self._send_json(writer, 404, {"error": f"Endpoint {path} not found"})

        except Exception as e:
            logger.exception("Error handling HTTP request")
            try:
                await self._send_json(writer, 500, {"error": str(e)})
            except Exception:
                pass
        finally:
            try:
                writer.close()
                await writer.wait_closed()
            except Exception:
                pass

    async def _handle_completion(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
        path: str,
        headers: dict,
        body: bytes,
    ) -> None:
        """Handle live OpenAI chat/text completions request."""
        try:
            payload = json.loads(body.decode("utf-8"))
        except Exception:
            await self._send_json(writer, 400, {"error": "Invalid JSON body"})
            return

        model = payload.get("model", "")
        origin_region = headers.get("x-region", headers.get("cf-ipcountry", "US")).upper()
        ttft_budget = float(headers["x-ttft-budget-ms"]) if "x-ttft-budget-ms" in headers else None
        session_id = headers.get("x-session-id") or headers.get("x-conversation-id") or payload.get("user")

        # Execute Economic and Cache-Affinity Routing Decision
        decision = await self.router.select_route(
            origin_region=origin_region,
            model=model,
            ttft_budget_ms=ttft_budget,
            estimated_payload_bytes=len(body),
            session_id=session_id,
        )

        if decision.route_type == "REJECTED":
            await self._send_json(
                writer,
                503,
                {
                    "error": {
                        "message": decision.rejection_reason,
                        "type": "capacity_residency_exhaustion",
                        "code": 503,
                    }
                },
                extra_headers={
                    "X-InferaCap-Status": "REJECTED",
                    "X-InferaCap-Origin": origin_region,
                },
            )
            return

        # Forward request to chosen backend
        target_url = decision.target_backend_url.rstrip("/") + path
        stream = bool(payload.get("stream", False))

        # 1. Handle Streaming Completion (Server-Sent Events)
        if stream:
            try:
                start_req = time.time()
                first_chunk_recorded = False

                def _open_stream():
                    req = urllib.request.Request(
                        target_url,
                        data=body,
                        headers={
                            "Content-Type": "application/json",
                            "User-Agent": "InferaCap-Live-Gateway/1.0",
                        },
                        method="POST",
                    )
                    return urllib.request.urlopen(req, timeout=self.config.request_timeout_seconds)

                resp = await asyncio.to_thread(_open_stream)

                extra_headers = [
                    "HTTP/1.1 200 OK",
                    "Content-Type: text/event-stream; charset=utf-8",
                    "Cache-Control: no-cache",
                    "Connection: close",
                    f"X-InferaCap-Origin-Region: {decision.origin_region}",
                    f"X-InferaCap-Served-Region: {decision.target_region}",
                    f"X-InferaCap-Route-Type: {decision.route_type}",
                    f"X-InferaCap-Session-Affinity: {'PINNED' if 'AFFINITY' in decision.route_type else ('INITIALIZED' if session_id else 'NONE')}",
                    f"X-InferaCap-Estimated-Savings-USD: {decision.estimated_savings_usd:.6f}",
                    f"X-InferaCap-Estimated-Egress-USD: {decision.estimated_egress_usd:.6f}",
                    f"X-InferaCap-Estimated-RTT-MS: {decision.estimated_rtt_ms:.1f}",
                    "\r\n",
                ]
                writer.write("\r\n".join(extra_headers).encode("iso-8859-1"))
                await writer.drain()

                # Stream chunks asynchronously
                while True:
                    line = await asyncio.to_thread(resp.readline)
                    if not line:
                        break
                    if not first_chunk_recorded:
                        first_chunk_recorded = True
                        ttft_ms = (time.time() - start_req) * 1000
                        logger.info(f"⚡ Stream First Token (TTFT): {ttft_ms:.1f}ms from [{decision.target_region}]")

                    writer.write(line)
                    await writer.drain()

                resp.close()
                self.router.report_backend_success(decision.target_backend_url, decision.target_region)
                self.router.record_feature_interaction("live_routing")

            except Exception as e:
                self.router.report_backend_failure(decision.target_backend_url, decision.target_region, str(e))
                logger.error(f"Error streaming from backend {target_url}: {e}")
                try:
                    await self._send_json(writer, 502, {"error": f"Backend stream failed: {e}"})
                except Exception:
                    pass
            finally:
                await self.router.release_route(decision.target_region)
            return

        # 2. Handle Non-Streaming Completion
        try:
            start_t = time.time()
            # Execute backend dispatch in async worker thread
            resp_status, resp_headers, resp_body = await asyncio.to_thread(
                self._dispatch_backend, target_url, headers, body
            )
            elapsed_ms = (time.time() - start_t) * 1000

            if resp_status < 500:
                self.router.report_backend_success(decision.target_backend_url, decision.target_region, elapsed_ms)
            else:
                self.router.report_backend_failure(
                    decision.target_backend_url, decision.target_region, f"HTTP {resp_status}"
                )
            self.router.record_feature_interaction("live_routing")

            extra_response_headers = {
                "X-InferaCap-Origin-Region": decision.origin_region,
                "X-InferaCap-Served-Region": decision.target_region,
                "X-InferaCap-Route-Type": decision.route_type,
                "X-InferaCap-Session-Affinity": "PINNED" if "AFFINITY" in decision.route_type else ("INITIALIZED" if session_id else "NONE"),
                "X-InferaCap-Estimated-Savings-USD": f"{decision.estimated_savings_usd:.6f}",
                "X-InferaCap-Estimated-Egress-USD": f"{decision.estimated_egress_usd:.6f}",
                "X-InferaCap-Estimated-RTT-MS": f"{decision.estimated_rtt_ms:.1f}",
            }

            # Send headers
            header_lines = [f"HTTP/1.1 {resp_status} OK"]
            for hk, hv in resp_headers.items():
                if hk.lower() not in ("content-length", "transfer-encoding", "connection"):
                    header_lines.append(f"{hk}: {hv}")
            for ehk, ehv in extra_response_headers.items():
                header_lines.append(f"{ehk}: {ehv}")
            header_lines.append(f"Content-Length: {len(resp_body)}")
            header_lines.append("Connection: close")
            header_lines.append("\r\n")

            writer.write("\r\n".join(header_lines).encode("iso-8859-1"))
            writer.write(resp_body)
            await writer.drain()

        except Exception as e:
            self.router.report_backend_failure(decision.target_backend_url, decision.target_region, str(e))
            logger.error(f"Error dispatching to backend {target_url}: {e}")
            await self._send_json(writer, 502, {"error": f"Backend dispatch error: {e}"})

        finally:
            # Release concurrency on chosen region
            await self.router.release_route(decision.target_region)

    def _dispatch_backend(
        self, target_url: str, headers: dict, body: bytes
    ) -> tuple[int, dict, bytes]:
        """Synchronous HTTP dispatch to regional backend."""
        req = urllib.request.Request(
            target_url,
            data=body,
            headers={
                "Content-Type": "application/json",
                "User-Agent": "InferaCap-Live-Gateway/1.0",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=self.config.request_timeout_seconds) as resp:
                resp_headers = dict(resp.getheaders())
                resp_body = resp.read()
                return resp.status, resp_headers, resp_body
        except urllib.error.HTTPError as e:
            return e.code, dict(e.headers), e.read()

    async def _send_json(
        self,
        writer: asyncio.StreamWriter,
        status: int,
        data: dict,
        extra_headers: Optional[dict] = None,
    ) -> None:
        body = json.dumps(data, indent=2).encode("utf-8")
        headers = [
            f"HTTP/1.1 {status} OK",
            "Content-Type: application/json; charset=utf-8",
            f"Content-Length: {len(body)}",
            "Connection: close",
        ]
        if extra_headers:
            for k, v in extra_headers.items():
                headers.append(f"{k}: {v}")
        headers.append("\r\n")
        writer.write("\r\n".join(headers).encode("iso-8859-1"))
        writer.write(body)
        await writer.drain()
