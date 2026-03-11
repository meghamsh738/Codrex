#!/usr/bin/env python3
"""
Codrex helper: share a local WSL file into Codrex outbox, optionally relay to Telegram.

Usage:
  codrex-send /home/megha/codrex-work/output/result.png --title "Result" --expires 24 --telegram --caption "Nightly run"
"""

from __future__ import annotations

import argparse
import json
import os
import pathlib
import re
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
from typing import Any, Dict, List, Optional, Tuple


def _die(msg: str, code: int = 1) -> "None":
    print(msg, file=sys.stderr)
    raise SystemExit(code)


def _default_config_path() -> pathlib.Path:
    # If called via symlink (~/.local/bin/codrex-send), resolve to repo path first.
    script_real = pathlib.Path(__file__).resolve()
    repo_root = script_real.parent.parent
    return repo_root / "controller.config.json"


def _local_config_path_for(config_path: pathlib.Path) -> pathlib.Path:
    return config_path.with_name("controller.config.local.json")


def _win_to_wsl_path(path: str) -> str:
    p = (path or "").strip()
    if len(p) >= 3 and p[1] == ":" and (p[2] == "\\" or p[2] == "/"):
        drive = p[0].lower()
        rest = p[2:].replace("\\", "/").lstrip("/")
        return f"/mnt/{drive}/{rest}"
    return p


def _read_controller_config(config_path: pathlib.Path) -> Dict[str, Any]:
    try:
        raw = config_path.read_text(encoding="utf-8-sig")
    except Exception:
        return {}
    if not raw.strip():
        return {}
    try:
        data = json.loads(raw)
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def _merge_controller_configs(primary: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
    merged: Dict[str, Any] = {}
    if isinstance(primary, dict):
        merged.update(primary)
    if isinstance(override, dict):
        for key, value in override.items():
            # Treat empty-string override as "ignore" so blank local fields do not
            # accidentally erase a usable main config value.
            if isinstance(value, str) and not value.strip():
                continue
            if value is None:
                continue
            merged[key] = value
    return merged


def _normalize_base_url(raw: str) -> str:
    text = (raw or "").strip()
    if not text:
        return ""
    if not re.match(r"^https?://", text, flags=re.IGNORECASE):
        text = f"http://{text}"
    return text.rstrip("/")


def _wsl_nameserver_host() -> str:
    # In WSL2 this is usually the Windows host gateway and can reach Windows services.
    try:
        with open("/etc/resolv.conf", "r", encoding="utf-8") as f:
            for raw_line in f:
                line = (raw_line or "").strip()
                if not line.lower().startswith("nameserver "):
                    continue
                value = line.split(None, 1)[1].strip()
                if value:
                    return value
    except Exception:
        return ""
    return ""


def _read_json_file(path: pathlib.Path) -> Dict[str, Any]:
    try:
        raw = path.read_text(encoding="utf-8-sig")
    except Exception:
        return {}
    if not raw.strip():
        return {}
    try:
        data = json.loads(raw)
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def _windows_local_appdata_wsl() -> pathlib.Path | None:
    env_value = (os.environ.get("LOCALAPPDATA") or "").strip()
    if env_value:
        converted = _win_to_wsl_path(env_value)
        candidate = pathlib.Path(converted).expanduser()
        if candidate.exists():
            return candidate
    try:
        out = subprocess.run(
            ["cmd.exe", "/c", "echo", "%LocalAppData%"],
            check=False,
            capture_output=True,
            text=True,
            timeout=3,
        )
        raw = (out.stdout or "").strip()
        if raw and "%" not in raw:
            converted = _win_to_wsl_path(raw)
            candidate = pathlib.Path(converted).expanduser()
            if candidate.exists():
                return candidate
    except Exception:
        return None
    return None


def _runtime_dir_candidates(config_path: pathlib.Path) -> List[pathlib.Path]:
    candidates: List[pathlib.Path] = []

    def add(value: pathlib.Path | str) -> None:
        if not value:
            return
        path_value = pathlib.Path(str(value)).expanduser()
        if path_value not in candidates:
            candidates.append(path_value)

    runtime_env = (os.environ.get("CODEX_RUNTIME_DIR") or "").strip()
    if runtime_env:
        add(_win_to_wsl_path(runtime_env))

    local_appdata = _windows_local_appdata_wsl()
    if local_appdata:
        add(local_appdata / "Codrex" / "remote-ui")

    repo_root = config_path.parent
    add(repo_root / ".runtime")

    return candidates


def _load_runtime_controller_state(config_path: pathlib.Path) -> Dict[str, Any]:
    merged: Dict[str, Any] = {}
    for runtime_dir in _runtime_dir_candidates(config_path):
        state_dir = runtime_dir / "state"
        local_cfg = _read_json_file(state_dir / "controller.config.local.json")
        session = _read_json_file(state_dir / "mobile.session.json")
        if local_cfg:
            merged = _merge_controller_configs(merged, local_cfg)
        if session:
            merged = _merge_controller_configs(merged, session)
    return merged


def _controller_reachable(base_url: str, token: str) -> bool:
    base = _normalize_base_url(base_url)
    if not base:
        return False
    url = f"{base}/auth/status"
    headers = {"Accept": "application/json"}
    if token:
        headers["x-auth-token"] = token
    req = urllib.request.Request(url, method="GET", headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=1.5) as resp:
            if int(getattr(resp, "status", 0) or 0) != 200:
                return False
            raw = resp.read().decode("utf-8", errors="replace")
            parsed = json.loads(raw) if raw else {}
            return isinstance(parsed, dict) and bool(parsed.get("ok"))
    except Exception:
        return False


def _build_controller_candidates(env_base: str, cfg: Dict[str, Any], port: int) -> List[str]:
    candidates: List[str] = []

    def add(value: str) -> None:
        base = _normalize_base_url(value)
        if not base:
            return
        if base not in candidates:
            candidates.append(base)

    if env_base:
        add(env_base)

    for key in (
        "controller_url",
        "controllerUrl",
        "base_url",
        "baseUrl",
        "url",
        "app_url",
        "network_app_url",
        "local_url",
        "network_url",
    ):
        v = str(cfg.get(key) or "").strip()
        if v:
            add(v)

    # Legacy/defaults
    add(f"http://127.0.0.1:{port}")
    add(f"http://localhost:{port}")

    for key in ("lanIp", "lan_ip", "tailscaleIp", "tailscale_ip", "host", "hostname"):
        host = str(cfg.get(key) or "").strip()
        if host:
            add(f"http://{host}:{port}")

    ns = _wsl_nameserver_host()
    if ns:
        add(f"http://{ns}:{port}")

    extra_hosts = (os.environ.get("CODREX_CONTROLLER_HOSTS") or "").strip()
    if extra_hosts:
        for part in extra_hosts.split(","):
            host = part.strip()
            if host:
                add(f"http://{host}:{port}")

    return candidates


def _get_controller_defaults() -> Tuple[str, str, Dict[str, Any]]:
    # Priority:
    # 1) explicit env
    # 2) controller.config.json (port + token)
    env_base = (os.environ.get("CODREX_CONTROLLER_URL") or "").strip().rstrip("/")
    env_token = (os.environ.get("CODREX_AUTH_TOKEN") or "").strip()

    config_env = (os.environ.get("CODREX_CONTROLLER_CONFIG") or "").strip()
    if config_env:
        config_path = pathlib.Path(_win_to_wsl_path(config_env)).expanduser()
    else:
        config_path = _default_config_path()
    local_config_path = _local_config_path_for(config_path)

    cfg_main = _read_controller_config(config_path)
    cfg_local = _read_controller_config(local_config_path)
    cfg_runtime = _load_runtime_controller_state(config_path)
    cfg = _merge_controller_configs(_merge_controller_configs(cfg_main, cfg_local), cfg_runtime)

    port = 8787
    try:
        port = int(cfg.get("port") or 8787)
    except Exception:
        port = 8787
    if port <= 0 or port > 65535:
        port = 8787

    token = env_token or str(cfg.get("token") or "").strip()
    candidates = _build_controller_candidates(env_base, cfg, port)
    base = candidates[0] if candidates else f"http://127.0.0.1:{port}"
    for candidate in candidates:
        if _controller_reachable(candidate, token):
            base = candidate
            break
    return base, token, cfg


def _path_within_root(path_value: pathlib.Path, root_value: pathlib.Path) -> bool:
    try:
        path_value.resolve().relative_to(root_value.resolve())
        return True
    except Exception:
        return False


def _resolve_share_root(cfg: Dict[str, Any]) -> pathlib.Path:
    for key in ("fileRoot", "file_root", "workdir", "cwd"):
        raw = str(cfg.get(key) or "").strip()
        if raw:
            converted = _win_to_wsl_path(raw)
            root = pathlib.Path(converted).expanduser()
            if root.is_absolute():
                return root
    return pathlib.Path("/home/megha/codrex-work")


def _stage_file_into_share_root(source_path: pathlib.Path, share_root: pathlib.Path) -> pathlib.Path:
    staging_dir = share_root / "output" / ".codrex-share-staging"
    staging_dir.mkdir(parents=True, exist_ok=True)
    stamp = int(time.time())
    safe_name = source_path.name or "file.bin"
    dest = staging_dir / f"{stamp}_{safe_name}"
    if dest.exists():
        dest = staging_dir / f"{stamp}_{os.getpid()}_{safe_name}"
    shutil.copy2(source_path, dest)
    return dest


def _request_json(base_url: str, method: str, path: str, payload: Optional[Dict[str, Any]], token: str) -> Dict[str, Any]:
    url = f"{base_url.rstrip('/')}{path}"
    body_bytes = None
    headers = {"Accept": "application/json"}
    if payload is not None:
        body_bytes = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    if token:
        headers["x-auth-token"] = token

    req = urllib.request.Request(url, data=body_bytes, headers=headers, method=method)

    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
            return json.loads(raw) if raw else {"ok": True}
    except urllib.error.HTTPError as e:
        try:
            raw = e.read().decode("utf-8", errors="replace")
            parsed = json.loads(raw) if raw else {}
            if isinstance(parsed, dict):
                return parsed
        except Exception:
            pass
        return {"ok": False, "error": "http_error", "detail": f"HTTP {getattr(e, 'code', '?')}"}
    except Exception as e:
        return {"ok": False, "error": "request_failed", "detail": f"{type(e).__name__}: {e}"}


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Share file to Codrex inbox and optional Telegram relay")
    parser.add_argument("path", help="Absolute or relative WSL file path")
    parser.add_argument("--title", default="", help="Optional display title")
    parser.add_argument("--expires", type=int, default=24, help="Expiry in hours (default: 24)")
    parser.add_argument("--telegram", "--tg", action="store_true", help="Also send this file to Telegram")
    parser.add_argument("--caption", default="", help="Telegram caption override")
    parser.add_argument("--created-by", default="codex-cli", help="Audit origin tag for share item")
    return parser.parse_args(argv)


def main(argv: list[str]) -> int:
    args = _parse_args(argv)

    wsl_path = pathlib.Path(args.path).expanduser()
    if not wsl_path.is_absolute():
        wsl_path = (pathlib.Path.cwd() / wsl_path).resolve()

    if not wsl_path.exists():
        _die(f"Source file not found: {wsl_path}", code=2)
    if not wsl_path.is_file():
        _die(f"Source path is not a regular file: {wsl_path}", code=2)

    base_url, token, cfg = _get_controller_defaults()

    share_path = wsl_path
    share_root = _resolve_share_root(cfg)
    if share_root and not _path_within_root(share_path, share_root):
        share_path = _stage_file_into_share_root(share_path, share_root)
        print(f"Staged outside-root file into: {share_path}")

    share_payload: Dict[str, Any] = {
        "path": str(share_path),
        "expires_hours": max(1, int(args.expires or 24)),
        "created_by": (args.created_by or "codex-cli").strip()[:64],
    }
    if args.title.strip():
        share_payload["title"] = args.title.strip()

    share = _request_json(base_url, "POST", "/shares", share_payload, token)
    if not share.get("ok"):
        _die(f"Share failed: {share.get('detail') or share.get('error') or 'unknown error'}", code=2)

    item = share.get("item") if isinstance(share.get("item"), dict) else {}
    share_id = str(item.get("id") or "").strip()
    if not share_id:
        _die("Share failed: backend did not return share id.", code=2)

    print(f"Shared: {item.get('file_name') or wsl_path.name}")
    print(f"Inbox id: {share_id}")
    dl = str(item.get("download_url") or "").strip()
    if dl:
        print(f"Download: {base_url.rstrip('/')}{dl if dl.startswith('/') else '/' + dl}")

    if args.telegram:
        tg_payload: Dict[str, Any] = {}
        caption = args.caption.strip() or args.title.strip()
        if caption:
            tg_payload["caption"] = caption
        tg = _request_json(base_url, "POST", f"/shares/{share_id}/telegram", tg_payload, token)
        if not tg.get("ok"):
            _die(f"Telegram failed: {tg.get('detail') or tg.get('error') or 'unknown error'}", code=3)
        print("Telegram: sent")

    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
