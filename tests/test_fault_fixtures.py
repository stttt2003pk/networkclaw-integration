from __future__ import annotations

import http.client
import json
import os
from pathlib import Path
import selectors
import subprocess
import sys
import tempfile
import unittest
from urllib.parse import urlsplit

from support.event_ledger import EventLedger
from support.fault_injection import JSONLFaultPlan
from support.process import ManagedProcess


ROOT = Path(__file__).resolve().parents[1]
PROVIDER_STUB = ROOT / "tests/fixtures/provider_stub/server.py"
FAULT_PROXY = ROOT / "tools/fault-proxy.py"


class EventLedgerTests(unittest.TestCase):
    def test_records_only_allowlisted_metadata_and_waits_with_timeout(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            ledger = EventLedger(Path(temp_dir) / "events.jsonl")
            ledger.record("provider.request_received", "provider_request_received", model="test-model", stream=True)

            event = ledger.wait_for(
                lambda entry: entry["reason_code"] == "provider_request_received",
                timeout=0.1,
            )

            self.assertEqual(event["model"], "test-model")
            self.assertNotIn("payload", event)
            self.assertNotIn("authorization", event)
            self.assertEqual(len(ledger.snapshot()), 1)

    def test_rejects_unbounded_or_sensitive_event_fields(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            ledger = EventLedger(Path(temp_dir) / "events.jsonl")

            with self.assertRaises(ValueError):
                ledger.record("provider.request_received", "provider_request_received", payload="private")

            with self.assertRaises(TimeoutError):
                ledger.wait_for(lambda _entry: False, timeout=0.02)


class FaultPlanTests(unittest.TestCase):
    def test_stale_terminal_is_injected_before_original_with_epoch_decremented(self) -> None:
        plan = JSONLFaultPlan("stale-terminal")
        frame = json.dumps({
            "type": "turn.completed",
            "payload": {"execution_epoch": 7, "reason_code": "completed"},
        }).encode() + b"\n"

        result = plan.transform(frame)

        self.assertEqual(result.reason_code, "stale_epoch_injected")
        self.assertEqual(len(result.frames), 2)
        self.assertEqual(json.loads(result.frames[0])["payload"]["execution_epoch"], 6)
        self.assertEqual(json.loads(result.frames[1])["payload"]["execution_epoch"], 7)

    def test_transport_drop_stops_forwarding_after_configured_frame(self) -> None:
        plan = JSONLFaultPlan("drop", after_frames=2)
        first = plan.transform(b'{"type":"protocol.negotiate"}\n')
        second = plan.transform(b'{"type":"request.accepted"}\n')
        third = plan.transform(b'{"type":"turn.completed"}\n')

        self.assertEqual(len(first.frames), 1)
        self.assertEqual(second.reason_code, "transport_dropped")
        self.assertTrue(second.terminate_child)
        self.assertEqual(third.frames, ())

    def test_sigkill_stops_forwarding_with_harness_reason_code(self) -> None:
        plan = JSONLFaultPlan("sigkill", after_frames=1)
        result = plan.transform(b'{"type":"protocol.negotiate"}\n')

        self.assertEqual(result.reason_code, "harness_sigkill")
        self.assertTrue(result.terminate_child)
        self.assertEqual(result.frames, ())


class ManagedProcessTests(unittest.TestCase):
    def test_ready_process_can_be_disconnected_and_reaped(self) -> None:
        managed, _ = ManagedProcess.start_ready(
            [sys.executable, "-u", "-c", "import sys; print('READY 7'); sys.stdin.read()"],
            timeout=2,
        )
        with managed:
            managed.disconnect_stdin()
            self.assertEqual(managed.wait(timeout=2), 0)

    def test_sigkill_fault_is_reaped_within_bound(self) -> None:
        managed, _ = ManagedProcess.start_ready(
            [sys.executable, "-u", "-c", "import time; print('READY 7'); time.sleep(5)"],
            timeout=2,
        )
        managed.kill()
        self.assertNotEqual(managed.wait(timeout=2), 0)
        managed.close()


class FaultProxyTests(unittest.TestCase):
    def test_drop_proxy_terminates_child_and_records_reason(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            events = Path(temp_dir) / "faults.jsonl"
            child_code = "import sys; print('{\\\"type\\\":\\\"protocol.negotiate\\\"}'); sys.stdout.flush(); sys.stdin.read()"
            process = subprocess.Popen(
                [
                    sys.executable,
                    str(FAULT_PROXY),
                    "--mode", "drop",
                    "--after-frames", "1",
                    "--events", str(events),
                    "--", sys.executable, "-u", "-c", child_code,
                ],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            stdout, _stderr = process.communicate(timeout=3)
            self.assertEqual(process.returncode, 75)
            self.assertEqual(stdout, b"")
            record = json.loads(events.read_text(encoding="utf-8"))
            self.assertEqual(record["reason_code"], "transport_dropped")

    def test_sigkill_proxy_kills_child_and_records_reason(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            events = Path(temp_dir) / "faults.jsonl"
            child_code = "import sys,time; print('{\\\"type\\\":\\\"protocol.negotiate\\\"}', flush=True); time.sleep(5)"
            process = subprocess.Popen(
                [
                    sys.executable,
                    str(FAULT_PROXY),
                    "--mode", "sigkill",
                    "--after-frames", "1",
                    "--events", str(events),
                    "--", sys.executable, "-u", "-c", child_code,
                ],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            stdout, _stderr = process.communicate(input=b"{\\\"type\\\":\\\"request\\\"}\n", timeout=3)
            self.assertEqual(process.returncode, 77)
            self.assertEqual(stdout, b"")
            record = json.loads(events.read_text(encoding="utf-8"))
            self.assertEqual(record["reason_code"], "harness_sigkill")

    def test_reset_proxy_kills_child_and_records_transport_reset(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            events = Path(temp_dir) / "faults.jsonl"
            child_code = "import time; print('{\\\"type\\\":\\\"protocol.negotiate\\\"}', flush=True); time.sleep(5)"
            process = subprocess.Popen(
                [
                    sys.executable,
                    str(FAULT_PROXY),
                    "--mode", "reset",
                    "--after-frames", "1",
                    "--events", str(events),
                    "--", sys.executable, "-u", "-c", child_code,
                ],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            stdout, _stderr = process.communicate(timeout=3)
            self.assertEqual(process.returncode, 76)
            self.assertEqual(stdout, b"")
            record = json.loads(events.read_text(encoding="utf-8"))
            self.assertEqual(record["reason_code"], "transport_reset")

    def test_disconnect_proxy_closes_child_stdin_and_records_reason(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            events = Path(temp_dir) / "faults.jsonl"
            child_code = "import sys; print('{\\\"type\\\":\\\"child.ready\\\"}', flush=True); sys.stdin.read(); print('{\\\"type\\\":\\\"child.eof\\\"}', flush=True)"
            process = subprocess.Popen(
                [
                    sys.executable,
                    str(FAULT_PROXY),
                    "--mode", "disconnect",
                    "--after-frames", "1",
                    "--events", str(events),
                    "--", sys.executable, "-u", "-c", child_code,
                ],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            stdout, _stderr = process.communicate(input=b"{\\\"type\\\":\\\"request\\\"}\n", timeout=3)
            self.assertEqual(process.returncode, 78)
            self.assertIn(b"child.eof", stdout)
            record = json.loads(events.read_text(encoding="utf-8"))
            self.assertEqual(record["reason_code"], "go_client_disconnected")


class ProviderStubTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.ledger_path = Path(self.temp_dir.name) / "provider-events.jsonl"
        self.process: subprocess.Popen[bytes] | None = None

    def tearDown(self) -> None:
        if self.process is not None and self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=2)
        if self.process is not None:
            for stream in (self.process.stdin, self.process.stdout, self.process.stderr):
                if stream is not None:
                    stream.close()
        self.temp_dir.cleanup()

    def test_modes_emit_openai_sse_or_stable_faults(self) -> None:
        cases = {
            "stream": (200, "provider_succeeded", b"[DONE]"),
            "slow": (200, "provider_succeeded", b"[DONE]"),
            "drop": (200, "provider_stream_interrupted", b"partial"),
            "http-error": (503, "provider_http_error", b"fixture_provider_unavailable"),
            "malformed": (200, "provider_response_invalid", b"{not-json"),
        }
        for mode, (status, reason_code, body_fragment) in cases.items():
            with self.subTest(mode=mode):
                base_url = self._start_provider(mode)
                parsed = urlsplit(base_url)
                connection = http.client.HTTPConnection(parsed.hostname, parsed.port, timeout=2)
                body = json.dumps({"model": "test-model", "stream": True}).encode()
                connection.request("POST", "/v1/chat/completions", body=body, headers={"Content-Type": "application/json"})
                response = connection.getresponse()
                response_body = response.read()
                self.assertEqual(response.status, status)
                self.assertIn(body_fragment, response_body)
                connection.close()

                events = self._read_events(base_url)
                self.assertIn(reason_code, [event["reason_code"] for event in events])
                serialized = json.dumps(events).lower()
                self.assertNotIn("authorization", serialized)
                self.assertNotIn("api_key", serialized)
                self._stop_provider()

    def test_reset_mode_closes_connection_and_records_reason(self) -> None:
        base_url = self._start_provider("reset")
        parsed = urlsplit(base_url)
        connection = http.client.HTTPConnection(parsed.hostname, parsed.port, timeout=2)
        connection.request("POST", "/v1/chat/completions", body=b'{"model":"test-model","stream":true}')
        with self.assertRaises((http.client.HTTPException, OSError)):
            connection.getresponse()
        connection.close()

        events = self._read_events(base_url)
        self.assertIn("provider_transport_reset", [event["reason_code"] for event in events])

    def test_non_loopback_bind_is_rejected(self) -> None:
        result = subprocess.run(
            [sys.executable, str(PROVIDER_STUB), "--host", "0.0.0.0"],
            capture_output=True,
            check=False,
            timeout=2,
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn(b"loopback", result.stderr.lower())

    def _start_provider(self, mode: str) -> str:
        environment = os.environ.copy()
        environment["NETWORKCLAW_PROVIDER_STUB_EVENTS"] = str(self.ledger_path)
        self.process = subprocess.Popen(
            [sys.executable, str(PROVIDER_STUB), "--mode", mode, "--delay-ms", "20"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=environment,
        )
        assert self.process.stdout is not None
        selector = selectors.DefaultSelector()
        selector.register(self.process.stdout, selectors.EVENT_READ)
        try:
            ready = selector.select(timeout=2)
            self.assertTrue(ready, "provider stub did not become ready")
            line = self.process.stdout.readline().decode("ascii").strip()
        finally:
            selector.close()
        fields = line.split()
        self.assertEqual(fields[0], "READY")
        return f"http://127.0.0.1:{int(fields[1])}/v1"

    def _read_events(self, base_url: str) -> list[dict[str, object]]:
        parsed = urlsplit(base_url)
        connection = http.client.HTTPConnection(parsed.hostname, parsed.port, timeout=2)
        connection.request("GET", "/__fixture/events")
        response = connection.getresponse()
        self.assertEqual(response.status, 200)
        events = json.loads(response.read())
        connection.close()
        return events

    def _stop_provider(self) -> None:
        if self.process is None:
            return
        self.process.terminate()
        self.process.wait(timeout=2)
        for stream in (self.process.stdin, self.process.stdout, self.process.stderr):
            if stream is not None:
                stream.close()
        self.process = None


if __name__ == "__main__":
    unittest.main()
