#!/usr/bin/env python3
"""Loopback-only OpenAI-compatible provider fixture for offline integration tests."""

from __future__ import annotations

import argparse
import ipaddress
import json
import os
import socket
import struct
import sys
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

TESTS_ROOT = Path(__file__).resolve().parents[2]
if str(TESTS_ROOT) not in sys.path:
    sys.path.insert(0, str(TESTS_ROOT))

from support.event_ledger import EventLedger


_CHUNKS = (
    {"choices": [{"delta": {"role": "assistant"}, "finish_reason": None}]},
    {"choices": [{"delta": {"content": "interop-ok"}, "finish_reason": None}]},
    {"choices": [{"delta": {}, "finish_reason": "stop"}]},
)


class ProviderServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, address: tuple[str, int], mode: str, delay_ms: int, ledger: EventLedger) -> None:
        self.mode = mode
        self.delay_ms = delay_ms
        self.ledger = ledger
        super().__init__(address, ProviderHandler)


class ProviderHandler(BaseHTTPRequestHandler):
    server: ProviderServer

    def do_GET(self) -> None:  # noqa: N802
        if self.path == "/healthz":
            self._json(200, {"status": "ready"})
            return
        if self.path == "/__fixture/events":
            self._json(200, self.server.ledger.snapshot())
            return
        self._json(404, {"error": "not_found"})

    def do_POST(self) -> None:  # noqa: N802
        if self.path != "/v1/chat/completions":
            self._json(404, {"error": "not_found"})
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            self._json(400, {"error": "invalid_content_length"})
            return
        if length < 0 or length > 1024 * 1024:
            self._json(413, {"error": "request_too_large"})
            return
        raw_body = self.rfile.read(length)
        try:
            request = json.loads(raw_body)
        except (UnicodeDecodeError, json.JSONDecodeError):
            self._json(400, {"error": "invalid_json"})
            return
        if not isinstance(request, dict):
            self._json(400, {"error": "invalid_request"})
            return
        stream = request.get("stream") is True
        self.server.ledger.record(
            "provider.request_received", "provider_request_received",
            mode=self.server.mode, stream=stream,
        )

        parent_delegation = self.server.mode in {"delegate", "delegate-failure"} and any(
            message.get("role") == "user" and message.get("content") == "reply with a short fixture response"
            for message in request.get("messages", [])
        )
        context_round = sum(message.get("role") == "tool" for message in request.get("messages", []))
        latest_user = next((str(message.get("content") or "") for message in reversed(request.get("messages", [])) if message.get("role") == "user"), "")
        self.context_summary = self.server.mode == "context" and not request.get("tools")
        context_tool = self.server.mode == "context" and not latest_user.startswith("context warmup ") and context_round < 3 and not any(
            "[CONTEXT" in str(message.get("content") or "") or "e06 compressed fixture" in str(message.get("content") or "")
            for message in request.get("messages", [])
        )
        if request.get("tools") and (context_tool or ((self.server.mode in {"todo", "clarification", "usage"} or parent_delegation) and not any(
            message.get("role") == "tool" for message in request.get("messages", [])
        ))):
            call = {"index": 0, "id": "call-parity-todo", "type": "function",
                    "function": {"name": "todo_list", "arguments": json.dumps({
                        "todos": [{"id": "parity-item", "content": "fixture task", "status": "pending"}],
                    })}}
            if context_tool:
                call["id"] = f"call-context-{context_round}"
                call["function"]["arguments"] = json.dumps({"todos": [
                    {"id": f"context-{context_round}-{index}", "content": "fixture context details " * 160, "status": "pending"}
                    for index in range(4)
                ]})
            if parent_delegation:
                call = {"index": 0, "id": "call-e06-delegate", "type": "function",
                        "function": {"name": "delegate_task", "arguments": json.dumps({
                            "tasks": [{"goal": "e06-child-fail" if self.server.mode == "delegate-failure" else "e06-child-a"}, {"goal": "e06-child-b"}],
                        })}}
            elif self.server.mode == "clarification":
                call = {"index": 0, "id": "call-e06-clarify", "type": "function",
                        "function": {"name": "clarify", "arguments": json.dumps({
                            "question": "Which fixture route should continue?", "choices": ["primary", "fallback"],
                        })}}
            if not stream:
                self._json(200, {"id": "todo-fixture", "object": "chat.completion",
                    "choices": [{"index": 0, "message": {"role": "assistant", "content": None,
                        "tool_calls": [call]}, "finish_reason": "tool_calls"}]})
                return
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.end_headers()
            for delta, finish in (({"role": "assistant", "tool_calls": [call]}, None), ({}, "tool_calls")):
                self.wfile.write(self._sse({"id": "todo-fixture", "object": "chat.completion.chunk",
                    "choices": [{"index": 0, "delta": delta, "finish_reason": finish}]}))
            self.wfile.write(b"data: [DONE]\n\n")
            self.wfile.flush()
            return


        if self.server.mode == "delegate-failure" and any(
            "e06-child-fail" in str(message.get("content") or "") for message in request.get("messages", [])
        ):
            self._json(503, {"error": {"message": "fixture child failure", "type": "server_error", "code": "fixture_child_failure"}})
            return
        if self.server.mode in {"delegate", "delegate-failure"} and not parent_delegation:
            time.sleep(0.2)
        if self.server.mode == "reset":
            self.server.ledger.record("provider.connection_reset", "provider_transport_reset", mode="reset")
            self.close_connection = True
            try:
                self.connection.setsockopt(socket.SOL_SOCKET, socket.SO_LINGER, struct.pack("ii", 1, 0))
                self.connection.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            self.connection.close()
            return
        if self.server.mode == "delay":
            time.sleep(self.server.delay_ms / 1000)
        if self.server.mode == "http-error":
            self.server.ledger.record("provider.response_failed", "provider_http_error", mode="http-error", status=503)
            self._json(503, {"error": {"message": "fixture provider unavailable", "type": "server_error", "code": "fixture_provider_unavailable"}})
            return
        if self.server.mode == "malformed":
            self.server.ledger.record("provider.response_failed", "provider_response_invalid", mode="malformed", status=200)
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.end_headers()
            self.wfile.write(b"data: {not-json\n\n")
            self.wfile.flush()
            return
        if not stream:
            self.server.ledger.record("provider.response_sent", "provider_succeeded", mode=self.server.mode, status=200)
            self._json(200, self._completion())
            return
        self._stream_response()

    def _stream_response(self) -> None:
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        if self.server.mode == "drop":
            self.wfile.write(self._sse({"choices": [{"delta": {"content": "partial"}, "finish_reason": None}]}))
            self.wfile.flush()
            self.server.ledger.record("provider.stream_interrupted", "provider_stream_interrupted", mode="drop", chunk_count=1)
            self.close_connection = True
            return
        count = 0
        chunks = _CHUNKS
        if getattr(self, "context_summary", False):
            chunks = (chunks[0], {"choices": [{"delta": {"content": "interop-ok\ne06 compressed fixture\n" + "Preserve the fixture task and continue after context compression. " * 20}, "finish_reason": None}]}, chunks[-1])
        for index, chunk in enumerate(chunks):
            payload = {"id": "networkclaw-fixture", "object": "chat.completion.chunk", "model": "fixture", **chunk}
            if self.server.mode == "usage" and index == len(_CHUNKS) - 1:
                payload["usage"] = {"prompt_tokens": 7, "completion_tokens": 3, "total_tokens": 10}
            try:
                self.wfile.write(self._sse(payload))
                self.wfile.flush()
            except OSError:
                self.server.ledger.record("provider.client_disconnected", "provider_client_disconnected", mode=self.server.mode)
                return
            count += 1
            if self.server.mode == "slow":
                time.sleep(self.server.delay_ms / 1000)
        try:
            if self.server.mode == "usage":
                self.wfile.write(self._sse({"id": "networkclaw-fixture", "object": "chat.completion.chunk", "model": "fixture", "choices": [], "usage": {"prompt_tokens": 7, "completion_tokens": 3, "total_tokens": 10}}))
                self.wfile.flush()
            self.wfile.write(b"data: [DONE]\n\n")
            self.wfile.flush()
        except OSError:
            self.server.ledger.record("provider.client_disconnected", "provider_client_disconnected", mode=self.server.mode)
            return
        self.server.ledger.record("provider.response_sent", "provider_succeeded", mode=self.server.mode, chunk_count=count)

    def _completion(self) -> dict[str, object]:
        content = "interop-ok"
        if getattr(self, "context_summary", False):
            content += "\ne06 compressed fixture\n" + "Preserve the fixture task and continue after context compression. " * 20
        return {
            "id": "networkclaw-fixture", "object": "chat.completion", "model": "fixture",
            "choices": [{"index": 0, "message": {"role": "assistant", "content": content}, "finish_reason": "stop"}],
        }

    @staticmethod
    def _sse(value: dict[str, object]) -> bytes:
        return f"data: {json.dumps(value, separators=(',', ':'))}\n\n".encode("utf-8")

    def _json(self, status: int, value: object) -> None:
        body = json.dumps(value, separators=(",", ":")).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, _format: str, *_args: object) -> None:
        return


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=0)
    parser.add_argument("--mode", choices=("stream", "slow", "drop", "reset", "delay", "http-error", "malformed", "todo", "clarification", "usage", "context", "delegate", "delegate-failure"), default="stream")
    parser.add_argument("--delay-ms", type=int, default=50)
    args = parser.parse_args()
    try:
        address = ipaddress.ip_address(args.host)
        if not address.is_loopback:
            raise ValueError("provider stub may bind only to loopback addresses")
        if not 0 <= args.port <= 65535 or not 0 <= args.delay_ms <= 30000:
            raise ValueError("port or delay is outside the allowed range")
        ledger_path = os.environ.get("NETWORKCLAW_PROVIDER_STUB_EVENTS")
        ledger = EventLedger(Path(ledger_path) if ledger_path else None)
        server = ProviderServer((str(address), args.port), args.mode, args.delay_ms, ledger)
    except (OSError, ValueError) as error:
        print(f"provider-stub: {error}", file=sys.stderr)
        return 2
    print(f"READY {server.server_port}", flush=True)
    try:
        server.serve_forever(poll_interval=0.1)
    except KeyboardInterrupt:
        pass
    finally:
        server.shutdown()
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
