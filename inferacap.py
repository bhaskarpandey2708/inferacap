"""InferaCap Official Python SDK.

Zero-dependency, high-performance client library for the InferaCap
Economically-Aware Multi-Region Inference Load Balancer.

Compatible with Python 3.9+ and standard library only.
"""

from __future__ import annotations

import json
import logging
import time
import urllib.request
import urllib.error
from dataclasses import dataclass
from typing import Any, Dict, Iterator, List, Optional

logger = logging.getLogger("inferacap.client")


@dataclass
class InferaCapResponse:
    content: str
    model: str
    id: str
    origin_region: str
    served_region: str
    route_type: str
    estimated_savings_usd: float
    estimated_egress_usd: float
    latency_ms: float
    usage: Dict[str, int]
    raw_payload: Dict[str, Any]


@dataclass
class InferaCapStreamChunk:
    delta: str
    model: str
    id: str
    finish_reason: Optional[str]
    served_region: str
    route_type: str
    ttft_ms: Optional[float] = None


class InferaCapError(Exception):
    """Base exception for InferaCap client errors."""
    def __init__(self, message: str, status_code: int = 500, error_type: str = "inferacap_error"):
        super().__init__(message)
        self.status_code = status_code
        self.error_type = error_type


class InferaCap:
    """Official Python Client for InferaCap Intelligent Load Balancer."""

    def __init__(
        self,
        base_url: str = "http://127.0.0.1:8765/v1",
        api_key: Optional[str] = "inferacap-default-key",
        origin_region: str = "US",
        default_ttft_budget_ms: float = 400.0,
        timeout_seconds: float = 30.0,
    ):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.origin_region = origin_region.upper()
        self.default_ttft_budget_ms = default_ttft_budget_ms
        self.timeout_seconds = timeout_seconds

    def _get_headers(self, ttft_budget: Optional[float] = None) -> Dict[str, str]:
        budget = ttft_budget if ttft_budget is not None else self.default_ttft_budget_ms
        headers = {
            "Content-Type": "application/json",
            "User-Agent": "InferaCap-Python-SDK/1.0",
            "X-Region": self.origin_region,
            "X-TTFT-Budget-MS": str(budget),
        }
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    def chat(
        self,
        model: str,
        messages: List[Dict[str, str]],
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
        ttft_budget_ms: Optional[float] = None,
        extra_headers: Optional[Dict[str, str]] = None,
    ) -> InferaCapResponse:
        """Send chat completion request through InferaCap economic load balancer."""
        url = f"{self.base_url}/chat/completions"
        payload = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "stream": False,
        }
        if max_tokens is not None:
            payload["max_tokens"] = max_tokens

        req_headers = self._get_headers(ttft_budget_ms)
        if extra_headers:
            req_headers.update(extra_headers)

        body = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(url, data=body, headers=req_headers, method="POST")

        start = time.time()
        try:
            with urllib.request.urlopen(req, timeout=self.timeout_seconds) as resp:
                elapsed_ms = (time.time() - start) * 1000
                data = json.loads(resp.read().decode("utf-8"))
                hdrs = {k.lower(): v for k, v in resp.getheaders()}

                content = ""
                if "choices" in data and data["choices"]:
                    content = data["choices"][0].get("message", {}).get("content", "")

                return InferaCapResponse(
                    content=content,
                    model=data.get("model", model),
                    id=data.get("id", ""),
                    origin_region=hdrs.get("x-inferacap-origin-region", self.origin_region),
                    served_region=hdrs.get("x-inferacap-served-region", "UNKNOWN"),
                    route_type=hdrs.get("x-inferacap-route-type", "LOCAL"),
                    estimated_savings_usd=float(hdrs.get("x-inferacap-estimated-savings-usd", 0.0)),
                    estimated_egress_usd=float(hdrs.get("x-inferacap-estimated-egress-usd", 0.0)),
                    latency_ms=elapsed_ms,
                    usage=data.get("usage", {}),
                    raw_payload=data,
                )
        except urllib.error.HTTPError as e:
            err_body = e.read().decode("utf-8")
            try:
                err_data = json.loads(err_body)
                err_msg = err_data.get("error", {}).get("message", err_body)
                err_type = err_data.get("error", {}).get("type", "http_error")
            except Exception:
                err_msg = err_body
                err_type = "http_error"
            raise InferaCapError(err_msg, status_code=e.code, error_type=err_type) from e

    def chat_stream(
        self,
        model: str,
        messages: List[Dict[str, str]],
        temperature: float = 0.7,
        ttft_budget_ms: Optional[float] = None,
        extra_headers: Optional[Dict[str, str]] = None,
    ) -> Iterator[InferaCapStreamChunk]:
        """Stream chat tokens via Server-Sent Events (SSE) with live TTFT tracking."""
        url = f"{self.base_url}/chat/completions"
        payload = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "stream": True,
        }

        req_headers = self._get_headers(ttft_budget_ms)
        if extra_headers:
            req_headers.update(extra_headers)

        body = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(url, data=body, headers=req_headers, method="POST")

        start = time.time()
        first_chunk = True
        try:
            with urllib.request.urlopen(req, timeout=self.timeout_seconds) as resp:
                hdrs = {k.lower(): v for k, v in resp.getheaders()}
                served_region = hdrs.get("x-inferacap-served-region", "UNKNOWN")
                route_type = hdrs.get("x-inferacap-route-type", "LOCAL")

                for line_b in resp:
                    line = line_b.decode("utf-8").strip()
                    if not line:
                        continue
                    if line.startswith("data: "):
                        raw_data = line[6:].strip()
                        if raw_data == "[DONE]":
                            break
                        try:
                            chunk_data = json.loads(raw_data)
                            delta = ""
                            finish = None
                            if "choices" in chunk_data and chunk_data["choices"]:
                                delta = chunk_data["choices"][0].get("delta", {}).get("content", "")
                                finish = chunk_data["choices"][0].get("finish_reason")

                            ttft = (time.time() - start) * 1000 if first_chunk else None
                            first_chunk = False

                            yield InferaCapStreamChunk(
                                delta=delta,
                                model=chunk_data.get("model", model),
                                id=chunk_data.get("id", ""),
                                finish_reason=finish,
                                served_region=served_region,
                                route_type=route_type,
                                ttft_ms=ttft,
                            )
                        except Exception:
                            continue
        except urllib.error.HTTPError as e:
            err_body = e.read().decode("utf-8")
            raise InferaCapError(err_body, status_code=e.code) from e

    def get_metrics(self) -> Dict[str, Any]:
        """Fetch live routing ledger and financial metrics."""
        url = f"{self.base_url}/metrics"
        req = urllib.request.Request(url, headers=self._get_headers())
        with urllib.request.urlopen(req, timeout=self.timeout_seconds) as resp:
            return json.loads(resp.read().decode("utf-8"))

    def get_analytics(self) -> Dict[str, Any]:
        """Fetch feature distribution telemetry and drop/merge recommendations."""
        url = f"{self.base_url}/analytics"
        req = urllib.request.Request(url, headers=self._get_headers())
        with urllib.request.urlopen(req, timeout=self.timeout_seconds) as resp:
            return json.loads(resp.read().decode("utf-8"))

    def health(self) -> bool:
        """Check gateway health."""
        try:
            url = f"{self.base_url}/health"
            req = urllib.request.Request(url, headers={"User-Agent": "InferaCap-HealthProbe/1.0"})
            with urllib.request.urlopen(req, timeout=3.0) as resp:
                return resp.status == 200
        except Exception:
            return False
