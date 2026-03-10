import importlib.util
import json
import sys
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path


RELAY_PATH = Path(__file__).resolve().parents[1] / "tools" / "wake-relay" / "wake_relay.py"
SPEC = importlib.util.spec_from_file_location("wake_relay", RELAY_PATH)
wake_relay = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
sys.modules["wake_relay"] = wake_relay
SPEC.loader.exec_module(wake_relay)


def _read_http_error_json(exc: urllib.error.HTTPError):
    raw = exc.read().decode("utf-8")
    return json.loads(raw) if raw else {}


class WakePacketTests(unittest.TestCase):
    def test_build_magic_packet_repeats_normalized_mac(self):
        packet = wake_relay.build_magic_packet("aa-bb-cc-dd-ee-ff")
        self.assertEqual(len(packet), 102)
        self.assertEqual(packet[:6], b"\xff" * 6)
        self.assertEqual(packet[6:12], bytes.fromhex("AABBCCDDEEFF"))
        self.assertEqual(packet[-6:], bytes.fromhex("AABBCCDDEEFF"))

    def test_build_magic_packet_rejects_invalid_mac(self):
        with self.assertRaises(ValueError):
            wake_relay.build_magic_packet("invalid")


class RelayHTTPTests(unittest.TestCase):
    def setUp(self):
        self.wake_calls = []
        config = wake_relay.WakeRelayConfig(
            host="127.0.0.1",
            port=0,
            relay_token="secret-token",
            target_mac="AA:BB:CC:DD:EE:FF",
        )
        self.state = wake_relay.WakeRelayState(config=config, send_wake_fn=self._fake_send_wake)
        self.server = wake_relay.create_server(state=self.state)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        host, port = self.server.server_address
        self.base_url = f"http://{host}:{port}"

    def tearDown(self):
        self.server.shutdown()
        self.thread.join(timeout=2.0)
        self.server.server_close()

    def _fake_send_wake(self, mac, broadcast_ip, wake_port):
        self.wake_calls.append((mac, broadcast_ip, wake_port))
        return {"ok": True, "packet_size": 102}

    def _request(self, path, *, method="GET", token=None, payload=None):
        data = None if payload is None else json.dumps(payload).encode("utf-8")
        headers = {}
        if token:
            headers["x-relay-token"] = token
        if data is not None:
            headers["content-type"] = "application/json"
        req = urllib.request.Request(f"{self.base_url}{path}", data=data, headers=headers, method=method)
        with urllib.request.urlopen(req, timeout=2.0) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))

    def test_health_requires_relay_token(self):
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            self._request("/health")
        self.assertEqual(ctx.exception.code, 401)
        self.assertEqual(_read_http_error_json(ctx.exception), {"error": "unauthorized", "ok": False})

    def test_wake_requires_relay_token(self):
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            self._request("/wake", method="POST", payload={})
        self.assertEqual(ctx.exception.code, 401)
        self.assertEqual(len(self.wake_calls), 0)

    def test_health_and_wake_succeed_with_valid_token(self):
        status, health = self._request("/health", token="secret-token")
        self.assertEqual(status, 200)
        self.assertEqual(health["target_mac"], "AA:BB:CC:DD:EE:FF")
        self.assertEqual(health["wake_surface"], "http")

        status, wake = self._request("/wake", method="POST", token="secret-token", payload={})
        self.assertEqual(status, 200)
        self.assertTrue(wake["accepted"])
        self.assertEqual(wake["source"], "http")
        self.assertEqual(self.wake_calls, [("AA:BB:CC:DD:EE:FF", "255.255.255.255", 9)])


class TelegramRoutingTests(unittest.TestCase):
    def setUp(self):
        self.sent_messages = []
        self.wake_calls = []
        config = wake_relay.WakeRelayConfig(
            target_mac="AA:BB:CC:DD:EE:FF",
            allowed_chat_id="42",
            telegram_bot_token="telegram-token",
        )
        self.state = wake_relay.WakeRelayState(config=config, send_wake_fn=self._fake_send_wake)

    def _fake_send_wake(self, mac, broadcast_ip, wake_port):
        self.wake_calls.append((mac, broadcast_ip, wake_port))
        return {"ok": True}

    def _fake_send_message(self, config, chat_id, text, *, request_json_fn):
        self.sent_messages.append((config.telegram_bot_token, chat_id, text))
        return {"ok": True}

    def test_status_command_replies_for_allowed_chat(self):
        outcome = wake_relay.route_telegram_update(
            {"update_id": 7, "message": {"chat": {"id": 42}, "text": "/status"}},
            self.state,
            send_message_fn=self._fake_send_message,
        )
        self.assertEqual(outcome, {"handled": True, "action": "status", "chat_id": "42"})
        self.assertEqual(len(self.sent_messages), 1)
        self.assertIn("Wake relay is ready.", self.sent_messages[0][2])
        self.assertEqual(self.wake_calls, [])

    def test_wake_command_triggers_magic_packet_for_allowed_chat(self):
        outcome = wake_relay.route_telegram_update(
            {"update_id": 8, "message": {"chat": {"id": "42"}, "text": "/wake"}},
            self.state,
            send_message_fn=self._fake_send_message,
        )
        self.assertEqual(outcome, {"handled": True, "action": "wake", "chat_id": "42"})
        self.assertEqual(self.wake_calls, [("AA:BB:CC:DD:EE:FF", "255.255.255.255", 9)])
        self.assertEqual(len(self.sent_messages), 1)
        self.assertIn("Wake packet sent to AA:BB:CC:DD:EE:FF", self.sent_messages[0][2])

    def test_unauthorized_chat_is_ignored(self):
        outcome = wake_relay.route_telegram_update(
            {"update_id": 9, "message": {"chat": {"id": 999}, "text": "/wake"}},
            self.state,
            send_message_fn=self._fake_send_message,
        )
        self.assertEqual(outcome, {"handled": False, "reason": "unauthorized", "chat_id": "999"})
        self.assertEqual(self.wake_calls, [])
        self.assertEqual(self.sent_messages, [])


if __name__ == "__main__":
    unittest.main()
