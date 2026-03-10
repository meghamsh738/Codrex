#!/usr/bin/env python3
from __future__ import annotations

import hmac
import json
import os
import socket
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Callable, Dict, Optional


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def normalize_mac(mac: str) -> str:
    cleaned = "".join(ch for ch in str(mac or "") if ch.isalnum())
    if len(cleaned) != 12:
        raise ValueError("MAC address must contain exactly 12 hexadecimal characters")
    try:
        int(cleaned, 16)
    except ValueError as exc:
        raise ValueError("MAC address contains non-hexadecimal characters") from exc
    pairs = [cleaned[idx : idx + 2].upper() for idx in range(0, 12, 2)]
    return ":".join(pairs)


def build_magic_packet(mac: str) -> bytes:
    normalized = normalize_mac(mac)
    mac_bytes = bytes.fromhex(normalized.replace(":", ""))
    return (b"\xff" * 6) + (mac_bytes * 16)


def send_wake_packet(
    mac: str,
    broadcast_ip: str = "255.255.255.255",
    wake_port: int = 9,
    sock_factory: Callable[..., socket.socket] = socket.socket,
) -> Dict[str, Any]:
    packet = build_magic_packet(mac)
    sock = sock_factory(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        sent = sock.sendto(packet, (broadcast_ip, int(wake_port)))
    finally:
        sock.close()
    return {
        "ok": True,
        "bytes_sent": sent,
        "packet_size": len(packet),
        "broadcast_ip": broadcast_ip,
        "wake_port": int(wake_port),
        "target_mac": normalize_mac(mac),
    }


def request_json(
    url: str,
    *,
    method: str = "GET",
    payload: Optional[Dict[str, Any]] = None,
    headers: Optional[Dict[str, str]] = None,
    timeout_s: float = 10.0,
) -> Dict[str, Any]:
    req_headers = {"accept": "application/json"}
    if headers:
        req_headers.update({str(key): str(value) for key, value in headers.items()})
    data: Optional[bytes] = None
    if payload is not None:
        req_headers.setdefault("content-type", "application/json")
        data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers=req_headers, method=method.upper())
    with urllib.request.urlopen(req, timeout=max(1.0, float(timeout_s))) as resp:
        raw = resp.read()
    if not raw:
        return {}
    return json.loads(raw.decode("utf-8"))


@dataclass
class WakeRelayConfig:
    host: str = "0.0.0.0"
    port: int = 8765
    relay_token: str = ""
    target_mac: str = ""
    broadcast_ip: str = "255.255.255.255"
    wake_port: int = 9
    allowed_chat_id: str = ""
    telegram_bot_token: str = ""
    telegram_api_base: str = "https://api.telegram.org"
    telegram_poll_timeout_s: float = 25.0
    telegram_retry_delay_s: float = 2.0
    wake_command: str = "/wake"

    def __post_init__(self) -> None:
        self.host = str(self.host or "0.0.0.0")
        self.port = int(self.port or 8765)
        self.relay_token = str(self.relay_token or "").strip()
        self.target_mac = normalize_mac(self.target_mac) if self.target_mac else ""
        self.broadcast_ip = str(self.broadcast_ip or "255.255.255.255").strip() or "255.255.255.255"
        self.wake_port = int(self.wake_port or 9)
        self.allowed_chat_id = str(self.allowed_chat_id or "").strip()
        self.telegram_bot_token = str(self.telegram_bot_token or "").strip()
        self.telegram_api_base = str(self.telegram_api_base or "https://api.telegram.org").strip().rstrip("/")
        self.telegram_poll_timeout_s = max(5.0, float(self.telegram_poll_timeout_s or 25.0))
        self.telegram_retry_delay_s = max(0.5, float(self.telegram_retry_delay_s or 2.0))
        wake_command = str(self.wake_command or "/wake").strip() or "/wake"
        self.wake_command = wake_command if wake_command.startswith("/") else f"/{wake_command}"

    @classmethod
    def from_env(cls) -> "WakeRelayConfig":
        return cls(
            host=os.environ.get("WAKE_RELAY_HOST", "0.0.0.0"),
            port=int(os.environ.get("WAKE_RELAY_PORT", "8765") or "8765"),
            relay_token=os.environ.get("WAKE_RELAY_TOKEN", ""),
            target_mac=os.environ.get("WAKE_RELAY_TARGET_MAC", ""),
            broadcast_ip=os.environ.get("WAKE_RELAY_BROADCAST_IP", "255.255.255.255"),
            wake_port=int(os.environ.get("WAKE_RELAY_WAKE_PORT", "9") or "9"),
            allowed_chat_id=os.environ.get("WAKE_RELAY_ALLOWED_CHAT_ID", ""),
            telegram_bot_token=os.environ.get("WAKE_RELAY_TELEGRAM_BOT_TOKEN", ""),
            telegram_api_base=os.environ.get("WAKE_RELAY_TELEGRAM_API_BASE", "https://api.telegram.org"),
            telegram_poll_timeout_s=float(os.environ.get("WAKE_RELAY_TELEGRAM_POLL_TIMEOUT", "25") or "25"),
            telegram_retry_delay_s=float(os.environ.get("WAKE_RELAY_TELEGRAM_RETRY_DELAY", "2") or "2"),
            wake_command=os.environ.get("WAKE_RELAY_WAKE_COMMAND", "/wake"),
        )

    @property
    def telegram_enabled(self) -> bool:
        return bool(self.telegram_bot_token and self.allowed_chat_id)


SendWakeFn = Callable[[str, str, int], Dict[str, Any]]
TelegramSendFn = Callable[..., Dict[str, Any]]


@dataclass
class WakeRelayState:
    config: WakeRelayConfig
    send_wake_fn: SendWakeFn = send_wake_packet
    request_json_fn: Callable[..., Dict[str, Any]] = request_json
    last_wake_at: str = ""
    last_wake_source: str = ""
    last_error: str = ""
    telegram_offset: int = 0
    lock: threading.Lock = field(default_factory=threading.Lock)

    def health_payload(self) -> Dict[str, Any]:
        with self.lock:
            last_wake_at = self.last_wake_at
            last_wake_source = self.last_wake_source
            last_error = self.last_error
        return {
            "ok": True,
            "service": "wake-relay",
            "target_mac": self.config.target_mac,
            "broadcast_ip": self.config.broadcast_ip,
            "wake_port": self.config.wake_port,
            "wake_surface": "telegram" if self.config.telegram_enabled else "http",
            "wake_command": self.config.wake_command,
            "telegram_enabled": self.config.telegram_enabled,
            "allowed_chat_id_configured": bool(self.config.allowed_chat_id),
            "last_wake_at": last_wake_at,
            "last_wake_source": last_wake_source,
            "last_error": last_error,
            "server_time": utc_now_iso(),
        }

    def trigger_wake(self, *, source: str) -> Dict[str, Any]:
        if not self.config.target_mac:
            raise RuntimeError("WAKE_RELAY_TARGET_MAC is not configured")
        result = self.send_wake_fn(self.config.target_mac, self.config.broadcast_ip, self.config.wake_port)
        timestamp = utc_now_iso()
        with self.lock:
            self.last_wake_at = timestamp
            self.last_wake_source = str(source or "unknown")
            self.last_error = ""
        payload = {
            "ok": True,
            "action": "wake",
            "accepted": True,
            "message": "Wake packet sent",
            "target_mac": self.config.target_mac,
            "broadcast_ip": self.config.broadcast_ip,
            "wake_port": self.config.wake_port,
            "source": str(source or "unknown"),
            "timestamp": timestamp,
        }
        payload.update(result or {})
        return payload

    def record_error(self, exc: BaseException) -> None:
        with self.lock:
            self.last_error = str(exc)

    def telegram_status_text(self) -> str:
        payload = self.health_payload()
        lines = [
            "Wake relay is ready.",
            f"Target MAC: {payload['target_mac'] or 'not configured'}",
            f"Broadcast: {payload['broadcast_ip']}:{payload['wake_port']}",
            f"Telegram: {'enabled' if payload['telegram_enabled'] else 'disabled'}",
            f"Last wake: {payload['last_wake_at'] or 'never'}",
        ]
        if payload["last_error"]:
            lines.append(f"Last error: {payload['last_error']}")
        return "\n".join(lines)


def telegram_api_url(config: WakeRelayConfig, method_name: str, **query: Any) -> str:
    base = f"{config.telegram_api_base}/bot{config.telegram_bot_token}/{method_name}"
    compact = {key: value for key, value in query.items() if value not in (None, "")}
    if not compact:
        return base
    return f"{base}?{urllib.parse.urlencode(compact)}"


def send_telegram_text(
    config: WakeRelayConfig,
    chat_id: str,
    text: str,
    *,
    request_json_fn: Callable[..., Dict[str, Any]] = request_json,
) -> Dict[str, Any]:
    return request_json_fn(
        telegram_api_url(config, "sendMessage"),
        method="POST",
        payload={"chat_id": str(chat_id), "text": str(text)},
        timeout_s=20.0,
    )


def _telegram_message_from_update(update: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    for key in ("message", "edited_message"):
        candidate = update.get(key)
        if isinstance(candidate, dict):
            return candidate
    return None


def route_telegram_update(
    update: Dict[str, Any],
    state: WakeRelayState,
    *,
    send_message_fn: TelegramSendFn = send_telegram_text,
) -> Dict[str, Any]:
    message = _telegram_message_from_update(update)
    if not message:
        return {"handled": False, "reason": "no_message"}
    text = str(message.get("text") or "").strip()
    if not text.startswith("/"):
        return {"handled": False, "reason": "not_command"}
    chat = message.get("chat") or {}
    chat_id = str(chat.get("id") or "").strip()
    if not chat_id:
        return {"handled": False, "reason": "missing_chat"}
    if state.config.allowed_chat_id and chat_id != state.config.allowed_chat_id:
        return {"handled": False, "reason": "unauthorized", "chat_id": chat_id}
    command = text.split()[0].split("@", 1)[0].lower()
    if command == state.config.wake_command.lower():
        wake_result = state.trigger_wake(source="telegram")
        send_message_fn(
            state.config,
            chat_id,
            f"Wake packet sent to {wake_result['target_mac']} via {wake_result['broadcast_ip']}:{wake_result['wake_port']}.",
            request_json_fn=state.request_json_fn,
        )
        return {"handled": True, "action": "wake", "chat_id": chat_id}
    if command == "/status":
        send_message_fn(
            state.config,
            chat_id,
            state.telegram_status_text(),
            request_json_fn=state.request_json_fn,
        )
        return {"handled": True, "action": "status", "chat_id": chat_id}
    return {"handled": False, "reason": "unsupported_command", "chat_id": chat_id}


def poll_telegram_once(
    state: WakeRelayState,
    *,
    send_message_fn: TelegramSendFn = send_telegram_text,
) -> int:
    if not state.config.telegram_enabled:
        return 0
    response = state.request_json_fn(
        telegram_api_url(
            state.config,
            "getUpdates",
            timeout=int(state.config.telegram_poll_timeout_s),
            offset=state.telegram_offset,
        ),
        method="GET",
        timeout_s=state.config.telegram_poll_timeout_s + 5.0,
    )
    updates = response.get("result") or []
    if not isinstance(updates, list):
        raise RuntimeError("Telegram getUpdates returned an unexpected payload")
    processed = 0
    highest_offset = state.telegram_offset
    for update in updates:
        if not isinstance(update, dict):
            continue
        update_id = int(update.get("update_id") or 0)
        if update_id:
            highest_offset = max(highest_offset, update_id + 1)
        route_telegram_update(update, state, send_message_fn=send_message_fn)
        processed += 1
    state.telegram_offset = highest_offset
    return processed


class TelegramPollingLoop(threading.Thread):
    def __init__(
        self,
        state: WakeRelayState,
        *,
        send_message_fn: TelegramSendFn = send_telegram_text,
        stop_event: Optional[threading.Event] = None,
    ) -> None:
        super().__init__(daemon=True, name="wake-relay-telegram")
        self.state = state
        self.send_message_fn = send_message_fn
        self.stop_event = stop_event or threading.Event()

    def run(self) -> None:
        while not self.stop_event.is_set():
            try:
                processed = poll_telegram_once(self.state, send_message_fn=self.send_message_fn)
                if processed == 0:
                    self.stop_event.wait(self.state.config.telegram_retry_delay_s)
            except Exception as exc:
                self.state.record_error(exc)
                self.stop_event.wait(self.state.config.telegram_retry_delay_s)


class WakeRelayHTTPServer(ThreadingHTTPServer):
    def __init__(self, server_address: tuple[str, int], state: WakeRelayState):
        super().__init__(server_address, WakeRelayRequestHandler)
        self.relay_state = state


class WakeRelayRequestHandler(BaseHTTPRequestHandler):
    server_version = "WakeRelay/1.0"

    def log_message(self, fmt: str, *args: Any) -> None:
        print(f"{self.address_string()} - - [{self.log_date_time_string()}] {fmt % args}")

    @property
    def relay_state(self) -> WakeRelayState:
        return self.server.relay_state  # type: ignore[attr-defined]

    def do_GET(self) -> None:
        if self.path.split("?", 1)[0] != "/health":
            self._send_json(404, {"ok": False, "error": "not_found"})
            return
        if not self._authorized():
            self._send_json(401, {"ok": False, "error": "unauthorized"})
            return
        self._send_json(200, self.relay_state.health_payload())

    def do_POST(self) -> None:
        if self.path.split("?", 1)[0] != "/wake":
            self._send_json(404, {"ok": False, "error": "not_found"})
            return
        if not self._authorized():
            self._send_json(401, {"ok": False, "error": "unauthorized"})
            return
        try:
            self._read_json_body()
            payload = self.relay_state.trigger_wake(source="http")
            self._send_json(200, payload)
        except Exception as exc:
            self.relay_state.record_error(exc)
            self._send_json(500, {"ok": False, "error": "wake_failed", "detail": str(exc)})

    def _read_json_body(self) -> Dict[str, Any]:
        length = int(self.headers.get("content-length") or "0")
        if length <= 0:
            return {}
        raw = self.rfile.read(length)
        if not raw:
            return {}
        return json.loads(raw.decode("utf-8"))

    def _authorized(self) -> bool:
        expected = self.relay_state.config.relay_token
        if not expected:
            return True
        provided = str(self.headers.get("x-relay-token") or "").strip()
        if not provided:
            auth_header = str(self.headers.get("authorization") or "").strip()
            if auth_header.lower().startswith("bearer "):
                provided = auth_header[7:].strip()
        return bool(provided) and hmac.compare_digest(provided, expected)

    def _send_json(self, status: int, payload: Dict[str, Any]) -> None:
        body = json.dumps(payload, sort_keys=True).encode("utf-8")
        self.send_response(status)
        self.send_header("content-type", "application/json; charset=utf-8")
        self.send_header("content-length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def create_server(config: Optional[WakeRelayConfig] = None, *, state: Optional[WakeRelayState] = None) -> WakeRelayHTTPServer:
    relay_state = state or WakeRelayState(config or WakeRelayConfig.from_env())
    return WakeRelayHTTPServer((relay_state.config.host, relay_state.config.port), relay_state)


def run_forever(config: Optional[WakeRelayConfig] = None) -> None:
    server = create_server(config)
    stop_event = threading.Event()
    telegram_thread: Optional[TelegramPollingLoop] = None
    if server.relay_state.config.telegram_enabled:
        telegram_thread = TelegramPollingLoop(server.relay_state, stop_event=stop_event)
        telegram_thread.start()
    print(
        f"Wake relay listening on http://{server.server_address[0]}:{server.server_address[1]} "
        f"for target {server.relay_state.config.target_mac or 'unset'}"
    )
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        stop_event.set()
        server.shutdown()
        server.server_close()
        if telegram_thread and telegram_thread.is_alive():
            telegram_thread.join(timeout=2.0)


def main() -> int:
    config = WakeRelayConfig.from_env()
    run_forever(config)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
