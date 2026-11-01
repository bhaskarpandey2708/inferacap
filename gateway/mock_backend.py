"""Mock OpenAI-compatible regional LLM backend for integration testing."""

from __future__ import annotations

import json
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
import threading
from typing import Dict, List, Optional


class MockLLMHandler(BaseHTTPRequestHandler):
    region_name = "US"
    request_log: List[dict] = []

    def log_message(self, format, *args):
        pass  # Quiet logging

    def do_GET(self):
        if self.path in ("/v1/health", "/health"):
            self._send_json(200, {"status": "ok", "region": self.region_name})
        else:
            self._send_json(404, {"error": "not found"})

    def do_POST(self):
        if self.path in ("/v1/chat/completions", "/v1/completions"):
            content_length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(content_length).decode("utf-8")
            payload = json.loads(body)
            
            # Log incoming request
            record = {
                "timestamp": time.time(),
                "region": self.region_name,
                "path": self.path,
                "payload": payload,
            }
            MockLLMHandler.request_log.append(record)

            stream = bool(payload.get("stream", False))
            if stream:
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.send_header("Cache-Control", "no-cache")
                self.send_header("Connection", "close")
                self.end_headers()

                words = ["Hello ", "from ", f"[{self.region_name}] ", "streaming ", "cluster!"]
                for w in words:
                    chunk = {
                        "id": f"chatcmpl-stream-{self.region_name}-{int(time.time()*1000)}",
                        "object": "chat.completion.chunk",
                        "created": int(time.time()),
                        "model": payload.get("model", "mock-model"),
                        "choices": [{"index": 0, "delta": {"content": w}, "finish_reason": None}],
                    }
                    self.wfile.write(f"data: {json.dumps(chunk)}\n\n".encode("utf-8"))
                    self.wfile.flush()
                    time.sleep(0.01)

                self.wfile.write(b"data: [DONE]\n\n")
                self.wfile.flush()
                return

            response = {
                "id": f"chatcmpl-mock-{self.region_name}-{int(time.time()*1000)}",
                "object": "chat.completion",
                "created": int(time.time()),
                "model": payload.get("model", "mock-model"),
                "system_fingerprint": f"fp_{self.region_name}",
                "choices": [
                    {
                        "index": 0,
                        "message": {
                            "role": "assistant",
                            "content": f"Hello from regional backend [{self.region_name}]! Your request was served successfully.",
                        },
                        "finish_reason": "stop",
                    }
                ],
                "usage": {
                    "prompt_tokens": 15,
                    "completion_tokens": 12,
                    "total_tokens": 27,
                },
            }
            self._send_json(200, response)
        else:
            self._send_json(404, {"error": "not found"})

    def _send_json(self, status: int, data: dict):
        body = json.dumps(data).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


class MockRegionalServer:
    def __init__(self, region_name: str, host: str = "127.0.0.1", port: int = 0):
        self.region_name = region_name
        self.host = host
        handler = type(f"MockHandler_{region_name}", (MockLLMHandler,), {"region_name": region_name})
        self.server = HTTPServer((host, port), handler)
        self.port = self.server.server_port
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    def start(self):
        self.thread.start()

    def stop(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=3)

    @property
    def url(self) -> str:
        return f"http://{self.host}:{self.port}"
