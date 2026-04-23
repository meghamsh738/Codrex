from fastapi import FastAPI, HTTPException, Body, UploadFile, File, Form, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, Response, FileResponse, JSONResponse, StreamingResponse, RedirectResponse
import asyncio
import gc
import glob
import json
import math
import time
import os
import shutil
import subprocess
import socket
import io
import re
import shlex
import hashlib
import mimetypes
import html as html_std
import threading
import uuid
import posixpath
import secrets
import ctypes
import ipaddress
from ctypes import wintypes
from typing import List, Dict, Any, Optional, Tuple, Callable, Set
from urllib.parse import quote, urlparse, unquote
import urllib.request
import urllib.error
import atexit
import base64
import logging
import sqlite3
import traceback
from fractions import Fraction

from mss import mss
from mss.tools import to_png
try:
    import dxcam  # type: ignore
    DXCAM_AVAILABLE = os.name == "nt"
    DXCAM_IMPORT_ERROR = ""
except Exception as _dxcam_exc:
    dxcam = None  # type: ignore
    DXCAM_AVAILABLE = False
    DXCAM_IMPORT_ERROR = f"{type(_dxcam_exc).__name__}: {_dxcam_exc}"
try:
    from PIL import Image
    PILLOW_AVAILABLE = True
except Exception:
    Image = None  # type: ignore
    PILLOW_AVAILABLE = False
try:
    from winpty import PtyProcess  # type: ignore
    WINPTY_AVAILABLE = os.name == "nt"
    WINPTY_IMPORT_ERROR = ""
except Exception as _winpty_exc:
    PtyProcess = None  # type: ignore
    WINPTY_AVAILABLE = False
    WINPTY_IMPORT_ERROR = f"{type(_winpty_exc).__name__}: {_winpty_exc}"
try:
    import websockets  # type: ignore
    WEBSOCKETS_AVAILABLE = True
    WEBSOCKETS_IMPORT_ERROR = ""
except Exception as _websockets_exc:
    websockets = None  # type: ignore
    WEBSOCKETS_AVAILABLE = False
    WEBSOCKETS_IMPORT_ERROR = f"{type(_websockets_exc).__name__}: {_websockets_exc}"

try:
    import numpy as np  # type: ignore
    from av import VideoFrame  # type: ignore
    from aiortc import RTCPeerConnection, RTCSessionDescription, RTCRtpSender, VideoStreamTrack  # type: ignore
    from aiortc.mediastreams import MediaStreamError  # type: ignore
    from aiortc.sdp import candidate_from_sdp, candidate_to_sdp  # type: ignore
    import aiortc.codecs.h264 as aiortc_h264  # type: ignore
    import aiortc.codecs.vpx as aiortc_vpx  # type: ignore
    import aiortc.rtcpeerconnection as aiortc_rtcpeerconnection  # type: ignore
    AIORTC_AVAILABLE = True
    AIORTC_IMPORT_ERROR = ""
except Exception as _aiortc_exc:
    np = None  # type: ignore
    VideoFrame = None  # type: ignore
    RTCPeerConnection = None  # type: ignore
    RTCSessionDescription = None  # type: ignore
    RTCRtpSender = None  # type: ignore
    VideoStreamTrack = object  # type: ignore
    MediaStreamError = Exception  # type: ignore
    candidate_from_sdp = None  # type: ignore
    candidate_to_sdp = None  # type: ignore
    aiortc_h264 = None  # type: ignore
    aiortc_vpx = None  # type: ignore
    aiortc_rtcpeerconnection = None  # type: ignore
    AIORTC_AVAILABLE = False
    AIORTC_IMPORT_ERROR = f"{type(_aiortc_exc).__name__}: {_aiortc_exc}"


def _patch_desktop_webrtc_codecs() -> None:
    if not AIORTC_AVAILABLE or aiortc_h264 is None or aiortc_vpx is None:
        return
    try:
        aiortc_h264.MIN_BITRATE = max(int(getattr(aiortc_h264, "MIN_BITRATE", 500000) or 500000), 1000000)
        aiortc_h264.DEFAULT_BITRATE = max(int(getattr(aiortc_h264, "DEFAULT_BITRATE", 1000000) or 1000000), 2500000)
        aiortc_h264.MAX_BITRATE = max(int(getattr(aiortc_h264, "MAX_BITRATE", 3000000) or 3000000), 5000000)
        aiortc_vpx.MIN_BITRATE = max(int(getattr(aiortc_vpx, "MIN_BITRATE", 250000) or 250000), 600000)
        aiortc_vpx.DEFAULT_BITRATE = max(int(getattr(aiortc_vpx, "DEFAULT_BITRATE", 500000) or 500000), 1800000)
        aiortc_vpx.MAX_BITRATE = max(int(getattr(aiortc_vpx, "MAX_BITRATE", 1500000) or 1500000), 3500000)
    except Exception:
        pass

    encoder_cls = getattr(aiortc_h264, "H264Encoder", None)
    if encoder_cls is None or getattr(encoder_cls, "_codrex_patched", False):
        return

    original_encode = encoder_cls.encode

    def _codrex_encode(self: Any, frame: Any, force_keyframe: bool = False):
        frames_since_keyframe = int(getattr(self, "_codrex_frames_since_keyframe", 0) or 0)
        should_force = bool(force_keyframe) or frames_since_keyframe <= 0 or frames_since_keyframe >= 12
        result = original_encode(self, frame, should_force)
        setattr(self, "_codrex_frames_since_keyframe", 1 if should_force else (frames_since_keyframe + 1))
        return result

    encoder_cls.encode = _codrex_encode  # type: ignore[assignment]
    encoder_cls._codrex_patched = True  # type: ignore[attr-defined]


_patch_desktop_webrtc_codecs()

START_TIME = time.time()
LOGGER = logging.getLogger("codrex.remote")
app = FastAPI(title="Codrex Remote UI", version="1.5.0")
APP_ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
UI_DIST_DIR = os.path.join(APP_ROOT_DIR, "ui", "dist")
UI_DIST_ASSETS_DIR = os.path.join(UI_DIST_DIR, "assets")

WSL_DISTRO = os.environ.get("CODEX_WSL_DISTRO", "Ubuntu")
WSL_EXE = os.environ.get("CODEX_WSL_EXE", "wsl")
CODEX_WORKDIR = os.environ.get("CODEX_WORKDIR", "/home/megha/codrex-work")
CODEX_WINDOWS_WORKDIR = os.path.abspath(
    os.environ.get("CODEX_WINDOWS_WORKDIR", os.path.abspath(os.path.join(APP_ROOT_DIR, "..")))
)
CODEX_WINDOWS_CLI = os.environ.get("CODEX_WINDOWS_CLI", "codex").strip() or "codex"
CODEX_AUTH_TOKEN = os.environ.get("CODEX_AUTH_TOKEN", "").strip()
CODEX_AUTH_COOKIE = os.environ.get("CODEX_AUTH_COOKIE", "codrex_remote_auth").strip() or "codrex_remote_auth"
CODEX_DESKTOP_MODE_COOKIE = os.environ.get("CODEX_DESKTOP_MODE_COOKIE", "codrex_remote_desktop_mode").strip() or "codrex_remote_desktop_mode"
CODEX_AUTH_REQUIRED = bool(CODEX_AUTH_TOKEN)
BLANK_IMAGE_DATA_URL = "data:image/gif;base64,R0lGODlhAQABAAD/ACwAAAAAAQABAAACADs="
DEFAULT_CODEX_MODELS = ["gpt-5-codex", "gpt-5", "gpt-5-mini", "gpt-4.1", "o4-mini"]
DEFAULT_REASONING_EFFORTS = ["minimal", "low", "medium", "high", "xhigh"]
BUILT_UI_ROOT_FILES = {
    "apple-touch-icon.png",
    "codrex-logo-hero.png",
    "icon-192.png",
    "icon-512.png",
    "icon-maskable-192.png",
    "icon-maskable-512.png",
    "icon-maskable.svg",
    "icon.svg",
    "manifest.webmanifest",
    "sw.js",
}
HOST_KEEP_AWAKE_ENABLED = str(os.environ.get("CODEX_HOST_KEEP_AWAKE", "1") or "1").strip().lower() not in {
    "0",
    "false",
    "no",
    "off",
}
HOST_KEEP_AWAKE_MIN_INTERVAL_S = max(5.0, float(os.environ.get("CODEX_HOST_KEEP_AWAKE_MIN_INTERVAL_S", "15") or "15"))
HOST_KEEP_AWAKE_LOCK = threading.Lock()
HOST_KEEP_AWAKE_LAST_PULSE = 0.0
ES_SYSTEM_REQUIRED = 0x00000001
ES_DISPLAY_REQUIRED = 0x00000002
ES_CONTINUOUS = 0x80000000


def _host_keep_awake_available() -> bool:
    return bool(HOST_KEEP_AWAKE_ENABLED and os.name == "nt" and getattr(ctypes, "windll", None))


def _host_keep_awake_pulse(*, force: bool = False, display_required: bool = True) -> None:
    global HOST_KEEP_AWAKE_LAST_PULSE
    if not _host_keep_awake_available():
        return
    now = time.time()
    with HOST_KEEP_AWAKE_LOCK:
        if not force and now - HOST_KEEP_AWAKE_LAST_PULSE < HOST_KEEP_AWAKE_MIN_INTERVAL_S:
            return
        flags = ES_CONTINUOUS | ES_SYSTEM_REQUIRED
        if display_required:
            flags |= ES_DISPLAY_REQUIRED
        try:
            result = int(ctypes.windll.kernel32.SetThreadExecutionState(flags))  # type: ignore[attr-defined]
        except Exception:
            return
        if result:
            HOST_KEEP_AWAKE_LAST_PULSE = now


def _host_keep_awake_release() -> None:
    global HOST_KEEP_AWAKE_LAST_PULSE
    if not _host_keep_awake_available():
        return
    with HOST_KEEP_AWAKE_LOCK:
        try:
            ctypes.windll.kernel32.SetThreadExecutionState(ES_CONTINUOUS)  # type: ignore[attr-defined]
        except Exception:
            return
        HOST_KEEP_AWAKE_LAST_PULSE = 0.0


def _built_ui_index_path() -> str:
    return os.path.join(UI_DIST_DIR, "index.html")


def _built_ui_present() -> bool:
    return os.path.isfile(_built_ui_index_path())


def _built_ui_mode() -> str:
    return "built" if _built_ui_present() else "legacy"


def _built_ui_health_payload() -> Dict[str, Any]:
    return {
        "ok": True,
        "controller_ok": True,
        "ui_mode": _built_ui_mode(),
        "build_present": _built_ui_present(),
        "dist_dir": UI_DIST_DIR,
        "entry": _built_ui_index_path(),
    }


def _serve_built_ui_root_file(filename: str) -> FileResponse:
    safe_name = posixpath.basename(filename or "")
    if safe_name not in BUILT_UI_ROOT_FILES and not safe_name.startswith("workbox-"):
        raise HTTPException(status_code=404, detail="asset_not_found")
    target = os.path.join(UI_DIST_DIR, safe_name)
    if not os.path.isfile(target):
        raise HTTPException(status_code=404, detail="asset_not_found")
    return FileResponse(target)


def _built_ui_missing_response() -> HTMLResponse:
    html = """
<!doctype html>
<html>
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>Codrex App Unavailable</title>
    <style>
      body { margin: 0; min-height: 100vh; display: grid; place-items: center; background: #edf4fb; color: #0f172a; font-family: system-ui, -apple-system, Segoe UI, Roboto, sans-serif; padding: 20px; }
      .card { width: min(100%, 560px); background: #fff; border: 1px solid #d7dfeb; border-radius: 18px; padding: 20px 22px; box-shadow: 0 18px 36px rgba(15, 23, 42, 0.12); }
      h1 { margin: 0 0 10px; font-size: 28px; }
      p { margin: 0 0 12px; line-height: 1.5; }
      code { font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; }
      .actions { display: flex; flex-wrap: wrap; gap: 10px; margin-top: 16px; }
      .actions a { text-decoration: none; border-radius: 12px; border: 1px solid #0f766e; padding: 10px 14px; font-weight: 600; }
      .primary { background: #0f766e; color: #fff; }
      .secondary { background: #fff; color: #0f766e; }
      .muted { color: #526173; font-size: 14px; }
    </style>
  </head>
  <body>
    <section class="card">
      <h1>Codrex app build missing</h1>
      <p>The controller is running, but the built web app is not available yet.</p>
      <p class="muted">Run <code>Setup.cmd</code> or <code>npm run build</code> inside <code>ui/</code>, then launch Codrex again.</p>
      <div class="actions">
        <a class="primary" href="/legacy">Open Fallback Controls</a>
        <a class="secondary" href="/auth/status">Open Auth Status</a>
      </div>
    </section>
  </body>
</html>
    """.strip()
    return HTMLResponse(content=html, status_code=503, headers={"Cache-Control": "no-store"})


def _default_runtime_dir() -> str:
    override = (
        str(os.environ.get("CODEX_RUNTIME_DIR", "") or "").strip()
        or str(os.environ.get("CODEX_RUNTIME_ROOT", "") or "").strip()
    )
    if override:
        return os.path.abspath(override)
    if os.name == "nt":
        base = (
            os.environ.get("LOCALAPPDATA")
            or os.environ.get("APPDATA")
            or os.path.expanduser("~")
        )
        return os.path.abspath(os.path.join(base, "Codrex", "remote-ui"))
    base = (
        os.environ.get("XDG_STATE_HOME")
        or os.path.join(os.path.expanduser("~"), ".local", "state")
    )
    return os.path.abspath(os.path.join(base, "codrex-remote-ui"))


def _default_host_transfer_dir() -> str:
    if os.name == "nt":
        base = (
            os.environ.get("USERPROFILE")
            or os.path.expanduser("~")
        )
        return os.path.abspath(os.path.join(base, "Downloads", "Codrex Transfers"))
    return os.path.abspath(os.path.join(os.path.expanduser("~"), "Downloads", "codrex-transfers"))


def _desktop_perf_wallpaper_path() -> str:
    return os.path.join(_default_runtime_dir(), "state", "desktop-perf-wallpaper.bmp")


def _desktop_perf_restore_wallpaper_path() -> str:
    return os.path.join(_default_runtime_dir(), "state", "desktop-perf-restore.bmp")


def _ps_single_quote(value: str) -> str:
    return str(value or "").replace("'", "''")


def _desktop_perf_powershell_helpers() -> str:
    return r"""
Add-Type -AssemblyName System.Drawing
$ProgressPreference = 'SilentlyContinue'
if (-not ('CodrexDesktopPerfNative' -as [type])) {
  Add-Type @"
using System;
using System.Runtime.InteropServices;
public static class CodrexDesktopPerfNative {
  public const int SPI_SETDESKWALLPAPER = 20;
  public const int SPIF_UPDATEINIFILE = 0x01;
  public const int SPIF_SENDWININICHANGE = 0x02;
  public static readonly IntPtr HWND_BROADCAST = new IntPtr(0xffff);
  public const uint WM_SETTINGCHANGE = 0x001A;
  public const uint SMTO_ABORTIFHUNG = 0x0002;

  [DllImport("user32.dll", SetLastError = true, CharSet = CharSet.Unicode)]
  public static extern bool SystemParametersInfo(int uiAction, int uiParam, string pvParam, int fWinIni);

  [DllImport("user32.dll", SetLastError = true, CharSet = CharSet.Unicode)]
  public static extern IntPtr SendMessageTimeout(IntPtr hWnd, uint Msg, IntPtr wParam, string lParam, uint fuFlags, uint uTimeout, out IntPtr lpdwResult);
}
"@
}

function Invoke-CodrexDesktopRefresh {
  param([string]$WallpaperPath)
  $resolvedWallpaper = ''
  if ($WallpaperPath) {
    try {
      $resolvedWallpaper = (Resolve-Path -LiteralPath $WallpaperPath -ErrorAction Stop).Path
    } catch {
      $resolvedWallpaper = $WallpaperPath
    }
  }
  [CodrexDesktopPerfNative]::SystemParametersInfo(
    [CodrexDesktopPerfNative]::SPI_SETDESKWALLPAPER,
    0,
    $resolvedWallpaper,
    [CodrexDesktopPerfNative]::SPIF_UPDATEINIFILE -bor [CodrexDesktopPerfNative]::SPIF_SENDWININICHANGE
  ) | Out-Null
  foreach ($area in @('Control Panel\Desktop', 'WindowsThemeElement', 'ImmersiveColorSet', 'TraySettings')) {
    $msgResult = [IntPtr]::Zero
    [CodrexDesktopPerfNative]::SendMessageTimeout(
      [CodrexDesktopPerfNative]::HWND_BROADCAST,
      [CodrexDesktopPerfNative]::WM_SETTINGCHANGE,
      [IntPtr]::Zero,
      $area,
      [CodrexDesktopPerfNative]::SMTO_ABORTIFHUNG,
      5000,
      [ref]$msgResult
    ) | Out-Null
  }
  & "$env:WINDIR\System32\cmd.exe" /c 'RUNDLL32.EXE user32.dll,UpdatePerUserSystemParameters 1, True' | Out-Null
}
"""


def _parse_csv_config(raw: str, fallback: List[str]) -> List[str]:
    values: List[str] = []
    for part in (raw or "").split(","):
        candidate = part.strip()
        if not candidate:
            continue
        if candidate not in values:
            values.append(candidate)
    return values or list(fallback)


CODEX_MODEL_OPTIONS = _parse_csv_config(os.environ.get("CODEX_MODEL_OPTIONS", ""), DEFAULT_CODEX_MODELS)
CODEX_DEFAULT_MODEL = (os.environ.get("CODEX_DEFAULT_MODEL", "").strip() or CODEX_MODEL_OPTIONS[0]).strip()
if CODEX_DEFAULT_MODEL not in CODEX_MODEL_OPTIONS:
    CODEX_MODEL_OPTIONS = [CODEX_DEFAULT_MODEL, *[m for m in CODEX_MODEL_OPTIONS if m != CODEX_DEFAULT_MODEL]]

CODEX_REASONING_EFFORT_OPTIONS = _parse_csv_config(
    os.environ.get("CODEX_REASONING_EFFORT_OPTIONS", ""),
    DEFAULT_REASONING_EFFORTS,
)
_reasoning_default_env = os.environ.get("CODEX_DEFAULT_REASONING_EFFORT", "").strip().lower()
if _reasoning_default_env in CODEX_REASONING_EFFORT_OPTIONS:
    CODEX_DEFAULT_REASONING_EFFORT = _reasoning_default_env
elif "xhigh" in CODEX_REASONING_EFFORT_OPTIONS:
    CODEX_DEFAULT_REASONING_EFFORT = "xhigh"
else:
    CODEX_DEFAULT_REASONING_EFFORT = CODEX_REASONING_EFFORT_OPTIONS[-1]

# Pairing codes are short-lived one-time secrets used to authenticate a second device (phone/tablet)
# without typing the long CODEX_AUTH_TOKEN. They are only generated by an already-authenticated client.
PAIRING_TTL_SECONDS = int(os.environ.get("CODEX_PAIRING_TTL_SECONDS", "90"))
PAIRING_LOCK = threading.Lock()
PAIRING_CODES: Dict[str, float] = {}

def pairing_create_code() -> Dict[str, Any]:
    code = secrets.token_urlsafe(18)
    now = time.time()
    expires_at = now + max(10, PAIRING_TTL_SECONDS)
    with PAIRING_LOCK:
        # Best-effort cleanup of expired entries.
        for k, exp in list(PAIRING_CODES.items()):
            if exp <= now:
                PAIRING_CODES.pop(k, None)
        PAIRING_CODES[code] = expires_at
    return {"code": code, "expires_in": int(expires_at - now)}

def pairing_consume_code(code: str) -> bool:
    if not code:
        return False
    now = time.time()
    with PAIRING_LOCK:
        exp = PAIRING_CODES.get(code)
        if not exp:
            return False
        if exp <= now:
            PAIRING_CODES.pop(code, None)
            return False
        PAIRING_CODES.pop(code, None)
    return True


def _normalize_pair_route(raw: Any) -> str:
    value = str(raw or "").strip().lower()
    if value in {"tailscale", "netbird", "lan", "current"}:
        return value
    return "tailscale"


def _launcher_state_file_path() -> str:
    return os.path.join(CODEX_RUNTIME_STATE_DIR, "launcher.state.json")


def _preferred_pair_route() -> str:
    prefs = _read_json_file(_launcher_state_file_path())
    return _normalize_pair_route(prefs.get("preferred_pair_route"))


def _trusted_device_token_hash(token: str) -> str:
    return hashlib.sha256(str(token or "").encode("utf-8")).hexdigest()


def _load_trusted_devices_unlocked() -> None:
    global TRUSTED_DEVICES_LOADED
    if TRUSTED_DEVICES_LOADED:
        return
    loaded = _read_json_file(TRUSTED_DEVICES_FILE)
    devices = loaded.get("devices") if isinstance(loaded, dict) else None
    TRUSTED_DEVICES_DATA["devices"] = list(devices) if isinstance(devices, list) else []
    TRUSTED_DEVICES_LOADED = True


def _persist_trusted_devices_unlocked() -> None:
    devices = [
        item for item in list(TRUSTED_DEVICES_DATA.get("devices") or [])
        if isinstance(item, dict) and str(item.get("id") or "").strip()
    ]
    devices.sort(key=lambda item: float(item.get("updated_at") or item.get("created_at") or 0.0), reverse=True)
    if TRUSTED_DEVICES_MAX_KEEP > 0:
        devices = devices[:TRUSTED_DEVICES_MAX_KEEP]
    TRUSTED_DEVICES_DATA["devices"] = devices
    _write_json_file(TRUSTED_DEVICES_FILE, {"devices": devices})


def _issue_trusted_device(name: str = "", platform: str = "", current_origin: str = "") -> Dict[str, Any]:
    device_id = f"android_{secrets.token_urlsafe(9)}"
    device_token = secrets.token_urlsafe(32)
    now = time.time()
    record = {
        "id": device_id,
        "token_hash": _trusted_device_token_hash(device_token),
        "name": str(name or "").strip()[:120] or "Codrex Android",
        "platform": str(platform or "").strip()[:48] or "android",
        "created_at": now,
        "updated_at": now,
        "last_seen_at": now,
        "last_origin": str(current_origin or "").strip(),
    }
    with TRUSTED_DEVICES_LOCK:
        _load_trusted_devices_unlocked()
        devices = [item for item in list(TRUSTED_DEVICES_DATA.get("devices") or []) if isinstance(item, dict)]
        devices.insert(0, record)
        TRUSTED_DEVICES_DATA["devices"] = devices
        _persist_trusted_devices_unlocked()
    return {
        "device_id": device_id,
        "device_token": device_token,
        "device_name": record["name"],
        "device_platform": record["platform"],
    }


def _reissue_trusted_device(
    device_id: str = "",
    name: str = "",
    platform: str = "",
    current_origin: str = "",
) -> Dict[str, Any]:
    wanted_id = str(device_id or "").strip()
    if not wanted_id:
        return _issue_trusted_device(name=name, platform=platform, current_origin=current_origin)

    device_token = secrets.token_urlsafe(32)
    now = time.time()
    with TRUSTED_DEVICES_LOCK:
        _load_trusted_devices_unlocked()
        devices = [item for item in list(TRUSTED_DEVICES_DATA.get("devices") or []) if isinstance(item, dict)]
        for item in devices:
            if str(item.get("id") or "").strip() != wanted_id:
                continue
            item["token_hash"] = _trusted_device_token_hash(device_token)
            item["name"] = str(name or item.get("name") or "").strip()[:120] or "Codrex Android"
            item["platform"] = str(platform or item.get("platform") or "").strip()[:48] or "android"
            item["updated_at"] = now
            item["last_seen_at"] = now
            if current_origin:
                item["last_origin"] = str(current_origin).strip()
            TRUSTED_DEVICES_DATA["devices"] = devices
            _persist_trusted_devices_unlocked()
            return {
                "device_id": str(item.get("id") or "").strip(),
                "device_token": device_token,
                "device_name": str(item.get("name") or "").strip(),
                "device_platform": str(item.get("platform") or "").strip(),
            }
    return _issue_trusted_device(name=name, platform=platform, current_origin=current_origin)


def _resume_trusted_device(device_id: str, device_token: str, current_origin: str = "") -> Dict[str, Any]:
    wanted_id = str(device_id or "").strip()
    wanted_token = str(device_token or "").strip()
    if not wanted_id or not wanted_token:
        return {}
    token_hash = _trusted_device_token_hash(wanted_token)
    now = time.time()
    with TRUSTED_DEVICES_LOCK:
        _load_trusted_devices_unlocked()
        devices = [item for item in list(TRUSTED_DEVICES_DATA.get("devices") or []) if isinstance(item, dict)]
        for item in devices:
            if str(item.get("id") or "").strip() != wanted_id:
                continue
            if str(item.get("token_hash") or "").strip() != token_hash:
                return {}
            item["last_seen_at"] = now
            item["updated_at"] = now
            if current_origin:
                item["last_origin"] = str(current_origin).strip()
            TRUSTED_DEVICES_DATA["devices"] = devices
            _persist_trusted_devices_unlocked()
            return dict(item)
    return {}


def _win_kernel32():
    _ensure_windows_host()
    return ctypes.windll.kernel32


def _is_windows_pid_running(pid: int) -> bool:
    if os.name != "nt":
        return False
    wanted_pid = int(pid or 0)
    if wanted_pid <= 0:
        return False
    kernel32 = _win_kernel32()
    PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
    STILL_ACTIVE = 259
    handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, wanted_pid)
    if not handle:
        return False
    try:
        exit_code = wintypes.DWORD(0)
        ok = kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code))
        if not ok:
            return False
        return int(exit_code.value or 0) == STILL_ACTIVE
    finally:
        try:
            kernel32.CloseHandle(handle)
        except Exception:
            pass


def _terminate_windows_pid(pid: int) -> bool:
    wanted_pid = int(pid or 0)
    if os.name != "nt" or wanted_pid <= 0:
        return True
    if not _is_windows_pid_running(wanted_pid):
        return True
    try:
        result = subprocess.run(
            ["taskkill", "/PID", str(wanted_pid), "/T", "/F"],
            capture_output=True,
            text=True,
            timeout=5,
            encoding="utf-8",
            errors="replace",
        )
        output = (str(getattr(result, "stdout", "") or "") + "\n" + str(getattr(result, "stderr", "") or "")).lower()
        if int(getattr(result, "returncode", 1) or 1) == 0:
            if not _is_windows_pid_running(wanted_pid):
                return True
        elif "not found" in output or "no running instance" in output:
            return True
    except Exception:
        pass
    try:
        os.kill(wanted_pid, signal.SIGTERM)
    except Exception:
        pass
    time.sleep(0.05)
    return not _is_windows_pid_running(wanted_pid)


def _legacy_privacy_lock_helper_pids() -> List[int]:
    if os.name != "nt":
        return []
    try:
        result = subprocess.run(
            [
                "powershell",
                "-NoProfile",
                "-NonInteractive",
                "-Command",
                (
                    "$items = Get-CimInstance Win32_Process | "
                    "Where-Object { $_.Name -eq 'Codrex.Launcher.exe' -and $_.CommandLine -like '*--privacy-lock-helper*' } | "
                    "Select-Object -ExpandProperty ProcessId; "
                    "if ($items -eq $null) { '[]' } else { $items | ConvertTo-Json -Compress }"
                ),
            ],
            capture_output=True,
            text=True,
            timeout=8,
            encoding="utf-8",
            errors="replace",
        )
    except Exception:
        return []
    if int(getattr(result, "returncode", 1) or 1) != 0:
        return []
    raw = str(getattr(result, "stdout", "") or "").strip()
    if not raw:
        return []
    try:
        parsed = json.loads(raw)
    except Exception:
        return []
    if isinstance(parsed, int):
        return [int(parsed)]
    if not isinstance(parsed, list):
        return []
    output: List[int] = []
    for item in parsed:
        try:
            output.append(int(item))
        except Exception:
            continue
    return output


def _cleanup_legacy_privacy_lock_state() -> None:
    helper_pids = sorted({pid for pid in _legacy_privacy_lock_helper_pids() if int(pid or 0) > 0})
    for pid in helper_pids:
        try:
            _terminate_windows_pid(pid)
        except Exception:
            pass
    for path in (LEGACY_PRIVACY_LOCK_STATE_FILE, LEGACY_PRIVACY_LOCK_CONFIG_FILE):
        try:
            if os.path.isfile(path):
                os.remove(path)
        except Exception:
            pass


def _tailscale_exe_path() -> str:
    if os.name != "nt":
        return ""
    pf = os.environ.get("ProgramFiles", r"C:\Program Files")
    pf86 = os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")
    local_app_data = os.environ.get("LocalAppData", "")
    candidates = [
        os.path.join(pf, "Tailscale", "tailscale.exe"),
        os.path.join(pf86, "Tailscale", "tailscale.exe"),
        os.path.join(local_app_data, "Tailscale", "tailscale.exe"),
    ]
    for p in candidates:
        if p and os.path.exists(p):
            return p

    # Per-user installs can be available via PATH but not under Program Files.
    for cmd in ("tailscale.exe", "tailscale"):
        try:
            exe = shutil.which(cmd)
        except Exception:
            exe = ""
        if exe and os.path.exists(exe):
            return exe

    # Last fallback for Windows shells where PATH lookup is odd in service contexts.
    try:
        out = subprocess.check_output(
            ["where", "tailscale"],
            text=True,
            timeout=5,
            stderr=subprocess.DEVNULL,
        )
        for line in out.splitlines():
            candidate = line.strip()
            if candidate and os.path.exists(candidate):
                return candidate
    except Exception:
        pass
    return ""


def _adapter_ipv4_from_ipconfig(adapter_keywords: List[str]) -> str:
    """
    Best-effort Windows adapter detection by parsing ipconfig blocks.
    """
    if os.name != "nt":
        return ""
    try:
        out = subprocess.check_output(
            ["ipconfig"],
            text=True,
            timeout=5,
            stderr=subprocess.DEVNULL,
            encoding="utf-8",
            errors="ignore",
        )
    except Exception:
        return ""

    wanted = [str(keyword or "").strip().lower() for keyword in adapter_keywords if str(keyword or "").strip()]
    in_adapter_block = False
    for raw_line in out.splitlines():
        line = (raw_line or "").strip()
        low = line.lower()

        # Adapter section headers are not indented in ipconfig output.
        is_section_header = bool(line) and line.endswith(":") and raw_line == raw_line.lstrip()
        if is_section_header:
            in_adapter_block = any(keyword in low for keyword in wanted)
            continue
        if not in_adapter_block:
            continue

        m = re.search(r"(\d+\.\d+\.\d+\.\d+)", line)
        if not m:
            continue
        ip = m.group(1).strip()
        if ip and ip != "127.0.0.1" and not ip.startswith("169.254."):
            return ip
    return ""


def _tailscale_ipv4_from_ipconfig() -> str:
    """
    Best-effort fallback for Windows setups where tailscale.exe is unavailable
    to this process (PATH/service context), but the Tailscale adapter exists.
    """
    return _adapter_ipv4_from_ipconfig(["tailscale"])


def get_tailscale_ipv4() -> str:
    if os.name != "nt":
        return ""
    exe = _tailscale_exe_path()
    if not exe:
        return _tailscale_ipv4_from_ipconfig()
    try:
        out = subprocess.check_output([exe, "ip", "-4"], text=True, timeout=5).strip()
        ip = (out.splitlines()[0].strip() if out else "")
        if re.match(r"^\d+\.\d+\.\d+\.\d+$", ip):
            return ip
    except Exception:
        pass
    try:
        out = subprocess.check_output(
            [exe, "status", "--json"],
            text=True,
            timeout=5,
            stderr=subprocess.DEVNULL,
        )
        data = json.loads(out)
        if isinstance(data, dict):
            candidates: List[str] = []
            self_obj = data.get("Self")
            if isinstance(self_obj, dict):
                self_ips = self_obj.get("TailscaleIPs")
                if isinstance(self_ips, list):
                    candidates.extend(str(v) for v in self_ips)
            top_ips = data.get("TailscaleIPs")
            if isinstance(top_ips, list):
                candidates.extend(str(v) for v in top_ips)
            for ip in candidates:
                if re.match(r"^\d+\.\d+\.\d+\.\d+$", ip.strip()):
                    return ip.strip()
    except Exception:
        pass
    try:
        out = subprocess.check_output(
            [exe, "status"],
            text=True,
            timeout=5,
            stderr=subprocess.DEVNULL,
        )
        for line in out.splitlines():
            m = re.match(r"^\s*(\d+\.\d+\.\d+\.\d+)\s+", line)
            if m:
                return m.group(1)
    except Exception:
        pass
    return _tailscale_ipv4_from_ipconfig()


def _netbird_ipv4_from_ipconfig() -> str:
    return _adapter_ipv4_from_ipconfig(["netbird"])


def get_netbird_ipv4() -> str:
    if os.name != "nt":
        return ""
    return _netbird_ipv4_from_ipconfig()


def guess_lan_ipv4() -> str:
    # Works on Windows and Linux. Doesn't actually send packets, just picks the default route.
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return ""


def _origin_payload(provider: str, host: str, port: int, *, private: bool = False) -> Dict[str, Any]:
    cleaned_host = str(host or "").strip()
    if not cleaned_host:
        return {}
    effective_port = int(port or 0) or 48787
    return {
        "provider": provider,
        "host": cleaned_host,
        "origin": f"http://{cleaned_host}:{effective_port}",
        "label": provider.replace("_", " ").title(),
        "private": bool(private),
    }


def _route_priority() -> List[str]:
    # Keep Tailscale as the default private route until NetBird proves itself.
    return ["tailscale", "netbird", "lan", "localhost"]


def _classify_route_provider(host: str, net_info: Optional[Dict[str, Any]] = None) -> str:
    normalized = str(host or "").strip().lower()
    if not normalized:
        return "unknown"
    if normalized in {"localhost", "127.0.0.1", "::1"}:
        return "localhost"
    info = net_info or {}
    netbird_ip = str(info.get("netbird_ip") or "").strip().lower()
    tailscale_ip = str(info.get("tailscale_ip") or "").strip().lower()
    lan_ip = str(info.get("lan_ip") or "").strip().lower()
    if netbird_ip and normalized == netbird_ip:
        return "netbird"
    if tailscale_ip and normalized == tailscale_ip:
        return "tailscale"
    if lan_ip and normalized == lan_ip:
        return "lan"
    return "unknown"


def _build_available_origins(controller_port: int, net_info: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
    info = dict(net_info or {})
    items: List[Dict[str, Any]] = []
    seen: set[str] = set()
    for provider, host, private in (
        ("tailscale", str(info.get("tailscale_ip") or "").strip(), True),
        ("netbird", str(info.get("netbird_ip") or "").strip(), True),
        ("lan", str(info.get("lan_ip") or "").strip(), False),
        ("localhost", "127.0.0.1", False),
    ):
        payload = _origin_payload(provider, host, controller_port, private=private)
        origin = str(payload.get("origin") or "").strip()
        if not origin or origin in seen:
            continue
        seen.add(origin)
        items.append(payload)
    return items


def _resolve_preferred_origin(
    controller_port: int,
    net_info: Optional[Dict[str, Any]] = None,
    request_host: str = "",
) -> Tuple[str, str, str]:
    items = _build_available_origins(controller_port, net_info)
    info = dict(net_info or {})
    current_provider = _classify_route_provider(request_host, info)
    if current_provider in {"tailscale", "netbird", "lan"}:
        for item in items:
            if str(item.get("provider") or "") == current_provider:
                provider = str(item.get("provider") or "unknown")
                return str(item.get("origin") or ""), provider, "connected"

    for wanted in _route_priority():
        for item in items:
            if str(item.get("provider") or "") == wanted:
                provider = str(item.get("provider") or "unknown")
                if provider in {"tailscale", "netbird"}:
                    return str(item.get("origin") or ""), provider, "connected"
                if provider == "lan":
                    return str(item.get("origin") or ""), provider, "local_only"
                return str(item.get("origin") or ""), provider, "local_only"
    return "", "unknown", "unavailable"


def _compute_net_info_payload() -> Dict[str, Any]:
    mac_info = _wake_mac_info()
    lan_ip = guess_lan_ipv4()
    tailscale_ip = get_tailscale_ipv4()
    netbird_ip = get_netbird_ipv4()
    preferred_pair_route = _preferred_pair_route()
    controller_port = 48787
    try:
        persisted = _read_json_file(os.path.join(APP_ROOT_DIR, "controller.config.json")) or {}
        controller_port = int((persisted or {}).get("port") or 0) or controller_port
    except Exception:
        controller_port = 48787
    available_origins = _build_available_origins(
        controller_port,
        {
            "lan_ip": lan_ip,
            "tailscale_ip": tailscale_ip,
            "netbird_ip": netbird_ip,
        },
    )
    preferred_origin, route_provider, route_state = _resolve_preferred_origin(
        controller_port,
        {
            "lan_ip": lan_ip,
            "tailscale_ip": tailscale_ip,
            "netbird_ip": netbird_ip,
        },
    )
    tailscale_available = bool(tailscale_ip)
    tailscale_warning = (
        "Tailscale is off on this laptop."
        if preferred_pair_route == "tailscale" and not tailscale_available
        else ""
    )
    return {
        "ok": True,
        "lan_ip": lan_ip,
        "tailscale_ip": tailscale_ip,
        "netbird_ip": netbird_ip,
        "preferred_pair_route": preferred_pair_route,
        "tailscale_available": tailscale_available,
        "tailscale_warning": tailscale_warning,
        "available_origins": available_origins,
        "preferred_origin": preferred_origin,
        "route_provider": route_provider,
        "route_state": route_state,
        "primary_mac": str(mac_info.get("primary_mac") or ""),
        "wake_candidate_macs": list(mac_info.get("wake_candidate_macs") or []),
        "wake_supported": bool(mac_info.get("wake_supported")),
    }


def _get_cached_net_info(force: bool = False) -> Dict[str, Any]:
    now = time.time()
    with NET_INFO_CACHE_LOCK:
        cached_at = float(NET_INFO_CACHE.get("loaded_at") or 0.0)
        cached_payload = NET_INFO_CACHE.get("payload")
        if not force and isinstance(cached_payload, dict) and (now - cached_at) < NET_INFO_CACHE_TTL_S:
            return dict(cached_payload)
        payload = _compute_net_info_payload()
        NET_INFO_CACHE["loaded_at"] = now
        NET_INFO_CACHE["payload"] = dict(payload)
        return payload


def _normalize_mac_address(value: str) -> str:
    raw = re.sub(r"[^0-9A-Fa-f]", "", str(value or ""))
    if len(raw) != 12:
        return ""
    raw = raw.upper()
    return ":".join(raw[i:i + 2] for i in range(0, 12, 2))


def _wake_mac_info() -> Dict[str, Any]:
    if os.name != "nt":
        return {
            "primary_mac": "",
            "wake_candidate_macs": [],
            "wake_supported": False,
        }
    script = (
        "$ErrorActionPreference = 'Stop'; "
        "$primary = $null; "
        "try { "
        "$route = Get-NetRoute -DestinationPrefix '0.0.0.0/0' "
        "| Where-Object { $_.NextHop -and $_.NextHop -ne '0.0.0.0' } "
        "| Sort-Object RouteMetric, ifMetric | Select-Object -First 1; "
        "if ($route) { $primary = Get-NetAdapter -InterfaceIndex $route.ifIndex -ErrorAction SilentlyContinue | Select-Object -First 1 } "
        "} catch {} "
        "$adapters = @(Get-NetAdapter | Where-Object { $_.MacAddress -and $_.Status -ne 'Disabled' } | Select-Object -First 12); "
        "[pscustomobject]@{ "
        "primary_mac = if ($primary) { $primary.MacAddress } else { '' }; "
        "candidates = @($adapters | ForEach-Object { $_.MacAddress }); "
        "} | ConvertTo-Json -Compress"
    )
    r = _run_powershell(script, timeout_s=6)
    if r.get("exit_code") != 0:
        return {
            "primary_mac": "",
            "wake_candidate_macs": [],
            "wake_supported": False,
        }
    try:
        data = json.loads(r.get("stdout") or "{}")
    except Exception:
        data = {}
    primary = _normalize_mac_address(data.get("primary_mac", ""))
    candidates: List[str] = []
    seen: set[str] = set()
    for raw in data.get("candidates") or []:
        mac = _normalize_mac_address(str(raw or ""))
        if not mac or mac in seen:
            continue
        seen.add(mac)
        candidates.append(mac)
    if primary and primary not in seen:
        candidates.insert(0, primary)
    return {
        "primary_mac": primary,
        "wake_candidate_macs": candidates,
        "wake_supported": bool(primary or candidates),
    }


def _wake_adapter_kind(name: str, description: str) -> str:
    haystack = f"{name or ''} {description or ''}".strip().lower()
    if re.search(r"\b(wi-?fi|wireless|wlan|802\.11)\b", haystack):
        return "wifi"
    if re.search(r"\b(ethernet|gigabit|gbe|lan)\b", haystack):
        return "ethernet"
    return "unknown"


def _normalize_wake_label(value: str) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip()).lower()


def _wake_adapter_matches_line(adapter: Dict[str, Any], line: str) -> bool:
    target = _normalize_wake_label(line)
    if not target:
        return False
    candidates = {
        _normalize_wake_label(adapter.get("name", "")),
        _normalize_wake_label(adapter.get("interface_description", "")),
    }
    candidates.discard("")
    for candidate in candidates:
        if target == candidate or target in candidate or candidate in target:
            return True
    return False


def _classify_wake_local_capabilities(snapshot: Dict[str, Any]) -> Dict[str, Any]:
    adapters_raw = snapshot.get("adapters") or []
    wake_armed_lines = [
        str(line or "").strip()
        for line in (snapshot.get("wake_armed") or [])
        if str(line or "").strip() and str(line or "").strip().upper() != "NONE"
    ]
    primary_name = str(snapshot.get("primary_name") or "").strip()
    primary_desc = str(snapshot.get("primary_desc") or "").strip()

    adapters: List[Dict[str, Any]] = []
    for raw in adapters_raw if isinstance(adapters_raw, list) else []:
        if not isinstance(raw, dict):
            continue
        name = str(raw.get("name") or "").strip()
        interface_description = str(raw.get("interface_description") or raw.get("desc") or "").strip()
        adapter = {
            "name": name,
            "interface_description": interface_description,
            "status": str(raw.get("status") or "").strip(),
            "kind": _wake_adapter_kind(name, interface_description),
            "wake_magic": str(raw.get("wake_magic") or "").strip().lower(),
            "wake_pattern": str(raw.get("wake_pattern") or "").strip().lower(),
        }
        adapter["wake_capable"] = adapter["wake_magic"] not in {"", "unsupported", "notsupported"}
        adapter["wake_armed"] = any(_wake_adapter_matches_line(adapter, line) for line in wake_armed_lines)
        adapter["is_primary"] = bool(
            (primary_name and _normalize_wake_label(primary_name) == _normalize_wake_label(name))
            or (primary_desc and _normalize_wake_label(primary_desc) == _normalize_wake_label(interface_description))
        )
        adapters.append(adapter)

    has_ethernet = any(adapter["kind"] == "ethernet" for adapter in adapters)
    has_wifi = any(adapter["kind"] == "wifi" for adapter in adapters)
    capable_adapters = [adapter for adapter in adapters if bool(adapter.get("wake_capable"))]
    armed_adapters = [adapter for adapter in capable_adapters if bool(adapter.get("wake_armed"))]
    primary_adapter = next((adapter for adapter in adapters if adapter.get("is_primary")), None)

    if armed_adapters:
        readiness = "ready"
        warning = ""
    elif capable_adapters:
        readiness = "partial"
        if transport_hint == "ethernet":
            warning = (
                "Wake support is present but not armed on this host. Confirm BIOS/UEFI Wake-on-LAN and "
                "Windows adapter power settings, then test with Ethernet connected."
            )
        elif transport_hint == "wifi":
            warning = (
                "Wake support is present but not armed on this host. Confirm BIOS/UEFI wake settings and do not "
                "rely on Wi-Fi wake; Ethernet is preferred."
            )
        else:
            warning = "Wake support is present but not armed on this host. Confirm BIOS/UEFI and Windows wake settings."
    else:
        readiness = "unsupported"
        if has_ethernet:
            warning = (
                "Wake is not confirmed on this host. An Ethernet adapter exists, but Windows is not exposing "
                "Wake-on-Magic-Packet yet."
            )
        elif has_wifi:
            warning = (
                "Wake is not confirmed on this host. This machine appears to rely on Wi-Fi, and Wake-on-WLAN is "
                "often unsupported."
            )
        else:
            warning = "Wake is not confirmed on this host. No wake-capable physical adapter was detected."

    transport_hint = "unknown"
    if readiness != "ready" and has_ethernet:
        transport_hint = "ethernet"
    elif primary_adapter and primary_adapter.get("kind") != "unknown":
        transport_hint = str(primary_adapter.get("kind") or "unknown")
    elif has_ethernet:
        transport_hint = "ethernet"
    elif has_wifi:
        transport_hint = "wifi"

    return {
        "wake_readiness": readiness,
        "wake_warning": warning,
        "wake_transport_hint": transport_hint,
        "wake_capable": bool(capable_adapters),
        "wake_armed": bool(armed_adapters),
    }


def _wake_local_capabilities() -> Dict[str, Any]:
    if os.name != "nt":
        return {
            "wake_readiness": "unsupported",
            "wake_warning": "Wake diagnostics are only available on Windows hosts.",
            "wake_transport_hint": "unknown",
            "wake_capable": False,
            "wake_armed": False,
        }
    script = (
        "$ErrorActionPreference = 'Stop'; "
        "$primary = $null; "
        "try { "
        "$route = Get-NetRoute -DestinationPrefix '0.0.0.0/0' "
        "| Where-Object { $_.NextHop -and $_.NextHop -ne '0.0.0.0' } "
        "| Sort-Object RouteMetric, ifMetric | Select-Object -First 1; "
        "if ($route) { $primary = Get-NetAdapter -InterfaceIndex $route.ifIndex -ErrorAction SilentlyContinue | Select-Object -First 1 } "
        "} catch {} "
        "$wakeArmed = @(); "
        "try { $wakeArmed = @((powercfg /devicequery wake_armed 2>$null) | Where-Object { $_ -and $_.Trim() -and $_.Trim().ToUpper() -ne 'NONE' } | ForEach-Object { $_.Trim() }) } catch {} "
        "$adapters = @(Get-NetAdapter | Where-Object { $_.HardwareInterface -and $_.MacAddress -and $_.Status -ne 'Disabled' }); "
        "$details = @($adapters | ForEach-Object { "
        "$pm = Get-NetAdapterPowerManagement -Name $_.Name -ErrorAction SilentlyContinue; "
        "[pscustomobject]@{ "
        "name = $_.Name; "
        "interface_description = $_.InterfaceDescription; "
        "status = $_.Status; "
        "wake_magic = if ($pm) { [string]$pm.WakeOnMagicPacket } else { '' }; "
        "wake_pattern = if ($pm) { [string]$pm.WakeOnPattern } else { '' }; "
        "} "
        "}); "
        "[pscustomobject]@{ "
        "primary_name = if ($primary) { $primary.Name } else { '' }; "
        "primary_desc = if ($primary) { $primary.InterfaceDescription } else { '' }; "
        "wake_armed = $wakeArmed; "
        "adapters = $details; "
        "} | ConvertTo-Json -Compress -Depth 5"
    )
    result = _run_powershell(script, timeout_s=8)
    if result.get("exit_code") != 0:
        return {
            "wake_readiness": "partial",
            "wake_warning": "Wake diagnostics could not read Windows adapter power state. Verify BIOS/UEFI and adapter wake settings manually.",
            "wake_transport_hint": "unknown",
            "wake_capable": False,
            "wake_armed": False,
        }
    try:
        snapshot = json.loads(result.get("stdout") or "{}")
    except Exception:
        snapshot = {}
    if not isinstance(snapshot, dict):
        snapshot = {}
    return _classify_wake_local_capabilities(snapshot)


def _merge_wake_warning(base: str, extra: str) -> str:
    primary = str(base or "").strip()
    secondary = str(extra or "").strip()
    if not primary:
        return secondary
    if not secondary:
        return primary
    if secondary in primary:
        return primary
    return f"{primary} {secondary}".strip()


def _request_json_url(url: str, method: str = "GET", payload: Optional[Dict[str, Any]] = None, headers: Optional[Dict[str, str]] = None, timeout_s: float = 5.0) -> Tuple[Optional[int], Dict[str, Any]]:
    req_headers = dict(headers or {})
    data: Optional[bytes] = None
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        req_headers.setdefault("Content-Type", "application/json")
    req = urllib.request.Request(url, data=data, headers=req_headers, method=method.upper())
    try:
        with urllib.request.urlopen(req, timeout=max(0.5, timeout_s)) as resp:
            raw = (resp.read() or b"").decode("utf-8", errors="replace")
            try:
                parsed = json.loads(raw) if raw.strip() else {}
            except Exception:
                parsed = {"detail": raw.strip()}
            return getattr(resp, "status", 200), parsed if isinstance(parsed, dict) else {"value": parsed}
    except urllib.error.HTTPError as e:
        raw = (e.read() or b"").decode("utf-8", errors="replace")
        try:
            parsed = json.loads(raw) if raw.strip() else {}
        except Exception:
            parsed = {"detail": raw.strip() or str(e)}
        return int(getattr(e, "code", 500) or 500), parsed if isinstance(parsed, dict) else {"value": parsed}
    except Exception as e:
        return None, {"detail": f"{type(e).__name__}: {e}"}


def _wake_relay_health() -> Dict[str, Any]:
    if not CODEX_WAKE_RELAY_URL:
        return {
            "configured": False,
            "reachable": False,
            "detail": "Wake relay URL is not configured.",
            "wake_surface": "telegram",
            "wake_command": CODEX_WAKE_TELEGRAM_COMMAND,
        }
    headers: Dict[str, str] = {}
    if CODEX_WAKE_RELAY_TOKEN:
        headers["x-relay-token"] = CODEX_WAKE_RELAY_TOKEN
    status, payload = _request_json_url(
        f"{CODEX_WAKE_RELAY_URL}/health",
        method="GET",
        headers=headers,
        timeout_s=CODEX_WAKE_RELAY_TIMEOUT_SECONDS,
    )
    if status is None:
        return {
            "configured": True,
            "reachable": False,
            "detail": str(payload.get("detail") or "relay_unreachable"),
            "wake_surface": "telegram",
            "wake_command": str(payload.get("wake_command") or CODEX_WAKE_TELEGRAM_COMMAND),
        }
    return {
        "configured": True,
        "reachable": 200 <= status < 300 and bool(payload.get("ok", True)),
        "detail": str(payload.get("detail") or "").strip(),
        "wake_surface": str(payload.get("wake_surface") or "telegram"),
        "wake_command": str(payload.get("wake_command") or CODEX_WAKE_TELEGRAM_COMMAND),
    }

# WSL file access is restricted to this root by default (safer).
# You can widen later by setting CODEX_FILE_ROOT to e.g. "/home/megha"
CODEX_FILE_ROOT = os.environ.get("CODEX_FILE_ROOT", CODEX_WORKDIR)
CODEX_RUNTIME_DIR = _default_runtime_dir()
CODEX_RUNTIME_ROOT = CODEX_RUNTIME_DIR
CODEX_RUNTIME_STATE_DIR = os.path.join(CODEX_RUNTIME_DIR, "state")
CODEX_RUNTIME_LOGS_DIR = os.path.join(CODEX_RUNTIME_DIR, "logs")
CODEX_RUNTIME_SECRETS_DIR = os.path.join(CODEX_RUNTIME_DIR, "secrets")
CODEX_RUNTIME_TELEGRAM_DIR = os.path.join(CODEX_RUNTIME_SECRETS_DIR, "telegram")
CODEX_HOST_TRANSFER_ROOT = os.path.abspath(
    str(os.environ.get("CODEX_HOST_TRANSFER_ROOT") or _default_host_transfer_dir()).strip()
)
CODEX_HOST_PASTE_CACHE_DIR = os.path.join(CODEX_RUNTIME_DIR, "host-paste-cache")
LEGACY_RUNTIME_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))

VALID_NAME_RE = re.compile(r"^[A-Za-z0-9_.-]+$")
VALID_PANE_RE = re.compile(r"^%\d+$")
VALID_ENTITY_ID_RE = re.compile(r"^[A-Za-z0-9_.-]{3,96}$")
VALID_CODEX_MODEL_RE = re.compile(r"^[A-Za-z0-9._:/-]{2,120}$")
VALID_RESUME_ID_RE = re.compile(r"^[A-Za-z0-9_-]{8,}$")

# -------------------------
# Small in-memory run store
# -------------------------
RUNS_LOCK = threading.Lock()
RUNS: Dict[str, Dict[str, Any]] = {}
RUNS_ORDER: List[str] = []
MAX_RUNS_KEEP = 50
MAX_CONCURRENT_RUNS = 2
MAX_DESKTOP_TEXT = 2000
SHOW_CURSOR_OVERLAY = os.environ.get("CODEX_SHOW_CURSOR_OVERLAY", "1").strip().lower() not in {"0", "false", "no"}
DESKTOP_STREAM_FPS_DEFAULT = float(os.environ.get("CODEX_DESKTOP_STREAM_FPS", "3.0") or "3.0")
DESKTOP_STREAM_PNG_LEVEL_DEFAULT = int(os.environ.get("CODEX_DESKTOP_STREAM_PNG_LEVEL", "3") or "3")
DESKTOP_STREAM_FORMAT_DEFAULT = str(os.environ.get("CODEX_DESKTOP_STREAM_FORMAT", "png") or "png").strip().lower()
DESKTOP_STREAM_JPEG_QUALITY_DEFAULT = int(os.environ.get("CODEX_DESKTOP_STREAM_JPEG_QUALITY", "74") or "74")
DESKTOP_WEBRTC_ENABLED = str(os.environ.get("CODEX_DESKTOP_WEBRTC", "1") or "1").strip().lower() in {"1", "true", "yes", "on"}
DESKTOP_STREAM_PREFERRED_TRANSPORT = "webrtc" if (AIORTC_AVAILABLE and DESKTOP_WEBRTC_ENABLED) else "fallback"
DESKTOP_STREAM_FALLBACK_TRANSPORT = "multipart_png"
DESKTOP_WEBRTC_SESSION_LOCK = threading.Lock()
DESKTOP_WEBRTC_SESSIONS: Dict[str, Dict[str, Any]] = {}
DESKTOP_CAPTURE_TLS = threading.local()
DESKTOP_TARGET_LOCK = threading.Lock()
DESKTOP_DXCAM_LOCK = threading.RLock()
DESKTOP_CAPTURE_GENERATION = 0
DESKTOP_DXCAM_CAMERA = None
DESKTOP_DXCAM_OUTPUT_IDX = None
DESKTOP_DXCAM_GENERATION = -1
DESKTOP_TARGET_VIRTUAL_HINT = str(os.environ.get("CODEX_DESKTOP_VIRTUAL_TARGET_ID", "") or "").strip().lower()
DESKTOP_TARGET_SELECTED_ID = ""
WINDOWS_DPI_AWARE = False
WINDOWS_DPI_AWARE_LOCK = threading.Lock()
DESKTOP_WEBRTC_MAX_SESSIONS = int(os.environ.get("CODEX_DESKTOP_WEBRTC_MAX_SESSIONS", "2") or "2")
DESKTOP_CAPTURE_BACKEND_DEFAULT = str(os.environ.get("CODEX_DESKTOP_CAPTURE_BACKEND", "auto") or "auto").strip().lower()
DESKTOP_MODE_LOCK = threading.Lock()
DESKTOP_MODE_ENABLED = str(os.environ.get("CODEX_DESKTOP_MODE_DEFAULT", "1") or "1").strip().lower() not in {"0", "false", "no", "off"}
DESKTOP_ALT_LOCK = threading.Lock()
DESKTOP_ALT_HELD = False
DESKTOP_PERF_LOCK = threading.Lock()
DESKTOP_PERF_ENABLED = str(os.environ.get("CODEX_DESKTOP_PERF_DEFAULT", "1") or "1").strip().lower() not in {"0", "false", "no", "off"}
DESKTOP_PERF_ACTIVE = False
DESKTOP_PERF_SNAPSHOT: Optional[Dict[str, Any]] = None
_cookie_secure_raw = str(os.environ.get("CODEX_COOKIE_SECURE", "auto") or "auto").strip().lower()
if _cookie_secure_raw in {"auto", "always", "never", "on", "off", "true", "false", "1", "0", "yes", "no"}:
    CODEX_COOKIE_SECURE_MODE = _cookie_secure_raw
else:
    CODEX_COOKIE_SECURE_MODE = "auto"
CODEX_WAKE_RELAY_URL = str(os.environ.get("CODEX_WAKE_RELAY_URL", "") or "").strip().rstrip("/")
CODEX_WAKE_RELAY_TOKEN = str(os.environ.get("CODEX_WAKE_RELAY_TOKEN", "") or "").strip()
CODEX_WAKE_TELEGRAM_COMMAND = str(os.environ.get("CODEX_WAKE_TELEGRAM_COMMAND", "/wake") or "/wake").strip() or "/wake"
CODEX_WAKE_RELAY_TIMEOUT_SECONDS = float(os.environ.get("CODEX_WAKE_RELAY_TIMEOUT_SECONDS", "3.5") or "3.5")
CODEX_POWER_CONFIRM_TTL_SECONDS = int(os.environ.get("CODEX_POWER_CONFIRM_TTL_SECONDS", "60") or "60")
CODEX_POWER_ACTION_DELAY_SECONDS = max(0.5, float(os.environ.get("CODEX_POWER_ACTION_DELAY_SECONDS", "2.0") or "2.0"))
POWER_CONFIRM_LOCK = threading.Lock()
POWER_CONFIRMATIONS: Dict[str, Dict[str, Any]] = {}

DISPLAY_DEVICE_ATTACHED_TO_DESKTOP = 0x00000001
DISPLAY_DEVICE_PRIMARY_DEVICE = 0x00000004
DISPLAY_DEVICE_MIRRORING_DRIVER = 0x00000008
ENUM_CURRENT_SETTINGS = -1
CDS_UPDATEREGISTRY = 0x00000001
CDS_TEST = 0x00000002
CDS_SET_PRIMARY = 0x00000010
CDS_NORESET = 0x10000000
DISP_CHANGE_SUCCESSFUL = 0
DM_BITSPERPEL = 0x00040000
DM_POSITION = 0x00000020
DM_PELSWIDTH = 0x00080000
DM_PELSHEIGHT = 0x00100000
DM_DISPLAYFREQUENCY = 0x00400000


class RECT(ctypes.Structure):
    _fields_ = [
        ("left", wintypes.LONG),
        ("top", wintypes.LONG),
        ("right", wintypes.LONG),
        ("bottom", wintypes.LONG),
    ]


class WINDOWPLACEMENT(ctypes.Structure):
    _fields_ = [
        ("length", wintypes.UINT),
        ("flags", wintypes.UINT),
        ("showCmd", wintypes.UINT),
        ("ptMinPosition", wintypes.POINT),
        ("ptMaxPosition", wintypes.POINT),
        ("rcNormalPosition", RECT),
    ]


class DEVMODEW(ctypes.Structure):
    _fields_ = [
        ("dmDeviceName", wintypes.WCHAR * 32),
        ("dmSpecVersion", wintypes.WORD),
        ("dmDriverVersion", wintypes.WORD),
        ("dmSize", wintypes.WORD),
        ("dmDriverExtra", wintypes.WORD),
        ("dmFields", wintypes.DWORD),
        ("dmPositionX", ctypes.c_long),
        ("dmPositionY", ctypes.c_long),
        ("dmDisplayOrientation", wintypes.DWORD),
        ("dmDisplayFixedOutput", wintypes.DWORD),
        ("dmColor", wintypes.WORD),
        ("dmDuplex", wintypes.WORD),
        ("dmYResolution", wintypes.WORD),
        ("dmTTOption", wintypes.WORD),
        ("dmCollate", wintypes.WORD),
        ("dmFormName", wintypes.WCHAR * 32),
        ("dmLogPixels", wintypes.WORD),
        ("dmBitsPerPel", wintypes.DWORD),
        ("dmPelsWidth", wintypes.DWORD),
        ("dmPelsHeight", wintypes.DWORD),
        ("dmDisplayFlags", wintypes.DWORD),
        ("dmDisplayFrequency", wintypes.DWORD),
        ("dmICMMethod", wintypes.DWORD),
        ("dmICMIntent", wintypes.DWORD),
        ("dmMediaType", wintypes.DWORD),
        ("dmDitherType", wintypes.DWORD),
        ("dmReserved1", wintypes.DWORD),
        ("dmReserved2", wintypes.DWORD),
        ("dmPanningWidth", wintypes.DWORD),
        ("dmPanningHeight", wintypes.DWORD),
    ]


class MONITORINFOEXW(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("rcMonitor", RECT),
        ("rcWork", RECT),
        ("dwFlags", wintypes.DWORD),
        ("szDevice", wintypes.WCHAR * 32),
    ]


class DISPLAY_DEVICEW(ctypes.Structure):
    _fields_ = [
        ("cb", wintypes.DWORD),
        ("DeviceName", wintypes.WCHAR * 32),
        ("DeviceString", wintypes.WCHAR * 128),
        ("StateFlags", wintypes.DWORD),
        ("DeviceID", wintypes.WCHAR * 128),
        ("DeviceKey", wintypes.WCHAR * 128),
    ]

# -------------------------
# Thread transcript store
# -------------------------
LEGACY_THREADS_FILE = os.path.abspath(os.path.join(LEGACY_RUNTIME_DIR, "logs", "threads-store.json"))
DEFAULT_THREADS_FILE = os.path.abspath(
    os.environ.get(
        "CODEX_THREADS_FILE",
        os.path.join(CODEX_RUNTIME_STATE_DIR, "threads-store.json"),
    )
)
THREADS_FILE = DEFAULT_THREADS_FILE
THREADS_LOCK = threading.Lock()
THREADS_LOADED = False
THREADS_MAX_KEEP = int(os.environ.get("CODEX_THREADS_MAX_KEEP", "200") or "200")
THREAD_MESSAGES_MAX_PER_THREAD = int(os.environ.get("CODEX_THREAD_MESSAGES_MAX_PER_THREAD", "240") or "240")
THREAD_MESSAGE_TEXT_MAX = int(os.environ.get("CODEX_THREAD_MESSAGE_TEXT_MAX", "20000") or "20000")
THREADS_DATA: Dict[str, Any] = {
    "threads": [],
    "messages": {},
}

# -------------------------
# Shared file outbox store
# -------------------------
LEGACY_SHARED_OUTBOX_FILE = os.path.abspath(os.path.join(LEGACY_RUNTIME_DIR, "logs", "shared-outbox.json"))
DEFAULT_SHARED_OUTBOX_FILE = os.path.abspath(
    os.environ.get(
        "CODEX_SHARED_OUTBOX_FILE",
        os.path.join(CODEX_RUNTIME_STATE_DIR, "shared-outbox.json"),
    )
)
SHARED_OUTBOX_FILE = DEFAULT_SHARED_OUTBOX_FILE
SHARED_OUTBOX_LOCK = threading.Lock()
SHARED_OUTBOX_LOADED = False
SHARED_OUTBOX_MAX_KEEP = int(os.environ.get("CODEX_SHARED_OUTBOX_MAX_KEEP", "200") or "200")
SHARED_OUTBOX_DEFAULT_EXPIRES_HOURS = int(os.environ.get("CODEX_SHARED_OUTBOX_DEFAULT_EXPIRES_HOURS", "24") or "24")
SHARED_OUTBOX_MAX_EXPIRES_HOURS = int(os.environ.get("CODEX_SHARED_OUTBOX_MAX_EXPIRES_HOURS", "168") or "168")
SHARED_OUTBOX_MAX_FILE_MB = int(os.environ.get("CODEX_SHARED_OUTBOX_MAX_FILE_MB", "200") or "200")
SHARED_OUTBOX_DATA: Dict[str, Any] = {
    "items": [],
}

# -------------------------
# Session file store
# -------------------------
DEFAULT_SESSION_FILES_FILE = os.path.abspath(
    os.environ.get(
        "CODEX_SESSION_FILES_FILE",
        os.path.join(CODEX_RUNTIME_STATE_DIR, "session-files.json"),
    )
)
SESSION_FILES_FILE = DEFAULT_SESSION_FILES_FILE
SESSION_FILES_LOCK = threading.Lock()
SESSION_FILES_LOADED = False
SESSION_FILES_MAX_KEEP = int(os.environ.get("CODEX_SESSION_FILES_MAX_KEEP", "600") or "600")
SESSION_FILES_MAX_FILE_MB = int(os.environ.get("CODEX_SESSION_FILES_MAX_FILE_MB", "200") or "200")
SESSION_FILES_DATA: Dict[str, Any] = {
    "items": [],
}
DEFAULT_SESSION_NOTES_FILE = os.path.abspath(
    os.environ.get(
        "CODEX_SESSION_NOTES_FILE",
        os.path.join(CODEX_RUNTIME_STATE_DIR, "session-notes.json"),
    )
)
SESSION_NOTES_FILE = DEFAULT_SESSION_NOTES_FILE
SESSION_NOTES_LOCK = threading.Lock()
SESSION_NOTES_LOADED = False
SESSION_NOTES_MAX_CHARS = int(os.environ.get("CODEX_SESSION_NOTES_MAX_CHARS", "200000") or "200000")
SESSION_NOTES_MAX_SNAPSHOT_CHARS = int(os.environ.get("CODEX_SESSION_NOTES_MAX_SNAPSHOT_CHARS", "2000") or "2000")
SESSION_NOTES_DATA: Dict[str, Any] = {
    "notes": {},
}
DEFAULT_SESSION_HISTORY_FILE = os.path.abspath(
    os.environ.get(
        "CODEX_SESSION_HISTORY_FILE",
        os.path.join(CODEX_RUNTIME_STATE_DIR, "session-history.json"),
    )
)
SESSION_HISTORY_FILE = DEFAULT_SESSION_HISTORY_FILE
SESSION_HISTORY_LOCK = threading.Lock()
SESSION_HISTORY_LOADED = False
SESSION_HISTORY_MAX_KEEP = int(os.environ.get("CODEX_SESSION_HISTORY_MAX_KEEP", "240") or "240")
SESSION_HISTORY_DATA: Dict[str, Any] = {
    "items": [],
}
DEFAULT_LOOP_CONTROL_FILE = os.path.abspath(
    os.environ.get(
        "CODEX_LOOP_CONTROL_FILE",
        os.path.join(CODEX_RUNTIME_STATE_DIR, "loop-control.json"),
    )
)
LOOP_CONTROL_FILE = DEFAULT_LOOP_CONTROL_FILE
LOOP_CONTROL_LOCK = threading.Lock()
LOOP_CONTROL_LOADED = False
LOOP_CONTROL_POLL_INTERVAL_S = float(os.environ.get("CODEX_LOOP_CONTROL_POLL_INTERVAL_S", "3.0") or "3.0")
LOOP_CONTROL_TELEGRAM_POLL_INTERVAL_S = float(
    os.environ.get("CODEX_LOOP_CONTROL_TELEGRAM_POLL_INTERVAL_S", "5.0") or "5.0"
)
LOOP_CONTROL_CHECK_TIMEOUT_S = float(os.environ.get("CODEX_LOOP_CONTROL_CHECK_TIMEOUT_S", "900") or "900")
LOOP_PRESET_VALUES = (
    "infinite",
    "await-reply",
    "completion-checks",
    "max-turns-1",
    "max-turns-2",
    "max-turns-3",
)
LOOP_OVERRIDE_MODE_VALUES = ("inherit", "off") + LOOP_PRESET_VALUES
LOOP_TERMINAL_STATES = {"done", "error"}
LOOP_WAITING_STATES = {"waiting"}
LOOP_CONTROL_DEFAULT_PROMPT = str(
    os.environ.get(
        "CODEX_LOOP_DEFAULT_PROMPT",
        (
            "Continue working until the task is actually done. "
            "Run the relevant verification before stopping, and only stop when the work is complete "
            "or you need a concrete decision from me."
        ),
    )
    or ""
).strip()
if not LOOP_CONTROL_DEFAULT_PROMPT:
    LOOP_CONTROL_DEFAULT_PROMPT = (
        "Continue working until the task is actually done. "
        "Run the relevant verification before stopping."
    )
TELEGRAM_WINDOWS_MIRROR_ENABLED_DEFAULT = str(
    os.environ.get("CODEX_TELEGRAM_WINDOWS_MIRROR_ENABLED", "0") or "0"
).strip().lower() in {"1", "true", "yes", "on"}
TELEGRAM_WINDOWS_MIRROR_MAX_CHARS = max(
    800,
    int(os.environ.get("CODEX_TELEGRAM_WINDOWS_MIRROR_MAX_CHARS", "3200") or "3200"),
)
TELEGRAM_WINDOWS_MIRROR_SNAPSHOT_TAIL_CHARS = max(
    800,
    int(os.environ.get("CODEX_TELEGRAM_WINDOWS_MIRROR_SNAPSHOT_TAIL_CHARS", "3200") or "3200"),
)
TELEGRAM_WINDOWS_MIRROR_MAX_PARTS = max(
    1,
    int(os.environ.get("CODEX_TELEGRAM_WINDOWS_MIRROR_MAX_PARTS", "4") or "4"),
)
ANSI_ESCAPE_RE = re.compile(
    r"(?:\x1B[@-Z\\-_]|\x1B\[[0-?]*[ -/]*[@-~]|\x1B\][^\x07]*(?:\x07|\x1B\\))"
)
CONTROL_CHAR_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
LOOP_CONTROL_DATA: Dict[str, Any] = {
    "settings": {
        "default_prompt": LOOP_CONTROL_DEFAULT_PROMPT,
        "global_preset": "",
        "completion_checks": [],
        "telegram_update_offset": 0,
        "telegram_windows_mirror_enabled": TELEGRAM_WINDOWS_MIRROR_ENABLED_DEFAULT,
        "updated_at": 0,
    },
    "sessions": {},
    "worker": {
        "alive": False,
        "last_cycle_at": 0,
        "last_telegram_poll_at": 0,
        "last_error": "",
        "last_error_at": 0,
    },
}
LOOP_CONTROL_WORKER_THREAD: Optional[threading.Thread] = None
APP_RUNTIME_SESSION_FILE = os.path.abspath(
    os.environ.get(
        "CODEX_APP_RUNTIME_SESSION_FILE",
        os.path.join(CODEX_RUNTIME_STATE_DIR, "mobile.session.json"),
    )
)
LEGACY_APP_RUNTIME_SESSION_FILE = os.path.abspath(os.path.join(LEGACY_RUNTIME_DIR, "logs", "mobile.session.json"))
TRUSTED_DEVICES_FILE = os.path.abspath(
    os.environ.get(
        "CODEX_TRUSTED_DEVICES_FILE",
        os.path.join(CODEX_RUNTIME_STATE_DIR, "trusted-devices.json"),
    )
)
TRUSTED_DEVICES_LOCK = threading.Lock()
TRUSTED_DEVICES_MAX_KEEP = int(os.environ.get("CODEX_TRUSTED_DEVICES_MAX_KEEP", "20") or "20")
TRUSTED_DEVICES_DATA: Dict[str, Any] = {
    "devices": [],
}
TRUSTED_DEVICES_LOADED = False
LEGACY_PRIVACY_LOCK_CONFIG_FILE = os.path.abspath(
    os.environ.get(
        "CODEX_PRIVACY_LOCK_CONFIG_FILE",
        os.path.join(CODEX_RUNTIME_STATE_DIR, "privacy-lock.config.json"),
    )
)
LEGACY_PRIVACY_LOCK_STATE_FILE = os.path.abspath(
    os.environ.get(
        "CODEX_PRIVACY_LOCK_STATE_FILE",
        os.path.join(CODEX_RUNTIME_STATE_DIR, "privacy-lock.state.json"),
    )
)
_cleanup_legacy_privacy_lock_state()
# -------------------------
# Session output stream state
# -------------------------
SESSION_STREAM_LOCK = threading.Lock()
SESSION_STREAM_REPLAY_MAX = int(os.environ.get("CODEX_SESSION_STREAM_REPLAY_MAX", "240") or "240")
SESSION_STREAM_STATES: Dict[str, Dict[str, Any]] = {}
SESSION_RECOVERING_AFTER_S = float(os.environ.get("CODEX_SESSION_RECOVERING_AFTER_S", "20") or "20")
SESSION_STALE_TTL_S = float(os.environ.get("CODEX_SESSION_STALE_TTL_S", "180") or "180")
SESSION_BACKGROUND_MODE = "selected_only"
CODEX_HISTORY_CACHE_LOCK = threading.Lock()
CODEX_HISTORY_CACHE: Dict[str, Any] = {
    "loaded_at": 0.0,
    "entries": [],
}
NET_INFO_CACHE_LOCK = threading.Lock()
NET_INFO_CACHE_TTL_S = float(os.environ.get("CODEX_NET_INFO_CACHE_TTL_S", "30") or "30")
NET_INFO_CACHE: Dict[str, Any] = {
    "loaded_at": 0.0,
    "payload": None,
}

# -------------------------
# Telegram delivery (optional)
# -------------------------
LEGACY_TELEGRAM_SECRETS_DIR = os.path.abspath(os.path.join(LEGACY_RUNTIME_DIR, "Telegram bot"))
DEFAULT_TELEGRAM_SECRETS_DIR = os.path.abspath(
    os.environ.get(
        "CODEX_TELEGRAM_SECRETS_DIR",
        CODEX_RUNTIME_TELEGRAM_DIR,
    )
)
DEFAULT_TELEGRAM_SECRET_FILE = os.path.join(DEFAULT_TELEGRAM_SECRETS_DIR, "key.txt")
DEFAULT_TELEGRAM_CHAT_FILE = os.path.join(DEFAULT_TELEGRAM_SECRETS_DIR, "chat_id.txt")
TELEGRAM_SECRET_FILE = os.path.abspath(os.environ.get("CODEX_TELEGRAM_SECRET_FILE", DEFAULT_TELEGRAM_SECRET_FILE))
TELEGRAM_CHAT_FILE = os.path.abspath(os.environ.get("CODEX_TELEGRAM_CHAT_FILE", DEFAULT_TELEGRAM_CHAT_FILE))
TELEGRAM_API_BASE = os.environ.get("CODEX_TELEGRAM_API_BASE", "https://api.telegram.org").strip() or "https://api.telegram.org"
TELEGRAM_TIMEOUT_SECONDS = float(os.environ.get("CODEX_TELEGRAM_TIMEOUT_SECONDS", "30") or "30")
TELEGRAM_MAX_FILE_MB = int(os.environ.get("CODEX_TELEGRAM_MAX_FILE_MB", "45") or "45")
CODEX_TELEGRAM_DEFAULT_SEND = str(os.environ.get("CODEX_TELEGRAM_DEFAULT_SEND", "0") or "0").strip().lower() in {"1", "true", "yes", "on"}

for _runtime_dir in (
    CODEX_RUNTIME_DIR,
    CODEX_RUNTIME_STATE_DIR,
    CODEX_RUNTIME_LOGS_DIR,
    CODEX_RUNTIME_SECRETS_DIR,
    CODEX_RUNTIME_TELEGRAM_DIR,
    CODEX_HOST_TRANSFER_ROOT,
):
    try:
        os.makedirs(_runtime_dir, exist_ok=True)
    except Exception:
        pass


def _read_text_file(path: str) -> str:
    p = str(path or "").strip()
    if not p:
        return ""
    try:
        with open(p, "r", encoding="utf-8-sig") as f:
            return f.read()
    except Exception:
        return ""


def _read_text_with_fallback(*paths: str) -> str:
    for candidate in paths:
        text = _read_text_file(candidate)
        if text:
            return text
    return ""


def _read_json_file(path: str) -> Dict[str, Any]:
    p = str(path or "").strip()
    if not p:
        return {}
    last_error: Optional[Exception] = None
    for attempt in range(12):
        try:
            with open(p, "r", encoding="utf-8-sig") as f:
                parsed = json.load(f)
            return parsed if isinstance(parsed, dict) else {}
        except FileNotFoundError:
            return {}
        except json.JSONDecodeError as exc:
            last_error = exc
        except PermissionError as exc:
            last_error = exc
        except OSError as exc:
            last_error = exc
        time.sleep(0.05 * (attempt + 1))
    if last_error is not None:
        print(f"JSON read retry exhausted path={p} error={type(last_error).__name__}: {last_error}", flush=True)
    return {}


def _write_json_file(path: str, payload: Dict[str, Any]) -> None:
    p = str(path or "").strip()
    if not p:
        return
    parent = os.path.dirname(p)
    if parent:
        os.makedirs(parent, exist_ok=True)
    last_error: Optional[Exception] = None
    for attempt in range(12):
        tmp_path = f"{p}.{os.getpid()}.{uuid.uuid4().hex}.tmp"
        try:
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(payload or {}, f, indent=2, ensure_ascii=True)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp_path, p)
            return
        except PermissionError as exc:
            last_error = exc
        except OSError as exc:
            last_error = exc
        finally:
            try:
                if os.path.exists(tmp_path):
                    os.remove(tmp_path)
            except OSError:
                pass
        time.sleep(0.05 * (attempt + 1))
    if last_error is not None:
        raise last_error


def _parse_telegram_secret_text(raw: str) -> Dict[str, str]:
    out: Dict[str, str] = {}
    for raw_line in (raw or "").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if line.startswith("#") or line.startswith(";"):
            continue
        if "=" in line:
            key, value = line.split("=", 1)
            norm_key = key.strip().lower().replace("-", "_")
            norm_value = value.strip().strip('"').strip("'")
            if not norm_value:
                continue
            if norm_key in {"token", "bot_token", "telegram_bot_token", "codex_telegram_bot_token"}:
                out["token"] = norm_value
                continue
            if norm_key in {"chat", "chat_id", "telegram_chat_id", "codex_telegram_chat_id"}:
                out["chat_id"] = norm_value
                continue
            continue
        # Common direct-value forms:
        # - bot token: 123456:AbC...
        # - chat id: 123456789 or -1001234567890
        if "token" not in out and re.fullmatch(r"\d{5,}:[A-Za-z0-9_-]{10,}", line):
            out["token"] = line
            continue
        if "chat_id" not in out and re.fullmatch(r"-?\d{5,20}", line):
            out["chat_id"] = line
            continue
    return out


def _load_telegram_file_values(secret_file: str, chat_file: str) -> Dict[str, str]:
    out: Dict[str, str] = {}
    runtime_secret = _parse_telegram_secret_text(
        _read_text_with_fallback(secret_file, os.path.join(LEGACY_TELEGRAM_SECRETS_DIR, "key.txt"))
    )
    out.update(runtime_secret)
    secret_abs = os.path.abspath(secret_file or "")
    chat_abs = os.path.abspath(chat_file or "")
    if chat_abs and chat_abs != secret_abs:
        chat_values = _parse_telegram_secret_text(
            _read_text_with_fallback(chat_file, os.path.join(LEGACY_TELEGRAM_SECRETS_DIR, "chat_id.txt"))
        )
        if chat_values.get("chat_id"):
            out["chat_id"] = chat_values["chat_id"]
    return out


_TELEGRAM_FILE_VALUES = _load_telegram_file_values(TELEGRAM_SECRET_FILE, TELEGRAM_CHAT_FILE)
TELEGRAM_BOT_TOKEN = os.environ.get("CODEX_TELEGRAM_BOT_TOKEN", "").strip() or _TELEGRAM_FILE_VALUES.get("token", "")
TELEGRAM_CHAT_ID = os.environ.get("CODEX_TELEGRAM_CHAT_ID", "").strip() or _TELEGRAM_FILE_VALUES.get("chat_id", "")


def _now_ms() -> int:
    return int(time.time() * 1000)


def _clean_entity_id(raw: Any) -> str:
    value = str(raw or "").strip()
    if not VALID_ENTITY_ID_RE.fullmatch(value):
        return ""
    return value


def _normalize_thread_title(raw: Any, session: str) -> str:
    text = str(raw or "").strip()
    text = re.sub(r"\s+", " ", text)
    if text:
        return text[:80]
    return f"{session} thread" if session else "Untitled thread"


def _coerce_ms(raw: Any, fallback: int) -> int:
    try:
        value = int(raw)
    except Exception:
        return fallback
    if value <= 0:
        return fallback
    return value


def _normalize_loop_preset(raw: Any) -> str:
    value = str(raw or "").strip().lower()
    return value if value in LOOP_PRESET_VALUES else ""


def _normalize_loop_override_mode(raw: Any) -> str:
    value = str(raw or "").strip().lower()
    return value if value in LOOP_OVERRIDE_MODE_VALUES else "inherit"


def _loop_budget_for_preset(preset: str) -> Optional[int]:
    if preset == "max-turns-1":
        return 1
    if preset == "max-turns-2":
        return 2
    if preset == "max-turns-3":
        return 3
    return None


def _loop_limit_text(text: str, max_chars: int = 1400) -> str:
    value = str(text or "").strip()
    if len(value) <= max_chars:
        return value
    return value[: max(0, max_chars - 1)].rstrip() + "…"


def _default_loop_settings() -> Dict[str, Any]:
    return {
        "default_prompt": LOOP_CONTROL_DEFAULT_PROMPT,
        "global_preset": "",
        "completion_checks": [],
        "telegram_update_offset": 0,
        "telegram_windows_mirror_enabled": TELEGRAM_WINDOWS_MIRROR_ENABLED_DEFAULT,
        "updated_at": 0,
    }


def _default_loop_session_state(session: str) -> Dict[str, Any]:
    session_id = _validate_session_name(session)
    return {
        "session": session_id,
        "override_mode": "inherit",
        "remaining_turns": None,
        "awaiting_reply": False,
        "last_terminal_state": "",
        "last_terminal_at": 0,
        "last_action": "",
        "last_action_detail": "",
        "last_action_at": 0,
        "last_notification_at": 0,
        "last_continue_at": 0,
        "last_reply_at": 0,
        "last_telegram_message_id": 0,
        "last_prompt_at": 0,
        "last_auto_prompt_at": 0,
        "last_handled_fingerprint": "",
        "last_snapshot": "",
        "windows_mirror_last_seq": 0,
        "windows_mirror_last_sent_at": 0,
        "windows_mirror_last_status": "",
    }


def _normalize_loop_commands(raw: Any) -> List[str]:
    values = raw if isinstance(raw, list) else []
    commands: List[str] = []
    for item in values:
        text = str(item or "").strip()
        if text:
            commands.append(text)
    return commands[:12]


def _normalize_loop_settings(raw: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    data = raw or {}
    default_prompt = str(data.get("default_prompt") or LOOP_CONTROL_DEFAULT_PROMPT).strip()
    if not default_prompt:
        default_prompt = LOOP_CONTROL_DEFAULT_PROMPT
    updated_at = _coerce_ms(data.get("updated_at"), _now_ms())
    return {
        "default_prompt": default_prompt,
        "global_preset": _normalize_loop_preset(data.get("global_preset")),
        "completion_checks": _normalize_loop_commands(data.get("completion_checks")),
        "telegram_update_offset": max(0, int(data.get("telegram_update_offset") or 0)),
        "telegram_windows_mirror_enabled": bool(
            data.get("telegram_windows_mirror_enabled", TELEGRAM_WINDOWS_MIRROR_ENABLED_DEFAULT)
        ),
        "updated_at": updated_at,
    }


def _normalize_loop_session_state(raw: Optional[Dict[str, Any]], session: str) -> Dict[str, Any]:
    base = _default_loop_session_state(session)
    data = raw or {}
    base["override_mode"] = _normalize_loop_override_mode(data.get("override_mode"))
    remaining_turns = data.get("remaining_turns")
    if remaining_turns is None or str(remaining_turns).strip() == "":
        base["remaining_turns"] = None
    else:
        try:
            base["remaining_turns"] = max(0, int(remaining_turns))
        except Exception:
            base["remaining_turns"] = None
    base["awaiting_reply"] = bool(data.get("awaiting_reply"))
    base["last_terminal_state"] = str(data.get("last_terminal_state") or "").strip().lower()
    base["last_terminal_at"] = _coerce_ms(data.get("last_terminal_at"), 0)
    base["last_action"] = str(data.get("last_action") or "").strip()[:64]
    base["last_action_detail"] = str(data.get("last_action_detail") or "").strip()[:4000]
    base["last_action_at"] = _coerce_ms(data.get("last_action_at"), 0)
    base["last_notification_at"] = _coerce_ms(data.get("last_notification_at"), 0)
    base["last_continue_at"] = _coerce_ms(data.get("last_continue_at"), 0)
    base["last_reply_at"] = _coerce_ms(data.get("last_reply_at"), 0)
    base["last_telegram_message_id"] = max(0, int(data.get("last_telegram_message_id") or 0))
    base["last_prompt_at"] = _coerce_ms(data.get("last_prompt_at"), 0)
    base["last_auto_prompt_at"] = _coerce_ms(data.get("last_auto_prompt_at"), 0)
    base["last_handled_fingerprint"] = str(data.get("last_handled_fingerprint") or "").strip()[:128]
    base["last_snapshot"] = _loop_limit_text(str(data.get("last_snapshot") or ""), 2000)
    try:
        base["windows_mirror_last_seq"] = max(0, int(data.get("windows_mirror_last_seq") or 0))
    except Exception:
        base["windows_mirror_last_seq"] = 0
    base["windows_mirror_last_sent_at"] = _coerce_ms(data.get("windows_mirror_last_sent_at"), 0)
    base["windows_mirror_last_status"] = str(data.get("windows_mirror_last_status") or "").strip()[:64]
    return base


def _sort_and_trim_loop_control_unlocked() -> None:
    LOOP_CONTROL_DATA["settings"] = _normalize_loop_settings(
        LOOP_CONTROL_DATA.get("settings") if isinstance(LOOP_CONTROL_DATA.get("settings"), dict) else {},
    )
    sessions_raw = LOOP_CONTROL_DATA.get("sessions")
    normalized_sessions: Dict[str, Dict[str, Any]] = {}
    if isinstance(sessions_raw, dict):
        for key, value in sessions_raw.items():
            try:
                session_id = _validate_session_name(key)
            except Exception:
                continue
            normalized_sessions[session_id] = _normalize_loop_session_state(
                value if isinstance(value, dict) else {},
                session_id,
            )
    LOOP_CONTROL_DATA["sessions"] = normalized_sessions
    worker_raw = LOOP_CONTROL_DATA.get("worker")
    worker_data = worker_raw if isinstance(worker_raw, dict) else {}
    LOOP_CONTROL_DATA["worker"] = {
        "alive": bool(worker_data.get("alive")),
        "last_cycle_at": _coerce_ms(worker_data.get("last_cycle_at"), 0),
        "last_telegram_poll_at": _coerce_ms(worker_data.get("last_telegram_poll_at"), 0),
        "last_error": str(worker_data.get("last_error") or "").strip()[:4000],
        "last_error_at": _coerce_ms(worker_data.get("last_error_at"), 0),
    }


def _persist_loop_control_unlocked() -> None:
    _sort_and_trim_loop_control_unlocked()
    payload = {
        "settings": LOOP_CONTROL_DATA.get("settings") or _default_loop_settings(),
        "sessions": LOOP_CONTROL_DATA.get("sessions") or {},
    }
    _write_json_file(LOOP_CONTROL_FILE, payload)


def _load_loop_control_unlocked() -> None:
    global LOOP_CONTROL_LOADED
    if LOOP_CONTROL_LOADED:
        return
    LOOP_CONTROL_LOADED = True
    LOOP_CONTROL_DATA["settings"] = _default_loop_settings()
    LOOP_CONTROL_DATA["sessions"] = {}
    raw = _read_json_file(LOOP_CONTROL_FILE)
    if isinstance(raw, dict):
        if isinstance(raw.get("settings"), dict):
            LOOP_CONTROL_DATA["settings"] = raw.get("settings") or {}
        if isinstance(raw.get("sessions"), dict):
            LOOP_CONTROL_DATA["sessions"] = raw.get("sessions") or {}
    _sort_and_trim_loop_control_unlocked()


def _get_loop_settings_unlocked() -> Dict[str, Any]:
    _load_loop_control_unlocked()
    return LOOP_CONTROL_DATA.get("settings") or _default_loop_settings()


def _get_loop_session_unlocked(session: str) -> Dict[str, Any]:
    _load_loop_control_unlocked()
    session_id = _validate_session_name(session)
    sessions = LOOP_CONTROL_DATA.setdefault("sessions", {})
    if not isinstance(sessions, dict):
        sessions = {}
        LOOP_CONTROL_DATA["sessions"] = sessions
    existing = sessions.get(session_id)
    normalized = _normalize_loop_session_state(existing if isinstance(existing, dict) else {}, session_id)
    sessions[session_id] = normalized
    return normalized


def _effective_loop_preset_unlocked(session: str) -> str:
    settings = _get_loop_settings_unlocked()
    session_state = _get_loop_session_unlocked(session)
    override_mode = str(session_state.get("override_mode") or "inherit")
    if override_mode == "off":
        return ""
    if override_mode in LOOP_PRESET_VALUES:
        return override_mode
    return _normalize_loop_preset(settings.get("global_preset"))


def _public_loop_settings_unlocked() -> Dict[str, Any]:
    settings = _get_loop_settings_unlocked()
    return {
        "default_prompt": str(settings.get("default_prompt") or LOOP_CONTROL_DEFAULT_PROMPT),
        "global_preset": _normalize_loop_preset(settings.get("global_preset")) or None,
        "completion_checks": list(settings.get("completion_checks") or []),
        "telegram_configured": bool(_telegram_enabled()),
        "telegram_windows_mirror_enabled": bool(settings.get("telegram_windows_mirror_enabled")),
    }


def _public_loop_session_state_unlocked(session: str) -> Dict[str, Any]:
    state = _get_loop_session_unlocked(session)
    effective_preset = _effective_loop_preset_unlocked(session)
    return {
        "override_mode": str(state.get("override_mode") or "inherit"),
        "effective_preset": effective_preset or None,
        "remaining_turns": state.get("remaining_turns"),
        "awaiting_reply": bool(state.get("awaiting_reply")),
        "last_terminal_state": str(state.get("last_terminal_state") or ""),
        "last_terminal_at": int(state.get("last_terminal_at") or 0),
        "last_action": str(state.get("last_action") or ""),
        "last_action_detail": str(state.get("last_action_detail") or ""),
        "last_action_at": int(state.get("last_action_at") or 0),
        "last_notification_at": int(state.get("last_notification_at") or 0),
        "last_continue_at": int(state.get("last_continue_at") or 0),
        "last_reply_at": int(state.get("last_reply_at") or 0),
        "last_prompt_at": int(state.get("last_prompt_at") or 0),
        "last_snapshot": str(state.get("last_snapshot") or ""),
    }


def _loop_snapshot_text_from_session_record(session_record: Optional[Dict[str, Any]]) -> str:
    record = session_record or {}
    snapshot = _compact_assistant_snapshot_text(str(record.get("last_text") or ""))
    if snapshot:
        return snapshot
    return _compact_assistant_snapshot_text(str(record.get("snippet") or ""))


def _build_thread_record(raw: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    thread_id = _clean_entity_id(raw.get("id"))
    session = str(raw.get("session") or "").strip()
    if not thread_id or not VALID_NAME_RE.fullmatch(session):
        return None
    now_ms = _now_ms()
    created_at = _coerce_ms(raw.get("created_at"), now_ms)
    updated_at = _coerce_ms(raw.get("updated_at"), created_at)
    if updated_at < created_at:
        updated_at = created_at
    return {
        "id": thread_id,
        "title": _normalize_thread_title(raw.get("title"), session),
        "session": session,
        "created_at": created_at,
        "updated_at": updated_at,
    }


def _build_thread_message(raw: Dict[str, Any], thread_id: str) -> Optional[Dict[str, Any]]:
    msg_id = _clean_entity_id(raw.get("id"))
    role = str(raw.get("role") or "").strip().lower()
    text = str(raw.get("text") or "").strip()
    if not msg_id:
        msg_id = f"msg_{uuid.uuid4().hex[:12]}"
    if role not in {"user", "assistant", "system"}:
        return None
    if not text:
        return None
    if len(text) > THREAD_MESSAGE_TEXT_MAX:
        text = text[:THREAD_MESSAGE_TEXT_MAX]
    now_ms = _now_ms()
    at = _coerce_ms(raw.get("at"), now_ms)
    return {
        "id": msg_id,
        "thread_id": thread_id,
        "role": role,
        "text": text,
        "at": at,
    }


def _sort_and_trim_threads_unlocked() -> None:
    threads = THREADS_DATA.get("threads") or []
    messages = THREADS_DATA.get("messages") or {}

    by_id: Dict[str, Dict[str, Any]] = {}
    for thread in threads:
        thread_id = _clean_entity_id((thread or {}).get("id"))
        if not thread_id:
            continue
        by_id[thread_id] = thread

    normalized_threads = list(by_id.values())
    normalized_threads.sort(key=lambda item: int(item.get("updated_at") or 0), reverse=True)
    normalized_threads = normalized_threads[: max(1, THREADS_MAX_KEEP)]
    keep_ids = {item["id"] for item in normalized_threads}

    normalized_messages: Dict[str, List[Dict[str, Any]]] = {}
    for thread_id, items in (messages or {}).items():
        if thread_id not in keep_ids:
            continue
        arr = []
        if isinstance(items, list):
            for msg in items:
                if not isinstance(msg, dict):
                    continue
                built = _build_thread_message(msg, thread_id)
                if built:
                    arr.append(built)
        arr.sort(key=lambda item: int(item.get("at") or 0))
        if len(arr) > THREAD_MESSAGES_MAX_PER_THREAD:
            arr = arr[-THREAD_MESSAGES_MAX_PER_THREAD:]
        normalized_messages[thread_id] = arr
        if arr:
            latest = arr[-1]["at"]
            for t in normalized_threads:
                if t["id"] == thread_id:
                    t["updated_at"] = max(int(t.get("updated_at") or 0), int(latest))
                    break

    normalized_threads.sort(key=lambda item: int(item.get("updated_at") or 0), reverse=True)
    THREADS_DATA["threads"] = normalized_threads
    THREADS_DATA["messages"] = normalized_messages


def _persist_threads_store_unlocked() -> None:
    _sort_and_trim_threads_unlocked()
    parent = os.path.dirname(THREADS_FILE)
    if parent:
        os.makedirs(parent, exist_ok=True)
    temp_path = THREADS_FILE + ".tmp"
    payload = {
        "threads": THREADS_DATA.get("threads") or [],
        "messages": THREADS_DATA.get("messages") or {},
    }
    with open(temp_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    os.replace(temp_path, THREADS_FILE)


def _load_threads_store_unlocked() -> None:
    global THREADS_LOADED
    if THREADS_LOADED:
        return
    THREADS_LOADED = True
    THREADS_DATA["threads"] = []
    THREADS_DATA["messages"] = {}

    source_path = THREADS_FILE if os.path.exists(THREADS_FILE) else LEGACY_THREADS_FILE
    if not os.path.exists(source_path):
        return
    raw = _read_json_file(source_path)
    if not isinstance(raw, dict):
        return

    threads_raw = raw.get("threads")
    messages_raw = raw.get("messages")
    thread_items: List[Dict[str, Any]] = []
    message_items: Dict[str, List[Dict[str, Any]]] = {}
    valid_ids = set()

    if isinstance(threads_raw, list):
        for item in threads_raw:
            if not isinstance(item, dict):
                continue
            built = _build_thread_record(item)
            if not built:
                continue
            thread_items.append(built)
            valid_ids.add(built["id"])

    if isinstance(messages_raw, dict):
        for thread_id, items in messages_raw.items():
            tid = _clean_entity_id(thread_id)
            if not tid or tid not in valid_ids:
                continue
            if not isinstance(items, list):
                continue
            arr: List[Dict[str, Any]] = []
            for msg in items:
                if not isinstance(msg, dict):
                    continue
                built_msg = _build_thread_message(msg, tid)
                if built_msg:
                    arr.append(built_msg)
            if arr:
                message_items[tid] = arr

    THREADS_DATA["threads"] = thread_items
    THREADS_DATA["messages"] = message_items
    _sort_and_trim_threads_unlocked()


def _threads_snapshot_unlocked() -> Dict[str, Any]:
    return {
        "threads": json.loads(json.dumps(THREADS_DATA.get("threads") or [])),
        "messages": json.loads(json.dumps(THREADS_DATA.get("messages") or {})),
    }


def _find_thread_unlocked(thread_id: str) -> Optional[Dict[str, Any]]:
    for thread in THREADS_DATA.get("threads") or []:
        if thread.get("id") == thread_id:
            return thread
    return None


def _normalize_codex_resume_id(raw: Any) -> str:
    candidate = str(raw or "").strip()
    if not candidate:
        return ""
    if not VALID_RESUME_ID_RE.fullmatch(candidate):
        raise HTTPException(status_code=400, detail="Invalid resume id format.")
    return candidate


def _build_session_history_record(raw: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    data = raw if isinstance(raw, dict) else {}
    session = str(data.get("session") or "").strip()
    if not session:
        return None
    session = _validate_session_name(session)
    now = time.time()
    state = str(data.get("state") or "starting").strip().lower() or "starting"
    if state not in {"starting", "idle", "busy", "running", "waiting", "done", "error", "recovering"}:
        state = "starting"
    created_at = float(data.get("created_at") or now)
    updated_at = float(data.get("updated_at") or created_at or now)
    last_seen_at = float(data.get("last_seen_at") or updated_at or created_at or now)
    closed_at_raw = data.get("closed_at")
    closed_at = float(closed_at_raw) if closed_at_raw not in {None, ""} else None
    resume_id = str(data.get("resume_id") or "").strip()
    if resume_id and not VALID_RESUME_ID_RE.fullmatch(resume_id):
        resume_id = ""
    return {
        "session": session,
        "pane_id": str(data.get("pane_id") or ""),
        "current_command": str(data.get("current_command") or ""),
        "cwd": str(data.get("cwd") or ""),
        "state": state,
        "updated_at": updated_at,
        "last_seen_at": last_seen_at,
        "snippet": str(data.get("snippet") or ""),
        "model": str(data.get("model") or CODEX_DEFAULT_MODEL),
        "reasoning_effort": str(data.get("reasoning_effort") or CODEX_DEFAULT_REASONING_EFFORT),
        "created_at": created_at,
        "closed_at": closed_at,
        "active": bool(data.get("active", closed_at is None)),
        "resume_id": resume_id,
        "last_user_prompt": str(data.get("last_user_prompt") or ""),
        "last_prompt_at": float(data.get("last_prompt_at") or 0.0),
    }


def _sort_and_trim_session_history_unlocked() -> None:
    normalized: List[Dict[str, Any]] = []
    seen = set()
    for item in SESSION_HISTORY_DATA.get("items") or []:
        built = _build_session_history_record(item if isinstance(item, dict) else {})
        if not built:
            continue
        session = built["session"]
        if session in seen:
            continue
        seen.add(session)
        normalized.append(built)
    normalized.sort(
        key=lambda item: max(
            float(item.get("closed_at") or 0.0),
            float(item.get("updated_at") or 0.0),
            float(item.get("created_at") or 0.0),
        ),
        reverse=True,
    )
    if len(normalized) > SESSION_HISTORY_MAX_KEEP:
        normalized = normalized[:SESSION_HISTORY_MAX_KEEP]
    SESSION_HISTORY_DATA["items"] = normalized


def _persist_session_history_unlocked() -> None:
    _sort_and_trim_session_history_unlocked()
    parent = os.path.dirname(SESSION_HISTORY_FILE)
    if parent:
        os.makedirs(parent, exist_ok=True)
    temp_path = SESSION_HISTORY_FILE + ".tmp"
    payload = {"items": SESSION_HISTORY_DATA.get("items") or []}
    with open(temp_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    os.replace(temp_path, SESSION_HISTORY_FILE)


def _load_session_history_unlocked() -> None:
    global SESSION_HISTORY_LOADED
    if SESSION_HISTORY_LOADED:
        return
    SESSION_HISTORY_LOADED = True
    SESSION_HISTORY_DATA["items"] = []
    raw = _read_json_file(SESSION_HISTORY_FILE)
    items = raw.get("items")
    if isinstance(items, list):
        SESSION_HISTORY_DATA["items"] = [item for item in items if isinstance(item, dict)]
    _sort_and_trim_session_history_unlocked()


def _find_session_history_unlocked(session: str) -> Optional[Dict[str, Any]]:
    session_id = _validate_session_name(session)
    for item in SESSION_HISTORY_DATA.get("items") or []:
        if str(item.get("session") or "").strip() == session_id:
            return item
    return None


def _upsert_session_history_unlocked(session: str, patch: Dict[str, Any]) -> Dict[str, Any]:
    session_id = _validate_session_name(session)
    _load_session_history_unlocked()
    existing = _find_session_history_unlocked(session_id)
    base = dict(existing) if existing else {"session": session_id, "created_at": time.time()}
    next_record = dict(base)
    for key, value in (patch or {}).items():
        if key == "session":
            continue
        if value is None:
            if key in {"closed_at", "resume_id", "last_user_prompt", "last_prompt_at"}:
                next_record.pop(key, None)
            continue
        next_record[key] = value
    built = _build_session_history_record(next_record)
    if not built:
        raise HTTPException(status_code=500, detail="session_history_build_failed")
    items = [
        item
        for item in (SESSION_HISTORY_DATA.get("items") or [])
        if str(item.get("session") or "").strip() != session_id
    ]
    items.insert(0, built)
    SESSION_HISTORY_DATA["items"] = items
    _persist_session_history_unlocked()
    return built


def _latest_thread_user_message_for_session_unlocked(session: str) -> Optional[Dict[str, Any]]:
    session_id = _validate_session_name(session)
    _load_threads_store_unlocked()
    latest: Optional[Dict[str, Any]] = None
    for thread in THREADS_DATA.get("threads") or []:
        if str((thread or {}).get("session") or "").strip() != session_id:
            continue
        thread_id = str((thread or {}).get("id") or "").strip()
        if not thread_id:
            continue
        for message in THREADS_DATA.get("messages", {}).get(thread_id, []) or []:
            if str((message or {}).get("role") or "").strip().lower() != "user":
                continue
            text = str((message or {}).get("text") or "").strip()
            if not text:
                continue
            at = float(message.get("at") or 0.0)
            if not latest or at > float(latest.get("at") or 0.0):
                latest = {"text": text, "at": at}
    return latest


def _read_codex_history_entries(limit: int = 4000) -> List[Dict[str, Any]]:
    now = time.time()
    with CODEX_HISTORY_CACHE_LOCK:
        cached_at = float(CODEX_HISTORY_CACHE.get("loaded_at") or 0.0)
        if now - cached_at < 3.0:
            return list(CODEX_HISTORY_CACHE.get("entries") or [])
    command = f'if [ -f "$HOME/.codex/history.jsonl" ]; then tail -n {max(200, int(limit or 0))} "$HOME/.codex/history.jsonl"; fi'
    result = run_wsl_bash(command, timeout_s=20)
    entries: List[Dict[str, Any]] = []
    if result.get("exit_code") == 0:
        for raw_line in str(result.get("stdout") or "").splitlines():
            line = raw_line.strip()
            if not line:
                continue
            try:
                parsed = json.loads(line)
            except Exception:
                continue
            if not isinstance(parsed, dict):
                continue
            session_id = str(parsed.get("session_id") or "").strip()
            text = str(parsed.get("text") or "")
            try:
                ts = float(parsed.get("ts") or 0.0)
            except Exception:
                ts = 0.0
            if not session_id or not text:
                continue
            entries.append({"session_id": session_id, "text": text, "ts": ts})
    with CODEX_HISTORY_CACHE_LOCK:
        CODEX_HISTORY_CACHE["loaded_at"] = now
        CODEX_HISTORY_CACHE["entries"] = list(entries)
    return entries


def _match_codex_resume_id(prompt_text: str, prompt_at_s: float = 0.0) -> str:
    needle = str(prompt_text or "").strip()
    if not needle:
        return ""
    best_id = ""
    best_delta: Optional[float] = None
    for entry in reversed(_read_codex_history_entries()):
        if str(entry.get("text") or "").strip() != needle:
            continue
        session_id = str(entry.get("session_id") or "").strip()
        if not VALID_RESUME_ID_RE.fullmatch(session_id):
            continue
        if prompt_at_s > 0:
            delta = abs(float(entry.get("ts") or 0.0) - prompt_at_s)
            if delta > 21600:
                continue
            if best_delta is None or delta < best_delta:
                best_delta = delta
                best_id = session_id
                if delta <= 5:
                    break
            continue
        return session_id
    return best_id


def _resolve_session_resume_id(session: str, prev: Optional[Dict[str, Any]] = None) -> str:
    session_id = _validate_session_name(session)
    source = dict(prev or {})
    existing_resume_id = str(source.get("resume_id") or "").strip()
    if existing_resume_id:
        return existing_resume_id
    prompt_text = str(source.get("last_user_prompt") or "").strip()
    prompt_at_s = float(source.get("last_prompt_at") or 0.0)
    if not prompt_text:
        with THREADS_LOCK:
            candidate = _latest_thread_user_message_for_session_unlocked(session_id)
        if candidate:
            prompt_text = str(candidate.get("text") or "").strip()
            prompt_at_s = max(prompt_at_s, float(candidate.get("at") or 0.0) / 1000.0)
    return _match_codex_resume_id(prompt_text, prompt_at_s)


def _public_session_record(item: Dict[str, Any]) -> Dict[str, Any]:
    record = {
        "session": str(item.get("session") or ""),
        "pane_id": str(item.get("pane_id") or ""),
        "current_command": str(item.get("current_command") or ""),
        "cwd": str(item.get("cwd") or ""),
        "state": str(item.get("state") or "starting"),
        "updated_at": float(item.get("updated_at") or time.time()),
        "last_seen_at": float(item.get("last_seen_at") or item.get("updated_at") or time.time()),
        "snippet": str(item.get("snippet") or ""),
        "model": str(item.get("model") or CODEX_DEFAULT_MODEL),
        "reasoning_effort": str(item.get("reasoning_effort") or CODEX_DEFAULT_REASONING_EFFORT),
        "active": bool(item.get("active", True)),
        "can_resume": bool(str(item.get("resume_id") or "").strip()),
    }
    resume_id = str(item.get("resume_id") or "").strip()
    if resume_id:
        record["resume_id"] = resume_id
    closed_at = item.get("closed_at")
    if closed_at not in {None, ""}:
        record["closed_at"] = float(closed_at)
    return record


def _session_id_from_created_by(created_by: str) -> str:
    marker = str(created_by or "").strip()
    if not marker.lower().startswith("session:"):
        return ""
    candidate = marker.split(":", 1)[1].strip()
    if not VALID_NAME_RE.fullmatch(candidate):
        return ""
    return candidate


def _normalize_share_title(raw: Any, fallback_name: str) -> str:
    text = re.sub(r"\s+", " ", str(raw or "").strip())
    if text:
        return text[:120]
    return (fallback_name or "Shared file")[:120]


def _normalize_share_expires_hours(raw: Any) -> int:
    try:
        value = int(raw if raw is not None else SHARED_OUTBOX_DEFAULT_EXPIRES_HOURS)
    except Exception:
        value = SHARED_OUTBOX_DEFAULT_EXPIRES_HOURS
    value = max(1, value)
    return min(value, max(1, SHARED_OUTBOX_MAX_EXPIRES_HOURS))


def _share_expired(item: Dict[str, Any], now_ms: Optional[int] = None) -> bool:
    current = int(now_ms if now_ms is not None else _now_ms())
    expires_at = _coerce_ms(item.get("expires_at"), 0)
    return expires_at > 0 and expires_at <= current


def _shared_item_from_raw(raw: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    item_id = _clean_entity_id(raw.get("id"))
    wsl_path = str(raw.get("wsl_path") or "").strip()
    has_wsl_path = wsl_path.startswith("/")
    file_name = str(raw.get("file_name") or "").strip()
    windows_path = str(raw.get("windows_path") or "").strip()
    if not item_id or not file_name:
        return None
    if not has_wsl_path and not windows_path:
        return None
    now_ms = _now_ms()
    created_at = _coerce_ms(raw.get("created_at"), now_ms)
    expires_at = _coerce_ms(raw.get("expires_at"), created_at)
    mime_type = str(raw.get("mime_type") or "").strip() or "application/octet-stream"
    try:
        size_bytes = max(0, int(raw.get("size_bytes") or 0))
    except Exception:
        size_bytes = 0
    created_by = str(raw.get("created_by") or "").strip()[:64]
    session = str(raw.get("session") or "").strip()
    if not session:
        session = _session_id_from_created_by(created_by)
    if session and not VALID_NAME_RE.fullmatch(session):
        session = ""
    item_kind = str(raw.get("item_kind") or "").strip().lower()
    if item_kind not in {"file", "directory"}:
        item_kind = "directory" if bool(raw.get("is_directory")) else "file"
    source_kind = str(raw.get("source_kind") or "").strip().lower() or "registered"
    windows_path = windows_path or (_wsl_to_windows_path(wsl_path) if has_wsl_path else "")
    if not has_wsl_path and not os.path.isabs(windows_path):
        return None
    display_path = str(raw.get("display_path") or windows_path or wsl_path).strip()
    is_image = item_kind == "file" and (bool(raw.get("is_image")) or mime_type.startswith("image/"))
    return {
        "id": item_id,
        "title": _normalize_share_title(raw.get("title"), file_name),
        "wsl_path": wsl_path if has_wsl_path else "",
        "file_name": file_name[:180],
        "mime_type": mime_type[:120],
        "size_bytes": size_bytes,
        "created_at": created_at,
        "expires_at": expires_at,
        "created_by": created_by,
        "is_image": is_image,
        "session": session,
        "item_kind": item_kind,
        "source_kind": source_kind,
        "windows_path": windows_path,
        "display_path": display_path,
    }


def _sort_and_trim_shared_outbox_unlocked() -> None:
    items = SHARED_OUTBOX_DATA.get("items") or []
    now_ms = _now_ms()
    cleaned: List[Dict[str, Any]] = []
    seen_ids = set()
    for raw in items:
        if not isinstance(raw, dict):
            continue
        item = _shared_item_from_raw(raw)
        if not item:
            continue
        item_id = item["id"]
        if item_id in seen_ids:
            continue
        if _share_expired(item, now_ms=now_ms):
            continue
        seen_ids.add(item_id)
        cleaned.append(item)
    cleaned.sort(key=lambda x: int(x.get("created_at") or 0), reverse=True)
    SHARED_OUTBOX_DATA["items"] = cleaned[: max(1, SHARED_OUTBOX_MAX_KEEP)]


def _persist_shared_outbox_unlocked() -> None:
    _sort_and_trim_shared_outbox_unlocked()
    parent = os.path.dirname(SHARED_OUTBOX_FILE)
    if parent:
        os.makedirs(parent, exist_ok=True)
    payload = {"items": SHARED_OUTBOX_DATA.get("items") or []}
    temp_path = SHARED_OUTBOX_FILE + ".tmp"
    with open(temp_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    os.replace(temp_path, SHARED_OUTBOX_FILE)


def _load_shared_outbox_unlocked() -> None:
    global SHARED_OUTBOX_LOADED
    if SHARED_OUTBOX_LOADED:
        return
    SHARED_OUTBOX_LOADED = True
    SHARED_OUTBOX_DATA["items"] = []
    source_path = SHARED_OUTBOX_FILE if os.path.exists(SHARED_OUTBOX_FILE) else LEGACY_SHARED_OUTBOX_FILE
    if not os.path.exists(source_path):
        return
    raw = _read_json_file(source_path)
    if not isinstance(raw, dict):
        return
    items = raw.get("items")
    if isinstance(items, list):
        SHARED_OUTBOX_DATA["items"] = items
    _sort_and_trim_shared_outbox_unlocked()


def _shared_outbox_snapshot_unlocked() -> Dict[str, Any]:
    _sort_and_trim_shared_outbox_unlocked()
    return {"items": json.loads(json.dumps(SHARED_OUTBOX_DATA.get("items") or []))}


def _find_shared_item_unlocked(item_id: str) -> Optional[Dict[str, Any]]:
    item_id = _clean_entity_id(item_id)
    if not item_id:
        return None
    for item in SHARED_OUTBOX_DATA.get("items") or []:
        if (item or {}).get("id") == item_id:
            return item
    return None


def _public_shared_item(item: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "id": item.get("id"),
        "title": item.get("title"),
        "file_name": item.get("file_name"),
        "mime_type": item.get("mime_type"),
        "size_bytes": item.get("size_bytes"),
        "created_at": item.get("created_at"),
        "expires_at": item.get("expires_at"),
        "created_by": item.get("created_by"),
        "is_image": bool(item.get("is_image")),
        "session": item.get("session") or "",
        "item_kind": item.get("item_kind") or "file",
        "source_kind": item.get("source_kind") or "registered",
        "wsl_path": item.get("wsl_path"),
        "windows_path": item.get("windows_path") or "",
        "display_path": item.get("display_path") or item.get("wsl_path") or "",
        "download_url": (
            f"/share/file/{item.get('id')}"
            if (item.get("item_kind") or "file") == "file"
            else ""
        ),
    }


def _public_session_file_item(session: str, item: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if not item:
        return None
    public = _public_shared_item(item)
    if (item.get("item_kind") or "file") == "file":
        public["download_url"] = (
            f"/codex/session/{quote(_validate_session_name(session))}/files/{quote(str(item.get('id') or ''))}/download"
        )
    else:
        public["download_url"] = ""
    return public


def _create_shared_outbox_item(
    path: str,
    *,
    title: str = "",
    expires_hours: Optional[int] = None,
    created_by: str = "",
    session: str = "",
    allow_directory: bool = False,
    source_kind: str = "registered",
) -> Dict[str, Any]:
    wsl_abs = _resolve_session_access_path(path)
    unc = _wsl_unc_path(wsl_abs)
    if not os.path.exists(unc):
        raise HTTPException(status_code=404, detail="File not found.")
    is_directory = os.path.isdir(unc)
    if is_directory and not allow_directory:
        raise HTTPException(status_code=400, detail="Path is a directory. Provide a file path.")
    try:
        size_bytes = 0 if is_directory else int(os.path.getsize(unc))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Could not stat file: {type(e).__name__}: {e}")
    max_bytes = max(1, SHARED_OUTBOX_MAX_FILE_MB) * 1024 * 1024
    if size_bytes > max_bytes:
        raise HTTPException(
            status_code=413,
            detail=f"File too large ({size_bytes} bytes). Limit is {max_bytes} bytes.",
        )
    file_name = os.path.basename(wsl_abs.rstrip("/")) or "shared.bin"
    if is_directory:
        mime_type = "inode/directory"
    else:
        claimed_mime = (mimetypes.guess_type(file_name)[0] or "application/octet-stream").strip() or "application/octet-stream"
        detected_mime = ""
        try:
            with open(unc, "rb") as f:
                detected_mime = _detect_mime_from_bytes(f.read(512))
        except Exception:
            detected_mime = ""
        mime_type = _choose_effective_mime_type(claimed_mime, detected_mime)
    now_ms = _now_ms()
    expires_h = _normalize_share_expires_hours(expires_hours)
    expires_at = now_ms + int(expires_h * 3600 * 1000)
    normalized_session = session.strip() if isinstance(session, str) else ""
    if not normalized_session:
        normalized_session = _session_id_from_created_by(created_by)
    if normalized_session and not VALID_NAME_RE.fullmatch(normalized_session):
        raise HTTPException(status_code=400, detail="Invalid session name.")
    item = {
        "id": f"shr_{uuid.uuid4().hex[:12]}",
        "title": _normalize_share_title(title, file_name),
        "wsl_path": wsl_abs,
        "file_name": file_name,
        "mime_type": mime_type,
        "size_bytes": size_bytes,
        "created_at": now_ms,
        "expires_at": expires_at,
        "created_by": (created_by or "manual")[:64],
        "is_image": mime_type.startswith("image/"),
        "session": normalized_session,
        "item_kind": "directory" if is_directory else "file",
        "source_kind": (source_kind or "registered")[:32],
        "windows_path": _wsl_to_windows_path(wsl_abs),
        "display_path": _display_path_for_wsl(wsl_abs),
    }
    with SHARED_OUTBOX_LOCK:
        _load_shared_outbox_unlocked()
        SHARED_OUTBOX_DATA["items"].insert(0, item)
        _persist_shared_outbox_unlocked()
    return item


def _normalize_host_path(path_value: str) -> str:
    cleaned = str(path_value or "").strip().strip('"')
    if not cleaned:
        raise HTTPException(status_code=400, detail="path is required.")
    normalized = os.path.normpath(os.path.abspath(cleaned))
    if not os.path.isabs(normalized):
        raise HTTPException(status_code=400, detail="Host path must be absolute.")
    drive, _ = os.path.splitdrive(normalized)
    if not drive:
        raise HTTPException(status_code=400, detail="Host path must resolve to a local drive.")
    return normalized


def _host_unique_target_path(dest_dir: str, file_name: str) -> str:
    directory = _normalize_host_path(dest_dir)
    os.makedirs(directory, exist_ok=True)
    base_name = os.path.basename(str(file_name or "").strip()) or "upload.bin"
    safe_name = re.sub(r'[<>:"/\\|?*\x00-\x1f]+', "_", base_name).strip(" .") or "upload.bin"
    stem, ext = os.path.splitext(safe_name)
    candidate = os.path.join(directory, safe_name)
    counter = 2
    while os.path.exists(candidate):
        candidate = os.path.join(directory, f"{stem} ({counter}){ext}")
        counter += 1
    return candidate


def _inspect_host_share_path(path_value: str, *, allow_directory: bool = False) -> Dict[str, Any]:
    _ensure_windows_host()
    host_path = _normalize_host_path(path_value)
    if not os.path.exists(host_path):
        raise HTTPException(status_code=404, detail="Host path not found.")
    is_directory = os.path.isdir(host_path)
    if is_directory and not allow_directory:
        raise HTTPException(status_code=400, detail="Host path is a directory. Provide a file path.")
    try:
        size_bytes = 0 if is_directory else int(os.path.getsize(host_path))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Could not stat host path: {type(exc).__name__}: {exc}")
    max_bytes = max(1, SHARED_OUTBOX_MAX_FILE_MB) * 1024 * 1024
    if size_bytes > max_bytes:
        raise HTTPException(
            status_code=413,
            detail=f"File too large ({size_bytes} bytes). Limit is {max_bytes} bytes.",
        )
    file_name = os.path.basename(host_path.rstrip("\\/")) or "shared.bin"
    if is_directory:
        mime_type = "inode/directory"
    else:
        claimed_mime = (mimetypes.guess_type(file_name)[0] or "application/octet-stream").strip() or "application/octet-stream"
        detected_mime = ""
        try:
            with open(host_path, "rb") as f:
                detected_mime = _detect_mime_from_bytes(f.read(512))
        except Exception:
            detected_mime = ""
        mime_type = _choose_effective_mime_type(claimed_mime, detected_mime)
    return {
        "path": host_path,
        "file_name": file_name,
        "mime_type": mime_type,
        "size_bytes": size_bytes,
        "is_directory": is_directory,
    }


def _create_host_shared_outbox_item(
    path_value: str,
    *,
    title: str = "",
    expires_hours: Optional[int] = None,
    created_by: str = "",
    session: str = "",
    allow_directory: bool = False,
    source_kind: str = "host_transfer",
) -> Dict[str, Any]:
    info = _inspect_host_share_path(path_value, allow_directory=allow_directory)
    now_ms = _now_ms()
    expires_h = _normalize_share_expires_hours(expires_hours)
    expires_at = now_ms + int(expires_h * 3600 * 1000)
    normalized_session = session.strip() if isinstance(session, str) else ""
    if not normalized_session:
        normalized_session = _session_id_from_created_by(created_by)
    if normalized_session and not VALID_NAME_RE.fullmatch(normalized_session):
        raise HTTPException(status_code=400, detail="Invalid session name.")
    item = {
        "id": f"shr_{uuid.uuid4().hex[:12]}",
        "title": _normalize_share_title(title, info["file_name"]),
        "wsl_path": "",
        "file_name": info["file_name"],
        "mime_type": info["mime_type"],
        "size_bytes": info["size_bytes"],
        "created_at": now_ms,
        "expires_at": expires_at,
        "created_by": (created_by or "host")[:64],
        "is_image": str(info["mime_type"]).startswith("image/"),
        "session": normalized_session,
        "item_kind": "directory" if info["is_directory"] else "file",
        "source_kind": (source_kind or "host_transfer")[:32],
        "windows_path": info["path"],
        "display_path": info["path"],
    }
    with SHARED_OUTBOX_LOCK:
        _load_shared_outbox_unlocked()
        SHARED_OUTBOX_DATA["items"].insert(0, item)
        _persist_shared_outbox_unlocked()
    return item


def _sort_and_trim_session_files_unlocked() -> None:
    items = SESSION_FILES_DATA.get("items") or []
    now_ms = _now_ms()
    cleaned: List[Dict[str, Any]] = []
    seen_ids = set()
    for raw in items:
        if not isinstance(raw, dict):
            continue
        item = _shared_item_from_raw(raw)
        if not item:
            continue
        session_id = str(item.get("session") or "").strip()
        if not session_id or not VALID_NAME_RE.fullmatch(session_id):
            continue
        item_id = item["id"]
        if item_id in seen_ids or _share_expired(item, now_ms=now_ms):
            continue
        seen_ids.add(item_id)
        cleaned.append(item)
    cleaned.sort(key=lambda x: int(x.get("created_at") or 0), reverse=True)
    SESSION_FILES_DATA["items"] = cleaned[: max(1, SESSION_FILES_MAX_KEEP)]


def _persist_session_files_unlocked() -> None:
    _sort_and_trim_session_files_unlocked()
    parent = os.path.dirname(SESSION_FILES_FILE)
    if parent:
        os.makedirs(parent, exist_ok=True)
    payload = {"items": SESSION_FILES_DATA.get("items") or []}
    temp_path = SESSION_FILES_FILE + ".tmp"
    with open(temp_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    os.replace(temp_path, SESSION_FILES_FILE)


def _load_session_files_unlocked() -> None:
    global SESSION_FILES_LOADED
    if SESSION_FILES_LOADED:
        return
    SESSION_FILES_LOADED = True
    SESSION_FILES_DATA["items"] = []
    source_path = ""
    for candidate in (SESSION_FILES_FILE, SHARED_OUTBOX_FILE, LEGACY_SHARED_OUTBOX_FILE):
        if candidate and os.path.exists(candidate):
            source_path = candidate
            break
    if not source_path:
        return
    raw = _read_json_file(source_path)
    if not isinstance(raw, dict):
        return
    items = raw.get("items")
    if isinstance(items, list):
        SESSION_FILES_DATA["items"] = items
    _sort_and_trim_session_files_unlocked()


def _session_files_snapshot_unlocked(session: str) -> Dict[str, Any]:
    _sort_and_trim_session_files_unlocked()
    session_id = session.strip()
    items = [
        item
        for item in (SESSION_FILES_DATA.get("items") or [])
        if str((item or {}).get("session") or "").strip() == session_id
    ]
    return {"items": json.loads(json.dumps(items))}


def _find_session_file_unlocked(session: str, file_id: str) -> Optional[Dict[str, Any]]:
    session_id = session.strip()
    clean_id = _clean_entity_id(file_id)
    if not session_id or not clean_id:
        return None
    for item in SESSION_FILES_DATA.get("items") or []:
        if (
            str((item or {}).get("id") or "").strip() == clean_id
            and str((item or {}).get("session") or "").strip() == session_id
        ):
            return item
    return None


def _create_session_file_item(
    session: str,
    path: str,
    *,
    title: str = "",
    expires_hours: Optional[int] = None,
    created_by: str = "",
    allow_directory: bool = False,
    source_kind: str = "registered",
) -> Dict[str, Any]:
    session_id = _validate_session_name(session)
    wsl_abs = _resolve_session_access_path(path)
    unc = _wsl_unc_path(wsl_abs)
    if not os.path.exists(unc):
        raise HTTPException(status_code=404, detail="Path not found.")
    is_directory = os.path.isdir(unc)
    if is_directory and not allow_directory:
        raise HTTPException(status_code=400, detail="Select a file or enable directory registration.")
    if not is_directory:
        try:
            size_bytes = int(os.path.getsize(unc))
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Could not stat file: {type(e).__name__}: {e}")
    else:
        size_bytes = 0
    max_bytes = max(1, SESSION_FILES_MAX_FILE_MB) * 1024 * 1024
    if size_bytes > max_bytes:
        raise HTTPException(
            status_code=413,
            detail=f"File too large ({size_bytes} bytes). Limit is {max_bytes} bytes.",
        )
    file_name = os.path.basename(wsl_abs.rstrip("/")) or "session-item"
    if is_directory:
        mime_type = "inode/directory"
    else:
        claimed_mime = (mimetypes.guess_type(file_name)[0] or "application/octet-stream").strip() or "application/octet-stream"
        detected_mime = ""
        try:
            with open(unc, "rb") as f:
                detected_mime = _detect_mime_from_bytes(f.read(512))
        except Exception:
            detected_mime = ""
        mime_type = _choose_effective_mime_type(claimed_mime, detected_mime)
    now_ms = _now_ms()
    expires_h = _normalize_share_expires_hours(expires_hours)
    item = {
        "id": f"sf_{uuid.uuid4().hex[:12]}",
        "session": session_id,
        "title": _normalize_share_title(title, file_name),
        "wsl_path": wsl_abs,
        "file_name": file_name,
        "mime_type": mime_type,
        "size_bytes": size_bytes,
        "created_at": now_ms,
        "expires_at": now_ms + int(expires_h * 3600 * 1000),
        "created_by": (created_by or f"session:{session_id}")[:64],
        "is_image": mime_type.startswith("image/"),
        "item_kind": "directory" if is_directory else "file",
        "source_kind": (source_kind or "registered")[:32],
        "windows_path": _wsl_to_windows_path(wsl_abs),
        "display_path": _display_path_for_wsl(wsl_abs),
    }
    with SESSION_FILES_LOCK:
        _load_session_files_unlocked()
        SESSION_FILES_DATA["items"].insert(0, item)
        _persist_session_files_unlocked()
    return item


def _remove_session_file_unlocked(session: str, file_id: str) -> Optional[Dict[str, Any]]:
    existing = _find_session_file_unlocked(session, file_id)
    if not existing:
        return None
    SESSION_FILES_DATA["items"] = [
        item
        for item in (SESSION_FILES_DATA.get("items") or [])
        if not (
            str((item or {}).get("id") or "").strip() == existing.get("id")
            and str((item or {}).get("session") or "").strip() == existing.get("session")
        )
    ]
    return existing


def _session_upload_root(session: str) -> str:
    session_id = _validate_session_name(session)
    return _norm_posix(posixpath.join(CODEX_WORKDIR.rstrip("/"), ".remote_uploads", session_id))


def _session_upload_path(session: str, base_name: str) -> str:
    safe_name = _safe_name(base_name or "upload.bin")
    ts = int(time.time() * 1000)
    return _norm_posix(posixpath.join(_session_upload_root(session), f"{ts}_{safe_name}"))


def _session_file_is_managed_upload(item: Dict[str, Any]) -> bool:
    if str(item.get("source_kind") or "").strip().lower() not in {"upload", "session_upload", "managed"}:
        return False
    session_id = str(item.get("session") or "").strip()
    wsl_path = str(item.get("wsl_path") or "").strip()
    if not session_id or not wsl_path.startswith("/"):
        return False
    return _path_under_root(wsl_path, _session_upload_root(session_id))


def _compact_assistant_snapshot_text(text: str) -> str:
    lines = [line.rstrip() for line in str(text or "").splitlines()]
    lines = [line for line in lines if line.strip()]
    if not lines:
        return ""
    tail = "\n".join(lines[-24:]).strip()
    if len(tail) > SESSION_NOTES_MAX_SNAPSHOT_CHARS:
        tail = tail[-SESSION_NOTES_MAX_SNAPSHOT_CHARS :]
    return tail


def _normalize_session_note_record(session: str, raw: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    session_id = _validate_session_name(session)
    data = raw or {}
    now_ms = _now_ms()
    created_at = _coerce_ms(data.get("created_at"), now_ms)
    updated_at = _coerce_ms(data.get("updated_at"), created_at)
    if updated_at < created_at:
        updated_at = created_at
    content = str(data.get("content") or "")
    if len(content) > SESSION_NOTES_MAX_CHARS:
        content = content[:SESSION_NOTES_MAX_CHARS]
    snapshot = _compact_assistant_snapshot_text(str(data.get("last_response_snapshot") or ""))
    return {
        "session": session_id,
        "content": content,
        "created_at": created_at,
        "updated_at": updated_at,
        "last_response_snapshot": snapshot,
    }


def _sort_and_trim_session_notes_unlocked() -> None:
    cleaned: Dict[str, Dict[str, Any]] = {}
    for key, value in (SESSION_NOTES_DATA.get("notes") or {}).items():
        try:
            session_id = _validate_session_name(key)
        except Exception:
            continue
        cleaned[session_id] = _normalize_session_note_record(session_id, value if isinstance(value, dict) else {})
    SESSION_NOTES_DATA["notes"] = cleaned


def _persist_session_notes_unlocked() -> None:
    _sort_and_trim_session_notes_unlocked()
    parent = os.path.dirname(SESSION_NOTES_FILE)
    if parent:
        os.makedirs(parent, exist_ok=True)
    payload = {"notes": SESSION_NOTES_DATA.get("notes") or {}}
    temp_path = SESSION_NOTES_FILE + ".tmp"
    with open(temp_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    os.replace(temp_path, SESSION_NOTES_FILE)


def _load_session_notes_unlocked() -> None:
    global SESSION_NOTES_LOADED
    if SESSION_NOTES_LOADED:
        return
    SESSION_NOTES_LOADED = True
    SESSION_NOTES_DATA["notes"] = {}
    raw = _read_json_file(SESSION_NOTES_FILE)
    if not isinstance(raw, dict):
        return
    notes = raw.get("notes")
    if isinstance(notes, dict):
        SESSION_NOTES_DATA["notes"] = notes
    _sort_and_trim_session_notes_unlocked()


def _get_session_note_unlocked(session: str) -> Dict[str, Any]:
    session_id = _validate_session_name(session)
    _sort_and_trim_session_notes_unlocked()
    existing = (SESSION_NOTES_DATA.get("notes") or {}).get(session_id)
    if isinstance(existing, dict):
        return json.loads(json.dumps(existing))
    now_ms = _now_ms()
    return {
        "session": session_id,
        "content": "",
        "created_at": now_ms,
        "updated_at": now_ms,
        "last_response_snapshot": "",
    }


def _save_session_note_unlocked(session: str, content: str, last_response_snapshot: str = "") -> Dict[str, Any]:
    session_id = _validate_session_name(session)
    existing = _get_session_note_unlocked(session_id)
    snapshot = _compact_assistant_snapshot_text(last_response_snapshot or existing.get("last_response_snapshot") or "")
    now_ms = _now_ms()
    record = {
        "session": session_id,
        "content": str(content or "")[:SESSION_NOTES_MAX_CHARS],
        "created_at": existing.get("created_at") or now_ms,
        "updated_at": now_ms,
        "last_response_snapshot": snapshot,
    }
    SESSION_NOTES_DATA.setdefault("notes", {})[session_id] = record
    _persist_session_notes_unlocked()
    return json.loads(json.dumps(record))


def _append_session_note_snapshot_unlocked(session: str, snapshot: str) -> Dict[str, Any]:
    compact = _compact_assistant_snapshot_text(snapshot)
    if not compact:
        raise HTTPException(status_code=409, detail="No recent assistant response available to append.")
    existing = _get_session_note_unlocked(session)
    base = str(existing.get("content") or "").rstrip()
    next_content = f"{base}\n\n{compact}" if base else compact
    return _save_session_note_unlocked(session, next_content, compact)


def _telegram_get_updates(token: str, offset: Optional[int] = None, limit: int = 20) -> Dict[str, Any]:
    query_parts = [f"limit={max(1, min(int(limit or 20), 100))}"]
    if offset is not None:
        try:
            query_parts.append(f"offset={int(offset)}")
        except Exception:
            pass
    endpoint = f"{TELEGRAM_API_BASE.rstrip('/')}/bot{token}/getUpdates?{'&'.join(query_parts)}"
    req = urllib.request.Request(
        endpoint,
        method="GET",
        headers={"Accept": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=max(5.0, TELEGRAM_TIMEOUT_SECONDS)) as resp:
        raw = resp.read().decode("utf-8", errors="replace")
    try:
        parsed = json.loads(raw) if raw else {}
    except Exception:
        return {}
    if not isinstance(parsed, dict):
        return {}
    return parsed


def _telegram_extract_chat_id_from_update(update: Dict[str, Any]) -> str:
    if not isinstance(update, dict):
        return ""
    msg_keys = (
        "message",
        "edited_message",
        "channel_post",
        "edited_channel_post",
        "my_chat_member",
        "chat_member",
        "chat_join_request",
    )
    for key in msg_keys:
        obj = update.get(key)
        if not isinstance(obj, dict):
            continue
        chat = obj.get("chat")
        if isinstance(chat, dict) and chat.get("id") is not None:
            return str(chat.get("id")).strip()

    callback = update.get("callback_query")
    if isinstance(callback, dict):
        msg = callback.get("message")
        if isinstance(msg, dict):
            chat = msg.get("chat")
            if isinstance(chat, dict) and chat.get("id") is not None:
                return str(chat.get("id")).strip()
        from_user = callback.get("from")
        if isinstance(from_user, dict) and from_user.get("id") is not None:
            return str(from_user.get("id")).strip()

    inline_query = update.get("inline_query")
    if isinstance(inline_query, dict):
        from_user = inline_query.get("from")
        if isinstance(from_user, dict) and from_user.get("id") is not None:
            return str(from_user.get("id")).strip()
    return ""


def _telegram_discover_chat_id(token: str) -> str:
    if not token:
        return ""
    try:
        parsed = _telegram_get_updates(token)
    except Exception:
        return ""
    if not parsed.get("ok"):
        return ""
    items = parsed.get("result")
    if not isinstance(items, list):
        return ""
    for raw in reversed(items):
        cid = _telegram_extract_chat_id_from_update(raw if isinstance(raw, dict) else {})
        if cid:
            return cid
    return ""


def _persist_telegram_chat_id(chat_id: str) -> None:
    cid = str(chat_id or "").strip()
    if not cid:
        return
    chat_path = os.path.abspath(TELEGRAM_CHAT_FILE or "")
    key_path = os.path.abspath(TELEGRAM_SECRET_FILE or "")
    # Never overwrite the token file with chat id.
    if not chat_path or (key_path and chat_path == key_path):
        return
    try:
        parent = os.path.dirname(chat_path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        with open(chat_path, "w", encoding="utf-8") as f:
            f.write(f"{cid}\n")
    except Exception:
        return


def _telegram_resolve_chat_id(allow_discovery: bool = True) -> str:
    cid = str(TELEGRAM_CHAT_ID or "").strip()
    if cid:
        return cid
    # Read chat id file dynamically so once discovered/persisted it works after restart.
    file_values = _parse_telegram_secret_text(_read_text_file(TELEGRAM_CHAT_FILE))
    cid = str(file_values.get("chat_id") or "").strip()
    if cid:
        return cid
    if not allow_discovery:
        return ""
    discovered = _telegram_discover_chat_id(str(TELEGRAM_BOT_TOKEN or "").strip())
    if discovered:
        _persist_telegram_chat_id(discovered)
    return discovered


def _telegram_enabled() -> bool:
    token = str(TELEGRAM_BOT_TOKEN or "").strip()
    return bool(token and _telegram_resolve_chat_id(allow_discovery=True))


def _mask_sensitive(text: str) -> str:
    value = str(text or "").strip()
    if len(value) <= 4:
        return "*" * len(value)
    return f"{value[:2]}{'*' * (len(value) - 4)}{value[-2:]}"


def _normalize_telegram_caption(raw: Any) -> str:
    text = re.sub(r"\s+", " ", str(raw or "").strip())
    if not text:
        return ""
    # Telegram caption max is 1024 chars.
    return text[:1024]


def _detect_mime_from_bytes(sample: bytes) -> str:
    head = bytes(sample or b"")
    if not head:
        return ""
    if head.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if head.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if head.startswith(b"GIF87a") or head.startswith(b"GIF89a"):
        return "image/gif"
    if head.startswith(b"RIFF") and len(head) >= 12 and head[8:12] == b"WEBP":
        return "image/webp"
    if head.startswith(b"%PDF-"):
        return "application/pdf"
    if head.startswith(b"PK\x03\x04"):
        return "application/zip"
    if b"\x00" not in head:
        printable = 0
        for b in head:
            if b in (9, 10, 13) or 32 <= b <= 126:
                printable += 1
        if printable >= int(len(head) * 0.95):
            return "text/plain"
    return ""


def _mime_preferred_extension(mime_type: str) -> str:
    m = str(mime_type or "").strip().lower()
    mapping = {
        "image/png": ".png",
        "image/jpeg": ".jpg",
        "image/gif": ".gif",
        "image/webp": ".webp",
        "application/pdf": ".pdf",
        "text/plain": ".txt",
        "application/zip": ".zip",
    }
    return mapping.get(m, "")


def _is_known_zip_container_document_mime(mime_type: str) -> bool:
    m = str(mime_type or "").strip().lower()
    if not m:
        return False
    if m.startswith("application/vnd.openxmlformats-officedocument."):
        return True
    if m.startswith("application/vnd.oasis.opendocument."):
        return True
    return m in {
        "application/epub+zip",
        "application/vnd.ms-word.document.macroenabled.12",
        "application/vnd.ms-word.template.macroenabled.12",
        "application/vnd.ms-excel.sheet.macroenabled.12",
        "application/vnd.ms-excel.template.macroenabled.12",
        "application/vnd.ms-excel.sheet.binary.macroenabled.12",
        "application/vnd.ms-powerpoint.presentation.macroenabled.12",
        "application/vnd.ms-powerpoint.template.macroenabled.12",
        "application/vnd.ms-powerpoint.slideshow.macroenabled.12",
    }


def _choose_effective_mime_type(claimed_mime: str, detected_mime: str) -> str:
    claimed = str(claimed_mime or "").strip() or "application/octet-stream"
    detected = str(detected_mime or "").strip()
    if not detected:
        return claimed
    # DOCX/ODT/PPTX/XLSX are ZIP containers; keep the specific office MIME.
    if detected == "application/zip" and _is_known_zip_container_document_mime(claimed):
        return claimed
    return detected


def _build_multipart_form_data(
    fields: Dict[str, str],
    *,
    file_field: str,
    file_name: str,
    content_type: str,
    file_bytes: bytes,
) -> Tuple[bytes, str]:
    boundary = f"----codrex{uuid.uuid4().hex}"
    chunks: List[bytes] = []
    for k, v in fields.items():
        chunks.append(f"--{boundary}\r\n".encode("utf-8"))
        chunks.append(f'Content-Disposition: form-data; name="{k}"\r\n\r\n'.encode("utf-8"))
        chunks.append(str(v).encode("utf-8"))
        chunks.append(b"\r\n")

    safe_name = (file_name or "upload.bin").replace('"', "_")
    mime = (content_type or "application/octet-stream").strip() or "application/octet-stream"
    chunks.append(f"--{boundary}\r\n".encode("utf-8"))
    chunks.append(
        (
            f'Content-Disposition: form-data; name="{file_field}"; filename="{safe_name}"\r\n'
            f"Content-Type: {mime}\r\n\r\n"
        ).encode("utf-8")
    )
    chunks.append(file_bytes)
    chunks.append(b"\r\n")
    chunks.append(f"--{boundary}--\r\n".encode("utf-8"))
    body = b"".join(chunks)
    return body, f"multipart/form-data; boundary={boundary}"


def _telegram_send_shared_item(item: Dict[str, Any], caption_override: str = "") -> Dict[str, Any]:
    token = str(TELEGRAM_BOT_TOKEN or "").strip()
    if not token:
        return {
            "ok": False,
            "error": "telegram_not_configured",
            "detail": "Telegram bot token is missing. Put token in `Telegram bot/key.txt` or set CODEX_TELEGRAM_BOT_TOKEN.",
        }
    chat_id = _telegram_resolve_chat_id(allow_discovery=True)
    if not chat_id:
        return {
            "ok": False,
            "error": "telegram_chat_not_found",
            "detail": "Telegram chat id is not available yet. Open your bot chat in Telegram, press Start, then retry.",
        }

    wsl_path = str(item.get("wsl_path") or "").strip()
    if not wsl_path:
        return {"ok": False, "error": "telegram_missing_path", "detail": "Shared item has no source path."}

    wsl_abs = _resolve_session_access_path(wsl_path)
    unc = _wsl_unc_path(wsl_abs)
    if not os.path.exists(unc):
        return {"ok": False, "error": "telegram_file_missing", "detail": "Shared file is no longer available."}
    if os.path.isdir(unc):
        return {"ok": False, "error": "telegram_is_directory", "detail": "Shared path is a directory."}

    try:
        size_bytes = int(os.path.getsize(unc))
    except Exception as e:
        return {"ok": False, "error": "telegram_stat_failed", "detail": f"Could not read file size: {type(e).__name__}: {e}"}
    max_bytes = max(1, TELEGRAM_MAX_FILE_MB) * 1024 * 1024
    if size_bytes > max_bytes:
        return {
            "ok": False,
            "error": "telegram_file_too_large",
            "detail": f"File too large for Telegram relay ({size_bytes} bytes). Limit is {max_bytes} bytes.",
            "size_bytes": size_bytes,
            "max_bytes": max_bytes,
        }

    file_name_raw = str(item.get("file_name") or os.path.basename(wsl_abs.rstrip("/")) or "shared.bin")
    claimed_mime = str(item.get("mime_type") or mimetypes.guess_type(file_name_raw)[0] or "application/octet-stream")

    try:
        with open(unc, "rb") as f:
            file_bytes = f.read()
    except Exception as e:
        return {"ok": False, "error": "telegram_read_failed", "detail": f"Could not read file: {type(e).__name__}: {e}"}

    detected_mime = _detect_mime_from_bytes(file_bytes[:512])
    effective_mime = _choose_effective_mime_type(claimed_mime, detected_mime)
    effective_file_name = file_name_raw
    preferred_ext = _mime_preferred_extension(effective_mime)
    if preferred_ext:
        stem, old_ext = os.path.splitext(file_name_raw)
        if old_ext.lower() != preferred_ext:
            effective_file_name = f"{stem or file_name_raw}{preferred_ext}"
    caption = _normalize_telegram_caption(caption_override or item.get("title") or effective_file_name)

    payload, content_type = _build_multipart_form_data(
        {
            "chat_id": chat_id,
            **({"caption": caption} if caption else {}),
        },
        file_field="document",
        file_name=effective_file_name,
        content_type=effective_mime,
        file_bytes=file_bytes,
    )

    endpoint = f"{TELEGRAM_API_BASE.rstrip('/')}/bot{token}/sendDocument"
    req = urllib.request.Request(
        endpoint,
        data=payload,
        method="POST",
        headers={
            "Content-Type": content_type,
            "Accept": "application/json",
        },
    )

    status_code = 0
    raw_body = ""
    try:
        with urllib.request.urlopen(req, timeout=max(5.0, TELEGRAM_TIMEOUT_SECONDS)) as resp:
            status_code = int(getattr(resp, "status", 200) or 200)
            raw_body = resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        status_code = int(getattr(e, "code", 0) or 0)
        try:
            raw_body = e.read().decode("utf-8", errors="replace")
        except Exception:
            raw_body = str(e)
    except Exception as e:
        return {"ok": False, "error": "telegram_request_failed", "detail": f"Telegram request failed: {type(e).__name__}: {e}"}

    try:
        parsed = json.loads(raw_body) if raw_body else {}
    except Exception:
        parsed = {}

    if status_code != 200:
        detail = ""
        if isinstance(parsed, dict):
            detail = str(parsed.get("description") or "").strip()
        if not detail:
            detail = f"Telegram API returned HTTP {status_code}."
        return {"ok": False, "error": "telegram_http_error", "detail": detail, "status_code": status_code}

    if not isinstance(parsed, dict) or not parsed.get("ok"):
        detail = "Telegram API did not accept the file."
        if isinstance(parsed, dict):
            detail = str(parsed.get("description") or detail)
        return {"ok": False, "error": "telegram_api_error", "detail": detail, "status_code": status_code}

    result = parsed.get("result") if isinstance(parsed, dict) else {}
    if not isinstance(result, dict):
        result = {}
    return {
        "ok": True,
        "chat_id": chat_id,
        "message_id": result.get("message_id"),
        "file_name": effective_file_name,
        "claimed_mime_type": claimed_mime,
        "mime_type": effective_mime,
        "mime_corrected": bool(effective_mime and effective_mime != claimed_mime),
        "size_bytes": size_bytes,
    }


def _telegram_send_text(text: str) -> Dict[str, Any]:
    token = str(TELEGRAM_BOT_TOKEN or "").strip()
    if not token:
        return {
            "ok": False,
            "error": "telegram_not_configured",
            "detail": "Telegram bot token is missing. Put token in `Telegram bot/key.txt` or set CODEX_TELEGRAM_BOT_TOKEN.",
        }
    chat_id = _telegram_resolve_chat_id(allow_discovery=True)
    if not chat_id:
        return {
            "ok": False,
            "error": "telegram_chat_not_found",
            "detail": "Telegram chat id is not available yet. Open your bot chat in Telegram, press Start, then retry.",
        }

    message = str(text or "").strip()
    if not message:
        return {"ok": False, "error": "telegram_empty_message", "detail": "Text is required."}
    if len(message) > 4096:
        return {"ok": False, "error": "telegram_message_too_long", "detail": "Text is too long for Telegram (max 4096 characters)."}

    endpoint = f"{TELEGRAM_API_BASE.rstrip('/')}/bot{token}/sendMessage"
    payload = json.dumps({"chat_id": chat_id, "text": message}, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        endpoint,
        data=payload,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
    )

    status_code = 0
    raw_body = ""
    try:
        with urllib.request.urlopen(req, timeout=max(5.0, TELEGRAM_TIMEOUT_SECONDS)) as resp:
            status_code = int(getattr(resp, "status", 200) or 200)
            raw_body = resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        status_code = int(getattr(e, "code", 0) or 0)
        try:
            raw_body = e.read().decode("utf-8", errors="replace")
        except Exception:
            raw_body = str(e)
    except Exception as e:
        return {"ok": False, "error": "telegram_request_failed", "detail": f"Telegram request failed: {type(e).__name__}: {e}"}

    try:
        parsed = json.loads(raw_body) if raw_body else {}
    except Exception:
        parsed = {}

    if status_code != 200:
        detail = ""
        if isinstance(parsed, dict):
            detail = str(parsed.get("description") or "").strip()
        if not detail:
            detail = f"Telegram API returned HTTP {status_code}."
        return {"ok": False, "error": "telegram_http_error", "detail": detail, "status_code": status_code}

    if not isinstance(parsed, dict) or not parsed.get("ok"):
        detail = "Telegram API did not accept the message."
        if isinstance(parsed, dict):
            detail = str(parsed.get("description") or detail)
        return {"ok": False, "error": "telegram_api_error", "detail": detail, "status_code": status_code}

    result = parsed.get("result") if isinstance(parsed, dict) else {}
    if not isinstance(result, dict):
        result = {}
    return {
        "ok": True,
        "chat_id": chat_id,
        "message_id": result.get("message_id"),
        "length": len(message),
    }


def _loop_extract_telegram_message(update: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    if not isinstance(update, dict):
        return None
    for key in ("message", "edited_message", "channel_post", "edited_channel_post"):
        raw = update.get(key)
        if not isinstance(raw, dict):
            continue
        chat = raw.get("chat") if isinstance(raw.get("chat"), dict) else {}
        reply_to = raw.get("reply_to_message") if isinstance(raw.get("reply_to_message"), dict) else {}
        text = str(raw.get("text") or raw.get("caption") or "").strip()
        return {
            "update_id": int(update.get("update_id") or 0),
            "message_id": int(raw.get("message_id") or 0),
            "chat_id": str(chat.get("id") or "").strip(),
            "text": text,
            "reply_to_message_id": int(reply_to.get("message_id") or 0),
        }
    return None


def _format_loop_preset_label(preset: str) -> str:
    if preset == "await-reply":
        return "Await Reply"
    if preset == "completion-checks":
        return "Completion Checks"
    if preset == "max-turns-1":
        return "Max Turns 1"
    if preset == "max-turns-2":
        return "Max Turns 2"
    if preset == "max-turns-3":
        return "Max Turns 3"
    if preset == "infinite":
        return "Infinite"
    return "Off"


def _telegram_windows_mirror_enabled_unlocked() -> bool:
    settings = _get_loop_settings_unlocked()
    return bool(settings.get("telegram_windows_mirror_enabled"))


def _telegram_windows_mirror_clean_text(text: str) -> str:
    value = str(text or "").replace("\r\n", "\n").replace("\r", "\n")
    if not value:
        return ""
    value = ANSI_ESCAPE_RE.sub("", value)
    value = CONTROL_CHAR_RE.sub("", value)
    value = re.sub(r"\n{3,}", "\n\n", value)
    if not value.strip():
        return ""
    return value.strip("\n")


def _telegram_windows_mirror_split_text(text: str, max_chars: int) -> List[str]:
    value = str(text or "")
    limit = max(200, int(max_chars or 0))
    if len(value) <= limit:
        return [value] if value else []
    chunks: List[str] = []
    remaining = value
    while remaining and len(chunks) < TELEGRAM_WINDOWS_MIRROR_MAX_PARTS:
        if len(remaining) <= limit:
            chunks.append(remaining)
            remaining = ""
            break
        split_at = remaining.rfind("\n", 0, limit)
        if split_at < max(80, limit // 3):
            split_at = limit
        chunk = remaining[:split_at].rstrip("\n")
        if chunk:
            chunks.append(chunk)
        remaining = remaining[split_at:].lstrip("\n")
    if remaining:
        notice = "\n\n[Telegram mirror truncated.]"
        if chunks:
            tail_limit = max(40, limit - len(notice))
            chunks[-1] = chunks[-1][:tail_limit].rstrip() + notice
        else:
            chunks.append("[Telegram mirror truncated.]")
    return chunks


def _telegram_windows_mirror_header(
    session: str,
    kind: str,
    *,
    state: str = "",
    current_command: str = "",
    part_index: int = 0,
    part_total: int = 0,
) -> str:
    label = "Codrex Windows mirror"
    if kind == "prompt":
        label = "Codrex Windows prompt"
    elif kind == "status":
        label = "Codrex Windows status"
    elif kind == "snapshot":
        label = "Codrex Windows snapshot"
    lines = [f"{label} for {session}"]
    if state:
        lines.append(f"State: {state}")
    if current_command:
        lines.append(f"Command: {current_command}")
    if part_total > 1 and part_index > 0:
        lines.append(f"Part: {part_index}/{part_total}")
    return "\n".join(lines)


def _telegram_windows_mirror_send_text(
    session: str,
    text: str,
    *,
    kind: str,
    state: str = "",
    current_command: str = "",
) -> bool:
    cleaned = _telegram_windows_mirror_clean_text(text)
    if not cleaned:
        return True
    if kind in {"snapshot", "replace"} and len(cleaned) > TELEGRAM_WINDOWS_MIRROR_SNAPSHOT_TAIL_CHARS:
        cleaned = cleaned[-TELEGRAM_WINDOWS_MIRROR_SNAPSHOT_TAIL_CHARS:].lstrip()
        cleaned = f"[Showing the latest snapshot tail]\n\n{cleaned}"
    chunks = _telegram_windows_mirror_split_text(cleaned, TELEGRAM_WINDOWS_MIRROR_MAX_CHARS)
    total = len(chunks)
    for index, chunk in enumerate(chunks, start=1):
        header = _telegram_windows_mirror_header(
            session,
            kind,
            state=state,
            current_command=current_command,
            part_index=index,
            part_total=total,
        )
        message = f"{header}\n\n{chunk}" if chunk else header
        result = _telegram_send_text(message)
        if not result.get("ok"):
            return False
    return True


def _telegram_windows_mirror_send_status(
    session: str,
    *,
    state: str = "",
    current_command: str = "",
    detail: str = "",
) -> bool:
    header = _telegram_windows_mirror_header(
        session,
        "status",
        state=state,
        current_command=current_command,
    )
    lines = [header]
    if detail:
        lines.append("")
        lines.append(detail)
    result = _telegram_send_text("\n".join(lines))
    return bool(result.get("ok"))


def _telegram_windows_mirror_session_snapshots() -> Tuple[Dict[str, Dict[str, Any]], Dict[str, Dict[str, Any]]]:
    session_meta: Dict[str, Dict[str, Any]] = {}
    stream_meta: Dict[str, Dict[str, Any]] = {}
    with WINDOWS_SESSIONS_LOCK:
        for session_id, raw in WINDOWS_SESSIONS.items():
            if str((raw or {}).get("profile") or "").strip().lower() != "codex":
                continue
            session_meta[session_id] = _windows_session_public_record(raw)
        for raw in WINDOWS_RECENT_CLOSED:
            if not isinstance(raw, dict):
                continue
            session_id = str(raw.get("session") or "").strip()
            if not session_id:
                continue
            if str(raw.get("profile") or "").strip().lower() != "codex":
                continue
            session_meta.setdefault(session_id, dict(raw))
    with WINDOWS_SESSION_STREAM_LOCK:
        for session_id in list(session_meta.keys()):
            raw = WINDOWS_SESSION_STREAM_STATES.get(session_id)
            if not isinstance(raw, dict):
                continue
            stream_meta[session_id] = {
                "seq": int(raw.get("seq") or 0),
                "last_text": str(raw.get("last_text") or ""),
                "events": [dict(item) for item in list(raw.get("events") or []) if isinstance(item, dict)],
                "updated_at": float(raw.get("updated_at") or 0.0),
            }
    return session_meta, stream_meta


def _telegram_windows_mirror_collect_events(
    session: str,
    stream_state: Dict[str, Any],
    session_state: Dict[str, Any],
    session_record: Dict[str, Any],
) -> Tuple[List[Dict[str, Any]], int]:
    current_seq = max(0, int(stream_state.get("seq") or 0))
    last_seq = max(0, int(session_state.get("windows_mirror_last_seq") or 0))
    if current_seq <= 0 or current_seq <= last_seq:
        return [], last_seq
    events = [dict(item) for item in list(stream_state.get("events") or []) if isinstance(item, dict)]
    oldest_seq = int(events[0].get("seq") or 0) if events else 0
    if last_seq <= 0 or not events or oldest_seq > last_seq + 1:
        return [
            {
                "session": session,
                "seq": current_seq,
                "type": "snapshot",
                "text": str(stream_state.get("last_text") or ""),
                "state": str(session_record.get("state") or ""),
                "current_command": str(session_record.get("current_command") or ""),
            }
        ], current_seq
    replay = [event for event in events if int(event.get("seq") or 0) > last_seq]
    return replay, current_seq


def _telegram_windows_mirror_sync_session(
    session: str,
    stream_state: Dict[str, Any],
    session_state: Dict[str, Any],
    session_record: Dict[str, Any],
) -> Tuple[bool, int, str]:
    events, target_seq = _telegram_windows_mirror_collect_events(session, stream_state, session_state, session_record)
    if target_seq <= int(session_state.get("windows_mirror_last_seq") or 0):
        return True, int(session_state.get("windows_mirror_last_seq") or 0), ""
    if not events:
        return True, target_seq, ""
    aggregate_kind = ""
    aggregate_state = str(session_record.get("state") or "")
    aggregate_command = str(session_record.get("current_command") or "")
    aggregate_text = ""
    last_status = ""
    for event in events:
        event_type = str(event.get("type") or "").strip().lower()
        event_state = str(event.get("state") or aggregate_state or "").strip().lower()
        event_command = str(event.get("current_command") or aggregate_command or "").strip()
        if event_type == "status":
            if aggregate_text:
                ok = _telegram_windows_mirror_send_text(
                    session,
                    aggregate_text,
                    kind=aggregate_kind or "append",
                    state=aggregate_state,
                    current_command=aggregate_command,
                )
                if not ok:
                    return False, int(session_state.get("windows_mirror_last_seq") or 0), last_status
                aggregate_text = ""
                aggregate_kind = ""
            detail = str(event.get("detail") or "").strip()
            if detail or event_state:
                ok = _telegram_windows_mirror_send_status(
                    session,
                    state=event_state,
                    current_command=event_command,
                    detail=detail or "Session status changed.",
                )
                if not ok:
                    return False, int(session_state.get("windows_mirror_last_seq") or 0), last_status
                last_status = detail[:64]
            continue
        clean_text = _telegram_windows_mirror_clean_text(str(event.get("text") or ""))
        if event_type in {"snapshot", "replace"}:
            aggregate_kind = event_type
            aggregate_text = clean_text
            aggregate_state = event_state or aggregate_state
            aggregate_command = event_command or aggregate_command
            continue
        if event_type == "append" and clean_text:
            if aggregate_kind not in {"snapshot", "replace", "append"}:
                aggregate_kind = "append"
            aggregate_text += clean_text
            aggregate_state = event_state or aggregate_state
            aggregate_command = event_command or aggregate_command
    if aggregate_text:
        ok = _telegram_windows_mirror_send_text(
            session,
            aggregate_text,
            kind=aggregate_kind or "append",
            state=aggregate_state,
            current_command=aggregate_command,
        )
        if not ok:
            return False, int(session_state.get("windows_mirror_last_seq") or 0), last_status
    return True, target_seq, last_status


def _telegram_windows_mirror_send_prompt(session: str, prompt_text: str, current_command: str = "") -> None:
    with LOOP_CONTROL_LOCK:
        enabled = _telegram_windows_mirror_enabled_unlocked()
    if not enabled:
        return
    try:
        _telegram_windows_mirror_send_text(
            session,
            prompt_text,
            kind="prompt",
            state="sent",
            current_command=current_command or "codex",
        )
    except Exception:
        return


def _telegram_windows_mirror_once() -> None:
    with LOOP_CONTROL_LOCK:
        enabled = _telegram_windows_mirror_enabled_unlocked()
    if not enabled or not _telegram_enabled():
        return
    session_meta, stream_meta = _telegram_windows_mirror_session_snapshots()
    if not session_meta:
        return
    progress_updates: List[Tuple[str, int, str]] = []
    for session, session_record in session_meta.items():
        stream_state = stream_meta.get(session)
        if not stream_state:
            continue
        with LOOP_CONTROL_LOCK:
            loop_state = _get_loop_session_unlocked(session)
            prior_seq = int(loop_state.get("windows_mirror_last_seq") or 0)
        ok, next_seq, last_status = _telegram_windows_mirror_sync_session(
            session,
            stream_state,
            loop_state,
            session_record,
        )
        if ok and next_seq > prior_seq:
            progress_updates.append((session, next_seq, last_status))
    if not progress_updates:
        return
    with LOOP_CONTROL_LOCK:
        dirty = False
        for session, next_seq, last_status in progress_updates:
            loop_state = _get_loop_session_unlocked(session)
            prior_seq = int(loop_state.get("windows_mirror_last_seq") or 0)
            if next_seq <= prior_seq:
                continue
            loop_state["windows_mirror_last_seq"] = next_seq
            loop_state["windows_mirror_last_sent_at"] = _now_ms()
            if last_status:
                loop_state["windows_mirror_last_status"] = last_status[:64]
            _loop_commit_session_state_unlocked(session, loop_state)
            dirty = True
        if dirty:
            _persist_loop_control_unlocked()


def _loop_build_help_text() -> str:
    return "\n".join(
        [
            "Codrex loop controls:",
            "/help - show this help",
            "/list - list active Codex sessions and loop modes",
            "/status - show global loop settings",
            "/mode global infinite|await|checks|max1|max2|max3|off",
            "/mode <session> infinite|await|checks|max1|max2|max3|off|inherit",
            "/reply <session> <message> - send a prompt to one session",
            "Reply directly to a loop notification to continue that session.",
        ]
    )


def _loop_build_list_text() -> str:
    response = codex_sessions_live()
    sessions = response.get("sessions") if isinstance(response, dict) else []
    if not isinstance(sessions, list) or not sessions:
        return "No active Codex sessions."
    lines = ["Active Codex sessions:"]
    for raw in sessions[:24]:
        if not isinstance(raw, dict):
            continue
        session = str(raw.get("session") or "").strip()
        if not session:
            continue
        state = str(raw.get("state") or "").strip() or "unknown"
        loop_info = raw.get("loop") if isinstance(raw.get("loop"), dict) else {}
        preset = str(loop_info.get("effective_preset") or "").strip()
        awaiting = bool(loop_info.get("awaiting_reply"))
        mode_label = _format_loop_preset_label(preset) if preset else "Off"
        if awaiting:
            mode_label += " / waiting for reply"
        lines.append(f"- {session}: {state} | {mode_label}")
    return "\n".join(lines[:40])


def _loop_build_status_text() -> str:
    with LOOP_CONTROL_LOCK:
        settings = _public_loop_settings_unlocked()
        worker = dict(LOOP_CONTROL_DATA.get("worker") or {})
    global_label = _format_loop_preset_label(str(settings.get("global_preset") or ""))
    checks = settings.get("completion_checks") or []
    return "\n".join(
        [
            f"Global mode: {global_label}",
            f"Telegram configured: {'Yes' if settings.get('telegram_configured') else 'No'}",
            f"Windows mirror: {'On' if settings.get('telegram_windows_mirror_enabled') else 'Off'}",
            f"Completion checks: {len(checks)} command(s)",
            f"Worker alive: {'Yes' if worker.get('alive') else 'No'}",
            f"Default prompt: {_loop_limit_text(str(settings.get('default_prompt') or ''), 220)}",
        ]
    )


def _parse_loop_mode_token(raw: str) -> Optional[str]:
    value = str(raw or "").strip().lower()
    aliases = {
        "off": "off",
        "inherit": "inherit",
        "global": "inherit",
        "infinite": "infinite",
        "await": "await-reply",
        "await-reply": "await-reply",
        "checks": "completion-checks",
        "completion-checks": "completion-checks",
        "max1": "max-turns-1",
        "max2": "max-turns-2",
        "max3": "max-turns-3",
        "max-turns-1": "max-turns-1",
        "max-turns-2": "max-turns-2",
        "max-turns-3": "max-turns-3",
    }
    return aliases.get(value)


def _parse_loop_reply_command(text: str) -> Optional[Tuple[str, str]]:
    match = re.match(r"^/reply(?:@\w+)?\s+(\S+)\s+([\s\S]+)$", str(text or "").strip(), re.IGNORECASE)
    if not match:
        return None
    session = str(match.group(1) or "").strip()
    prompt_text = str(match.group(2) or "").strip()
    if not session or not prompt_text:
        return None
    return session, prompt_text


def _parse_loop_mode_command(text: str) -> Optional[Tuple[str, str]]:
    match = re.match(r"^/mode(?:@\w+)?\s+(\S+)\s+(\S+)$", str(text or "").strip(), re.IGNORECASE)
    if not match:
        return None
    target = str(match.group(1) or "").strip()
    mode = _parse_loop_mode_token(match.group(2) or "")
    if not target or mode is None:
        return None
    return target, mode


def _loop_build_notification_text(
    session: str,
    state: str,
    mode_label: str,
    snapshot: str,
    detail: str = "",
    include_reply_hint: bool = False,
) -> str:
    parts = [
        f"Codrex loop update for {session}",
        f"State: {state}",
        f"Mode: {mode_label}",
    ]
    if detail:
        parts.append(detail)
    compact_snapshot = _loop_limit_text(snapshot, 2000)
    if compact_snapshot:
        parts.extend(["", compact_snapshot])
    if include_reply_hint:
        parts.extend(["", "Reply to this message to continue the session."])
    return _loop_limit_text("\n".join(parts).strip(), 3800)


def _loop_build_continue_prompt(default_prompt: str, extra_detail: str = "") -> str:
    base = str(default_prompt or LOOP_CONTROL_DEFAULT_PROMPT).strip() or LOOP_CONTROL_DEFAULT_PROMPT
    extra = str(extra_detail or "").strip()
    if not extra:
        return base
    return f"{base}\n\n{extra}".strip()


def _loop_build_error_prompt(snapshot: str, default_prompt: str, state: str) -> str:
    extra_parts = [
        f"The session stopped in state '{state}'. Continue working from here.",
    ]
    compact_snapshot = _loop_limit_text(snapshot, 1800)
    if compact_snapshot:
        extra_parts.extend(["Latest terminal output:", compact_snapshot])
    return _loop_build_continue_prompt(default_prompt, "\n".join(extra_parts))


def _loop_run_completion_checks(cwd: str, commands: List[str]) -> Tuple[bool, List[Dict[str, Any]]]:
    clean_cwd = str(cwd or "").strip()
    if not clean_cwd.startswith("/"):
        return False, [{"command": "", "exit_code": -1, "output": "", "detail": "Session cwd is unavailable."}]
    results: List[Dict[str, Any]] = []
    all_passed = True
    for command in commands:
        wrapped = f"cd {_bash_quote(clean_cwd)} && {command}"
        run = run_wsl_bash(wrapped, timeout_s=LOOP_CONTROL_CHECK_TIMEOUT_S)
        output = str(run.get("stdout") or "")
        stderr = str(run.get("stderr") or "")
        detail_parts = []
        if output.strip():
            detail_parts.append(output.strip())
        if stderr.strip():
            detail_parts.append(stderr.strip())
        combined = _loop_limit_text("\n\n".join(detail_parts), 1800)
        exit_code = int(run.get("exit_code") or 0)
        if exit_code != 0:
            all_passed = False
        results.append(
            {
                "command": command,
                "exit_code": exit_code,
                "output": combined,
                "detail": str(run.get("error") or "").strip(),
            }
        )
    return all_passed, results


def _loop_build_failed_checks_prompt(
    default_prompt: str,
    cwd: str,
    results: List[Dict[str, Any]],
) -> str:
    lines = [
        f"Completion checks failed in {cwd}. Fix the issues and rerun these commands until they all pass:",
    ]
    for item in results:
        command = str(item.get("command") or "").strip()
        exit_code = int(item.get("exit_code") or 0)
        if exit_code == 0:
            continue
        lines.append(f"- {command} (exit {exit_code})")
        output = str(item.get("output") or "").strip()
        if output:
            lines.append(_loop_limit_text(output, 800))
    return _loop_build_continue_prompt(default_prompt, "\n".join(lines))


def _loop_commit_session_state_unlocked(session: str, state: Dict[str, Any]) -> Dict[str, Any]:
    session_id = _validate_session_name(session)
    normalized = _normalize_loop_session_state(state, session_id)
    sessions = LOOP_CONTROL_DATA.setdefault("sessions", {})
    if not isinstance(sessions, dict):
        sessions = {}
        LOOP_CONTROL_DATA["sessions"] = sessions
    sessions[session_id] = normalized
    return normalized


def _loop_set_session_action_unlocked(
    session: str,
    state: Dict[str, Any],
    action: str,
    detail: str,
    *,
    snapshot: str = "",
    persist: bool = True,
) -> Dict[str, Any]:
    now_ms = _now_ms()
    state["last_action"] = str(action or "").strip()[:64]
    state["last_action_detail"] = _loop_limit_text(detail, 4000)
    state["last_action_at"] = now_ms
    if snapshot:
        state["last_snapshot"] = _loop_limit_text(snapshot, 2000)
    normalized = _loop_commit_session_state_unlocked(session, state)
    if persist:
        _persist_loop_control_unlocked()
    return normalized


def _loop_set_global_preset_unlocked(preset: str) -> None:
    settings = _get_loop_settings_unlocked()
    next_preset = _normalize_loop_preset(preset)
    settings["global_preset"] = next_preset
    settings["updated_at"] = _now_ms()
    sessions = LOOP_CONTROL_DATA.get("sessions") if isinstance(LOOP_CONTROL_DATA.get("sessions"), dict) else {}
    for session, raw_state in list(sessions.items()):
        if not isinstance(raw_state, dict):
            continue
        state = _normalize_loop_session_state(raw_state, session)
        if state.get("override_mode") != "inherit":
            continue
        state["awaiting_reply"] = False
        state["last_handled_fingerprint"] = ""
        budget = _loop_budget_for_preset(next_preset)
        state["remaining_turns"] = budget if budget is not None else None
        _loop_commit_session_state_unlocked(session, state)
    _persist_loop_control_unlocked()


def _loop_set_session_override_unlocked(session: str, override_mode: str) -> Dict[str, Any]:
    state = _get_loop_session_unlocked(session)
    next_mode = _normalize_loop_override_mode(override_mode)
    state["override_mode"] = next_mode
    state["awaiting_reply"] = False
    state["last_handled_fingerprint"] = ""
    budget = _loop_budget_for_preset(next_mode)
    state["remaining_turns"] = budget if budget is not None else None
    state["last_action"] = ""
    state["last_action_detail"] = ""
    normalized = _loop_commit_session_state_unlocked(session, state)
    _persist_loop_control_unlocked()
    return normalized


def _loop_find_waiting_session_by_message_unlocked(message_id: int) -> str:
    if message_id <= 0:
        return ""
    sessions = LOOP_CONTROL_DATA.get("sessions") if isinstance(LOOP_CONTROL_DATA.get("sessions"), dict) else {}
    winner = ""
    newest = 0
    for session, raw_state in sessions.items():
        if not isinstance(raw_state, dict):
            continue
        state = _normalize_loop_session_state(raw_state, session)
        if not state.get("awaiting_reply"):
            continue
        if int(state.get("last_telegram_message_id") or 0) != int(message_id):
            continue
        at = int(state.get("last_notification_at") or 0)
        if at >= newest:
            newest = at
            winner = session
    return winner


def _loop_find_latest_waiting_session_unlocked() -> str:
    sessions = LOOP_CONTROL_DATA.get("sessions") if isinstance(LOOP_CONTROL_DATA.get("sessions"), dict) else {}
    winner = ""
    newest = 0
    for session, raw_state in sessions.items():
        if not isinstance(raw_state, dict):
            continue
        state = _normalize_loop_session_state(raw_state, session)
        if not state.get("awaiting_reply"):
            continue
        at = int(state.get("last_notification_at") or 0)
        if at >= newest:
            newest = at
            winner = session
    return winner


def _loop_send_prompt_to_session(session: str, prompt_text: str, *, auto_prompt: bool) -> Dict[str, Any]:
    result = codex_session_send(session, prompt_text)
    with LOOP_CONTROL_LOCK:
        state = _get_loop_session_unlocked(session)
        now_ms = _now_ms()
        state["awaiting_reply"] = False
        state["last_prompt_at"] = now_ms
        if auto_prompt:
            state["last_auto_prompt_at"] = now_ms
        _loop_commit_session_state_unlocked(session, state)
        _persist_loop_control_unlocked()
    return result


def _loop_process_reply_message(session: str, prompt_text: str, source_label: str) -> Dict[str, Any]:
    try:
        session_id = _validate_session_name(session)
    except HTTPException:
        return {"ok": False, "detail": f"Unknown session '{session}'."}
    prompt = str(prompt_text or "").strip()
    if not prompt:
        return {"ok": False, "detail": "Reply text is empty."}
    result = _loop_send_prompt_to_session(session_id, prompt, auto_prompt=False)
    with LOOP_CONTROL_LOCK:
        state = _get_loop_session_unlocked(session_id)
        state["awaiting_reply"] = False
        state["last_reply_at"] = _now_ms()
        state["last_handled_fingerprint"] = ""
        _loop_set_session_action_unlocked(
            session_id,
            state,
            "reply_received",
            f"Sent reply from {source_label}.",
            snapshot=prompt,
            persist=True,
        )
    return result


def _loop_handle_telegram_message(message: Dict[str, Any]) -> None:
    text = str(message.get("text") or "").strip()
    if not text:
        return

    command_name = ""
    if text.startswith("/"):
        match = re.match(r"^/([a-z0-9_]+)(?:@\w+)?", text, re.IGNORECASE)
        command_name = str(match.group(1) if match else "").strip().lower()

    if command_name == "help":
        _telegram_send_text(_loop_build_help_text())
        return
    if command_name == "list":
        _telegram_send_text(_loop_build_list_text())
        return
    if command_name == "status":
        _telegram_send_text(_loop_build_status_text())
        return

    mode_command = _parse_loop_mode_command(text)
    if mode_command:
        target, mode = mode_command
        with LOOP_CONTROL_LOCK:
            _load_loop_control_unlocked()
            if target.lower() == "global":
                _loop_set_global_preset_unlocked("" if mode == "off" else mode)
                response = _loop_build_status_text()
            else:
                try:
                    session_id = _validate_session_name(target)
                except HTTPException:
                    session_id = ""
                if not session_id:
                    response = f"Unknown session '{target}'."
                else:
                    override_mode = "inherit" if mode == "inherit" else ("off" if mode == "off" else mode)
                    _loop_set_session_override_unlocked(session_id, override_mode)
                    public = _public_loop_session_state_unlocked(session_id)
                    effective = str(public.get("effective_preset") or "")
                    mode_label = _format_loop_preset_label(effective) if effective else "Off"
                    response = f"{session_id}: override={public.get('override_mode')} effective={mode_label}"
        _telegram_send_text(_loop_limit_text(response, 3500))
        return

    reply_command = _parse_loop_reply_command(text)
    if reply_command:
        session, prompt_text = reply_command
        result = _loop_process_reply_message(session, prompt_text, "Telegram command")
        detail = "Reply sent." if result.get("ok") else (result.get("detail") or result.get("error") or "Reply failed.")
        _telegram_send_text(_loop_limit_text(detail, 3500))
        return

    target_session = ""
    with LOOP_CONTROL_LOCK:
        _load_loop_control_unlocked()
        reply_to_message_id = int(message.get("reply_to_message_id") or 0)
        if reply_to_message_id > 0:
            target_session = _loop_find_waiting_session_by_message_unlocked(reply_to_message_id)
        if not target_session:
            target_session = _loop_find_latest_waiting_session_unlocked()
    if not target_session:
        _telegram_send_text("No Codex session is currently waiting for a Telegram reply.")
        return
    result = _loop_process_reply_message(target_session, text, "Telegram reply")
    detail = (
        f"Sent reply to {target_session}."
        if result.get("ok")
        else (result.get("detail") or result.get("error") or f"Reply to {target_session} failed.")
    )
    _telegram_send_text(_loop_limit_text(detail, 3500))


def _loop_poll_telegram_once() -> None:
    token = str(TELEGRAM_BOT_TOKEN or "").strip()
    chat_id = _telegram_resolve_chat_id(allow_discovery=True) if token else ""
    if not token or not chat_id:
        with LOOP_CONTROL_LOCK:
            _load_loop_control_unlocked()
            worker = LOOP_CONTROL_DATA.setdefault("worker", {})
            worker["last_telegram_poll_at"] = _now_ms()
        return

    with LOOP_CONTROL_LOCK:
        settings = _get_loop_settings_unlocked()
        offset = int(settings.get("telegram_update_offset") or 0)

    if offset <= 0:
        parsed = _telegram_get_updates(token, limit=20)
        items = parsed.get("result") if isinstance(parsed, dict) else []
        newest = 0
        if isinstance(items, list):
            for raw in items:
                if isinstance(raw, dict):
                    newest = max(newest, int(raw.get("update_id") or 0))
        with LOOP_CONTROL_LOCK:
            settings = _get_loop_settings_unlocked()
            settings["telegram_update_offset"] = newest
            worker = LOOP_CONTROL_DATA.setdefault("worker", {})
            worker["last_telegram_poll_at"] = _now_ms()
            _persist_loop_control_unlocked()
        return

    parsed = _telegram_get_updates(token, offset=offset + 1, limit=20)
    items = parsed.get("result") if isinstance(parsed, dict) else []
    newest = offset
    if isinstance(items, list):
        for raw in items:
            if not isinstance(raw, dict):
                continue
            newest = max(newest, int(raw.get("update_id") or 0))
            message = _loop_extract_telegram_message(raw)
            if not message:
                continue
            if str(message.get("chat_id") or "").strip() != chat_id:
                continue
            _loop_handle_telegram_message(message)
    with LOOP_CONTROL_LOCK:
        settings = _get_loop_settings_unlocked()
        settings["telegram_update_offset"] = newest
        worker = LOOP_CONTROL_DATA.setdefault("worker", {})
        worker["last_telegram_poll_at"] = _now_ms()
        _persist_loop_control_unlocked()


def _loop_sync_budget_unlocked(session: str, state: Dict[str, Any], effective_preset: str, session_prompt_at_ms: int) -> None:
    budget = _loop_budget_for_preset(effective_preset)
    if budget is None:
        state["remaining_turns"] = None
        state["last_prompt_at"] = session_prompt_at_ms
        _loop_commit_session_state_unlocked(session, state)
        return
    previous_prompt_at = int(state.get("last_prompt_at") or 0)
    last_auto_prompt_at = int(state.get("last_auto_prompt_at") or 0)
    if state.get("remaining_turns") is None:
        state["remaining_turns"] = budget
    if session_prompt_at_ms > 0 and session_prompt_at_ms != previous_prompt_at and session_prompt_at_ms != last_auto_prompt_at:
        state["remaining_turns"] = budget
    state["last_prompt_at"] = session_prompt_at_ms
    _loop_commit_session_state_unlocked(session, state)


def _loop_handle_terminal_session(session_item: Dict[str, Any], session_record: Dict[str, Any]) -> None:
    session = _validate_session_name(session_item.get("session"))
    state_name = str(session_item.get("state") or "").strip().lower()
    snapshot = _loop_snapshot_text_from_session_record(session_record)
    session_prompt_at_ms = 0
    try:
        session_prompt_at_ms = int(float(session_record.get("last_prompt_at") or 0) * 1000)
    except Exception:
        session_prompt_at_ms = 0

    with LOOP_CONTROL_LOCK:
        loop_state = _get_loop_session_unlocked(session)
        effective_preset = _effective_loop_preset_unlocked(session)
        _loop_sync_budget_unlocked(session, loop_state, effective_preset, session_prompt_at_ms)
        fingerprint_source = "\n".join([session, state_name, snapshot, str(session_prompt_at_ms), effective_preset])
        fingerprint = hashlib.sha1(fingerprint_source.encode("utf-8", errors="ignore")).hexdigest()
        if fingerprint == str(loop_state.get("last_handled_fingerprint") or ""):
            return
        loop_state["last_terminal_state"] = state_name
        loop_state["last_terminal_at"] = _now_ms()
        loop_state["last_snapshot"] = _loop_limit_text(snapshot, 2000)
        loop_state["last_handled_fingerprint"] = fingerprint
        settings = _get_loop_settings_unlocked()
        default_prompt = str(settings.get("default_prompt") or LOOP_CONTROL_DEFAULT_PROMPT)
        completion_checks = list(settings.get("completion_checks") or [])
        _loop_commit_session_state_unlocked(session, loop_state)
        _persist_loop_control_unlocked()

    if state_name in LOOP_WAITING_STATES or effective_preset == "await-reply":
        telegram_result = _telegram_send_text(
            _loop_build_notification_text(
                session,
                state_name or "waiting",
                _format_loop_preset_label(effective_preset),
                snapshot,
                (
                    "Codex is waiting for your reply."
                    if state_name in LOOP_WAITING_STATES
                    else "Codex stopped and is waiting for your next instruction."
                ),
                include_reply_hint=True,
            )
        )
        with LOOP_CONTROL_LOCK:
            loop_state = _get_loop_session_unlocked(session)
            loop_state["awaiting_reply"] = bool(telegram_result.get("ok"))
            if telegram_result.get("ok"):
                loop_state["last_notification_at"] = _now_ms()
                loop_state["last_telegram_message_id"] = int(telegram_result.get("message_id") or 0)
            _loop_set_session_action_unlocked(
                session,
                loop_state,
                "awaiting_reply",
                (
                    "Waiting for a Telegram reply."
                    if telegram_result.get("ok")
                    else (telegram_result.get("detail") or telegram_result.get("error") or "Telegram notification failed.")
                ),
                snapshot=snapshot,
                persist=True,
            )
        return

    if state_name not in LOOP_TERMINAL_STATES:
        return

    if not effective_preset:
        with LOOP_CONTROL_LOCK:
            loop_state = _get_loop_session_unlocked(session)
            loop_state["awaiting_reply"] = False
            _loop_set_session_action_unlocked(
                session,
                loop_state,
                "stopped",
                "Loop mode is off for this session.",
                snapshot=snapshot,
                persist=True,
            )
        return

    if state_name == "error":
        prompt = _loop_build_error_prompt(snapshot, default_prompt, state_name)
        send_result = _loop_send_prompt_to_session(session, prompt, auto_prompt=True)
        with LOOP_CONTROL_LOCK:
            loop_state = _get_loop_session_unlocked(session)
            if send_result.get("ok"):
                loop_state["last_continue_at"] = _now_ms()
            _loop_set_session_action_unlocked(
                session,
                loop_state,
                "auto_continue_error",
                "Continued after an error state." if send_result.get("ok") else (send_result.get("detail") or send_result.get("error") or "Auto-continue failed."),
                snapshot=snapshot,
                persist=True,
            )
        return

    if effective_preset == "completion-checks":
        all_passed, results = _loop_run_completion_checks(str(session_item.get("cwd") or session_record.get("cwd") or ""), completion_checks)
        if completion_checks and all_passed:
            telegram_result = _telegram_send_text(
                _loop_build_notification_text(
                    session,
                    state_name,
                    _format_loop_preset_label(effective_preset),
                    snapshot,
                    "Completion checks passed.",
                    include_reply_hint=False,
                )
            )
            with LOOP_CONTROL_LOCK:
                loop_state = _get_loop_session_unlocked(session)
                if telegram_result.get("ok"):
                    loop_state["last_notification_at"] = _now_ms()
                _loop_set_session_action_unlocked(
                    session,
                    loop_state,
                    "completion_checks_passed",
                    "Completion checks passed.",
                    snapshot=snapshot,
                    persist=True,
                )
            return
        if not completion_checks:
            prompt = _loop_build_continue_prompt(
                default_prompt,
                "Completion checks mode is enabled, but no commands are configured yet. Continue and finish the task before stopping.",
            )
        else:
            prompt = _loop_build_failed_checks_prompt(
                default_prompt,
                str(session_item.get("cwd") or session_record.get("cwd") or ""),
                results,
            )
        send_result = _loop_send_prompt_to_session(session, prompt, auto_prompt=True)
        with LOOP_CONTROL_LOCK:
            loop_state = _get_loop_session_unlocked(session)
            if send_result.get("ok"):
                loop_state["last_continue_at"] = _now_ms()
            _loop_set_session_action_unlocked(
                session,
                loop_state,
                "completion_checks_continue",
                (
                    "Completion checks failed; sent follow-up prompt."
                    if completion_checks
                    else "Completion checks are not configured; sent follow-up prompt."
                )
                if send_result.get("ok")
                else (send_result.get("detail") or send_result.get("error") or "Follow-up prompt failed."),
                snapshot=snapshot,
                persist=True,
            )
        return

    if effective_preset.startswith("max-turns-"):
        with LOOP_CONTROL_LOCK:
            loop_state = _get_loop_session_unlocked(session)
            try:
                remaining_turns = int(loop_state.get("remaining_turns") or 0)
            except Exception:
                remaining_turns = 0
        if remaining_turns <= 0:
            telegram_result = _telegram_send_text(
                _loop_build_notification_text(
                    session,
                    state_name,
                    _format_loop_preset_label(effective_preset),
                    snapshot,
                    "Max-turns budget is exhausted.",
                    include_reply_hint=False,
                )
            )
            with LOOP_CONTROL_LOCK:
                loop_state = _get_loop_session_unlocked(session)
                if telegram_result.get("ok"):
                    loop_state["last_notification_at"] = _now_ms()
                _loop_set_session_action_unlocked(
                    session,
                    loop_state,
                    "max_turns_exhausted",
                    "Max-turns budget is exhausted.",
                    snapshot=snapshot,
                    persist=True,
                )
            return
        send_result = _loop_send_prompt_to_session(session, default_prompt, auto_prompt=True)
        with LOOP_CONTROL_LOCK:
            loop_state = _get_loop_session_unlocked(session)
            if send_result.get("ok"):
                loop_state["remaining_turns"] = max(0, remaining_turns - 1)
                loop_state["last_continue_at"] = _now_ms()
            _loop_set_session_action_unlocked(
                session,
                loop_state,
                "auto_continue",
                (
                    f"Sent follow-up prompt. Remaining turns: {loop_state.get('remaining_turns')}"
                    if send_result.get("ok")
                    else (send_result.get("detail") or send_result.get("error") or "Auto-continue failed.")
                ),
                snapshot=snapshot,
                persist=True,
            )
        return

    send_result = _loop_send_prompt_to_session(session, default_prompt, auto_prompt=True)
    with LOOP_CONTROL_LOCK:
        loop_state = _get_loop_session_unlocked(session)
        if send_result.get("ok"):
            loop_state["last_continue_at"] = _now_ms()
        _loop_set_session_action_unlocked(
            session,
            loop_state,
            "auto_continue",
            "Sent follow-up prompt." if send_result.get("ok") else (send_result.get("detail") or send_result.get("error") or "Auto-continue failed."),
            snapshot=snapshot,
            persist=True,
        )


def _loop_control_worker() -> None:
    while True:
        try:
            _loop_poll_telegram_once()
            _telegram_windows_mirror_once()
            response = codex_sessions_live()
            sessions = response.get("sessions") if isinstance(response, dict) else []
            session_records: Dict[str, Dict[str, Any]] = {}
            with SESSIONS_LOCK:
                for item in sessions if isinstance(sessions, list) else []:
                    if not isinstance(item, dict):
                        continue
                    session = str(item.get("session") or "").strip()
                    if not session:
                        continue
                    session_records[session] = dict(SESSIONS.get(session, {}))
            for item in sessions if isinstance(sessions, list) else []:
                if not isinstance(item, dict):
                    continue
                session = str(item.get("session") or "").strip()
                if not session:
                    continue
                _loop_handle_terminal_session(item, session_records.get(session, {}))
            with LOOP_CONTROL_LOCK:
                _load_loop_control_unlocked()
                worker = LOOP_CONTROL_DATA.setdefault("worker", {})
                worker["alive"] = True
                worker["last_cycle_at"] = _now_ms()
                worker["last_error"] = ""
                worker["last_error_at"] = 0
        except Exception as exc:
            with LOOP_CONTROL_LOCK:
                _load_loop_control_unlocked()
                worker = LOOP_CONTROL_DATA.setdefault("worker", {})
                worker["alive"] = True
                worker["last_cycle_at"] = _now_ms()
                worker["last_error"] = f"{type(exc).__name__}: {exc}"
                worker["last_error_at"] = _now_ms()
        time.sleep(max(1.0, LOOP_CONTROL_POLL_INTERVAL_S))


def _ensure_loop_control_worker() -> None:
    global LOOP_CONTROL_WORKER_THREAD
    existing = LOOP_CONTROL_WORKER_THREAD
    if existing and existing.is_alive():
        return
    worker = threading.Thread(
        target=_loop_control_worker,
        name="codrex-loop-control",
        daemon=True,
    )
    LOOP_CONTROL_WORKER_THREAD = worker
    worker.start()


def _overlay_cursor_rgb(rgb_bytes: bytes, size: Tuple[int, int], x: int, y: int) -> bytes:
    """
    MSS screenshots typically do not include the OS cursor. For mobile remote control,
    we overlay a visible cursor marker into the PNG bytes.
    """
    w, h = int(size[0]), int(size[1])
    if not rgb_bytes or w <= 0 or h <= 0:
        return rgb_bytes
    expected = w * h * 3
    if len(rgb_bytes) < expected:
        return rgb_bytes

    buf = bytearray(rgb_bytes)

    def set_px(px: int, py: int, r: int, g: int, b: int) -> None:
        if px < 0 or py < 0 or px >= w or py >= h:
            return
        i = (py * w + px) * 3
        buf[i] = r
        buf[i + 1] = g
        buf[i + 2] = b

    cx, cy = int(x), int(y)
    if cx < 0 or cy < 0 or cx >= w or cy >= h:
        return rgb_bytes

    # Outer black crosshair for contrast on bright backgrounds.
    for i in range(-12, 13):
        for t in (-1, 0, 1):
            set_px(cx + i, cy + t, 0, 0, 0)
            set_px(cx + t, cy + i, 0, 0, 0)

    # Inner cyan crosshair.
    for i in range(-10, 11):
        set_px(cx + i, cy, 0, 255, 255)
        set_px(cx, cy + i, 0, 255, 255)

    # Center red dot.
    for dx in (-1, 0, 1):
        for dy in (-1, 0, 1):
            set_px(cx + dx, cy + dy, 255, 0, 0)

    return bytes(buf)


def _desktop_cursor_pos() -> Optional[Tuple[int, int]]:
    if os.name != "nt":
        return None
    user32 = _win_user32()
    try:
        pt = wintypes.POINT()
        ok = user32.GetCursorPos(ctypes.byref(pt))
        if not ok:
            return None
        return int(pt.x), int(pt.y)
    except Exception:
        return None


def _desktop_capture_probe(scale_factor: int = 6) -> Dict[str, Any]:
    try:
        rgb, out_size = _desktop_capture_rgb(scale_factor=scale_factor, grayscale=True)
        if not rgb:
            return {
                "ok": True,
                "width": int(out_size[0]),
                "height": int(out_size[1]),
                "avg_luma": 0.0,
                "non_black": False,
            }
        step = max(1, len(rgb) // 2048)
        sample = rgb[::step]
        avg_luma = (float(sum(sample)) / float(len(sample))) if sample else 0.0
        non_black = any(int(value) > 12 for value in sample)
        return {
            "ok": True,
            "width": int(out_size[0]),
            "height": int(out_size[1]),
            "avg_luma": round(avg_luma, 2),
            "non_black": bool(non_black),
        }
    except Exception as exc:
        return {
            "ok": False,
            "error": f"{type(exc).__name__}: {exc}",
        }


def _desktop_run_remote_action(
    action_name: str,
    callback: Callable[[], Any],
    *,
    capture_probe: bool = False,
) -> Tuple[Any, Dict[str, Any]]:
    active_target_id = ""
    try:
        active_target_id = str(_desktop_targets_payload().get("active_target", {}).get("id") or "").strip()
    except Exception:
        active_target_id = ""
    diagnostics: Dict[str, Any] = {
        "action": str(action_name or "").strip() or "desktop_action",
        "capture_backend": _desktop_capture_backend(),
        "active_target_id": active_target_id,
    }
    try:
        result = callback()
        if capture_probe:
            diagnostics["capture_probe"] = _desktop_capture_probe()
        return result, diagnostics
    finally:
        if capture_probe:
            print(
                f"Desktop remote action={diagnostics.get('action')} diag={json.dumps(diagnostics, ensure_ascii=False)}",
                flush=True,
            )

ULONG_PTR = getattr(wintypes, "ULONG_PTR", ctypes.c_size_t)

INPUT_MOUSE = 0
INPUT_KEYBOARD = 1
INPUT_HARDWARE = 2

MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004
MOUSEEVENTF_RIGHTDOWN = 0x0008
MOUSEEVENTF_RIGHTUP = 0x0010
MOUSEEVENTF_MIDDLEDOWN = 0x0020
MOUSEEVENTF_MIDDLEUP = 0x0040
MOUSEEVENTF_MOVE = 0x0001
MOUSEEVENTF_WHEEL = 0x0800
MOUSEEVENTF_VIRTUALDESK = 0x4000
MOUSEEVENTF_ABSOLUTE = 0x8000
REMOTE_MOUSE_EXTRA_INFO = 0x434F445245584D31

KEYEVENTF_EXTENDEDKEY = 0x0001
KEYEVENTF_KEYUP = 0x0002
KEYEVENTF_UNICODE = 0x0004

VK_BACK = 0x08
VK_TAB = 0x09
VK_RETURN = 0x0D
VK_ESCAPE = 0x1B
VK_SHIFT = 0x10
VK_DELETE = 0x2E
VK_SPACE = 0x20

VK_CONTROL = 0x11
VK_MENU = 0x12  # Alt
VK_LWIN = 0x5B
VK_HOME = 0x24
VK_END = 0x23
VK_PRIOR = 0x21  # Page Up
VK_NEXT = 0x22   # Page Down
VK_LEFT = 0x25
VK_UP = 0x26
VK_RIGHT = 0x27
VK_DOWN = 0x28
VK_F5 = 0x74

WM_MOUSEMOVE = 0x0200
WM_LBUTTONDOWN = 0x0201
WM_LBUTTONUP = 0x0202
WM_RBUTTONDOWN = 0x0204
WM_RBUTTONUP = 0x0205
WM_MBUTTONDOWN = 0x0207
WM_MBUTTONUP = 0x0208
WM_NCHITTEST = 0x0084
WM_NCLBUTTONDOWN = 0x00A1
WM_NCLBUTTONUP = 0x00A2
WM_NCRBUTTONDOWN = 0x00A4
WM_NCRBUTTONUP = 0x00A5
WM_NCMBUTTONDOWN = 0x00A7
WM_NCMBUTTONUP = 0x00A8
WM_SYSCOMMAND = 0x0112

MK_LBUTTON = 0x0001
MK_RBUTTON = 0x0002
MK_MBUTTON = 0x0010

HTNOWHERE = 0
HTCLIENT = 1
HTCAPTION = 2
HTMINBUTTON = 8
HTMAXBUTTON = 9
HTCLOSE = 20

SC_MINIMIZE = 0xF020
SC_MAXIMIZE = 0xF030
SC_RESTORE = 0xF120
SC_CLOSE = 0xF060

GA_ROOT = 2
GW_HWNDNEXT = 2
DWMWA_CLOAKED = 14


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ("dx", wintypes.LONG),
        ("dy", wintypes.LONG),
        ("mouseData", wintypes.DWORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ULONG_PTR),
    ]


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk", wintypes.WORD),
        ("wScan", wintypes.WORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ULONG_PTR),
    ]


class HARDWAREINPUT(ctypes.Structure):
    _fields_ = [
        ("uMsg", wintypes.DWORD),
        ("wParamL", wintypes.WORD),
        ("wParamH", wintypes.WORD),
    ]


class INPUT_UNION(ctypes.Union):
    _fields_ = [
        ("mi", MOUSEINPUT),
        ("ki", KEYBDINPUT),
        ("hi", HARDWAREINPUT),
    ]


class INPUT(ctypes.Structure):
    _fields_ = [
        ("type", wintypes.DWORD),
        ("union", INPUT_UNION),
    ]


def _win_send_input() -> Any:
    _ensure_windows_host()
    user32 = _win_user32()
    if not hasattr(_win_send_input, "_configured"):
        user32.SendInput.argtypes = [wintypes.UINT, ctypes.POINTER(INPUT), ctypes.c_int]
        user32.SendInput.restype = wintypes.UINT
        _win_send_input._configured = True  # type: ignore[attr-defined]
    return user32.SendInput


def _win_vk_key_scan() -> Any:
    _ensure_windows_host()
    user32 = _win_user32()
    if not hasattr(_win_vk_key_scan, "_configured"):
        user32.VkKeyScanW.argtypes = [wintypes.WCHAR]
        user32.VkKeyScanW.restype = ctypes.c_short
        _win_vk_key_scan._configured = True  # type: ignore[attr-defined]
    return user32.VkKeyScanW


def _send_inputs(inputs: List[INPUT]) -> None:
    send_input = _win_send_input()
    arr = (INPUT * len(inputs))(*inputs)
    sent = int(send_input(len(inputs), arr, ctypes.sizeof(INPUT)))
    if sent != len(inputs):
        raise HTTPException(status_code=500, detail="Failed to send keyboard input.")


def _send_vk(vk: int, extended: bool = False) -> None:
    flags = KEYEVENTF_EXTENDEDKEY if extended else 0
    down = INPUT(type=INPUT_KEYBOARD, union=INPUT_UNION(ki=KEYBDINPUT(wVk=vk, wScan=0, dwFlags=flags, time=0, dwExtraInfo=0)))
    up = INPUT(type=INPUT_KEYBOARD, union=INPUT_UNION(ki=KEYBDINPUT(wVk=vk, wScan=0, dwFlags=flags | KEYEVENTF_KEYUP, time=0, dwExtraInfo=0)))
    _send_inputs([down, up])

def _send_vk_down(vk: int, extended: bool = False) -> None:
    flags = KEYEVENTF_EXTENDEDKEY if extended else 0
    down = INPUT(type=INPUT_KEYBOARD, union=INPUT_UNION(ki=KEYBDINPUT(wVk=vk, wScan=0, dwFlags=flags, time=0, dwExtraInfo=0)))
    _send_inputs([down])

def _send_vk_up(vk: int, extended: bool = False) -> None:
    flags = (KEYEVENTF_EXTENDEDKEY if extended else 0) | KEYEVENTF_KEYUP
    up = INPUT(type=INPUT_KEYBOARD, union=INPUT_UNION(ki=KEYBDINPUT(wVk=vk, wScan=0, dwFlags=flags, time=0, dwExtraInfo=0)))
    _send_inputs([up])

def _send_vk_repeat(vk: int, count: int, extended: bool = False) -> None:
    n = int(count)
    if n <= 0:
        return
    if n > 200:
        raise HTTPException(status_code=400, detail="Key repeat too large (max 200).")
    flags = KEYEVENTF_EXTENDEDKEY if extended else 0
    inputs: List[INPUT] = []
    for _ in range(n):
        down = INPUT(type=INPUT_KEYBOARD, union=INPUT_UNION(ki=KEYBDINPUT(wVk=vk, wScan=0, dwFlags=flags, time=0, dwExtraInfo=0)))
        up = INPUT(type=INPUT_KEYBOARD, union=INPUT_UNION(ki=KEYBDINPUT(wVk=vk, wScan=0, dwFlags=flags | KEYEVENTF_KEYUP, time=0, dwExtraInfo=0)))
        inputs.append(down)
        inputs.append(up)
    _send_inputs(inputs)


def _send_vk_combo(modifiers: List[int], vk: int, extended: bool = False) -> None:
    """
    Send modifier combo reliably with native SendInput.
    Example: Ctrl+A -> modifiers=[VK_CONTROL], vk=0x41
    """
    seq: List[INPUT] = []
    for mod in modifiers:
        seq.append(INPUT(type=INPUT_KEYBOARD, union=INPUT_UNION(ki=KEYBDINPUT(wVk=mod, wScan=0, dwFlags=0, time=0, dwExtraInfo=0))))
    flags = KEYEVENTF_EXTENDEDKEY if extended else 0
    seq.append(INPUT(type=INPUT_KEYBOARD, union=INPUT_UNION(ki=KEYBDINPUT(wVk=vk, wScan=0, dwFlags=flags, time=0, dwExtraInfo=0))))
    seq.append(INPUT(type=INPUT_KEYBOARD, union=INPUT_UNION(ki=KEYBDINPUT(wVk=vk, wScan=0, dwFlags=flags | KEYEVENTF_KEYUP, time=0, dwExtraInfo=0))))
    for mod in reversed(modifiers):
        seq.append(INPUT(type=INPUT_KEYBOARD, union=INPUT_UNION(ki=KEYBDINPUT(wVk=mod, wScan=0, dwFlags=KEYEVENTF_KEYUP, time=0, dwExtraInfo=0))))
    _send_inputs(seq)


def _resolve_char_key(char: str) -> Optional[Tuple[int, List[int]]]:
    value = str(char or "")
    if len(value) != 1:
        return None
    try:
        scan = int(_win_vk_key_scan()(value))
    except Exception:
        return None
    if scan == -1:
        return None
    vk = scan & 0xFF
    shift_state = (scan >> 8) & 0xFF
    modifiers: List[int] = []
    if shift_state & 1:
        modifiers.append(VK_SHIFT)
    if shift_state & 2:
        modifiers.append(VK_CONTROL)
    if shift_state & 4:
        modifiers.append(VK_MENU)
    return vk, modifiers


def _send_char_key(char: str) -> bool:
    resolved = _resolve_char_key(char)
    if resolved is None:
        return False
    vk, modifiers = resolved
    if modifiers:
        _send_vk_combo(modifiers, vk)
    else:
        _send_vk(vk)
    return True


def _send_unicode_text(text: str) -> None:
    if not text:
        return
    # Send UTF-16 code units to support characters outside the BMP (surrogate pairs).
    data = text.encode("utf-16-le", errors="strict")
    inputs: List[INPUT] = []
    for i in range(0, len(data), 2):
        code_unit = int.from_bytes(data[i:i + 2], "little")
        down = INPUT(type=INPUT_KEYBOARD, union=INPUT_UNION(ki=KEYBDINPUT(wVk=0, wScan=code_unit, dwFlags=KEYEVENTF_UNICODE, time=0, dwExtraInfo=0)))
        up = INPUT(type=INPUT_KEYBOARD, union=INPUT_UNION(ki=KEYBDINPUT(wVk=0, wScan=code_unit, dwFlags=KEYEVENTF_UNICODE | KEYEVENTF_KEYUP, time=0, dwExtraInfo=0)))
        inputs.append(down)
        inputs.append(up)
    _send_inputs(inputs)


def _iter_text_chunks(text: str, chunk_size: int):
    size = max(1, int(chunk_size or 1))
    for start in range(0, len(text), size):
        yield text[start:start + size]


def _send_unicode_text_chunked(text: str, chunk_size: int = 240) -> int:
    sent = 0
    for chunk in _iter_text_chunks(text, chunk_size):
        _send_unicode_text(chunk)
        sent += len(chunk)
    return sent


def _send_text_native_first(text: str, unicode_chunk_size: int = 240) -> int:
    """
    Prefer native VK-based key events for text so the input behaves like real typing.
    Fall back to Unicode injection only for characters that cannot be mapped by VkKeyScanW.
    This keeps remote typing close to real keyboard behavior for desktop apps and shell UI.
    """
    value = str(text or "")
    if not value:
        return 0

    sent = 0
    unicode_buffer: List[str] = []

    def flush_unicode_buffer() -> None:
        nonlocal sent
        if not unicode_buffer:
            return
        chunk = "".join(unicode_buffer)
        sent += _send_unicode_text_chunked(chunk, chunk_size=unicode_chunk_size)
        unicode_buffer.clear()

    for char in value:
        resolved = _resolve_char_key(char)
        if resolved is not None:
            flush_unicode_buffer()
            vk, modifiers = resolved
            if modifiers:
                _send_vk_combo(modifiers, vk)
            else:
                _send_vk(vk)
            sent += 1
        else:
            unicode_buffer.append(char)

    flush_unicode_buffer()
    return sent

# -------------------------
# Live codex session state
# -------------------------
SESSIONS_LOCK = threading.Lock()
SESSIONS: Dict[str, Dict[str, Any]] = {}
WINDOWS_RUNTIME_LOCK = threading.Lock()
WINDOWS_RUNTIME_ACTIVE = bool(WINPTY_AVAILABLE and os.name == "nt")
WINDOWS_SUPPORTED_PROFILES = {"codex", "powershell", "cmd"}
WINDOWS_CODEX_PROFILE_LOCK = threading.Lock()
WINDOWS_CODEX_PROFILE_STATUS: Dict[str, Any] = {
    "supported": None,
    "detail": "",
    "checked_at": 0.0,
}
WINDOWS_SESSION_BACKGROUND_MODE = "selected_only"
WINDOWS_SESSION_OUTPUT_MAX_CHARS = int(os.environ.get("CODEX_WINDOWS_SESSION_OUTPUT_MAX_CHARS", "60000") or "60000")
WINDOWS_SESSION_STREAM_REPLAY_MAX = int(os.environ.get("CODEX_WINDOWS_SESSION_STREAM_REPLAY_MAX", "240") or "240")
WINDOWS_SESSION_RECENT_CLOSED_MAX = int(os.environ.get("CODEX_WINDOWS_SESSION_RECENT_CLOSED_MAX", "24") or "24")
WINDOWS_SESSIONS_LOCK = threading.Lock()
WINDOWS_SESSIONS: Dict[str, Dict[str, Any]] = {}
WINDOWS_RECENT_CLOSED: List[Dict[str, Any]] = []
WINDOWS_SESSION_STREAM_LOCK = threading.Lock()
WINDOWS_SESSION_STREAM_STATES: Dict[str, Dict[str, Any]] = {}
DESKTOP_CODEX_HOME = os.path.join(os.path.expanduser("~"), ".codex")
DESKTOP_CODEX_STATE_DB = os.path.join(DESKTOP_CODEX_HOME, "state_5.sqlite")
DESKTOP_CODEX_TRANSCRIPT_MAX_CHARS = int(
    os.environ.get("CODEX_DESKTOP_TRANSCRIPT_MAX_CHARS", "140000") or "140000"
)
DESKTOP_CODEX_ROLLOUT_TAIL_BYTES = int(
    os.environ.get("CODEX_DESKTOP_ROLLOUT_TAIL_BYTES", "32768") or "32768"
)
DESKTOP_CODEX_STALE_BUSY_SECONDS = max(
    15.0,
    float(os.environ.get("CODEX_DESKTOP_STALE_BUSY_SECONDS", "120") or "120"),
)
DESKTOP_CODEX_STREAM_POLL_SECONDS = max(
    0.4,
    float(os.environ.get("CODEX_DESKTOP_STREAM_POLL_SECONDS", "1.2") or "1.2"),
)
DESKTOP_CODEX_WSL_REAL_CODEX = str(
    os.environ.get("CODEX_DESKTOP_WSL_REAL_CODEX") or "/home/megha/.local/nodejs/v22.22.0/bin/codex"
).strip()
DESKTOP_CODEX_WSL_NODE_BIN = str(
    os.environ.get("CODEX_DESKTOP_WSL_NODE_BIN") or os.path.dirname(DESKTOP_CODEX_WSL_REAL_CODEX)
).strip()
DESKTOP_CODEX_WINDOWS_APPS_GLOB = os.environ.get(
    "CODEX_DESKTOP_WINDOWS_APPS_GLOB",
    r"C:\Program Files\WindowsApps\OpenAI.Codex_*_x64__2p2nqsd0c76g0\app\resources\codex.exe",
).strip()
DESKTOP_CODEX_WINDOWS_CLI_CACHE_DIR = os.path.join(CODEX_RUNTIME_DIR, "desktop-codex-win-cli")
DESKTOP_CODEX_WINDOWS_CLI_CACHE_PATH = os.path.join(DESKTOP_CODEX_WINDOWS_CLI_CACHE_DIR, "codex-app-server.exe")
DESKTOP_CODEX_APP_SERVER_START_TIMEOUT_SECONDS = max(
    4.0,
    float(os.environ.get("CODEX_DESKTOP_APP_SERVER_START_TIMEOUT_SECONDS", "15") or "15"),
)
DESKTOP_CODEX_APP_SERVER_RPC_TIMEOUT_SECONDS = max(
    3.0,
    float(os.environ.get("CODEX_DESKTOP_APP_SERVER_RPC_TIMEOUT_SECONDS", "45") or "45"),
)
DESKTOP_CODEX_JOB_LOCK = threading.Lock()
DESKTOP_CODEX_JOBS: Dict[str, Dict[str, Any]] = {}
DESKTOP_CODEX_APP_SERVER_LOCK = threading.Lock()
DESKTOP_CODEX_APP_SERVER: Dict[str, Any] = {}

def _validate_session_name(name: str) -> str:
    if not VALID_NAME_RE.fullmatch(name or ""):
        raise HTTPException(status_code=400, detail="Invalid session name format.")
    return name

def _validate_pane_id(pane_id: str) -> str:
    if not VALID_PANE_RE.fullmatch(pane_id or ""):
        raise HTTPException(status_code=400, detail="Invalid pane id format.")
    return pane_id

def _bash_quote(s: str) -> str:
    return "'" + s.replace("'", "'\"'\"'") + "'"


def _windows_runtime_supported() -> bool:
    return bool(os.name == "nt" and WINPTY_AVAILABLE and PtyProcess is not None)


def _desktop_codex_available() -> bool:
    return os.path.isfile(DESKTOP_CODEX_STATE_DB)


def _desktop_codex_windows_cli_source_candidates() -> List[str]:
    candidates: List[str] = []
    env_cli = str(os.environ.get("CODEX_DESKTOP_WINDOWS_CLI_SOURCE") or "").strip()
    if env_cli and os.path.isfile(env_cli):
        candidates.append(os.path.abspath(env_cli))
    configured_cli = str(CODEX_WINDOWS_CLI or "").strip()
    if configured_cli:
        configured_abs = configured_cli if os.path.isabs(configured_cli) else os.path.abspath(configured_cli)
        if os.path.isfile(configured_abs):
            candidates.append(configured_abs)
    for matched in sorted(glob.glob(DESKTOP_CODEX_WINDOWS_APPS_GLOB), reverse=True):
        if os.path.isfile(matched):
            candidates.append(os.path.abspath(matched))
    seen: set[str] = set()
    unique: List[str] = []
    for candidate in candidates:
        lowered = candidate.lower()
        if lowered in seen:
            continue
        seen.add(lowered)
        unique.append(candidate)
    return unique


def _desktop_codex_app_server_supported() -> bool:
    return bool(
        os.name == "nt"
        and WEBSOCKETS_AVAILABLE
        and (_desktop_codex_windows_cli_source_candidates() or os.path.isfile(DESKTOP_CODEX_WINDOWS_CLI_CACHE_PATH))
    )


def _desktop_codex_write_supported() -> bool:
    return _desktop_codex_app_server_supported()


def _desktop_codex_prepare_windows_cli_copy() -> str:
    if os.name != "nt":
        raise HTTPException(status_code=501, detail="Desktop Codex write-back is only supported on Windows hosts.")
    cached = os.path.abspath(DESKTOP_CODEX_WINDOWS_CLI_CACHE_PATH)
    if os.path.isfile(cached):
        return cached
    source_candidates = _desktop_codex_windows_cli_source_candidates()
    if not source_candidates:
        raise HTTPException(
            status_code=500,
            detail="Could not locate a Windows Codex CLI binary to start the desktop app-server.",
        )
    os.makedirs(DESKTOP_CODEX_WINDOWS_CLI_CACHE_DIR, exist_ok=True)
    for source in source_candidates:
        temp_target = f"{cached}.{uuid.uuid4().hex}.tmp"
        try:
            shutil.copy2(source, temp_target)
            os.replace(temp_target, cached)
            return cached
        except Exception as exc:
            LOGGER.warning("Failed to copy Windows Codex CLI from %s: %s", source, exc)
            try:
                if os.path.exists(temp_target):
                    os.remove(temp_target)
            except Exception:
                pass
    raise HTTPException(
        status_code=500,
        detail="Could not stage a runnable Windows Codex CLI binary for desktop app-server transport.",
    )


def _desktop_codex_find_free_loopback_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as handle:
        handle.bind(("127.0.0.1", 0))
        return int(handle.getsockname()[1])


def _desktop_codex_app_server_ready(port: int, timeout: float = 1.5) -> bool:
    url = f"http://127.0.0.1:{int(port)}/readyz"
    try:
        with urllib.request.urlopen(url, timeout=max(0.2, timeout)) as response:
            return int(getattr(response, "status", 0) or 0) == 200
    except Exception:
        return False


def _desktop_codex_terminate_app_server_state(state: Optional[Dict[str, Any]]) -> None:
    process = state.get("process") if isinstance(state, dict) else None
    if not process:
        return
    try:
        if process.poll() is None:
            process.terminate()
            process.wait(timeout=4)
    except Exception:
        try:
            if process.poll() is None:
                process.kill()
        except Exception:
            LOGGER.debug("Failed to terminate private Desktop Codex app-server", exc_info=True)


def _desktop_codex_app_server_state() -> Dict[str, Any]:
    with DESKTOP_CODEX_APP_SERVER_LOCK:
        return dict(DESKTOP_CODEX_APP_SERVER)


def _desktop_codex_shutdown_app_server() -> None:
    with DESKTOP_CODEX_APP_SERVER_LOCK:
        state = dict(DESKTOP_CODEX_APP_SERVER)
        DESKTOP_CODEX_APP_SERVER.clear()
    if state:
        _desktop_codex_terminate_app_server_state(state)


def _desktop_codex_ensure_app_server() -> Dict[str, Any]:
    if not _desktop_codex_write_supported():
        raise HTTPException(
            status_code=500,
            detail=(
                "Desktop Codex write-back is unavailable on this host. "
                + (
                    f"websockets import failed: {WEBSOCKETS_IMPORT_ERROR}"
                    if not WEBSOCKETS_AVAILABLE
                    else "Windows Codex CLI could not be located."
                )
            ),
        )
    with DESKTOP_CODEX_APP_SERVER_LOCK:
        existing = dict(DESKTOP_CODEX_APP_SERVER)
        existing_port = int(existing.get("port") or 0)
        existing_process = existing.get("process")
        if existing_process and existing_process.poll() is None and existing_port and _desktop_codex_app_server_ready(existing_port):
            return existing

        if existing:
            _desktop_codex_terminate_app_server_state(existing)
            DESKTOP_CODEX_APP_SERVER.clear()

        cli_path = _desktop_codex_prepare_windows_cli_copy()
        port = _desktop_codex_find_free_loopback_port()
        url = f"ws://127.0.0.1:{port}"
        stdout_log = os.path.join(CODEX_RUNTIME_LOGS_DIR, f"desktop-codex-app-server-{port}.stdout.log")
        stderr_log = os.path.join(CODEX_RUNTIME_LOGS_DIR, f"desktop-codex-app-server-{port}.stderr.log")
        os.makedirs(CODEX_RUNTIME_LOGS_DIR, exist_ok=True)
        stdout_handle = open(stdout_log, "ab")
        stderr_handle = open(stderr_log, "ab")
        process = subprocess.Popen(
            [cli_path, "app-server", "--listen", url],
            cwd=DESKTOP_CODEX_WINDOWS_CLI_CACHE_DIR,
            stdout=stdout_handle,
            stderr=stderr_handle,
            stdin=subprocess.DEVNULL,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0,
        )
        try:
            stdout_handle.close()
        except Exception:
            pass
        try:
            stderr_handle.close()
        except Exception:
            pass
        started = time.time()
        ready = False
        while time.time() - started < DESKTOP_CODEX_APP_SERVER_START_TIMEOUT_SECONDS:
            if process.poll() is not None:
                break
            if _desktop_codex_app_server_ready(port):
                ready = True
                break
            time.sleep(0.25)
        if not ready:
            _desktop_codex_terminate_app_server_state({"process": process})
            try:
                stdout_handle.flush()
                stderr_handle.flush()
            except Exception:
                pass
            detail = "Desktop Codex app-server failed to start."
            try:
                with open(stderr_log, "rb") as handle:
                    tail = handle.read()[-4000:].decode("utf-8", errors="ignore").strip()
                if tail:
                    detail = f"{detail} {tail}"
            except Exception:
                pass
            raise HTTPException(status_code=500, detail=detail)

        DESKTOP_CODEX_APP_SERVER.update(
            {
                "process": process,
                "port": port,
                "url": url,
                "stdout_log": stdout_log,
                "stderr_log": stderr_log,
                "started_at": time.time(),
                "cli_path": cli_path,
            }
        )
        return dict(DESKTOP_CODEX_APP_SERVER)


def _desktop_codex_runtime_status_payload() -> Dict[str, Any]:
    if not _desktop_codex_available():
        return {
            "ok": False,
            "state": "missing",
            "detail": f"Codex Desktop thread store was not found at {DESKTOP_CODEX_STATE_DB}.",
            "can_start": False,
            "can_stop": False,
            "cwd": DESKTOP_CODEX_HOME,
            "read_only": True,
        }
    write_supported = _desktop_codex_write_supported()
    return {
        "ok": True,
        "state": "running",
        "detail": (
            "Attached to the shared Codex Desktop thread history under ~/.codex. "
            + (
                "Prompts are sent through a private Windows app-server against the same thread store."
                if write_supported
                else "This mirror is read-only on this host because desktop app-server transport is unavailable."
            )
        ),
        "can_start": False,
        "can_stop": False,
        "cwd": DESKTOP_CODEX_HOME,
        "read_only": not write_supported,
    }


def _desktop_codex_sessions_detail() -> str:
    if _desktop_codex_write_supported():
        return "Attached to the shared Codex Desktop thread history under ~/.codex. Prompts are sent through a private Windows app-server against the same thread store."
    return "Read-only mirror of Codex Desktop threads."


def _desktop_codex_normalize_windows_path(value: str) -> str:
    text = str(value or "").strip()
    if text.startswith("\\\\?\\"):
        text = text[4:]
    return text


def _desktop_codex_windows_to_wsl_path(value: str) -> str:
    text = _desktop_codex_normalize_windows_path(value)
    match = re.match(r"^([A-Za-z]):\\(.*)$", text)
    if not match:
        return text.replace("\\", "/")
    drive = match.group(1).lower()
    rest = match.group(2).replace("\\", "/")
    return f"/mnt/{drive}/{rest}"


def _desktop_codex_compact_text(value: Any, max_length: int = 140) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    if len(text) <= max_length:
        return text
    return text[: max(0, max_length - 3)].rstrip() + "..."


def _desktop_codex_decode_path_value(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    try:
        text = unquote(text)
    except Exception:
        pass
    text = _desktop_codex_normalize_windows_path(text).replace("\\", "/")
    text = re.sub(r"/{2,}", "/", text)
    windows_mnt_match = re.match(r"^([A-Za-z]):/mnt/([A-Za-z])(?:/|$)", text)
    if windows_mnt_match:
        rest = text[windows_mnt_match.end():].lstrip("/")
        return f"{windows_mnt_match.group(2).upper()}:/{rest}".rstrip("/")
    return text.rstrip("/")


def _desktop_codex_split_path(value: Any) -> Tuple[str, List[str]]:
    normalized = _desktop_codex_decode_path_value(value)
    if not normalized:
        return "", []
    drive_match = re.match(r"^([A-Za-z]):(?:/|$)", normalized)
    if drive_match:
        return f"{drive_match.group(1).upper()}:", [part for part in normalized[2:].split("/") if part]
    mnt_match = re.match(r"^/mnt/([A-Za-z])(?:/|$)", normalized)
    if mnt_match:
        trimmed = re.sub(r"^/mnt/[A-Za-z](?:/|$)", "", normalized)
        return f"{mnt_match.group(1).upper()}:", [part for part in trimmed.split("/") if part]
    return "", [part for part in normalized.split("/") if part]


def _desktop_codex_is_home_like_cwd(value: Any) -> bool:
    normalized = _desktop_codex_decode_path_value(value).lower()
    if not normalized:
        return True
    return bool(
        re.fullmatch(r"[a-z]:/users/[^/]+/?", normalized)
        or re.fullmatch(r"/users/[^/]+/?", normalized)
        or re.fullmatch(r"/home/[^/]+/?", normalized)
    )


def _desktop_codex_strip_common_user_prefixes(parts: List[str]) -> List[str]:
    if len(parts) >= 2 and parts[0].lower() == "users":
        trimmed = parts[2:]
        if trimmed and trimmed[0].lower() in {"desktop", "documents", "downloads", "onedrive"}:
            return trimmed[1:]
        return trimmed
    if len(parts) >= 2 and parts[0].lower() == "home":
        return parts[2:]
    return parts


def _desktop_codex_compact_display_path(value: Any, tail_count: int = 2) -> str:
    drive, parts = _desktop_codex_split_path(value)
    if not parts:
        return drive
    tail = parts[-tail_count:]
    if len(parts) <= tail_count:
        return f"{drive} / {' / '.join(tail)}" if drive else " / ".join(tail)
    return f"{drive} / ... / {' / '.join(tail)}" if drive else f"... / {' / '.join(tail)}"


def _desktop_codex_launch_issue_path(raw_title: Any, first_user_message: Any = "") -> str:
    haystack = f"{raw_title or ''}\n{first_user_message or ''}"
    match = re.search(r'could not access starting directory\s+"([^"]+)"', haystack, flags=re.IGNORECASE)
    if not match:
        return ""
    return _desktop_codex_decode_path_value(match.group(1))


def _desktop_codex_launch_issue_title(raw_title: Any, first_user_message: Any = "") -> str:
    haystack = f"{raw_title or ''}\n{first_user_message or ''}"
    return "could not access starting directory" in haystack.lower() or "0x8007010b" in haystack.lower()


def _desktop_codex_source_label(value: Any) -> str:
    source = str(value or "").strip().lower()
    if source == "vscode":
        return "VS Code"
    if source == "cli":
        return "CLI"
    if source == "desktop":
        return "Desktop"
    return source.title() if source else "Desktop"


def _desktop_codex_first_meaningful_line(value: Any) -> str:
    for raw_line in str(value or "").splitlines():
        line = _desktop_codex_compact_text(raw_line, 240)
        if line:
            return line
    return ""


def _desktop_codex_title_seed(raw_title: Any, first_user_message: Any = "") -> str:
    for source in (raw_title, first_user_message):
        lines: List[str] = []
        for raw_line in str(source or "").splitlines():
            line = _desktop_codex_compact_text(raw_line, 240)
            if not line:
                continue
            lines.append(line)
            if len(lines) >= 3:
                break
        if lines:
            return " ".join(lines)
    return ""


def _desktop_codex_display_title(raw_title: Any, first_user_message: Any = "") -> str:
    candidate = _desktop_codex_title_seed(raw_title, first_user_message)
    if not candidate:
        return "Untitled chat"

    path_heavy = bool(
        candidate.count('"') >= 2
        or re.search(r'[A-Za-z]:[\\/][^"\n]{10,}', candidate)
        or re.search(r'/mnt/[A-Za-z]/[^"\n]{10,}', candidate)
    )
    if path_heavy:
        candidate = re.split(r'\s+"(?:[A-Za-z]:[\\/]|/mnt/[A-Za-z]/)', candidate, maxsplit=1)[0]
        candidate = re.sub(
            r"^(?:in this path|in this folder|in this directory|from this path|from this folder)\s*,\s*",
            "",
            candidate,
            flags=re.IGNORECASE,
        )
        candidate = re.sub(
            r"\s*(?:as per(?: to)? .*|like the example provided.*)$",
            "",
            candidate,
            flags=re.IGNORECASE,
        )
        candidate = candidate.strip(" -,:")
    if candidate and candidate[0].islower():
        candidate = candidate[0].upper() + candidate[1:]
    return _desktop_codex_compact_text(candidate, 72) or "Untitled chat"


def _desktop_codex_workspace_meta(cwd: Any) -> Dict[str, str]:
    normalized = _desktop_codex_decode_path_value(cwd)
    drive, parts = _desktop_codex_split_path(normalized)
    meaningful = _desktop_codex_strip_common_user_prefixes(parts)
    root = meaningful[0] if meaningful else (parts[0] if parts else drive or "Unknown")
    group_label = drive or root or "Other"
    group_hint = ""
    if drive and root and root != drive:
        group_hint = root
    elif len(meaningful) > 1:
        group_hint = " / ".join(meaningful[:2])
    workspace_label = root or drive or "Unknown"
    workspace_hint = " / ".join(meaningful[1:3]) if len(meaningful) > 1 else ""
    group_id = f"{(drive or 'root').lower()}::{(root or 'unknown').lower()}"
    return {
        "group_id": group_id,
        "group_label": group_label,
        "group_hint": group_hint,
        "workspace_label": workspace_label,
        "workspace_hint": workspace_hint,
        "workspace_path": normalized,
    }


def _desktop_codex_thread_display_meta(
    *,
    cwd: Any,
    title: Any,
    first_user_message: Any,
    snippet: Any,
    source: Any,
    git_branch: Any,
    git_origin_url: Any,
    agent_nickname: Any,
    agent_role: Any,
) -> Dict[str, Any]:
    raw_title = str(title or "").strip()
    first_prompt = str(first_user_message or "").strip()
    launch_issue = _desktop_codex_launch_issue_title(raw_title, first_prompt)
    launch_path = _desktop_codex_launch_issue_path(raw_title, first_prompt) if launch_issue else ""
    workspace = _desktop_codex_workspace_meta(cwd)
    kind = "chat" if _desktop_codex_is_home_like_cwd(cwd) else "project"

    display_title = _desktop_codex_display_title(raw_title, first_prompt)
    details = ""
    preview = _desktop_codex_compact_text(snippet or first_prompt, 120)
    if launch_issue:
        display_title = "Fix Codex launch error"
        subject = workspace.get("workspace_label") or ""
        if launch_path:
            _drive, launch_parts = _desktop_codex_split_path(launch_path)
            subject = launch_parts[-1] if launch_parts else subject
            details = f"Working directory unavailable: {_desktop_codex_compact_display_path(launch_path, 3)}"
            preview = f"Launch issue in {subject}" if subject else "Launch issue"
        else:
            details = "Working directory unavailable."
            preview = "Launch issue"
    elif not preview:
        preview = _desktop_codex_compact_text(first_prompt or raw_title, 120)

    return {
        "kind": kind,
        "source_label": _desktop_codex_source_label(source),
        "group_id": "chats" if kind == "chat" else workspace["group_id"],
        "group_label": "Chats" if kind == "chat" else workspace["group_label"],
        "group_hint": "" if kind == "chat" else workspace["group_hint"],
        "workspace_label": workspace["workspace_label"],
        "workspace_hint": workspace["workspace_hint"],
        "workspace_path": workspace["workspace_path"],
        "display_title": display_title,
        "full_title": raw_title or first_prompt or "Untitled chat",
        "preview": preview,
        "details": details,
        "git_branch": str(git_branch or "").strip(),
        "git_origin_url": str(git_origin_url or "").strip(),
        "agent_nickname": str(agent_nickname or "").strip(),
        "agent_role": str(agent_role or "").strip(),
        "launch_issue": {
            "active": launch_issue,
            "path": launch_path,
            "path_label": _desktop_codex_compact_display_path(launch_path, 3) if launch_path else "",
        },
    }


def _desktop_codex_is_job_active(job: Optional[Dict[str, Any]]) -> bool:
    if isinstance(job, dict) and str(job.get("transport") or "").strip() == "app_server":
        return bool(job.get("active"))
    process = job.get("process") if isinstance(job, dict) else None
    return bool(process and process.poll() is None)


def _desktop_codex_prune_jobs() -> None:
    stale_sessions: List[str] = []
    with DESKTOP_CODEX_JOB_LOCK:
        for session_id, job in DESKTOP_CODEX_JOBS.items():
            if not _desktop_codex_is_job_active(job) and float(job.get("finished_at") or 0) > 0:
                stale_sessions.append(session_id)
        for session_id in stale_sessions:
            DESKTOP_CODEX_JOBS.pop(session_id, None)


def _desktop_codex_job_snapshot(session: str) -> Optional[Dict[str, Any]]:
    _desktop_codex_prune_jobs()
    with DESKTOP_CODEX_JOB_LOCK:
        job = DESKTOP_CODEX_JOBS.get(session)
        if not job:
            return None
        return dict(job)


def _desktop_codex_wait_for_job(session: str, process: subprocess.Popen[Any], log_handle: Any) -> None:
    exit_code = process.wait()
    try:
        log_handle.flush()
        log_handle.close()
    except Exception:
        pass
    script_path = ""
    with DESKTOP_CODEX_JOB_LOCK:
        job = DESKTOP_CODEX_JOBS.get(session)
        if job and job.get("process") is process:
            job["exit_code"] = exit_code
            job["finished_at"] = time.time()
            job["active"] = False
            script_path = str(job.get("script_path") or "").strip()
    if script_path:
        try:
            os.remove(script_path)
        except FileNotFoundError:
            pass
        except Exception:
            LOGGER.debug("Failed to remove Desktop Codex sidecar wrapper: %s", script_path, exc_info=True)


async def _desktop_codex_app_server_request_async(
    ws: Any,
    request_id: int,
    method: str,
    params: Optional[Dict[str, Any]] = None,
    *,
    timeout_seconds: Optional[float] = None,
) -> Dict[str, Any]:
    if websockets is None:
        raise RuntimeError("websockets is unavailable")
    await ws.send(
        json.dumps(
            {
                "jsonrpc": "2.0",
                "id": request_id,
                "method": method,
                "params": params or {},
            }
        )
    )
    deadline = time.time() + max(1.0, float(timeout_seconds or DESKTOP_CODEX_APP_SERVER_RPC_TIMEOUT_SECONDS))
    while True:
        remaining = deadline - time.time()
        if remaining <= 0:
            raise TimeoutError(f"Timed out waiting for app-server response to {method}.")
        raw_message = await asyncio.wait_for(ws.recv(), timeout=remaining)
        message = json.loads(raw_message)
        if int(message.get("id") or 0) != request_id:
            continue
        error_payload = message.get("error")
        if isinstance(error_payload, dict):
            error_text = str(error_payload.get("message") or method).strip() or method
            raise RuntimeError(f"{method} failed: {error_text}")
        result = message.get("result")
        return result if isinstance(result, dict) else {}


async def _desktop_codex_with_app_server_async(
    operation: Callable[[Any], "asyncio.Future[Dict[str, Any]] | Any"],
) -> Dict[str, Any]:
    if websockets is None:
        raise RuntimeError("websockets is unavailable")
    server = _desktop_codex_ensure_app_server()
    url = str(server.get("url") or "").strip()
    if not url:
        raise RuntimeError("Desktop Codex app-server URL is missing.")
    async with websockets.connect(url, max_size=None, open_timeout=10) as ws:  # type: ignore[attr-defined]
        await _desktop_codex_app_server_request_async(
            ws,
            1,
            "initialize",
            {
                "protocolVersion": 2,
                "clientInfo": {
                    "name": "codrex-remote-ui",
                    "version": "1.0.0",
                },
            },
            timeout_seconds=5.0,
        )
        result = operation(ws)
        if asyncio.iscoroutine(result):
            result = await result
        return result if isinstance(result, dict) else {}


def _desktop_codex_run_app_server_rpc(
    operation: Callable[[Any], "asyncio.Future[Dict[str, Any]] | Any"],
) -> Dict[str, Any]:
    try:
        return asyncio.run(_desktop_codex_with_app_server_async(operation))
    except HTTPException:
        raise
    except TimeoutError as exc:
        raise HTTPException(status_code=504, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Desktop Codex app-server request failed: {exc}") from exc


def _desktop_codex_find_turn(thread_payload: Dict[str, Any], turn_id: str) -> Optional[Dict[str, Any]]:
    thread = thread_payload.get("thread") if isinstance(thread_payload, dict) else {}
    turns = thread.get("turns") if isinstance(thread, dict) else []
    if not isinstance(turns, list):
        return None
    target = str(turn_id or "").strip()
    for turn in turns:
        if isinstance(turn, dict) and str(turn.get("id") or "").strip() == target:
            return turn
    return None


def _desktop_codex_start_app_server_resume(session_entry: Dict[str, Any], prompt: str) -> Dict[str, Any]:
    if not _desktop_codex_write_supported():
        raise HTTPException(status_code=400, detail="Desktop Codex write-back is unavailable on this host.")
    text = str(prompt or "").strip()
    if not text:
        raise HTTPException(status_code=400, detail="Prompt is required.")
    session_id = str(session_entry.get("session") or "").strip()
    cwd = str(session_entry.get("cwd") or "").strip() or None
    if not session_id:
        raise HTTPException(status_code=400, detail="Desktop Codex thread metadata is incomplete.")

    with DESKTOP_CODEX_JOB_LOCK:
        existing = DESKTOP_CODEX_JOBS.get(session_id)
        if _desktop_codex_is_job_active(existing):
            raise HTTPException(status_code=409, detail="This desktop thread already has an active app-server turn.")

    async def _operation(ws: Any) -> Dict[str, Any]:
        await _desktop_codex_app_server_request_async(
            ws,
            2,
            "thread/resume",
            {
                "threadId": session_id,
                "cwd": cwd,
            },
        )
        turn_started = await _desktop_codex_app_server_request_async(
            ws,
            3,
            "turn/start",
            {
                "threadId": session_id,
                "cwd": cwd,
                "input": [
                    {
                        "type": "text",
                        "text": text,
                    }
                ],
            },
            timeout_seconds=max(8.0, DESKTOP_CODEX_APP_SERVER_RPC_TIMEOUT_SECONDS),
        )
        return turn_started

    started = _desktop_codex_run_app_server_rpc(_operation)
    turn_payload = started.get("turn") if isinstance(started, dict) else {}
    turn_id = str(turn_payload.get("id") or "").strip() if isinstance(turn_payload, dict) else ""
    if not turn_id:
        raise HTTPException(status_code=502, detail="Desktop Codex app-server did not return a turn id.")

    with DESKTOP_CODEX_JOB_LOCK:
        DESKTOP_CODEX_JOBS[session_id] = {
            "session": session_id,
            "transport": "app_server",
            "turn_id": turn_id,
            "prompt_preview": " ".join(text.split())[:200],
            "started_at": time.time(),
            "finished_at": 0.0,
            "exit_code": None,
            "active": True,
        }

    watcher = threading.Thread(
        target=_desktop_codex_wait_for_app_server_turn,
        args=(session_id, turn_id, cwd),
        daemon=True,
    )
    watcher.start()
    return {
        "session": session_id,
        "turn_id": turn_id,
        "started_at": time.time(),
    }


def _desktop_codex_wait_for_app_server_turn(session: str, turn_id: str, cwd: Optional[str]) -> None:
    while True:
        time.sleep(1.0)
        job = _desktop_codex_job_snapshot(session)
        if not _desktop_codex_is_job_active(job):
            return

        async def _operation(ws: Any) -> Dict[str, Any]:
            thread_payload = await _desktop_codex_app_server_request_async(
                ws,
                2,
                "thread/read",
                {"threadId": session},
            )
            target_turn = _desktop_codex_find_turn(thread_payload, turn_id)
            if target_turn:
                return target_turn
            resumed = await _desktop_codex_app_server_request_async(
                ws,
                3,
                "thread/resume",
                {
                    "threadId": session,
                    "cwd": cwd,
                },
            )
            return _desktop_codex_find_turn(resumed, turn_id) or {}

        try:
            turn_state = _desktop_codex_run_app_server_rpc(_operation)
        except HTTPException:
            continue
        status = str(turn_state.get("status") or "").strip().lower()
        if status in {"inprogress", "pending"}:
            continue
        with DESKTOP_CODEX_JOB_LOCK:
            job = DESKTOP_CODEX_JOBS.get(session)
            if job and str(job.get("turn_id") or "").strip() == str(turn_id or "").strip():
                job["active"] = False
                job["finished_at"] = time.time()
                job["exit_code"] = 0 if status == "completed" else 1
        return


def _desktop_codex_start_sidecar_resume(session_entry: Dict[str, Any], prompt: str) -> Dict[str, Any]:
    if not _desktop_codex_write_supported():
        raise HTTPException(status_code=400, detail="Desktop Codex write-back requires WSL on this host.")
    text = str(prompt or "").strip()
    if not text:
        raise HTTPException(status_code=400, detail="Prompt is required.")
    session_id = str(session_entry.get("session") or "").strip()
    rollout_alias = _desktop_codex_normalize_windows_path(str(session_entry.get("rollout_path") or "").strip())
    rollout_target = _desktop_codex_windows_to_wsl_path(rollout_alias)
    codex_home_wsl = _desktop_codex_windows_to_wsl_path(DESKTOP_CODEX_HOME)
    if not session_id or not rollout_alias or not rollout_target:
        raise HTTPException(status_code=400, detail="Desktop Codex thread metadata is incomplete.")
    baseline_size = os.path.getsize(rollout_alias) if os.path.isfile(rollout_alias) else 0
    baseline_mtime = os.path.getmtime(rollout_alias) if os.path.isfile(rollout_alias) else 0.0

    with DESKTOP_CODEX_JOB_LOCK:
        existing = DESKTOP_CODEX_JOBS.get(session_id)
        if _desktop_codex_is_job_active(existing):
            raise HTTPException(status_code=409, detail="This desktop thread already has an active sidecar turn.")

        log_path = os.path.join(CODEX_RUNTIME_LOGS_DIR, f"desktop-codex-sidecar-{session_id}.log")
        os.makedirs(os.path.dirname(log_path), exist_ok=True)
        log_handle = open(log_path, "wb")
        rollout_target_b64 = base64.b64encode(rollout_target.encode("utf-8")).decode("ascii")
        rollout_alias_b64 = base64.b64encode(rollout_alias.encode("utf-8")).decode("ascii")
        script_path = os.path.join(
            CODEX_RUNTIME_LOGS_DIR,
            f"desktop-codex-sidecar-{session_id}-{uuid.uuid4().hex}.py",
        )
        script_wsl_path = _desktop_codex_windows_to_wsl_path(script_path)
        script_source = "\n".join(
            [
                "import base64",
                "import os",
                "import shutil",
                "import subprocess",
                "import sys",
                "import tempfile",
                "",
                "rollout_target = base64.b64decode(sys.argv[1]).decode('utf-8')",
                "rollout_alias = base64.b64decode(sys.argv[2]).decode('utf-8')",
                "codex_home = sys.argv[3]",
                "node_bin = sys.argv[4]",
                "real_codex = sys.argv[5]",
                "session_id = sys.argv[6]",
                "",
                "shim = tempfile.mkdtemp(prefix='codrex-desktop-codex-')",
                "try:",
                "    os.symlink(rollout_target, os.path.join(shim, rollout_alias))",
                "    prompt = sys.stdin.read()",
                "    env = os.environ.copy()",
                "    env['CODEX_HOME'] = codex_home",
                "    env['PATH'] = node_bin + os.pathsep + env.get('PATH', '')",
                "    os.chdir(shim)",
                "    completed = subprocess.run(",
                "        [real_codex, 'exec', 'resume', '--skip-git-repo-check', session_id, '-', '--json'],",
                "        env=env,",
                "        input=prompt,",
                "        text=True,",
                "        stderr=subprocess.STDOUT,",
                "        check=False,",
                "    )",
                "    raise SystemExit(int(completed.returncode or 0))",
                "finally:",
                "    shutil.rmtree(shim, ignore_errors=True)",
                "",
            ]
        )
        with open(script_path, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(script_source)
        process = subprocess.Popen(
            [
                "wsl.exe",
                "python3",
                script_wsl_path,
                rollout_target_b64,
                rollout_alias_b64,
                codex_home_wsl,
                DESKTOP_CODEX_WSL_NODE_BIN,
                DESKTOP_CODEX_WSL_REAL_CODEX,
                session_id,
            ],
            stdin=subprocess.PIPE,
            stdout=log_handle,
            stderr=subprocess.STDOUT,
            text=True,
        )
        assert process.stdin is not None
        process.stdin.write(text)
        if not text.endswith("\n"):
            process.stdin.write("\n")
        process.stdin.close()

        time.sleep(0.15)
        early_exit = process.poll()
        if early_exit is not None:
            try:
                log_handle.flush()
                log_handle.close()
            except Exception:
                pass
            try:
                os.remove(script_path)
            except FileNotFoundError:
                pass
            except Exception:
                LOGGER.debug("Failed to remove failed Desktop Codex sidecar wrapper: %s", script_path, exc_info=True)
            detail = f"Desktop Codex sidecar exited early with code {early_exit}."
            try:
                with open(log_path, "rb") as handle:
                    tail = handle.read()[-2000:].decode("utf-8", errors="ignore").strip()
                if tail:
                    detail = f"{detail} {tail}"
            except Exception:
                pass
            raise HTTPException(status_code=500, detail=detail)

        accepted = _desktop_codex_wait_for_prompt_enqueue(
            rollout_alias,
            text,
            baseline_size,
            baseline_mtime,
            process,
        )
        if not accepted:
            try:
                process.terminate()
            except Exception:
                LOGGER.debug("Failed to terminate unaccepted Desktop Codex sidecar turn for %s", session_id, exc_info=True)
            try:
                process.wait(timeout=3)
            except Exception:
                try:
                    process.kill()
                except Exception:
                    LOGGER.debug("Failed to kill unaccepted Desktop Codex sidecar turn for %s", session_id, exc_info=True)
            try:
                log_handle.flush()
                log_handle.close()
            except Exception:
                pass
            try:
                os.remove(script_path)
            except FileNotFoundError:
                pass
            except Exception:
                LOGGER.debug("Failed to remove rejected Desktop Codex sidecar wrapper: %s", script_path, exc_info=True)
            detail = (
                "Desktop thread did not accept the prompt. "
                "If this chat is already active in Codex Desktop, finish that turn or switch to another thread before sending from SSH."
            )
            try:
                with open(log_path, "rb") as handle:
                    tail = handle.read()[-2000:].decode("utf-8", errors="ignore").strip()
                if tail:
                    detail = f"{detail} {tail}"
            except Exception:
                pass
            raise HTTPException(status_code=409, detail=detail)

        DESKTOP_CODEX_JOBS[session_id] = {
            "session": session_id,
            "process": process,
            "prompt_preview": " ".join(text.split())[:200],
            "started_at": time.time(),
            "finished_at": 0.0,
            "exit_code": None,
            "active": True,
            "log_path": log_path,
            "script_path": script_path,
        }

    watcher = threading.Thread(
        target=_desktop_codex_wait_for_job,
        args=(session_id, process, log_handle),
        daemon=True,
    )
    watcher.start()
    return {
        "session": session_id,
        "started_at": time.time(),
        "log_path": log_path,
    }


def _desktop_codex_interrupt_sidecar_resume(session: str) -> bool:
    session_id = _validate_session_name(session)
    job = _desktop_codex_job_snapshot(session_id)
    if not _desktop_codex_is_job_active(job):
        return False
    if str(job.get("transport") or "").strip() == "app_server":
        turn_id = str(job.get("turn_id") or "").strip()
        if not turn_id:
            return False

        async def _operation(ws: Any) -> Dict[str, Any]:
            await _desktop_codex_app_server_request_async(
                ws,
                2,
                "turn/interrupt",
                {
                    "threadId": session_id,
                    "turnId": turn_id,
                },
            )
            return {"ok": True}

        _desktop_codex_run_app_server_rpc(_operation)
        with DESKTOP_CODEX_JOB_LOCK:
            latest = DESKTOP_CODEX_JOBS.get(session_id)
            if latest and str(latest.get("turn_id") or "").strip() == turn_id:
                latest["active"] = False
                latest["finished_at"] = time.time()
                latest["exit_code"] = 130
        return True

    with DESKTOP_CODEX_JOB_LOCK:
        latest = DESKTOP_CODEX_JOBS.get(session_id)
        process = latest.get("process") if isinstance(latest, dict) else None
        if not process or process.poll() is not None:
            return False
        try:
            process.terminate()
        except Exception:
            return False
        latest["active"] = False
        latest["finished_at"] = time.time()
        return True


def _desktop_codex_open_deeplink(url: str) -> None:
    if os.name != "nt":
        raise HTTPException(status_code=501, detail="Codex desktop deeplinks are only supported on Windows hosts.")
    target = str(url or "").strip()
    if not target:
        raise HTTPException(status_code=400, detail="Codex desktop deeplink is required.")
    try:
        os.startfile(target)  # type: ignore[attr-defined]
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Could not open Codex desktop deeplink: {exc}") from exc


def _desktop_codex_open_thread(session: str) -> None:
    session_id = _validate_session_name(session)
    _desktop_codex_open_deeplink(f"codex://threads/{session_id}")


def _desktop_codex_refresh_thread(session: str) -> None:
    session_id = _validate_session_name(session)
    _desktop_codex_open_deeplink("codex://settings")
    time.sleep(0.35)
    _desktop_codex_open_deeplink(f"codex://threads/{session_id}")


def _desktop_codex_extract_message_text(message_payload: Dict[str, Any]) -> Tuple[str, str]:
    role = str(message_payload.get("role") or "").strip().lower()
    parts: List[str] = []
    for item in message_payload.get("content") or []:
        if not isinstance(item, dict):
            continue
        item_type = str(item.get("type") or "").strip().lower()
        if item_type in {"input_text", "output_text"}:
            text = str(item.get("text") or "").strip()
            if text:
                parts.append(text)
        elif item_type == "local_image":
            path = str(item.get("path") or "").strip()
            parts.append(f"[local image] {path}" if path else "[local image]")
        elif item_type == "image":
            parts.append("[image]")
    return role, "\n".join(part for part in parts if part).strip()


def _desktop_codex_rollout_tail_lines(rollout_path: str, max_bytes: int = DESKTOP_CODEX_ROLLOUT_TAIL_BYTES) -> List[str]:
    path = _desktop_codex_normalize_windows_path(rollout_path)
    if not path or not os.path.isfile(path):
        return []
    with open(path, "rb") as handle:
        handle.seek(0, os.SEEK_END)
        size = handle.tell()
        start = max(0, size - max_bytes)
        handle.seek(start, os.SEEK_SET)
        data = handle.read()
    if start > 0:
        first_newline = data.find(b"\n")
        if first_newline >= 0:
            data = data[first_newline + 1 :]
    return [line.decode("utf-8", errors="ignore") for line in data.splitlines() if line.strip()]


def _desktop_codex_rollout_has_prompt(rollout_path: str, prompt: str) -> bool:
    target = " ".join(str(prompt or "").split()).strip().lower()
    if not target:
        return False
    for raw_line in _desktop_codex_rollout_tail_lines(rollout_path, max_bytes=max(DESKTOP_CODEX_ROLLOUT_TAIL_BYTES, 65536)):
        try:
            event = json.loads(raw_line)
        except Exception:
            continue
        event_type = str(event.get("type") or "").strip()
        payload = event.get("payload") if isinstance(event.get("payload"), dict) else {}
        message_text = ""
        if event_type == "event_msg" and str(payload.get("type") or "").strip() == "user_message":
            message_text = str(payload.get("message") or "")
        elif event_type == "response_item" and str(payload.get("type") or "").strip() == "message":
            role, message_text = _desktop_codex_extract_message_text(payload)
            if role != "user":
                message_text = ""
        compact = " ".join(message_text.split()).strip().lower()
        if compact == target:
            return True
    return False


def _desktop_codex_wait_for_prompt_enqueue(
    rollout_path: str,
    prompt: str,
    baseline_size: int,
    baseline_mtime: float,
    process: subprocess.Popen[Any],
    timeout_seconds: float = 6.0,
) -> bool:
    deadline = time.time() + max(0.5, timeout_seconds)
    while time.time() < deadline:
        if process.poll() is not None:
            return _desktop_codex_rollout_has_prompt(rollout_path, prompt)
        try:
            stat = os.stat(rollout_path)
            changed = stat.st_size > baseline_size or stat.st_mtime > baseline_mtime
        except Exception:
            changed = False
        if changed and _desktop_codex_rollout_has_prompt(rollout_path, prompt):
            return True
        time.sleep(0.2)
    return _desktop_codex_rollout_has_prompt(rollout_path, prompt)


def _desktop_codex_resolve_busy_state(rollout_path: str, busy: bool) -> bool:
    if not busy:
        return False
    path = _desktop_codex_normalize_windows_path(rollout_path)
    if not path or not os.path.isfile(path):
        return busy
    try:
        modified_at = os.path.getmtime(path)
    except Exception:
        return busy
    return (time.time() - modified_at) < DESKTOP_CODEX_STALE_BUSY_SECONDS


def _desktop_codex_rollout_summary(rollout_path: str) -> Dict[str, Any]:
    lines = _desktop_codex_rollout_tail_lines(rollout_path)
    busy = False
    last_role = ""
    last_text = ""
    for raw_line in lines:
        try:
            event = json.loads(raw_line)
        except Exception:
            continue
        event_type = str(event.get("type") or "").strip()
        payload = event.get("payload") if isinstance(event.get("payload"), dict) else {}
        if event_type == "event_msg":
            inner_type = str(payload.get("type") or "").strip()
            if inner_type == "task_started":
                busy = True
            elif inner_type == "task_complete":
                busy = False
        elif event_type == "response_item" and str(payload.get("type") or "").strip() == "message":
            role, text = _desktop_codex_extract_message_text(payload)
            if role in {"user", "assistant"} and text:
                last_role = role
                last_text = text
    busy = _desktop_codex_resolve_busy_state(rollout_path, busy)
    if not last_text:
        return {
            "state": "busy" if busy else "idle",
            "snippet": "",
            "last_role": "",
            "last_text": "",
        }
    compact = " ".join(last_text.split())
    if last_role:
        compact = f"{last_role.title()}: {compact}"
    if len(compact) > 200:
        compact = f"{compact[:200].rstrip()}..."
    return {
        "state": "busy" if busy else "idle",
        "snippet": compact,
        "last_role": last_role,
        "last_text": last_text,
    }


def _desktop_codex_render_transcript(rollout_path: str) -> Dict[str, Any]:
    path = _desktop_codex_normalize_windows_path(rollout_path)
    if not path or not os.path.isfile(path):
        raise HTTPException(status_code=404, detail="Codex Desktop rollout file was not found.")
    rendered: List[str] = []
    busy = False
    with open(path, "r", encoding="utf-8", errors="ignore") as handle:
        for raw_line in handle:
            raw_line = raw_line.strip()
            if not raw_line:
                continue
            try:
                event = json.loads(raw_line)
            except Exception:
                continue
            event_type = str(event.get("type") or "").strip()
            payload = event.get("payload") if isinstance(event.get("payload"), dict) else {}
            if event_type == "event_msg":
                inner_type = str(payload.get("type") or "").strip()
                if inner_type == "task_started":
                    busy = True
                elif inner_type == "task_complete":
                    busy = False
                continue
            if event_type != "response_item" or str(payload.get("type") or "").strip() != "message":
                continue
            role, text = _desktop_codex_extract_message_text(payload)
            if role not in {"user", "assistant"} or not text:
                continue
            rendered.append(f"{role.title()}:\n{text.strip()}")
    busy = _desktop_codex_resolve_busy_state(path, busy)
    transcript = "\n\n".join(part for part in rendered if part).strip()
    if not transcript:
        transcript = "No visible user or assistant messages were found in this Codex Desktop thread yet."
    if len(transcript) > DESKTOP_CODEX_TRANSCRIPT_MAX_CHARS:
        transcript = transcript[-DESKTOP_CODEX_TRANSCRIPT_MAX_CHARS :]
        transcript = transcript.lstrip()
    return {
        "state": "busy" if busy else "idle",
        "text": transcript,
    }


def _desktop_codex_fetch_sessions() -> List[Dict[str, Any]]:
    if not _desktop_codex_available():
        return []
    _desktop_codex_prune_jobs()
    rows: List[Dict[str, Any]] = []
    conn = sqlite3.connect(DESKTOP_CODEX_STATE_DB)
    conn.row_factory = sqlite3.Row
    try:
        cursor = conn.execute(
            """
            SELECT
              id,
              rollout_path,
              cwd,
              title,
              source,
              first_user_message,
              git_branch,
              git_origin_url,
              agent_nickname,
              agent_role,
              model,
              COALESCE(updated_at_ms, updated_at * 1000) AS updated_ms,
              COALESCE(created_at_ms, created_at * 1000) AS created_ms
            FROM threads
            WHERE archived = 0
            ORDER BY COALESCE(updated_at_ms, updated_at * 1000) DESC
            LIMIT 200
            """
        )
        rows = [dict(row) for row in cursor.fetchall()]
    except sqlite3.Error as exc:
        raise HTTPException(status_code=500, detail=f"Could not read Codex Desktop threads: {exc}") from exc
    finally:
        conn.close()
    sessions: List[Dict[str, Any]] = []
    for row in rows:
        session_id = str(row.get("id") or "").strip()
        if not session_id:
            continue
        rollout_path = _desktop_codex_normalize_windows_path(str(row.get("rollout_path") or "").strip())
        summary = _desktop_codex_rollout_summary(rollout_path) if rollout_path else {
            "state": "error",
            "snippet": "",
            "last_role": "",
            "last_text": "",
        }
        title = str(row.get("title") or "").strip() or session_id
        cwd = _desktop_codex_normalize_windows_path(str(row.get("cwd") or "").strip())
        desktop_meta = _desktop_codex_thread_display_meta(
            cwd=cwd,
            title=title,
            first_user_message=row.get("first_user_message"),
            snippet=summary.get("snippet") or "",
            source=row.get("source"),
            git_branch=row.get("git_branch"),
            git_origin_url=row.get("git_origin_url"),
            agent_nickname=row.get("agent_nickname"),
            agent_role=row.get("agent_role"),
        )
        updated_at = float(row.get("updated_ms") or 0) / 1000.0
        created_at = float(row.get("created_ms") or 0) / 1000.0
        active_job = _desktop_codex_job_snapshot(session_id)
        state = str(summary.get("state") or "idle")
        busy_source = "desktop" if state == "busy" else "idle"
        if _desktop_codex_is_job_active(active_job):
            state = "busy"
            busy_source = str(active_job.get("transport") or "app_server")
        sessions.append({
            "session": session_id,
            "pane_id": session_id,
            "current_command": "Codex Desktop",
            "cwd": cwd,
            "state": state,
            "busy_source": busy_source,
            "updated_at": updated_at or created_at or time.time(),
            "last_seen_at": updated_at or created_at or time.time(),
            "snippet": desktop_meta.get("preview") or summary.get("snippet") or title,
            "model": str(row.get("model") or "").strip() or "gpt-5.4",
            "reasoning_effort": "desktop",
            "active": state == "busy",
            "closed_at": None,
            "can_resume": False,
            "resume_id": session_id,
            "title": desktop_meta.get("display_title") or title,
            "raw_title": title,
            "raw_snippet": summary.get("snippet") or "",
            "source": "desktop_codex",
            "read_only": not _desktop_codex_write_supported(),
            "rollout_path": rollout_path,
            "log_path": str(active_job.get("log_path") or "") if active_job else "",
            "desktop_codex_meta": desktop_meta,
        })
    return sessions


def _desktop_codex_session_entry(session: str) -> Dict[str, Any]:
    session_id = _validate_session_name(session)
    for entry in _desktop_codex_fetch_sessions():
        if entry.get("session") == session_id:
            return entry
    raise HTTPException(status_code=404, detail=f"Codex Desktop thread '{session_id}' was not found.")


def _windows_codex_profile_status(force: bool = False) -> Dict[str, Any]:
    with WINDOWS_CODEX_PROFILE_LOCK:
        cached = dict(WINDOWS_CODEX_PROFILE_STATUS)
        checked_at = float(cached.get("checked_at") or 0.0)
        if not force and checked_at > 0 and (time.time() - checked_at) < 60.0:
            return cached
    supported = False
    detail = ""
    try:
        result = subprocess.run(
            [CODEX_WINDOWS_CLI, "--version"],
            cwd=CODEX_WINDOWS_WORKDIR,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=8,
            creationflags=(
                getattr(subprocess, "CREATE_NO_WINDOW", 0)
                if os.name == "nt"
                else 0
            ),
        )
        supported = result.returncode == 0
        if not supported:
            stderr = (result.stderr or "").strip()
            detail = stderr or f"Codex exited with status {result.returncode}."
    except PermissionError as exc:
        detail = f"Windows Codex CLI is installed but cannot be launched from this host process: {exc}"
    except FileNotFoundError:
        detail = "Windows Codex CLI is not available on PATH."
    except subprocess.TimeoutExpired:
        detail = "Windows Codex CLI did not respond in time."
    except Exception as exc:
        detail = f"{type(exc).__name__}: {exc}"
    payload = {
        "supported": bool(supported),
        "detail": str(detail or ""),
        "checked_at": time.time(),
    }
    with WINDOWS_CODEX_PROFILE_LOCK:
        WINDOWS_CODEX_PROFILE_STATUS.update(payload)
        return dict(WINDOWS_CODEX_PROFILE_STATUS)


def _windows_available_profiles() -> List[str]:
    profiles = {"powershell", "cmd"}
    if _windows_codex_profile_status().get("supported"):
        profiles.add("codex")
    return sorted(profiles)


def _windows_default_profile() -> str:
    return "codex" if _windows_codex_profile_status().get("supported") else "powershell"


def _windows_runtime_status_payload() -> Dict[str, Any]:
    supported = _windows_runtime_supported()
    profiles = _windows_available_profiles() if supported else sorted({"powershell", "cmd"})
    default_profile = _windows_default_profile() if supported else "powershell"
    codex_status = _windows_codex_profile_status() if supported else {"supported": False, "detail": ""}
    with WINDOWS_RUNTIME_LOCK:
        active = bool(WINDOWS_RUNTIME_ACTIVE and supported)
    if not supported:
        detail = (
            "Windows ConPTY support is only available on Windows hosts."
            if os.name != "nt"
            else f"Windows ConPTY runtime is unavailable: {WINPTY_IMPORT_ERROR or 'pywinpty is missing.'}"
        )
        return {
            "ok": False,
            "state": "missing",
            "detail": detail,
            "can_start": False,
            "can_stop": False,
            "profiles": profiles,
            "default_profile": default_profile,
            "cwd": CODEX_WINDOWS_WORKDIR,
        }
    detail = "Windows terminal runtime ready."
    if not codex_status.get("supported") and codex_status.get("detail"):
        detail = f"{detail} Windows Codex profile unavailable: {codex_status['detail']}"
    return {
        "ok": active,
        "state": "running" if active else "stopped",
        "detail": detail if active else detail.replace("ready.", "is stopped."),
        "can_start": not active,
        "can_stop": active,
        "profiles": profiles,
        "default_profile": default_profile,
        "cwd": CODEX_WINDOWS_WORKDIR,
    }


def _windows_session_profile(raw: Any) -> str:
    profile = str(raw or _windows_default_profile()).strip().lower()
    if profile not in WINDOWS_SUPPORTED_PROFILES:
        raise HTTPException(status_code=400, detail="Unsupported Windows session profile. Use: codex, powershell, cmd.")
    if profile == "codex":
        codex_status = _windows_codex_profile_status()
        if not codex_status.get("supported"):
            raise HTTPException(
                status_code=409,
                detail=str(codex_status.get("detail") or "Windows Codex CLI is unavailable on this host."),
            )
    return profile


def _windows_session_stream_state_unlocked(session: str) -> Dict[str, Any]:
    session_id = _validate_session_name(session)
    state = WINDOWS_SESSION_STREAM_STATES.get(session_id)
    if state is None:
        state = {
            "seq": 0,
            "last_text": "",
            "events": [],
            "updated_at": time.time(),
        }
        WINDOWS_SESSION_STREAM_STATES[session_id] = state
    return state


def _windows_session_stream_event_payload(
    *,
    session: str,
    seq: int,
    event_type: str,
    text: str,
    profile: str = "",
    detail: str = "",
    state: str = "",
    current_command: str = "",
) -> Dict[str, Any]:
    payload = {
        "session": session,
        "pane_id": "winpty",
        "seq": seq,
        "type": event_type,
        "text": text,
        "detail": detail,
        "ts": time.time(),
    }
    if profile:
        payload["profile"] = profile
    if state:
        payload["state"] = state
    if current_command:
        payload["current_command"] = current_command
    return payload


def _publish_windows_session_stream_snapshot(
    session: str,
    text: str,
    *,
    screen_state: str = "",
    current_command: str = "",
) -> Optional[Dict[str, Any]]:
    session_id = _validate_session_name(session)
    with WINDOWS_SESSION_STREAM_LOCK:
        stream_state = _windows_session_stream_state_unlocked(session_id)
        previous = str(stream_state.get("last_text") or "")
        if text == previous:
            return None
        if stream_state["seq"] == 0:
            event_type = "snapshot"
            payload_text = text
        elif text.startswith(previous):
            event_type = "append"
            payload_text = text[len(previous):]
        else:
            event_type = "replace"
            payload_text = text
        stream_state["seq"] = int(stream_state.get("seq") or 0) + 1
        event = _windows_session_stream_event_payload(
            session=session_id,
            seq=stream_state["seq"],
            event_type=event_type,
            text=payload_text,
            state=screen_state,
            current_command=current_command,
        )
        stream_state["last_text"] = text
        stream_state["updated_at"] = time.time()
        stream_state["events"].append(event)
        if len(stream_state["events"]) > WINDOWS_SESSION_STREAM_REPLAY_MAX:
            stream_state["events"] = stream_state["events"][-WINDOWS_SESSION_STREAM_REPLAY_MAX:]
        return dict(event)


def _windows_session_stream_replay(session: str, since_seq: int) -> Tuple[List[Dict[str, Any]], Optional[Dict[str, Any]]]:
    with WINDOWS_SESSION_STREAM_LOCK:
        state = _windows_session_stream_state_unlocked(session)
        events = list(state.get("events") or [])
        if since_seq <= 0:
            return [], None
        replay = [dict(event) for event in events if int(event.get("seq") or 0) > since_seq]
        if replay:
            oldest = int(replay[0].get("seq") or 0)
            if oldest <= since_seq + 1:
                return replay, None
        if int(state.get("seq") or 0) <= 0:
            return [], None
        snapshot = _windows_session_stream_event_payload(
            session=session,
            seq=int(state.get("seq") or 0),
            event_type="snapshot",
            text=str(state.get("last_text") or ""),
        )
        return [], snapshot


def _windows_session_output_trim(text: str) -> str:
    value = str(text or "")
    if len(value) <= WINDOWS_SESSION_OUTPUT_MAX_CHARS:
        return value
    return value[-WINDOWS_SESSION_OUTPUT_MAX_CHARS:]


def _windows_session_snippet(text: str) -> str:
    value = str(text or "").strip()
    if not value:
        return ""
    return value.splitlines()[-1][:240]


def _windows_session_public_record(raw: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    item = dict(raw or {})
    profile = str(item.get("profile") or "codex").strip().lower() or "codex"
    return {
        "session": str(item.get("session") or "").strip(),
        "pane_id": "winpty",
        "current_command": str(item.get("current_command") or profile).strip() or profile,
        "cwd": str(item.get("cwd") or CODEX_WINDOWS_WORKDIR).strip() or CODEX_WINDOWS_WORKDIR,
        "state": str(item.get("state") or "starting").strip().lower() or "starting",
        "updated_at": float(item.get("updated_at") or time.time()),
        "last_seen_at": float(item.get("last_seen_at") or item.get("updated_at") or time.time()),
        "snippet": str(item.get("snippet") or ""),
        "model": str(item.get("model") or profile).strip() or profile,
        "reasoning_effort": str(item.get("reasoning_effort") or ""),
        "profile": profile,
        "closed_at": item.get("closed_at"),
        "can_resume": False,
    }


def _windows_recent_closed_push_unlocked(record: Dict[str, Any]) -> None:
    session_id = str(record.get("session") or "").strip()
    if not session_id:
        return
    next_items = [
        dict(item)
        for item in WINDOWS_RECENT_CLOSED
        if str(item.get("session") or "").strip() != session_id
    ]
    next_items.insert(0, dict(record))
    del next_items[WINDOWS_SESSION_RECENT_CLOSED_MAX:]
    WINDOWS_RECENT_CLOSED[:] = next_items


def _windows_normalize_cwd(raw: Any) -> str:
    candidate = str(raw or "").strip()
    if not candidate:
        candidate = CODEX_WINDOWS_WORKDIR
    elif candidate.startswith("/"):
        candidate = _wsl_to_windows_path(candidate) or candidate
    candidate = os.path.abspath(os.path.expandvars(os.path.expanduser(candidate)))
    if not os.path.isdir(candidate):
        raise HTTPException(status_code=400, detail=f"Windows cwd does not exist: {candidate}")
    return candidate


def _windows_session_command_label(profile: str) -> str:
    if profile == "powershell":
        return "powershell.exe"
    if profile == "cmd":
        return "cmd.exe"
    return "codex"


def _windows_codex_argv(model: str, reasoning_effort: str) -> List[str]:
    argv = [CODEX_WINDOWS_CLI]
    if model:
        argv.extend(["--model", model])
    if reasoning_effort:
        argv.extend(["--reasoning-effort", reasoning_effort])
    return argv


def _windows_session_spawn_argv(profile: str, model: str, reasoning_effort: str) -> List[str]:
    if profile == "powershell":
        return ["powershell.exe", "-NoLogo"]
    if profile == "cmd":
        return ["cmd.exe"]
    return _windows_codex_argv(model, reasoning_effort)


def _windows_session_entry(session: str) -> Dict[str, Any]:
    session_id = _validate_session_name(session)
    with WINDOWS_SESSIONS_LOCK:
        entry = WINDOWS_SESSIONS.get(session_id)
        if not entry:
            raise HTTPException(status_code=404, detail=f"Windows session '{session_id}' was not found.")
        return entry


def _windows_session_finalize(session: str, reason: str = "closed") -> Optional[Dict[str, Any]]:
    session_id = _validate_session_name(session)
    now = time.time()
    with WINDOWS_SESSIONS_LOCK:
        entry = WINDOWS_SESSIONS.pop(session_id, None)
        if not entry:
            return None
        process = entry.get("process")
        exit_code = None
        try:
            if process is not None:
                exit_code = process.exitstatus
        except Exception:
            exit_code = None
        if reason in {"spawn_failed", "reader_error", "exited_error"}:
            final_state = "error"
        elif isinstance(exit_code, int) and exit_code not in {0, None}:
            final_state = "error"
        elif reason in {"closed", "stopped", "remote_stop"}:
            final_state = "done"
        else:
            final_state = str(entry.get("state") or "done").strip().lower() or "done"
        closed_record = _windows_session_public_record({
            **entry,
            "session": session_id,
            "state": final_state,
            "updated_at": now,
            "last_seen_at": now,
            "closed_at": now,
            "snippet": _windows_session_snippet(str(entry.get("last_text") or entry.get("snippet") or "")),
        })
        _windows_recent_closed_push_unlocked(closed_record)
    with WINDOWS_SESSION_STREAM_LOCK:
        stream_state = _windows_session_stream_state_unlocked(session_id)
        stream_state["seq"] = int(stream_state.get("seq") or 0) + 1
        event = _windows_session_stream_event_payload(
            session=session_id,
            seq=stream_state["seq"],
            event_type="status",
            text="",
            detail=reason,
            state=str(closed_record.get("state") or ""),
            current_command=str(closed_record.get("current_command") or ""),
        )
        stream_state["updated_at"] = now
        stream_state["events"].append(event)
        if len(stream_state["events"]) > WINDOWS_SESSION_STREAM_REPLAY_MAX:
            stream_state["events"] = stream_state["events"][-WINDOWS_SESSION_STREAM_REPLAY_MAX:]
    return closed_record


def _windows_session_reader(session: str) -> None:
    session_id = _validate_session_name(session)
    while True:
        try:
            entry = _windows_session_entry(session_id)
        except HTTPException:
            return
        process = entry.get("process")
        if process is None:
            _windows_session_finalize(session_id, "reader_error")
            return
        try:
            chunk = process.read(4096)
        except EOFError:
            try:
                if process.isalive():
                    time.sleep(0.05)
                    continue
            except Exception:
                pass
            break
        except Exception:
            _windows_session_finalize(session_id, "reader_error")
            return
        if not chunk:
            try:
                if not process.isalive():
                    break
            except Exception:
                break
            continue
        _host_keep_awake_pulse()
        with WINDOWS_SESSIONS_LOCK:
            live_entry = WINDOWS_SESSIONS.get(session_id)
            if not live_entry:
                return
            next_text = _windows_session_output_trim(str(live_entry.get("last_text") or "") + str(chunk))
            current_command = str(live_entry.get("current_command") or _windows_session_command_label(str(live_entry.get("profile") or "")))
            current_state = (
                _infer_progress_state(next_text, current_command)
                if str(live_entry.get("profile") or "") == "codex"
                else "running"
            )
            live_entry.update({
                "last_text": next_text,
                "snippet": _windows_session_snippet(next_text),
                "state": current_state,
                "updated_at": time.time(),
                "last_seen_at": time.time(),
            })
        _publish_windows_session_stream_snapshot(
            session_id,
            next_text,
            screen_state=current_state,
            current_command=current_command,
        )
    _windows_session_finalize(session_id, "exited")


def _windows_session_write(session: str, text: str) -> None:
    entry = _windows_session_entry(session)
    process = entry.get("process")
    if process is None:
        raise HTTPException(status_code=409, detail=f"Windows session '{session}' is not writable.")
    io_lock = entry.get("io_lock")
    if io_lock is None:
        io_lock = threading.Lock()
        with WINDOWS_SESSIONS_LOCK:
            current = WINDOWS_SESSIONS.get(session)
            if current is not None:
                current["io_lock"] = io_lock
    with io_lock:
        try:
            process.write(text)
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"Could not write to Windows session: {type(exc).__name__}: {exc}")


def _windows_runtime_stop_all_sessions(reason: str = "stopped") -> None:
    with WINDOWS_SESSIONS_LOCK:
        session_ids = list(WINDOWS_SESSIONS.keys())
    for session_id in session_ids:
        entry = None
        with WINDOWS_SESSIONS_LOCK:
            entry = WINDOWS_SESSIONS.get(session_id)
        process = (entry or {}).get("process")
        try:
            if process is not None:
                process.terminate(force=True)
        except Exception:
            pass
        _windows_session_finalize(session_id, reason)

def _tmux_server_running(stderr: str) -> bool:
    s = (stderr or "").lower()
    return not ("no server running" in s or "failed to connect to server" in s)

WIN_INTERRUPT_EXIT_CODES = {3221225786, -1073741510}  # 0xC000013A (Ctrl+C / console interrupt)

def _is_windows_interrupt(exit_code: Optional[int]) -> bool:
    if exit_code is None:
        return False
    return exit_code in WIN_INTERRUPT_EXIT_CODES

def _wsl_run_kwargs() -> Dict[str, Any]:
    kwargs: Dict[str, Any] = {}
    if os.name != "nt":
        return kwargs

    creationflags = 0
    creationflags |= getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    # Avoid DETACHED_PROCESS because it breaks stdout capture for wsl.exe.
    creationflags |= getattr(subprocess, "CREATE_NO_WINDOW", 0)

    if creationflags:
        kwargs["creationflags"] = creationflags

    if hasattr(subprocess, "STARTUPINFO"):
        startupinfo = subprocess.STARTUPINFO()
        if hasattr(subprocess, "STARTF_USESHOWWINDOW"):
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            startupinfo.wShowWindow = 0
        kwargs["startupinfo"] = startupinfo

    kwargs["stdin"] = subprocess.DEVNULL
    return kwargs

def _wsl_executable() -> str:
    if os.name != "nt":
        return WSL_EXE
    if WSL_EXE and WSL_EXE != "wsl":
        return WSL_EXE
    windir = os.environ.get("WINDIR", r"C:\Windows")
    sys32_wsl = os.path.join(windir, "System32", "wsl.exe")
    if os.path.exists(sys32_wsl):
        return sys32_wsl
    return "wsl"


def _parse_wsl_list_output(stdout: str, distro_name: str) -> Dict[str, Any]:
    wanted = str(distro_name or "").strip().lower()
    lines = [str(line or "").rstrip() for line in (stdout or "").splitlines()]
    for raw_line in lines:
        line = raw_line.replace("\x00", "").strip()
        if not line or line.lower().startswith("name") or set(line) <= {"-", " "}:
            continue
        if line.startswith("*"):
            line = line[1:].strip()
        parts = [part.strip() for part in re.split(r"\s{2,}", line) if part.strip()]
        if len(parts) < 2:
            continue
        name = parts[0].lower()
        if name != wanted:
            continue
        state = parts[1].strip().lower()
        if state == "running":
            return {"state": "running", "detail": f"{distro_name} is running.", "can_start": False, "can_stop": True}
        if state == "stopped":
            return {"state": "stopped", "detail": f"{distro_name} is stopped.", "can_start": True, "can_stop": False}
        return {"state": "unknown", "detail": f"{distro_name} reported state '{parts[1]}'.", "can_start": False, "can_stop": False}
    return {"state": "missing", "detail": f"{distro_name} is not installed.", "can_start": False, "can_stop": False}


def _wsl_runtime_status_payload() -> Dict[str, Any]:
    if os.name != "nt":
        return {
            "state": "running",
            "detail": "Non-Windows host runtime assumed active.",
            "can_start": False,
            "can_stop": False,
            "distro": WSL_DISTRO,
        }
    try:
        result = subprocess.run(
            [_wsl_executable(), "-l", "-v"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=8,
            **_wsl_run_kwargs(),
        )
    except Exception as exc:
        return {
            "state": "unknown",
            "detail": f"Could not inspect WSL runtime: {type(exc).__name__}: {exc}",
            "can_start": False,
            "can_stop": False,
            "distro": WSL_DISTRO,
        }
    stdout = (result.stdout or "").strip()
    stderr = (result.stderr or "").strip()
    if result.returncode != 0 and not stdout:
        detail = stderr or stdout or f"wsl.exe exited with {result.returncode}."
        return {
            "state": "unknown",
            "detail": detail,
            "can_start": False,
            "can_stop": False,
            "distro": WSL_DISTRO,
        }
    parsed = _parse_wsl_list_output(stdout, WSL_DISTRO)
    parsed["distro"] = WSL_DISTRO
    return parsed


def _start_wsl_runtime() -> Dict[str, Any]:
    status = _wsl_runtime_status_payload()
    if status.get("state") == "running":
        return {"ok": True, **status}
    if status.get("state") == "missing":
        return {"ok": False, **status}
    try:
        result = subprocess.run(
            [_wsl_executable(), "-d", WSL_DISTRO, "--", "bash", "-lc", "tmux start-server >/dev/null 2>&1 || true; printf ready"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=20,
            **_wsl_run_kwargs(),
        )
    except Exception as exc:
        return {
            "ok": False,
            "state": "unknown",
            "detail": f"Could not start WSL runtime: {type(exc).__name__}: {exc}",
            "can_start": True,
            "can_stop": False,
            "distro": WSL_DISTRO,
        }
    fresh = _wsl_runtime_status_payload()
    return {
        "ok": bool(result.returncode == 0 and fresh.get("state") == "running"),
        **fresh,
    }


def _stop_wsl_runtime() -> Dict[str, Any]:
    status = _wsl_runtime_status_payload()
    if status.get("state") == "stopped":
        return {"ok": True, **status}
    if status.get("state") == "missing":
        return {"ok": False, **status}
    try:
        result = subprocess.run(
            [_wsl_executable(), "--terminate", WSL_DISTRO],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=12,
            **_wsl_run_kwargs(),
        )
    except Exception as exc:
        return {
            "ok": False,
            "state": "unknown",
            "detail": f"Could not stop WSL runtime: {type(exc).__name__}: {exc}",
            "can_start": False,
            "can_stop": True,
            "distro": WSL_DISTRO,
        }
    fresh = _wsl_runtime_status_payload()
    return {
        "ok": bool(result.returncode == 0 and fresh.get("state") == "stopped"),
        **fresh,
    }


def run_wsl_bash(command: str, timeout_s: int = 30) -> Dict[str, Any]:
    args = [_wsl_executable(), "-d", WSL_DISTRO, "--", "bash", "-lc", command]
    max_attempts = 2 if os.name == "nt" else 1
    attempt = 0
    while attempt < max_attempts:
        attempt += 1
        try:
            p = subprocess.run(
                args,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout_s,
                **_wsl_run_kwargs(),
            )
            if os.name == "nt" and _is_windows_interrupt(p.returncode) and attempt < max_attempts:
                time.sleep(0.2)
                continue
            result = {
                "exit_code": p.returncode,
                "stdout": (p.stdout or "").rstrip(),
                "stderr": (p.stderr or "").rstrip(),
                "attempts": attempt,
            }
            if os.name == "nt" and _is_windows_interrupt(p.returncode):
                result["error"] = "interrupted"
            return result
        except subprocess.TimeoutExpired:
            return {"exit_code": 124, "stdout": "", "stderr": f"timeout after {timeout_s}s", "attempts": attempt}
        except Exception as e:
            return {"exit_code": 125, "stdout": "", "stderr": f"exception: {type(e).__name__}: {e}", "attempts": attempt}

# -------------------------
# WSL path helpers
# -------------------------
def _norm_posix(p: str) -> str:
    return posixpath.normpath(p).replace("\\", "/")


def _windows_to_wsl_path(path: str) -> str:
    text = str(path or "").strip()
    if not text:
        return ""
    if len(text) >= 3 and text[1] == ":" and text[2] in {"\\", "/"}:
        drive = text[0].lower()
        rest = text[2:].replace("\\", "/").lstrip("/")
        return _norm_posix(f"/mnt/{drive}/{rest}")
    if text.startswith(r"\\wsl$\\"):
        parts = text.split("\\")
        if len(parts) >= 5:
            return _norm_posix("/" + "/".join(parts[4:]))
    return text


def _wsl_to_windows_path(wsl_abs_path: str) -> str:
    path = _norm_posix(str(wsl_abs_path or ""))
    match = re.match(r"^/mnt/([a-zA-Z])(?:/(.*))?$", path)
    if not match:
        return ""
    drive = match.group(1).upper()
    rest = (match.group(2) or "").replace("/", "\\")
    return f"{drive}:\\{rest}" if rest else f"{drive}:\\"


def _display_path_for_wsl(wsl_abs_path: str) -> str:
    return _wsl_to_windows_path(wsl_abs_path) or _norm_posix(wsl_abs_path)


def _path_under_root(path_value: str, root_value: str) -> bool:
    norm_path = _norm_posix(path_value)
    norm_root = _norm_posix(root_value)
    return norm_path == norm_root or norm_path.startswith(norm_root.rstrip("/") + "/")


def _browse_roots() -> List[Dict[str, str]]:
    candidates = [
        {"id": "workspace", "label": "Workspace", "path": _norm_posix(CODEX_FILE_ROOT)},
        {"id": "mnt-c", "label": "Windows C:", "path": "/mnt/c"},
        {"id": "mnt-d", "label": "Windows D:", "path": "/mnt/d"},
        {"id": "mnt-e", "label": "Windows E:", "path": "/mnt/e"},
    ]
    roots: List[Dict[str, str]] = []
    seen = set()
    for item in candidates:
        root_path = _norm_posix(item["path"])
        if not root_path.startswith("/") or root_path in seen:
            continue
        unc = _wsl_unc_path(root_path)
        if os.path.exists(unc):
            seen.add(root_path)
            roots.append({"id": item["id"], "label": item["label"], "path": root_path})
    return roots


def _resolve_wsl_path(user_path: str) -> str:
    """
    Resolve a user-provided path into an absolute WSL path under CODEX_FILE_ROOT.
    - If user_path starts with '/', treat it as absolute but still require it stays under root.
    - Otherwise treat it as relative to CODEX_FILE_ROOT.
    """
    if not user_path:
        raise HTTPException(status_code=400, detail="Missing path.")
    root = _norm_posix(CODEX_FILE_ROOT)
    if not root.startswith("/"):
        raise HTTPException(status_code=500, detail="CODEX_FILE_ROOT must be an absolute WSL path.")

    p = _windows_to_wsl_path(user_path.strip())
    if p.startswith("/"):
        resolved = _norm_posix(p)
    else:
        resolved = _norm_posix(posixpath.join(root, p))

    if not _path_under_root(resolved, root):
        raise HTTPException(status_code=403, detail=f"Path is outside allowed root: {root}")
    return resolved


def _resolve_session_access_path(user_path: str) -> str:
    if not user_path:
        raise HTTPException(status_code=400, detail="Missing path.")
    converted = _windows_to_wsl_path(user_path.strip())
    if not converted:
        raise HTTPException(status_code=400, detail="Missing path.")
    if converted.startswith("/"):
        resolved = _norm_posix(converted)
    else:
        resolved = _resolve_wsl_path(converted)
    allowed_roots = [root["path"] for root in _browse_roots()]
    if not any(_path_under_root(resolved, allowed_root) for allowed_root in allowed_roots):
        raise HTTPException(status_code=403, detail="Path is outside allowed browse roots.")
    return resolved


def _looks_like_windows_host_path(path_value: str) -> bool:
    candidate = str(path_value or "").strip().strip('"')
    if not candidate:
        return False
    return bool(re.match(r"^[A-Za-z]:[\\/]", candidate) or candidate.startswith("\\\\"))


def _resolve_existing_host_path(path_value: str) -> Dict[str, str]:
    host_path = _normalize_host_path(path_value)
    if not os.path.exists(host_path):
        raise HTTPException(status_code=404, detail="Host path not found.")
    item_kind = "directory" if os.path.isdir(host_path) else "file"
    return {
        "requested_path": path_value,
        "normalized_path": host_path,
        "opened_path": host_path,
        "item_kind": item_kind,
    }


def _strip_path_location_suffix(path_value: str) -> str:
    candidate = str(path_value or "").strip()
    if not candidate:
        return ""
    if candidate.startswith("<") and candidate.endswith(">") and len(candidate) > 2:
        candidate = candidate[1:-1].strip()
    hash_match = re.search(r"#L\d+(?:C\d+)?$", candidate)
    if hash_match:
        candidate = candidate[:hash_match.start()].rstrip()
    colon_match = re.search(r":\d+(?::\d+)?$", candidate)
    if colon_match:
        prefix = candidate[:colon_match.start()]
        if "/" in prefix or "\\" in prefix:
            candidate = prefix.rstrip()
    return candidate


def _resolve_openable_host_path(path_value: str) -> Dict[str, str]:
    cleaned = _strip_path_location_suffix(path_value)
    if not cleaned:
        raise HTTPException(status_code=400, detail="path is required.")
    if os.name == "nt" and _looks_like_windows_host_path(cleaned):
        return _resolve_existing_host_path(cleaned)
    resolved = _resolve_session_access_path(cleaned)
    unc = _wsl_unc_path(resolved)
    if not os.path.exists(unc):
        raise HTTPException(status_code=404, detail="Path not found.")
    item_kind = "directory" if os.path.isdir(unc) else "file"
    windows_path = _wsl_to_windows_path(resolved)
    launch_path = windows_path or unc
    return {
        "requested_path": cleaned,
        "normalized_path": resolved,
        "opened_path": launch_path,
        "item_kind": item_kind,
    }


def _open_resolved_host_path(info: Dict[str, str]) -> Dict[str, Any]:
    opened_path = info["opened_path"]
    try:
        os.startfile(opened_path)
    except OSError as exc:
        raise HTTPException(status_code=500, detail=f"Could not open path: {exc}")
    return {
        "ok": True,
        "path": info["requested_path"],
        "normalized_path": info["normalized_path"],
        "opened_path": opened_path,
        "item_kind": info["item_kind"],
        "detail": f"Opened {info['item_kind']}: {opened_path}",
    }


def _reveal_resolved_host_path(info: Dict[str, str]) -> Dict[str, Any]:
    opened_path = info["opened_path"]
    if info["item_kind"] == "file":
        try:
            subprocess.Popen(
                ["explorer.exe", f"/select,{opened_path}"],
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"Could not reveal path: {exc}")
    else:
        try:
            os.startfile(opened_path)
        except OSError as exc:
            raise HTTPException(status_code=500, detail=f"Could not open directory: {exc}")
    return {
        "ok": True,
        "path": info["requested_path"],
        "normalized_path": info["normalized_path"],
        "opened_path": opened_path,
        "item_kind": info["item_kind"],
        "detail": f"Revealed {info['item_kind']}: {opened_path}",
    }


def _desktop_stream_transport_payload() -> Dict[str, Any]:
    detail = ""
    if AIORTC_AVAILABLE and DESKTOP_WEBRTC_ENABLED:
        detail = "WebRTC transport is enabled on this host."
    elif not AIORTC_AVAILABLE:
        detail = f"WebRTC fallback active because aiortc is unavailable ({AIORTC_IMPORT_ERROR or 'import_failed'})."
    elif not DESKTOP_WEBRTC_ENABLED:
        detail = "WebRTC transport is installed but disabled by CODEX_DESKTOP_WEBRTC."
    else:
        detail = "WebRTC fallback active."
    return {
        "desktop_stream_transport": DESKTOP_STREAM_PREFERRED_TRANSPORT,
        "desktop_stream_fallback": DESKTOP_STREAM_FALLBACK_TRANSPORT,
        "desktop_webrtc_available": bool(AIORTC_AVAILABLE),
        "desktop_webrtc_enabled": bool(DESKTOP_WEBRTC_ENABLED and AIORTC_AVAILABLE),
        "desktop_webrtc_detail": detail,
    }


def _desktop_webrtc_payload_session_id(value: Any) -> str:
    session_id = _clean_entity_id(str(value or ""))
    if not session_id:
        raise HTTPException(status_code=400, detail="session_id is required.")
    return session_id


def _desktop_webrtc_candidate_payload(candidate: Dict[str, Any]) -> Any:
    if not AIORTC_AVAILABLE or candidate_from_sdp is None:
        raise HTTPException(status_code=503, detail="WebRTC support is unavailable on this host.")
    candidate_sdp = str(candidate.get("candidate") or "").strip()
    if not candidate_sdp:
        return None
    parsed = candidate_from_sdp(candidate_sdp[10:] if candidate_sdp.startswith("candidate:") else candidate_sdp)
    parsed.sdpMid = candidate.get("sdpMid")
    parsed.sdpMLineIndex = candidate.get("sdpMLineIndex")
    return parsed


def _desktop_webrtc_store_session(
    session_id: str,
    pc: Any,
    track: Any,
    sender: Any = None,
    transceiver: Any = None,
) -> None:
    with DESKTOP_WEBRTC_SESSION_LOCK:
        DESKTOP_WEBRTC_SESSIONS[session_id] = {
            "pc": pc,
            "track": track,
            "sender": sender,
            "transceiver": transceiver,
            "created_at": time.time(),
            "sent_local_candidate_keys": set(),
            "local_candidates_complete": False,
            "last_local_candidate_count": 0,
            "local_description_ready": False,
            "local_description_error": "",
            "local_description_task": None,
        }


def _desktop_webrtc_pop_session(session_id: str) -> Optional[Dict[str, Any]]:
    with DESKTOP_WEBRTC_SESSION_LOCK:
        return DESKTOP_WEBRTC_SESSIONS.pop(session_id, None)


def _desktop_webrtc_get_session(session_id: str) -> Optional[Dict[str, Any]]:
    with DESKTOP_WEBRTC_SESSION_LOCK:
        return DESKTOP_WEBRTC_SESSIONS.get(session_id)


def _desktop_webrtc_session_connection_state(session: Optional[Dict[str, Any]]) -> str:
    if not isinstance(session, dict):
        return ""
    try:
        pc = session.get("pc")
        return str(getattr(pc, "connectionState", "") or "").strip().lower()
    except Exception:
        return ""


def _desktop_webrtc_collect_evictable_session_ids_for_new_offer() -> List[str]:
    with DESKTOP_WEBRTC_SESSION_LOCK:
        snapshot = list(DESKTOP_WEBRTC_SESSIONS.items())
    if len(snapshot) < DESKTOP_WEBRTC_MAX_SESSIONS:
        return []

    stale_candidates: List[Tuple[int, float, str]] = []
    now = time.time()
    for session_id, session in snapshot:
        created_at = float((session or {}).get("created_at") or 0.0)
        age_s = max(0.0, now - created_at)
        ready = bool((session or {}).get("local_description_ready"))
        state = _desktop_webrtc_session_connection_state(session)
        if state in {"closed", "failed", "disconnected"}:
            stale_candidates.append((0, created_at, session_id))
            continue
        if state in {"", "new", "connecting"} and age_s >= 2.0:
            priority = 1 if not ready else 2
            stale_candidates.append((priority, created_at, session_id))

    if not stale_candidates:
        return []

    keep_limit = max(0, DESKTOP_WEBRTC_MAX_SESSIONS - 1)
    needed = max(1, len(snapshot) - keep_limit)
    stale_candidates.sort(key=lambda item: (item[0], item[1], item[2]))
    return [session_id for _priority, _created_at, session_id in stale_candidates[:needed]]


async def _desktop_webrtc_shutdown_session_resources(session: Optional[Dict[str, Any]], session_id: str = "") -> None:
    if not session:
        return
    track = session.get("track")
    pc = session.get("pc")
    task = session.get("local_description_task")
    if task is not None:
        try:
            task.cancel()
        except Exception:
            pass
    try:
        if track is not None:
            track.stop()
    except Exception:
        pass
    try:
        if pc is not None:
            await asyncio.wait_for(pc.close(), timeout=1.5)
    except Exception as exc:
        if session_id:
            print(
                "Desktop WebRTC session="
                f"{session_id} close timed out or failed: {type(exc).__name__}: {exc}",
                flush=True,
            )
    return


async def _desktop_webrtc_close_session(session_id: str) -> None:
    session = _desktop_webrtc_pop_session(session_id)
    await _desktop_webrtc_shutdown_session_resources(session, session_id=session_id)


async def _desktop_webrtc_close_all_sessions() -> int:
    with DESKTOP_WEBRTC_SESSION_LOCK:
        sessions = list(DESKTOP_WEBRTC_SESSIONS.items())
        DESKTOP_WEBRTC_SESSIONS.clear()
    for session_id, session in sessions:
        await _desktop_webrtc_shutdown_session_resources(session, session_id=session_id)
    return len(sessions)


async def _desktop_webrtc_evict_stale_sessions_for_new_offer() -> int:
    session_ids = _desktop_webrtc_collect_evictable_session_ids_for_new_offer()
    if not session_ids:
        return 0
    evicted: List[Tuple[str, Dict[str, Any]]] = []
    with DESKTOP_WEBRTC_SESSION_LOCK:
        for session_id in session_ids:
            session = DESKTOP_WEBRTC_SESSIONS.pop(session_id, None)
            if session is not None:
                evicted.append((session_id, session))
    for session_id, session in evicted:
        await _desktop_webrtc_shutdown_session_resources(session, session_id=session_id)
    if evicted:
        print(
            "Desktop WebRTC evicted stale sessions before new offer: "
            + ",".join(session_id for session_id, _session in evicted),
            flush=True,
        )
    return len(evicted)


async def _desktop_webrtc_wait_for_ice(pc: Any, timeout_s: float = 1.5) -> None:
    deadline = time.time() + max(0.2, timeout_s)
    while time.time() < deadline:
        local = getattr(pc, "localDescription", None)
        sdp = str(getattr(local, "sdp", "") or "")
        if getattr(pc, "iceGatheringState", "") == "complete" or "candidate:" in sdp:
            return
        await asyncio.sleep(0.1)


def _desktop_webrtc_iter_media_contexts(pc: Any) -> List[Tuple[int, Any, Any, Any]]:
    contexts: List[Tuple[int, Any, Any, Any]] = []
    transceivers = list(getattr(pc, "_RTCPeerConnection__transceivers", []) or [])
    for index, transceiver in enumerate(transceivers):
        if getattr(transceiver, "kind", "") not in {"audio", "video"}:
            continue
        try:
            dtls_transport = transceiver.receiver.transport
            ice_transport = dtls_transport.transport
            gatherer = ice_transport.iceGatherer
        except Exception:
            continue
        contexts.append((index, transceiver, dtls_transport, gatherer))
    return contexts


def _desktop_webrtc_preferred_local_host(value: Any) -> str:
    try:
        ip_value = ipaddress.ip_address(str(value or "").strip())
    except Exception:
        return ""
    if ip_value.version != 4 or ip_value.is_loopback:
        return ""
    return str(ip_value)


def _desktop_webrtc_constrain_local_gathering(pc: Any, preferred_host: Any) -> str:
    host = _desktop_webrtc_preferred_local_host(preferred_host)
    if not host:
        return ""
    for _index, _transceiver, _dtls_transport, gatherer in _desktop_webrtc_iter_media_contexts(pc):
        connection = getattr(gatherer, "_connection", None)
        if connection is None:
            continue
        try:
            connection._use_ipv4 = True
            connection._use_ipv6 = False
            if getattr(connection, "_local_candidates_start", False):
                continue

            async def _gather_candidates_with_preferred(
                _connection: Any = connection,
                _preferred_host: str = host,
            ) -> None:
                if _connection._local_candidates_start:
                    return
                _connection._local_candidates_start = True
                coros = [
                    _connection.get_component_candidates(component=component, addresses=[_preferred_host])
                    for component in _connection._components
                ]
                for candidates in await asyncio.gather(*coros):
                    _connection._local_candidates += candidates
                _connection._local_candidates_end = True

            connection.gather_candidates = _gather_candidates_with_preferred
        except Exception:
            continue
    return host


async def _desktop_webrtc_wait_for_first_candidate(
    pc: Any,
    timeout_s: float = 0.35,
    gather_task: Optional[asyncio.Task] = None,
) -> bool:
    deadline = time.time() + max(0.05, timeout_s)
    while time.time() < deadline:
        for _index, _transceiver, _dtls_transport, gatherer in _desktop_webrtc_iter_media_contexts(pc):
            try:
                if list(gatherer.getLocalCandidates() or []):
                    return True
                if getattr(gatherer, "state", "") == "completed":
                    return True
            except Exception:
                continue
        if gather_task is not None and gather_task.done():
            return True
        await asyncio.sleep(0.03)
    return False


def _desktop_webrtc_collect_local_candidates(session: Dict[str, Any]) -> Tuple[List[Dict[str, Any]], bool]:
    if not AIORTC_AVAILABLE or candidate_to_sdp is None:
        return [], True
    pc = session.get("pc")
    if pc is None:
        return [], True
    items: List[Dict[str, Any]] = []
    seen: set[Tuple[str, str, int]] = set()
    complete = True
    for index, transceiver, _dtls_transport, gatherer in _desktop_webrtc_iter_media_contexts(pc):
        mid = str(getattr(transceiver, "mid", "") or "")
        state = str(getattr(gatherer, "state", "") or "")
        if state != "completed":
            complete = False
        try:
            local_candidates = list(gatherer.getLocalCandidates() or [])
        except Exception:
            local_candidates = []
        for candidate in local_candidates:
            try:
                candidate_sdp = "candidate:" + candidate_to_sdp(candidate)
            except Exception:
                continue
            key = (candidate_sdp, mid, index)
            if key in seen:
                continue
            seen.add(key)
            items.append(
                {
                    "candidate": candidate_sdp,
                    "sdpMid": mid or None,
                    "sdpMLineIndex": index,
                }
            )
    return items, complete


def _desktop_webrtc_drain_local_candidates(session: Dict[str, Any]) -> Tuple[List[Dict[str, Any]], bool]:
    items, complete = _desktop_webrtc_collect_local_candidates(session)
    sent = session.setdefault("sent_local_candidate_keys", set())
    pending: List[Dict[str, Any]] = []
    for item in items:
        key = (
            str(item.get("candidate") or ""),
            str(item.get("sdpMid") or ""),
            int(item.get("sdpMLineIndex") or 0),
        )
        if key in sent:
            continue
        sent.add(key)
        pending.append(item)
    session["local_candidates_complete"] = complete
    session["last_local_candidate_count"] = len(items)
    return pending, complete


async def _desktop_webrtc_set_local_answer_fast(
    session_id: str,
    pc: Any,
    answer: Any,
) -> Any:
    if not AIORTC_AVAILABLE or aiortc_rtcpeerconnection is None:
        await pc.setLocalDescription(answer)
        return pc.localDescription

    started_at = time.perf_counter()
    try:
        description = aiortc_rtcpeerconnection.sdp.SessionDescription.parse(answer.sdp)
        description.type = answer.type
        pc._RTCPeerConnection__validate_description(description, is_local=True)
        pc._RTCPeerConnection__setSignalingState("stable")

        for index, media in enumerate(description.media):
            mid = media.rtp.muxId
            pc._RTCPeerConnection__seenMids.add(mid)
            if media.kind in ["audio", "video"]:
                transceiver = pc._RTCPeerConnection__getTransceiverByMLineIndex(index)
                transceiver._set_mid(mid)
            elif media.kind == "application" and getattr(pc, "_RTCPeerConnection__sctp", None) is not None:
                pc._RTCPeerConnection__sctp.mid = mid

        for index, media in enumerate(description.media):
            if media.kind in ["audio", "video"]:
                transceiver = pc._RTCPeerConnection__getTransceiverByMLineIndex(index)
                transceiver.receiver.transport._set_role(media.dtls.role)
            elif media.kind == "application" and getattr(pc, "_RTCPeerConnection__sctp", None) is not None:
                pc._RTCPeerConnection__sctp.transport._set_role(media.dtls.role)

        for transceiver in list(getattr(pc, "_RTCPeerConnection__transceivers", []) or []):
            transceiver._setCurrentDirection(
                aiortc_rtcpeerconnection.and_direction(transceiver.direction, transceiver._offerDirection)
            )

        gather_task = asyncio.create_task(pc._RTCPeerConnection__gather())
        first_candidate_ready = await _desktop_webrtc_wait_for_first_candidate(
            pc,
            timeout_s=0.9,
            gather_task=gather_task,
        )

        for index, media in enumerate(description.media):
            if media.kind in ["audio", "video"]:
                transceiver = pc._RTCPeerConnection__getTransceiverByMLineIndex(index)
                aiortc_rtcpeerconnection.add_transport_description(media, transceiver.receiver.transport)
            elif media.kind == "application" and getattr(pc, "_RTCPeerConnection__sctp", None) is not None:
                aiortc_rtcpeerconnection.add_transport_description(media, pc._RTCPeerConnection__sctp.transport)

        pc._RTCPeerConnection__currentLocalDescription = description
        pc._RTCPeerConnection__pendingLocalDescription = None
        asyncio.ensure_future(pc._RTCPeerConnection__connect())

        session = _desktop_webrtc_get_session(session_id)
        if session is not None:
            session["local_description_ready"] = bool(first_candidate_ready)

        async def _finish_local_answer() -> None:
            try:
                await gather_task
                for index, media in enumerate(description.media):
                    if media.kind in ["audio", "video"]:
                        transceiver = pc._RTCPeerConnection__getTransceiverByMLineIndex(index)
                        aiortc_rtcpeerconnection.add_transport_description(media, transceiver.receiver.transport)
                    elif media.kind == "application" and getattr(pc, "_RTCPeerConnection__sctp", None) is not None:
                        aiortc_rtcpeerconnection.add_transport_description(media, pc._RTCPeerConnection__sctp.transport)
                pc._RTCPeerConnection__currentLocalDescription = description
                asyncio.ensure_future(pc._RTCPeerConnection__connect())
                finished_session = _desktop_webrtc_get_session(session_id)
                if finished_session is not None:
                    finished_session["local_description_ready"] = True
                    finished_session["local_description_error"] = ""
                print(
                    "Desktop WebRTC session="
                    f"{session_id} local gather completed in {(time.perf_counter() - started_at) * 1000.0:.0f} ms",
                    flush=True,
                )
            except Exception as gather_exc:
                failed_session = _desktop_webrtc_get_session(session_id)
                if failed_session is not None:
                    failed_session["local_description_error"] = f"{type(gather_exc).__name__}: {gather_exc}"
                print(
                    f"Desktop WebRTC session={session_id} local gather failed: {type(gather_exc).__name__}: {gather_exc}",
                    flush=True,
                )

        session = _desktop_webrtc_get_session(session_id)
        if session is not None:
            session["local_description_task"] = asyncio.create_task(_finish_local_answer())
            session["local_description_error"] = ""
        return RTCSessionDescription(sdp=str(description), type=description.type)
    except Exception as exc:
        print(
            f"Desktop WebRTC session={session_id} fast local answer failed; using aiortc default: {type(exc).__name__}: {exc}",
            flush=True,
        )
        await pc.setLocalDescription(answer)
        return pc.localDescription


def _desktop_webrtc_preferred_video_codecs() -> List[Any]:
    if RTCRtpSender is None:
        return []
    try:
        capabilities = RTCRtpSender.getCapabilities("video")
        codecs = list(getattr(capabilities, "codecs", []) or [])
    except Exception:
        return []
    preferred_vp8: List[Any] = []
    preferred_h264: List[Any] = []
    fallbacks: List[Any] = []
    for codec in codecs:
        mime = str(getattr(codec, "mimeType", "") or "").lower()
        if not mime.startswith("video/"):
            continue
        if mime == "video/rtx":
            continue
        if mime == "video/h264":
            packetization_mode = str(getattr(codec, "parameters", {}).get("packetization-mode", "") or "")
            if packetization_mode == "1":
                preferred_h264.append(codec)
            else:
                fallbacks.append(codec)
        elif mime == "video/vp8":
            preferred_vp8.append(codec)
        else:
            fallbacks.append(codec)
    # Android tablets on this project have been significantly smoother with VP8
    # than with the currently negotiated H264 desktop stream. Keep H264 as a
    # fallback, but prefer VP8 first for the live remote session.
    return preferred_vp8 + preferred_h264 + fallbacks


def _desktop_webrtc_log_sender_state(session_id: str, sender: Any) -> None:
    if sender is None:
        print(f"Desktop WebRTC session={session_id} sender missing", flush=True)
        return
    track = getattr(sender, "track", None)
    started = getattr(sender, "_RTCRtpSender__started", None)
    rtp_task = getattr(sender, "_RTCRtpSender__rtp_task", None)
    rtcp_task = getattr(sender, "_RTCRtpSender__rtcp_task", None)
    print(
        "Desktop WebRTC session="
        f"{session_id} sender_state started={started}"
        f" track_kind={getattr(track, 'kind', None)}"
        f" track_id={getattr(track, 'id', None)}"
        f" rtp_task={'yes' if rtp_task is not None else 'no'}"
        f" rtcp_task={'yes' if rtcp_task is not None else 'no'}",
        flush=True,
    )
    if rtp_task is not None and getattr(rtp_task, "done", lambda: False)():
        exc = None
        try:
            exc = rtp_task.exception()
        except Exception as task_exc:
            exc = task_exc
        print(
            f"Desktop WebRTC session={session_id} rtp_task_done exception={type(exc).__name__ if exc else 'None'}:{exc}",
            flush=True,
        )


def _desktop_webrtc_sdp_video_summary(sdp: str) -> str:
    lines = []
    for raw in str(sdp or "").splitlines():
        line = raw.strip()
        if not line:
            continue
        if line.startswith("m=video") or line.startswith("a=rtpmap:") or line.startswith("a=fmtp:") or line.startswith("a=send") or line.startswith("a=recv"):
            lines.append(line)
    return " | ".join(lines[:18])


def _resolve_host_transfer_destination(mode: str = "default") -> Dict[str, Any]:
    _ensure_windows_host()
    normalized_mode = str(mode or "default").strip().lower() or "default"
    if normalized_mode in {"default", "downloads"}:
        dest_dir = _normalize_host_path(CODEX_HOST_TRANSFER_ROOT)
        os.makedirs(dest_dir, exist_ok=True)
        return {
            "mode": "default",
            "directory": dest_dir,
            "selected_path": "",
        }
    if normalized_mode not in {"focused", "send-here", "send_here"}:
        raise HTTPException(status_code=400, detail="Unsupported host transfer destination.")
    selection = _desktop_selected_paths()
    selected_path = _normalize_host_path(str(selection.get("path") or ""))
    dest_dir = selected_path if os.path.isdir(selected_path) else os.path.dirname(selected_path)
    if not dest_dir:
        raise HTTPException(status_code=400, detail="Focused Explorer selection does not resolve to a directory.")
    dest_dir = _normalize_host_path(dest_dir)
    os.makedirs(dest_dir, exist_ok=True)
    return {
        "mode": "focused",
        "directory": dest_dir,
        "selected_path": selected_path,
    }


def _resolve_browser_root(root_id: str) -> Dict[str, str]:
    normalized = str(root_id or "workspace").strip().lower() or "workspace"
    for root in _browse_roots():
        if root["id"] == normalized:
            return root
    raise HTTPException(status_code=404, detail="Browse root not available.")


def _resolve_browser_path(root_id: str, relative_path: str = "") -> str:
    root = _resolve_browser_root(root_id)
    rel = _windows_to_wsl_path(relative_path).strip()
    if not rel or rel == ".":
        return root["path"]
    if rel.startswith("/"):
        resolved = _norm_posix(rel)
    else:
        resolved = _norm_posix(posixpath.join(root["path"], rel))
    if not _path_under_root(resolved, root["path"]):
        raise HTTPException(status_code=403, detail="Browse path is outside the selected root.")
    return resolved


def _wsl_unc_path(wsl_abs_path: str) -> str:
    if not wsl_abs_path.startswith("/"):
        raise HTTPException(status_code=500, detail="Internal error: expected absolute WSL path.")
    return r"\\wsl$\%s%s" % (WSL_DISTRO, wsl_abs_path.replace("/", "\\"))

# -------------------------
# Auth helpers
# -------------------------
def _auth_token_from_request(request: Request) -> str:
    return (
        request.headers.get("x-auth-token")
        or request.cookies.get(CODEX_AUTH_COOKIE)
        or ""
    ).strip()


def _auth_token_from_websocket(websocket: WebSocket) -> str:
    header_token = str(websocket.headers.get("x-auth-token") or "").strip()
    cookie_token = str(websocket.cookies.get(CODEX_AUTH_COOKIE) or "").strip()
    query_token = str(websocket.query_params.get("token") or "").strip()
    return header_token or cookie_token or query_token


def _browser_entry_for_path(wsl_path: str) -> Dict[str, Any]:
    unc = _wsl_unc_path(wsl_path)
    is_dir = os.path.isdir(unc)
    stat_result = os.stat(unc)
    return {
        "name": os.path.basename(wsl_path.rstrip("/")) or wsl_path,
        "kind": "directory" if is_dir else "file",
        "display_path": _display_path_for_wsl(wsl_path),
        "wsl_path": wsl_path,
        "windows_path": _wsl_to_windows_path(wsl_path),
        "size_bytes": 0 if is_dir else int(stat_result.st_size),
        "mtime": int(stat_result.st_mtime * 1000),
    }


def _list_browser_entries(root_id: str, relative_path: str = "") -> Dict[str, Any]:
    root = _resolve_browser_root(root_id)
    current_wsl_path = _resolve_browser_path(root_id, relative_path)
    current_unc = _wsl_unc_path(current_wsl_path)
    if not os.path.exists(current_unc):
        raise HTTPException(status_code=404, detail="Browse path not found.")
    if not os.path.isdir(current_unc):
        raise HTTPException(status_code=400, detail="Browse path is not a directory.")

    items: List[Dict[str, Any]] = []
    try:
        names = sorted(os.listdir(current_unc), key=lambda value: value.lower())
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Could not list directory: {type(e).__name__}: {e}")

    for name in names:
        child_wsl = _norm_posix(posixpath.join(current_wsl_path, name))
        child_unc = _wsl_unc_path(child_wsl)
        try:
            items.append(_browser_entry_for_path(child_wsl))
        except Exception:
            continue

    relative = ""
    if current_wsl_path != root["path"]:
        relative = posixpath.relpath(current_wsl_path, root["path"])
        if relative == ".":
            relative = ""

    return {
        "ok": True,
        "root": root,
        "roots": _browse_roots(),
        "current_path": current_wsl_path,
        "current_relative_path": relative,
        "display_path": _display_path_for_wsl(current_wsl_path),
        "windows_path": _wsl_to_windows_path(current_wsl_path),
        "items": items,
    }

def _is_valid_auth_token(token: str) -> bool:
    if not CODEX_AUTH_REQUIRED:
        return True
    if not token:
        return False
    return secrets.compare_digest(token, CODEX_AUTH_TOKEN)


def _require_authenticated_request(request: Request) -> None:
    if _is_valid_auth_token(_auth_token_from_request(request)):
        return
    raise HTTPException(status_code=401, detail="Login required.")


def _is_local_client_request(request: Request) -> bool:
    try:
        client_host = str(getattr(getattr(request, "client", None), "host", "") or "").strip()
    except Exception:
        client_host = ""
    return _is_loopback_ip(client_host)


def _require_local_client_request(request: Request) -> None:
    if _is_local_client_request(request):
        return
    raise HTTPException(status_code=403, detail="This action is only available from the local laptop.")


def _is_localhost_label(host: str) -> bool:
    h = (host or "").strip().lower().strip("[]")
    return h in {"localhost", "127.0.0.1", "::1"}


def _is_loopback_ip(value: str) -> bool:
    host = (value or "").strip().lower().strip("[]")
    if not host:
        return False
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except Exception:
        return False


def _host_from_host_header(host_header: str) -> str:
    value = (host_header or "").strip()
    if not value:
        return ""
    if value.startswith("["):
        end = value.find("]")
        if end > 0:
            return value[1:end].lower()
    if ":" in value:
        return value.split(":", 1)[0].lower()
    return value.lower()


def _host_from_url_header(url_value: str) -> str:
    value = (url_value or "").strip()
    if not value:
        return ""
    try:
        parsed = urlparse(value)
        return (parsed.hostname or "").lower()
    except Exception:
        return ""

def _truthy_flag(v: Any) -> bool:
    return str(v or "").strip().lower() in {"1", "true", "yes", "on"}

def _falsy_flag(v: Any) -> bool:
    return str(v or "").strip().lower() in {"0", "false", "no", "off"}


def _request_is_https(request: Optional[Request]) -> bool:
    if request is None:
        return False
    try:
        scheme = (getattr(getattr(request, "url", None), "scheme", "") or "").strip().lower()
        if scheme == "https":
            return True
    except Exception:
        pass
    try:
        xf_proto = (request.headers.get("x-forwarded-proto") or "").strip().lower()
    except Exception:
        xf_proto = ""
    if xf_proto:
        # Proxy chains can include comma-separated values.
        if xf_proto.split(",", 1)[0].strip() == "https":
            return True
    try:
        forwarded = (request.headers.get("forwarded") or "").strip()
    except Exception:
        forwarded = ""
    if forwarded:
        m = re.search(r"proto=([^;,\s]+)", forwarded, flags=re.IGNORECASE)
        if m and m.group(1).strip().strip('"').lower() == "https":
            return True
    return False


def _cookie_secure_for_request(request: Optional[Request]) -> bool:
    mode = (CODEX_COOKIE_SECURE_MODE or "auto").strip().lower()
    if mode in {"always", "on", "true", "1", "yes"}:
        return True
    if mode in {"never", "off", "false", "0", "no"}:
        return False
    return _request_is_https(request)


def _desktop_global_enabled() -> bool:
    with DESKTOP_MODE_LOCK:
        return bool(DESKTOP_MODE_ENABLED)


def _desktop_alt_held() -> bool:
    with DESKTOP_ALT_LOCK:
        return bool(DESKTOP_ALT_HELD)


def _set_desktop_alt_held(value: bool) -> bool:
    global DESKTOP_ALT_HELD
    with DESKTOP_ALT_LOCK:
        DESKTOP_ALT_HELD = bool(value)
        return DESKTOP_ALT_HELD


def _desktop_release_alt_if_held() -> bool:
    if not _desktop_alt_held():
        return False
    try:
        _send_vk_up(VK_MENU)
    except Exception:
        pass
    _set_desktop_alt_held(False)
    return True


def _desktop_perf_snapshot() -> Dict[str, Any]:
    with DESKTOP_PERF_LOCK:
        return {
            "enabled": bool(DESKTOP_PERF_ENABLED),
            "active": bool(DESKTOP_PERF_ACTIVE),
            "snapshot_present": bool(DESKTOP_PERF_SNAPSHOT),
        }


def _apply_desktop_perf_mode() -> Dict[str, Any]:
    global DESKTOP_PERF_ACTIVE, DESKTOP_PERF_SNAPSHOT
    if os.name != "nt":
        return _desktop_perf_snapshot()
    with DESKTOP_PERF_LOCK:
        if not DESKTOP_PERF_ENABLED:
            return {
                "enabled": False,
                "active": False,
                "snapshot_present": bool(DESKTOP_PERF_SNAPSHOT),
            }
        if DESKTOP_PERF_ACTIVE and isinstance(DESKTOP_PERF_SNAPSHOT, dict):
            return {
                "enabled": True,
                "active": True,
                "snapshot_present": True,
            }
    wallpaper_path = _desktop_perf_wallpaper_path()
    restore_wallpaper_path = _desktop_perf_restore_wallpaper_path()
    script = _desktop_perf_powershell_helpers() + r"""
$ErrorActionPreference = 'Stop'
$desktop = Get-ItemProperty 'HKCU:\Control Panel\Desktop'
$metrics = Get-ItemProperty 'HKCU:\Control Panel\Desktop\WindowMetrics' -ErrorAction SilentlyContinue
$personalize = Get-ItemProperty 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Themes\Personalize' -ErrorAction SilentlyContinue
$colors = Get-ItemProperty 'HKCU:\Control Panel\Colors' -ErrorAction SilentlyContinue
$restoreWallpaperPath = '__RESTORE_WALLPAPER_PATH__'
$restoreWallpaperDir = Split-Path -Parent $restoreWallpaperPath
if ($restoreWallpaperDir -and -not (Test-Path $restoreWallpaperDir)) {
  New-Item -Path $restoreWallpaperDir -ItemType Directory -Force | Out-Null
}
$wallpaperCandidates = New-Object System.Collections.Generic.List[string]
if ($desktop.Wallpaper) {
  $wallpaperCandidates.Add([string]$desktop.Wallpaper) | Out-Null
}
$themesRoot = Join-Path $env:APPDATA 'Microsoft\Windows\Themes'
$transcodedWallpaper = Join-Path $themesRoot 'TranscodedWallpaper'
if (Test-Path $transcodedWallpaper) {
  $wallpaperCandidates.Add($transcodedWallpaper) | Out-Null
}
$cachedWallpaperDir = Join-Path $themesRoot 'CachedFiles'
if (Test-Path $cachedWallpaperDir) {
  $cachedWallpaper = Get-ChildItem -LiteralPath $cachedWallpaperDir -Filter 'CachedImage_*' -File -ErrorAction SilentlyContinue |
    Sort-Object LastWriteTime -Descending |
    Select-Object -First 1
  if ($cachedWallpaper) {
    $wallpaperCandidates.Add([string]$cachedWallpaper.FullName) | Out-Null
  }
}
$resolvedWallpaperSource = ''
foreach ($candidate in $wallpaperCandidates) {
  if (-not $candidate) { continue }
  try {
    $resolvedWallpaperSource = (Resolve-Path -LiteralPath $candidate -ErrorAction Stop).Path
    if ($resolvedWallpaperSource) { break }
  } catch {}
}
if ($resolvedWallpaperSource) {
  $img = $null
  try {
    $img = [System.Drawing.Image]::FromFile($resolvedWallpaperSource)
    $img.Save($restoreWallpaperPath, [System.Drawing.Imaging.ImageFormat]::Bmp)
  } finally {
    if ($img) { $img.Dispose() }
  }
}
$snapshot = [pscustomobject]@{
  wallpaper = [string]$desktop.Wallpaper
  wallpaper_restore_path = if (Test-Path $restoreWallpaperPath) { $restoreWallpaperPath } else { '' }
  wallpaper_source = [string]$resolvedWallpaperSource
  wallpaper_style = [string]$desktop.WallpaperStyle
  tile_wallpaper = [string]$desktop.TileWallpaper
  background = if ($colors) { [string]$colors.Background } else { '' }
  min_animate = if ($metrics) { [string]$metrics.MinAnimate } else { '' }
  enable_transparency = if ($personalize) { [string]$personalize.EnableTransparency } else { '' }
}
$wallpaperPath = '__WALLPAPER_PATH__'
$wallpaperDir = Split-Path -Parent $wallpaperPath
if ($wallpaperDir -and -not (Test-Path $wallpaperDir)) {
  New-Item -Path $wallpaperDir -ItemType Directory -Force | Out-Null
}
$bmp = New-Object System.Drawing.Bitmap 64, 64
$gfx = [System.Drawing.Graphics]::FromImage($bmp)
try {
  $gfx.Clear([System.Drawing.Color]::Black)
  $bmp.Save($wallpaperPath, [System.Drawing.Imaging.ImageFormat]::Bmp)
} finally {
  if ($gfx) { $gfx.Dispose() }
  if ($bmp) { $bmp.Dispose() }
}
Set-ItemProperty 'HKCU:\Control Panel\Desktop' -Name Wallpaper -Value $wallpaperPath
Set-ItemProperty 'HKCU:\Control Panel\Desktop' -Name WallpaperStyle -Value '0'
Set-ItemProperty 'HKCU:\Control Panel\Desktop' -Name TileWallpaper -Value '0'
if ($colors) {
  Set-ItemProperty 'HKCU:\Control Panel\Colors' -Name Background -Value '0 0 0'
}
if ($metrics) {
  Set-ItemProperty 'HKCU:\Control Panel\Desktop\WindowMetrics' -Name MinAnimate -Value '0'
}
if ($personalize) {
  Set-ItemProperty 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Themes\Personalize' -Name EnableTransparency -Value 0
}
Invoke-CodrexDesktopRefresh -WallpaperPath $wallpaperPath
$snapshot | ConvertTo-Json -Compress -Depth 4
"""
    script = script.replace("__WALLPAPER_PATH__", _ps_single_quote(wallpaper_path))
    script = script.replace("__RESTORE_WALLPAPER_PATH__", _ps_single_quote(restore_wallpaper_path))
    result = _run_powershell(script, timeout_s=12)
    if result.get("exit_code") != 0:
        return {
            "enabled": _desktop_perf_snapshot().get("enabled", False),
            "active": False,
            "snapshot_present": bool(DESKTOP_PERF_SNAPSHOT),
            "error": (result.get("stderr") or result.get("stdout") or "desktop_perf_apply_failed").strip(),
        }
    try:
        snapshot = json.loads(str(result.get("stdout") or "{}"))
    except Exception:
        snapshot = {}
    if not isinstance(snapshot, dict):
        snapshot = {}
    with DESKTOP_PERF_LOCK:
        DESKTOP_PERF_SNAPSHOT = snapshot
        DESKTOP_PERF_ACTIVE = True
        return {
            "enabled": bool(DESKTOP_PERF_ENABLED),
            "active": True,
            "snapshot_present": True,
        }


def _restore_desktop_perf_mode() -> Dict[str, Any]:
    global DESKTOP_PERF_ACTIVE, DESKTOP_PERF_SNAPSHOT
    if os.name != "nt":
        return _desktop_perf_snapshot()
    with DESKTOP_PERF_LOCK:
        snapshot = dict(DESKTOP_PERF_SNAPSHOT or {})
        active = bool(DESKTOP_PERF_ACTIVE)
    if not active:
        return {
            "enabled": _desktop_perf_snapshot().get("enabled", False),
            "active": False,
            "snapshot_present": bool(snapshot),
        }
    snapshot_json = json.dumps(snapshot).encode("utf-8")
    snapshot_b64 = base64.b64encode(snapshot_json).decode("ascii")
    script = _desktop_perf_powershell_helpers() + (
        "$ErrorActionPreference = 'Stop'; "
        "$snapshotJson = [System.Text.Encoding]::UTF8.GetString([Convert]::FromBase64String('" + snapshot_b64 + "')); "
        "$snapshot = $snapshotJson | ConvertFrom-Json; "
        "$wallpaper = [string]$snapshot.wallpaper; "
        "if ($snapshot.wallpaper_restore_path -and (Test-Path ([string]$snapshot.wallpaper_restore_path))) { "
        "  $wallpaper = [string]$snapshot.wallpaper_restore_path "
        "}; "
        "Set-ItemProperty 'HKCU:\\Control Panel\\Desktop' -Name Wallpaper -Value $wallpaper; "
        "Set-ItemProperty 'HKCU:\\Control Panel\\Desktop' -Name WallpaperStyle -Value ([string]$snapshot.wallpaper_style); "
        "Set-ItemProperty 'HKCU:\\Control Panel\\Desktop' -Name TileWallpaper -Value ([string]$snapshot.tile_wallpaper); "
        "if ($snapshot.background -ne $null) { Set-ItemProperty 'HKCU:\\Control Panel\\Colors' -Name Background -Value ([string]$snapshot.background) }; "
        "if ($snapshot.min_animate -ne $null) { Set-ItemProperty 'HKCU:\\Control Panel\\Desktop\\WindowMetrics' -Name MinAnimate -Value ([string]$snapshot.min_animate) }; "
        "if ($snapshot.enable_transparency -ne $null -and [string]$snapshot.enable_transparency -ne '') { "
        "  Set-ItemProperty 'HKCU:\\Software\\Microsoft\\Windows\\CurrentVersion\\Themes\\Personalize' -Name EnableTransparency -Value ([int]$snapshot.enable_transparency) "
        "}; "
        "Invoke-CodrexDesktopRefresh -WallpaperPath $wallpaper"
    )
    result = _run_powershell(script, timeout_s=12)
    if result.get("exit_code") != 0:
        return {
            "enabled": _desktop_perf_snapshot().get("enabled", False),
            "active": True,
            "snapshot_present": bool(snapshot),
            "error": (result.get("stderr") or result.get("stdout") or "desktop_perf_restore_failed").strip(),
        }
    with DESKTOP_PERF_LOCK:
        DESKTOP_PERF_ACTIVE = False
        DESKTOP_PERF_SNAPSHOT = None
        try:
            os.remove(_desktop_perf_wallpaper_path())
        except FileNotFoundError:
            pass
        except Exception:
            pass
        return {
            "enabled": bool(DESKTOP_PERF_ENABLED),
            "active": False,
            "snapshot_present": False,
        }


def _set_desktop_perf_enabled(enabled: bool) -> Dict[str, Any]:
    global DESKTOP_PERF_ENABLED
    value = bool(enabled)
    with DESKTOP_PERF_LOCK:
        DESKTOP_PERF_ENABLED = value
    if not value:
        restored = _restore_desktop_perf_mode()
        restored["enabled"] = False
        return restored
    if _desktop_global_enabled():
        return _apply_desktop_perf_mode()
    return {
        "enabled": True,
        "active": False,
        "snapshot_present": bool(_desktop_perf_snapshot().get("snapshot_present")),
    }


def _sync_desktop_perf_mode(enabled: bool) -> Dict[str, Any]:
    if not _desktop_perf_snapshot().get("enabled", False):
        return _restore_desktop_perf_mode()
    if enabled:
        return _apply_desktop_perf_mode()
    return _restore_desktop_perf_mode()


def _close_desktop_webrtc_sessions_sync() -> None:
    with DESKTOP_WEBRTC_SESSION_LOCK:
        sessions = list(DESKTOP_WEBRTC_SESSIONS.values())
        DESKTOP_WEBRTC_SESSIONS.clear()
    for session in sessions:
        try:
            track = session.get("track")
            if track is not None:
                track.stop()
        except Exception:
            pass
        try:
            pc = session.get("pc")
            if pc is not None:
                asyncio.run(pc.close())
        except Exception:
            pass


atexit.register(_restore_desktop_perf_mode)
atexit.register(_close_desktop_webrtc_sessions_sync)
atexit.register(_host_keep_awake_release)
atexit.register(_desktop_codex_shutdown_app_server)


def _set_desktop_global_enabled(enabled: bool) -> bool:
    global DESKTOP_MODE_ENABLED
    value = bool(enabled)
    with DESKTOP_MODE_LOCK:
        DESKTOP_MODE_ENABLED = value
    if not value:
        _desktop_release_alt_if_held()
    _sync_desktop_perf_mode(value)
    return value


def _desktop_enabled_from_request(request: Request) -> bool:
    if not _desktop_global_enabled():
        return False

    # Query param can temporarily override cookie value on this request.
    q = ""
    try:
        q = (request.query_params.get("desktop") or "").strip().lower()
    except Exception:
        q = ""
    if _truthy_flag(q):
        return True
    if _falsy_flag(q):
        return False

    c = (request.cookies.get(CODEX_DESKTOP_MODE_COOKIE) or "").strip().lower()
    if _truthy_flag(c):
        return True
    if _falsy_flag(c):
        return False
    return True


def _require_desktop_enabled(request: Request) -> None:
    if _desktop_enabled_from_request(request):
        return
    raise HTTPException(409, "Desktop control is disabled. Enable Desktop to continue.")


def _compact_enabled_from_request(request: Request) -> bool:
    q = ""
    try:
        q = (request.query_params.get("compact") or "").strip().lower()
    except Exception:
        q = ""
    if _truthy_flag(q):
        return True
    if q in {"m", "mobile"}:
        return True
    if _falsy_flag(q):
        return False
    return False


def _mobile_ui_target_url(request: Request) -> str:
    """
    After QR pairing succeeds on the controller port, send users back to the
    built app served from the same controller origin.
    """
    try:
        base_url = str(getattr(request, "base_url", "") or "").strip()
        if base_url:
            return base_url
    except Exception:
        pass

    url = getattr(request, "url", None)
    host = str(getattr(url, "hostname", "") or "").strip() or "127.0.0.1"
    scheme = str(getattr(url, "scheme", "") or "http").strip() or "http"
    port = getattr(url, "port", None)
    try:
        port_num = int(port) if port is not None else None
    except Exception:
        port_num = None

    if port_num and port_num not in {80, 443}:
        return f"{scheme}://{host}:{port_num}/"
    return f"{scheme}://{host}/"

@app.middleware("http")
async def auth_middleware(request: Request, call_next):
    if not CODEX_AUTH_REQUIRED:
        return await call_next(request)

    path = request.url.path
    public_paths = {
        "/",
        "/app/health",
        "/app/runtime",
        "/mobile",
        "/diag/js",
        "/diag/status",
        "/favicon.ico",
        "/manifest.webmanifest",
        "/sw.js",
        "/apple-touch-icon.png",
        "/codrex-logo-hero.png",
        "/icon.svg",
        "/icon-192.png",
        "/icon-512.png",
        "/icon-maskable-192.png",
        "/icon-maskable-512.png",
        "/icon-maskable.svg",
        "/auth/login",
        "/auth/bootstrap/local",
        "/auth/logout",
        "/auth/status",
        "/net/info",
        "/codex/runtime/status",
        "/auth/pair/exchange",
        "/auth/device/resume",
        "/auth/pair/consume",
        "/auth/pair/qr.svg",
        "/auth/pair/qr.png",
        "/legacy/auth",
        "/legacy/auth/login",
        "/legacy/auth/logout",
    }
    public_prefixes = (
        "/assets/",
        "/workbox-",
    )
    if path in public_paths or any(path.startswith(prefix) for prefix in public_prefixes):
        return await call_next(request)

    token = _auth_token_from_request(request)
    if not _is_valid_auth_token(token):
        resp = JSONResponse(
            status_code=401,
            content={"ok": False, "error": "unauthorized", "detail": "Login required."},
        )
        # Avoid caching 401 responses (some mobile browsers can be sticky about subresource failures).
        resp.headers["Cache-Control"] = "no-store"
        return resp
    return await call_next(request)


@app.get("/app/health")
def app_health():
    payload = _built_ui_health_payload()
    if payload["ui_mode"] != "built":
        payload["detail"] = "Built app is unavailable. Use /legacy until the UI is built."
    return payload


@app.get("/app/runtime")
def app_runtime(request: Request):
    payload = _built_ui_health_payload()
    session = _read_json_file(APP_RUNTIME_SESSION_FILE)
    if not session:
        session = _read_json_file(LEGACY_APP_RUNTIME_SESSION_FILE)
    persisted = _read_json_file(os.path.join(APP_ROOT_DIR, "controller.config.json"))
    local_cfg = _read_json_file(os.path.join(CODEX_RUNTIME_STATE_DIR, "controller.config.local.json"))
    controller_port = None
    try:
        controller_port = int(getattr(request.url, "port", None) or 0) or None
    except Exception:
        controller_port = None
    if controller_port is None:
        try:
            controller_port = int((session or {}).get("controller_port") or 0) or None
        except Exception:
            controller_port = None
    if controller_port is None:
        try:
            controller_port = int((persisted or {}).get("port") or 0) or None
        except Exception:
            controller_port = None
    effective_port = int(controller_port or 48787)
    net_info = _get_cached_net_info()
    preferred_pair_route = _normalize_pair_route((net_info or {}).get("preferred_pair_route"))
    tailscale_available = bool((net_info or {}).get("tailscale_ip"))
    tailscale_warning = (
        str((net_info or {}).get("tailscale_warning") or "").strip()
        or ("Tailscale is off on this laptop." if preferred_pair_route == "tailscale" and not tailscale_available else "")
    )
    request_host = str(getattr(getattr(request, "url", None), "hostname", "") or "").strip()
    available_origins = _build_available_origins(effective_port, net_info)
    preferred_origin, route_provider, route_state = _resolve_preferred_origin(
        effective_port,
        net_info,
        request_host=request_host,
    )
    sessions_runtime = _wsl_runtime_status_payload()

    return {
        **payload,
        "ok": True,
        "version": str(getattr(app, "version", "") or "").strip(),
        "launcher_mode": "controller-served",
        "repo_root": APP_ROOT_DIR,
        "runtime_dir": CODEX_RUNTIME_DIR,
        "state_dir": CODEX_RUNTIME_STATE_DIR,
        "session_file": APP_RUNTIME_SESSION_FILE,
        "session_present": bool(session),
        "session": session if isinstance(session, dict) and session else None,
        "controller_port": controller_port,
        "controller_origin": _mobile_ui_target_url(request).rstrip("/"),
        "preferred_pair_route": preferred_pair_route,
        "tailscale_available": tailscale_available,
        "tailscale_warning": tailscale_warning,
        "available_origins": available_origins,
        "preferred_origin": preferred_origin,
        "route_provider": route_provider,
        "route_state": route_state,
        "controller_mode": "sessions-running" if sessions_runtime.get("state") == "running" else "controller-only",
        "sessions_runtime_state": sessions_runtime.get("state"),
        "sessions_runtime_detail": sessions_runtime.get("detail"),
        "sessions_runtime_distro": sessions_runtime.get("distro"),
        "sessions_runtime_can_start": bool(sessions_runtime.get("can_start")),
        "sessions_runtime_can_stop": bool(sessions_runtime.get("can_stop")),
        "config_port": (persisted or {}).get("port"),
        "runtime_token_present": bool(str((local_cfg or {}).get("token") or "").strip()),
        **_desktop_stream_transport_payload(),
    }


@app.get("/assets/{asset_path:path}")
def app_asset(asset_path: str):
    target = os.path.join(UI_DIST_ASSETS_DIR, asset_path or "")
    safe_target = os.path.abspath(target)
    safe_root = os.path.abspath(UI_DIST_ASSETS_DIR)
    if not safe_target.startswith(safe_root + os.sep):
        raise HTTPException(status_code=404, detail="asset_not_found")
    if not os.path.isfile(safe_target):
        raise HTTPException(status_code=404, detail="asset_not_found")
    return FileResponse(safe_target)


@app.get("/manifest.webmanifest")
@app.get("/sw.js")
@app.get("/apple-touch-icon.png")
@app.get("/codrex-logo-hero.png")
@app.get("/icon.svg")
@app.get("/icon-192.png")
@app.get("/icon-512.png")
@app.get("/icon-maskable-192.png")
@app.get("/icon-maskable-512.png")
@app.get("/icon-maskable.svg")
def app_root_file(request: Request):
    return _serve_built_ui_root_file(request.url.path.lstrip("/"))


@app.get("/workbox-{suffix:path}")
def app_workbox_asset(suffix: str):
    return _serve_built_ui_root_file(f"workbox-{suffix}")


@app.get("/mobile")
def mobile_entry():
    resp = RedirectResponse(url="/", status_code=307)
    resp.headers["Cache-Control"] = "no-store"
    return resp

# -------------------------
# Desktop control helpers
# -------------------------
def _ensure_windows_host() -> None:
    if os.name != "nt":
        raise HTTPException(status_code=400, detail="Desktop control is only supported on Windows hosts.")
    _ensure_windows_dpi_awareness()


def _ensure_windows_dpi_awareness() -> None:
    global WINDOWS_DPI_AWARE
    if os.name != "nt" or WINDOWS_DPI_AWARE:
        return
    with WINDOWS_DPI_AWARE_LOCK:
        if WINDOWS_DPI_AWARE:
            return
        try:
            user32 = ctypes.windll.user32
            awareness_set = False

            try:
                # Per-monitor v2 awareness keeps cursor/input coordinates in physical pixels.
                dpi_context = ctypes.c_void_p(-4 & ((1 << (ctypes.sizeof(ctypes.c_void_p) * 8)) - 1))
                awareness_set = bool(user32.SetProcessDpiAwarenessContext(dpi_context))
            except Exception:
                awareness_set = False

            if not awareness_set:
                try:
                    shcore = ctypes.windll.shcore
                    result = int(shcore.SetProcessDpiAwareness(2))
                    awareness_set = result in {0, 0x80070005}
                except Exception:
                    awareness_set = False

            if not awareness_set:
                try:
                    awareness_set = bool(user32.SetProcessDPIAware())
                except Exception:
                    awareness_set = False

            metrics = (int(user32.GetSystemMetrics(0)), int(user32.GetSystemMetrics(1)))
            print(
                f"Windows DPI awareness active={awareness_set} metrics={metrics[0]}x{metrics[1]}",
                flush=True,
            )
            WINDOWS_DPI_AWARE = True
        except Exception as exc:
            print(f"Windows DPI awareness setup failed: {type(exc).__name__}: {exc}", flush=True)
            WINDOWS_DPI_AWARE = True


def _desktop_windows_display_virtual_hint(
    adapter_name: str,
    adapter_id: str,
    monitor_name: str,
    monitor_id: str,
) -> bool:
    adapter_id_norm = str(adapter_id or "").strip().upper()
    monitor_id_norm = str(monitor_id or "").strip().upper()
    text = " ".join([
        str(adapter_name or "").strip(),
        str(adapter_id or "").strip(),
        str(monitor_name or "").strip(),
        str(monitor_id or "").strip(),
    ]).upper()
    for token in (
        "VIRTUAL",
        "INDIRECT",
        "IDD",
        "IDDSAMPLE",
        "PARSEC",
        "RUSTDESK",
        "MTTVDD",
        "DUMMY",
        "HEADLESS",
    ):
        if token in text:
            return True
    for prefix in (
        "ROOT\\DISPLAY",
        "ROOT\\MTTVDD",
        "ROOT\\IDD",
        "ROOT\\VIRTUAL",
        "SWD\\DISPLAY",
        "SWD\\INDIRECTDISPLAY",
        "INDIRECTDISPLAY\\",
        "INDIRECTDISPLAY#",
    ):
        if adapter_id_norm.startswith(prefix) or monitor_id_norm.startswith(prefix):
            return True
    return False


def _desktop_windows_display_info() -> List[Dict[str, Any]]:
    if os.name != "nt" or not getattr(ctypes, "windll", None):
        return []
    try:
        user32 = ctypes.windll.user32  # type: ignore[attr-defined]
        EnumDisplayDevicesW = user32.EnumDisplayDevicesW
        EnumDisplayDevicesW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, ctypes.POINTER(DISPLAY_DEVICEW), wintypes.DWORD]
        EnumDisplayDevicesW.restype = wintypes.BOOL
        EnumDisplayMonitors = user32.EnumDisplayMonitors
        EnumDisplayMonitors.argtypes = [wintypes.HDC, ctypes.POINTER(RECT), ctypes.c_void_p, wintypes.LPARAM]
        EnumDisplayMonitors.restype = wintypes.BOOL
        GetMonitorInfoW = user32.GetMonitorInfoW
        GetMonitorInfoW.argtypes = [wintypes.HANDLE, ctypes.POINTER(MONITORINFOEXW)]
        GetMonitorInfoW.restype = wintypes.BOOL

        adapters_by_name: Dict[str, Dict[str, Any]] = {}
        adapter_index = 0
        while True:
            adapter = DISPLAY_DEVICEW()
            adapter.cb = ctypes.sizeof(DISPLAY_DEVICEW)
            if not EnumDisplayDevicesW(None, adapter_index, ctypes.byref(adapter), 0):
                break
            adapter_index += 1
            device_name = str(adapter.DeviceName or "").strip()
            if not device_name:
                continue
            state_flags = int(adapter.StateFlags or 0)
            if state_flags & DISPLAY_DEVICE_MIRRORING_DRIVER:
                continue
            if not (state_flags & DISPLAY_DEVICE_ATTACHED_TO_DESKTOP):
                continue
            monitor_name = ""
            monitor_id = ""
            monitor_index = 0
            while True:
                monitor = DISPLAY_DEVICEW()
                monitor.cb = ctypes.sizeof(DISPLAY_DEVICEW)
                if not EnumDisplayDevicesW(device_name, monitor_index, ctypes.byref(monitor), 0):
                    break
                monitor_index += 1
                monitor_state = int(monitor.StateFlags or 0)
                if monitor_state and not (monitor_state & DISPLAY_DEVICE_ATTACHED_TO_DESKTOP):
                    continue
                monitor_name = str(monitor.DeviceString or "").strip()
                monitor_id = str(monitor.DeviceID or "").strip()
                break
            adapters_by_name[device_name.upper()] = {
                "device_name": device_name,
                "adapter_name": str(adapter.DeviceString or "").strip(),
                "adapter_id": str(adapter.DeviceID or "").strip(),
                "monitor_name": monitor_name,
                "monitor_id": monitor_id,
                "primary": bool(state_flags & DISPLAY_DEVICE_PRIMARY_DEVICE),
            }

        if not adapters_by_name:
            return []

        callback_records: List[Dict[str, Any]] = []

        MonitorEnumProc = ctypes.WINFUNCTYPE(
            wintypes.BOOL,
            wintypes.HANDLE,
            wintypes.HDC,
            ctypes.POINTER(RECT),
            wintypes.LPARAM,
        )

        @MonitorEnumProc
        def _enum_monitor_proc(hmonitor: wintypes.HANDLE, hdc: wintypes.HDC, lprc: ctypes.POINTER(RECT), lparam: wintypes.LPARAM) -> wintypes.BOOL:
            info = MONITORINFOEXW()
            info.cbSize = ctypes.sizeof(MONITORINFOEXW)
            if not GetMonitorInfoW(hmonitor, ctypes.byref(info)):
                return True
            bounds = info.rcMonitor
            callback_records.append({
                "device_name": str(info.szDevice or "").strip(),
                "left": int(bounds.left),
                "top": int(bounds.top),
                "width": int(bounds.right - bounds.left),
                "height": int(bounds.bottom - bounds.top),
            })
            return True

        if not EnumDisplayMonitors(None, None, _enum_monitor_proc, 0):
            return []

        enriched: List[Dict[str, Any]] = []
        for record in callback_records:
            adapter = adapters_by_name.get(str(record.get("device_name") or "").strip().upper(), {})
            adapter_name = str(adapter.get("adapter_name") or "").strip()
            adapter_id = str(adapter.get("adapter_id") or "").strip()
            monitor_name = str(adapter.get("monitor_name") or "").strip()
            monitor_id = str(adapter.get("monitor_id") or "").strip()
            enriched.append({
                **record,
                "primary": bool(adapter.get("primary")),
                "adapter_name": adapter_name,
                "adapter_id": adapter_id,
                "monitor_name": monitor_name,
                "monitor_id": monitor_id,
                "virtual": _desktop_windows_display_virtual_hint(adapter_name, adapter_id, monitor_name, monitor_id),
            })
        enriched.sort(key=lambda item: (0 if item.get("primary") else 1, int(item.get("top", 0)), int(item.get("left", 0)), str(item.get("device_name") or "")))
        return enriched
    except Exception:
        return []


def _desktop_device_name_sort_key(device_name: str) -> Tuple[int, str]:
    text = str(device_name or "").strip().upper()
    match = re.search(r"DISPLAY(\d+)$", text)
    if match:
        try:
            return (int(match.group(1)), text)
        except Exception:
            pass
    return (1 << 30, text)


def _desktop_target_device_name(target: Optional[Dict[str, Any]]) -> str:
    return str((target or {}).get("device_name") or "").strip()


def _desktop_current_display_mode(device_name: str) -> Optional[Dict[str, Any]]:
    name = str(device_name or "").strip()
    if os.name != "nt" or not name or not getattr(ctypes, "windll", None):
        return None
    try:
        user32 = ctypes.windll.user32  # type: ignore[attr-defined]
        EnumDisplaySettingsW = user32.EnumDisplaySettingsW
        EnumDisplaySettingsW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, ctypes.POINTER(DEVMODEW)]
        EnumDisplaySettingsW.restype = wintypes.BOOL
        mode = DEVMODEW()
        mode.dmSize = ctypes.sizeof(DEVMODEW)
        if not EnumDisplaySettingsW(name, ENUM_CURRENT_SETTINGS, ctypes.byref(mode)):
            return None
        return {
            "width": int(mode.dmPelsWidth or 0),
            "height": int(mode.dmPelsHeight or 0),
            "bits_per_pixel": int(mode.dmBitsPerPel or 0),
            "display_frequency": int(mode.dmDisplayFrequency or 0),
        }
    except Exception:
        return None


def _desktop_supported_display_modes(device_name: str) -> List[Dict[str, Any]]:
    name = str(device_name or "").strip()
    if os.name != "nt" or not name or not getattr(ctypes, "windll", None):
        return []
    modes: List[Dict[str, Any]] = []
    seen: Set[Tuple[int, int, int, int]] = set()
    try:
        user32 = ctypes.windll.user32  # type: ignore[attr-defined]
        EnumDisplaySettingsW = user32.EnumDisplaySettingsW
        EnumDisplaySettingsW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, ctypes.POINTER(DEVMODEW)]
        EnumDisplaySettingsW.restype = wintypes.BOOL
        index = 0
        while True:
            mode = DEVMODEW()
            mode.dmSize = ctypes.sizeof(DEVMODEW)
            if not EnumDisplaySettingsW(name, index, ctypes.byref(mode)):
                break
            index += 1
            width = int(mode.dmPelsWidth or 0)
            height = int(mode.dmPelsHeight or 0)
            bits = int(mode.dmBitsPerPel or 0)
            freq = int(mode.dmDisplayFrequency or 0)
            if width <= 0 or height <= 0:
                continue
            key = (width, height, bits, freq)
            if key in seen:
                continue
            seen.add(key)
            modes.append({
                "width": width,
                "height": height,
                "bits_per_pixel": bits,
                "display_frequency": freq,
            })
    except Exception:
        return []
    modes.sort(key=lambda item: (int(item.get("width") or 0), int(item.get("height") or 0), int(item.get("display_frequency") or 0)))
    return modes


def _desktop_select_display_mode(
    device_name: str,
    desired_width: int,
    desired_height: int,
    *,
    current_mode: Optional[Dict[str, Any]] = None,
    downshift_only: bool = False,
) -> Optional[Dict[str, Any]]:
    desired_width = max(1, int(desired_width or 0))
    desired_height = max(1, int(desired_height or 0))
    current = dict(current_mode or _desktop_current_display_mode(device_name) or {})
    supported = list(_desktop_supported_display_modes(device_name) or [])
    if not supported:
        return None

    current_width = int(current.get("width") or 0)
    current_height = int(current.get("height") or 0)
    current_bits = int(current.get("bits_per_pixel") or 0)
    current_freq = int(current.get("display_frequency") or 0)

    candidates = list(supported)
    if downshift_only and current_width > 0 and current_height > 0:
        smaller = [
            dict(item)
            for item in candidates
            if int(item.get("width") or 0) <= current_width and int(item.get("height") or 0) <= current_height
        ]
        if smaller:
            candidates = smaller

    exact = [
        dict(item)
        for item in candidates
        if int(item.get("width") or 0) == desired_width and int(item.get("height") or 0) == desired_height
    ]
    if exact:
        exact.sort(
            key=lambda item: (
                abs(int(item.get("bits_per_pixel") or 0) - current_bits),
                abs(int(item.get("display_frequency") or 0) - current_freq),
            )
        )
        return dict(exact[0])

    desired_aspect = float(desired_width) / float(max(1, desired_height))

    def _candidate_score(item: Dict[str, Any]) -> Tuple[float, int, int, int]:
        width = int(item.get("width") or 0)
        height = int(item.get("height") or 0)
        aspect = float(width) / float(max(1, height))
        return (
            abs(aspect - desired_aspect),
            abs(width - desired_width) + abs(height - desired_height),
            abs(int(item.get("bits_per_pixel") or 0) - current_bits),
            abs(int(item.get("display_frequency") or 0) - current_freq),
        )

    candidates.sort(key=_candidate_score)
    return dict(candidates[0]) if candidates else None


def _desktop_apply_display_mode(device_name: str, mode: Dict[str, Any]) -> Dict[str, Any]:
    name = str(device_name or "").strip()
    if os.name != "nt" or not name or not getattr(ctypes, "windll", None):
        return {"ok": False, "detail": "display_mode_unavailable"}
    try:
        user32 = ctypes.windll.user32  # type: ignore[attr-defined]
        EnumDisplaySettingsW = user32.EnumDisplaySettingsW
        EnumDisplaySettingsW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, ctypes.POINTER(DEVMODEW)]
        EnumDisplaySettingsW.restype = wintypes.BOOL
        ChangeDisplaySettingsExW = user32.ChangeDisplaySettingsExW
        ChangeDisplaySettingsExW.argtypes = [
            wintypes.LPCWSTR,
            ctypes.POINTER(DEVMODEW),
            wintypes.HWND,
            wintypes.DWORD,
            ctypes.c_void_p,
        ]
        ChangeDisplaySettingsExW.restype = wintypes.LONG
        devmode = DEVMODEW()
        devmode.dmSize = ctypes.sizeof(DEVMODEW)
        if not EnumDisplaySettingsW(name, ENUM_CURRENT_SETTINGS, ctypes.byref(devmode)):
            return {"ok": False, "detail": "current_mode_unavailable"}
        width = int(mode.get("width") or 0)
        height = int(mode.get("height") or 0)
        bits = int(mode.get("bits_per_pixel") or 0)
        freq = int(mode.get("display_frequency") or 0)
        if width <= 0 or height <= 0:
            return {"ok": False, "detail": "invalid_target_mode"}
        devmode.dmPelsWidth = width
        devmode.dmPelsHeight = height
        devmode.dmFields = DM_PELSWIDTH | DM_PELSHEIGHT
        if bits > 0:
            devmode.dmBitsPerPel = bits
            devmode.dmFields |= DM_BITSPERPEL
        if freq > 0:
            devmode.dmDisplayFrequency = freq
            devmode.dmFields |= DM_DISPLAYFREQUENCY
        test_result = int(ChangeDisplaySettingsExW(name, ctypes.byref(devmode), None, CDS_TEST, None))
        if test_result != DISP_CHANGE_SUCCESSFUL:
            return {"ok": False, "detail": f"mode_test_failed:{test_result}"}
        apply_result = int(ChangeDisplaySettingsExW(name, ctypes.byref(devmode), None, 0, None))
        return {
            "ok": apply_result == DISP_CHANGE_SUCCESSFUL,
            "detail": "" if apply_result == DISP_CHANGE_SUCCESSFUL else f"mode_apply_failed:{apply_result}",
        }
    except Exception as exc:
        return {"ok": False, "detail": f"{type(exc).__name__}: {exc}"}


def _desktop_capture_display_layout(targets: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
    snapshot = list(targets or _desktop_target_items() or [])
    items: List[Dict[str, Any]] = []
    primary_device_name = ""
    for item in snapshot:
        if not isinstance(item, dict):
            continue
        device_name = _desktop_target_device_name(item)
        if not device_name:
            continue
        record = {
            "target_id": str(item.get("id") or "").strip().lower(),
            "device_name": device_name,
            "left": int(item.get("left") or 0),
            "top": int(item.get("top") or 0),
            "width": int(item.get("width") or 0),
            "height": int(item.get("height") or 0),
            "primary": bool(item.get("primary")),
        }
        if record["primary"] and not primary_device_name:
            primary_device_name = device_name
        items.append(record)
    return {
        "primary_device_name": primary_device_name,
        "items": items,
    }


def _desktop_apply_display_layout(layout: Dict[str, Any], primary_device_name: str) -> Dict[str, Any]:
    target_primary = str(primary_device_name or "").strip()
    entries = list((layout or {}).get("items") or [])
    if os.name != "nt" or not target_primary or not entries or not getattr(ctypes, "windll", None):
        return {"ok": False, "detail": "display_layout_unavailable"}
    baseline = next((dict(item) for item in entries if str(item.get("device_name") or "").strip() == target_primary), None)
    if not baseline:
        return {"ok": False, "detail": "primary_layout_missing"}
    base_left = int(baseline.get("left") or 0)
    base_top = int(baseline.get("top") or 0)
    try:
        user32 = ctypes.windll.user32  # type: ignore[attr-defined]
        EnumDisplaySettingsW = user32.EnumDisplaySettingsW
        EnumDisplaySettingsW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, ctypes.POINTER(DEVMODEW)]
        EnumDisplaySettingsW.restype = wintypes.BOOL
        ChangeDisplaySettingsExW = user32.ChangeDisplaySettingsExW
        ChangeDisplaySettingsExW.argtypes = [
            wintypes.LPCWSTR,
            ctypes.POINTER(DEVMODEW),
            wintypes.HWND,
            wintypes.DWORD,
            ctypes.c_void_p,
        ]
        ChangeDisplaySettingsExW.restype = wintypes.LONG
        prepared: List[Tuple[str, DEVMODEW, int]] = []
        for entry in entries:
            device_name = str(entry.get("device_name") or "").strip()
            if not device_name:
                continue
            devmode = DEVMODEW()
            devmode.dmSize = ctypes.sizeof(DEVMODEW)
            if not EnumDisplaySettingsW(device_name, ENUM_CURRENT_SETTINGS, ctypes.byref(devmode)):
                return {"ok": False, "detail": f"current_mode_unavailable:{device_name}"}
            devmode.dmPositionX = int(entry.get("left") or 0) - base_left
            devmode.dmPositionY = int(entry.get("top") or 0) - base_top
            devmode.dmFields |= DM_POSITION
            flags = CDS_TEST
            if device_name == target_primary:
                flags |= CDS_SET_PRIMARY
            test_result = int(ChangeDisplaySettingsExW(device_name, ctypes.byref(devmode), None, flags, None))
            if test_result != DISP_CHANGE_SUCCESSFUL:
                return {"ok": False, "detail": f"layout_test_failed:{device_name}:{test_result}"}
            prepared.append((device_name, devmode, CDS_UPDATEREGISTRY | CDS_NORESET | (CDS_SET_PRIMARY if device_name == target_primary else 0)))
        for device_name, devmode, flags in prepared:
            apply_result = int(ChangeDisplaySettingsExW(device_name, ctypes.byref(devmode), None, flags, None))
            if apply_result != DISP_CHANGE_SUCCESSFUL:
                return {"ok": False, "detail": f"layout_stage_failed:{device_name}:{apply_result}"}
        commit_result = int(ChangeDisplaySettingsExW(None, None, None, 0, None))
        if commit_result != DISP_CHANGE_SUCCESSFUL:
            return {"ok": False, "detail": f"layout_commit_failed:{commit_result}"}
        time.sleep(0.6)
        _desktop_clear_cached_capture_handles()
        return {"ok": True, "detail": "", "primary_device_name": target_primary}
    except Exception as exc:
        return {"ok": False, "detail": f"{type(exc).__name__}: {exc}"}


def _desktop_match_mss_monitor_index(
    monitor_items: List[Dict[str, Any]],
    *,
    target_id: str = "",
    target_left: Optional[int] = None,
    target_top: Optional[int] = None,
    target_width: Optional[int] = None,
    target_height: Optional[int] = None,
) -> int:
    if not monitor_items:
        raise HTTPException(status_code=500, detail="No desktop displays were detected.")
    if target_left is not None and target_top is not None and target_width is not None and target_height is not None:
        for index, mon in enumerate(monitor_items):
            if (
                int(mon.get("left", 0)) == int(target_left)
                and int(mon.get("top", 0)) == int(target_top)
                and int(mon.get("width", 0)) == int(target_width)
                and int(mon.get("height", 0)) == int(target_height)
            ):
                return index
    wanted = str(target_id or "").strip().lower()
    match = re.fullmatch(r"display-(\d+)", wanted)
    if match:
        try:
            legacy_index = max(0, int(match.group(1)) - 1)
            if legacy_index < len(monitor_items):
                return legacy_index
        except Exception:
            pass
    return 0


def _desktop_monitor() -> Dict[str, int]:
    targets = _desktop_target_items()
    selected_target = next((dict(item) for item in targets if item.get("selected")), dict(targets[0]) if targets else {})
    with mss() as sct:
        monitor_items = sct.monitors[1:] if len(sct.monitors) > 1 else sct.monitors
        if not monitor_items:
            raise HTTPException(status_code=500, detail="No desktop displays were detected.")
        chosen = monitor_items[_desktop_match_mss_monitor_index(
            monitor_items,
            target_id=str(selected_target.get("id") or ""),
            target_left=selected_target.get("left"),
            target_top=selected_target.get("top"),
            target_width=selected_target.get("width"),
            target_height=selected_target.get("height"),
        )]
        mon = chosen
        return {
            "left": int(mon.get("left", 0)),
            "top": int(mon.get("top", 0)),
            "width": int(mon.get("width", 0)),
            "height": int(mon.get("height", 0)),
        }


def _desktop_selected_output_index() -> Optional[int]:
    targets = _desktop_target_items()
    if not targets:
        return None
    selected_target = next((dict(item) for item in targets if item.get("selected")), dict(targets[0]))
    with mss() as sct:
        monitor_items = sct.monitors[1:] if len(sct.monitors) > 1 else sct.monitors
        if not monitor_items:
            return None
        return _desktop_match_mss_monitor_index(
            monitor_items,
            target_id=str(selected_target.get("id") or ""),
            target_left=selected_target.get("left"),
            target_top=selected_target.get("top"),
            target_width=selected_target.get("width"),
            target_height=selected_target.get("height"),
        )


def _desktop_clear_current_thread_capture_handles() -> None:
    sct = getattr(DESKTOP_CAPTURE_TLS, "sct", None)
    if sct is not None:
        try:
            close_fn = getattr(sct, "close", None)
            if callable(close_fn):
                close_fn()
        except Exception:
            pass
    setattr(DESKTOP_CAPTURE_TLS, "sct", None)
    setattr(DESKTOP_CAPTURE_TLS, "dxcam_black_target_id", "")
    setattr(DESKTOP_CAPTURE_TLS, "dxcam_black_until", 0.0)


def _desktop_mark_dxcam_blacklisted_for_current_thread(target_id: str, ttl_s: float = 30.0) -> None:
    normalized = str(target_id or "").strip().lower()
    if not normalized:
        return
    setattr(DESKTOP_CAPTURE_TLS, "dxcam_black_target_id", normalized)
    setattr(DESKTOP_CAPTURE_TLS, "dxcam_black_until", time.time() + max(float(ttl_s), 1.0))


def _desktop_is_dxcam_blacklisted_for_current_thread(target_id: str) -> bool:
    normalized = str(target_id or "").strip().lower()
    if not normalized:
        return False
    blocked_target = str(getattr(DESKTOP_CAPTURE_TLS, "dxcam_black_target_id", "") or "").strip().lower()
    blocked_until = float(getattr(DESKTOP_CAPTURE_TLS, "dxcam_black_until", 0.0) or 0.0)
    if blocked_target != normalized or blocked_until <= time.time():
        if blocked_target and blocked_until <= time.time():
            setattr(DESKTOP_CAPTURE_TLS, "dxcam_black_target_id", "")
            setattr(DESKTOP_CAPTURE_TLS, "dxcam_black_until", 0.0)
        return False
    return True


def _desktop_dxcam_frame_looks_black(frame: Any) -> bool:
    try:
        shape = getattr(frame, "shape", None)
        if shape is None or len(shape) < 2:
            return False
        height = int(shape[0] or 0)
        width = int(shape[1] or 0)
        if height <= 0 or width <= 0:
            return False
        row_stride = max(1, height // 64)
        col_stride = max(1, width // 64)
        sample = frame[::row_stride, ::col_stride]
        sample_shape = getattr(sample, "shape", None)
        if sample_shape is not None and len(sample_shape) >= 3 and int(sample_shape[2] or 0) >= 4:
            sample = sample[:, :, :3]
        max_level = int(sample.max())
        if max_level > 6:
            return False
        mean_level = float(sample.mean())
        return mean_level <= 1.5
    except Exception:
        return False


def _desktop_clear_global_dxcam_handle() -> None:
    global DESKTOP_DXCAM_CAMERA, DESKTOP_DXCAM_OUTPUT_IDX, DESKTOP_DXCAM_GENERATION
    camera = DESKTOP_DXCAM_CAMERA
    DESKTOP_DXCAM_CAMERA = None
    DESKTOP_DXCAM_OUTPUT_IDX = None
    DESKTOP_DXCAM_GENERATION = -1
    if camera is not None:
        try:
            camera.release()
        except Exception:
            pass
    if DXCAM_AVAILABLE and dxcam is not None:
        try:
            factory = getattr(dxcam, "__factory", None)
            clean_up = getattr(factory, "clean_up", None)
            if callable(clean_up):
                clean_up()
        except Exception:
            pass
    gc.collect()


def _desktop_clear_cached_capture_handles() -> None:
    with DESKTOP_TARGET_LOCK:
        global DESKTOP_CAPTURE_GENERATION
        DESKTOP_CAPTURE_GENERATION += 1
        generation = DESKTOP_CAPTURE_GENERATION
    with DESKTOP_DXCAM_LOCK:
        _desktop_clear_global_dxcam_handle()
    _desktop_clear_current_thread_capture_handles()
    setattr(DESKTOP_CAPTURE_TLS, "capture_generation", generation)


def _desktop_target_items() -> List[Dict[str, Any]]:
    with DESKTOP_TARGET_LOCK:
        selected_id = DESKTOP_TARGET_SELECTED_ID
    targets: List[Dict[str, Any]] = []
    windows_displays = _desktop_windows_display_info()
    if windows_displays:
        ordered_windows_displays = sorted(
            list(windows_displays),
            key=lambda item: _desktop_device_name_sort_key(str(item.get("device_name") or "")),
        )
        for index, mon in enumerate(ordered_windows_displays, start=1):
            target_id = f"display-{index}"
            device_name = str(mon.get("device_name") or "").strip().lower()
            monitor_id = str(mon.get("monitor_id") or "").strip().lower()
            is_primary = bool(mon.get("primary")) if index != 1 else bool(mon.get("primary", True))
            is_virtual = bool(mon.get("virtual"))
            if DESKTOP_TARGET_VIRTUAL_HINT:
                hint = DESKTOP_TARGET_VIRTUAL_HINT
                if hint in {target_id, device_name, monitor_id}:
                    is_virtual = True
            targets.append({
                "id": target_id,
                "label": f"{'Primary' if is_primary else 'Display'} {index}",
                "kind": "virtual" if is_virtual else "physical",
                "virtual": is_virtual,
                "physical": not is_virtual,
                "primary": is_primary,
                "selected": target_id == selected_id if selected_id else is_primary,
                "device_name": str(mon.get("device_name") or "").strip(),
                "adapter_name": str(mon.get("adapter_name") or "").strip(),
                "adapter_id": str(mon.get("adapter_id") or "").strip(),
                "monitor_name": str(mon.get("monitor_name") or "").strip(),
                "monitor_id": str(mon.get("monitor_id") or "").strip(),
                "left": int(mon.get("left", 0)),
                "top": int(mon.get("top", 0)),
                "width": int(mon.get("width", 0)),
                "height": int(mon.get("height", 0)),
            })
        if targets:
            return targets
    with mss() as sct:
        monitor_items = sct.monitors[1:] if len(sct.monitors) > 1 else sct.monitors
        for index, mon in enumerate(monitor_items, start=1):
            target_id = f"display-{index}"
            is_primary = index == 1
            is_virtual = bool(DESKTOP_TARGET_VIRTUAL_HINT and target_id == DESKTOP_TARGET_VIRTUAL_HINT)
            targets.append({
                "id": target_id,
                "label": f"{'Primary' if is_primary else 'Display'} {index}",
                "kind": "virtual" if is_virtual else "physical",
                "virtual": is_virtual,
                "physical": not is_virtual,
                "primary": is_primary,
                "selected": target_id == selected_id if selected_id else is_primary,
                "left": int(mon.get("left", 0)),
                "top": int(mon.get("top", 0)),
                "width": int(mon.get("width", 0)),
                "height": int(mon.get("height", 0)),
            })
    return targets


def _desktop_selected_target_item(targets: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
    snapshot = targets if targets is not None else _desktop_target_items()
    if not snapshot:
        return {}
    return next((dict(item) for item in snapshot if item.get("selected")), dict(snapshot[0]))


def _desktop_sync_capture_handles_for_current_thread() -> None:
    with DESKTOP_TARGET_LOCK:
        generation = int(DESKTOP_CAPTURE_GENERATION)
    if int(getattr(DESKTOP_CAPTURE_TLS, "capture_generation", -1) or -1) == generation:
        return
    _desktop_clear_current_thread_capture_handles()
    setattr(DESKTOP_CAPTURE_TLS, "capture_generation", generation)


def _desktop_targets_payload() -> Dict[str, Any]:
    targets = _desktop_target_items()
    if not targets:
        raise HTTPException(status_code=500, detail="No desktop displays were detected.")
    active = _desktop_selected_target_item(targets)
    virtual_target = next((dict(item) for item in targets if item.get("virtual")), None)
    return {
        "ok": True,
        "targets": targets,
        "active_target": active,
        "virtual_supported": bool(virtual_target),
        "virtual_enabled": bool(virtual_target and active.get("id") == virtual_target.get("id")),
        "detail": (
            ""
            if virtual_target
            else "No existing IDD or virtual display target is configured on this host."
        ),
    }


def _desktop_find_target_item(target_id: str, targets: Optional[List[Dict[str, Any]]] = None) -> Optional[Dict[str, Any]]:
    wanted = str(target_id or "").strip().lower()
    if not wanted:
        return None
    snapshot = targets if targets is not None else _desktop_target_items()
    return next((dict(item) for item in snapshot if str(item.get("id") or "").strip().lower() == wanted), None)


def _desktop_virtual_target_item(targets: Optional[List[Dict[str, Any]]] = None) -> Optional[Dict[str, Any]]:
    snapshot = targets if targets is not None else _desktop_target_items()
    return next((dict(item) for item in snapshot if bool(item.get("virtual"))), None)


def _desktop_first_physical_target_item(targets: Optional[List[Dict[str, Any]]] = None) -> Optional[Dict[str, Any]]:
    snapshot = targets if targets is not None else _desktop_target_items()
    return next((dict(item) for item in snapshot if bool(item.get("physical", not bool(item.get("virtual"))))), None)

def _desktop_select_target(target_id: str) -> Dict[str, Any]:
    selected = str(target_id or "").strip().lower()
    if not selected:
        raise HTTPException(status_code=400, detail="target_id is required.")
    targets = _desktop_target_items()
    ids = {str(item.get("id") or "").strip().lower() for item in targets}
    if selected not in ids:
        raise HTTPException(status_code=404, detail=f"Desktop target '{selected}' was not found.")
    with DESKTOP_TARGET_LOCK:
        global DESKTOP_TARGET_SELECTED_ID
        changed = DESKTOP_TARGET_SELECTED_ID != selected
        DESKTOP_TARGET_SELECTED_ID = selected
    if changed:
        _desktop_clear_cached_capture_handles()
    return _desktop_targets_payload()


def _desktop_capture_backend() -> str:
    candidate = DESKTOP_CAPTURE_BACKEND_DEFAULT
    if candidate in {"dxcam", "auto"} and DXCAM_AVAILABLE and os.name == "nt":
        return "dxcam"
    return "mss"


def _desktop_dxcam() -> Any:
    global DESKTOP_DXCAM_CAMERA, DESKTOP_DXCAM_OUTPUT_IDX, DESKTOP_DXCAM_GENERATION
    if not DXCAM_AVAILABLE or dxcam is None or os.name != "nt":
        raise RuntimeError("dxcam desktop capture is not available on this host.")
    output_idx = _desktop_selected_output_index()
    generation = int(DESKTOP_CAPTURE_GENERATION)
    camera = DESKTOP_DXCAM_CAMERA
    cached_output_idx = DESKTOP_DXCAM_OUTPUT_IDX
    cached_generation = int(DESKTOP_DXCAM_GENERATION)
    if camera is None or cached_output_idx != output_idx or cached_generation != generation:
        _desktop_clear_global_dxcam_handle()
        create_kwargs: Dict[str, Any] = {"processor_backend": "numpy"}
        if output_idx is not None:
            create_kwargs["output_idx"] = output_idx
        camera = dxcam.create(**create_kwargs)  # type: ignore[call-arg]
        DESKTOP_DXCAM_CAMERA = camera
        DESKTOP_DXCAM_OUTPUT_IDX = output_idx
        DESKTOP_DXCAM_GENERATION = generation
    return camera


def _desktop_dxcam_monitor() -> Dict[str, int]:
    return _desktop_monitor()

def _clamp(v: int, lo: int, hi: int) -> int:
    return max(lo, min(hi, v))


def _parse_stream_scale(raw: Any, default: int = 1) -> int:
    try:
        value = int(raw if raw is not None else default)
    except Exception:
        value = int(default)
    return _clamp(value, 1, 6)


def _parse_stream_aspect(raw: Any) -> Optional[float]:
    try:
        value = float(raw)
    except Exception:
        return None
    if not math.isfinite(value):
        return None
    return max(0.5, min(value, 3.0))


def _parse_stream_layout_mode(raw: Any) -> str:
    candidate = str(raw or "").strip().lower()
    if candidate in {"stretch", "fill", "crop", "fit"}:
        return candidate
    return "fit"


def _parse_stream_target_size(raw_width: Any, raw_height: Any) -> Optional[Tuple[int, int]]:
    try:
        width = int(raw_width)
        height = int(raw_height)
    except Exception:
        return None
    if width <= 0 or height <= 0:
        return None
    max_edge = max(width, height)
    if max_edge > 1920:
        scale = 1920.0 / float(max_edge)
        width = max(320, int(round(width * scale)))
        height = max(240, int(round(height * scale)))
    return (width, height)


def _downsample_rgb_nearest(rgb_bytes: bytes, size: Tuple[int, int], factor: int) -> Tuple[bytes, Tuple[int, int]]:
    w, h = int(size[0]), int(size[1])
    f = _clamp(int(factor or 1), 1, 6)
    if f <= 1 or w <= 0 or h <= 0:
        return rgb_bytes, (w, h)

    src = memoryview(rgb_bytes)
    out_w = (w + f - 1) // f
    out_h = (h + f - 1) // f
    out = bytearray(out_w * out_h * 3)
    di = 0
    row_stride = w * 3

    for y in range(0, h, f):
        row_start = y * row_stride
        for x in range(0, w, f):
            si = row_start + x * 3
            out[di] = src[si]
            out[di + 1] = src[si + 1]
            out[di + 2] = src[si + 2]
            di += 3

    return bytes(out), (out_w, out_h)


def _rgb_to_grayscale(rgb_bytes: bytes) -> bytes:
    src = memoryview(rgb_bytes)
    out = bytearray(len(src))
    for i in range(0, len(src), 3):
        lum = (int(src[i]) * 30 + int(src[i + 1]) * 59 + int(src[i + 2]) * 11) // 100
        out[i] = lum
        out[i + 1] = lum
        out[i + 2] = lum
    return bytes(out)


def _crop_rgb_region(
    rgb_bytes: bytes,
    size: Tuple[int, int],
    left: int,
    top: int,
    crop_w: int,
    crop_h: int,
) -> Tuple[bytes, Tuple[int, int]]:
    src_w, src_h = int(size[0]), int(size[1])
    left = _clamp(int(left), 0, max(0, src_w - 1))
    top = _clamp(int(top), 0, max(0, src_h - 1))
    crop_w = max(1, min(int(crop_w), src_w - left))
    crop_h = max(1, min(int(crop_h), src_h - top))
    if left == 0 and top == 0 and crop_w == src_w and crop_h == src_h:
        return rgb_bytes, (src_w, src_h)
    row_stride = src_w * 3
    out_stride = crop_w * 3
    src = memoryview(rgb_bytes)
    out = bytearray(crop_h * out_stride)
    for row in range(crop_h):
        src_start = ((top + row) * row_stride) + (left * 3)
        src_end = src_start + out_stride
        dst_start = row * out_stride
        out[dst_start : dst_start + out_stride] = src[src_start:src_end]
    return bytes(out), (crop_w, crop_h)


def _crop_rgb_to_aspect(
    rgb_bytes: bytes,
    size: Tuple[int, int],
    aspect_ratio: Optional[float],
) -> Tuple[bytes, Tuple[int, int]]:
    target_aspect = _parse_stream_aspect(aspect_ratio)
    src_w, src_h = int(size[0]), int(size[1])
    if not target_aspect or src_w <= 0 or src_h <= 0:
        return rgb_bytes, (src_w, src_h)
    source_aspect = float(src_w) / float(src_h)
    if abs(source_aspect - target_aspect) <= 0.01:
        return rgb_bytes, (src_w, src_h)
    if target_aspect < source_aspect:
        crop_w = max(1, min(src_w, int(round(src_h * target_aspect))))
        crop_h = src_h
        left = max(0, (src_w - crop_w) // 2)
        top = 0
    else:
        crop_w = src_w
        crop_h = max(1, min(src_h, int(round(src_w / target_aspect))))
        left = 0
        top = max(0, (src_h - crop_h) // 2)
    return _crop_rgb_region(rgb_bytes, (src_w, src_h), left, top, crop_w, crop_h)


def _resize_rgb_to_target(
    rgb_bytes: bytes,
    size: Tuple[int, int],
    target_size: Optional[Tuple[int, int]],
) -> Tuple[bytes, Tuple[int, int]]:
    if not target_size or not PILLOW_AVAILABLE:
        return rgb_bytes, size
    src_w, src_h = int(size[0]), int(size[1])
    target_w, target_h = int(target_size[0]), int(target_size[1])
    if src_w <= 0 or src_h <= 0 or target_w <= 0 or target_h <= 0:
        return rgb_bytes, size
    if src_w == target_w and src_h == target_h:
        return rgb_bytes, size
    image = Image.frombytes("RGB", (src_w, src_h), rgb_bytes)
    resample = getattr(Image, "Resampling", Image).BILINEAR
    resized = image.resize((target_w, target_h), resample=resample)
    return resized.tobytes(), (target_w, target_h)


def _resize_rgb_to_fit_target(
    rgb_bytes: bytes,
    size: Tuple[int, int],
    target_size: Optional[Tuple[int, int]],
) -> Tuple[bytes, Tuple[int, int]]:
    if not target_size:
        return rgb_bytes, size
    src_w, src_h = int(size[0]), int(size[1])
    target_w, target_h = int(target_size[0]), int(target_size[1])
    if src_w <= 0 or src_h <= 0 or target_w <= 0 or target_h <= 0:
        return rgb_bytes, size
    scale = min(target_w / float(src_w), target_h / float(src_h))
    resized_w = max(1, int(round(src_w * scale)))
    resized_h = max(1, int(round(src_h * scale)))
    if resized_w == src_w and resized_h == src_h:
        return rgb_bytes, size
    return _resize_rgb_to_target(rgb_bytes, size, (resized_w, resized_h))


def _desktop_capture_rgb(
    scale_factor: int = 1,
    grayscale: bool = False,
    sct_instance: Optional[Any] = None,
    aspect_ratio: Optional[float] = None,
    layout_mode: str = "fit",
    target_size: Optional[Tuple[int, int]] = None,
) -> Tuple[bytes, Tuple[int, int]]:
    _host_keep_awake_pulse()
    _desktop_sync_capture_handles_for_current_thread()
    selected_target = _desktop_selected_target_item()
    selected_target_id = str(selected_target.get("id") or "").strip().lower()
    selected_target_virtual = bool(selected_target.get("virtual"))

    def _process_capture(
        rgb: bytes,
        out_size: Tuple[int, int],
        left: int,
        top: int,
        include_cursor_overlay: bool = True,
    ) -> Tuple[bytes, Tuple[int, int]]:
        if include_cursor_overlay and SHOW_CURSOR_OVERLAY:
            cur = _desktop_cursor_pos()
            if cur:
                rel_x = int(cur[0]) - int(left)
                rel_y = int(cur[1]) - int(top)
                rgb = _overlay_cursor_rgb(rgb, out_size, rel_x, rel_y)
        mode = _parse_stream_layout_mode(layout_mode)
        if mode == "stretch" and target_size:
            rgb, out_size = _resize_rgb_to_target(rgb, out_size, target_size)
        else:
            crop_aspect = aspect_ratio if mode in {"crop", "fill"} else None
            rgb, out_size = _crop_rgb_to_aspect(rgb, out_size, crop_aspect)
            if scale_factor > 1:
                rgb, out_size = _downsample_rgb_nearest(rgb, out_size, scale_factor)
            rgb, out_size = _resize_rgb_to_fit_target(rgb, out_size, target_size)
        if grayscale:
            rgb = _rgb_to_grayscale(rgb)
        return rgb, out_size

    def _capture(sct: Any) -> Tuple[bytes, Tuple[int, int]]:
        mon = _desktop_monitor()
        img = sct.grab(mon)
        return _process_capture(
            img.rgb,
            img.size,
            int(mon.get("left", 0)),
            int(mon.get("top", 0)),
        )

    def _capture_dxcam() -> Tuple[bytes, Tuple[int, int]]:
        with DESKTOP_DXCAM_LOCK:
            camera = _desktop_dxcam()
            frame = camera.grab(new_frame_only=False)
            if frame is None:
                time.sleep(0.01)
                frame = camera.grab(new_frame_only=False)
            if frame is None:
                raise HTTPException(status_code=503, detail="Desktop capture unavailable.")
            if len(frame.shape) >= 3 and int(frame.shape[2]) >= 4:
                frame = frame[:, :, :3]
            if _desktop_dxcam_frame_looks_black(frame):
                _desktop_mark_dxcam_blacklisted_for_current_thread(selected_target_id)
                raise HTTPException(status_code=503, detail="Desktop capture returned a black frame.")
            out_size = (int(frame.shape[1]), int(frame.shape[0]))
            monitor = _desktop_dxcam_monitor()
            return _process_capture(
                frame.tobytes(),
                out_size,
                int(monitor.get("left", 0)),
                int(monitor.get("top", 0)),
                include_cursor_overlay=False,
            )

    # Prefer DXCAM when available for physical outputs, but skip it entirely for
    # virtual displays where this host's IDD path is known to require MSS.
    use_dxcam = (
        _desktop_capture_backend() == "dxcam"
        and not selected_target_virtual
        and not _desktop_is_dxcam_blacklisted_for_current_thread(selected_target_id)
    )
    if use_dxcam:
        try:
            return _capture_dxcam()
        except HTTPException as exc:
            print(
                "Desktop capture DXCAM fallback"
                f" target={selected_target_id or 'unknown'}"
                f" virtual={selected_target_virtual}"
                f" reason=http_{int(exc.status_code)}:{exc.detail}",
                flush=True,
            )
        except Exception as exc:
            print(
                "Desktop capture DXCAM fallback"
                f" target={selected_target_id or 'unknown'}"
                f" virtual={selected_target_virtual}"
                f" reason={type(exc).__name__}: {exc}",
                flush=True,
            )
            traceback.print_exc()

    if sct_instance is not None:
        return _capture(sct_instance)

    thread_local_sct = getattr(DESKTOP_CAPTURE_TLS, "sct", None)
    if thread_local_sct is None:
        thread_local_sct = mss()
        DESKTOP_CAPTURE_TLS.sct = thread_local_sct
    return _capture(thread_local_sct)


def _desktop_stream_format(value: Optional[str]) -> str:
    candidate = str(value or DESKTOP_STREAM_FORMAT_DEFAULT or "png").strip().lower()
    if candidate in {"jpg", "jpeg", "mjpeg"} and PILLOW_AVAILABLE:
        return "jpeg"
    return "png"


def _desktop_stream_quality(value: Optional[int]) -> int:
    try:
        numeric = int(value if value is not None else DESKTOP_STREAM_JPEG_QUALITY_DEFAULT)
    except Exception:
        numeric = DESKTOP_STREAM_JPEG_QUALITY_DEFAULT
    return _clamp(numeric, 40, 95)


def _desktop_encode_frame(
    rgb: bytes,
    out_size: Tuple[int, int],
    stream_format: str,
    png_level: int,
    jpeg_quality: int,
) -> Tuple[bytes, str]:
    if stream_format == "jpeg":
        image = Image.frombytes("RGB", (int(out_size[0]), int(out_size[1])), rgb)
        buffer = io.BytesIO()
        image.save(
            buffer,
            format="JPEG",
            quality=jpeg_quality,
            optimize=False,
            progressive=False,
            subsampling=0,
        )
        return buffer.getvalue(), "image/jpeg"
    return to_png(rgb, out_size, level=png_level), "image/png"


if AIORTC_AVAILABLE:
    class DesktopVideoTrack(VideoStreamTrack):
        def __init__(
            self,
            fps: float,
            scale_factor: int,
            grayscale: bool,
            aspect_ratio: Optional[float] = None,
            layout_mode: str = "fit",
            target_size: Optional[Tuple[int, int]] = None,
        ):
            super().__init__()
            self._fps = max(1.0, min(float(fps or 8.0), 30.0))
            self._scale_factor = _parse_stream_scale(scale_factor, default=1)
            self._grayscale = bool(grayscale)
            self._aspect_ratio = _parse_stream_aspect(aspect_ratio)
            self._layout_mode = _parse_stream_layout_mode(layout_mode)
            self._target_size = target_size
            self._frames_sent = 0
            self._clock_rate = 90000
            self._time_base = Fraction(1, self._clock_rate)
            self._timestamp_step = max(1, int(round(self._clock_rate / self._fps)))
            self._started_at: Optional[float] = None
            self._timestamp = 0

        async def _next_frame_timestamp(self) -> Tuple[int, Fraction]:
            if self._started_at is None:
                self._started_at = time.time()
                self._timestamp = 0
                return 0, self._time_base
            self._timestamp += self._timestamp_step
            target_time = self._started_at + (self._timestamp / self._clock_rate)
            delay = target_time - time.time()
            if delay > 0:
                await asyncio.sleep(delay)
            return self._timestamp, self._time_base

        async def recv(self):
            if self.readyState != "live":
                raise MediaStreamError

            pts, time_base = await self._next_frame_timestamp()
            capture_started = time.perf_counter()
            rgb, out_size = await asyncio.to_thread(
                _desktop_capture_rgb,
                self._scale_factor,
                self._grayscale,
                None,
                self._aspect_ratio,
                self._layout_mode,
                self._target_size,
            )
            capture_ms = (time.perf_counter() - capture_started) * 1000.0
            frame_array = np.frombuffer(rgb, dtype=np.uint8).reshape((int(out_size[1]), int(out_size[0]), 3))
            frame = VideoFrame.from_ndarray(frame_array, format="rgb24")
            frame.pts = pts
            frame.time_base = time_base
            self._frames_sent += 1
            return frame

        def stop(self) -> None:
            super().stop()


def _desktop_point(x: int, y: int) -> Dict[str, int]:
    mon = _desktop_monitor()
    if mon["width"] <= 0 or mon["height"] <= 0:
        raise HTTPException(status_code=500, detail="Invalid desktop monitor size.")
    sx = _clamp(int(x), 0, mon["width"] - 1)
    sy = _clamp(int(y), 0, mon["height"] - 1)
    return {
        "x": mon["left"] + sx,
        "y": mon["top"] + sy,
        "rel_x": sx,
        "rel_y": sy,
        **mon,
    }

def _win_user32():
    _ensure_windows_host()
    return ctypes.windll.user32

def _desktop_move_abs(x: int, y: int) -> None:
    user32 = _win_user32()
    user32.SetCursorPos(int(x), int(y))


def _desktop_click_hover_delay_s(screen_x: int, screen_y: int) -> float:
    return 0.03


def _desktop_click_at(
    x: int,
    y: int,
    button: str = "left",
    double: bool = False,
    action: str = "click",
    extra_info: int = REMOTE_MOUSE_EXTRA_INFO,
) -> None:
    _desktop_move_abs(int(x), int(y))
    time.sleep(_desktop_click_hover_delay_s(int(x), int(y)))
    _desktop_click_sendinput(button=button, double=double, action=action, extra_info=extra_info)

def _desktop_click(
    button: str = "left",
    double: bool = False,
    action: str = "click",
    extra_info: int = REMOTE_MOUSE_EXTRA_INFO,
) -> None:
    _desktop_click_sendinput(button=button, double=double, action=action, extra_info=extra_info)


def _desktop_click_sendinput(
    button: str = "left",
    double: bool = False,
    action: str = "click",
    extra_info: int = REMOTE_MOUSE_EXTRA_INFO,
) -> None:
    btn = (button or "left").strip().lower()
    click_action = (action or "click").strip().lower()
    mapping = {
        "left": (MOUSEEVENTF_LEFTDOWN, MOUSEEVENTF_LEFTUP),
        "right": (MOUSEEVENTF_RIGHTDOWN, MOUSEEVENTF_RIGHTUP),
        "middle": (MOUSEEVENTF_MIDDLEDOWN, MOUSEEVENTF_MIDDLEUP),
    }
    if btn not in mapping:
        raise HTTPException(status_code=400, detail="Unsupported mouse button.")
    if click_action not in {"click", "down", "up"}:
        raise HTTPException(status_code=400, detail="Unsupported mouse action.")
    down, up = mapping[btn]

    def _mouse_input(flags: int) -> INPUT:
        return INPUT(
            type=INPUT_MOUSE,
            union=INPUT_UNION(
                mi=MOUSEINPUT(
                    dx=0,
                    dy=0,
                    mouseData=0,
                    dwFlags=int(flags),
                    time=0,
                    dwExtraInfo=ULONG_PTR(int(extra_info or 0)),
                )
            ),
        )

    if click_action == "down":
        _send_inputs([_mouse_input(down)])
        return
    if click_action == "up":
        _send_inputs([_mouse_input(up)])
        return

    times = 2 if double else 1
    inputs = []
    for _ in range(times):
        inputs.append(_mouse_input(down))
        inputs.append(_mouse_input(up))
    _send_inputs(inputs)


def _desktop_scroll(delta: int) -> None:
    _send_inputs([
        INPUT(
            type=INPUT_MOUSE,
            union=INPUT_UNION(
                mi=MOUSEINPUT(
                    dx=0,
                    dy=0,
                    mouseData=int(delta),
                    dwFlags=MOUSEEVENTF_WHEEL,
                    time=0,
                    dwExtraInfo=REMOTE_MOUSE_EXTRA_INFO,
                )
            ),
        )
    ])


class _POINT(ctypes.Structure):
    _fields_ = [
        ("x", wintypes.LONG),
        ("y", wintypes.LONG),
    ]


def _win_window_from_point() -> Any:
    _ensure_windows_host()
    user32 = _win_user32()
    if not hasattr(_win_window_from_point, "_configured"):
        user32.WindowFromPoint.argtypes = [_POINT]
        user32.WindowFromPoint.restype = wintypes.HWND
        _win_window_from_point._configured = True  # type: ignore[attr-defined]
    return user32.WindowFromPoint


def _win_get_foreground_window() -> Any:
    _ensure_windows_host()
    user32 = _win_user32()
    if not hasattr(_win_get_foreground_window, "_configured"):
        user32.GetForegroundWindow.argtypes = []
        user32.GetForegroundWindow.restype = wintypes.HWND
        _win_get_foreground_window._configured = True  # type: ignore[attr-defined]
    return user32.GetForegroundWindow


def _win_enum_windows() -> Any:
    _ensure_windows_host()
    user32 = _win_user32()
    if not hasattr(_win_enum_windows, "_configured"):
        _win_enum_windows._callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)  # type: ignore[attr-defined]
        user32.EnumWindows.argtypes = [_win_enum_windows._callback_type, wintypes.LPARAM]  # type: ignore[attr-defined]
        user32.EnumWindows.restype = wintypes.BOOL
        _win_enum_windows._configured = True  # type: ignore[attr-defined]
    return user32.EnumWindows


def _win_get_ancestor() -> Any:
    _ensure_windows_host()
    user32 = _win_user32()
    if not hasattr(_win_get_ancestor, "_configured"):
        user32.GetAncestor.argtypes = [wintypes.HWND, wintypes.UINT]
        user32.GetAncestor.restype = wintypes.HWND
        _win_get_ancestor._configured = True  # type: ignore[attr-defined]
    return user32.GetAncestor


def _win_is_window_visible() -> Any:
    _ensure_windows_host()
    user32 = _win_user32()
    if not hasattr(_win_is_window_visible, "_configured"):
        user32.IsWindowVisible.argtypes = [wintypes.HWND]
        user32.IsWindowVisible.restype = wintypes.BOOL
        _win_is_window_visible._configured = True  # type: ignore[attr-defined]
    return user32.IsWindowVisible


def _win_get_window_rect() -> Any:
    _ensure_windows_host()
    user32 = _win_user32()
    if not hasattr(_win_get_window_rect, "_configured"):
        user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(RECT)]
        user32.GetWindowRect.restype = wintypes.BOOL
        _win_get_window_rect._configured = True  # type: ignore[attr-defined]
    return user32.GetWindowRect


def _win_get_dpi_for_window() -> Any:
    _ensure_windows_host()
    user32 = _win_user32()
    if not hasattr(_win_get_dpi_for_window, "_configured"):
        user32.GetDpiForWindow.argtypes = [wintypes.HWND]
        user32.GetDpiForWindow.restype = wintypes.UINT
        _win_get_dpi_for_window._configured = True  # type: ignore[attr-defined]
    return user32.GetDpiForWindow


def _win_dwm_get_window_attribute() -> Any:
    _ensure_windows_host()
    dwmapi = ctypes.windll.dwmapi
    if not hasattr(_win_dwm_get_window_attribute, "_configured"):
        dwmapi.DwmGetWindowAttribute.argtypes = [wintypes.HWND, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD]
        dwmapi.DwmGetWindowAttribute.restype = ctypes.c_long
        _win_dwm_get_window_attribute._configured = True  # type: ignore[attr-defined]
    return dwmapi.DwmGetWindowAttribute


def _win_send_message() -> Any:
    _ensure_windows_host()
    user32 = _win_user32()
    if not hasattr(_win_send_message, "_configured"):
        user32.SendMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
        user32.SendMessageW.restype = wintypes.LPARAM
        _win_send_message._configured = True  # type: ignore[attr-defined]
    return user32.SendMessageW


def _win_is_zoomed() -> Any:
    _ensure_windows_host()
    user32 = _win_user32()
    if not hasattr(_win_is_zoomed, "_configured"):
        user32.IsZoomed.argtypes = [wintypes.HWND]
        user32.IsZoomed.restype = wintypes.BOOL
        _win_is_zoomed._configured = True  # type: ignore[attr-defined]
    return user32.IsZoomed


def _make_lparam(x: int, y: int) -> int:
    return ((int(y) & 0xFFFF) << 16) | (int(x) & 0xFFFF)


def _win_is_window_cloaked(hwnd: wintypes.HWND) -> bool:
    cloaked = wintypes.DWORD(0)
    try:
        hr = int(_win_dwm_get_window_attribute()(hwnd, DWMWA_CLOAKED, ctypes.byref(cloaked), ctypes.sizeof(cloaked)))
        return hr == 0 and bool(cloaked.value)
    except Exception:
        return False


def _window_point_for_hit_test(hwnd: wintypes.HWND, x: int, y: int) -> Tuple[int, int]:
    try:
        dpi = int(_win_get_dpi_for_window()(hwnd))
    except Exception:
        dpi = 96
    scale = max(1.0, float(dpi or 96) / 96.0)
    return (int(round(float(x) * scale)), int(round(float(y) * scale)))


def _iter_top_level_windows() -> List[int]:
    windows: List[int] = []
    seen: Set[int] = set()
    enum_windows = _win_enum_windows()
    callback_type = _win_enum_windows._callback_type  # type: ignore[attr-defined]

    @callback_type
    def _collector(hwnd: wintypes.HWND, lparam: wintypes.LPARAM) -> wintypes.BOOL:
        handle_value = int(hwnd)
        if handle_value not in seen:
            seen.add(handle_value)
            windows.append(handle_value)
        return True

    enum_windows(_collector, 0)
    return windows


def _desktop_caption_syscommand_at(x: int, y: int) -> Optional[str]:
    point = _POINT(int(x), int(y))
    candidates: List[int] = []

    foreground = _win_get_foreground_window()()
    if foreground:
        foreground_root = _win_get_ancestor()(foreground, GA_ROOT) or foreground
        candidates.append(int(foreground_root))

    hwnd = _win_window_from_point()(point)
    if hwnd:
        point_root = _win_get_ancestor()(hwnd, GA_ROOT) or hwnd
        point_root_value = int(point_root)
        if point_root_value not in candidates:
            candidates.append(point_root_value)

    for handle_value in _iter_top_level_windows():
        if handle_value in candidates:
            continue
        hwnd_candidate = wintypes.HWND(handle_value)
        if not bool(_win_is_window_visible()(hwnd_candidate)):
            continue
        if _win_is_window_cloaked(hwnd_candidate):
            continue
        test_x, test_y = _window_point_for_hit_test(hwnd_candidate, int(x), int(y))
        rect = RECT()
        if not bool(_win_get_window_rect()(hwnd_candidate, ctypes.byref(rect))):
            continue
        if not (rect.left <= test_x <= rect.right and rect.top <= test_y <= rect.bottom):
            continue
        candidates.append(handle_value)

    for candidate in candidates:
        root = wintypes.HWND(candidate)
        test_x, test_y = _window_point_for_hit_test(root, int(x), int(y))
        hit = int(_win_send_message()(root, WM_NCHITTEST, 0, _make_lparam(test_x, test_y)))
        command = None
        command_name = None
        if hit == HTMINBUTTON:
            command = SC_MINIMIZE
            command_name = "minimize"
        elif hit == HTMAXBUTTON:
            command = SC_RESTORE if bool(_win_is_zoomed()(root)) else SC_MAXIMIZE
            command_name = "restore" if command == SC_RESTORE else "maximize"
        elif hit == HTCLOSE:
            command = SC_CLOSE
            command_name = "close"
        if command is not None:
            _win_send_message()(root, WM_SYSCOMMAND, int(command), 0)
            return command_name
    return None








def _ps_single_quote(value: str) -> str:
    # PowerShell single-quoted literals escape apostrophes by doubling them.
    return "'" + str(value or "").replace("'", "''") + "'"


def _run_powershell(script: str, timeout_s: int = 10, sta: bool = False) -> Dict[str, Any]:
    _ensure_windows_host()
    try:
        cmd = ["powershell", "-NoProfile"]
        if sta:
            cmd.append("-STA")
        cmd.extend(["-Command", script])
        p = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout_s,
            encoding="utf-8",
            errors="replace",
        )
        return {
            "exit_code": p.returncode,
            "stdout": (p.stdout or "").rstrip(),
            "stderr": (p.stderr or "").rstrip(),
        }
    except subprocess.TimeoutExpired:
        return {"exit_code": 124, "stdout": "", "stderr": f"timeout after {timeout_s}s"}
    except Exception as e:
        return {"exit_code": 125, "stdout": "", "stderr": f"exception: {type(e).__name__}: {e}"}


def _spawn_windows_background_process(args: List[str], *, detached: bool = True) -> Dict[str, Any]:
    _ensure_windows_host()
    kwargs: Dict[str, Any] = {
        "stdin": subprocess.DEVNULL,
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.DEVNULL,
    }
    if os.name == "nt":
        creationflags = 0
        if detached:
            creationflags |= getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
            creationflags |= getattr(subprocess, "DETACHED_PROCESS", 0)
        creationflags |= getattr(subprocess, "CREATE_NO_WINDOW", 0)
        if creationflags:
            kwargs["creationflags"] = creationflags
        if hasattr(subprocess, "STARTUPINFO"):
            startupinfo = subprocess.STARTUPINFO()
            if hasattr(subprocess, "STARTF_USESHOWWINDOW"):
                startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                startupinfo.wShowWindow = 0
            kwargs["startupinfo"] = startupinfo
    try:
        proc = subprocess.Popen(args, **kwargs)
        return {"ok": True, "pid": int(getattr(proc, "pid", 0) or 0)}
    except Exception as e:
        return {"ok": False, "detail": f"{type(e).__name__}: {e}"}


def _create_power_confirmation(action: str) -> Dict[str, Any]:
    expires_in = max(10, CODEX_POWER_CONFIRM_TTL_SECONDS)
    token = secrets.token_urlsafe(24)
    expires_at = time.time() + expires_in
    with POWER_CONFIRM_LOCK:
        now = time.time()
        for existing, entry in list(POWER_CONFIRMATIONS.items()):
            if float(entry.get("expires_at", 0) or 0) <= now:
                POWER_CONFIRMATIONS.pop(existing, None)
        POWER_CONFIRMATIONS[token] = {
            "action": action,
            "expires_at": expires_at,
        }
    return {
        "confirm_required": True,
        "confirm_token": token,
        "confirm_expires_in": expires_in,
    }


def _consume_power_confirmation(action: str, token: str) -> bool:
    candidate = str(token or "").strip()
    if not candidate:
        return False
    with POWER_CONFIRM_LOCK:
        now = time.time()
        for existing, entry in list(POWER_CONFIRMATIONS.items()):
            if float(entry.get("expires_at", 0) or 0) <= now:
                POWER_CONFIRMATIONS.pop(existing, None)
        entry = POWER_CONFIRMATIONS.get(candidate)
        if not entry or str(entry.get("action") or "") != action:
            return False
        POWER_CONFIRMATIONS.pop(candidate, None)
        return True


def _schedule_power_action(action: str) -> Dict[str, Any]:
    _ensure_windows_host()
    action_name = str(action or "").strip().lower()
    destructive = {"sleep", "hibernate", "restart", "shutdown"}
    if action_name not in {"lock", *destructive}:
        raise HTTPException(status_code=400, detail="Unsupported power action.")
    delay_ms = int(max(0.5, CODEX_POWER_ACTION_DELAY_SECONDS) * 1000)
    if action_name == "lock":
        script = (
            f"Start-Sleep -Milliseconds {delay_ms}; "
            "rundll32.exe user32.dll,LockWorkStation"
        )
        args = ["powershell", "-NoProfile", "-Command", script]
    elif action_name == "sleep":
        script = (
            f"Start-Sleep -Milliseconds {delay_ms}; "
            "Add-Type -AssemblyName System.Windows.Forms; "
            "[System.Windows.Forms.Application]::SetSuspendState([System.Windows.Forms.PowerState]::Suspend, $false, $false) | Out-Null"
        )
        args = ["powershell", "-NoProfile", "-STA", "-Command", script]
    elif action_name == "hibernate":
        script = f"Start-Sleep -Milliseconds {delay_ms}; shutdown.exe /h"
        args = ["powershell", "-NoProfile", "-Command", script]
    elif action_name == "restart":
        script = f"Start-Sleep -Milliseconds {delay_ms}; shutdown.exe /r /t 0 /f"
        args = ["powershell", "-NoProfile", "-Command", script]
    else:
        script = f"Start-Sleep -Milliseconds {delay_ms}; shutdown.exe /s /t 0 /f"
        args = ["powershell", "-NoProfile", "-Command", script]
    # Desktop-facing power actions need to stay in the current interactive
    # Windows session. Detached background flags work for backend helpers, but
    # they are unreliable for LockWorkStation / suspend style actions.
    started = _spawn_windows_background_process(args, detached=False)
    if not started.get("ok"):
        raise HTTPException(status_code=500, detail=str(started.get("detail") or "power_action_failed"))
    return {
        "ok": True,
        "action": action_name,
        "accepted": True,
        "scheduled_at": time.time() + (0 if action_name == "lock" else CODEX_POWER_ACTION_DELAY_SECONDS),
        "detail": "Power action scheduled." if action_name != "lock" else "Desktop locked.",
        "pid": started.get("pid", 0),
    }

def _desktop_send_text(text: str) -> Dict[str, Any]:
    # Clipboard + Ctrl+V handles large text and special chars better than raw SendKeys.
    if len(text) > MAX_DESKTOP_TEXT:
        raise HTTPException(status_code=400, detail=f"Text too long (max {MAX_DESKTOP_TEXT}).")
    script = (
        "Add-Type -AssemblyName System.Windows.Forms; "
        "$txt = @'\n"
        + text
        + "\n'@; "
        "Set-Clipboard -Value $txt"
    )
    result = _run_powershell(script, timeout_s=10, sta=True)
    if result.get("exit_code") == 0:
        time.sleep(0.12)
        _send_vk_combo([VK_CONTROL], 0x56)
        time.sleep(0.08)
        result["mode"] = "clipboard_native_paste"
    return result


def _desktop_paste_target_family(process_name: str, window_title: str) -> str:
    proc = str(process_name or "").strip().lower()
    title = str(window_title or "").strip().lower()
    if proc in {"powerpnt", "pptview"}:
        return "powerpoint"
    if proc in {"winword"}:
        return "word"
    if proc in {"onenote"}:
        return "onenote"
    if proc in {"mspaint"}:
        return "paint"
    if proc in {"wps", "wpp"}:
        if any(token in title for token in {"presentation", ".ppt", ".pptx", "slides"}):
            return "wps_presentation"
        if any(token in title for token in {"document", ".doc", ".docx", ".rtf", "writer"}):
            return "wps_document"
    return ""


def _desktop_paste_target_label(target_family: str, process_name: str, window_title: str) -> str:
    family = str(target_family or "").strip().lower()
    if family == "powerpoint":
        return "PowerPoint"
    if family == "word":
        return "Word"
    if family == "onenote":
        return "OneNote"
    if family == "paint":
        return "Paint"
    if family == "wps_presentation":
        return "WPS Presentation"
    if family == "wps_document":
        return "WPS Document"
    title = str(window_title or "").strip()
    if title:
        return title[:120]
    proc = str(process_name or "").strip()
    return proc or "Windows app"


def _desktop_foreground_target_info() -> Dict[str, Any]:
    _ensure_windows_host()
    user32 = _win_user32()
    if not hasattr(user32.GetWindowThreadProcessId, "_codrex_configured"):
        user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
        user32.GetWindowThreadProcessId.restype = wintypes.DWORD
        user32.GetWindowThreadProcessId._codrex_configured = True  # type: ignore[attr-defined]
    if not hasattr(user32.GetWindowTextLengthW, "_codrex_configured"):
        user32.GetWindowTextLengthW.argtypes = [wintypes.HWND]
        user32.GetWindowTextLengthW.restype = ctypes.c_int
        user32.GetWindowTextLengthW._codrex_configured = True  # type: ignore[attr-defined]
    if not hasattr(user32.GetWindowTextW, "_codrex_configured"):
        user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
        user32.GetWindowTextW.restype = ctypes.c_int
        user32.GetWindowTextW._codrex_configured = True  # type: ignore[attr-defined]
    hwnd = int(user32.GetForegroundWindow() or 0)
    if hwnd <= 0:
        return {"hwnd": 0, "pid": 0, "process_name": "", "window_title": "", "target_family": "", "target_label": ""}
    title = ""
    try:
        text_len = int(user32.GetWindowTextLengthW(wintypes.HWND(hwnd)) or 0)
        if text_len > 0:
            buf = ctypes.create_unicode_buffer(text_len + 1)
            user32.GetWindowTextW(wintypes.HWND(hwnd), buf, text_len + 1)
            title = str(buf.value or "").strip()
    except Exception:
        title = ""
    pid = wintypes.DWORD(0)
    try:
        user32.GetWindowThreadProcessId(wintypes.HWND(hwnd), ctypes.byref(pid))
    except Exception:
        return {"hwnd": hwnd, "pid": 0, "process_name": "", "window_title": title, "target_family": "", "target_label": _desktop_paste_target_label("", "", title)}
    if int(pid.value or 0) <= 0:
        return {"hwnd": hwnd, "pid": 0, "process_name": "", "window_title": title, "target_family": "", "target_label": _desktop_paste_target_label("", "", title)}
    process_name = ""
    try:
        result = subprocess.run(
            [
                "powershell",
                "-NoProfile",
                "-Command",
                f"$p = Get-Process -Id {int(pid.value)} -ErrorAction SilentlyContinue; if ($p) {{ $p.ProcessName }}",
            ],
            capture_output=True,
            text=True,
            timeout=4,
            encoding="utf-8",
            errors="replace",
        )
    except Exception:
        result = None
    if result and result.returncode == 0:
        process_name = str(result.stdout or "").strip().lower()
    target_family = _desktop_paste_target_family(process_name, title)
    return {
        "hwnd": hwnd,
        "pid": int(pid.value or 0),
        "process_name": process_name,
        "window_title": title,
        "target_family": target_family,
        "target_label": _desktop_paste_target_label(target_family, process_name, title),
    }


def _desktop_restore_foreground_window(hwnd: int) -> bool:
    try:
        target_hwnd = int(hwnd or 0)
    except Exception:
        target_hwnd = 0
    if target_hwnd <= 0:
        return False
    user32 = _win_user32()
    if not hasattr(user32.IsWindow, "_codrex_configured"):
        user32.IsWindow.argtypes = [wintypes.HWND]
        user32.IsWindow.restype = wintypes.BOOL
        user32.IsWindow._codrex_configured = True  # type: ignore[attr-defined]
    if not hasattr(user32.IsIconic, "_codrex_configured"):
        user32.IsIconic.argtypes = [wintypes.HWND]
        user32.IsIconic.restype = wintypes.BOOL
        user32.IsIconic._codrex_configured = True  # type: ignore[attr-defined]
    if not hasattr(user32.ShowWindow, "_codrex_configured"):
        user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
        user32.ShowWindow.restype = wintypes.BOOL
        user32.ShowWindow._codrex_configured = True  # type: ignore[attr-defined]
    if not hasattr(user32.SetForegroundWindow, "_codrex_configured"):
        user32.SetForegroundWindow.argtypes = [wintypes.HWND]
        user32.SetForegroundWindow.restype = wintypes.BOOL
        user32.SetForegroundWindow._codrex_configured = True  # type: ignore[attr-defined]
    hwnd_handle = wintypes.HWND(target_hwnd)
    try:
        if not bool(user32.IsWindow(hwnd_handle)):
            return False
        if bool(user32.IsIconic(hwnd_handle)):
            user32.ShowWindow(hwnd_handle, 9)
            time.sleep(0.05)
        user32.ShowWindow(hwnd_handle, 5)
        time.sleep(0.04)
        return bool(user32.SetForegroundWindow(hwnd_handle))
    except Exception:
        return False


def _desktop_window_handoff_powershell_helpers() -> str:
    return r"""
if (-not ('CodrexDesktopWindowNative' -as [type])) {
  Add-Type @"
using System;
using System.Collections.Generic;
using System.Runtime.InteropServices;
using System.Text;
public struct RECT {
  public int Left;
  public int Top;
  public int Right;
  public int Bottom;
}
public struct POINT {
  public int X;
  public int Y;
}
public struct WINDOWPLACEMENT {
  public int length;
  public int flags;
  public int showCmd;
  public POINT ptMinPosition;
  public POINT ptMaxPosition;
  public RECT rcNormalPosition;
}
public class DesktopWindowSnapshot {
  public long Hwnd { get; set; }
  public int Left { get; set; }
  public int Top { get; set; }
  public int Width { get; set; }
  public int Height { get; set; }
  public int ShowCmd { get; set; }
  public string Title { get; set; }
  public string ClassName { get; set; }
}
public static class CodrexDesktopWindowNative {
  public delegate bool EnumWindowsProc(IntPtr hWnd, IntPtr lParam);
  [DllImport("user32.dll")] public static extern bool EnumWindows(EnumWindowsProc lpEnumFunc, IntPtr lParam);
  [DllImport("user32.dll")] public static extern IntPtr GetForegroundWindow();
  [DllImport("user32.dll")] public static extern IntPtr GetShellWindow();
  [DllImport("user32.dll")] public static extern bool IsWindow(IntPtr hWnd);
  [DllImport("user32.dll")] public static extern bool IsWindowVisible(IntPtr hWnd);
  [DllImport("user32.dll")] public static extern bool IsIconic(IntPtr hWnd);
  [DllImport("user32.dll")] public static extern bool GetWindowRect(IntPtr hWnd, out RECT rect);
  [DllImport("user32.dll")] public static extern bool GetWindowPlacement(IntPtr hWnd, ref WINDOWPLACEMENT placement);
  [DllImport("user32.dll")] public static extern bool SetWindowPos(IntPtr hWnd, IntPtr hWndInsertAfter, int X, int Y, int cx, int cy, uint uFlags);
  [DllImport("user32.dll")] public static extern bool ShowWindow(IntPtr hWnd, int nCmdShow);
  [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr hWnd);
  [DllImport("user32.dll", CharSet = CharSet.Unicode)] public static extern int GetWindowTextLengthW(IntPtr hWnd);
  [DllImport("user32.dll", CharSet = CharSet.Unicode)] public static extern int GetWindowTextW(IntPtr hWnd, StringBuilder lpString, int nMaxCount);
  [DllImport("user32.dll", CharSet = CharSet.Unicode)] public static extern int GetClassNameW(IntPtr hWnd, StringBuilder lpClassName, int nMaxCount);

  public static string ReadWindowTitle(IntPtr hWnd) {
    int length = Math.Max(0, GetWindowTextLengthW(hWnd));
    if (length <= 0) {
      return string.Empty;
    }
    var builder = new StringBuilder(length + 1);
    GetWindowTextW(hWnd, builder, builder.Capacity);
    return builder.ToString();
  }

  public static string ReadWindowClass(IntPtr hWnd) {
    var builder = new StringBuilder(260);
    GetClassNameW(hWnd, builder, builder.Capacity);
    return builder.ToString();
  }

  public static DesktopWindowSnapshot[] EnumerateTopLevelWindows() {
    var windows = new List<DesktopWindowSnapshot>();
    IntPtr shellWindow = GetShellWindow();
    EnumWindows(delegate (IntPtr hWnd, IntPtr lParam) {
      if (hWnd == IntPtr.Zero || hWnd == shellWindow || !IsWindow(hWnd) || !IsWindowVisible(hWnd)) {
        return true;
      }
      RECT rect;
      if (!GetWindowRect(hWnd, out rect)) {
        return true;
      }
      int width = Math.Max(0, rect.Right - rect.Left);
      int height = Math.Max(0, rect.Bottom - rect.Top);
      var placement = new WINDOWPLACEMENT();
      placement.length = Marshal.SizeOf(typeof(WINDOWPLACEMENT));
      GetWindowPlacement(hWnd, ref placement);
      windows.Add(new DesktopWindowSnapshot {
        Hwnd = hWnd.ToInt64(),
        Left = rect.Left,
        Top = rect.Top,
        Width = width,
        Height = height,
        ShowCmd = placement.showCmd,
        Title = ReadWindowTitle(hWnd),
        ClassName = ReadWindowClass(hWnd),
      });
      return true;
    }, IntPtr.Zero);
    return windows.ToArray();
  }
}
"@
}
"""


def _desktop_move_foreground_window_to_target(
    source_target: Dict[str, Any],
    destination_target: Dict[str, Any],
) -> Dict[str, Any]:
    src_left = int(source_target.get("left") or 0)
    src_top = int(source_target.get("top") or 0)
    src_width = max(1, int(source_target.get("width") or 0))
    src_height = max(1, int(source_target.get("height") or 0))
    dst_left = int(destination_target.get("left") or 0)
    dst_top = int(destination_target.get("top") or 0)
    dst_width = max(1, int(destination_target.get("width") or 0))
    dst_height = max(1, int(destination_target.get("height") or 0))
    script = _desktop_window_handoff_powershell_helpers() + f"""
$srcLeft = {src_left}
$srcTop = {src_top}
$srcWidth = {src_width}
$srcHeight = {src_height}
$dstLeft = {dst_left}
$dstTop = {dst_top}
$dstWidth = {dst_width}
$dstHeight = {dst_height}
$hwnd = [CodrexDesktopWindowNative]::GetForegroundWindow()
if ($hwnd -eq [IntPtr]::Zero -or -not [CodrexDesktopWindowNative]::IsWindow($hwnd)) {{
  @{{ ok = $false; detail = 'no_foreground_window' }} | ConvertTo-Json -Compress
  exit 0
}}
$rect = New-Object RECT
if (-not [CodrexDesktopWindowNative]::GetWindowRect($hwnd, [ref]$rect)) {{
  @{{ ok = $false; detail = 'get_window_rect_failed' }} | ConvertTo-Json -Compress
  exit 0
}}
$placement = New-Object WINDOWPLACEMENT
$placement.length = [System.Runtime.InteropServices.Marshal]::SizeOf([type][WINDOWPLACEMENT])
[void][CodrexDesktopWindowNative]::GetWindowPlacement($hwnd, [ref]$placement)
$showCmd = [int]$placement.showCmd
$width = [Math]::Max(200, $rect.Right - $rect.Left)
$height = [Math]::Max(120, $rect.Bottom - $rect.Top)
$relLeft = $rect.Left - $srcLeft
$relTop = $rect.Top - $srcTop
$newWidth = [Math]::Min($width, $dstWidth)
$newHeight = [Math]::Min($height, $dstHeight)
$newLeft = [Math]::Max($dstLeft, [Math]::Min($dstLeft + $dstWidth - $newWidth, $dstLeft + $relLeft))
$newTop = [Math]::Max($dstTop, [Math]::Min($dstTop + $dstHeight - $newHeight, $dstTop + $relTop))
if ($showCmd -eq 3) {{
  [void][CodrexDesktopWindowNative]::ShowWindow($hwnd, 9)
  Start-Sleep -Milliseconds 60
}}
[void][CodrexDesktopWindowNative]::SetWindowPos($hwnd, [IntPtr]::Zero, $newLeft, $newTop, $newWidth, $newHeight, 0x0014)
if ($showCmd -eq 3) {{
  [void][CodrexDesktopWindowNative]::ShowWindow($hwnd, 3)
}} else {{
  [void][CodrexDesktopWindowNative]::ShowWindow($hwnd, 5)
}}
[void][CodrexDesktopWindowNative]::SetForegroundWindow($hwnd)
@{{
  ok = $true
  hwnd = [Int64]$hwnd
  show_cmd = $showCmd
  restore_rect = @{{
    left = $rect.Left
    top = $rect.Top
    width = [Math]::Max(1, $rect.Right - $rect.Left)
    height = [Math]::Max(1, $rect.Bottom - $rect.Top)
  }}
}} | ConvertTo-Json -Compress -Depth 4
"""
    result = _run_powershell(script, timeout_s=8, sta=True)
    raw = str(result.get("stdout") or "").strip()
    if result.get("exit_code") != 0:
        print(f"Virtual-display window handoff failed: {result.get('stderr') or raw or 'unknown_error'}", flush=True)
        return {}
    try:
        payload = json.loads(raw) if raw else {}
    except Exception:
        payload = {}
    if not isinstance(payload, dict) or not payload.get("ok"):
        return {}
    restore_rect = payload.get("restore_rect") or {}
    return {
        "hwnd": int(payload.get("hwnd") or 0),
        "show_cmd": int(payload.get("show_cmd") or 0),
        "restore_rect": {
            "left": int(restore_rect.get("left") or 0),
            "top": int(restore_rect.get("top") or 0),
            "width": max(1, int(restore_rect.get("width") or 0)),
            "height": max(1, int(restore_rect.get("height") or 0)),
        },
        "source_target_id": str(source_target.get("id") or "").strip().lower(),
        "destination_target_id": str(destination_target.get("id") or "").strip().lower(),
    }


def _desktop_move_workspace_to_target(
    source_target: Dict[str, Any],
    destination_target: Dict[str, Any],
    *,
    allow_foreground_fallback: bool = True,
) -> List[Dict[str, Any]]:
    src_left = int(source_target.get("left") or 0)
    src_top = int(source_target.get("top") or 0)
    src_width = max(1, int(source_target.get("width") or 0))
    src_height = max(1, int(source_target.get("height") or 0))
    dst_left = int(destination_target.get("left") or 0)
    dst_top = int(destination_target.get("top") or 0)
    dst_width = max(1, int(destination_target.get("width") or 0))
    dst_height = max(1, int(destination_target.get("height") or 0))
    script = _desktop_window_handoff_powershell_helpers() + f"""
$srcLeft = {src_left}
$srcTop = {src_top}
$srcWidth = {src_width}
$srcHeight = {src_height}
$dstLeft = {dst_left}
$dstTop = {dst_top}
$dstWidth = {dst_width}
$dstHeight = {dst_height}
$excludeClasses = @('Progman', 'WorkerW', 'Shell_TrayWnd', 'Shell_SecondaryTrayWnd')
$foreground = [int64][CodrexDesktopWindowNative]::GetForegroundWindow()
$windows = @()
foreach ($window in [CodrexDesktopWindowNative]::EnumerateTopLevelWindows()) {{
  if (-not $window) {{ continue }}
  $className = [string]$window.ClassName
  $title = [string]$window.Title
  if ($excludeClasses -contains $className) {{ continue }}
  if ([string]::IsNullOrWhiteSpace($className) -and [string]::IsNullOrWhiteSpace($title)) {{ continue }}
  if ([int]$window.Width -lt 140 -or [int]$window.Height -lt 90) {{ continue }}
  $intersects = (([int]$window.Left + [int]$window.Width) -gt $srcLeft) -and ([int]$window.Left -lt ($srcLeft + $srcWidth)) -and (([int]$window.Top + [int]$window.Height) -gt $srcTop) -and ([int]$window.Top -lt ($srcTop + $srcHeight))
  if (-not $intersects) {{ continue }}
  $showCmd = [int]$window.ShowCmd
  $hwnd = [IntPtr]::new([int64]$window.Hwnd)
  if ($hwnd -eq [IntPtr]::Zero -or -not [CodrexDesktopWindowNative]::IsWindow($hwnd)) {{ continue }}
  $width = [Math]::Max(220, [int]$window.Width)
  $height = [Math]::Max(120, [int]$window.Height)
  $newWidth = [Math]::Min($width, $dstWidth)
  $newHeight = [Math]::Min($height, $dstHeight)
  $relLeft = [int]$window.Left - $srcLeft
  $relTop = [int]$window.Top - $srcTop
  $newLeft = [Math]::Max($dstLeft, [Math]::Min($dstLeft + $dstWidth - $newWidth, $dstLeft + $relLeft))
  $newTop = [Math]::Max($dstTop, [Math]::Min($dstTop + $dstHeight - $newHeight, $dstTop + $relTop))
  if ($showCmd -eq 3) {{
    [void][CodrexDesktopWindowNative]::ShowWindow($hwnd, 9)
    Start-Sleep -Milliseconds 40
    $newLeft = $dstLeft
    $newTop = $dstTop
    $newWidth = $dstWidth
    $newHeight = $dstHeight
  }}
  [void][CodrexDesktopWindowNative]::SetWindowPos($hwnd, [IntPtr]::Zero, $newLeft, $newTop, $newWidth, $newHeight, 0x0014)
  if ($showCmd -eq 3) {{
    [void][CodrexDesktopWindowNative]::ShowWindow($hwnd, 3)
  }} else {{
    [void][CodrexDesktopWindowNative]::ShowWindow($hwnd, 5)
  }}
  $windows += @{{
    hwnd = [int64]$window.Hwnd
    show_cmd = $showCmd
    title = $title
    class_name = $className
    restore_rect = @{{
      left = [int]$window.Left
      top = [int]$window.Top
      width = [Math]::Max(1, [int]$window.Width)
      height = [Math]::Max(1, [int]$window.Height)
    }}
  }}
}}
if ($windows.Count -gt 0) {{
  $focusWindow = $windows | Where-Object {{ [int64]$_.hwnd -eq $foreground }} | Select-Object -First 1
  if (-not $focusWindow) {{
    $focusWindow = $windows | Select-Object -First 1
  }}
  if ($focusWindow) {{
    [void][CodrexDesktopWindowNative]::SetForegroundWindow([IntPtr]::new([int64]$focusWindow.hwnd))
  }}
}}
@{{
  ok = ($windows.Count -gt 0)
  windows = $windows
}} | ConvertTo-Json -Compress -Depth 6
"""
    result = _run_powershell(script, timeout_s=12, sta=True)
    raw = str(result.get("stdout") or "").strip()
    if result.get("exit_code") != 0:
        print(f"Virtual-display workspace handoff failed: {result.get('stderr') or raw or 'unknown_error'}", flush=True)
        return []
    try:
        payload = json.loads(raw) if raw else {}
    except Exception:
        payload = {}
    windows = payload.get("windows") if isinstance(payload, dict) else []
    moved: List[Dict[str, Any]] = []
    for item in list(windows or []):
        if not isinstance(item, dict):
            continue
        restore_rect = dict(item.get("restore_rect") or {})
        moved.append({
            "hwnd": int(item.get("hwnd") or 0),
            "show_cmd": int(item.get("show_cmd") or 0),
            "title": str(item.get("title") or "").strip(),
            "class_name": str(item.get("class_name") or "").strip(),
            "restore_rect": {
                "left": int(restore_rect.get("left") or 0),
                "top": int(restore_rect.get("top") or 0),
                "width": max(1, int(restore_rect.get("width") or 0)),
                "height": max(1, int(restore_rect.get("height") or 0)),
            },
            "source_target_id": str(source_target.get("id") or "").strip().lower(),
            "destination_target_id": str(destination_target.get("id") or "").strip().lower(),
        })
    if moved:
        return moved
    if not allow_foreground_fallback:
        return []
    fallback = _desktop_move_foreground_window_to_target(source_target, destination_target)
    return [fallback] if fallback else []


def _desktop_clamp_restore_rect_to_target(
    restore_rect: Dict[str, Any],
    target: Optional[Dict[str, Any]],
) -> Dict[str, int]:
    rect = dict(restore_rect or {})
    left = int(rect.get("left") or 0)
    top = int(rect.get("top") or 0)
    width = max(1, int(rect.get("width") or 0))
    height = max(1, int(rect.get("height") or 0))
    target_payload = dict(target or {})
    target_width = int(target_payload.get("width") or 0)
    target_height = int(target_payload.get("height") or 0)
    if target_width <= 0 or target_height <= 0:
        return {
            "left": left,
            "top": top,
            "width": width,
            "height": height,
        }
    target_left = int(target_payload.get("left") or 0)
    target_top = int(target_payload.get("top") or 0)
    clamped_width = min(width, max(1, target_width))
    clamped_height = min(height, max(1, target_height))
    clamped_left = max(target_left, min(target_left + target_width - clamped_width, left))
    clamped_top = max(target_top, min(target_top + target_height - clamped_height, top))
    return {
        "left": clamped_left,
        "top": clamped_top,
        "width": clamped_width,
        "height": clamped_height,
    }


def _desktop_repatriate_virtual_workspace(
    previous_target_id: str,
    virtual_target_id: str,
) -> int:
    previous_id = str(previous_target_id or "").strip().lower()
    virtual_id = str(virtual_target_id or "").strip().lower()
    if not previous_id or not virtual_id or previous_id == virtual_id:
        return 0
    targets_payload = _desktop_targets_payload()
    current_targets = list(targets_payload.get("targets") or [])
    source_target = _desktop_find_target_item(virtual_id, current_targets)
    destination_target = _desktop_find_target_item(previous_id, current_targets)
    if not source_target or not destination_target:
        return 0
    moved = _desktop_move_workspace_to_target(
        source_target,
        destination_target,
        allow_foreground_fallback=False,
    )
    return len(list(moved or []))


def _desktop_restore_window_handoff(handoff: Optional[Dict[str, Any]]) -> bool:
    payload = dict(handoff or {})
    hwnd = int(payload.get("hwnd") or 0)
    restore_rect = dict(payload.get("restore_rect") or {})
    if hwnd <= 0 or not restore_rect:
        return False
    source_target_id = str(payload.get("source_target_id") or "").strip().lower()
    destination_target_id = str(payload.get("destination_target_id") or "").strip().lower()
    targets_payload = _desktop_targets_payload()
    current_targets = list(targets_payload.get("targets") or [])
    target = _desktop_find_target_item(source_target_id, current_targets)
    if not target and destination_target_id:
        target = _desktop_find_target_item(destination_target_id, current_targets)
    if not target:
        target = _desktop_first_physical_target_item(current_targets) or dict(targets_payload.get("active_target") or {})
    clamped_rect = _desktop_clamp_restore_rect_to_target(restore_rect, target)
    left = int(clamped_rect.get("left") or 0)
    top = int(clamped_rect.get("top") or 0)
    width = max(1, int(clamped_rect.get("width") or 0))
    height = max(1, int(clamped_rect.get("height") or 0))
    show_cmd = int(payload.get("show_cmd") or 0)
    script = _desktop_window_handoff_powershell_helpers() + f"""
$hwnd = [IntPtr]::new({hwnd})
if ($hwnd -eq [IntPtr]::Zero -or -not [CodrexDesktopWindowNative]::IsWindow($hwnd)) {{
  @{{ ok = $false; detail = 'window_missing' }} | ConvertTo-Json -Compress
  exit 0
}}
$showCmd = {show_cmd}
if ($showCmd -eq 3) {{
  [void][CodrexDesktopWindowNative]::ShowWindow($hwnd, 9)
  Start-Sleep -Milliseconds 60
}}
[void][CodrexDesktopWindowNative]::SetWindowPos($hwnd, [IntPtr]::Zero, {left}, {top}, {width}, {height}, 0x0014)
if ($showCmd -eq 3) {{
  [void][CodrexDesktopWindowNative]::ShowWindow($hwnd, 3)
}} else {{
  [void][CodrexDesktopWindowNative]::ShowWindow($hwnd, 5)
}}
[void][CodrexDesktopWindowNative]::SetForegroundWindow($hwnd)
@{{ ok = $true }} | ConvertTo-Json -Compress
"""
    result = _run_powershell(script, timeout_s=8, sta=True)
    raw = str(result.get("stdout") or "").strip()
    if result.get("exit_code") != 0:
        print(f"Virtual-display window restore failed: {result.get('stderr') or raw or 'unknown_error'}", flush=True)
        return False
    try:
        restored = json.loads(raw) if raw else {}
    except Exception:
        restored = {}
    return bool(isinstance(restored, dict) and restored.get("ok"))


def _desktop_restore_window_handoffs(handoffs: Optional[List[Dict[str, Any]]]) -> int:
    restored = 0
    for handoff in list(handoffs or []):
        try:
            if _desktop_restore_window_handoff(handoff):
                restored += 1
        except Exception:
            pass
    return restored


def _desktop_foreground_process_name() -> str:
    info = _desktop_foreground_target_info()
    return str(info.get("process_name") or "").strip().lower()


def _desktop_prepare_clipboard_image_file(path_for_windows: str) -> str:
    host_path = _normalize_host_path(path_for_windows)
    if not PILLOW_AVAILABLE or Image is None:
        return host_path
    ext = os.path.splitext(host_path)[1].lower()
    if ext == ".bmp":
        return host_path
    os.makedirs(CODEX_HOST_PASTE_CACHE_DIR, exist_ok=True)
    target_name = (os.path.splitext(os.path.basename(host_path))[0] or "clipboard-image") + ".bmp"
    prepared_path = _host_unique_target_path(CODEX_HOST_PASTE_CACHE_DIR, target_name)
    with Image.open(host_path) as image:
        converted = image.convert("RGB")
        converted.save(prepared_path, format="BMP")
    return prepared_path


def _desktop_clipboard_set_image_file(path_for_windows: str, target_family: str = "") -> Dict[str, Any]:
    prepared_path = _desktop_prepare_clipboard_image_file(path_for_windows)
    quoted_path = _ps_single_quote(prepared_path)
    family = str(target_family or "").strip().lower()
    if family == "paint":
        script = (
            "Add-Type -AssemblyName System.Windows.Forms; "
            "Add-Type -AssemblyName System.Drawing; "
            "$path = " + quoted_path + "; "
            "if (!(Test-Path -LiteralPath $path)) { throw 'image_not_found' }; "
            "$source = New-Object System.Drawing.Bitmap $path; "
            "try { "
            "$bmp = New-Object System.Drawing.Bitmap $source; "
            "try { "
            "[System.Windows.Forms.Clipboard]::Clear(); "
            "[System.Windows.Forms.Clipboard]::SetImage($bmp); "
            "Start-Sleep -Milliseconds 140 "
            "} finally { $bmp.Dispose() } "
            "} finally { $source.Dispose() }"
        )
    else:
        script = (
            "Add-Type -AssemblyName System.Windows.Forms; "
            "Add-Type -AssemblyName System.Drawing; "
            "$path = " + quoted_path + "; "
            "if (!(Test-Path -LiteralPath $path)) { throw 'image_not_found' }; "
            "$source = New-Object System.Drawing.Bitmap $path; "
            "try { "
            "$bmp = New-Object System.Drawing.Bitmap $source; "
            "$pngStream = New-Object System.IO.MemoryStream; "
            "try { "
            "$bmp.Save($pngStream, [System.Drawing.Imaging.ImageFormat]::Png); "
            "$pngBytes = $pngStream.ToArray(); "
            "$pngData = New-Object System.IO.MemoryStream(,$pngBytes); "
            "try { "
            "$files = New-Object System.Collections.Specialized.StringCollection; "
            "[void]$files.Add($path); "
            "$data = New-Object System.Windows.Forms.DataObject; "
            "$data.SetData([System.Windows.Forms.DataFormats]::Bitmap, $true, $bmp); "
            "$data.SetData('PNG', $false, $pngData); "
            "$data.SetFileDropList($files); "
            "[System.Windows.Forms.Clipboard]::Clear(); "
            "[System.Windows.Forms.Clipboard]::SetDataObject($data, $true, 8, 120); "
            "Start-Sleep -Milliseconds 140 "
            "} finally { $pngData.Dispose() } "
            "} finally { $pngStream.Dispose(); $bmp.Dispose() } "
            "} finally { $source.Dispose() }"
        )
    return _run_powershell(script, timeout_s=12, sta=True)


def _desktop_try_office_image_paste(target_info: Dict[str, Any]) -> Dict[str, Any]:
    family = str((target_info or {}).get("target_family") or "").strip().lower()
    if family == "powerpoint":
        script = r"""
$ErrorActionPreference = 'SilentlyContinue'
$ok = $false
try { $app = [System.Runtime.InteropServices.Marshal]::GetActiveObject('PowerPoint.Application') } catch { $app = $null }
if ($app -and $app.ActiveWindow) {
  try {
    if ($app.CommandBars) {
      $app.CommandBars.ExecuteMso('Paste')
      $ok = $true
    }
  } catch {}
  if (-not $ok) {
    try {
      [void]$app.ActiveWindow.View.Paste()
      $ok = $true
    } catch {}
  }
}
if ($ok) {
  @{ ok = $true; mode = 'powerpoint_com_paste' } | ConvertTo-Json -Compress
  exit 0
}
@{ ok = $false; detail = 'powerpoint_com_paste_failed' } | ConvertTo-Json -Compress
exit 3
"""
    elif family == "word":
        script = r"""
$ErrorActionPreference = 'SilentlyContinue'
$ok = $false
try { $app = [System.Runtime.InteropServices.Marshal]::GetActiveObject('Word.Application') } catch { $app = $null }
if ($app) {
  try {
    if ($app.Selection) {
      $app.Selection.Paste()
      $ok = $true
    }
  } catch {}
  if (-not $ok) {
    try {
      if ($app.CommandBars) {
        $app.CommandBars.ExecuteMso('Paste')
        $ok = $true
      }
    } catch {}
  }
}
if ($ok) {
  @{ ok = $true; mode = 'word_com_paste' } | ConvertTo-Json -Compress
  exit 0
}
@{ ok = $false; detail = 'word_com_paste_failed' } | ConvertTo-Json -Compress
exit 3
"""
    else:
        return {"exit_code": 3, "stdout": "", "stderr": "office_com_paste_unavailable"}
    result = _run_powershell(script, timeout_s=8, sta=True)
    raw = str(result.get("stdout") or "").strip()
    if raw:
        try:
            payload = json.loads(raw)
        except Exception:
            payload = {}
        if isinstance(payload, dict):
            if payload.get("mode"):
                result["mode"] = str(payload.get("mode") or "").strip()
            if payload.get("detail"):
                result["detail"] = str(payload.get("detail") or "").strip()
    return result


def _desktop_try_window_message_image_paste(target_info: Dict[str, Any], mode_name: str) -> Dict[str, Any]:
    hwnd = int((target_info or {}).get("hwnd") or 0)
    if hwnd <= 0:
        return {"exit_code": 3, "stdout": "", "stderr": "window_message_paste_unavailable"}
    try:
        _win_send_message()(wintypes.HWND(hwnd), 0x0302, wintypes.WPARAM(0), wintypes.LPARAM(0))
        return {"exit_code": 0, "stdout": "", "stderr": "", "mode": mode_name}
    except Exception as exc:
        return {
            "exit_code": 3,
            "stdout": "",
            "stderr": f"window_message_paste_failed: {type(exc).__name__}: {exc}",
            "mode": mode_name,
        }


def _desktop_try_sendkeys_image_paste(target_info: Dict[str, Any], mode_name: str) -> Dict[str, Any]:
    pid = int((target_info or {}).get("pid") or 0)
    window_title = str((target_info or {}).get("window_title") or "").strip()
    if pid <= 0 and not window_title:
        return {"exit_code": 3, "stdout": "", "stderr": "window_sendkeys_paste_unavailable"}
    quoted_title = _ps_single_quote(window_title)
    quoted_mode = _ps_single_quote(mode_name)
    script = (
        "Add-Type -AssemblyName System.Windows.Forms; "
        "$wshell = New-Object -ComObject WScript.Shell; "
        f"$pid = {pid}; "
        f"$title = {quoted_title}; "
        f"$mode = {quoted_mode}; "
        "$ok = $false; "
        "if ($pid -gt 0) { "
        "try { $ok = [bool]$wshell.AppActivate($pid) } catch { $ok = $false } "
        "} "
        "if (-not $ok -and -not [string]::IsNullOrWhiteSpace($title)) { "
        "try { $ok = [bool]$wshell.AppActivate($title) } catch { $ok = $false } "
        "} "
        "if ($ok) { "
        "Start-Sleep -Milliseconds 180; "
        "try { [System.Windows.Forms.SendKeys]::SendWait('^v'); $ok = $true } catch { $ok = $false } "
        "} "
        "if ($ok) { "
        "@{ ok = $true; mode = $mode } | ConvertTo-Json -Compress; exit 0 "
        "} "
        "@{ ok = $false; detail = 'window_sendkeys_paste_failed' } | ConvertTo-Json -Compress; exit 3"
    )
    result = _run_powershell(script, timeout_s=8, sta=True)
    raw = str(result.get("stdout") or "").strip()
    if raw:
        try:
            payload = json.loads(raw)
        except Exception:
            payload = {}
        if isinstance(payload, dict):
            if payload.get("mode"):
                result["mode"] = str(payload.get("mode") or "").strip()
            if payload.get("detail"):
                result["detail"] = str(payload.get("detail") or "").strip()
    return result


def _desktop_paste_image_file(path_for_windows: str) -> Dict[str, Any]:
    target_info = _desktop_foreground_target_info()
    target_process = str(target_info.get("process_name") or "").strip().lower()
    target_family = str(target_info.get("target_family") or "").strip()
    result = _desktop_clipboard_set_image_file(path_for_windows, target_family=target_family)
    result["target_process"] = target_process
    result["target_family"] = target_family
    result["target_label"] = str(target_info.get("target_label") or "").strip()
    if result.get("exit_code") != 0:
        return result
    _desktop_restore_foreground_window(int(target_info.get("hwnd") or 0))
    _desktop_release_alt_if_held()
    time.sleep(0.18)
    if str(target_info.get("target_family") or "") == "paint":
        message_result = _desktop_try_window_message_image_paste(target_info, "paint_window_message_paste")
        message_result["target_process"] = target_process
        message_result["target_family"] = str(target_info.get("target_family") or "").strip()
        message_result["target_label"] = str(target_info.get("target_label") or "").strip()
        if message_result.get("exit_code") == 0:
            return message_result
    if str(target_info.get("target_family") or "") in {"powerpoint", "word"}:
        office_result = _desktop_try_office_image_paste(target_info)
        office_result["target_process"] = target_process
        office_result["target_family"] = str(target_info.get("target_family") or "").strip()
        office_result["target_label"] = str(target_info.get("target_label") or "").strip()
        if office_result.get("exit_code") == 0:
            return office_result
    if str(target_info.get("target_family") or "") in {"paint", "wps_presentation", "wps_document", "onenote"}:
        sendkeys_mode = {
            "paint": "paint_sendkeys_paste",
            "wps_presentation": "wps_sendkeys_paste",
            "wps_document": "wps_sendkeys_paste",
            "onenote": "onenote_sendkeys_paste",
        }.get(str(target_info.get("target_family") or ""), "window_sendkeys_paste")
        sendkeys_result = _desktop_try_sendkeys_image_paste(target_info, sendkeys_mode)
        sendkeys_result["target_process"] = target_process
        sendkeys_result["target_family"] = str(target_info.get("target_family") or "").strip()
        sendkeys_result["target_label"] = str(target_info.get("target_label") or "").strip()
        if sendkeys_result.get("exit_code") == 0:
            return sendkeys_result
        _desktop_restore_foreground_window(int(target_info.get("hwnd") or 0))
        time.sleep(0.12)
    try:
        _send_vk_combo([VK_CONTROL], 0x56)
        time.sleep(0.1)
        result["mode"] = "clipboard_native_paste"
        return result
    except HTTPException:
        sendkeys_result = _desktop_try_sendkeys_image_paste(target_info, "window_sendkeys_paste")
        sendkeys_result["target_process"] = target_process
        sendkeys_result["target_family"] = str(target_info.get("target_family") or "").strip()
        sendkeys_result["target_label"] = str(target_info.get("target_label") or "").strip()
        if sendkeys_result.get("exit_code") == 0:
            return sendkeys_result
        raise


def _desktop_pick_shareable_host_file() -> str:
    _ensure_windows_host()
    script = r"""
Add-Type -AssemblyName System.Windows.Forms
$dialog = New-Object System.Windows.Forms.OpenFileDialog
$dialog.Title = 'Choose a host file to send'
$dialog.CheckFileExists = $true
$dialog.Multiselect = $false
$dialog.RestoreDirectory = $true
$desktop = [Environment]::GetFolderPath('Desktop')
if (-not [string]::IsNullOrWhiteSpace($desktop) -and (Test-Path -LiteralPath $desktop)) {
  $dialog.InitialDirectory = $desktop
}
$picked = $dialog.ShowDialog()
if ($picked -ne [System.Windows.Forms.DialogResult]::OK -or [string]::IsNullOrWhiteSpace($dialog.FileName)) {
  @{ ok = $false; detail = 'cancelled' } | ConvertTo-Json -Compress
  exit 0
}
@{ ok = $true; path = [string]$dialog.FileName } | ConvertTo-Json -Compress
"""
    result = _run_powershell(script, timeout_s=60, sta=True)
    raw = str(result.get("stdout") or "").strip()
    try:
        payload = json.loads(raw) if raw else {}
    except Exception:
        detail = (result.get("stderr") or raw or "host_file_picker_failed").strip()
        raise HTTPException(status_code=500, detail=detail)
    if not payload.get("ok"):
        raise HTTPException(status_code=400, detail=str(payload.get("detail") or "cancelled"))
    picked_path = _normalize_host_path(str(payload.get("path") or ""))
    if not os.path.isfile(picked_path):
        raise HTTPException(status_code=404, detail="Selected host file no longer exists.")
    return picked_path

def _desktop_send_key(key: str) -> Dict[str, Any]:
    raw_key = (key or "").strip()
    k = raw_key.lower()
    if k == "alt+release":
        try:
            _send_vk_up(VK_MENU)
        except Exception:
            pass
        _set_desktop_alt_held(False)
        return {"exit_code": 0, "stdout": "", "stderr": "", "mode": "native_release", "key": k, "alt_held": False}

    if k != "alt+tab-hold":
        _desktop_release_alt_if_held()

    native_vk = {
        "enter": VK_RETURN,
        "esc": VK_ESCAPE,
        "tab": VK_TAB,
        "backspace": VK_BACK,
        "delete": VK_DELETE,
        "up": VK_UP,
        "down": VK_DOWN,
        "left": VK_LEFT,
        "right": VK_RIGHT,
        "home": VK_HOME,
        "end": VK_END,
        "pgup": VK_PRIOR,
        "pgdn": VK_NEXT,
        "f5": VK_F5,
        "space": VK_SPACE,
    }
    if k in native_vk:
        _send_vk(native_vk[k], extended=(k in {"delete", "up", "down", "left", "right", "home", "end", "pgup", "pgdn"}))
        return {"exit_code": 0, "stdout": "", "stderr": "", "mode": "native", "key": k}

    native_combos = {
        "ctrl+a": ([VK_CONTROL], 0x41),
        "ctrl+c": ([VK_CONTROL], 0x43),
        "ctrl+v": ([VK_CONTROL], 0x56),
        "ctrl+x": ([VK_CONTROL], 0x58),
        "ctrl+z": ([VK_CONTROL], 0x5A),
        "ctrl+shift+z": ([VK_CONTROL, VK_SHIFT], 0x5A),
        "ctrl+y": ([VK_CONTROL], 0x59),
        "ctrl+tab": ([VK_CONTROL], VK_TAB),
        "ctrl+shift+tab": ([VK_CONTROL, VK_SHIFT], VK_TAB),
        "shift+tab": ([VK_SHIFT], VK_TAB),
        "alt+tab": ([VK_MENU], VK_TAB),
        "alt+shift+tab": ([VK_MENU, VK_SHIFT], VK_TAB),
        "win": ([VK_LWIN], 0x20),
        "win+d": ([VK_LWIN], 0x44),
        "win+left": ([VK_LWIN], VK_LEFT),
        "win+right": ([VK_LWIN], VK_RIGHT),
        "win+tab": ([VK_LWIN], VK_TAB),
    }
    if k in native_combos:
        mods, vk = native_combos[k]
        _send_vk_combo(mods, vk, extended=(k in {"alt+tab", "alt+shift+tab", "win+left", "win+right", "win+tab"}))
        return {"exit_code": 0, "stdout": "", "stderr": "", "mode": "native_combo", "key": k, "alt_held": False}

    if len(raw_key) == 1 and 32 <= ord(raw_key) <= 126:
        if _send_char_key(raw_key):
            return {"exit_code": 0, "stdout": "", "stderr": "", "mode": "native_char", "key": raw_key, "alt_held": False}

    if k == "alt+tab-hold":
        if not _desktop_alt_held():
            _send_vk_down(VK_MENU)
            _set_desktop_alt_held(True)
        _send_vk(VK_TAB, extended=True)
        return {"exit_code": 0, "stdout": "", "stderr": "", "mode": "native_hold", "key": k, "alt_held": True}

    # Fallback to SendKeys for uncommon special-key specs.
    ps_key_map = {
        "printscreen": "{PRTSC}",
    }
    spec = ps_key_map.get(k)
    if not spec:
        raise HTTPException(
            status_code=400,
            detail=(
                "Unsupported key. Try: enter, esc, tab, shift+tab, arrows, "
                "alt+tab, alt+tab-hold, alt+release, win, win+left, win+right, win+tab, ctrl+c."
            ),
        )
    script = "Add-Type -AssemblyName System.Windows.Forms; " + f"[System.Windows.Forms.SendKeys]::SendWait('{spec}')"
    r = _run_powershell(script, timeout_s=8)
    r["mode"] = "powershell_sendkeys"
    r["key"] = k
    r["alt_held"] = _desktop_alt_held()
    return r


def _desktop_selected_paths() -> Dict[str, Any]:
    script = r"""
Add-Type @"
using System;
using System.Runtime.InteropServices;
using System.Text;
public static class CodrexWin32 {
  [DllImport("user32.dll")]
  public static extern IntPtr GetForegroundWindow();
  [DllImport("user32.dll")]
  public static extern IntPtr GetAncestor(IntPtr hWnd, uint gaFlags);
  [DllImport("user32.dll")]
  [return: MarshalAs(UnmanagedType.Bool)]
  public static extern bool IsWindowVisible(IntPtr hWnd);
  [DllImport("user32.dll")]
  [return: MarshalAs(UnmanagedType.Bool)]
  public static extern bool IsIconic(IntPtr hWnd);
  [DllImport("user32.dll", CharSet = CharSet.Unicode)]
  public static extern int GetClassName(IntPtr hWnd, StringBuilder lpClassName, int nMaxCount);
  [DllImport("user32.dll")]
  public static extern uint GetWindowThreadProcessId(IntPtr hWnd, out uint processId);
}
"@;
$ErrorActionPreference = 'Stop'
$shell = New-Object -ComObject Shell.Application
$GA_ROOT = [uint32]2
$foregroundHandle = [CodrexWin32]::GetForegroundWindow()
$foregroundRootHandle = [CodrexWin32]::GetAncestor($foregroundHandle, $GA_ROOT)
$foreground = [int64]$foregroundHandle
$foregroundRoot = [int64]$foregroundRootHandle
$windows = @()
foreach ($candidate in $shell.Windows()) {
  try {
    if ($candidate -and $candidate.Document) {
      $windows += $candidate
    }
  } catch {}
}

if ($windows.Count -eq 0) {
  $windows = @()
}

$focusedPid = [uint32]0
[void][CodrexWin32]::GetWindowThreadProcessId([intptr]$foregroundHandle, [ref]$focusedPid)
$focusedProcess = ''
try {
  if ([int]$focusedPid -gt 0) {
    $focusedProcess = (Get-Process -Id ([int]$focusedPid) -ErrorAction Stop).ProcessName
  }
} catch {}
$classNameBuilder = New-Object System.Text.StringBuilder 260
try {
  [void][CodrexWin32]::GetClassName([intptr]$foregroundHandle, $classNameBuilder, $classNameBuilder.Capacity)
} catch {}
$focusedClass = $classNameBuilder.ToString()

$diag = @{
  windows_count = $windows.Count
  focused_process = $focusedProcess
  focused_class = $focusedClass
  focused_hwnd = $foreground
  focused_root_hwnd = $foregroundRoot
}
$allowedDesktopClasses = @('Progman', 'WorkerW')
$focusedExplorer = ($focusedProcess -eq 'explorer')
$focusedDesktop = $allowedDesktopClasses -contains $focusedClass
$focusedShellSurface = $focusedExplorer -or $focusedDesktop
$diag.focused_shell_surface = $focusedShellSurface
$diag.foreground_visible = if ($foregroundHandle -ne [IntPtr]::Zero) { [CodrexWin32]::IsWindowVisible($foregroundHandle) } else { $false }
$diag.foreground_root_visible = if ($foregroundRootHandle -ne [IntPtr]::Zero) { [CodrexWin32]::IsWindowVisible($foregroundRootHandle) } else { $false }
$diag.foreground_root_minimized = if ($foregroundRootHandle -ne [IntPtr]::Zero) { [CodrexWin32]::IsIconic($foregroundRootHandle) } else { $false }

function Normalize-Paths($rawPaths) {
  $paths = @()
  foreach ($raw in @($rawPaths)) {
    try {
      $value = [string]$raw
      if (-not [string]::IsNullOrWhiteSpace($value)) {
        $paths += $value.Trim()
      }
    } catch {}
  }
  return @($paths | Select-Object -Unique)
}

function Get-WindowPaths($window) {
  $paths = @()
  try {
    foreach ($item in @($window.Document.SelectedItems())) {
      try {
        if ($item.Path) {
          $paths += [string]$item.Path
        }
      } catch {}
    }
  } catch {}
  $normalized = Normalize-Paths $paths
  if ($normalized.Count -gt 0) {
    return @{
      mode = 'selected_items'
      paths = $normalized
    }
  }
  try {
    $focused = $window.Document.FocusedItem()
    if ($focused -and $focused.Path) {
      return @{
        mode = 'focused_item'
        paths = Normalize-Paths @([string]$focused.Path)
      }
    }
  } catch {}
  return $null
}

$foregroundWindow = $null
foreach ($candidate in $windows) {
  try {
    $candidateHandle = [intptr]([int64]$candidate.HWND)
    if ([int64]$candidate.HWND -eq $foregroundRoot -and [CodrexWin32]::IsWindowVisible($candidateHandle) -and -not [CodrexWin32]::IsIconic($candidateHandle)) {
      $foregroundWindow = $candidate
      break
    }
  } catch {}
}
$diag.matched_foreground_window = [bool]$foregroundWindow

$result = $null
if ($foregroundWindow) {
  $result = Get-WindowPaths $foregroundWindow
}

if ((-not $result -or ($result.paths | Measure-Object).Count -eq 0) -and ($foregroundWindow -or ($focusedDesktop -and $diag.foreground_root_visible -and -not $diag.foreground_root_minimized))) {
  Add-Type -AssemblyName System.Windows.Forms
  try {
    [System.Windows.Forms.SendKeys]::SendWait('^c')
    Start-Sleep -Milliseconds 250
  } catch {}

  $clipboardPaths = @()
  try {
    foreach ($entry in [System.Windows.Forms.Clipboard]::GetFileDropList()) {
      if ($entry) {
        $clipboardPaths += [string]$entry
      }
    }
  } catch {}

  $normalizedClipboardPaths = Normalize-Paths $clipboardPaths
  if ($normalizedClipboardPaths.Count -gt 0) {
    $result = @{
      mode = 'clipboard_file_drop'
      paths = $normalizedClipboardPaths
    }
  } else {
    $clipboardTextPaths = @()
    try {
      $clipboardText = [System.Windows.Forms.Clipboard]::GetText()
      foreach ($line in @($clipboardText -split "`r?`n")) {
        $candidate = [string]$line
        if ([string]::IsNullOrWhiteSpace($candidate)) {
          continue
        }
        $candidate = $candidate.Trim().Trim('"')
        if (-not [string]::IsNullOrWhiteSpace($candidate) -and (Test-Path -LiteralPath $candidate)) {
          $clipboardTextPaths += $candidate
        }
      }
    } catch {}

    $normalizedClipboardTextPaths = Normalize-Paths $clipboardTextPaths
    if ($normalizedClipboardTextPaths.Count -gt 0) {
      $result = @{
        mode = 'clipboard_text'
        paths = $normalizedClipboardTextPaths
      }
    }
  }

  $diag.clipboard_file_drop_count = $normalizedClipboardPaths.Count
  $diag.clipboard_text_count = if ($normalizedClipboardTextPaths) { $normalizedClipboardTextPaths.Count } else { 0 }
}

if (-not $result -or ($result.paths | Measure-Object).Count -eq 0) {
  @{
    ok = $false
    detail = if (-not $focusedShellSurface) { 'focused_window_is_not_explorer_or_desktop' } elseif ($focusedExplorer -and -not $foregroundWindow) { 'focused_explorer_window_not_resolved' } elseif ($windows.Count -eq 0 -and -not $focusedDesktop) { 'file_explorer_not_focused' } else { 'no_selection' }
    diagnostics = $diag
  } | ConvertTo-Json -Compress -Depth 4
  exit 3
}

$resultPaths = Normalize-Paths @($result.paths)
$firstResultPath = $null
if ($resultPaths.Count -gt 0) {
  $firstResultPath = ($resultPaths | Select-Object -First 1)
}
@{
  ok = $true
  path = if ($firstResultPath) { [string]$firstResultPath } else { '' }
  paths = @($resultPaths)
  count = $resultPaths.Count
  mode = $result.mode
  diagnostics = $diag
} | ConvertTo-Json -Compress -Depth 4
"""
    result = _run_powershell(script, timeout_s=8, sta=True)
    raw = str(result.get("stdout") or "").strip()
    try:
        payload = json.loads(raw)
    except Exception:
        detail = (result.get("stderr") or result.get("stdout") or "selected_path_parse_failed").strip()
        raise HTTPException(status_code=500, detail=detail)
    if not payload.get("ok", False):
        detail = str(payload.get("detail") or result.get("stderr") or result.get("stdout") or "selected_path_failed").strip()
        diagnostics = payload.get("diagnostics")
        if isinstance(diagnostics, dict) and diagnostics:
            detail = f"{detail} | diagnostics={json.dumps(diagnostics, separators=(',', ':'))}"
        raise HTTPException(status_code=400, detail=detail)
    raw_paths = payload.get("paths") or []
    if isinstance(raw_paths, str):
        raw_paths = [raw_paths]
    paths = [str(p).strip() for p in raw_paths if str(p).strip()]
    if not paths:
        raise HTTPException(status_code=400, detail="no_selection")
    return {
        "ok": True,
        "path": paths[0],
        "paths": paths,
        "count": len(paths),
        "mode": str(payload.get("mode") or ""),
    }

# -------------------------
# Codex session helpers
# -------------------------
def _tmux_list_panes(session: Optional[str] = None) -> List[Dict[str, Any]]:
    if session:
        _validate_session_name(session)
        cmd = (
            "tmux list-panes -t " + session +
            " -F '#{session_name}\\t#{window_index}\\t#{pane_index}\\t#{pane_id}\\t#{pane_active}\\t#{pane_current_command}\\t#{pane_current_path}'"
        )
    else:
        cmd = (
            "tmux list-panes -a "
            "-F '#{session_name}\\t#{window_index}\\t#{pane_index}\\t#{pane_id}\\t#{pane_active}\\t#{pane_current_command}\\t#{pane_current_path}'"
        )
    r = run_wsl_bash(cmd)
    if r.get("exit_code") != 0:
        return []
    panes: List[Dict[str, Any]] = []
    for line in (r.get("stdout") or "").splitlines():
        parts = line.replace("\\t", "\t").split("\t")
        if len(parts) >= 7:
            panes.append({
                "session": parts[0],
                "window_index": parts[1],
                "pane_index": parts[2],
                "pane_id": parts[3],
                "active": parts[4] == "1",
                "current_command": parts[5],
                "current_path": parts[6],
            })
    return panes

def _infer_progress_state(text: str, current_command: str = "") -> str:
    t = (text or "").lower()
    cc = (current_command or "").lower()
    # Codex renders live progress lines like:
    #   "◦ Working (2s • esc to interrupt)"
    #   "Interpreting user request (12s • esc to interrupt)"
    if ("working (" in t) or ("esc to interrupt" in t):
        return "running"
    if any(x in t for x in ["approve", "approval", "press enter", "y/n", "continue?"]):
        return "waiting"

    # Avoid false "error" states from non-fatal MCP startup warnings that often contain
    # the word "failed".
    mcp_warning = ("mcp" in t) and any(x in t for x in ["mcp client", "mcp startup incomplete", "starting mcp servers"])

    # Only treat these as hard errors.
    if any(x in t for x in ["traceback", "exception", "panic", "segmentation fault"]):
        return "error"
    if not mcp_warning and any(x in t for x in ["error", "failed"]):
        return "error"
    if any(x in t for x in ["done", "completed", "all set", "finished"]):
        return "done"
    # Codex often runs under `node` in tmux; treat that as idle unless we saw explicit progress above.
    if cc == "node":
        return "idle"
    # If tmux reports the command as `codex`, it's reasonable to treat it as running.
    if cc == "codex":
        return "running"
    if cc and cc not in {"bash", "zsh", "sh", "fish"}:
        return "running"
    return "idle"

def _capture_snippet(pane_id: str, lines: int = 60) -> str:
    pane_id = _validate_pane_id(pane_id)
    r = run_wsl_bash(f"tmux capture-pane -t {pane_id} -p -J -S -{int(lines)}", timeout_s=15)
    if r.get("exit_code") != 0:
        return ""
    out = (r.get("stdout") or "").strip()
    if not out:
        return ""
    lines_arr = out.splitlines()
    return "\n".join(lines_arr[-12:])


def _session_cached_snippet(prev: Optional[Dict[str, Any]]) -> str:
    last_text = str((prev or {}).get("last_text") or "").strip()
    if last_text:
        return last_text.splitlines()[-1][:240]
    cached = str((prev or {}).get("snippet") or "").strip()
    if cached:
        return cached[:240]
    return ""


def _session_summary_state(prev: Optional[Dict[str, Any]], current_command: str) -> str:
    cached_text = str((prev or {}).get("last_text") or (prev or {}).get("snippet") or "")
    cached_state = str((prev or {}).get("state") or "").strip().lower()
    inferred = _infer_progress_state(cached_text, current_command)
    if cached_state in {"running", "waiting", "done", "error", "recovering", "starting", "idle"}:
        if cached_state == "starting" and inferred not in {"idle", "starting"}:
            return inferred
        return cached_state
    return inferred

def _capture_pane_full(pane_id: str, max_chars: int = 20000) -> str:
    pane_id = _validate_pane_id(pane_id)
    # Prefer alternate-screen, which is where TUIs (Codex) typically render.
    r = run_wsl_bash(f"tmux capture-pane -t {pane_id} -a -p -J", timeout_s=30)
    if r.get("exit_code") != 0 and ("no alternate screen" in (r.get("stderr") or "").lower()):
        r = run_wsl_bash(f"tmux capture-pane -t {pane_id} -p -J -S -20000", timeout_s=30)
    if r.get("exit_code") != 0:
        return ""
    txt = r.get("stdout") or ""
    if max_chars and len(txt) > max_chars:
        # Keep the tail, which is where the latest assistant output usually is.
        txt = txt[-max_chars:]
    return txt.strip("\n")

def _pane_is_codex_like(pane_id: str) -> bool:
    """
    Best-effort detection for panes that are running the Codex TUI.

    Why: Codex uses multi-line input where submission is "Enter on an empty line",
    which often needs an extra Enter (and a tiny delay). Regular shells generally
    want a single Enter.
    """
    try:
        panes = _tmux_list_panes()
    except Exception:
        panes = []
    for p in panes:
        if p.get("pane_id") != pane_id:
            continue
        sess = (p.get("session") or "").strip().lower()
        cc = (p.get("current_command") or "").strip().lower()
        if sess.startswith("codex"):
            return True
        if cc == "codex":
            return True
    return False

def _safe_name(name: str) -> str:
    x = re.sub(r"[^A-Za-z0-9._-]+", "_", (name or "").strip())
    return x.strip("._-") or "codex_session"


def _normalize_codex_model(raw: Any) -> str:
    model = str(raw or "").strip()
    if not model:
        return CODEX_DEFAULT_MODEL
    if not VALID_CODEX_MODEL_RE.fullmatch(model):
        raise HTTPException(status_code=400, detail="Invalid model format.")
    return model

def _is_codex_family_model(model: str) -> bool:
    normalized = (model or "").strip().lower()
    return "codex" in normalized

def _reasoning_efforts_for_model(model: str) -> List[str]:
    base = [item for item in CODEX_REASONING_EFFORT_OPTIONS]
    if _is_codex_family_model(model):
        preferred = ["low", "medium", "high"]
        filtered = [item for item in preferred if item in base]
        return filtered or preferred
    return base


def _default_reasoning_effort_for_model(model: str) -> str:
    allowed = _reasoning_efforts_for_model(model)
    if CODEX_DEFAULT_REASONING_EFFORT in allowed:
        return CODEX_DEFAULT_REASONING_EFFORT
    if "high" in allowed:
        return "high"
    return allowed[-1]


def _normalize_reasoning_effort(raw: Any, model: Optional[str] = None) -> str:
    selected_model = _normalize_codex_model(model) if model else CODEX_DEFAULT_MODEL
    allowed_for_model = _reasoning_efforts_for_model(selected_model)
    effort = str(raw or "").strip().lower()
    if not effort:
        return _default_reasoning_effort_for_model(selected_model)
    if effort not in CODEX_REASONING_EFFORT_OPTIONS:
        allowed = ", ".join(CODEX_REASONING_EFFORT_OPTIONS)
        raise HTTPException(status_code=400, detail=f"Invalid reasoning effort. Allowed: {allowed}")
    if effort in allowed_for_model:
        return effort
    if effort == "xhigh" and "high" in allowed_for_model:
        return "high"
    if effort == "minimal" and "low" in allowed_for_model:
        return "low"
    return allowed_for_model[-1]


def _build_codex_launch_command(model: str, reasoning_effort: str) -> str:
    # Apply model + reasoning at startup so session behavior is deterministic.
    return f"codex -c model={model} -c model_reasoning_effort={reasoning_effort}"

# -------------------------
# UI
# -------------------------
@app.get("/diag/status")
def diag_status(request: Request):
    token = _auth_token_from_request(request)
    return {
        "ok": True,
        "app": "Codrex Remote UI",
        "version": app.version,
        "started_at_unix": START_TIME,
        "uptime_s": int(max(0, time.time() - START_TIME)),
        "auth_required": CODEX_AUTH_REQUIRED,
        "authenticated": _is_valid_auth_token(token),
        "paths": {
            "root": "/",
            "diag_js": "/diag/js",
            "auth_status": "/auth/status",
        },
        "js_badge_expected": "JS: basic -> JS: ok",
    }

@app.get("/diag/js", response_class=HTMLResponse)
def diag_js():
    """
    Minimal JS sanity-check page for mobile devices.

    Why:
    - Some Android Chrome setups can have per-site JS blocked.
    - Users often don't have devtools, so we need a visible signal.
    """
    html = """
<!doctype html>
<html>
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>Codrex Remote UI - JS Diagnostic</title>
    <style>
      body { font-family: system-ui, -apple-system, Segoe UI, Roboto, sans-serif; padding: 16px; }
      .box { border: 1px solid #ddd; border-radius: 10px; padding: 12px 14px; margin: 12px 0; background: #fff; }
      .muted { color: #555; font-size: 13px; }
      code, pre { font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; }
      pre { white-space: pre-wrap; word-break: break-word; }
    </style>
    <noscript>
      <div class="box" style="background:#fee2e2;border-color:#fecaca;color:#7f1d1d;">
        <strong>JavaScript is disabled</strong> (or blocked for this site). Enable it in Chrome to use Auto/controls.
      </div>
    </noscript>
  </head>
  <body>
    <h2>JS Diagnostic</h2>
    <div class="box">
      <div id="badge"><strong>JS:</strong> loading...</div>
      <div class="muted">If this never changes to <code>ok</code>, JS is blocked for this site.</div>
    </div>
    <div class="box">
      <div class="muted">User-Agent:</div>
      <pre id="ua">(not available)</pre>
    </div>
    <div class="box">
      <div class="muted">Next steps (Chrome Android):</div>
      <ol>
        <li>Open the site in Chrome.</li>
        <li>Tap the lock/tune icon → Site settings.</li>
        <li>Set JavaScript to <code>Allowed</code>.</li>
        <li>Reload.</li>
      </ol>
    </div>
    <p><a href="/">Back to controller</a></p>
    <script>
      (function () {
        try {
          var el = document.getElementById('badge');
          if (el) el.textContent = 'JS: ok';
        } catch (e) {}
        try {
          var ua = document.getElementById('ua');
          if (ua) ua.textContent = (navigator && navigator.userAgent) ? navigator.userAgent : '(unknown)';
        } catch (e) {}
      })();
    </script>
  </body>
</html>
    """.strip()
    return HTMLResponse(content=html, headers={"Cache-Control": "no-store"})

@app.get("/", response_class=HTMLResponse)
def app_entry():
    if not _built_ui_present():
        return _built_ui_missing_response()
    return FileResponse(_built_ui_index_path(), headers={"Cache-Control": "no-store"})


@app.get("/legacy", response_class=HTMLResponse)
@app.get("/legacy/", response_class=HTMLResponse)
def legacy_index(request: Request):
    root = CODEX_FILE_ROOT
    workdir = CODEX_WORKDIR
    distro = WSL_DISTRO
    desktop_enabled = _desktop_enabled_from_request(request)
    authenticated = _is_valid_auth_token(_auth_token_from_request(request))
    desktop_native_w = 1366
    desktop_native_h = 768
    if os.name == "nt":
        try:
            mon = _desktop_monitor()
            w = int(mon.get("width") or 0)
            h = int(mon.get("height") or 0)
            if w > 0:
                desktop_native_w = w
            if h > 0:
                desktop_native_h = h
        except Exception:
            pass
    desktop_tap_w = max(220, min(420, int(desktop_native_w)))
    # Keep aspect ratio and avoid very short tap maps.
    desktop_tap_h = max(140, int(round((desktop_native_h * desktop_tap_w) / max(1, desktop_native_w))))
    desktop_stream_fps = max(0.5, min(float(DESKTOP_STREAM_FPS_DEFAULT), 8.0))
    desktop_stream_level = _clamp(int(DESKTOP_STREAM_PNG_LEVEL_DEFAULT), 0, 9)
    desktop_stream_url = f"/desktop/stream?fps={desktop_stream_fps:g}&level={desktop_stream_level}"
    desktop_live_badge = f"Live stream: {desktop_stream_fps:g} fps"
    desktop_mode_class = "desktop-on" if desktop_enabled else "desktop-off"
    desktop_stream_active = desktop_enabled and (not CODEX_AUTH_REQUIRED or authenticated)
    desktop_stream_src = desktop_stream_url if desktop_stream_active else BLANK_IMAGE_DATA_URL
    desktop_mode_badge_class = "badge running" if desktop_enabled else "badge warn"
    if desktop_stream_active:
        desktop_mode_badge = desktop_live_badge
    elif desktop_enabled and CODEX_AUTH_REQUIRED and not authenticated:
        desktop_mode_badge = "Login required for desktop stream"
    else:
        desktop_mode_badge = "Desktop stream paused"
    desktop_toggle_label = "Off" if desktop_enabled else "On"
    compact_mode = _compact_enabled_from_request(request)
    compact_mode_class = "compact-mode" if compact_mode else "full-mode"
    compact_toggle_href = "/" if compact_mode else "/mobile"
    compact_toggle_label = "Open Full" if compact_mode else "Open Compact"
    compact_pill = "Compact layout" if compact_mode else "Full layout"
    html = """
<!doctype html>
<html>
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Codrex Master Controller</title>
  <noscript>
    <style>
      .nojs-banner {
        margin: 0;
        padding: 12px 14px;
        background: #fee2e2;
        border-bottom: 1px solid #fecaca;
        color: #7f1d1d;
        font-family: system-ui, -apple-system, Segoe UI, Roboto, sans-serif;
        font-size: 13px;
      }
      .nojs-banner code { font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; }
    </style>
    <div class="nojs-banner">
      JavaScript is disabled or blocked. Turn it on to use this controller UI.
      If JS stays at <code>JS: basic</code>, use <code>Fallback Controls (No-JS)</code> and <code>Fallback Login (No-JS)</code> below.
    </div>
  </noscript>
  <style>
    :root {
      --bg: radial-gradient(1200px 680px at 0% -10%, #e3edf8 0%, #f2f6fb 42%, #eef2f6 100%);
      --panel: #ffffff;
      --text: #111827;
      --muted: #5b6473;
      --border: #d7dfeb;
      --accent: #115e59;
      --accent-strong: #0f766e;
      --accent-soft: #d7f1ee;
      --surface-soft: #f6f9fc;
      --ok: #166534;
      --warn: #9a3412;
      --off: #92400e;
      --radius-sm: 10px;
      --radius-md: 14px;
      --radius-lg: 18px;
      --shadow-sm: 0 8px 24px rgba(15, 23, 42, 0.08);
      --shadow-md: 0 18px 36px rgba(15, 23, 42, 0.12);
      --shadow-focus: 0 0 0 3px rgba(29, 78, 216, 0.18);
      --space-1: 4px;
      --space-2: 8px;
      --space-3: 12px;
      --space-4: 16px;
      --space-5: 24px;
      --space-6: 32px;
    }
    html { scroll-behavior: smooth; }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      background: var(--bg);
      color: var(--text);
      font-family: "Space Grotesk", "IBM Plex Sans", "Segoe UI", sans-serif;
      min-height: 100vh;
      line-height: 1.35;
    }
    a { color: inherit; }
    h1 { font-size: 28px; margin: 0 0 var(--space-2); letter-spacing: -0.02em; }
    h2 { font-size: 18px; margin: 0; }
    p { margin: 0; }
    .page { max-width: none; width: 100%; margin: 0 auto; padding: var(--space-6) var(--space-5); }
    .top {
      position: sticky;
      top: 0;
      z-index: 25;
      background: linear-gradient(180deg, rgba(244, 249, 255, 0.96), rgba(244, 249, 255, 0.86));
      backdrop-filter: blur(8px);
      border: 1px solid rgba(223, 228, 234, 0.9);
      border-radius: var(--radius-md);
      padding: var(--space-3);
      box-shadow: var(--shadow-sm);
    }
    .quick-nav {
      position: sticky;
      top: 92px;
      z-index: 24;
      display: flex;
      gap: var(--space-2);
      overflow-x: auto;
      padding: 6px;
      border-radius: 999px;
      border: 1px solid #d9e4f1;
      background: rgba(255, 255, 255, 0.84);
      backdrop-filter: blur(10px);
      scrollbar-width: thin;
    }
    .quick-chip {
      display: inline-flex;
      align-items: center;
      justify-content: center;
      white-space: nowrap;
      padding: 8px 12px;
      border-radius: 999px;
      border: 1px solid #cfdae8;
      background: #ffffff;
      color: #1f2937;
      font-size: 13px;
      font-weight: 600;
      text-decoration: none;
      transition: background 140ms ease, transform 140ms ease, border-color 140ms ease;
    }
    .quick-chip:hover {
      background: #f3f8ff;
      border-color: #9ec5ed;
      transform: translateY(-1px);
    }
    .quick-chip:focus-visible {
      outline: none;
      box-shadow: var(--shadow-focus);
    }
    .stack { display: flex; flex-direction: column; gap: var(--space-3); }
    .row { display: flex; gap: var(--space-2); flex-wrap: wrap; align-items: center; }
    .row.tight { gap: var(--space-1); }
    .pair-actions {
      display: grid;
      grid-template-columns: 1fr auto auto auto;
      align-items: end;
    }
    .pair-actions .field {
      min-width: 0;
    }
    .grid { display: grid; grid-template-columns: 1fr; gap: var(--space-4); }
    .span-2 { grid-column: span 1; }
    .card {
      background: var(--panel);
      border: 1px solid rgba(223, 228, 234, 0.92);
      border-radius: var(--radius-md);
      padding: var(--space-4);
      box-shadow: var(--shadow-sm);
      backdrop-filter: blur(2px);
      transition: box-shadow 180ms ease, transform 180ms ease, border-color 180ms ease;
      animation: card-rise 260ms ease both;
      transform-origin: center top;
    }
    .card:hover {
      box-shadow: var(--shadow-md);
      border-color: #c9d9ea;
      transform: translateY(-1px);
    }
    .card.pair-tone { border-top: 4px solid #0f766e; }
    .card.codex-tone { border-top: 4px solid #1d4ed8; }
    .card.tmux-tone { border-top: 4px solid #334155; }
    .card.desktop-tone { border-top: 4px solid #166534; }
    .card.exec-tone { border-top: 4px solid #0e7490; }
    .card.files-tone { border-top: 4px solid #0f766e; }
    .card.shot-tone { border-top: 4px solid #9a3412; }
    .grid > .card:nth-child(2) { animation-delay: 30ms; }
    .grid > .card:nth-child(3) { animation-delay: 60ms; }
    .grid > .card:nth-child(4) { animation-delay: 90ms; }
    .grid > .card:nth-child(5) { animation-delay: 120ms; }
    .grid > .card:nth-child(6) { animation-delay: 150ms; }
    .grid > .card:nth-child(7) { animation-delay: 180ms; }
    @keyframes card-rise {
      from { opacity: 0; transform: translateY(8px); }
      to { opacity: 1; transform: translateY(0); }
    }
    .card-head { display: flex; justify-content: space-between; align-items: center; gap: var(--space-3); }
    .pill {
      padding: 4px 10px;
      border-radius: 999px;
      font-size: 12px;
      background: #eef1f6;
      border: 1px solid var(--border);
      color: #2d3748;
    }
    .pill.brand { background: var(--accent-soft); color: #0f4b47; border-color: #9ad6d1; }
    .muted { color: var(--muted); }
    .small { font-size: 12px; color: var(--muted); }
    .label { font-size: 11px; color: var(--muted); text-transform: uppercase; letter-spacing: 0.04em; }
    .field { display: flex; flex-direction: column; gap: 6px; min-width: 180px; }
    .field.grow { flex: 1 1 280px; }
    .legacy-form { display: flex; flex-wrap: wrap; gap: var(--space-2); align-items: flex-end; }
    .legacy-form .field { flex: 1 1 220px; }
    input, select, textarea {
      width: 100%;
      border: 1px solid var(--border);
      background: #fff;
      padding: 10px 12px;
      border-radius: var(--radius-sm);
      font: inherit;
      color: var(--text);
    }
    input[type="file"] { padding: 7px 10px; background: #fff; }
    textarea { min-height: 90px; resize: vertical; }
    button {
      border-radius: var(--radius-sm);
      border: 1px solid var(--border);
      background: #fff;
      color: var(--text);
      padding: 10px 14px;
      font: inherit;
      font-weight: 600;
      cursor: pointer;
      transition: background 140ms ease, border-color 140ms ease, transform 140ms ease, box-shadow 140ms ease;
    }
    button.primary { background: var(--accent); border-color: var(--accent); color: #fff; }
    button.ghost { background: transparent; }
    button.toggle-btn { min-width: 136px; }
    button.state-on {
      background: var(--ok);
      border-color: var(--ok);
      color: #fff;
    }
    button.state-off {
      background: #fff7ed;
      border-color: #fdba74;
      color: var(--off);
    }
    button.soft {
      background: var(--surface-soft);
      border-color: #cad6e5;
    }
    button.danger { background: #b91c1c; border-color: #b91c1c; color: #fff; }
    button:disabled { opacity: 0.6; cursor: not-allowed; }
    button:hover:not(:disabled) {
      transform: translateY(-1px);
      box-shadow: 0 8px 16px rgba(15, 23, 42, 0.1);
    }
    input:focus-visible, select:focus-visible, textarea:focus-visible, button:focus-visible {
      outline: none;
      box-shadow: var(--shadow-focus);
      border-color: #3b82f6;
    }
    a.ghost {
      display: inline-flex;
      align-items: center;
      justify-content: center;
      border-radius: var(--radius-sm);
      border: 1px solid var(--border);
      background: transparent;
      color: var(--text);
      padding: 10px 14px;
      font: inherit;
      font-weight: 600;
      cursor: pointer;
      transition: background 140ms ease, border-color 140ms ease, transform 140ms ease, box-shadow 140ms ease;
      text-decoration: none;
    }
    a.ghost:hover {
      transform: translateY(-1px);
      background: #f6f9fc;
      border-color: #c5d4e6;
      box-shadow: 0 8px 16px rgba(15, 23, 42, 0.08);
    }
    a.ghost:focus-visible {
      outline: none;
      box-shadow: var(--shadow-focus);
    }
    .console {
      white-space: pre-wrap;
      background: #0b0d12;
      color: #e5e7eb;
      padding: var(--space-3);
      border-radius: var(--radius-sm);
      min-height: 220px;
      max-height: 520px;
      overflow: auto;
      border: 1px solid #1f2937;
      font-family: "JetBrains Mono", "SFMono-Regular", Menlo, Consolas, monospace;
    }
    #out, #execOut, #codexSessionOut { min-height: 180px; }
    #shotImg { width: 100%; border-radius: var(--radius-md); border: 1px solid var(--border); display: none; }
	    #deskImg {
	      width: 100%;
	      border-radius: var(--radius-sm);
	      border: 1px solid var(--border);
	      touch-action: none;
	      background: #111827;
	      min-height: 240px;
	    }
      .desktop-js-pane { display: none; }
      .desktop-fallback-pane { display: block; }
      html.js-ok-mode .desktop-js-pane { display: block; }
      html.js-ok-mode .desktop-fallback-pane { display: none; }
      .desktop-on .desktop-off-only { display: none; }
      .desktop-off .desktop-live-only { display: none; }
    .desktop-mode-btn-active {
      background: #14532d;
      border-color: #14532d;
      color: #ffffff;
    }
    .desktop-quick-grid {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(120px, 1fr));
      gap: var(--space-2);
    }
    .desktop-quick-grid button {
      min-height: 44px;
      border-radius: 12px;
    }
    #desktopJsControls button:nth-child(1),
    #desktopJsControls button:nth-child(2),
    #desktopJsControls button:nth-child(3) {
      background: #f8fafc;
    }
    #desktopJsControls button:nth-child(4),
    #desktopJsControls button:nth-child(5) {
      background: #f3f6fb;
    }
	    .legacy-stream-wrap {
	      overflow: auto;
	      border: 1px solid var(--border);
	      border-radius: var(--radius-sm);
	      background: #0b0d12;
	      max-height: 58vh;
	    }
	    .legacy-stream-tap {
	      display: block;
	      width: __DESKTOP_TAP_W__px;
	      height: __DESKTOP_TAP_H__px;
	      max-width: none;
	      border: 0;
	      cursor: crosshair;
	    }
	    #pairQrImg {
	      width: 220px;
	      max-width: 60vw;
	      background: #ffffff;
	      border-radius: var(--radius-sm);
	      border: 1px solid var(--border);
	      padding: var(--space-2);
	      display: none;
	    }
	    #pairLink {
	      min-height: 0;
	      padding: 10px 12px;
	      background: #0b0d12;
	      color: #e5e7eb;
	      border: 1px solid #1f2937;
	      border-radius: var(--radius-sm);
	      word-break: break-all;
	    }
	    .mono { font-family: "JetBrains Mono", "SFMono-Regular", Menlo, Consolas, monospace; }
	    .badge { padding: 6px 10px; border-radius: 999px; font-size: 12px; border: 1px solid var(--border); background: #f6f6f6; }
	    .badge.ok { background: #e7f7ed; border-color: #b9e5c7; color: #166534; }
	    .badge.warn { background: #fff7ed; border-color: #fed7aa; color: #9a3412; }
	    .badge.err { background: #fee2e2; border-color: #fecaca; color: #b91c1c; }
    .badge.running { background: #e0f2fe; border-color: #bae6fd; color: #075985; }
    .badge.route-ts { background: #dcfce7; border-color: #86efac; color: #166534; }
    .badge.route-lan { background: #e0f2fe; border-color: #93c5fd; color: #1d4ed8; }
    .badge.route-local { background: #fef9c3; border-color: #fde047; color: #92400e; }
    .badge.route-unknown { background: #f3f4f6; border-color: #d1d5db; color: #374151; }
    .pair-diag {
      border: 1px solid var(--border);
      border-radius: var(--radius-sm);
      background: var(--surface-soft);
      padding: 10px 12px;
      display: flex;
      flex-direction: column;
      gap: 8px;
    }
    .pair-net-grid {
      display: grid;
      gap: 8px;
      grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));
    }
    .pair-net-item {
      display: flex;
      flex-direction: column;
      gap: 4px;
      padding: 8px;
      border-radius: 10px;
      border: 1px solid #d6deea;
      background: #fff;
    }
    .pair-net-item .mono {
      font-size: 13px;
      min-height: 16px;
    }
    .pair-safety-ok { color: var(--ok); }
    .pair-safety-warn { color: var(--warn); }
    .panel-title {
      display: flex;
      justify-content: space-between;
      align-items: baseline;
      gap: var(--space-3);
    }
    .auth-gate {
      position: fixed;
      inset: 0;
      background: rgba(15, 23, 42, 0.66);
      display: flex;
      align-items: center;
      justify-content: center;
      padding: var(--space-5);
      z-index: 2000;
    }
    .auth-card {
      width: min(460px, 100%);
      background: #ffffff;
      border: 1px solid var(--border);
      border-radius: var(--radius-md);
      box-shadow: 0 20px 35px rgba(0, 0, 0, 0.2);
      padding: var(--space-5);
      display: flex;
      flex-direction: column;
      gap: var(--space-3);
    }
    .hidden { display: none !important; }
    body.compact-mode .page {
      max-width: 980px;
      padding: var(--space-4);
    }
    body.compact-mode .top {
      position: static;
    }
    body.compact-mode .quick-nav {
      top: 8px;
    }
    body.compact-mode .grid {
      grid-template-columns: 1fr;
      gap: var(--space-3);
    }
    body.compact-mode .span-2 {
      grid-column: span 1;
    }
    body.compact-mode .legacy-form,
    body.compact-mode [data-testid="legacy-auth-controls"],
    body.compact-mode [data-testid="legacy-codex-controls"],
    body.compact-mode [data-testid="legacy-desktop-controls"],
    body.compact-mode .desktop-fallback-pane {
      display: none !important;
    }
    body.compact-mode .compact-hide {
      display: none !important;
    }
    body.compact-mode .pair-actions {
      grid-template-columns: 1fr 1fr;
    }
    body.compact-mode .pair-actions .field.grow {
      grid-column: 1 / -1;
    }
    body.compact-mode .pair-actions button {
      width: 100%;
    }
    body.compact-mode .console {
      max-height: 320px;
      min-height: 160px;
    }
    @media (max-width: 960px) {
      .span-2 { grid-column: span 1; }
      .page { padding: var(--space-5) var(--space-4); }
      .card { padding: var(--space-3); }
      button, a.ghost { min-height: 44px; }
      .top { position: static; }
      .quick-nav { top: 8px; }
    }
    @media (max-width: 640px) {
      h1 { font-size: 22px; }
      h2 { font-size: 16px; }
      .grid { grid-template-columns: 1fr; gap: var(--space-3); }
      .row { gap: 6px; }
      .quick-chip { font-size: 12px; padding: 7px 11px; }
      .pair-actions {
        grid-template-columns: 1fr 1fr;
      }
      .pair-actions .field.grow {
        grid-column: 1 / -1;
      }
      .pair-actions button {
        width: 100%;
      }
      .pill { font-size: 11px; }
      .field { min-width: 140px; }
      .desktop-quick-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
      .desktop-quick-grid button { padding: 10px; font-size: 14px; }
      #deskImg { min-height: 190px; }
    }
  </style>
</head>
<body class="__DESKTOP_MODE_CLASS__ __COMPACT_MODE_CLASS__">
  <div id="authGate" class="auth-gate hidden">
    <div class="auth-card" role="dialog" aria-labelledby="authTitle" aria-modal="true">
      <h2 id="authTitle">Login Required</h2>
      <p class="small">Enter `CODEX_AUTH_TOKEN` to unlock controller access.</p>
      <label class="field">
        <span class="label">Access token</span>
        <input id="authTokenInput" type="password" autocomplete="current-password" data-testid="auth-token-input" />
      </label>
      <div class="row">
        <button id="authLoginBtn" class="primary" onclick="loginAuth()" data-testid="auth-login-btn">Unlock</button>
        <span id="authMsg" class="small"></span>
      </div>
    </div>
  </div>

  <div class="page stack">
    <header class="top stack">
      <div class="row" style="justify-content: space-between; align-items: flex-end;">
        <div class="stack">
          <span class="pill brand">Codrex Master Controller</span>
          <h1>Mobile Control For Codrex + Desktop</h1>
          <p class="muted">Two control panes: Codrex orchestration and desktop remote actions.</p>
        </div>
        <div class="row tight">
          <span id="jsBadge" class="badge">JS: loading…</span>
          <a class="ghost" href="/diag/js" target="_blank" rel="noopener" style="text-decoration:none;">JS diag</a>
          <a class="ghost" href="__COMPACT_TOGGLE_HREF__" data-testid="layout-toggle" style="text-decoration:none;">__COMPACT_TOGGLE_LABEL__</a>
          <span class="pill">layout: <span class="mono">__COMPACT_PILL__</span></span>
          <span class="pill compact-hide">WSL: <span class="mono">__CODEX_DISTRO__</span></span>
          <span class="pill compact-hide">workdir: <span class="mono">__CODEX_WORKDIR__</span></span>
          <span class="pill compact-hide">file root: <span class="mono">__CODEX_ROOT__</span></span>
          <button class="ghost" onclick="logoutAuth()">Logout</button>
        </div>
      </div>
    </header>

    <nav class="quick-nav" aria-label="Section shortcuts" data-testid="quick-nav">
      <a class="quick-chip" href="#pairSection">Pair</a>
      <a class="quick-chip" href="#codexSection">Codrex</a>
      <a class="quick-chip" href="#tmuxSection">Tmux</a>
      <a class="quick-chip" href="#desktopSection">Desktop</a>
      <a class="quick-chip" href="#execSection">Exec</a>
      <a class="quick-chip" href="#filesSection">Files</a>
      <a class="quick-chip" href="#shotSection">Capture</a>
    </nav>

	    <div class="grid">
	      <section id="pairSection" class="card span-2 stack pair-tone" data-testid="pair-card">
	        <div class="card-head">
	          <div class="stack">
	            <h2>Pair Phone (QR)</h2>
	            <p class="small">Generate a short-lived QR code to log your phone in without typing the token.</p>
	          </div>
	          <span class="badge">TTL: <span class="mono">~90s</span></span>
	        </div>

	        <div class="row pair-actions">
	          <label class="field grow">
	            <span class="label">Base URL (must be reachable from phone)</span>
	            <input id="pairBaseUrl" placeholder="http://100.x.x.x:&lt;codrex-port&gt;" data-testid="pair-base-url" />
	          </label>
	          <button class="ghost soft" onclick="useTailscaleBase()" data-testid="pair-use-tailscale">Use Tailscale</button>
	          <button class="ghost soft" onclick="useLanBase()" data-testid="pair-use-lan">Use LAN</button>
	          <button class="primary" onclick="generatePairQr()" data-testid="pair-generate">Generate QR</button>
	        </div>

          <div class="pair-diag" data-testid="pair-diag">
            <div class="row tight">
              <span class="label">Current route</span>
              <span id="pairRouteBadge" class="badge route-unknown" data-testid="pair-route-badge">Unknown</span>
              <span id="pairSafetyStatus" class="small"></span>
            </div>
            <div class="pair-net-grid">
              <div class="pair-net-item">
                <span class="label">LAN address</span>
                <span id="pairLanIp" class="mono">--</span>
              </div>
              <div class="pair-net-item">
                <span class="label">Tailscale address</span>
                <span id="pairTailscaleIp" class="mono">--</span>
              </div>
            </div>
            <div class="row">
              <button id="pairTailscaleOnlyBtn" class="toggle-btn state-off" onclick="toggleTailscaleOnly()" data-testid="pair-ts-only-btn">Tailscale-only: Off</button>
              <span class="small muted">When ON, QR generation is blocked unless the base URL is Tailscale.</span>
            </div>
          </div>

	        <div class="row" style="align-items: flex-start;">
	          <img id="pairQrImg" alt="Pairing QR code" />
	          <div class="stack grow">
	            <div class="small muted">Scan with your phone camera. Expires in <span id="pairExpires">--</span>s.</div>
	            <div id="pairLink" class="mono small" data-testid="pair-link">No pairing link generated yet.</div>
	            <div id="pairStatus" class="small" data-testid="pair-status"></div>
	          </div>
	        </div>
	      </section>

      <section class="card span-2 stack" data-testid="legacy-auth-controls">
        <div class="card-head">
          <div class="stack">
            <h2>Fallback Login (No-JS)</h2>
            <p class="small">Use this when JS stays at <span class="mono">JS: basic</span> and the Unlock button does not respond.</p>
          </div>
        </div>
        <form class="legacy-form" method="post" action="/legacy/auth/login">
          <label class="field grow">
            <span class="label">Access token</span>
            <input name="token" type="password" autocomplete="current-password" placeholder="Enter CODEX_AUTH_TOKEN" />
          </label>
          <input type="hidden" name="next" value="/legacy" />
          <button class="primary" type="submit">Login (No-JS)</button>
        </form>
        <form class="legacy-form" method="post" action="/legacy/auth/logout">
          <input type="hidden" name="next" value="/legacy" />
          <button class="ghost" type="submit">Logout (No-JS)</button>
          <a class="ghost" href="/auth/status" target="_blank" rel="noopener">Auth status JSON</a>
        </form>
      </section>

	      <section id="codexSection" class="card span-2 stack codex-tone">
	        <div class="panel-title">
	          <h2>Codrex Sessions (Master Pane)</h2>
	          <span id="codexSessionBadge" class="badge">loading…</span>
	        </div>
        <p class="small">Create multiple sessions, watch progress, send prompts, and attach images.</p>

        <div class="row">
          <label class="field">
            <span class="label">Session Name</span>
            <input id="codexSessionName" placeholder="e.g. feature_api_docs" data-testid="codex-session-name" />
          </label>
          <label class="field grow">
            <span class="label">Session CWD (optional)</span>
            <input id="codexSessionCwd" placeholder="Defaults to __CODEX_WORKDIR__" data-testid="codex-session-cwd" />
          </label>
          <button class="primary" onclick="createCodexSession()" data-testid="codex-session-create">Create Codex Session</button>
          <button onclick="refreshCodexSessions()">Refresh</button>
        </div>

        <div class="row">
          <label class="field grow">
            <span class="label">Active Session</span>
            <select id="codexSessionSelect" data-testid="codex-session-select"></select>
          </label>
          <button class="danger" onclick="closeCodexSession()">Close Session</button>
          <button class="ghost" onclick="loadCodexSessionScreen()">View Output</button>
          <button id="codexStreamBtn" class="toggle-btn state-on" onclick="toggleCodexStream()" data-testid="codex-stream-btn">Stream: On</button>
          <label class="field" style="min-width: 160px;">
            <span class="label">Live rate</span>
            <select id="codexStreamRate" data-testid="codex-stream-rate">
              <option value="300">Very fast</option>
              <option value="600">Fast</option>
              <option value="900" selected>Normal</option>
              <option value="1500">Slow</option>
              <option value="2500">Very slow</option>
            </select>
          </label>
          <span id="codexStreamStatus" class="small"></span>
          <span id="codexSessionState" class="small"></span>
        </div>

	        <div class="row">
	          <label class="field grow">
	            <span class="label">Prompt</span>
	            <input id="codexSessionPrompt" placeholder="Send command or prompt to selected session..." data-testid="codex-session-prompt" />
	          </label>
	          <button class="primary" onclick="sendCodexSessionPrompt()">Send</button>
	          <button onclick="sendCtrlCToSession()">Interrupt (Esc)</button>
	        </div>

        <div class="row">
          <input id="codexSessionImage" type="file" accept="image/*" data-testid="codex-session-image" />
          <label class="field grow">
            <span class="label">Image Message</span>
            <input id="codexSessionImagePrompt" placeholder="Optional instruction for this image..." data-testid="codex-session-image-prompt" />
          </label>
          <button onclick="uploadCodexSessionImage()">Send Image</button>
        </div>

        <div id="codexSessionOut" class="console" data-testid="codex-session-out">Select a session to inspect output.</div>
      </section>

      <section class="card span-2 stack" data-testid="legacy-codex-controls">
        <div class="card-head">
          <div class="stack">
            <h2>Fallback Controls (No-JS)</h2>
            <p class="small">If JS badge is not <span class="mono">JS: ok</span>, use these forms to control Codrex sessions.</p>
          </div>
        </div>

        <form class="legacy-form" method="post" action="/legacy/codex/create">
          <label class="field">
            <span class="label">Create Session Name</span>
            <input name="name" placeholder="e.g. codex_mobile" />
          </label>
          <label class="field grow">
            <span class="label">Create CWD (optional)</span>
            <input name="cwd" placeholder="Defaults to __CODEX_WORKDIR__" />
          </label>
          <button class="primary" type="submit">Create</button>
        </form>

        <form class="legacy-form" method="post" action="/legacy/codex/send">
          <label class="field">
            <span class="label">Send Session</span>
            <input name="session" placeholder="codex_xxxxxxxx" required />
          </label>
          <label class="field grow">
            <span class="label">Prompt</span>
            <input name="text" placeholder="Type prompt to send..." required />
          </label>
          <button class="primary" type="submit">Send Prompt</button>
        </form>

        <div class="row">
          <form class="legacy-form" method="post" action="/legacy/codex/interrupt">
            <label class="field">
              <span class="label">Interrupt Session</span>
              <input name="session" placeholder="codex_xxxxxxxx" required />
            </label>
            <button class="ghost" type="submit">Interrupt (Esc)</button>
          </form>

          <form class="legacy-form" method="post" action="/legacy/codex/close">
            <label class="field">
              <span class="label">Close Session</span>
              <input name="session" placeholder="codex_xxxxxxxx" required />
            </label>
            <button class="danger" type="submit">Close</button>
          </form>
        </div>

        <form class="legacy-form" method="get" action="/legacy/codex/screen">
          <label class="field">
            <span class="label">View Session Screen</span>
            <input name="session" placeholder="codex_xxxxxxxx" required />
          </label>
          <button type="submit">Open Screen</button>
          <a class="ghost" href="/codex/sessions" target="_blank" rel="noopener">Sessions JSON</a>
        </form>
      </section>

      <section id="tmuxSection" class="card span-2 stack tmux-tone">
        <div class="card-head">
          <div class="stack">
            <h2>Tmux sessions</h2>
            <p class="small">Create, view, and control tmux panes inside WSL.</p>
          </div>
          <span id="tmuxBadge" class="badge">tmux: checking…</span>
        </div>

        <div class="row">
          <button onclick="refreshPanes()">Refresh panes</button>
          <button class="ghost" onclick="debugTmux()">Debug tmux</button>
          <button id="tmuxStreamBtn" class="toggle-btn state-on" onclick="toggleTmuxStream()" data-testid="tmux-stream-btn">Stream: On</button>
          <label class="field" style="min-width: 160px;">
            <span class="label">Live rate</span>
            <select id="tmuxStreamRate" data-testid="tmux-stream-rate">
              <option value="300">Very fast</option>
              <option value="600">Fast</option>
              <option value="900" selected>Normal</option>
              <option value="1500">Slow</option>
              <option value="2500">Very slow</option>
            </select>
          </label>
          <span id="tmuxStreamStatus" class="small"></span>
          <span class="small" id="status"></span>
        </div>

        <div class="row">
          <label class="field">
            <span class="label">New session</span>
            <input id="sessionName" placeholder="Optional name (letters, numbers, ._-)" />
          </label>
          <button class="primary" onclick="createSession()">Create session</button>
          <label class="field">
            <span class="label">Close session</span>
            <select id="sessionSelect"></select>
          </label>
          <button id="closeSessionBtn" class="danger" onclick="closeSession()">Close</button>
        </div>

	        <div class="row">
	          <label class="field">
	            <span class="label">Pane</span>
	            <select id="pane"></select>
	          </label>
	          <button onclick="fetchScreen()">View</button>
	          <button class="ghost" onclick="ctrlC()">Interrupt</button>
	        </div>

        <div id="out" class="console" data-testid="tmux-out">Loading…</div>

        <div class="row">
          <label class="field grow">
            <span class="label">Send to pane</span>
            <input id="msg" placeholder="Send to selected pane (Codrex TUI or shell)..." />
          </label>
          <button class="primary" onclick="sendMsg()">Send</button>
        </div>
      </section>

      <section id="desktopSection" class="card stack desktop-tone">
        <div class="card-head">
          <div class="stack">
            <h2>Desktop Remote (Control Pane)</h2>
            <p class="small">Live screenshot stream + input controls for mobile/tablet remote actions.</p>
          </div>
          <div class="row tight">
            <span id="desktopModeBadge" class="__DESKTOP_MODE_BADGE_CLASS__" data-testid="desktop-stream-mode">__DESKTOP_MODE_BADGE__</span>
            <button id="desktopModeBtn" class="toggle-btn" onclick="toggleDesktopMode()" data-testid="desktop-mode-btn">Control: __DESKTOP_TOGGLE_LABEL__</button>
          </div>
        </div>
        <div class="stack desktop-js-pane">
          <div class="desktop-live-only">
            <img id="deskImg" alt="Desktop remote stream" src="__DESKTOP_STREAM_SRC__" data-testid="desktop-image" />
            <div class="row tight">
              <a id="deskStreamLink" class="ghost" href="__DESKTOP_STREAM_URL__" target="_blank" rel="noopener">Open live stream</a>
              <label class="field" style="min-width: 170px;">
                <span class="label">Stream profile</span>
                <select id="deskPerf" data-testid="desktop-stream-profile">
                  <option value="balanced" selected>Balanced</option>
                  <option value="responsive">Responsive</option>
                  <option value="saver">Data Saver</option>
                </select>
              </label>
              <a class="ghost" href="/auth/status" target="_blank" rel="noopener">Auth status</a>
            </div>
            <div class="desktop-quick-grid" id="desktopJsControls">
              <button onclick="desktopClick('left')">Left Click</button>
              <button onclick="desktopClick('right')">Right Click</button>
              <button onclick="desktopClick('left', true)">Double Click</button>
              <button onclick="desktopScroll(-240)">Scroll Up</button>
              <button onclick="desktopScroll(240)">Scroll Down</button>
            </div>
    	        <div class="row">
    	          <label class="field grow">
    	            <span class="label">Live Keyboard (real time)</span>
    	            <input id="deskLiveInput" placeholder="Type here to control the desktop. Backspace works." data-testid="desktop-live-input" autocomplete="off" autocapitalize="off" spellcheck="false" />
    	          </label>
    	          <button class="ghost" onclick="pasteToLive()" data-testid="desktop-live-paste">Paste</button>
    	          <button class="ghost" onclick="resetLiveBuffer()" data-testid="desktop-live-reset">Reset</button>
    	        </div>
    	        <p class="small muted">This box mirrors what you type on mobile. It may not reflect existing desktop text.</p>
    	        <div class="row">
    	          <label class="field">
    	            <span class="label">Key</span>
    	            <select id="deskKey" data-testid="desktop-key-select">
    	              <option value="enter">Enter</option>
    	              <option value="backspace">Backspace</option>
    	              <option value="delete">Delete</option>
    	              <option value="esc">Esc</option>
    	              <option value="tab">Tab</option>
    	              <option value="up">Up</option>
    	              <option value="down">Down</option>
    	              <option value="left">Left</option>
    	              <option value="right">Right</option>
    	              <option value="win+tab">Win+Tab</option>
    	              <option value="alt+tab">Alt+Tab</option>
    	              <option value="ctrl+a">Ctrl+A</option>
    	              <option value="ctrl+c">Ctrl+C</option>
    	            </select>
    	          </label>
    	          <button onclick="desktopSendKey()">Send Key</button>
    	          <span id="deskStatus" class="small"></span>
    	        </div>
          </div>
          <div class="desktop-off-only small muted">Desktop stream/control is off. Turn it on when you need to interact.</div>
        </div>

        <div class="stack desktop-fallback-pane" data-testid="legacy-desktop-controls">
          <div class="row">
            <form class="legacy-form" method="post" action="/legacy/desktop/mode">
              <input type="hidden" name="enabled" value="1" />
              <input type="hidden" name="next" value="/legacy" />
              <button class="primary" type="submit">Desktop On</button>
            </form>
            <form class="legacy-form" method="post" action="/legacy/desktop/mode">
              <input type="hidden" name="enabled" value="0" />
              <input type="hidden" name="next" value="/legacy" />
              <button class="ghost" type="submit">Desktop Off</button>
            </form>
          </div>
          <div class="small">Fallback Controls (No-JS): use these when JS stays at <span class="mono">JS: basic</span>.</div>

          <div class="row desktop-live-only">
            <form class="legacy-form" method="post" action="/legacy/desktop/click" target="legacyDesktopResult">
              <input type="hidden" name="button" value="left" />
              <button type="submit">Left Click (cursor)</button>
            </form>
            <form class="legacy-form" method="post" action="/legacy/desktop/click" target="legacyDesktopResult">
              <input type="hidden" name="button" value="right" />
              <button type="submit">Right Click (cursor)</button>
            </form>
            <form class="legacy-form" method="post" action="/legacy/desktop/click" target="legacyDesktopResult">
              <input type="hidden" name="button" value="left" />
              <input type="hidden" name="double" value="1" />
              <button type="submit">Double Click (cursor)</button>
            </form>
            <form class="legacy-form" method="post" action="/legacy/desktop/scroll" target="legacyDesktopResult">
              <input type="hidden" name="delta" value="-240" />
              <button type="submit">Scroll Up</button>
            </form>
            <form class="legacy-form" method="post" action="/legacy/desktop/scroll" target="legacyDesktopResult">
              <input type="hidden" name="delta" value="240" />
              <button type="submit">Scroll Down</button>
            </form>
          </div>

          <form class="legacy-form desktop-live-only" method="post" action="/legacy/desktop/key" target="legacyDesktopResult">
            <label class="field">
              <span class="label">Key (No-JS)</span>
              <select name="key">
                <option value="enter">Enter</option>
                <option value="backspace">Backspace</option>
                <option value="delete">Delete</option>
                <option value="esc">Esc</option>
                <option value="tab">Tab</option>
                <option value="up">Up</option>
                <option value="down">Down</option>
                <option value="left">Left</option>
                <option value="right">Right</option>
                <option value="win+tab">Win+Tab</option>
                <option value="alt+tab">Alt+Tab</option>
                <option value="ctrl+a">Ctrl+A</option>
                <option value="ctrl+c">Ctrl+C</option>
              </select>
            </label>
            <button type="submit">Send Key</button>
          </form>

          <form class="legacy-form desktop-live-only" method="post" action="/legacy/desktop/text" target="legacyDesktopResult">
            <label class="field grow">
              <span class="label">Type text (No-JS)</span>
              <input name="text" placeholder="Type text to send to Windows desktop..." required />
            </label>
            <button type="submit">Send Text</button>
          </form>

          <div class="small muted desktop-live-only">Tap-to-click map (native desktop size). Pan inside this area, then tap to click that exact point.</div>
          <form class="stack desktop-live-only" method="post" action="/legacy/desktop/tap" target="legacyDesktopResult">
            <input type="hidden" name="button" value="left" />
            <input type="hidden" name="double" value="0" />
            <input type="hidden" name="render_w" value="__DESKTOP_TAP_W__" />
            <input type="hidden" name="render_h" value="__DESKTOP_TAP_H__" />
            <div class="legacy-stream-wrap">
              <input class="legacy-stream-tap" type="image" name="tap" src="__DESKTOP_STREAM_SRC__" alt="Tap this live stream to left-click at that point" width="__DESKTOP_TAP_W__" height="__DESKTOP_TAP_H__" data-testid="legacy-desktop-tap-map" />
            </div>
          </form>
          <div class="desktop-off-only small muted">Desktop stream/control is off. Use Desktop On above to resume.</div>
          <iframe name="legacyDesktopResult" title="Desktop fallback result" style="width:100%; min-height:120px; border:1px solid var(--border); border-radius: var(--radius-sm); background:#fff;"></iframe>
        </div>
      </section>

      <section id="execSection" class="card stack exec-tone">
        <div class="card-head">
          <div class="stack">
            <h2>One-shot: codex exec</h2>
            <p class="small">Runs <span class="mono">codex exec --cd __CODEX_WORKDIR__</span> inside WSL and shows stdout/stderr.</p>
          </div>
          <div class="row">
            <button id="execBtn" class="primary" onclick="runExec()">Run</button>
            <button class="ghost" onclick="loadRuns()">Refresh runs</button>
          </div>
        </div>
        <textarea id="execPrompt" placeholder="Example: Summarize this repo and propose next steps"></textarea>
        <div class="row">
          <span class="small" id="execStatus"></span>
        </div>
        <div id="execOut" class="console mono"></div>
        <div class="small" style="margin-top:8px;">Recent runs:</div>
        <div id="runsList" class="small mono"></div>
      </section>

      <section id="filesSection" class="card stack files-tone">
        <div class="card-head">
          <div class="stack">
            <h2>WSL Files</h2>
            <p class="small">Download and upload files under <span class="mono">__CODEX_ROOT__</span>.</p>
          </div>
        </div>

        <div class="row">
          <label class="field grow">
            <span class="label">Download path</span>
            <input id="dlPath" placeholder="Relative path, e.g. README.md" />
          </label>
          <button onclick="downloadWsl()">Download</button>
        </div>

        <div class="row">
          <label class="field grow">
            <span class="label">Upload destination</span>
            <input id="upDest" placeholder="Relative path (leave blank to use filename)" />
          </label>
          <input id="upFile" type="file" />
          <button class="primary" onclick="uploadWsl()">Upload</button>
          <span class="small" id="fileStatus"></span>
        </div>

        <div class="small mono" id="fileOut"></div>
      </section>

      <section id="shotSection" class="card stack shot-tone">
        <div class="card-head">
          <div class="stack">
            <h2>Screenshot Capture</h2>
            <p class="small">One-tap desktop screenshot capture and share.</p>
          </div>
          <button onclick="takeShot()">Capture</button>
        </div>
        <div class="row tight">
          <a class="ghost" href="/shot" target="_blank" rel="noopener">Open latest capture</a>
        </div>
        <img id="shotImg" alt="Windows screenshot" />
      </section>
    </div>
  </div>

<script>
// Minimal ES5 "JS is enabled" signal that runs even if later scripts fail to parse.
(function () {
  try {
    if (document && document.documentElement && document.documentElement.classList) {
      document.documentElement.classList.add('js-basic-mode');
    }
    var el = document.getElementById('jsBadge');
    if (el) el.textContent = "JS: basic";
  } catch (e) {}
})();
</script>

<script>
// Surface runtime errors in the UI so mobile browsers without devtools aren't a black box.
try {
  window.addEventListener('error', (e) => {
    const msg = (e && e.message) ? String(e.message) : "error";
    const el = document.getElementById('jsBadge');
    if (el) el.textContent = `JS: err`;
    const st = document.getElementById('status');
    if (st && msg) st.textContent = `JS error: ${msg}`.slice(0, 120);
  });
  window.addEventListener('unhandledrejection', (e) => {
    const msg = (e && e.reason) ? String(e.reason) : "promise rejection";
    const el = document.getElementById('jsBadge');
    if (el) el.textContent = `JS: err`;
    const st = document.getElementById('status');
    if (st && msg) st.textContent = `JS rejection: ${msg}`.slice(0, 120);
  });
} catch (_e) {}

const paneSel = document.getElementById('pane');
const sessionSel = document.getElementById('sessionSelect');
const closeSessionBtn = document.getElementById('closeSessionBtn');
const outEl = document.getElementById('out');
const statusEl = document.getElementById('status');
const shotImg = document.getElementById('shotImg');

const execStatusEl = document.getElementById('execStatus');
const execOutEl = document.getElementById('execOut');
const runsListEl = document.getElementById('runsList');
const execBtn = document.getElementById('execBtn');

const fileStatusEl = document.getElementById('fileStatus');
const fileOutEl = document.getElementById('fileOut');
const tmuxBadgeEl = document.getElementById('tmuxBadge');
const tmuxStreamBtnEl = document.getElementById('tmuxStreamBtn');
const tmuxStreamRateEl = document.getElementById('tmuxStreamRate');
const tmuxStreamStatusEl = document.getElementById('tmuxStreamStatus');
const authGateEl = document.getElementById('authGate');
const authMsgEl = document.getElementById('authMsg');
const authTokenInputEl = document.getElementById('authTokenInput');
const codexSessionBadgeEl = document.getElementById('codexSessionBadge');
const codexSessionNameEl = document.getElementById('codexSessionName');
const codexSessionCwdEl = document.getElementById('codexSessionCwd');
const codexSessionSelectEl = document.getElementById('codexSessionSelect');
const codexSessionPromptEl = document.getElementById('codexSessionPrompt');
const codexSessionImageEl = document.getElementById('codexSessionImage');
const codexSessionImagePromptEl = document.getElementById('codexSessionImagePrompt');
const codexSessionOutEl = document.getElementById('codexSessionOut');
const codexSessionStateEl = document.getElementById('codexSessionState');
const codexStreamBtnEl = document.getElementById('codexStreamBtn');
const codexStreamRateEl = document.getElementById('codexStreamRate');
const codexStreamStatusEl = document.getElementById('codexStreamStatus');
		const deskImgEl = document.getElementById('deskImg');
		const deskStatusEl = document.getElementById('deskStatus');
		const deskLiveInputEl = document.getElementById('deskLiveInput');
		const deskKeyEl = document.getElementById('deskKey');
		const deskPerfEl = document.getElementById('deskPerf');
		const deskStreamLinkEl = document.getElementById('deskStreamLink');
		const deskModeBtnEl = document.getElementById('desktopModeBtn');
		const deskModeBadgeEl = document.getElementById('desktopModeBadge');
		const deskRateEl = document.getElementById('deskRate');
		const deskAutoBtnEl = document.getElementById('deskAutoBtn');
	const pairBaseUrlEl = document.getElementById('pairBaseUrl');
	const pairQrImgEl = document.getElementById('pairQrImg');
	const pairLinkEl = document.getElementById('pairLink');
const pairStatusEl = document.getElementById('pairStatus');
const pairExpiresEl = document.getElementById('pairExpires');
const pairRouteBadgeEl = document.getElementById('pairRouteBadge');
const pairLanIpEl = document.getElementById('pairLanIp');
const pairTailscaleIpEl = document.getElementById('pairTailscaleIp');
const pairTailscaleOnlyBtnEl = document.getElementById('pairTailscaleOnlyBtn');
const pairSafetyStatusEl = document.getElementById('pairSafetyStatus');

const paneSessionMap = new Map();
const codexSessionPaneMap = new Map();
let tmuxStream = { enabled: true, es: null, paneId: "", url: "", intervalMs: 900, maxChars: 25000, connected: false };
let codexStream = { enabled: true, es: null, paneId: "", url: "", intervalMs: 900, maxChars: 25000, connected: false };
let desktopInfo = null;
		let desktopModeEnabled = __DESKTOP_MODE_ENABLED__;
		let desktopStreamUrl = "__DESKTOP_STREAM_URL__";
		const desktopBlankImage = "__BLANK_IMAGE_DATA_URL__";
		const desktopLiveBadgeText = "__DESKTOP_LIVE_BADGE__";
		let desktopAutoTimer = null;
		let desktopAutoEnabled = false;
		let desktopAutoMs = 1200;
		let desktopLastFrameMs = 0;
		let desktopFrameInFlight = false;
		let desktopLastReqMs = 0;
		let desktopReqCount = 0;
		let desktopOkCount = 0;
		let desktopErrCount = 0;
		let desktopLastDiagMs = 0;
		let desktopDiagInFlight = false;
		let lastDesktopPoint = null;
		let liveKeyQueue = Promise.resolve();
		let liveLastValue = "";
		let netInfo = null;
		let pairCountdownTimer = null;
		let pairTailscaleOnly = false;
let authState = { auth_required: false, authenticated: false };
let desktopAutoBound = false;

function bindDesktopAutoButton() {
  if (!deskAutoBtnEl || desktopAutoBound) return;
  deskAutoBound = true;
  deskAutoBtnEl.addEventListener('click', (e) => {
    try { e.preventDefault(); } catch (_e) {}
    toggleDesktopAuto();
  });
}

	if (pairBaseUrlEl && !pairBaseUrlEl.value) {
	  pairBaseUrlEl.value = window.location.origin;
	}
if (pairBaseUrlEl) {
  pairBaseUrlEl.addEventListener('input', () => _syncPairRouteUi());
  pairBaseUrlEl.addEventListener('change', () => _syncPairRouteUi());
}

function encPaneId(p) { return encodeURIComponent(p); }

function _isNearBottom(el, thresholdPx = 80) {
  if (!el) return true;
  try {
    const delta = el.scrollHeight - el.scrollTop - el.clientHeight;
    return delta < thresholdPx;
  } catch (_e) {
    return true;
  }
}

function _setConsoleText(el, text) {
  if (!el) return;
  const stick = _isNearBottom(el);
  el.textContent = text || "";
  if (stick) {
    try { el.scrollTop = el.scrollHeight; } catch (_e) {}
  }
}

function _readIntValue(el, fallback) {
  if (!el) return fallback;
  const n = Number(el.value);
  return Number.isFinite(n) ? n : fallback;
}

function _closeEventSource(es) {
  try { if (es) es.close(); } catch (_e) {}
}

function _streamUrlForPane(paneId, intervalMs, maxChars) {
  const qs = new URLSearchParams();
  qs.set("interval_ms", String(intervalMs || 900));
  qs.set("max_chars", String(maxChars || 25000));
  return `/tmux/pane/${encPaneId(paneId)}/stream?${qs.toString()}`;
}

function _syncStreamBtn(btnEl, enabled) {
  if (!btnEl) return;
  btnEl.textContent = enabled ? "Stream: On" : "Stream: Off";
  btnEl.classList.add("toggle-btn");
  btnEl.classList.toggle("state-on", !!enabled);
  btnEl.classList.toggle("state-off", !enabled);
}

function _setStreamStatus(statusEl, text) {
  if (!statusEl) return;
  statusEl.textContent = text || "";
}

function _startPaneStream(streamState, paneId, outTargetEl, statusEl) {
  if (!streamState || !streamState.enabled) return;
  if (!paneId) return;
  const url = _streamUrlForPane(paneId, streamState.intervalMs, streamState.maxChars);
  if (streamState.es && streamState.url === url) return;

  _closeEventSource(streamState.es);
  streamState.es = null;
  streamState.paneId = paneId;
  streamState.url = url;
  streamState.connected = false;

  _setStreamStatus(statusEl, "stream: connecting…");
  const es = new EventSource(url);
  streamState.es = es;

  es.addEventListener("hello", (_ev) => {
    streamState.connected = true;
    _setStreamStatus(statusEl, `stream: on (${streamState.intervalMs}ms)`);
  });

  es.addEventListener("screen", (ev) => {
    let j = null;
    try { j = JSON.parse(ev.data); } catch (_e) { j = null; }
    if (!j || !j.ok) return;
    _setConsoleText(outTargetEl, j.text || "");
  });

  es.addEventListener("error", (_ev) => {
    streamState.connected = false;
    _setStreamStatus(statusEl, "stream: error (fallback: polling)");
    _closeEventSource(es);
    if (streamState.es === es) streamState.es = null;
  });
}

function _stopPaneStream(streamState, statusEl) {
  if (!streamState) return;
  _closeEventSource(streamState.es);
  streamState.es = null;
  streamState.paneId = "";
  streamState.url = "";
  streamState.connected = false;
  _setStreamStatus(statusEl, "stream: off");
}

function toggleTmuxStream() {
  tmuxStream.enabled = !tmuxStream.enabled;
  _syncStreamBtn(tmuxStreamBtnEl, tmuxStream.enabled);
  if (tmuxStream.enabled) {
    tmuxStream.intervalMs = _readIntValue(tmuxStreamRateEl, tmuxStream.intervalMs);
    _startPaneStream(tmuxStream, paneSel.value, outEl, tmuxStreamStatusEl);
  } else {
    _stopPaneStream(tmuxStream, tmuxStreamStatusEl);
  }
}

function toggleCodexStream() {
  codexStream.enabled = !codexStream.enabled;
  _syncStreamBtn(codexStreamBtnEl, codexStream.enabled);
  if (codexStream.enabled) {
    codexStream.intervalMs = _readIntValue(codexStreamRateEl, codexStream.intervalMs);
    const session = codexSessionSelectEl ? codexSessionSelectEl.value : "";
    const paneId = session ? (codexSessionPaneMap.get(session) || "") : "";
    _startPaneStream(codexStream, paneId, codexSessionOutEl, codexStreamStatusEl);
  } else {
    _stopPaneStream(codexStream, codexStreamStatusEl);
  }
}

function setAuthGate(open, message="") {
  authGateEl.classList.toggle('hidden', !open);
  authMsgEl.textContent = message || "";
}

async function apiFetch(url, options = {}) {
  const res = await fetch(url, options);
  if (res.status === 401) {
    setAuthGate(true, "Authentication required.");
    throw new Error("unauthorized");
  }
  return res;
}

async function checkAuthStatus() {
  const r = await fetch('/auth/status');
  const j = await r.json();
  if (!j.ok) return;
  authState = j;
  if (j.auth_required && !j.authenticated) {
    setAuthGate(true, "Enter access token.");
  } else {
    setAuthGate(false);
  }
}

function _hashParams() {
  // Supports pairing links like:
  //   http://host:48787/#pair=...   (hash isn't sent to server)
  // and token links like:
  //   http://host:48787/#token=...
  const raw = (window.location.hash || "").replace(/^#/, "").trim();
  if (!raw) return null;
  try { return new URLSearchParams(raw); } catch (_e) { return null; }
}

function _clearHash() {
  // Removes token from URL bar/history after using it.
  try {
    history.replaceState(null, "", window.location.pathname + window.location.search);
  } catch (_e) {}
}

async function autoLoginFromHash() {
  const params = _hashParams();
  if (!params) return false;
  const token = (params.get("token") || params.get("auth") || "").trim();
  const pair = (params.get("pair") || params.get("code") || "").trim();
  if (!token && !pair) return false;
  authMsgEl.textContent = "Pairing…";
  try {
    const r = await fetch(pair ? '/auth/pair/exchange' : '/auth/login', {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(pair ? { code: pair } : { token })
    });
    const j = await r.json();
    _clearHash();
    if (!j.ok) {
      setAuthGate(true, j.detail || "Login failed.");
      return false;
    }
    setAuthGate(false);
    return true;
  } catch (_e) {
    _clearHash();
    return false;
  }
}

async function loginAuth() {
  const token = (authTokenInputEl.value || "").trim();
  if (!token) {
    setAuthGate(true, "Token is required.");
    return;
  }
  authMsgEl.textContent = "Checking token…";
  try {
    const r = await fetch('/auth/login', {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ token })
    });
    const j = await r.json();
    if (!j.ok) {
      setAuthGate(true, j.detail || "Login failed.");
      return;
    }
    authTokenInputEl.value = "";
    setAuthGate(false);
    await bootstrapAll();
  } catch (_e) {
    setAuthGate(true, "Login request failed.");
  }
}

async function logoutAuth() {
  await fetch('/auth/logout', { method: 'POST' });
  setAuthGate(true, "Logged out.");
}

async function _fetchNetInfo(force = false) {
  if (netInfo && !force) return netInfo;
  try {
    const r = await apiFetch('/net/info');
    const j = await r.json();
    if (j && j.ok) {
      netInfo = j;
      _syncPairNetworkUi();
      return netInfo;
    }
  } catch (_e) {
    _syncPairNetworkUi();
  }
  return null;
}

function _normalizeBaseUrl(raw) {
  let base = (raw || "").trim();
  if (!base) return "";
  if (!/^https?:\\/\\//i.test(base)) base = "http://" + base;
  base = base.replace(/\\/+$/, "");
  return base;
}

function _setPairStatus(msg) {
  if (!pairStatusEl) return;
  pairStatusEl.textContent = msg || "";
}

const PAIR_TS_ONLY_KEY = "codex_pair_tailscale_only_v1";

function _storageGetBool(key, fallback = false) {
  try {
    const raw = localStorage.getItem(key);
    if (raw == null) return fallback;
    return String(raw).toLowerCase() === "true";
  } catch (_e) {
    return fallback;
  }
}

function _storageSetBool(key, value) {
  try { localStorage.setItem(key, value ? "true" : "false"); } catch (_e) {}
}

function _baseHost(baseUrl) {
  try {
    const base = _normalizeBaseUrl(baseUrl || "");
    if (!base) return "";
    return (new URL(base)).hostname || "";
  } catch (_e) {
    return "";
  }
}

function _isPrivateIpv4(host) {
  if (!/^\\d+\\.\\d+\\.\\d+\\.\\d+$/.test(host || "")) return false;
  return (
    host.startsWith("10.") ||
    host.startsWith("192.168.") ||
    /^172\\.(1[6-9]|2\\d|3[01])\\./.test(host)
  );
}

function _pairRouteKind(baseUrl, info) {
  const host = _baseHost(baseUrl);
  if (!host) return "unknown";
  if (host === "localhost" || host === "127.0.0.1") return "local";
  const ts = (info && info.tailscale_ip) ? String(info.tailscale_ip) : "";
  const lan = (info && info.lan_ip) ? String(info.lan_ip) : "";
  if (ts && host === ts) return "tailscale";
  if (lan && host === lan) return "lan";
  if (/^100\\./.test(host) || host.endsWith(".ts.net")) return "tailscale";
  if (_isPrivateIpv4(host)) return "lan";
  return "unknown";
}

function _pairRouteLabel(kind) {
  if (kind === "tailscale") return "Tailscale";
  if (kind === "lan") return "LAN";
  if (kind === "local") return "Localhost";
  return "Unknown";
}

function _syncPairRouteUi() {
  const kind = _pairRouteKind(pairBaseUrlEl ? pairBaseUrlEl.value : "", netInfo);
  if (pairRouteBadgeEl) {
    pairRouteBadgeEl.textContent = _pairRouteLabel(kind);
    pairRouteBadgeEl.classList.remove("route-ts", "route-lan", "route-local", "route-unknown");
    if (kind === "tailscale") pairRouteBadgeEl.classList.add("route-ts");
    else if (kind === "lan") pairRouteBadgeEl.classList.add("route-lan");
    else if (kind === "local") pairRouteBadgeEl.classList.add("route-local");
    else pairRouteBadgeEl.classList.add("route-unknown");
  }
  if (pairSafetyStatusEl) {
    pairSafetyStatusEl.classList.remove("pair-safety-ok", "pair-safety-warn");
    if (pairTailscaleOnly && kind !== "tailscale") {
      pairSafetyStatusEl.classList.add("pair-safety-warn");
      pairSafetyStatusEl.textContent = "Tailscale-only is ON. Current base URL is blocked.";
    } else if (kind === "local") {
      pairSafetyStatusEl.classList.add("pair-safety-warn");
      pairSafetyStatusEl.textContent = "Localhost is not reachable from phone. Use LAN or Tailscale.";
    } else if (kind === "unknown") {
      pairSafetyStatusEl.classList.add("pair-safety-warn");
      pairSafetyStatusEl.textContent = "Route not recognized. Verify this URL is reachable from mobile.";
    } else {
      pairSafetyStatusEl.classList.add("pair-safety-ok");
      pairSafetyStatusEl.textContent = "Route looks reachable.";
    }
  }
}

function _syncPairNetworkUi() {
  if (pairLanIpEl) pairLanIpEl.textContent = (netInfo && netInfo.lan_ip) ? netInfo.lan_ip : "--";
  if (pairTailscaleIpEl) pairTailscaleIpEl.textContent = (netInfo && netInfo.tailscale_ip) ? netInfo.tailscale_ip : "--";
  _syncPairRouteUi();
}

function _syncTailscaleOnlyBtn() {
  if (!pairTailscaleOnlyBtnEl) return;
  pairTailscaleOnlyBtnEl.textContent = pairTailscaleOnly ? "Tailscale-only: On" : "Tailscale-only: Off";
  pairTailscaleOnlyBtnEl.classList.toggle("state-on", pairTailscaleOnly);
  pairTailscaleOnlyBtnEl.classList.toggle("state-off", !pairTailscaleOnly);
}

async function toggleTailscaleOnly() {
  pairTailscaleOnly = !pairTailscaleOnly;
  _storageSetBool(PAIR_TS_ONLY_KEY, pairTailscaleOnly);
  _syncTailscaleOnlyBtn();
  if (pairTailscaleOnly) {
    await useTailscaleBase();
    const kind = _pairRouteKind(pairBaseUrlEl ? pairBaseUrlEl.value : "", netInfo);
    if (kind === "tailscale") {
      _setPairStatus("Tailscale-only enabled. Using Tailscale base URL.");
    } else {
      _setPairStatus("Tailscale-only enabled, but Tailscale IP is not detected yet.");
    }
  } else {
    _setPairStatus("Tailscale-only disabled.");
  }
  _syncPairRouteUi();
}

function _startPairCountdown(seconds) {
  if (!pairExpiresEl) return;
  if (pairCountdownTimer) {
    clearInterval(pairCountdownTimer);
    pairCountdownTimer = null;
  }
  let remaining = Math.max(0, Number(seconds || 0));
  pairExpiresEl.textContent = String(remaining);
  pairCountdownTimer = setInterval(() => {
    remaining -= 1;
    pairExpiresEl.textContent = String(Math.max(0, remaining));
    if (remaining <= 0 && pairCountdownTimer) {
      clearInterval(pairCountdownTimer);
      pairCountdownTimer = null;
      _setPairStatus("Pairing code expired. Generate a new QR.");
    }
  }, 1000);
}

async function useTailscaleBase() {
  _setPairStatus("Detecting Tailscale IP…");
  const info = await _fetchNetInfo(true);
  if (!info || !info.tailscale_ip) {
    _setPairStatus("Tailscale IP not detected on this laptop.");
    _syncPairRouteUi();
    return;
  }
  const port = window.location.port || "48787";
  pairBaseUrlEl.value = `http://${info.tailscale_ip}:${port}`;
  _setPairStatus("Using Tailscale base URL.");
  _syncPairRouteUi();
}

async function useLanBase() {
  _setPairStatus("Detecting LAN IP…");
  const info = await _fetchNetInfo(true);
  if (!info || !info.lan_ip) {
    _setPairStatus("LAN IP not detected.");
    _syncPairRouteUi();
    return;
  }
  const port = window.location.port || "48787";
  pairBaseUrlEl.value = `http://${info.lan_ip}:${port}`;
  _setPairStatus("Using LAN base URL.");
  _syncPairRouteUi();
}

async function generatePairQr() {
  if (!pairBaseUrlEl || !pairQrImgEl || !pairLinkEl) return;

  let base = _normalizeBaseUrl(pairBaseUrlEl.value || window.location.origin);
  if (!base) {
    _setPairStatus("Base URL is required.");
    return;
  }
  let routeKind = _pairRouteKind(base, netInfo);
  if (pairTailscaleOnly && routeKind !== "tailscale") {
    await useTailscaleBase();
    base = _normalizeBaseUrl(pairBaseUrlEl.value || base);
    routeKind = _pairRouteKind(base, netInfo);
  }
  if (pairTailscaleOnly && routeKind !== "tailscale") {
    _syncPairRouteUi();
    _setPairStatus("Blocked by Tailscale-only mode. Tailscale IP is not ready.");
    return;
  }
  if (routeKind === "local") {
    _setPairStatus("Localhost cannot be scanned from phone. Use LAN or Tailscale.");
    _syncPairRouteUi();
    return;
  }

  _setPairStatus("Generating one-time code…");
  try {
    const r = await apiFetch('/auth/pair/create', { method: "POST" });
    const j = await r.json();
    if (!j.ok) {
      _setPairStatus(j.detail || "Failed to create pairing code.");
      return;
    }
    const url = `${base}/auth/pair/consume?code=${encodeURIComponent(j.code)}`;
    pairLinkEl.textContent = url;
    pairQrImgEl.src = `/auth/pair/qr.svg?data=${encodeURIComponent(url)}&ts=${Date.now()}`;
    pairQrImgEl.style.display = "block";
    _startPairCountdown(j.expires_in || 0);
    _setPairStatus("QR ready. Scan from phone.");
    _syncPairRouteUi();
  } catch (_e) {
    _setPairStatus("Pairing request failed.");
  }
}

pairTailscaleOnly = _storageGetBool(PAIR_TS_ONLY_KEY, false);
_syncTailscaleOnlyBtn();
_syncPairNetworkUi();

function updateSessionSelect(sessions) {
  sessionSel.innerHTML = "";
  if (!sessions || sessions.length === 0) {
    const opt = document.createElement('option');
    opt.value = "";
    opt.textContent = "No sessions";
    sessionSel.appendChild(opt);
    sessionSel.disabled = true;
    closeSessionBtn.disabled = true;
    return;
  }

  sessionSel.disabled = false;
  closeSessionBtn.disabled = false;
  for (const s of sessions) {
    const opt = document.createElement('option');
    opt.value = s;
    opt.textContent = s;
    sessionSel.appendChild(opt);
  }
}

async function refreshPanes() {
  statusEl.textContent = "Refreshing…";
  refreshTmuxHealth();
  const r = await apiFetch('/tmux/panes');
  const j = await r.json();

  paneSel.innerHTML = "";
  paneSessionMap.clear();
  if (!j.ok) {
    statusEl.textContent = "Failed to list panes";
    _setConsoleText(outEl, JSON.stringify(j, null, 2));
    return;
  }

  const panes = j.panes || [];
  panes.sort((a,b) => (b.active - a.active));
  const sessions = new Set();

  for (const p of panes) {
    const opt = document.createElement('option');
    opt.value = p.pane_id;
    opt.textContent = `${p.session} | ${p.pane_id} | ${p.current_command} | ${p.current_path}${p.active ? " (active)" : ""}`;
    paneSel.appendChild(opt);
    sessions.add(p.session);
    paneSessionMap.set(p.pane_id, p.session);
  }

  statusEl.textContent = `Found ${panes.length} panes`;
  updateSessionSelect([...sessions].sort());

  if (panes.length) {
    paneSel.disabled = false;
    fetchScreen();
    tmuxStream.intervalMs = _readIntValue(tmuxStreamRateEl, tmuxStream.intervalMs);
    _startPaneStream(tmuxStream, paneSel.value, outEl, tmuxStreamStatusEl);
  } else {
    paneSel.disabled = true;
    _stopPaneStream(tmuxStream, tmuxStreamStatusEl);
    _setConsoleText(outEl, "No panes available. Create a session to get started.");
  }
}

async function createSession() {
  const nameEl = document.getElementById('sessionName');
  const name = (nameEl.value || "").trim();
  statusEl.textContent = "Creating session…";

  const payload = name ? { name } : {};
  const r = await apiFetch('/tmux/session', {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload)
  });
  const j = await r.json();
  if (!j.ok) {
    statusEl.textContent = "Failed to create session";
    _setConsoleText(outEl, JSON.stringify(j, null, 2));
    return;
  }
  nameEl.value = "";
  statusEl.textContent = j.name ? `Session created: ${j.name}` : "Session created";
  refreshPanes();
}

async function closeSession() {
  const name = sessionSel.value;
  if (!name) return;
  if (!confirm(`Close session \"${name}\"?`)) return;

  statusEl.textContent = "Closing session…";
  const r = await apiFetch(`/tmux/session/${encodeURIComponent(name)}`, { method: "DELETE" });
  const j = await r.json();
  if (!j.ok) {
    statusEl.textContent = "Failed to close session";
    _setConsoleText(outEl, JSON.stringify(j, null, 2));
    return;
  }
  statusEl.textContent = `Session closed: ${name}`;
  refreshPanes();
}

async function debugTmux() {
  statusEl.textContent = "Collecting tmux debug…";
  const r = await apiFetch('/tmux/debug');
  const j = await r.json();
  statusEl.textContent = "Debug collected";
  _setConsoleText(outEl, JSON.stringify(j, null, 2));
}

async function refreshTmuxHealth() {
  try {
    const r = await apiFetch('/tmux/health');
    const j = await r.json();
    if (!j.ok) {
      tmuxBadgeEl.textContent = "tmux: error";
      tmuxBadgeEl.className = "badge err";
      return;
    }
    updateSessionSelect(j.sessions || []);
    if (j.state === "no_server") {
      tmuxBadgeEl.textContent = "tmux: not running";
      tmuxBadgeEl.className = "badge warn";
      return;
    }
    if (j.count === 0) {
      tmuxBadgeEl.textContent = "tmux: no sessions";
      tmuxBadgeEl.className = "badge warn";
      return;
    }
    tmuxBadgeEl.textContent = `tmux: ${j.count} session${j.count === 1 ? "" : "s"}`;
    tmuxBadgeEl.className = "badge ok";
  } catch (e) {
    tmuxBadgeEl.textContent = "tmux: error";
    tmuxBadgeEl.className = "badge err";
  }
}

async function fetchScreen() {
  const pane = paneSel.value;
  if (!pane) return;
  const url = `/tmux/pane/${encPaneId(pane)}/screen`;
  const r = await apiFetch(url);
  const j = await r.json();
  _setConsoleText(outEl, j.ok ? (j.text || "") : JSON.stringify(j, null, 2));
}

async function sendMsg() {
  const pane = paneSel.value;
  const msgEl = document.getElementById('msg');
  const text = msgEl.value;
  if (!pane || !text) return;

  const r = await apiFetch(`/tmux/pane/${encPaneId(pane)}/send`, {
    method: "POST",
    headers: { "Content-Type": "text/plain" },
    body: text
  });
  const j = await r.json();
  if (!j.ok) {
    _setConsoleText(outEl, JSON.stringify(j, null, 2));
    return;
  }
  msgEl.value = "";
  if (tmuxStream.enabled) {
    tmuxStream.intervalMs = _readIntValue(tmuxStreamRateEl, tmuxStream.intervalMs);
    _startPaneStream(tmuxStream, pane, outEl, tmuxStreamStatusEl);
  } else {
    setTimeout(fetchScreen, 500);
  }
}

async function ctrlC() {
  const pane = paneSel.value;
  if (!pane) return;
  const r = await apiFetch(`/tmux/pane/${encPaneId(pane)}/ctrlc`, { method: "POST" });
  const j = await r.json();
  if (!j.ok) _setConsoleText(outEl, JSON.stringify(j, null, 2));
  if (tmuxStream.enabled) {
    tmuxStream.intervalMs = _readIntValue(tmuxStreamRateEl, tmuxStream.intervalMs);
    _startPaneStream(tmuxStream, pane, outEl, tmuxStreamStatusEl);
  } else {
    setTimeout(fetchScreen, 600);
  }
}

async function takeShot() {
  statusEl.textContent = "Taking screenshot…";
  shotImg.src = `/shot?ts=${Date.now()}`;
  shotImg.style.display = "block";
  shotImg.onload = () => { statusEl.textContent = "Screenshot updated"; };
  shotImg.onerror = () => { statusEl.textContent = "Screenshot failed"; };
}

async function loadRuns() {
  const r = await apiFetch('/codex/runs');
  const j = await r.json();
  if (!j.ok) {
    runsListEl.textContent = JSON.stringify(j, null, 2);
    return;
  }
  const items = j.runs || [];
  runsListEl.innerHTML = items.map(x => {
    const dur = x.duration_s == null ? "" : `${x.duration_s}s`;
    const p = (x.prompt || "").slice(0,80).replace(/</g,"&lt;");
    return `<div>• ${x.id} | ${x.status} | ${dur} | ${p}</div>`;
  }).join("");
}

async function runExec() {
  const prompt = document.getElementById('execPrompt').value.trim();
  if (!prompt) return;

  execBtn.disabled = true;
  execStatusEl.textContent = "Starting…";
  execOutEl.textContent = "";

  const r = await apiFetch('/codex/exec', {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ prompt })
  });
  const j = await r.json();
  if (!j.ok) {
    execOutEl.textContent = JSON.stringify(j, null, 2);
    execBtn.disabled = false;
    return;
  }

  const id = j.id;
  execStatusEl.textContent = `Running: ${id}`;

  const poll = async () => {
    const rr = await apiFetch(`/codex/run/${id}`);
    const jj = await rr.json();
    if (!jj.ok) {
      execOutEl.textContent = JSON.stringify(jj, null, 2);
      execBtn.disabled = false;
      return;
    }
    execStatusEl.textContent = `Status: ${jj.status}`;
    execOutEl.textContent = jj.output || "";
    if (jj.status === "running") {
      setTimeout(poll, 1000);
    } else {
      execBtn.disabled = false;
      loadRuns();
    }
  };
  setTimeout(poll, 600);
}

function downloadWsl() {
  const p = document.getElementById('dlPath').value.trim();
  if (!p) return;
  window.open(`/wsl/file?path=${encodeURIComponent(p)}`, "_blank");
}

async function uploadWsl() {
  const f = document.getElementById('upFile').files[0];
  const dest = document.getElementById('upDest').value.trim();
  if (!f) return;

  fileStatusEl.textContent = "Uploading…";
  fileOutEl.textContent = "";

  const fd = new FormData();
  fd.append("file", f);
  if (dest) fd.append("dest", dest);

  const r = await apiFetch("/wsl/upload", { method: "POST", body: fd });
  const j = await r.json();
  if (!j.ok) {
    fileStatusEl.textContent = "Upload failed";
    fileOutEl.textContent = JSON.stringify(j, null, 2);
    return;
  }
  fileStatusEl.textContent = "Uploaded";
  fileOutEl.textContent = `Saved as: ${j.saved_path}`;
}

async function refreshCodexSessions() {
  try {
    const prevSelected = codexSessionSelectEl ? (codexSessionSelectEl.value || "") : "";
    const r = await apiFetch('/codex/sessions');
    const j = await r.json();
    if (!j.ok) {
      codexSessionBadgeEl.textContent = "error";
      codexSessionBadgeEl.className = "badge err";
      return;
    }
    const items = j.sessions || [];
    codexSessionPaneMap.clear();
    codexSessionSelectEl.innerHTML = "";
    for (const s of items) {
      if (s && s.session) codexSessionPaneMap.set(s.session, s.pane_id);
      const opt = document.createElement('option');
      opt.value = s.session;
      opt.textContent = `${s.session} | ${s.state} | ${s.current_command}`;
      codexSessionSelectEl.appendChild(opt);
    }
    if (prevSelected && codexSessionPaneMap.has(prevSelected)) {
      codexSessionSelectEl.value = prevSelected;
    }
    codexSessionBadgeEl.textContent = `${items.length} session${items.length === 1 ? "" : "s"}`;
    codexSessionBadgeEl.className = items.length ? "badge running" : "badge warn";
    if (!items.length) {
      _stopPaneStream(codexStream, codexStreamStatusEl);
      _setConsoleText(codexSessionOutEl, "No codex sessions found. Create one to get started.");
      codexSessionStateEl.textContent = "";
      return;
    }

    const selected = codexSessionSelectEl.value;
    const selItem = items.find(x => x.session === selected) || items[0];
    if (selItem) codexSessionStateEl.textContent = `${selItem.state} | cmd: ${selItem.current_command}`;

    // If streaming is enabled, stream the selected session's pane output.
    codexStream.intervalMs = _readIntValue(codexStreamRateEl, codexStream.intervalMs);
    const paneId = codexSessionPaneMap.get(selected) || (selItem ? selItem.pane_id : "");
    _startPaneStream(codexStream, paneId, codexSessionOutEl, codexStreamStatusEl);

    // Otherwise, fall back to one-shot screen capture.
    if (!codexStream.enabled) await loadCodexSessionScreen();
  } catch (_e) {
    codexSessionBadgeEl.textContent = "error";
    codexSessionBadgeEl.className = "badge err";
  }
}

async function createCodexSession() {
  const name = (codexSessionNameEl.value || "").trim();
  const cwd = (codexSessionCwdEl.value || "").trim();
  const payload = {};
  if (name) payload.name = name;
  if (cwd) payload.cwd = cwd;
  const r = await apiFetch('/codex/session', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload)
  });
  const j = await r.json();
  if (!j.ok) {
    codexSessionStateEl.textContent = j.detail || j.error || "create failed";
    return;
  }
  codexSessionNameEl.value = "";
  codexSessionStateEl.textContent = `Created ${j.session}`;
  await refreshCodexSessions();
}

async function closeCodexSession() {
  const session = codexSessionSelectEl.value;
  if (!session) return;
  const r = await apiFetch(`/codex/session/${encodeURIComponent(session)}`, { method: 'DELETE' });
  const j = await r.json();
  codexSessionStateEl.textContent = j.ok ? `Closed ${session}` : (j.detail || "close failed");
  await refreshCodexSessions();
}

async function sendCodexSessionPrompt() {
  const session = codexSessionSelectEl.value;
  const text = (codexSessionPromptEl.value || "").trim();
  if (!session || !text) return;
  const r = await apiFetch(`/codex/session/${encodeURIComponent(session)}/send`, {
    method: 'POST',
    headers: { 'Content-Type': 'text/plain' },
    body: text
  });
  const j = await r.json();
  if (!j.ok) {
    codexSessionStateEl.textContent = j.detail || "send failed";
    return;
  }
  codexSessionPromptEl.value = "";
  codexSessionStateEl.textContent = "Prompt sent.";
  if (codexStream.enabled) {
    codexStream.intervalMs = _readIntValue(codexStreamRateEl, codexStream.intervalMs);
    const paneId = codexSessionPaneMap.get(session) || "";
    _startPaneStream(codexStream, paneId, codexSessionOutEl, codexStreamStatusEl);
  } else {
    setTimeout(loadCodexSessionScreen, 500);
  }
}

async function sendCtrlCToSession() {
  const session = codexSessionSelectEl.value;
  if (!session) return;
  const r = await apiFetch(`/codex/session/${encodeURIComponent(session)}/interrupt`, { method: 'POST' });
  const j = await r.json();
  codexSessionStateEl.textContent = j.ok ? "Interrupt sent." : (j.detail || "interrupt failed");
  if (codexStream.enabled) {
    codexStream.intervalMs = _readIntValue(codexStreamRateEl, codexStream.intervalMs);
    const paneId = codexSessionPaneMap.get(session) || "";
    _startPaneStream(codexStream, paneId, codexSessionOutEl, codexStreamStatusEl);
  } else {
    setTimeout(loadCodexSessionScreen, 600);
  }
}

async function uploadCodexSessionImage() {
  const session = codexSessionSelectEl.value;
  const file = codexSessionImageEl.files[0];
  if (!session || !file) return;
  const prompt = (codexSessionImagePromptEl.value || "").trim();
  const fd = new FormData();
  fd.append("file", file);
  if (prompt) fd.append("prompt", prompt);
  const r = await apiFetch(`/codex/session/${encodeURIComponent(session)}/image`, {
    method: 'POST',
    body: fd
  });
  const j = await r.json();
  codexSessionStateEl.textContent = j.ok ? `Image sent: ${j.saved_path}` : (j.detail || "image send failed");
  if (j.ok) {
    codexSessionImageEl.value = "";
    codexSessionImagePromptEl.value = "";
    if (codexStream.enabled) {
      codexStream.intervalMs = _readIntValue(codexStreamRateEl, codexStream.intervalMs);
      const paneId = codexSessionPaneMap.get(session) || "";
      _startPaneStream(codexStream, paneId, codexSessionOutEl, codexStreamStatusEl);
    } else {
      setTimeout(loadCodexSessionScreen, 700);
    }
  }
}

async function loadCodexSessionScreen() {
  const session = codexSessionSelectEl.value;
  if (!session) {
    _setConsoleText(codexSessionOutEl, "No active codex session selected.");
    return;
  }
  const r = await apiFetch(`/codex/session/${encodeURIComponent(session)}/screen`);
  const j = await r.json();
  if (!j.ok) {
    _setConsoleText(codexSessionOutEl, JSON.stringify(j, null, 2));
    return;
  }
  codexSessionStateEl.textContent = `${j.state} | cmd: ${j.current_command}`;
  _setConsoleText(codexSessionOutEl, j.text || "(empty)");
}

async function loadDesktopInfo() {
  try {
    const r = await apiFetch('/desktop/info');
    const j = await r.json();
    if (!j.ok) {
      _updateDesktopStatus(j.detail || "desktop unavailable");
      return;
    }
    desktopInfo = j;
    _updateDesktopStatus();
  } catch (_e) {
    _updateDesktopStatus("desktop unavailable");
  }
}

async function desktopDiagnose(reason = "") {
  if (!desktopModeEnabled) {
    _updateDesktopStatus("desktop off");
    return;
  }
  // Throttle repeated error diagnostics (mobile networks can be noisy).
  const now = Date.now();
  if (desktopDiagInFlight) return;
  if (now - desktopLastDiagMs < 3500) return;
  desktopLastDiagMs = now;
  desktopDiagInFlight = true;
  try {
    await checkAuthStatus();
    if (authState && authState.auth_required && !authState.authenticated) {
      _updateDesktopStatus("login required");
      setAuthGate(true, "Login required for desktop stream.");
      return;
    }
    const r = await apiFetch('/desktop/info');
    const j = await r.json();
    if (!j || !j.ok) {
      _updateDesktopStatus((j && (j.detail || j.error)) ? (j.detail || j.error) : "desktop unavailable");
      return;
    }
    desktopInfo = j;
    _updateDesktopStatus(reason ? `ok (${reason})` : "ok");
  } catch (_e) {
    _updateDesktopStatus("desktop unavailable");
  } finally {
    desktopDiagInFlight = false;
  }
}

async function refreshDesktopFrame() {
  if (!deskImgEl) return;
  if (!desktopModeEnabled) {
    desktopFrameInFlight = false;
    const cur = String(deskImgEl.getAttribute('src') || "");
    if (cur !== desktopBlankImage) deskImgEl.setAttribute('src', desktopBlankImage);
    _updateDesktopStatus("desktop off");
    return;
  }
  if (!desktopInfo) loadDesktopInfo();
  // Keep desktop feed always on via server stream, independent of JS timers.
  const target = desktopStreamUrl;
  const current = String(deskImgEl.getAttribute('src') || "");
  if (current !== target) {
    desktopFrameInFlight = true;
    desktopLastReqMs = Date.now();
    desktopReqCount += 1;
    deskImgEl.src = target;
  }
}

function toggleDesktopAuto() {
  desktopAutoEnabled = !desktopAutoEnabled;
  _syncDesktopAutoUI();
  if (desktopAutoEnabled) {
    desktopDiagnose("auto on");
    refreshDesktopFrame();
    _scheduleNextDesktopFrame();
  } else if (desktopAutoTimer) {
    clearTimeout(desktopAutoTimer);
    desktopAutoTimer = null;
    desktopFrameInFlight = false;
  }
}

function _isProbablyMobile() {
  try {
    return window.matchMedia && window.matchMedia('(pointer:coarse)').matches;
  } catch (_e) {
    return false;
  }
}

function _updateDesktopStatus(extra = "") {
  if (!deskStatusEl) return;
  const parts = [];
  parts.push(desktopModeEnabled ? "desktop on" : "desktop off");
  if (desktopInfo && desktopInfo.width && desktopInfo.height) {
    parts.push(`${desktopInfo.width}x${desktopInfo.height}`);
  }
  parts.push(desktopAutoEnabled ? `auto ${desktopAutoMs}ms` : "auto off");
  if (desktopReqCount || desktopOkCount || desktopErrCount) {
    parts.push(`req ${desktopReqCount} ok ${desktopOkCount} err ${desktopErrCount}`);
  }
  if (desktopFrameInFlight) {
    parts.push("pending");
  }
  if (desktopLastFrameMs) {
    try {
      const t = new Date(desktopLastFrameMs).toLocaleTimeString();
      parts.push(`frame ${t}`);
    } catch (_e) {}
  }
  if (extra) parts.push(extra);
  deskStatusEl.textContent = parts.join(" | ");
}

function _applyDesktopModeUI() {
  try {
    if (document && document.body && document.body.classList) {
      document.body.classList.toggle("desktop-on", !!desktopModeEnabled);
      document.body.classList.toggle("desktop-off", !desktopModeEnabled);
    }
  } catch (_e) {}

  if (deskModeBtnEl) {
    deskModeBtnEl.textContent = desktopModeEnabled ? "Control: On" : "Control: Off";
    deskModeBtnEl.classList.add("toggle-btn");
    deskModeBtnEl.classList.toggle("state-on", !!desktopModeEnabled);
    deskModeBtnEl.classList.toggle("state-off", !desktopModeEnabled);
    deskModeBtnEl.classList.toggle("desktop-mode-btn-active", !!desktopModeEnabled);
  }
  if (deskModeBadgeEl) {
    deskModeBadgeEl.textContent = desktopModeEnabled ? desktopLiveBadgeText : "Desktop stream paused";
    deskModeBadgeEl.classList.toggle("running", !!desktopModeEnabled);
    deskModeBadgeEl.classList.toggle("warn", !desktopModeEnabled);
  }
  if (!desktopModeEnabled && deskImgEl) {
    const cur = String(deskImgEl.getAttribute('src') || "");
    if (cur !== desktopBlankImage) deskImgEl.setAttribute('src', desktopBlankImage);
  }
  _updateDesktopStatus();
}

function _desktopStreamUrlFor(fps, level) {
  const qs = new URLSearchParams();
  qs.set("fps", String(fps));
  qs.set("level", String(level));
  return `/desktop/stream?${qs.toString()}`;
}

function _syncDesktopStreamLink() {
  if (deskStreamLinkEl) deskStreamLinkEl.href = desktopStreamUrl;
}

function _setDesktopPerf(profile, refresh = false) {
  const profiles = {
    responsive: { fps: 4, level: 2 },
    balanced: { fps: 3, level: 3 },
    saver: { fps: 2, level: 6 },
  };
  const p = profiles[profile] || profiles.balanced;
  desktopStreamUrl = _desktopStreamUrlFor(p.fps, p.level);
  _syncDesktopStreamLink();
  if (deskPerfEl && deskPerfEl.value !== profile) deskPerfEl.value = profile;
  if (refresh && desktopModeEnabled) {
    desktopFrameInFlight = false;
    refreshDesktopFrame();
  }
}

function _initDesktopPerfFromUrl() {
  try {
    const u = new URL(desktopStreamUrl, window.location.origin);
    const fps = Number(u.searchParams.get("fps") || "3");
    const level = Number(u.searchParams.get("level") || "3");
    if (fps >= 3.8 && level <= 2.5) return _setDesktopPerf("responsive", false);
    if (fps <= 2.2 || level >= 5.5) return _setDesktopPerf("saver", false);
  } catch (_e) {}
  _setDesktopPerf("balanced", false);
}

async function toggleDesktopMode() {
  const next = !desktopModeEnabled;
  try {
    const r = await apiFetch('/desktop/mode', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ enabled: next })
    });
    const j = await r.json();
    if (!j || !j.ok) {
      _updateDesktopStatus((j && (j.detail || j.error)) ? (j.detail || j.error) : "mode change failed");
      return;
    }
    desktopModeEnabled = !!j.enabled;
    _applyDesktopModeUI();
    if (desktopModeEnabled) {
      refreshDesktopFrame();
      desktopDiagnose("mode on");
      if (desktopAutoEnabled) _scheduleNextDesktopFrame();
    } else {
      if (desktopAutoTimer) {
        clearTimeout(desktopAutoTimer);
        desktopAutoTimer = null;
      }
      desktopFrameInFlight = false;
      _updateDesktopStatus("desktop off");
    }
  } catch (_e) {
    _updateDesktopStatus("mode change failed");
  }
}

function _syncDesktopAutoUI() {
  if (deskAutoBtnEl) {
    deskAutoBtnEl.textContent = desktopAutoEnabled ? "Auto: On" : "Auto: Off";
    deskAutoBtnEl.classList.toggle("primary", desktopAutoEnabled);
  }
  _updateDesktopStatus();
}

function _scheduleNextDesktopFrame(delayMs = null) {
  if (!desktopModeEnabled) return;
  if (!desktopAutoEnabled) return;
  if (desktopAutoTimer) clearTimeout(desktopAutoTimer);
  const ms = (delayMs != null ? delayMs : desktopAutoMs);
  desktopAutoTimer = setTimeout(() => {
    if (!desktopModeEnabled) return;
    if (!desktopAutoEnabled) return;
    if (document.visibilityState !== 'visible') {
      _scheduleNextDesktopFrame(ms);
      return;
    }
    // Avoid piling up requests; if a fetch seems stuck for too long, retry.
    const now = Date.now();
    const stuckMs = Math.max(8000, desktopAutoMs * 8);
    if (desktopFrameInFlight && (now - desktopLastReqMs) < stuckMs) {
      _scheduleNextDesktopFrame(ms);
      return;
    }
    if (desktopFrameInFlight && (now - desktopLastReqMs) >= stuckMs) {
      desktopFrameInFlight = false;
      _updateDesktopStatus("stalled; retrying");
    }
    refreshDesktopFrame();
    _scheduleNextDesktopFrame(ms);
  }, Math.max(250, ms));
}

// Turn the screenshot <img> into a self-throttling refresh loop when Auto is on.
// This avoids request pile-ups on slow networks and reduces flakiness on mobile.
if (deskImgEl) {
  deskImgEl.addEventListener('load', () => {
    desktopLastFrameMs = Date.now();
    desktopFrameInFlight = false;
    desktopOkCount += 1;
    _updateDesktopStatus();
  });
  deskImgEl.addEventListener('error', () => {
    desktopFrameInFlight = false;
    desktopErrCount += 1;
    _updateDesktopStatus("stream error");
    desktopDiagnose("stream error");
    _scheduleNextDesktopFrame(Math.min(4000, desktopAutoMs * 2));
  });
}

if (deskRateEl) {
  deskRateEl.addEventListener('change', () => {
    const next = Number(deskRateEl.value || "1200");
    if (!Number.isFinite(next) || next <= 0) return;
    desktopAutoMs = next;
    _syncDesktopAutoUI();
    if (desktopAutoEnabled) _scheduleNextDesktopFrame();
  });
  try {
    const initial = Number(deskRateEl.value || "1200");
    if (Number.isFinite(initial) && initial > 0) desktopAutoMs = initial;
  } catch (_e) {}
}

_initDesktopPerfFromUrl();
if (deskPerfEl) {
  deskPerfEl.addEventListener('change', () => {
    _setDesktopPerf(deskPerfEl.value || "balanced", true);
  });
}
_syncDesktopStreamLink();

_syncDesktopAutoUI();
_applyDesktopModeUI();
bindDesktopAutoButton();

function pointToDesktopXY(clientX, clientY) {
  if (!desktopInfo) return null;
  const rect = deskImgEl.getBoundingClientRect();
  if (!rect.width || !rect.height) return null;
  const relX = Math.max(0, Math.min(rect.width - 1, clientX - rect.left));
  const relY = Math.max(0, Math.min(rect.height - 1, clientY - rect.top));
  const x = Math.round((relX / rect.width) * desktopInfo.width);
  const y = Math.round((relY / rect.height) * desktopInfo.height);
  return { x, y };
}

deskImgEl.addEventListener('click', async (e) => {
  const p = pointToDesktopXY(e.clientX, e.clientY);
  if (!p) return;
  lastDesktopPoint = p;
  await desktopClick('left', false, p);
  refreshDesktopFrame();
});

deskImgEl.addEventListener('touchend', async (e) => {
  const t = e.changedTouches && e.changedTouches[0];
  if (!t) return;
  const p = pointToDesktopXY(t.clientX, t.clientY);
  if (!p) return;
  lastDesktopPoint = p;
  await desktopClick('left', false, p);
  refreshDesktopFrame();
});

async function desktopClick(button = 'left', double = false, explicitPoint = null) {
  if (!desktopModeEnabled) {
    _updateDesktopStatus("desktop off");
    return;
  }
  const p = explicitPoint || lastDesktopPoint;
  const payload = { button, double };
  if (p) {
    payload.x = p.x;
    payload.y = p.y;
  }
  const r = await apiFetch('/desktop/input/click', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload)
  });
  const j = await r.json();
  deskStatusEl.textContent = j.ok ? `click ${button}` : (j.detail || "click failed");
  if (j.ok) refreshDesktopFrame();
}

async function desktopScroll(delta) {
  if (!desktopModeEnabled) {
    _updateDesktopStatus("desktop off");
    return;
  }
  const r = await apiFetch('/desktop/input/scroll', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ delta })
  });
  const j = await r.json();
  deskStatusEl.textContent = j.ok ? `scroll ${delta}` : (j.detail || "scroll failed");
  if (j.ok) refreshDesktopFrame();
}

async function desktopSendKey() {
  if (!desktopModeEnabled) {
    _updateDesktopStatus("desktop off");
    return;
  }
  const key = deskKeyEl.value;
  const r = await apiFetch('/desktop/input/key', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ key })
  });
  const j = await r.json();
  deskStatusEl.textContent = j.ok ? `sent ${key}` : (j.detail || "key failed");
  if (j.ok) refreshDesktopFrame();
}

function _queueLive(fn) {
  // Keep keystrokes ordered even if network responses return out of order.
  liveKeyQueue = liveKeyQueue.then(fn).catch((_e) => {});
}

async function desktopQuickKey(key) {
  if (!desktopModeEnabled) {
    _updateDesktopStatus("desktop off");
    return;
  }
  const r = await apiFetch('/desktop/input/key', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ key })
  });
  const j = await r.json();
  if (!j.ok) deskStatusEl.textContent = j.detail || "key failed";
}

async function desktopEdit(backspaceCount, text) {
  if (!desktopModeEnabled) {
    _updateDesktopStatus("desktop off");
    return;
  }
  let backspace = Math.max(0, Number(backspaceCount || 0));
  let t = String(text || "");
  if (!backspace && !t) return;

  const BS_CHUNK = 200;   // server max
  const TXT_CHUNK = 400;  // keep under server max (500)

  async function sendOnce(bs, chunk) {
    const r = await apiFetch('/desktop/input/edit', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ backspace: bs, text: chunk })
    });
    let j = null;
    try { j = await r.json(); } catch (_e) { j = { ok: false, detail: `Bad response (${r.status})` }; }
    if (!r.ok || !j || !j.ok) {
      deskStatusEl.textContent = (j && j.detail) ? j.detail : "edit failed";
      throw new Error("edit_failed");
    }
  }

  while (backspace > 0) {
    const bs = Math.min(backspace, BS_CHUNK);
    backspace -= bs;
    await sendOnce(bs, "");
  }
  while (t.length > 0) {
    const chunk = t.slice(0, TXT_CHUNK);
    t = t.slice(chunk.length);
    await sendOnce(0, chunk);
  }
}

function resetLiveBuffer() {
  if (!deskLiveInputEl) return;
  liveLastValue = "";
  deskLiveInputEl.value = "";
  try { deskLiveInputEl.focus(); } catch (_e) {}
}

async function pasteToLive() {
  if (!deskLiveInputEl) return;

  // Clipboard API usually requires HTTPS; on HTTP we fall back to a prompt.
  let text = "";
  try {
    if (navigator.clipboard && navigator.clipboard.readText) {
      text = await navigator.clipboard.readText();
    }
  } catch (_e) {}
  if (!text) {
    text = window.prompt("Paste text to send to desktop:") || "";
  }

  // Normalize newlines for consistency.
  text = String(text || "").replace(/\\r\\n/g, "\\n");
  if (!text) return;

  // Keep local mirror in sync with what we send.
  liveLastValue = String(liveLastValue || "") + text;
  if (liveLastValue.length > 4000) liveLastValue = liveLastValue.slice(-4000);
  deskLiveInputEl.value = liveLastValue;
  _forceLiveCaretEnd();
  _queueLive(() => desktopEdit(0, text));
}

function _forceLiveCaretEnd() {
  if (!deskLiveInputEl) return;
  try {
    const n = (deskLiveInputEl.value || "").length;
    deskLiveInputEl.setSelectionRange(n, n);
  } catch (_e) {}
}

function _computeTailEdit(prev, next) {
  if (next === prev) return { backspace: 0, text: "" };
  if (next.startsWith(prev)) return { backspace: 0, text: next.slice(prev.length) };
  if (prev.startsWith(next)) return { backspace: prev.length - next.length, text: "" };
  let i = 0;
  while (i < prev.length && i < next.length && prev[i] === next[i]) i++;
  return { backspace: prev.length - i, text: next.slice(i) };
}

function _bindLiveKeyboard() {
  if (!deskLiveInputEl) return;

  liveLastValue = String(deskLiveInputEl.value || "");
  _forceLiveCaretEnd();

  deskLiveInputEl.addEventListener('focus', _forceLiveCaretEnd);
  deskLiveInputEl.addEventListener('click', _forceLiveCaretEnd);
  deskLiveInputEl.addEventListener('select', _forceLiveCaretEnd);

  deskLiveInputEl.addEventListener('keydown', (e) => {
    if (!e) return;
    if (e.ctrlKey || e.metaKey || e.altKey) return;
    if (e.key === "Backspace") {
      e.preventDefault();
      if (liveLastValue) liveLastValue = liveLastValue.slice(0, -1);
      deskLiveInputEl.value = liveLastValue;
      _forceLiveCaretEnd();
      _queueLive(() => desktopEdit(1, ""));
      return;
    }
    if (e.key === "Enter") {
      e.preventDefault();
      liveLastValue = String(liveLastValue || "") + "\\n";
      if (liveLastValue.length > 4000) liveLastValue = liveLastValue.slice(-4000);
      deskLiveInputEl.value = liveLastValue;
      _forceLiveCaretEnd();
      _queueLive(() => desktopQuickKey("enter"));
      return;
    }
  });

  deskLiveInputEl.addEventListener('beforeinput', (e) => {
    if (!e) return;
    const t = String(e.inputType || "");
    const data = (typeof e.data === "string") ? e.data : "";
    if (t === "insertLineBreak") {
      e.preventDefault();
      liveLastValue = String(liveLastValue || "") + "\\n";
      if (liveLastValue.length > 4000) liveLastValue = liveLastValue.slice(-4000);
      deskLiveInputEl.value = liveLastValue;
      _forceLiveCaretEnd();
      _queueLive(() => desktopQuickKey("enter"));
      return;
    }
    if (t === "deleteContentBackward") {
      e.preventDefault();
      if (liveLastValue) liveLastValue = liveLastValue.slice(0, -1);
      deskLiveInputEl.value = liveLastValue;
      _forceLiveCaretEnd();
      _queueLive(() => desktopEdit(1, ""));
      return;
    }
    if (t.startsWith("insert") && data) {
      e.preventDefault();
      const add = String(data || "").replace(/\\r\\n/g, "\\n");
      if (!add) return;
      liveLastValue = String(liveLastValue || "") + add;
      if (liveLastValue.length > 4000) liveLastValue = liveLastValue.slice(-4000);
      deskLiveInputEl.value = liveLastValue;
      _forceLiveCaretEnd();
      _queueLive(() => desktopEdit(0, add));
    }
  });

  deskLiveInputEl.addEventListener('input', (e) => {
    if (e && e.isComposing) return;
    const next = String(deskLiveInputEl.value || "");
    if (next === liveLastValue) {
      _forceLiveCaretEnd();
      return;
    }
    const edit = _computeTailEdit(liveLastValue, next);
    liveLastValue = next;
    if (liveLastValue.length > 4000) liveLastValue = liveLastValue.slice(-4000);
    deskLiveInputEl.value = liveLastValue;
    _forceLiveCaretEnd();
    if (!edit.backspace && !edit.text) return;
    _queueLive(() => desktopEdit(edit.backspace, edit.text));
  });
}

async function bootstrapAll() {
  await Promise.allSettled([
    refreshPanes(),
    loadRuns(),
    refreshCodexSessions(),
    loadDesktopInfo(),
    _fetchNetInfo(),
  ]);
  refreshDesktopFrame();
}

setInterval(() => {
  if (document.visibilityState !== 'visible') return;
  // If SSE streaming is on and connected, avoid extra polling load.
  if (tmuxStream && tmuxStream.enabled && tmuxStream.es) return;
  fetchScreen();
}, 2500);

setInterval(() => {
  if (document.visibilityState === 'visible') refreshTmuxHealth();
}, 10000);

setInterval(() => {
  if (document.visibilityState === 'visible') refreshCodexSessions();
}, 3000);

autoLoginFromHash().finally(() => {
  _bindLiveKeyboard();
  checkAuthStatus().then(() => {
    // --- Stream UI init (tmux + codex) ---
    tmuxStream.intervalMs = _readIntValue(tmuxStreamRateEl, tmuxStream.intervalMs);
    codexStream.intervalMs = _readIntValue(codexStreamRateEl, codexStream.intervalMs);
    _syncStreamBtn(tmuxStreamBtnEl, tmuxStream.enabled);
    _syncStreamBtn(codexStreamBtnEl, codexStream.enabled);
    _setStreamStatus(tmuxStreamStatusEl, tmuxStream.enabled ? "stream: starting…" : "stream: off");
    _setStreamStatus(codexStreamStatusEl, codexStream.enabled ? "stream: starting…" : "stream: off");

    if (tmuxStreamRateEl) {
      tmuxStreamRateEl.addEventListener('change', () => {
        tmuxStream.intervalMs = _readIntValue(tmuxStreamRateEl, tmuxStream.intervalMs);
        if (tmuxStream.enabled) _startPaneStream(tmuxStream, paneSel.value, outEl, tmuxStreamStatusEl);
      });
    }
    if (codexStreamRateEl) {
      codexStreamRateEl.addEventListener('change', () => {
        codexStream.intervalMs = _readIntValue(codexStreamRateEl, codexStream.intervalMs);
        if (!codexStream.enabled) return;
        const session = codexSessionSelectEl ? (codexSessionSelectEl.value || "") : "";
        const paneId = session ? (codexSessionPaneMap.get(session) || "") : "";
        _startPaneStream(codexStream, paneId, codexSessionOutEl, codexStreamStatusEl);
      });
    }

    bindDesktopAutoButton();

    if (paneSel) {
      paneSel.addEventListener('change', () => {
        if (tmuxStream.enabled) _startPaneStream(tmuxStream, paneSel.value, outEl, tmuxStreamStatusEl);
      });
    }
    if (codexSessionSelectEl) {
      codexSessionSelectEl.addEventListener('change', () => {
        const session = codexSessionSelectEl.value;
        if (codexStream.enabled) {
          const paneId = codexSessionPaneMap.get(session) || "";
          _startPaneStream(codexStream, paneId, codexSessionOutEl, codexStreamStatusEl);
        } else {
          loadCodexSessionScreen();
        }
      });
    }

    document.addEventListener('visibilitychange', () => {
      // EventSource keeps running in the background; pause when hidden to reduce load.
      if (document.visibilityState !== 'visible') {
        _stopPaneStream(tmuxStream, tmuxStreamStatusEl);
        _stopPaneStream(codexStream, codexStreamStatusEl);
        return;
      }
      if (tmuxStream.enabled) _startPaneStream(tmuxStream, paneSel.value, outEl, tmuxStreamStatusEl);
      if (codexStream.enabled) {
        const session = codexSessionSelectEl ? (codexSessionSelectEl.value || "") : "";
        const paneId = session ? (codexSessionPaneMap.get(session) || "") : "";
        _startPaneStream(codexStream, paneId, codexSessionOutEl, codexStreamStatusEl);
      }
      // Desktop <img> can be stale after bfcache/tab switching; refresh once on resume.
      try { refreshDesktopFrame(); } catch (_e) {}
      if (desktopAutoEnabled) _scheduleNextDesktopFrame();
    });

    try {
      document.documentElement.classList.remove('js-basic-mode');
      document.documentElement.classList.add('js-ok-mode');
      const jsBadge = document.getElementById('jsBadge');
      if (jsBadge) jsBadge.textContent = "JS: ok";
    } catch (_e) {}

    bootstrapAll();
    // Mobile defaults: enable auto-refresh after auth so the stream feels "live"
    // without requiring an extra tap.
    if (desktopModeEnabled && _isProbablyMobile() && authState && (!authState.auth_required || authState.authenticated)) {
      desktopAutoEnabled = true;
      _syncDesktopAutoUI();
      refreshDesktopFrame();
      _scheduleNextDesktopFrame();
    }
  });
});
</script>
</body>
</html>
    """
    content = (
        html.replace("__CODEX_DISTRO__", distro)
        .replace("__CODEX_WORKDIR__", workdir)
        .replace("__CODEX_ROOT__", root)
        .replace("__DESKTOP_MODE_CLASS__", desktop_mode_class)
        .replace("__COMPACT_MODE_CLASS__", compact_mode_class)
        .replace("__COMPACT_TOGGLE_HREF__", compact_toggle_href)
        .replace("__COMPACT_TOGGLE_LABEL__", compact_toggle_label)
        .replace("__COMPACT_PILL__", compact_pill)
        .replace("__DESKTOP_MODE_ENABLED__", "true" if desktop_enabled else "false")
        .replace("__DESKTOP_STREAM_URL__", desktop_stream_url)
        .replace("__DESKTOP_STREAM_SRC__", desktop_stream_src)
        .replace("__DESKTOP_LIVE_BADGE__", desktop_live_badge)
        .replace("__DESKTOP_MODE_BADGE_CLASS__", desktop_mode_badge_class)
        .replace("__DESKTOP_MODE_BADGE__", desktop_mode_badge)
        .replace("__DESKTOP_TOGGLE_LABEL__", desktop_toggle_label)
        .replace("__BLANK_IMAGE_DATA_URL__", BLANK_IMAGE_DATA_URL)
        .replace("__DESKTOP_NATIVE_W__", str(desktop_native_w))
        .replace("__DESKTOP_NATIVE_H__", str(desktop_native_h))
        .replace("__DESKTOP_TAP_W__", str(desktop_tap_w))
        .replace("__DESKTOP_TAP_H__", str(desktop_tap_h))
    )
    # Prevent sticky/cached UIs on mobile while we iterate quickly and fix auth issues.
    return HTMLResponse(content=content, headers={"Cache-Control": "no-store"})

# -------------------------
# Auth endpoints
# -------------------------
@app.get("/auth/status")
def auth_status(request: Request):
    token = _auth_token_from_request(request)
    authenticated = _is_valid_auth_token(token)
    return {
        "ok": True,
        "auth_required": CODEX_AUTH_REQUIRED,
        "authenticated": authenticated,
    }

@app.post("/auth/login")
def auth_login(request: Request, payload: Dict[str, Any] = Body(...)):
    token = (payload.get("token") or "").strip()
    if not _is_valid_auth_token(token):
        return {"ok": False, "error": "unauthorized", "detail": "Invalid token."}
    resp = JSONResponse({"ok": True, "auth_required": CODEX_AUTH_REQUIRED})
    resp.set_cookie(
        key=CODEX_AUTH_COOKIE,
        value=token,
        httponly=True,
        secure=_cookie_secure_for_request(request),
        samesite="lax",
        max_age=60 * 60 * 12,
    )
    return resp


@app.post("/auth/bootstrap/local")
def auth_bootstrap_local(request: Request):
    """
    Local-host bootstrap for laptop-first usage.

    Security model:
    - Only allowed when TCP client address is loopback.
    - Only allowed when request Host is localhost/127.0.0.1.
    - If Origin/Referer are present, they must also be localhost.
    - Never exposes token in response body; only sets auth cookie.
    """
    if not CODEX_AUTH_REQUIRED:
        return {"ok": True, "auth_required": False, "method": "local_bootstrap"}

    client_host = ""
    try:
        client = getattr(request, "client", None)
        client_host = str(getattr(client, "host", "") or "").strip()
    except Exception:
        client_host = ""
    host = _host_from_host_header(request.headers.get("host") or "")
    origin_host = _host_from_url_header(request.headers.get("origin") or "")
    referer_host = _host_from_url_header(request.headers.get("referer") or "")
    if not _is_loopback_ip(client_host):
        return {
            "ok": False,
            "error": "forbidden",
            "detail": "Local bootstrap is only allowed from loopback client addresses.",
        }
    if not _is_localhost_label(host):
        return {
            "ok": False,
            "error": "forbidden",
            "detail": "Local bootstrap is only allowed from localhost hostnames.",
        }
    if origin_host and not _is_localhost_label(origin_host):
        return {"ok": False, "error": "forbidden", "detail": "Origin must be localhost for local bootstrap."}
    if referer_host and not _is_localhost_label(referer_host):
        return {"ok": False, "error": "forbidden", "detail": "Referer must be localhost for local bootstrap."}

    resp = JSONResponse({"ok": True, "auth_required": CODEX_AUTH_REQUIRED, "method": "local_bootstrap"})
    resp.set_cookie(
        key=CODEX_AUTH_COOKIE,
        value=CODEX_AUTH_TOKEN,
        httponly=True,
        secure=_cookie_secure_for_request(request),
        samesite="lax",
        max_age=60 * 60 * 12,
    )
    return resp


@app.post("/auth/logout")
def auth_logout():
    resp = JSONResponse({"ok": True})
    resp.delete_cookie(CODEX_AUTH_COOKIE)
    return resp

def _safe_next_path(next_path: str) -> str:
    p = (next_path or "").strip()
    if not p.startswith("/"):
        return "/"
    if p.startswith("//"):
        return "/"
    return p

@app.get("/legacy/auth")
def legacy_auth_page():
    return HTMLResponse(
        content="""
<!doctype html>
<html>
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>Fallback Login</title>
    <style>
      body { margin: 0; padding: 16px; font-family: system-ui, -apple-system, Segoe UI, Roboto, sans-serif; background: #f8fafc; color: #0f172a; }
      .card { background: #fff; border: 1px solid #dfe4ea; border-radius: 12px; padding: 14px; }
      .field { display: flex; flex-direction: column; gap: 6px; margin: 10px 0; }
      input { width: 100%; border: 1px solid #dfe4ea; border-radius: 10px; padding: 10px 12px; font: inherit; }
      button { border-radius: 10px; border: 1px solid #0b4f6c; background: #0b4f6c; color: #fff; padding: 10px 14px; font: inherit; font-weight: 600; }
      a { display: inline-block; margin-top: 12px; color: #0b4f6c; }
    </style>
  </head>
  <body>
    <div class="card">
      <h2 style="margin:0 0 8px;">Fallback Login (No-JS)</h2>
      <form method="post" action="/legacy/auth/login">
        <div class="field">
          <label for="token">Access token</label>
          <input id="token" name="token" type="password" autocomplete="current-password" required />
        </div>
        <input type="hidden" name="next" value="/legacy" />
        <button type="submit">Login</button>
      </form>
      <a href="/legacy">Back to fallback controls</a>
    </div>
  </body>
</html>
        """.strip(),
        headers={"Cache-Control": "no-store"},
    )

@app.post("/legacy/auth/login")
def legacy_auth_login(request: Request, token: str = Form(""), next: str = Form("/legacy")):
    t = (token or "").strip()
    if not _is_valid_auth_token(t):
        return _legacy_result_page(
            "Fallback Login",
            {"ok": False, "error": "unauthorized", "detail": "Invalid token."},
            401,
        )
    resp = Response(status_code=303, headers={"Location": _safe_next_path(next)})
    resp.set_cookie(
        key=CODEX_AUTH_COOKIE,
        value=t if CODEX_AUTH_REQUIRED else "",
        httponly=True,
        secure=_cookie_secure_for_request(request),
        samesite="lax",
        max_age=60 * 60 * 12,
    )
    return resp

@app.post("/legacy/auth/logout")
def legacy_auth_logout(next: str = Form("/legacy")):
    resp = Response(status_code=303, headers={"Location": _safe_next_path(next)})
    resp.delete_cookie(CODEX_AUTH_COOKIE)
    return resp

# -------------------------
# Pairing + QR endpoints
# -------------------------
def _power_status_payload() -> Dict[str, Any]:
    mac_info = _wake_mac_info()
    relay = _wake_relay_health()
    local_wake = _wake_local_capabilities()
    wake_command = str(relay.get("wake_command") or CODEX_WAKE_TELEGRAM_COMMAND)
    wake_readiness = str(local_wake.get("wake_readiness") or "partial")
    wake_warning = str(local_wake.get("wake_warning") or "").strip()
    if wake_readiness == "ready" and not bool(relay.get("configured")):
        wake_readiness = "partial"
        wake_warning = _merge_wake_warning(
            wake_warning,
            "Local wake support looks ready, but the wake relay is not configured.",
        )
    elif wake_readiness == "ready" and not bool(relay.get("reachable")):
        wake_readiness = "partial"
        wake_warning = _merge_wake_warning(
            wake_warning,
            "Local wake support looks ready, but the wake relay is currently unreachable.",
        )
    elif wake_readiness == "partial" and not bool(relay.get("configured")):
        wake_warning = _merge_wake_warning(
            wake_warning,
            "The wake relay is not configured yet.",
        )
    return {
        "ok": True,
        "online": True,
        "actions": ["lock", "sleep", "hibernate", "restart", "shutdown"] if os.name == "nt" else [],
        "confirm_required_actions": ["sleep", "hibernate", "restart", "shutdown"],
        "wake_surface": str(relay.get("wake_surface") or "telegram"),
        "wake_command": wake_command,
        "wake_instruction": f"{wake_command} laptop",
        "wake_relay_configured": bool(relay.get("configured")),
        "relay_reachable": bool(relay.get("reachable")),
        "relay_detail": str(relay.get("detail") or "").strip(),
        "wake_readiness": wake_readiness,
        "wake_warning": wake_warning,
        "wake_transport_hint": str(local_wake.get("wake_transport_hint") or "unknown"),
        "primary_mac": str(mac_info.get("primary_mac") or ""),
        "wake_candidate_macs": list(mac_info.get("wake_candidate_macs") or []),
        "wake_supported": bool(mac_info.get("wake_supported")),
    }


@app.get("/net/info")
def net_info():
    # Helper for UI to suggest reachable base URLs and private routes.
    return _get_cached_net_info()


@app.get("/codex/runtime/status")
def codex_runtime_status():
    status = _wsl_runtime_status_payload()
    return {
        "ok": True,
        "state": status.get("state"),
        "detail": status.get("detail"),
        "distro": status.get("distro"),
        "can_start": bool(status.get("can_start")),
        "can_stop": bool(status.get("can_stop")),
    }


@app.post("/codex/runtime/start")
def codex_runtime_start():
    status = _start_wsl_runtime()
    return {
        "ok": bool(status.get("ok")),
        "state": status.get("state"),
        "detail": status.get("detail"),
        "distro": status.get("distro"),
        "can_start": bool(status.get("can_start")),
        "can_stop": bool(status.get("can_stop")),
    }


@app.post("/codex/runtime/stop")
def codex_runtime_stop():
    status = _stop_wsl_runtime()
    return {
        "ok": bool(status.get("ok")),
        "state": status.get("state"),
        "detail": status.get("detail"),
        "distro": status.get("distro"),
        "can_start": bool(status.get("can_start")),
        "can_stop": bool(status.get("can_stop")),
    }


@app.post("/auth/pair/create")
def auth_pair_create(request: Request):
    if not CODEX_AUTH_REQUIRED:
        return {"ok": True, "code": "", "expires_in": 0}
    token = _auth_token_from_request(request)
    if not _is_valid_auth_token(token):
        return {"ok": False, "error": "unauthorized", "detail": "Login required to generate pairing code."}
    data = pairing_create_code()
    return {"ok": True, **data}


@app.post("/auth/pair/exchange")
def auth_pair_exchange(request: Request, payload: Dict[str, Any] = Body(...)):
    if not CODEX_AUTH_REQUIRED:
        return {"ok": True, "auth_required": False}

    code = (payload.get("code") or payload.get("pair") or "").strip()
    if not pairing_consume_code(code):
        return {"ok": False, "error": "unauthorized", "detail": "Invalid or expired pairing code."}

    response_payload: Dict[str, Any] = {"ok": True, "auth_required": CODEX_AUTH_REQUIRED}
    if bool(payload.get("issue_device_token")):
        response_payload.update(
            _issue_trusted_device(
                name=str(payload.get("device_name") or payload.get("device_label") or "").strip(),
                platform=str(payload.get("device_platform") or "android").strip(),
                current_origin=str(getattr(request.url, "scheme", "http") or "http")
                + "://"
                + str(getattr(request.url, "hostname", "") or "").strip()
                + (f":{int(getattr(request.url, 'port', 0) or 0)}" if int(getattr(request.url, "port", 0) or 0) else ""),
            ),
        )

    resp = JSONResponse(response_payload)
    # Exchange does not reveal CODEX_AUTH_TOKEN to the browser; it only sets the auth cookie.
    resp.set_cookie(
        key=CODEX_AUTH_COOKIE,
        value=CODEX_AUTH_TOKEN,
        httponly=True,
        secure=_cookie_secure_for_request(request),
        samesite="lax",
        max_age=60 * 60 * 12,
    )
    return resp


@app.post("/auth/device/resume")
def auth_device_resume(request: Request, payload: Dict[str, Any] = Body(...)):
    if not CODEX_AUTH_REQUIRED:
        return {"ok": True, "auth_required": False}

    device_id = str(payload.get("device_id") or "").strip()
    device_token = str(payload.get("device_token") or "").strip()
    current_origin = (
        str(getattr(request.url, "scheme", "http") or "http")
        + "://"
        + str(getattr(request.url, "hostname", "") or "").strip()
        + (f":{int(getattr(request.url, 'port', 0) or 0)}" if int(getattr(request.url, "port", 0) or 0) else "")
    )
    trusted = _resume_trusted_device(device_id, device_token, current_origin=current_origin)
    if not trusted:
        return {"ok": False, "error": "unauthorized", "detail": "Trusted device token is invalid."}

    resp = JSONResponse(
        {
            "ok": True,
            "auth_required": CODEX_AUTH_REQUIRED,
            "trusted_device": True,
            "device_id": str(trusted.get("id") or ""),
            "device_name": str(trusted.get("name") or ""),
            "device_platform": str(trusted.get("platform") or ""),
        }
    )
    resp.set_cookie(
        key=CODEX_AUTH_COOKIE,
        value=CODEX_AUTH_TOKEN,
        httponly=True,
        secure=_cookie_secure_for_request(request),
        samesite="lax",
        max_age=60 * 60 * 24 * 30,
    )
    return resp


@app.post("/auth/device/refresh")
def auth_device_refresh(request: Request, payload: Dict[str, Any] = Body(...)):
    if not CODEX_AUTH_REQUIRED:
        return {"ok": True, "auth_required": False}

    _require_authenticated_request(request)
    current_origin = (
        str(getattr(request.url, "scheme", "http") or "http")
        + "://"
        + str(getattr(request.url, "hostname", "") or "").strip()
        + (f":{int(getattr(request.url, 'port', 0) or 0)}" if int(getattr(request.url, "port", 0) or 0) else "")
    )
    refreshed = _reissue_trusted_device(
        device_id=str(payload.get("device_id") or "").strip(),
        name=str(payload.get("device_name") or payload.get("device_label") or "").strip(),
        platform=str(payload.get("device_platform") or "android").strip(),
        current_origin=current_origin,
    )
    resp = JSONResponse(
        {
            "ok": True,
            "auth_required": CODEX_AUTH_REQUIRED,
            **refreshed,
        }
    )
    resp.set_cookie(
        key=CODEX_AUTH_COOKIE,
        value=CODEX_AUTH_TOKEN,
        httponly=True,
        secure=_cookie_secure_for_request(request),
        samesite="lax",
        max_age=60 * 60 * 24 * 30,
    )
    return resp


@app.get("/auth/pair/consume")
def auth_pair_consume(request: Request, code: str = "", pair: str = "", direct: str = ""):
    """
    Pairing endpoint designed for QR scanning.

    Why:
    - Some scanners/in-app browsers drop URL fragments (anything after '#').
    - The previous flow used `/#pair=...` which required JS to run.
    - This endpoint lets the QR link hit the server, set the auth cookie, and redirect.

    Security:
    - Codes are one-time + short-lived (default ~90s).
    - Endpoint is public but only accepts valid pairing codes.
    """
    target_url = _mobile_ui_target_url(request)
    target_href = html_std.escape(target_url, quote=True)
    target_url_js = json.dumps(target_url)

    if not CODEX_AUTH_REQUIRED:
        return Response(status_code=303, headers={"Location": target_url})

    c = (code or pair or "").strip()
    if not c:
        return HTMLResponse(
            content="""
<!doctype html>
<html>
  <head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>Pairing Missing Code</title>
  </head>
  <body style="font-family: system-ui, -apple-system, Segoe UI, Roboto, sans-serif; padding: 18px;">
    <h2>Pairing Link Missing Code</h2>
    <p>This pairing link is incomplete. Generate a new QR code from an already-authenticated device.</p>
    <p><a href="{target_href}">Open mobile app</a></p>
  </body>
</html>
            """.strip(),
            status_code=400,
            headers={"Cache-Control": "no-store"},
        )

    # QR scanners often prefetch GET links (or open previews) before launching the real browser.
    # To avoid burning one-time codes early, the default GET serves a small HTML page that
    # exchanges the code via JS only when the page actually renders.
    is_direct = str(direct or "").strip().lower() in {"1", "true", "yes", "on"}
    if not is_direct:
        code_js = json.dumps(c)
        direct_href = f"/auth/pair/consume?code={quote(c)}&direct=1"
        return HTMLResponse(
            content=f"""
<!doctype html>
<html>
  <head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>Pairing Phone</title>
    <style>
      body {{
        font-family: system-ui, -apple-system, Segoe UI, Roboto, sans-serif;
        padding: 18px;
        line-height: 1.35;
      }}
      .card {{
        max-width: 520px;
        border: 1px solid #dbe3ee;
        border-radius: 12px;
        padding: 14px 16px;
        background: #fff;
      }}
      .muted {{ color: #475569; }}
      .ok {{ color: #166534; }}
      .warn {{ color: #92400e; }}
      .err {{ color: #b91c1c; }}
      .btn {{
        display: inline-block;
        padding: 10px 14px;
        border-radius: 8px;
        border: 1px solid #cbd5e1;
        background: #0f766e;
        color: #fff;
        text-decoration: none;
        font-weight: 600;
      }}
      .btn.alt {{
        background: #fff;
        color: #0f172a;
      }}
      .row {{ display: flex; gap: 10px; flex-wrap: wrap; margin-top: 12px; }}
    </style>
  </head>
  <body>
    <div class="card">
      <h2 style="margin: 0 0 8px 0;">Pairing This Phone</h2>
      <p id="status" class="muted" style="margin: 0;">Finishing secure sign-in…</p>
      <div class="row">
        <a class="btn alt" href="{target_href}">Open mobile app</a>
        <a class="btn alt" href="{html_std.escape(direct_href, quote=True)}">Try direct pairing</a>
      </div>
      <p class="muted" style="margin-top: 12px;">If this page stays blank in a scanner preview, open the link in your browser app (Chrome/Safari).</p>
    </div>
    <script>
      (async () => {{
        const statusEl = document.getElementById("status");
        try {{
          const r = await fetch("/auth/pair/exchange", {{
            method: "POST",
            headers: {{ "Content-Type": "application/json" }},
            credentials: "same-origin",
            body: JSON.stringify({{ code: {code_js} }})
          }});
          let j = null;
          try {{ j = await r.json(); }} catch (_e) {{}}
          if (j && j.ok) {{
            statusEl.className = "ok";
            statusEl.textContent = "Paired successfully. Opening mobile app…";
            window.location.replace({target_url_js});
            return;
          }}
          statusEl.className = "err";
          statusEl.textContent = (j && (j.detail || j.error)) ? String(j.detail || j.error) : "Pairing failed or expired. Generate a new QR code.";
        }} catch (_e) {{
          statusEl.className = "err";
          statusEl.textContent = "Could not contact the controller. Verify Tailscale is connected, then try again.";
        }}
      }})();
    </script>
  </body>
</html>
            """.strip(),
            status_code=200,
            headers={"Cache-Control": "no-store"},
        )

    if not pairing_consume_code(c):
        return HTMLResponse(
            content="""
<!doctype html>
<html>
  <head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>Pairing Failed</title>
  </head>
  <body style="font-family: system-ui, -apple-system, Segoe UI, Roboto, sans-serif; padding: 18px;">
    <h2>Pairing Failed</h2>
    <p>This pairing code is invalid or expired. Generate a new QR code from an already-authenticated device.</p>
    <p><a href="{target_href}">Open mobile app</a></p>
  </body>
</html>
            """.strip(),
            status_code=401,
            headers={"Cache-Control": "no-store"},
        )

    # Some camera preview browsers can render a blank page on bare redirects.
    # The default GET path above serves HTML + JS and avoids consuming the code early.
    # `direct=1` keeps this no-JS redirect path as a fallback.
    resp = Response(status_code=303, headers={"Location": target_url})
    resp.set_cookie(
        key=CODEX_AUTH_COOKIE,
        value=CODEX_AUTH_TOKEN,
        httponly=True,
        secure=_cookie_secure_for_request(request),
        samesite="lax",
        max_age=60 * 60 * 12,
    )
    resp.headers["Cache-Control"] = "no-store"
    return resp


@app.get("/auth/pair/qr.svg")
def auth_pair_qr_svg(data: str = ""):
    data = (data or "").strip()
    if not data:
        raise HTTPException(status_code=400, detail="Missing data.")
    if len(data) > 2048:
        raise HTTPException(status_code=413, detail="QR data too long.")

    try:
        import segno  # lazy import so unit tests don't need this dependency
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"QR generator not installed (segno): {e}")

    qr = segno.make(data, error="m")
    buf = io.BytesIO()
    qr.save(buf, kind="svg", scale=6, border=2)
    return Response(
        content=buf.getvalue(),
        media_type="image/svg+xml",
        headers={"Cache-Control": "no-store"},
    )


@app.get("/auth/pair/qr.png")
def auth_pair_qr_png(data: str = ""):
    """
    PNG variant of the pairing QR generator.
    Useful for native launchers (WinForms) which can easily display bitmap images but not SVG.
    """
    data = (data or "").strip()
    if not data:
        raise HTTPException(status_code=400, detail="Missing data.")
    if len(data) > 2048:
        raise HTTPException(status_code=413, detail="QR data too long.")

    try:
        import segno  # lazy import so unit tests don't need this dependency
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"QR generator not installed (segno): {e}")

    qr = segno.make(data, error="m")
    buf = io.BytesIO()
    # segno's PNG writer is available in our Windows venv; if this fails,
    # the launcher can still fall back to opening the web UI QR panel.
    qr.save(buf, kind="png", scale=6, border=2)
    return Response(
        content=buf.getvalue(),
        media_type="image/png",
        headers={"Cache-Control": "no-store"},
    )

# -------------------------
# Desktop endpoints
# -------------------------
@app.get("/desktop/info")
def desktop_info(request: Request):
    _ensure_windows_host()
    mon = _desktop_monitor()
    return {
        "ok": True,
        "enabled": _desktop_enabled_from_request(request),
        "alt_held": _desktop_alt_held(),
        "perf_mode_enabled": _desktop_perf_snapshot().get("enabled", False),
        "perf_mode_active": _desktop_perf_snapshot().get("active", False),
        **_desktop_stream_transport_payload(),
        "active_target_id": str(_desktop_targets_payload().get("active_target", {}).get("id") or ""),
        **mon,
    }


@app.get("/desktop/targets")
def desktop_targets(request: Request):
    _ensure_windows_host()
    _require_authenticated_request(request)
    return _desktop_targets_payload()


@app.post("/desktop/targets/select")
def desktop_targets_select(request: Request, payload: Dict[str, Any] = Body(...)):
    _ensure_windows_host()
    _require_authenticated_request(request)
    return _desktop_select_target(payload.get("target_id"))


@app.post("/desktop/targets/virtual")
def desktop_targets_virtual(request: Request, payload: Dict[str, Any] = Body(...)):
    _ensure_windows_host()
    _require_authenticated_request(request)
    raise HTTPException(
        status_code=410,
        detail="Virtual display targeting is not available in this build.",
    )


@app.get("/desktop/stream/capabilities")
def desktop_stream_capabilities():
    _ensure_windows_host()
    payload = _desktop_stream_transport_payload()
    return {
        "ok": True,
        "preferred_transport": payload["desktop_stream_transport"],
        "fallback_transport": payload["desktop_stream_fallback"],
        "webrtc_available": payload["desktop_webrtc_available"],
        "webrtc_enabled": payload["desktop_webrtc_enabled"],
        "webrtc_detail": payload["desktop_webrtc_detail"],
        "fallback_formats": ["png", "jpeg"],
        "default_fallback_format": _desktop_stream_format(None),
        "default_jpeg_quality": _desktop_stream_quality(None),
    }

@app.get("/desktop/shot")
def desktop_shot(
    request: Request,
    level: Optional[int] = None,
    scale: Optional[int] = None,
    bw: Optional[str] = None,
    format: Optional[str] = None,
    quality: Optional[int] = None,
    aspect: Optional[float] = None,
    layout_mode: Optional[str] = None,
    target_width: Optional[int] = None,
    target_height: Optional[int] = None,
):
    _ensure_windows_host()
    png_level = _clamp(int(level if level is not None else DESKTOP_STREAM_PNG_LEVEL_DEFAULT), 0, 9)
    scale_factor = _parse_stream_scale(scale, default=1)
    grayscale = _truthy_flag(bw)
    stream_format = _desktop_stream_format(format)
    jpeg_quality = _desktop_stream_quality(quality)
    aspect_ratio = _parse_stream_aspect(aspect)
    resolved_layout_mode = _parse_stream_layout_mode(layout_mode)
    target_size = _parse_stream_target_size(target_width, target_height)
    try:
        rgb, out_size = _desktop_capture_rgb(
            scale_factor=scale_factor,
            grayscale=grayscale,
            aspect_ratio=aspect_ratio,
            layout_mode=resolved_layout_mode,
            target_size=target_size,
        )
        frame_bytes, media_type = _desktop_encode_frame(rgb, out_size, stream_format, png_level, jpeg_quality)
        return Response(
            content=frame_bytes,
            media_type=media_type,
            headers={"Cache-Control": "no-store"},
        )
    except HTTPException:
        raise
    except Exception as exc:
        selected_target = _desktop_selected_target_item()
        print(
            "Desktop shot failed"
            f" target={str(selected_target.get('id') or '').strip().lower() or 'unknown'}"
            f" virtual={bool(selected_target.get('virtual'))}"
            f" backend={_desktop_capture_backend()}"
            f" error={type(exc).__name__}: {exc}",
            flush=True,
        )
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"desktop_shot_failed: {type(exc).__name__}: {exc}")

@app.get("/desktop/stream")
async def desktop_stream(
    request: Request,
    fps: Optional[float] = None,
    level: Optional[int] = None,
    scale: Optional[int] = None,
    bw: Optional[str] = None,
    format: Optional[str] = None,
    quality: Optional[int] = None,
    aspect: Optional[float] = None,
    layout_mode: Optional[str] = None,
    target_width: Optional[int] = None,
    target_height: Optional[int] = None,
):
    """
    Continuous desktop stream using multipart/x-mixed-replace.
    This keeps updating even when client-side JS is disabled or broken.
    """
    _ensure_windows_host()
    try:
        fps_val = float(fps if fps is not None else DESKTOP_STREAM_FPS_DEFAULT)
    except Exception:
        fps_val = float(DESKTOP_STREAM_FPS_DEFAULT)
    stream_format = _desktop_stream_format(format)
    fps_cap = 20.0 if stream_format == "jpeg" else 12.0
    fps_val = max(0.5, min(fps_val, fps_cap))
    png_level = _clamp(int(level if level is not None else DESKTOP_STREAM_PNG_LEVEL_DEFAULT), 0, 9)
    jpeg_quality = _desktop_stream_quality(quality)
    scale_factor = _parse_stream_scale(scale, default=1)
    grayscale = _truthy_flag(bw)
    aspect_ratio = _parse_stream_aspect(aspect)
    resolved_layout_mode = _parse_stream_layout_mode(layout_mode)
    target_size = _parse_stream_target_size(target_width, target_height)
    frame_delay = 1.0 / fps_val
    boundary = "frame"

    async def _gen():
        with mss() as sct:
            while True:
                if await request.is_disconnected():
                    break
                rgb, out_size = _desktop_capture_rgb(
                    scale_factor=scale_factor,
                    grayscale=grayscale,
                    sct_instance=sct,
                    aspect_ratio=aspect_ratio,
                    layout_mode=resolved_layout_mode,
                    target_size=target_size,
                )
                frame_bytes, media_type = _desktop_encode_frame(
                    rgb,
                    out_size,
                    stream_format,
                    png_level,
                    jpeg_quality,
                )
                chunk = (
                    f"--{boundary}\r\n"
                    f"Content-Type: {media_type}\r\n"
                    "Cache-Control: no-store\r\n"
                    f"Content-Length: {len(frame_bytes)}\r\n\r\n"
                ).encode("utf-8") + frame_bytes + b"\r\n"
                yield chunk
                await asyncio.sleep(frame_delay)

    headers = {
        "Cache-Control": "no-store",
        "Connection": "keep-alive",
        "Pragma": "no-cache",
    }
    return StreamingResponse(
        _gen(),
        media_type=f"multipart/x-mixed-replace; boundary={boundary}",
        headers=headers,
    )


@app.post("/desktop/mode")
def desktop_mode(request: Request, payload: Dict[str, Any] = Body(...)):
    enabled = _set_desktop_global_enabled(_truthy_flag(payload.get("enabled")))
    perf = _desktop_perf_snapshot()
    resp = JSONResponse({
        "ok": True,
        "enabled": enabled,
        "alt_held": _desktop_alt_held(),
        "perf_mode_enabled": perf.get("enabled", False),
        "perf_mode_active": perf.get("active", False),
    })
    resp.set_cookie(
        key=CODEX_DESKTOP_MODE_COOKIE,
        value="1" if enabled else "0",
        httponly=True,
        secure=_cookie_secure_for_request(request),
        samesite="lax",
        max_age=60 * 60 * 24 * 30,
    )
    return resp


@app.post("/desktop/perf")
def desktop_perf_mode(payload: Dict[str, Any] = Body(...)):
    _ensure_windows_host()
    perf = _set_desktop_perf_enabled(_truthy_flag(payload.get("enabled")))
    return {"ok": True, **perf, "alt_held": _desktop_alt_held()}

@app.post("/desktop/input/move")
def desktop_input_move(request: Request, payload: Dict[str, Any] = Body(...)):
    _ensure_windows_host()
    _require_desktop_enabled(request)
    _host_keep_awake_pulse(force=True)
    x = int(payload.get("x", 0))
    y = int(payload.get("y", 0))
    p = _desktop_point(x, y)
    _desktop_move_abs(p["x"], p["y"])
    return {"ok": True, "x": p["rel_x"], "y": p["rel_y"], "alt_held": _desktop_alt_held()}

@app.post("/desktop/input/click")
def desktop_input_click(request: Request, payload: Dict[str, Any] = Body(...)):
    _ensure_windows_host()
    _require_desktop_enabled(request)
    _host_keep_awake_pulse(force=True)
    alt_held_before_click = _desktop_alt_held()
    x = payload.get("x")
    y = payload.get("y")
    button = (payload.get("button") or "left").strip().lower()
    double = bool(payload.get("double", False))
    action = (payload.get("action") or "click").strip().lower()
    screen_x = None
    screen_y = None
    via = "desktop"
    if x is not None and y is not None:
        p = _desktop_point(int(x), int(y))
        screen_x = int(p["x"])
        screen_y = int(p["y"])
    if screen_x is not None and screen_y is not None:
        caption_command = None
        if button == "left" and not double and action == "click":
            caption_command = _desktop_caption_syscommand_at(screen_x, screen_y)
        if caption_command:
            via = f"desktop_caption_{caption_command}"
        else:
            _desktop_click_at(screen_x, screen_y, button=button, double=double, action=action)
    else:
        _desktop_click(button=button, double=double, action=action)
    logging.info(
        "desktop_input_click x=%s y=%s screen_x=%s screen_y=%s button=%s action=%s via=%s",
        x,
        y,
        screen_x,
        screen_y,
        button,
        action,
        via,
    )
    if alt_held_before_click:
        _desktop_release_alt_if_held()
    return {"ok": True, "button": button, "double": double, "action": action, "via": via, "alt_held": _desktop_alt_held()}

@app.post("/desktop/input/scroll")
def desktop_input_scroll(request: Request, payload: Dict[str, Any] = Body(...)):
    _ensure_windows_host()
    _require_desktop_enabled(request)
    _host_keep_awake_pulse(force=True)
    _desktop_release_alt_if_held()
    delta = int(payload.get("delta", 0))
    if delta == 0:
        raise HTTPException(status_code=400, detail="delta is required.")
    _desktop_scroll(delta)
    return {"ok": True, "delta": delta, "alt_held": _desktop_alt_held()}

@app.post("/desktop/input/type")
def desktop_input_type(request: Request, payload: Dict[str, Any] = Body(...)):
    _ensure_windows_host()
    _require_desktop_enabled(request)
    _host_keep_awake_pulse(force=True)
    _desktop_release_alt_if_held()
    text = (payload.get("text") or "")
    if not text:
        raise HTTPException(status_code=400, detail="text is required.")
    r = _desktop_send_text(text)
    if r.get("exit_code") != 0:
        return {"ok": False, "error": "type_failed", "raw": r}
    return {"ok": True, "alt_held": _desktop_alt_held()}

@app.post("/desktop/input/text")
def desktop_input_text(request: Request, payload: Dict[str, Any] = Body(...)):
    """
    Real-time typing endpoint (does not touch clipboard).
    """
    _ensure_windows_host()
    _require_desktop_enabled(request)
    _host_keep_awake_pulse(force=True)
    _desktop_release_alt_if_held()
    text = payload.get("text")
    if not isinstance(text, str):
        raise HTTPException(status_code=400, detail="text must be a string.")
    if not text:
        return {"ok": True, "sent": 0, "alt_held": _desktop_alt_held()}
    if len(text) > 20000:
        raise HTTPException(status_code=400, detail="text too long (max 20000).")
    sent = _send_text_native_first(text, unicode_chunk_size=240)
    return {"ok": True, "sent": sent, "alt_held": _desktop_alt_held()}

@app.post("/desktop/input/edit")
def desktop_input_edit(request: Request, payload: Dict[str, Any] = Body(...)):
    """
    Atomic edit operation for the Live Keyboard:
    - send N backspaces
    - then send a text chunk
    """
    _ensure_windows_host()
    _require_desktop_enabled(request)
    _host_keep_awake_pulse(force=True)
    _desktop_release_alt_if_held()
    backspace = int(payload.get("backspace", 0) or 0)
    text = payload.get("text") or ""
    if not isinstance(text, str):
        raise HTTPException(status_code=400, detail="text must be a string.")
    if backspace < 0:
        raise HTTPException(status_code=400, detail="backspace must be >= 0.")
    if backspace > 200:
        raise HTTPException(status_code=400, detail="backspace too large (max 200).")
    if len(text) > 500:
        raise HTTPException(status_code=400, detail="text too long (max 500).")
    def _apply_edit() -> int:
        if backspace:
            _send_vk_repeat(VK_BACK, backspace)
        if text:
            return _send_text_native_first(text, unicode_chunk_size=240)
        return 0

    sent = _apply_edit()
    return {"ok": True, "backspace": backspace, "sent": sent, "alt_held": _desktop_alt_held()}

@app.post("/desktop/input/key")
def desktop_input_key(request: Request, payload: Dict[str, Any] = Body(...)):
    _ensure_windows_host()
    _require_desktop_enabled(request)
    _host_keep_awake_pulse(force=True)
    key = (payload.get("key") or "").strip()
    if not key:
        raise HTTPException(status_code=400, detail="key is required.")
    r = _desktop_send_key(key)
    if r.get("exit_code") != 0:
        return {"ok": False, "error": "key_failed", "raw": r}
    return {"ok": True, "key": key, "alt_held": bool(r.get("alt_held", _desktop_alt_held()))}


@app.post("/desktop/selection/path")
def desktop_selection_path(request: Request):
    _ensure_windows_host()
    _require_desktop_enabled(request)
    _desktop_release_alt_if_held()
    try:
        payload = _desktop_selected_paths()
        payload["alt_held"] = _desktop_alt_held()
        return payload
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"selected_path_internal_error: {type(exc).__name__}: {exc}")


@app.post("/desktop/webrtc/offer")
async def desktop_webrtc_offer(request: Request, payload: Optional[Dict[str, Any]] = Body(default=None)):
    _ensure_windows_host()
    payload = payload or {}
    offer = payload.get("offer")
    if not isinstance(offer, dict) or not str(offer.get("sdp") or "").strip():
        raise HTTPException(status_code=400, detail="offer is required.")
    transport = _desktop_stream_transport_payload()
    if not transport["desktop_webrtc_enabled"]:
        raise HTTPException(status_code=503, detail=transport["desktop_webrtc_detail"])
    await _desktop_webrtc_evict_stale_sessions_for_new_offer()
    if len(DESKTOP_WEBRTC_SESSIONS) >= DESKTOP_WEBRTC_MAX_SESSIONS:
        raise HTTPException(status_code=429, detail="Too many active WebRTC desktop sessions.")

    session_id = uuid.uuid4().hex
    fps = float((payload.get("fps") or DESKTOP_STREAM_FPS_DEFAULT) or DESKTOP_STREAM_FPS_DEFAULT)
    scale_factor = _parse_stream_scale(payload.get("scale"), default=1)
    grayscale = _truthy_flag(payload.get("bw"))
    aspect_ratio = _parse_stream_aspect(payload.get("aspect"))
    layout_mode = _parse_stream_layout_mode(payload.get("layout_mode"))
    target_size = _parse_stream_target_size(payload.get("target_width"), payload.get("target_height"))
    pc = RTCPeerConnection()
    track = DesktopVideoTrack(
        fps=fps,
        scale_factor=scale_factor,
        grayscale=grayscale,
        aspect_ratio=aspect_ratio,
        layout_mode=layout_mode,
        target_size=target_size,
    )
    transceiver = pc.addTransceiver(track, direction="sendonly")
    sender = transceiver.sender
    preferred_codecs = _desktop_webrtc_preferred_video_codecs()
    if preferred_codecs:
        try:
            transceiver.setCodecPreferences(preferred_codecs)
            print(
                "Desktop WebRTC session="
                f"{session_id} codec preference="
                f"{','.join(str(getattr(codec, 'mimeType', '') or '') for codec in preferred_codecs)}",
                flush=True,
            )
        except Exception as codec_exc:
            print(
                f"Desktop WebRTC session={session_id} codec preference failed: {type(codec_exc).__name__}: {codec_exc}",
                flush=True,
            )
    _desktop_webrtc_store_session(session_id, pc, track, sender=sender, transceiver=transceiver)
    preferred_host = _desktop_webrtc_constrain_local_gathering(pc, getattr(request.url, "hostname", ""))
    print(
        "Desktop WebRTC offer session="
        f"{session_id} created fps={fps:.1f} scale={scale_factor}"
        f" bw={grayscale} aspect={aspect_ratio or 0:.4f}"
        f" mode={layout_mode} target={target_size}",
        flush=True,
    )
    if preferred_host:
        print(
            f"Desktop WebRTC session={session_id} constrained ICE gathering to {preferred_host}",
            flush=True,
        )
    print(
        f"Desktop WebRTC session={session_id} remote SDP { _desktop_webrtc_sdp_video_summary(str(offer.get('sdp') or '')) }",
        flush=True,
    )

    @pc.on("connectionstatechange")
    async def _on_connectionstatechange():
        _desktop_webrtc_log_sender_state(session_id, sender)
        print(
            "Desktop WebRTC session="
            f"{session_id} connectionState={getattr(pc, 'connectionState', '')}"
            f" iceGathering={getattr(pc, 'iceGatheringState', '')}"
            f" iceConnection={getattr(pc, 'iceConnectionState', '')}",
            flush=True,
        )
        if pc.connectionState in {"failed", "closed", "disconnected"}:
            await _desktop_webrtc_close_session(session_id)

    try:
        negotiation_started = time.perf_counter()
        print(f"Desktop WebRTC session={session_id} applying remote offer", flush=True)
        await pc.setRemoteDescription(
            RTCSessionDescription(
                sdp=str(offer.get("sdp") or "").strip(),
                type=str(offer.get("type") or "offer").strip() or "offer",
            )
        )
        remote_applied_ms = (time.perf_counter() - negotiation_started) * 1000.0
        print(
            f"Desktop WebRTC session={session_id} remote offer applied in {remote_applied_ms:.0f} ms",
            flush=True,
        )
        print(f"Desktop WebRTC session={session_id} creating answer", flush=True)
        answer_started = time.perf_counter()
        answer = await pc.createAnswer()
        answer_created_ms = (time.perf_counter() - answer_started) * 1000.0
        print(
            f"Desktop WebRTC session={session_id} answer created in {answer_created_ms:.0f} ms",
            flush=True,
        )
        local = await _desktop_webrtc_set_local_answer_fast(session_id, pc, answer)
        _desktop_webrtc_log_sender_state(session_id, sender)
        if local is None or not str(local.sdp or "").strip():
            raise HTTPException(status_code=500, detail="Could not generate WebRTC answer.")
        answer_return_ms = (time.perf_counter() - negotiation_started) * 1000.0
        print(
            "Desktop WebRTC session="
            f"{session_id} returning answer in {answer_return_ms:.0f} ms"
            f" iceGathering={getattr(pc, 'iceGatheringState', '')}"
            f" iceConnection={getattr(pc, 'iceConnectionState', '')}",
            flush=True,
        )
        print(
            f"Desktop WebRTC session={session_id} local SDP { _desktop_webrtc_sdp_video_summary(str(local.sdp or '')) }",
            flush=True,
        )
        return {
            "ok": True,
            "session_id": session_id,
            "answer": {
                "type": local.type,
                "sdp": local.sdp,
            },
            "transport": "webrtc",
            "fallback": DESKTOP_STREAM_FALLBACK_TRANSPORT,
            "trickle_ice": True,
        }
    except HTTPException:
        await _desktop_webrtc_close_session(session_id)
        raise
    except Exception as exc:
        await _desktop_webrtc_close_session(session_id)
        raise HTTPException(status_code=500, detail=f"WebRTC negotiation failed: {type(exc).__name__}: {exc}")


@app.get("/desktop/webrtc/session/{session_id}/ice")
async def desktop_webrtc_local_ice(session_id: str):
    _ensure_windows_host()
    cleaned = _desktop_webrtc_payload_session_id(session_id)
    session = _desktop_webrtc_get_session(cleaned)
    if not session:
        raise HTTPException(status_code=404, detail="WebRTC desktop session not found.")
    pending, complete = _desktop_webrtc_drain_local_candidates(session)
    return {
        "ok": True,
        "session_id": cleaned,
        "candidates": pending,
        "complete": bool(complete),
        "ready": bool(session.get("local_description_ready")),
        "error": str(session.get("local_description_error") or ""),
    }


@app.get("/desktop/webrtc/ice/{session_id}")
async def desktop_webrtc_local_ice_legacy(session_id: str):
    return await desktop_webrtc_local_ice(session_id)


@app.post("/desktop/webrtc/ice")
async def desktop_webrtc_ice(payload: Optional[Dict[str, Any]] = Body(default=None)):
    _ensure_windows_host()
    payload = payload or {}
    candidate = payload.get("candidate")
    if not isinstance(candidate, dict):
        raise HTTPException(status_code=400, detail="candidate is required.")
    transport = _desktop_stream_transport_payload()
    if not transport["desktop_webrtc_enabled"]:
        raise HTTPException(status_code=503, detail=transport["desktop_webrtc_detail"])
    session_id = _desktop_webrtc_payload_session_id(payload.get("session_id"))
    session = _desktop_webrtc_get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="WebRTC desktop session not found.")
    try:
        await session["pc"].addIceCandidate(_desktop_webrtc_candidate_payload(candidate))
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Could not add ICE candidate: {type(exc).__name__}: {exc}")
    return {"ok": True, "session_id": session_id}


@app.delete("/desktop/webrtc/session/{session_id}")
async def desktop_webrtc_close(session_id: str):
    _ensure_windows_host()
    cleaned = _desktop_webrtc_payload_session_id(session_id)
    await _desktop_webrtc_close_session(cleaned)
    return {"ok": True, "session_id": cleaned}


@app.delete("/desktop/webrtc/sessions")
async def desktop_webrtc_close_all():
    _ensure_windows_host()
    closed = await _desktop_webrtc_close_all_sessions()
    return {"ok": True, "closed": closed}


@app.get("/power/status")
def power_status():
    _ensure_windows_host()
    return _power_status_payload()


@app.post("/power/action")
def power_action(payload: Dict[str, Any] = Body(...)):
    _ensure_windows_host()
    action = str(payload.get("action") or "").strip().lower()
    if action not in {"lock", "sleep", "hibernate", "restart", "shutdown"}:
        raise HTTPException(status_code=400, detail="Unsupported power action.")
    destructive = {"sleep", "hibernate", "restart", "shutdown"}
    if action in destructive and not _consume_power_confirmation(action, str(payload.get("confirm_token") or "")):
        return {
            "ok": False,
            "action": action,
            "error": "confirmation_required",
            "detail": f"Confirm {action} before it is sent to the host.",
            **_create_power_confirmation(action),
        }
    return _schedule_power_action(action)

# -------------------------
# Codex multi-session endpoints
# -------------------------
@app.get("/threads")
def threads_store_get():
    with THREADS_LOCK:
        _load_threads_store_unlocked()
        snapshot = _threads_snapshot_unlocked()
    return {"ok": True, **snapshot}


@app.post("/threads")
def thread_create(payload: Optional[Dict[str, Any]] = Body(default=None)):
    payload = payload or {}
    session = _validate_session_name((payload.get("session") or "").strip())
    requested_id = _clean_entity_id(payload.get("id"))
    title = _normalize_thread_title(payload.get("title"), session)
    now_ms = _now_ms()

    with THREADS_LOCK:
        _load_threads_store_unlocked()
        thread_id = requested_id or f"thr_{uuid.uuid4().hex[:12]}"
        existing = _find_thread_unlocked(thread_id)
        if existing:
            return {"ok": True, "thread": existing}
        thread = {
            "id": thread_id,
            "title": title,
            "session": session,
            "created_at": now_ms,
            "updated_at": now_ms,
        }
        THREADS_DATA["threads"].append(thread)
        THREADS_DATA["messages"].setdefault(thread_id, [])
        _persist_threads_store_unlocked()
    return {"ok": True, "thread": thread}


@app.post("/threads/{thread_id}")
def thread_update(thread_id: str, payload: Optional[Dict[str, Any]] = Body(default=None)):
    thread_id = _clean_entity_id(thread_id)
    if not thread_id:
        raise HTTPException(status_code=400, detail="Invalid thread id format.")
    payload = payload or {}

    with THREADS_LOCK:
        _load_threads_store_unlocked()
        thread = _find_thread_unlocked(thread_id)
        if not thread:
            return {"ok": False, "error": "not_found", "detail": f"Thread '{thread_id}' was not found."}

        if "session" in payload:
            next_session = _validate_session_name((payload.get("session") or "").strip())
            thread["session"] = next_session
        if "title" in payload:
            thread["title"] = _normalize_thread_title(payload.get("title"), thread.get("session") or "")
        thread["updated_at"] = _now_ms()
        _persist_threads_store_unlocked()
    return {"ok": True, "thread": thread}


@app.delete("/threads/{thread_id}")
def thread_delete(thread_id: str):
    thread_id = _clean_entity_id(thread_id)
    if not thread_id:
        raise HTTPException(status_code=400, detail="Invalid thread id format.")

    with THREADS_LOCK:
        _load_threads_store_unlocked()
        before = len(THREADS_DATA.get("threads") or [])
        THREADS_DATA["threads"] = [
            thread for thread in (THREADS_DATA.get("threads") or [])
            if thread.get("id") != thread_id
        ]
        THREADS_DATA["messages"].pop(thread_id, None)
        after = len(THREADS_DATA.get("threads") or [])
        if before == after:
            return {"ok": False, "error": "not_found", "detail": f"Thread '{thread_id}' was not found."}
        _persist_threads_store_unlocked()
    return {"ok": True, "thread_id": thread_id}


@app.post("/threads/{thread_id}/messages")
def thread_add_message(thread_id: str, payload: Dict[str, Any] = Body(...)):
    thread_id = _clean_entity_id(thread_id)
    if not thread_id:
        raise HTTPException(status_code=400, detail="Invalid thread id format.")
    payload = payload or {}

    role = str(payload.get("role") or "").strip().lower()
    if role not in {"user", "assistant", "system"}:
        raise HTTPException(status_code=400, detail="Invalid role. Must be user, assistant, or system.")

    text = str(payload.get("text") or "").strip()
    if not text:
        raise HTTPException(status_code=400, detail="Message text is required.")
    if len(text) > THREAD_MESSAGE_TEXT_MAX:
        raise HTTPException(status_code=400, detail=f"Message too long (max {THREAD_MESSAGE_TEXT_MAX}).")

    msg_id = _clean_entity_id(payload.get("id")) or f"msg_{uuid.uuid4().hex[:12]}"
    at = _coerce_ms(payload.get("at"), _now_ms())

    with THREADS_LOCK:
        _load_threads_store_unlocked()
        thread = _find_thread_unlocked(thread_id)
        if not thread:
            return {"ok": False, "error": "not_found", "detail": f"Thread '{thread_id}' was not found."}

        messages = THREADS_DATA["messages"].setdefault(thread_id, [])
        for existing in messages:
            if existing.get("id") == msg_id:
                return {"ok": True, "message": existing}

        message = {
            "id": msg_id,
            "thread_id": thread_id,
            "role": role,
            "text": text,
            "at": at,
        }
        messages.append(message)
        thread["updated_at"] = max(int(thread.get("updated_at") or 0), at, _now_ms())
        _persist_threads_store_unlocked()
    return {"ok": True, "message": message}


@app.get("/windows/runtime/status")
def windows_runtime_status():
    return {"ok": True, **_windows_runtime_status_payload()}


@app.post("/windows/runtime/start")
def windows_runtime_start():
    if not _windows_runtime_supported():
        return {"ok": False, **_windows_runtime_status_payload()}
    with WINDOWS_RUNTIME_LOCK:
        global WINDOWS_RUNTIME_ACTIVE
        WINDOWS_RUNTIME_ACTIVE = True
    return {"ok": True, **_windows_runtime_status_payload()}


@app.post("/windows/runtime/stop")
def windows_runtime_stop():
    if not _windows_runtime_supported():
        return {"ok": False, **_windows_runtime_status_payload()}
    _windows_runtime_stop_all_sessions("stopped")
    with WINDOWS_RUNTIME_LOCK:
        global WINDOWS_RUNTIME_ACTIVE
        WINDOWS_RUNTIME_ACTIVE = False
    return {"ok": True, **_windows_runtime_status_payload()}


@app.get("/windows/sessions")
def windows_sessions_live():
    _host_keep_awake_pulse()
    with WINDOWS_SESSIONS_LOCK:
        live = [
            _windows_session_public_record(entry)
            for entry in WINDOWS_SESSIONS.values()
        ]
        recent_closed = [dict(item) for item in WINDOWS_RECENT_CLOSED]
    live.sort(key=lambda item: str(item.get("session") or ""))
    return {
        "ok": True,
        "sessions": live,
        "recent_closed": recent_closed,
        "meta": {
            "total_sessions": len(live),
            "total_recent_closed": len(recent_closed),
            "background_mode": WINDOWS_SESSION_BACKGROUND_MODE,
            "summary_updated_at": time.time(),
        },
    }


@app.post("/windows/session")
def windows_session_create(payload: Optional[Dict[str, Any]] = Body(default=None)):
    payload = payload or {}
    status = _windows_runtime_status_payload()
    if not _windows_runtime_supported():
        return {"ok": False, **status}
    if status.get("state") != "running":
        raise HTTPException(status_code=409, detail="Windows runtime is stopped. Start it before creating SSH sessions.")

    name_raw = str(payload.get("name") or "").strip()
    if name_raw:
        name = _safe_name(name_raw)
        if not name.startswith("win_"):
            name = f"win_{name}"
    else:
        name = f"win_{uuid.uuid4().hex[:8]}"
    name = _validate_session_name(name)
    profile = _windows_session_profile(payload.get("profile"))
    cwd = _windows_normalize_cwd(payload.get("cwd"))
    model = _normalize_codex_model(payload.get("model")) if profile == "codex" else profile
    reasoning_effort = (
        _normalize_reasoning_effort(
            payload.get("reasoning_effort") or payload.get("model_reasoning_effort"),
            model=model,
        )
        if profile == "codex"
        else ""
    )
    argv = _windows_session_spawn_argv(profile, model if profile == "codex" else "", reasoning_effort)
    try:
        process = PtyProcess.spawn(
            argv,
            cwd=cwd,
            env=os.environ.copy(),
            dimensions=(32, 120),
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Could not start Windows session: {type(exc).__name__}: {exc}")

    now = time.time()
    entry = {
        "session": name,
        "pane_id": "winpty",
        "current_command": _windows_session_command_label(profile),
        "cwd": cwd,
        "state": "starting",
        "updated_at": now,
        "last_seen_at": now,
        "snippet": "",
        "last_text": "",
        "profile": profile,
        "model": model,
        "reasoning_effort": reasoning_effort,
        "process": process,
        "io_lock": threading.Lock(),
    }
    with WINDOWS_SESSIONS_LOCK:
        if name in WINDOWS_SESSIONS:
            try:
                process.terminate(force=True)
            except Exception:
                pass
            return {"ok": False, "error": "session_exists", "detail": f"Windows session '{name}' already exists."}
        WINDOWS_SESSIONS[name] = entry
    reader = threading.Thread(target=_windows_session_reader, args=(name,), name=f"codrex-winpty-{name}", daemon=True)
    with WINDOWS_SESSIONS_LOCK:
        current = WINDOWS_SESSIONS.get(name)
        if current is not None:
            current["reader_thread"] = reader
    reader.start()
    return {
        "ok": True,
        "session": name,
        "cwd": cwd,
        "model": model,
        "reasoning_effort": reasoning_effort,
        "profile": profile,
    }


@app.delete("/windows/session/{session}")
def windows_session_close(session: str):
    session_id = _validate_session_name(session)
    entry = _windows_session_entry(session_id)
    process = entry.get("process")
    try:
        if process is not None:
            process.terminate(force=True)
    except Exception:
        pass
    closed = _windows_session_finalize(session_id, "closed")
    if not closed:
        # The reader thread can finalize the session immediately after terminate().
        # Treat that race as a successful close rather than surfacing a false error.
        return {"ok": True, "session": session_id, "detail": "Windows session closed."}
    return {"ok": True, "session": session_id}


@app.post("/windows/session/{session}/send")
def windows_session_send(session: str, body: str = Body(..., media_type="text/plain")):
    session_id = _validate_session_name(session)
    text = str(body or "").replace("\r\n", "\n")
    if not text.strip():
        raise HTTPException(status_code=400, detail="Prompt text is required.")
    entry = _windows_session_entry(session_id)
    profile = str(entry.get("profile") or "codex")
    _host_keep_awake_pulse(force=True)
    _windows_session_write(session_id, text)
    _windows_session_write(session_id, "\r\n\r\n" if profile == "codex" else "\r\n")
    if profile == "codex":
        _telegram_windows_mirror_send_prompt(
            session_id,
            text,
            current_command=str(entry.get("current_command") or "codex"),
        )
    return {"ok": True, "session": session_id}


@app.post("/windows/session/{session}/enter")
def windows_session_enter(session: str):
    session_id = _validate_session_name(session)
    _host_keep_awake_pulse(force=True)
    _windows_session_write(session_id, "\r\n")
    return {"ok": True, "session": session_id}


@app.post("/windows/session/{session}/key")
def windows_session_key(session: str, payload: Dict[str, Any] = Body(...)):
    session_id = _validate_session_name(session)
    raw_key = str((payload or {}).get("key") or "").strip().lower()
    key_map = {
        "up": "\x1b[A",
        "down": "\x1b[B",
        "left": "\x1b[D",
        "right": "\x1b[C",
        "arrowup": "\x1b[A",
        "arrowdown": "\x1b[B",
        "arrowleft": "\x1b[D",
        "arrowright": "\x1b[C",
        "backspace": "\b",
    }
    value = key_map.get(raw_key)
    if not value:
        raise HTTPException(status_code=400, detail="Unsupported key. Use: up, down, left, right, backspace.")
    _host_keep_awake_pulse(force=True)
    _windows_session_write(session_id, value)
    return {"ok": True, "session": session_id, "key": raw_key}


@app.post("/windows/session/{session}/ctrlc")
def windows_session_ctrlc(session: str):
    session_id = _validate_session_name(session)
    entry = _windows_session_entry(session_id)
    process = entry.get("process")
    if process is None:
        raise HTTPException(status_code=409, detail=f"Windows session '{session_id}' is not writable.")
    _host_keep_awake_pulse(force=True)
    io_lock = entry.get("io_lock")
    with io_lock:
        try:
            process.sendcontrol("c")
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"Could not send Ctrl+C: {type(exc).__name__}: {exc}")
    return {"ok": True, "session": session_id}


@app.post("/windows/session/{session}/interrupt")
def windows_session_interrupt(session: str):
    session_id = _validate_session_name(session)
    _host_keep_awake_pulse(force=True)
    _windows_session_write(session_id, "\x1b")
    return {"ok": True, "session": session_id}


@app.get("/windows/session/{session}/screen")
def windows_session_screen(session: str):
    session_id = _validate_session_name(session)
    _host_keep_awake_pulse(force=True)
    entry = _windows_session_entry(session_id)
    text = str(entry.get("last_text") or "")
    current_command = str(entry.get("current_command") or "")
    state = (
        _infer_progress_state(text, current_command)
        if str(entry.get("profile") or "") == "codex"
        else ("running" if text or entry.get("process") else "starting")
    )
    with WINDOWS_SESSIONS_LOCK:
        live_entry = WINDOWS_SESSIONS.get(session_id)
        if live_entry is not None:
            live_entry.update({
                "state": state,
                "updated_at": time.time(),
                "last_seen_at": time.time(),
                "snippet": _windows_session_snippet(text),
            })
    _publish_windows_session_stream_snapshot(
        session_id,
        text,
        screen_state=state,
        current_command=current_command,
    )
    return {
        "ok": True,
        "session": session_id,
        "pane_id": "winpty",
        "current_command": current_command,
        "state": state,
        "text": text,
    }


@app.websocket("/windows/session/{session}/ws")
async def windows_session_stream(websocket: WebSocket, session: str):
    session_id = str(session or "").strip()
    try:
        session_id = _validate_session_name(session_id)
    except HTTPException as exc:
        await websocket.accept()
        await websocket.send_json({"ok": False, "type": "error", "detail": exc.detail})
        await websocket.close(code=4400)
        return

    await websocket.accept()
    if not _is_valid_auth_token(_auth_token_from_websocket(websocket)):
        await websocket.send_json({"ok": False, "type": "error", "detail": "Login required."})
        await websocket.close(code=4401)
        return

    selected_profile = str(websocket.query_params.get("profile") or "balanced").strip().lower()
    if selected_profile not in {"fast", "balanced", "battery"}:
        selected_profile = "balanced"
    try:
        since_seq = int(str(websocket.query_params.get("since_seq") or "0").strip() or "0")
    except Exception:
        since_seq = 0
    interval_ms = _session_stream_interval_ms(selected_profile)
    last_keepalive = 0.0

    try:
        _host_keep_awake_pulse(force=True)
        with WINDOWS_SESSION_STREAM_LOCK:
            state = _windows_session_stream_state_unlocked(session_id)
            hello_payload = _windows_session_stream_event_payload(
                session=session_id,
                seq=int(state.get("seq") or 0),
                event_type="hello",
                text="",
                profile=selected_profile,
                detail="connected",
            )
        await websocket.send_json({"ok": True, **hello_payload})

        replay_events, replay_snapshot = _windows_session_stream_replay(session_id, since_seq)
        for event in replay_events:
            await websocket.send_json({"ok": True, **event})
        if replay_snapshot:
            await websocket.send_json({"ok": True, **replay_snapshot})

        if not replay_events and not replay_snapshot:
            try:
                entry = _windows_session_entry(session_id)
            except HTTPException:
                entry = None
            if entry is not None:
                text = str(entry.get("last_text") or "")
                current_command = str(entry.get("current_command") or "")
                state_value = str(entry.get("state") or "starting")
                event = await asyncio.to_thread(
                    _publish_windows_session_stream_snapshot,
                    session_id,
                    text,
                    screen_state=state_value,
                    current_command=current_command,
                )
                if event:
                    await websocket.send_json({"ok": True, **event, "profile": selected_profile})

        while True:
            _host_keep_awake_pulse()
            pending: List[Dict[str, Any]] = []
            with WINDOWS_SESSION_STREAM_LOCK:
                stream_state = _windows_session_stream_state_unlocked(session_id)
                for event in stream_state.get("events") or []:
                    if int(event.get("seq") or 0) > since_seq:
                        pending.append(dict(event))
            if pending:
                for event in pending:
                    since_seq = max(since_seq, int(event.get("seq") or 0))
                    await websocket.send_json({"ok": True, **event})
                last_keepalive = time.time()
            elif time.time() - last_keepalive > 10:
                entry = None
                try:
                    entry = _windows_session_entry(session_id)
                except HTTPException:
                    entry = None
                await websocket.send_json(
                    {
                        "ok": True,
                        **_windows_session_stream_event_payload(
                            session=session_id,
                            seq=since_seq,
                            event_type="keepalive",
                            text="",
                            profile=selected_profile,
                            detail="idle",
                            state=str((entry or {}).get("state") or "done"),
                            current_command=str((entry or {}).get("current_command") or ""),
                        ),
                    }
                )
                last_keepalive = time.time()
            await asyncio.sleep(interval_ms / 1000.0)
    except WebSocketDisconnect:
        return


@app.get("/desktop-codex/runtime/status")
def desktop_codex_runtime_status():
    return _desktop_codex_runtime_status_payload()


@app.get("/desktop-codex/sessions")
def desktop_codex_sessions():
    _host_keep_awake_pulse()
    sessions = _desktop_codex_fetch_sessions()
    return {
        "ok": True,
        "sessions": sessions,
        "recent_closed": [],
        "meta": {
            "total_sessions": len(sessions),
            "total_recent_closed": 0,
            "background_mode": "selected_only",
            "summary_updated_at": time.time(),
        },
        "detail": _desktop_codex_sessions_detail(),
    }


@app.get("/desktop-codex/session/{session}/screen")
def desktop_codex_session_screen(session: str):
    session_entry = _desktop_codex_session_entry(session)
    transcript = _desktop_codex_render_transcript(str(session_entry.get("rollout_path") or ""))
    active_job = _desktop_codex_job_snapshot(str(session_entry.get("session") or ""))
    state = transcript.get("state") or session_entry.get("state") or "idle"
    if _desktop_codex_is_job_active(active_job):
        state = "busy"
    return {
        "ok": True,
        "session": session_entry.get("session"),
        "pane_id": session_entry.get("pane_id"),
        "current_command": session_entry.get("current_command"),
        "state": state,
        "text": transcript.get("text") or "",
        "detail": (
            "Attached to the shared Codex Desktop thread transcript. Sends go through the private Windows app-server."
            if _desktop_codex_write_supported()
            else "Read-only mirror of the shared Codex Desktop thread transcript."
        ),
        "title": session_entry.get("title") or session_entry.get("session"),
        "read_only": not _desktop_codex_write_supported(),
    }


@app.post("/desktop-codex/session/{session}/send")
def desktop_codex_session_send(session: str, text: str = Body(..., media_type="text/plain")):
    _host_keep_awake_pulse()
    session_entry = _desktop_codex_session_entry(session)
    started = _desktop_codex_start_app_server_resume(session_entry, text)
    return {
        "ok": True,
        "session": session_entry.get("session"),
        "detail": "Desktop Codex app-server turn started.",
        "started_at": started.get("started_at"),
        "turn_id": started.get("turn_id"),
    }


@app.post("/desktop-codex/session/{session}/interrupt")
def desktop_codex_session_interrupt(session: str):
    session_id = _validate_session_name(session)
    stopped = _desktop_codex_interrupt_sidecar_resume(session_id)
    if not stopped:
        return {
            "ok": False,
            "error": "not_running",
            "detail": "No active Desktop Codex app-server turn is running for this thread.",
        }
    return {
        "ok": True,
        "session": session_id,
        "detail": "Desktop Codex app-server turn interrupted.",
    }


@app.post("/desktop-codex/session/{session}/open")
def desktop_codex_session_open(session: str):
    session_id = _validate_session_name(session)
    _desktop_codex_open_thread(session_id)
    return {
        "ok": True,
        "session": session_id,
        "detail": "Opened the desktop Codex app on this thread.",
    }


@app.post("/desktop-codex/session/{session}/refresh")
def desktop_codex_session_refresh(session: str):
    session_id = _validate_session_name(session)
    _desktop_codex_refresh_thread(session_id)
    return {
        "ok": True,
        "session": session_id,
        "detail": "Requested a desktop Codex thread refresh.",
    }


@app.websocket("/desktop-codex/session/{session}/ws")
async def desktop_codex_session_stream(websocket: WebSocket, session: str):
    session_id = str(session or "").strip()
    try:
        session_entry = _desktop_codex_session_entry(session_id)
    except HTTPException as exc:
        await websocket.accept()
        await websocket.send_json({"ok": False, "type": "error", "detail": exc.detail})
        await websocket.close(code=4404)
        return

    await websocket.accept()
    if not _is_valid_auth_token(_auth_token_from_websocket(websocket)):
        await websocket.send_json({"ok": False, "type": "error", "detail": "Login required."})
        await websocket.close(code=4401)
        return

    rollout_path = str(session_entry.get("rollout_path") or "")
    seq = 0
    last_text = ""
    last_state = ""
    last_keepalive = 0.0

    try:
        while True:
            _host_keep_awake_pulse()
            transcript = await asyncio.to_thread(_desktop_codex_render_transcript, rollout_path)
            next_text = str(transcript.get("text") or "")
            next_state = str(transcript.get("state") or session_entry.get("state") or "idle")
            if next_text != last_text or next_state != last_state:
                seq += 1
                await websocket.send_json(
                    {
                        "ok": True,
                        "session": session_id,
                        "pane_id": session_id,
                        "seq": seq,
                        "type": "snapshot" if seq == 1 else "replace",
                        "text": next_text,
                        "state": next_state,
                        "current_command": str(session_entry.get("current_command") or "Codex Desktop"),
                        "detail": "read_only",
                        "ts": time.time(),
                    }
                )
                last_text = next_text
                last_state = next_state
                last_keepalive = time.time()
            elif time.time() - last_keepalive > 10.0:
                await websocket.send_json(
                    {
                        "ok": True,
                        "session": session_id,
                        "pane_id": session_id,
                        "seq": seq,
                        "type": "keepalive",
                        "text": "",
                        "state": next_state or "idle",
                        "current_command": str(session_entry.get("current_command") or "Codex Desktop"),
                        "detail": "idle",
                        "ts": time.time(),
                    }
                )
                last_keepalive = time.time()
            await asyncio.sleep(DESKTOP_CODEX_STREAM_POLL_SECONDS)
    except WebSocketDisconnect:
        return


@app.get("/codex/options")
def codex_options():
    default_model = CODEX_DEFAULT_MODEL
    allowed_reasoning = _reasoning_efforts_for_model(default_model)
    return {
        "ok": True,
        "models": CODEX_MODEL_OPTIONS,
        "default_model": default_model,
        "reasoning_efforts": allowed_reasoning,
        "default_reasoning_effort": _default_reasoning_effort_for_model(default_model),
    }


@app.post("/codex/session")
def codex_session_create(payload: Optional[Dict[str, Any]] = Body(default=None)):
    payload = payload or {}
    name_raw = (payload.get("name") or "").strip()
    if name_raw:
        name = _safe_name(name_raw)
        if not name.startswith("codex_"):
            name = f"codex_{name}"
    else:
        name = f"codex_{uuid.uuid4().hex[:8]}"
    _validate_session_name(name)

    cwd = (payload.get("cwd") or CODEX_WORKDIR).strip() or CODEX_WORKDIR
    model = _normalize_codex_model(payload.get("model"))
    reasoning_effort = _normalize_reasoning_effort(
        payload.get("reasoning_effort") or payload.get("model_reasoning_effort"),
        model=model,
    )
    resume_last = bool(payload.get("resume_last"))
    resume_id = _normalize_codex_resume_id(payload.get("resume_id")) if payload.get("resume_id") not in {None, ""} else ""
    if resume_id and resume_last:
        raise HTTPException(status_code=400, detail="Use either resume_id or resume_last, not both.")
    codex_cmd = (
        f"codex resume {resume_id}"
        if resume_id
        else ("codex resume --last" if resume_last else _build_codex_launch_command(model, reasoning_effort))
    )
    cmd = f"tmux new-session -d -s {name} -c " + _bash_quote(cwd) + " " + _bash_quote(codex_cmd)
    r = run_wsl_bash(cmd, timeout_s=45)
    if r.get("exit_code") != 0:
        stderr = (r.get("stderr") or "").lower()
        if "duplicate session" in stderr or "session already exists" in stderr:
            return {"ok": False, "error": "session_exists", "detail": f"Session '{name}' already exists."}
        return {"ok": False, "error": "create_failed", "raw": r}

    with SESSIONS_LOCK:
        SESSIONS[name] = {
            "session": name,
            "cwd": cwd,
            "created_at": time.time(),
            "updated_at": time.time(),
            "last_seen_at": time.time(),
            "state": "starting",
            "snippet": "",
            "last_text": "",
            "model": model,
            "reasoning_effort": reasoning_effort,
            "resume_last": resume_last,
            "resume_id": resume_id,
        }
    with SESSION_HISTORY_LOCK:
        _upsert_session_history_unlocked(
            name,
            {
                "session": name,
                "cwd": cwd,
                "state": "starting",
                "updated_at": time.time(),
                "last_seen_at": time.time(),
                "snippet": "",
                "model": model,
                "reasoning_effort": reasoning_effort,
                "created_at": time.time(),
                "active": True,
                "closed_at": None,
                "resume_id": resume_id or None,
            },
        )
    return {
        "ok": True,
        "session": name,
        "cwd": cwd,
        "model": model,
        "reasoning_effort": reasoning_effort,
        "resume_last": resume_last,
        "resume_id": resume_id or None,
    }

@app.delete("/codex/session/{session}")
def codex_session_close(session: str):
    session = _validate_session_name(session)
    with SESSIONS_LOCK:
        prev = dict(SESSIONS.get(session) or {})
    r = run_wsl_bash(f"tmux kill-session -t {session}", timeout_s=20)
    if r.get("exit_code") != 0:
        stderr = (r.get("stderr") or "").lower()
        if "can't find session" in stderr or "no such session" in stderr:
            return {"ok": False, "error": "not_found", "detail": f"Session '{session}' not found."}
        return {"ok": False, "error": "close_failed", "raw": r}
    with SESSIONS_LOCK:
        SESSIONS.pop(session, None)
    with SESSION_HISTORY_LOCK:
        _upsert_session_history_unlocked(
            session,
            {
                **prev,
                "session": session,
                "active": False,
                "closed_at": time.time(),
                "updated_at": time.time(),
            },
        )
    return {"ok": True, "session": session}

def _session_pane(session: str) -> Optional[Dict[str, Any]]:
    panes = _tmux_list_panes(session=session)
    if not panes:
        return None
    panes.sort(key=lambda p: p.get("active"), reverse=True)
    return panes[0]


def _session_stream_interval_ms(profile: str) -> int:
    selected = str(profile or "").strip().lower()
    if selected == "fast":
        return 220
    if selected == "battery":
        return 850
    return 420


def _session_stream_max_chars(profile: str) -> int:
    selected = str(profile or "").strip().lower()
    if selected == "fast":
        return 18000
    if selected == "battery":
        return 9000
    return 12000


def _session_stream_state_unlocked(session: str) -> Dict[str, Any]:
    session_id = _validate_session_name(session)
    state = SESSION_STREAM_STATES.get(session_id)
    if state is None:
        state = {
            "seq": 0,
            "last_text": "",
            "events": [],
            "updated_at": time.time(),
        }
        SESSION_STREAM_STATES[session_id] = state
    return state


def _session_stream_event_payload(
    *,
    session: str,
    pane_id: str,
    seq: int,
    event_type: str,
    text: str,
    profile: str = "",
    detail: str = "",
    state: str = "",
    current_command: str = "",
) -> Dict[str, Any]:
    payload = {
        "session": session,
        "pane_id": pane_id,
        "seq": seq,
        "type": event_type,
        "text": text,
        "detail": detail,
        "ts": time.time(),
    }
    if profile:
        payload["profile"] = profile
    if state:
        payload["state"] = state
    if current_command:
        payload["current_command"] = current_command
    return payload


def _publish_session_stream_snapshot(
    session: str,
    pane_id: str,
    text: str,
    *,
    screen_state: str = "",
    current_command: str = "",
) -> Optional[Dict[str, Any]]:
    session_id = _validate_session_name(session)
    pane_value = _validate_pane_id(pane_id)
    with SESSION_STREAM_LOCK:
        stream_state = _session_stream_state_unlocked(session_id)
        previous = str(stream_state.get("last_text") or "")
        if text == previous:
            return None
        if stream_state["seq"] == 0:
            event_type = "snapshot"
            payload_text = text
        elif text.startswith(previous):
            event_type = "append"
            payload_text = text[len(previous):]
        else:
            event_type = "replace"
            payload_text = text
        stream_state["seq"] = int(stream_state.get("seq") or 0) + 1
        event = _session_stream_event_payload(
            session=session_id,
            pane_id=pane_value,
            seq=stream_state["seq"],
            event_type=event_type,
            text=payload_text,
            state=screen_state,
            current_command=current_command,
        )
        stream_state["last_text"] = text
        stream_state["updated_at"] = time.time()
        stream_state["events"].append(event)
        if len(stream_state["events"]) > SESSION_STREAM_REPLAY_MAX:
            stream_state["events"] = stream_state["events"][-SESSION_STREAM_REPLAY_MAX:]
        return dict(event)


def _session_stream_replay(session: str, since_seq: int) -> Tuple[List[Dict[str, Any]], Optional[Dict[str, Any]]]:
    with SESSION_STREAM_LOCK:
        state = _session_stream_state_unlocked(session)
        events = list(state.get("events") or [])
        if since_seq <= 0:
            return [], None
        replay = [dict(event) for event in events if int(event.get("seq") or 0) > since_seq]
        if replay:
            oldest = int(replay[0].get("seq") or 0)
            if oldest <= since_seq + 1:
                return replay, None
        if int(state.get("seq") or 0) <= 0:
            return [], None
        pane = _session_pane(session)
        pane_id = _validate_pane_id(str((pane or {}).get("pane_id") or "%0")) if pane else "%0"
        snapshot = _session_stream_event_payload(
            session=session,
            pane_id=pane_id,
            seq=int(state.get("seq") or 0),
            event_type="snapshot",
            text=str(state.get("last_text") or ""),
            detail="replay_reset",
        )
        return [], snapshot


def _maybe_repair_codex_session_reasoning(session: str, pane_id: str) -> Dict[str, Any]:
    """
    Some older sessions were started/applied with xhigh on codex-* models.
    Those models only support low/medium/high and fail on prompt send.
    Best effort: if we detect stale reasoning in server session metadata,
    send one profile repair command before user prompt delivery.
    """
    with SESSIONS_LOCK:
        prev = dict(SESSIONS.get(session) or {})

    model_raw = str(prev.get("model") or "").strip()
    if not model_raw:
        return {"ok": True, "applied": False}

    try:
        model = _normalize_codex_model(model_raw)
    except Exception:
        return {"ok": True, "applied": False}

    if not _is_codex_family_model(model):
        return {"ok": True, "applied": False}

    current_effort_raw = str(prev.get("reasoning_effort") or "").strip().lower()
    normalized_effort = _normalize_reasoning_effort(current_effort_raw, model=model)
    if current_effort_raw == normalized_effort:
        return {"ok": True, "applied": False, "model": model, "reasoning_effort": normalized_effort}

    apply_cmd = f"/model {model} {normalized_effort}"
    sent = _tmux_send_text(pane_id, apply_cmd, codex_mode=True, timeout_s=20)
    if sent.get("exit_code") != 0:
        return {"ok": False, "applied": False, "error": "profile_repair_failed", "raw": sent}

    with SESSIONS_LOCK:
        prev_now = SESSIONS.get(session, {})
        SESSIONS[session] = {
            **prev_now,
            "session": session,
            "updated_at": time.time(),
            "model": model,
            "reasoning_effort": normalized_effort,
        }

    return {
        "ok": True,
        "applied": True,
        "model": model,
        "reasoning_effort": normalized_effort,
        "applied_command": apply_cmd,
    }


def _tmux_send_text(pane_id: str, text: str, *, codex_mode: Optional[bool] = None, timeout_s: int = 30) -> Dict[str, Any]:
    pane_id = _validate_pane_id(pane_id)
    if len(text) > 20000:
        raise HTTPException(status_code=400, detail="Text too long (max 20000 chars).")

    use_codex = _pane_is_codex_like(pane_id) if codex_mode is None else bool(codex_mode)
    for chunk in _iter_text_chunks(text, 400):
        send_cmd = f"tmux send-keys -t {pane_id} -l " + _bash_quote(chunk)
        send_result = run_wsl_bash(send_cmd, timeout_s=timeout_s)
        if send_result.get("exit_code") != 0:
            return send_result

    if use_codex:
        enter_cmd = (
            f"tmux send-keys -t {pane_id} Enter ; "
            f"sleep 0.2 ; "
            f"tmux send-keys -t {pane_id} Enter"
        )
    else:
        enter_cmd = f"tmux send-keys -t {pane_id} Enter"
    return run_wsl_bash(enter_cmd, timeout_s=timeout_s)


def _parse_share_command(raw_text: str) -> Dict[str, Any]:
    text = str(raw_text or "").strip()
    if not text:
        return {"is_command": False}
    aliases_default = {"codrex-send", "/codrex-send", "/send-file", "/share-file"}
    aliases_telegram = {"tgsend", "/tgsend", "telegram-send", "/telegram-send"}
    first_token = text.split(None, 1)[0].strip().lower() if text else ""
    if first_token not in aliases_default and first_token not in aliases_telegram:
        return {"is_command": False}
    try:
        parts = shlex.split(text, posix=True)
    except Exception as e:
        return {"is_command": True, "ok": False, "detail": f"Could not parse command: {type(e).__name__}: {e}"}
    if not parts:
        return {"is_command": False}

    cmd = parts[0].strip().lower()
    if cmd in aliases_telegram:
        default_send_telegram = True
    elif cmd in aliases_default:
        default_send_telegram = bool(CODEX_TELEGRAM_DEFAULT_SEND)
    else:
        return {"is_command": False}
    if len(parts) < 2:
        return {
            "is_command": True,
            "ok": False,
            "detail": "Missing file path. Usage: codrex-send|tgsend <path> [--title ...] [--expires <hours>] [--telegram|--no-telegram] [--caption ...]",
        }

    path = parts[1].strip()
    title = ""
    expires_hours: Optional[int] = None
    send_telegram = default_send_telegram
    caption = ""
    i = 2
    while i < len(parts):
        token = parts[i].strip().lower()
        if token == "--title":
            if i + 1 >= len(parts):
                return {"is_command": True, "ok": False, "detail": "Missing value for --title."}
            title = parts[i + 1]
            i += 2
            continue
        if token == "--expires":
            if i + 1 >= len(parts):
                return {"is_command": True, "ok": False, "detail": "Missing value for --expires."}
            try:
                expires_hours = int(parts[i + 1])
            except Exception:
                return {"is_command": True, "ok": False, "detail": "Invalid --expires value. Use an integer number of hours."}
            i += 2
            continue
        if token in {"--telegram", "--tg"}:
            send_telegram = True
            i += 1
            continue
        if token in {"--no-telegram", "--no-tg"}:
            send_telegram = False
            i += 1
            continue
        if token == "--caption":
            if i + 1 >= len(parts):
                return {"is_command": True, "ok": False, "detail": "Missing value for --caption."}
            caption = parts[i + 1]
            i += 2
            continue
        return {"is_command": True, "ok": False, "detail": f"Unknown option: {parts[i]}"}

    return {
        "is_command": True,
        "ok": True,
        "path": path,
        "title": title,
        "expires_hours": expires_hours,
        "send_telegram": send_telegram,
        "default_send_telegram": default_send_telegram,
        "caption": caption,
    }

@app.post("/codex/session/{session}/send")
def codex_session_send(session: str, text: str = Body(..., media_type="text/plain")):
    session = _validate_session_name(session)
    pane = _session_pane(session)
    if not pane:
        return {"ok": False, "error": "not_found", "detail": f"Session '{session}' has no panes."}

    share_cmd = _parse_share_command(text)
    if share_cmd.get("is_command"):
        if not share_cmd.get("ok"):
            return {
                "ok": False,
                "error": "share_command_invalid",
                "detail": share_cmd.get("detail") or "Invalid share command.",
            }
        try:
            item = _create_shared_outbox_item(
                share_cmd.get("path") or "",
                title=share_cmd.get("title") or "",
                expires_hours=share_cmd.get("expires_hours"),
                created_by=f"session:{session}",
                session=session,
                source_kind="command",
            )
        except HTTPException as e:
            return {"ok": False, "error": "share_create_failed", "detail": str(e.detail)}
        session_file = None
        try:
            session_file = _create_session_file_item(
                session,
                str(item.get("wsl_path") or ""),
                title=str(item.get("title") or ""),
                expires_hours=share_cmd.get("expires_hours"),
                created_by=f"session:{session}",
                allow_directory=bool(item.get("item_kind") == "directory"),
                source_kind="command",
            )
        except HTTPException:
            session_file = None
        telegram_result = None
        detail = "Shared file added to mobile inbox."
        if share_cmd.get("send_telegram"):
            telegram_result = _telegram_send_shared_item(item, caption_override=str(share_cmd.get("caption") or ""))
            if telegram_result.get("ok"):
                detail = "Shared file added to mobile inbox and sent to Telegram."
            else:
                detail = f"Shared file added to mobile inbox. Telegram send failed: {telegram_result.get('detail') or telegram_result.get('error') or 'unknown error'}"
        return {
            "ok": True,
            "session": session,
            "shared_file": _public_shared_item(item),
            "session_file": _public_session_file_item(session, session_file),
            "telegram": telegram_result,
            "detail": detail,
        }

    repair = _maybe_repair_codex_session_reasoning(session, pane["pane_id"])
    repair_applied = bool(repair.get("applied"))
    repair_warning = ""
    if not repair.get("ok"):
        repair_warning = "Could not auto-repair session profile before send."

    # Codex TUI uses "blank-line Enter" submission, so always use codex mode here.
    p = _tmux_send_text(pane["pane_id"], text, codex_mode=True, timeout_s=20)
    if p.get("exit_code") != 0:
        return {"ok": False, "error": "send_failed", "raw": p}
    sent_at = time.time()
    resume_id = ""
    with SESSIONS_LOCK:
        prev = SESSIONS.get(session, {})
        next_record = {
            **prev,
            "session": session,
            "updated_at": sent_at,
            "last_user_prompt": text,
            "last_prompt_at": sent_at,
        }
        resume_id = _resolve_session_resume_id(session, next_record)
        if resume_id:
            next_record["resume_id"] = resume_id
        SESSIONS[session] = next_record
    with SESSION_HISTORY_LOCK:
        _upsert_session_history_unlocked(
            session,
            {
                "session": session,
                "updated_at": sent_at,
                "last_user_prompt": text,
                "last_prompt_at": sent_at,
                "resume_id": resume_id or None,
                "active": True,
            },
        )
    with LOOP_CONTROL_LOCK:
        _load_loop_control_unlocked()
        state = _get_loop_session_unlocked(session)
        state["awaiting_reply"] = False
        state["last_prompt_at"] = _now_ms()
        state["last_handled_fingerprint"] = ""
        _loop_commit_session_state_unlocked(session, state)
        _persist_loop_control_unlocked()
    out: Dict[str, Any] = {"ok": True, "session": session}
    if repair_applied:
        out["profile_repaired"] = True
        out["profile_model"] = repair.get("model")
        out["profile_reasoning_effort"] = repair.get("reasoning_effort")
    if repair_warning:
        out["profile_repair_warning"] = repair_warning
    if resume_id:
        out["resume_id"] = resume_id
    return out


@app.post("/codex/session/{session}/profile")
def codex_session_apply_profile(session: str, payload: Optional[Dict[str, Any]] = Body(default=None)):
    """
    Best-effort live profile update for a running Codex session.

    We send the CLI slash command inline to the active Codex pane:
      /model <model> <reasoning_effort>

    This depends on the running Codex CLI supporting inline /model args.
    """
    session = _validate_session_name(session)
    payload = payload or {}
    model = _normalize_codex_model(payload.get("model"))
    reasoning_effort = _normalize_reasoning_effort(
        payload.get("reasoning_effort") or payload.get("model_reasoning_effort"),
        model=model,
    )
    pane = _session_pane(session)
    if not pane:
        return {"ok": False, "error": "not_found", "detail": f"Session '{session}' has no panes."}

    apply_cmd = f"/model {model} {reasoning_effort}"
    sent = _tmux_send_text(pane["pane_id"], apply_cmd, codex_mode=True, timeout_s=20)
    if sent.get("exit_code") != 0:
        return {"ok": False, "error": "apply_failed", "raw": sent}

    with SESSIONS_LOCK:
        prev = SESSIONS.get(session, {})
        SESSIONS[session] = {
            **prev,
            "session": session,
            "updated_at": time.time(),
            "model": model,
            "reasoning_effort": reasoning_effort,
        }

    return {
        "ok": True,
        "session": session,
        "model": model,
        "reasoning_effort": reasoning_effort,
        "applied_command": apply_cmd,
        "detail": "Best effort: sent /model command to running Codex session. Verify with /status in transcript.",
    }

@app.post("/codex/session/{session}/ctrlc")
def codex_session_ctrlc(session: str):
    session = _validate_session_name(session)
    pane = _session_pane(session)
    if not pane:
        return {"ok": False, "error": "not_found", "detail": f"Session '{session}' has no panes."}
    p = run_wsl_bash(f"tmux send-keys -t {pane['pane_id']} C-c", timeout_s=20)
    if p.get("exit_code") != 0:
        return {"ok": False, "error": "ctrlc_failed", "raw": p}
    return {"ok": True, "session": session}

@app.post("/codex/session/{session}/interrupt")
def codex_session_interrupt(session: str):
    """
    Interrupt Codex generation (preferred over Ctrl+C for the Codex TUI).
    Codex itself suggests: "esc to interrupt".
    """
    session = _validate_session_name(session)
    pane = _session_pane(session)
    if not pane:
        return {"ok": False, "error": "not_found", "detail": f"Session '{session}' has no panes."}
    p = run_wsl_bash(f"tmux send-keys -t {pane['pane_id']} Escape", timeout_s=20)
    if p.get("exit_code") != 0:
        return {"ok": False, "error": "interrupt_failed", "raw": p}
    return {"ok": True, "session": session}

@app.post("/codex/session/{session}/enter")
def codex_session_enter(session: str):
    """
    Send a single Enter key to the Codex pane.
    Useful for confirmations/prompts that require Enter without submitting a full message.
    """
    session = _validate_session_name(session)
    pane = _session_pane(session)
    if not pane:
        return {"ok": False, "error": "not_found", "detail": f"Session '{session}' has no panes."}
    p = run_wsl_bash(f"tmux send-keys -t {pane['pane_id']} Enter", timeout_s=20)
    if p.get("exit_code") != 0:
        return {"ok": False, "error": "enter_failed", "raw": p}
    return {"ok": True, "session": session}

@app.post("/codex/session/{session}/key")
def codex_session_key(session: str, payload: Dict[str, Any] = Body(...)):
    """
    Send a single navigation key to the Codex pane.
    Supported keys: up, down, left, right.
    """
    session = _validate_session_name(session)
    pane = _session_pane(session)
    if not pane:
        return {"ok": False, "error": "not_found", "detail": f"Session '{session}' has no panes."}

    raw_key = str((payload or {}).get("key") or "").strip().lower()
    key_map = {
        "up": "Up",
        "down": "Down",
        "left": "Left",
        "right": "Right",
        "arrowup": "Up",
        "arrowdown": "Down",
        "arrowleft": "Left",
        "arrowright": "Right",
    }
    tmux_key = key_map.get(raw_key)
    if not tmux_key:
        raise HTTPException(status_code=400, detail="Unsupported key. Use: up, down, left, right.")

    p = run_wsl_bash(f"tmux send-keys -t {pane['pane_id']} {tmux_key}", timeout_s=20)
    if p.get("exit_code") != 0:
        return {"ok": False, "error": "key_failed", "raw": p}
    return {"ok": True, "session": session, "key": raw_key}

@app.get("/codex/session/{session}/screen")
def codex_session_screen(session: str):
    session = _validate_session_name(session)
    _host_keep_awake_pulse(force=True)
    pane = _session_pane(session)
    if not pane:
        with SESSIONS_LOCK:
            prev = dict(SESSIONS.get(session) or {})
            if prev:
                SESSIONS[session] = {
                    **prev,
                    "session": session,
                    "state": "recovering",
                    "updated_at": time.time(),
                }
                with SESSION_HISTORY_LOCK:
                    _upsert_session_history_unlocked(
                        session,
                        {
                            **prev,
                            "session": session,
                            "state": "recovering",
                            "updated_at": time.time(),
                            "active": True,
                        },
                    )
                cached_text = str(prev.get("last_text") or prev.get("snippet") or "")
                return {
                    "ok": True,
                    "session": session,
                    "pane_id": str(prev.get("pane_id") or ""),
                    "current_command": str(prev.get("current_command") or ""),
                    "state": "recovering",
                    "text": cached_text,
                    "detail": f"Session '{session}' has no panes. Returning cached screen while recovering.",
                }
        return {"ok": False, "error": "not_found", "detail": f"Session '{session}' has no panes."}
    # Full pane capture is needed for Codex because it renders in the alternate screen.
    text = _capture_pane_full(pane["pane_id"], max_chars=25000)
    snippet = _capture_snippet(pane["pane_id"], lines=80)
    state = _infer_progress_state(text or snippet, pane.get("current_command", ""))
    with SESSIONS_LOCK:
        prev = SESSIONS.get(session, {})
        resume_id = _resolve_session_resume_id(session, prev)
        SESSIONS[session] = {
            **prev,
            "session": session,
            "state": state,
            "last_text": text or snippet,
            "updated_at": time.time(),
            "last_seen_at": time.time(),
            "current_command": pane.get("current_command", ""),
            "snippet": (text or snippet).splitlines()[-1][:240] if (text or snippet) else "",
            "model": prev.get("model") or CODEX_DEFAULT_MODEL,
            "reasoning_effort": prev.get("reasoning_effort") or CODEX_DEFAULT_REASONING_EFFORT,
            "resume_id": resume_id or prev.get("resume_id") or "",
        }
        next_record = dict(SESSIONS[session])
    with SESSION_HISTORY_LOCK:
        _upsert_session_history_unlocked(
            session,
            {
                **next_record,
                "active": True,
                "closed_at": None,
            },
        )
    _publish_session_stream_snapshot(
        session,
        pane["pane_id"],
        text or snippet,
        screen_state=state,
        current_command=pane.get("current_command", ""),
    )
    return {
        "ok": True,
        "session": session,
        "pane_id": pane["pane_id"],
        "current_command": pane.get("current_command", ""),
        "state": state,
        "text": text or snippet,
        "resume_id": next_record.get("resume_id") or None,
    }


@app.websocket("/codex/session/{session}/ws")
async def codex_session_stream(websocket: WebSocket, session: str):
    session_id = str(session or "").strip()
    try:
        session_id = _validate_session_name(session_id)
    except HTTPException as exc:
        await websocket.accept()
        await websocket.send_json({"ok": False, "type": "error", "detail": exc.detail})
        await websocket.close(code=4400)
        return

    await websocket.accept()
    if not _is_valid_auth_token(_auth_token_from_websocket(websocket)):
        await websocket.send_json({"ok": False, "type": "error", "detail": "Login required."})
        await websocket.close(code=4401)
        return

    selected_profile = str(websocket.query_params.get("profile") or "balanced").strip().lower()
    if selected_profile not in {"fast", "balanced", "battery"}:
        selected_profile = "balanced"
    try:
        since_seq = int(str(websocket.query_params.get("since_seq") or "0").strip() or "0")
    except Exception:
        since_seq = 0
    interval_ms = _session_stream_interval_ms(selected_profile)
    last_keepalive = 0.0
    waiting_for_pane = False

    try:
        _host_keep_awake_pulse(force=True)
        with SESSION_STREAM_LOCK:
            state = _session_stream_state_unlocked(session_id)
            hello_payload = _session_stream_event_payload(
                session=session_id,
                pane_id="",
                seq=int(state.get("seq") or 0),
                event_type="hello",
                text="",
                profile=selected_profile,
                detail="connected",
            )
        await websocket.send_json({"ok": True, **hello_payload})

        replay_events, replay_snapshot = _session_stream_replay(session_id, since_seq)
        for event in replay_events:
            await websocket.send_json({"ok": True, **event})
        if replay_snapshot:
            await websocket.send_json({"ok": True, **replay_snapshot})

        if not replay_events and not replay_snapshot:
            pane = _session_pane(session_id)
            if pane:
                initial = await asyncio.to_thread(_stream_capture_pane_text, pane["pane_id"], _session_stream_max_chars(selected_profile))
                if initial.get("ok"):
                    current_text = str(initial.get("text") or "")
                    current_state = _infer_progress_state(current_text, pane.get("current_command", ""))
                    event = await asyncio.to_thread(
                        _publish_session_stream_snapshot,
                        session_id,
                        pane["pane_id"],
                        current_text,
                        screen_state=current_state,
                        current_command=pane.get("current_command", ""),
                    )
                    if event:
                        await websocket.send_json({"ok": True, **event, "profile": selected_profile})

        while True:
            _host_keep_awake_pulse()
            pane = _session_pane(session_id)
            if not pane:
                if not waiting_for_pane:
                    waiting_for_pane = True
                    await websocket.send_json(
                        {
                            "ok": True,
                            **_session_stream_event_payload(
                                session=session_id,
                                pane_id="",
                                seq=0,
                                event_type="status",
                                text="",
                                profile=selected_profile,
                                detail="waiting_for_pane",
                                state="starting",
                            ),
                        }
                    )
                await asyncio.sleep(max(0.6, interval_ms / 1000.0))
                continue

            waiting_for_pane = False
            capture = await asyncio.to_thread(_stream_capture_pane_text, pane["pane_id"], _session_stream_max_chars(selected_profile))
            if not capture.get("ok"):
                await websocket.send_json(
                    {
                        "ok": False,
                        **_session_stream_event_payload(
                            session=session_id,
                            pane_id=pane["pane_id"],
                            seq=0,
                            event_type="error",
                            text="",
                            profile=selected_profile,
                            detail=str(capture.get("error") or "capture_failed"),
                        ),
                    }
                )
                await asyncio.sleep(max(1.0, interval_ms / 1000.0))
                continue

            text = str(capture.get("text") or "")
            current_command = str(pane.get("current_command") or "")
            current_state = _infer_progress_state(text, current_command)
            with SESSIONS_LOCK:
                prev = SESSIONS.get(session_id, {})
                SESSIONS[session_id] = {
                    **prev,
                    "session": session_id,
                    "pane_id": pane["pane_id"],
                    "current_command": current_command,
                    "cwd": pane.get("current_path", ""),
                    "state": current_state,
                    "updated_at": time.time(),
                    "last_seen_at": time.time(),
                    "snippet": text.splitlines()[-1][:240] if text else "",
                    "last_text": text,
                    "model": prev.get("model") or CODEX_DEFAULT_MODEL,
                    "reasoning_effort": prev.get("reasoning_effort") or CODEX_DEFAULT_REASONING_EFFORT,
                }
            event = await asyncio.to_thread(
                _publish_session_stream_snapshot,
                session_id,
                pane["pane_id"],
                text,
                screen_state=current_state,
                current_command=current_command,
            )
            if event:
                await websocket.send_json({"ok": True, **event, "profile": selected_profile})
                last_keepalive = time.time()
            elif time.time() - last_keepalive > 10:
                with SESSION_STREAM_LOCK:
                    seq = int((_session_stream_state_unlocked(session_id).get("seq") or 0))
                await websocket.send_json(
                    {
                        "ok": True,
                        **_session_stream_event_payload(
                            session=session_id,
                            pane_id=pane["pane_id"],
                            seq=seq,
                            event_type="keepalive",
                            text="",
                            profile=selected_profile,
                            detail="idle",
                            state=current_state,
                            current_command=current_command,
                        ),
                    }
                )
                last_keepalive = time.time()
            await asyncio.sleep(interval_ms / 1000.0)
    except WebSocketDisconnect:
        return

@app.get("/codex/sessions")
def codex_sessions_live():
    _host_keep_awake_pulse()
    panes = _tmux_list_panes()
    live: List[Dict[str, Any]] = []
    now = time.time()
    seen_sessions = set()
    with SESSIONS_LOCK:
        known_items = dict(SESSIONS)
    for p in panes:
        session = p.get("session", "")
        cc = (p.get("current_command") or "").lower()
        known = session in known_items
        codex_like = session.startswith("codex_") or cc == "codex"
        if not (known or codex_like):
            continue
        seen_sessions.add(session)
        prev = known_items.get(session, {})
        snippet = _session_cached_snippet(prev)
        state = _session_summary_state(prev, p.get("current_command", ""))
        item = {
            "session": session,
            "pane_id": p["pane_id"],
            "current_command": p.get("current_command", ""),
            "cwd": p.get("current_path", ""),
            "state": state,
            "updated_at": now,
            "last_seen_at": now,
            "snippet": snippet,
            "model": prev.get("model") or CODEX_DEFAULT_MODEL,
            "reasoning_effort": prev.get("reasoning_effort") or CODEX_DEFAULT_REASONING_EFFORT,
        }
        resume_id = _resolve_session_resume_id(session, prev)
        if resume_id:
            item["resume_id"] = resume_id
        with LOOP_CONTROL_LOCK:
            item["loop"] = _public_loop_session_state_unlocked(session)
        live.append(item)
        with SESSIONS_LOCK:
            SESSIONS[session] = {**prev, **item}
        with SESSION_HISTORY_LOCK:
            _upsert_session_history_unlocked(
                session,
                {
                    **item,
                    "active": True,
                    "closed_at": None,
                },
            )

    # Keep known sessions visible during transient pane discovery gaps.
    for session, prev in known_items.items():
        if session in seen_sessions:
            continue
        if not str(session or "").startswith("codex_"):
            continue
        last_seen_at = float(prev.get("last_seen_at") or prev.get("updated_at") or prev.get("created_at") or now)
        age_s = max(0.0, now - last_seen_at)
        if age_s > SESSION_STALE_TTL_S:
            with SESSIONS_LOCK:
                if session in SESSIONS and session not in seen_sessions:
                    SESSIONS.pop(session, None)
            with SESSION_HISTORY_LOCK:
                _upsert_session_history_unlocked(
                    session,
                    {
                        **prev,
                        "session": session,
                        "active": False,
                        "closed_at": now,
                        "updated_at": now,
                    },
                )
            continue
        fallback_snippet = _session_cached_snippet(prev)
        fallback_state = str(prev.get("state") or "").strip().lower()
        if age_s > SESSION_RECOVERING_AFTER_S and fallback_state not in {"done", "error"}:
            fallback_state = "recovering"
        elif not fallback_state:
            fallback_state = "starting"
        fallback_item = {
            "session": session,
            "pane_id": str(prev.get("pane_id") or ""),
            "current_command": str(prev.get("current_command") or ""),
            "cwd": str(prev.get("cwd") or ""),
            "state": fallback_state or "starting",
            "updated_at": now,
            "last_seen_at": last_seen_at,
            "snippet": fallback_snippet,
            "model": prev.get("model") or CODEX_DEFAULT_MODEL,
            "reasoning_effort": prev.get("reasoning_effort") or CODEX_DEFAULT_REASONING_EFFORT,
        }
        resume_id = _resolve_session_resume_id(session, prev)
        if resume_id:
            fallback_item["resume_id"] = resume_id
        with LOOP_CONTROL_LOCK:
            fallback_item["loop"] = _public_loop_session_state_unlocked(session)
        live.append(fallback_item)
        with SESSION_HISTORY_LOCK:
            _upsert_session_history_unlocked(
                session,
                {
                    **prev,
                    **fallback_item,
                    "active": True,
                },
            )
    live.sort(key=lambda x: x["session"])
    active_sessions = {str(item.get("session") or "").strip() for item in live}
    recent_closed: List[Dict[str, Any]] = []
    with SESSION_HISTORY_LOCK:
        _load_session_history_unlocked()
        for item in SESSION_HISTORY_DATA.get("items") or []:
            session = str(item.get("session") or "").strip()
            if not session or session in active_sessions:
                continue
            if not item.get("closed_at") and item.get("active", False):
                continue
            if not item.get("resume_id"):
                resume_id = _resolve_session_resume_id(session, item)
                if resume_id:
                    item["resume_id"] = resume_id
            public_item = _public_session_record(item)
            with LOOP_CONTROL_LOCK:
                public_item["loop"] = _public_loop_session_state_unlocked(session)
            recent_closed.append(public_item)
    return {
        "ok": True,
        "sessions": live,
        "recent_closed": recent_closed,
        "meta": {
            "total_sessions": len(live),
            "total_recent_closed": len(recent_closed),
            "background_mode": SESSION_BACKGROUND_MODE,
            "summary_updated_at": now,
        },
    }

@app.post("/codex/session/{session}/image")
async def codex_session_image(
    session: str,
    request: Request,
    file: UploadFile = File(...),
    prompt: str = Form(""),
    paste_desktop: bool = Form(True),
    delivery_mode: str = Form(""),
):
    session = _validate_session_name(session)
    pane = _session_pane(session)
    if not pane:
        return {"ok": False, "error": "not_found", "detail": f"Session '{session}' has no panes."}

    base_name = _safe_name(file.filename or "image")
    wsl_abs = _session_upload_path(session, base_name)
    unc = _wsl_unc_path(wsl_abs)
    os.makedirs(os.path.dirname(unc), exist_ok=True)
    with open(unc, "wb") as f:
        while True:
            chunk = await file.read(1024 * 1024)
            if not chunk:
                break
            f.write(chunk)
    try:
        session_file = _create_session_file_item(
            session,
            wsl_abs,
            title=base_name,
            created_by=f"session:{session}",
            source_kind="upload",
        )
    except HTTPException as exc:
        try:
            os.remove(unc)
        except Exception:
            pass
        return {"ok": False, "error": "upload_register_failed", "detail": str(exc.detail)}

    msg = (prompt or "").strip()
    mode = str(delivery_mode or "").strip().lower()
    if not mode:
        mode = "desktop_clipboard" if paste_desktop else "session_path"
    if mode not in {"desktop_clipboard", "session_path", "insert_path"}:
        raise HTTPException(status_code=400, detail="Invalid delivery_mode. Use: desktop_clipboard, insert_path, session_path.")

    if mode == "desktop_clipboard":
        if os.name != "nt":
            return {
                "ok": False,
                "error": "clipboard_paste_unavailable",
                "detail": "Desktop clipboard paste is available only on Windows host.",
                "saved_path": wsl_abs,
                "session_file": _public_session_file_item(session, session_file),
            }
        _require_desktop_enabled(request)
        pasted = _desktop_paste_image_file(unc)
        if pasted.get("exit_code") != 0:
            return {
                "ok": False,
                "error": "clipboard_paste_failed",
                "detail": (pasted.get("stderr") or pasted.get("stdout") or "clipboard_paste_failed").strip(),
                "saved_path": wsl_abs,
                "session_file": _public_session_file_item(session, session_file),
            }
        return {
            "ok": True,
            "session": session,
            "saved_path": wsl_abs,
            "session_file": _public_session_file_item(session, session_file),
            "paste_attempted": True,
            "paste_ok": True,
            "paste_error": "",
            "delivery_mode": "desktop_clipboard",
            "detail": "Image copied to desktop clipboard and Ctrl+V sent to focused window.",
        }

    if mode == "insert_path":
        insert_text = f"{wsl_abs} "
        if msg:
            insert_text = f"{msg} {wsl_abs} "
        insert = run_wsl_bash(
            f"tmux send-keys -t {pane['pane_id']} -l " + _bash_quote(insert_text),
            timeout_s=20,
        )
        if insert.get("exit_code") != 0:
            return {
                "ok": False,
                "error": "insert_failed",
                "saved_path": wsl_abs,
                "session_file": _public_session_file_item(session, session_file),
                "raw": insert,
            }
        return {
            "ok": True,
            "session": session,
            "saved_path": wsl_abs,
            "session_file": _public_session_file_item(session, session_file),
            "paste_attempted": False,
            "paste_ok": False,
            "paste_error": "",
            "delivery_mode": "insert_path",
            "detail": "Image path inserted into session composer. Continue typing, then send.",
        }

    repair = _maybe_repair_codex_session_reasoning(session, pane["pane_id"])
    repair_applied = bool(repair.get("applied"))
    repair_warning = ""
    if not repair.get("ok"):
        repair_warning = "Could not auto-repair session profile before image send."

    if msg:
        text = f"{msg}\n\nImage path: {wsl_abs}"
    else:
        text = f"Please inspect this image: {wsl_abs}"
    cmd = (
        f"tmux send-keys -t {pane['pane_id']} -l " + _bash_quote(text) + " ; "
        f"tmux send-keys -t {pane['pane_id']} Enter ; "
        f"sleep 0.2 ; "
        f"tmux send-keys -t {pane['pane_id']} Enter"
    )
    send = run_wsl_bash(cmd, timeout_s=20)
    if send.get("exit_code") != 0:
        return {
            "ok": False,
            "error": "send_failed",
            "saved_path": wsl_abs,
            "session_file": _public_session_file_item(session, session_file),
            "raw": send,
        }
    out: Dict[str, Any] = {
        "ok": True,
        "session": session,
        "saved_path": wsl_abs,
        "session_file": _public_session_file_item(session, session_file),
        "paste_attempted": False,
        "paste_ok": False,
        "paste_error": "",
        "delivery_mode": "session_path",
        "profile_repaired": repair_applied,
    }
    if repair_warning:
        out["profile_repair_warning"] = repair_warning
    return out


@app.post("/desktop/paste/image")
async def desktop_paste_image(
    request: Request,
    file: UploadFile = File(...),
):
    _ensure_windows_host()
    _require_desktop_enabled(request)
    _host_keep_awake_pulse(force=True)
    _desktop_release_alt_if_held()
    os.makedirs(CODEX_HOST_PASTE_CACHE_DIR, exist_ok=True)
    file_name = file.filename or "image.png"
    target_path = _host_unique_target_path(CODEX_HOST_PASTE_CACHE_DIR, file_name)
    try:
        with open(target_path, "wb") as f:
            while True:
                chunk = await file.read(1024 * 1024)
                if not chunk:
                    break
                f.write(chunk)
    except Exception as exc:
        try:
            if os.path.exists(target_path):
                os.remove(target_path)
        except Exception:
            pass
        raise HTTPException(status_code=500, detail=f"Failed to stage desktop image paste: {type(exc).__name__}: {exc}")
    pasted, paste_diag = _desktop_run_remote_action(
        "desktop_paste_image",
        lambda: _desktop_paste_image_file(target_path),
        capture_probe=True,
    )
    if pasted.get("exit_code") != 0:
        return {
            "ok": False,
            "error": "desktop_image_paste_failed",
            "saved_path": target_path,
            "detail": (pasted.get("stderr") or pasted.get("stdout") or "desktop_image_paste_failed").strip(),
            "paste_ok": False,
            "target_process": str(pasted.get("target_process") or "").strip(),
            "target_family": str(pasted.get("target_family") or "").strip(),
            "target_label": str(pasted.get("target_label") or "").strip(),
            "paste_strategy": str(pasted.get("mode") or "").strip(),
            "diagnostics": paste_diag,
        }
    target_process = str(pasted.get("target_process") or "").strip()
    target_family = str(pasted.get("target_family") or "").strip().lower()
    target_label = str(pasted.get("target_label") or "").strip()
    paste_strategy = str(pasted.get("mode") or "clipboard_native_paste").strip()
    if paste_strategy == "powerpoint_com_paste":
        detail = "Image copied to the Windows clipboard and pasted into PowerPoint using the Office automation fallback."
    elif paste_strategy == "word_com_paste":
        detail = "Image copied to the Windows clipboard and pasted into Word using the Office automation fallback."
    elif paste_strategy == "wps_sendkeys_paste":
        detail = f"Image copied to the Windows clipboard and pasted into {target_label or 'the focused WPS window'} using the WPS-compatible paste path."
    elif paste_strategy == "onenote_sendkeys_paste":
        detail = "Image copied to the Windows clipboard and pasted into the focused OneNote window using the compatibility paste path."
    elif target_family == "onenote":
        detail = "Image copied to the Windows clipboard and pasted into the focused OneNote window."
    elif target_family == "wps_presentation":
        detail = "Image copied to the Windows clipboard and pasted into the focused WPS presentation window."
    elif target_family == "wps_document":
        detail = "Image copied to the Windows clipboard and pasted into the focused WPS document window."
    elif target_label:
        detail = f"Image copied to the Windows clipboard and pasted into {target_label}."
    else:
        detail = "Image copied to the Windows clipboard and pasted into the focused host app."
    return {
        "ok": True,
        "saved_path": target_path,
        "paste_ok": True,
        "detail": detail,
        "target_process": target_process,
        "target_family": target_family,
        "target_label": target_label,
        "paste_strategy": paste_strategy,
        "diagnostics": paste_diag,
    }


@app.get("/fs/list")
def fs_list(root: str = "workspace", path: str = ""):
    return _list_browser_entries(root, path)


@app.get("/codex/session/{session}/notes")
def codex_session_notes_get(session: str):
    session = _validate_session_name(session)
    with SESSION_NOTES_LOCK:
        _load_session_notes_unlocked()
        note = _get_session_note_unlocked(session)
    return {"ok": True, "session": session, "notes": note}


@app.post("/codex/session/{session}/notes")
def codex_session_notes_save(session: str, payload: Optional[Dict[str, Any]] = Body(default=None)):
    session = _validate_session_name(session)
    payload = payload or {}
    content = str(payload.get("content") or "")
    if len(content) > SESSION_NOTES_MAX_CHARS:
        raise HTTPException(status_code=400, detail=f"Notes are too long (max {SESSION_NOTES_MAX_CHARS} chars).")
    snapshot = str(payload.get("last_response_snapshot") or "")
    with SESSION_NOTES_LOCK:
        _load_session_notes_unlocked()
        note = _save_session_note_unlocked(session, content, snapshot)
    return {"ok": True, "session": session, "notes": note, "detail": "Notes saved."}


@app.post("/codex/session/{session}/notes/append-latest")
def codex_session_notes_append_latest(session: str):
    session = _validate_session_name(session)
    pane = _session_pane(session)
    if not pane:
        raise HTTPException(status_code=404, detail=f"Session '{session}' has no active pane.")
    latest_text = _capture_pane_full(pane["pane_id"], max_chars=25000)
    compact = _compact_assistant_snapshot_text(latest_text)
    if not compact:
        raise HTTPException(status_code=409, detail="No recent assistant response available.")
    with SESSION_NOTES_LOCK:
        _load_session_notes_unlocked()
        note = _append_session_note_snapshot_unlocked(session, compact)
    return {
        "ok": True,
        "session": session,
        "notes": note,
        "appended_text": compact,
        "detail": "Latest assistant response appended to notes.",
    }


@app.get("/codex/session/{session}/files")
def codex_session_files(session: str):
    session = _validate_session_name(session)
    with SESSION_FILES_LOCK:
        _load_session_files_unlocked()
        snapshot = _session_files_snapshot_unlocked(session)
    return {
        "ok": True,
        "session": session,
        "items": [_public_session_file_item(session, item) for item in snapshot.get("items") or []],
    }


@app.post("/codex/session/{session}/files/register")
def codex_session_files_register(session: str, payload: Optional[Dict[str, Any]] = Body(default=None)):
    session = _validate_session_name(session)
    payload = payload or {}
    path = str(payload.get("path") or "").strip()
    if not path:
        raise HTTPException(status_code=400, detail="path is required.")
    title = str(payload.get("title") or "").strip()
    allow_directory = bool(payload.get("allow_directory"))
    item = _create_session_file_item(
        session,
        path,
        title=title,
        expires_hours=payload.get("expires_hours"),
        created_by=str(payload.get("created_by") or f"session:{session}")[:64],
        allow_directory=allow_directory,
        source_kind="registered",
    )
    return {"ok": True, "session": session, "item": _public_session_file_item(session, item)}


@app.post("/codex/session/{session}/files/upload")
async def codex_session_files_upload(
    session: str,
    file: UploadFile = File(...),
    title: str = Form(""),
):
    session = _validate_session_name(session)
    base_name = _safe_name(file.filename or "upload.bin")
    wsl_abs = _session_upload_path(session, base_name)
    unc = _wsl_unc_path(wsl_abs)
    os.makedirs(os.path.dirname(unc), exist_ok=True)
    try:
        with open(unc, "wb") as handle:
            while True:
                chunk = await file.read(1024 * 1024)
                if not chunk:
                    break
                handle.write(chunk)
        item = _create_session_file_item(
            session,
            wsl_abs,
            title=title or base_name,
            created_by=f"session:{session}",
            source_kind="upload",
        )
    except HTTPException:
        try:
            if os.path.exists(unc):
                os.remove(unc)
        except Exception:
            pass
        raise
    except Exception as exc:
        try:
            if os.path.exists(unc):
                os.remove(unc)
        except Exception:
            pass
        raise HTTPException(status_code=500, detail=f"Failed to upload file: {type(exc).__name__}: {exc}")
    return {"ok": True, "session": session, "item": _public_session_file_item(session, item)}


@app.post("/codex/session/{session}/files/{file_id}/telegram")
def codex_session_files_telegram(session: str, file_id: str, payload: Optional[Dict[str, Any]] = Body(default=None)):
    session = _validate_session_name(session)
    payload = payload or {}
    caption = str(payload.get("caption") or "").strip()
    with SESSION_FILES_LOCK:
        _load_session_files_unlocked()
        item = _find_session_file_unlocked(session, file_id)
        if not item:
            raise HTTPException(status_code=404, detail="Session file not found.")
        snap = json.loads(json.dumps(item))
    telegram_result = _telegram_send_shared_item(snap, caption_override=caption)
    return {
        "ok": bool(telegram_result.get("ok")),
        "session": session,
        "item": _public_session_file_item(session, snap),
        "telegram": telegram_result,
        "detail": (
            "Sent to Telegram."
            if telegram_result.get("ok")
            else (telegram_result.get("detail") or telegram_result.get("error") or "Telegram send failed.")
        ),
    }


@app.delete("/codex/session/{session}/files/{file_id}")
def codex_session_files_delete(session: str, file_id: str):
    session = _validate_session_name(session)
    with SESSION_FILES_LOCK:
        _load_session_files_unlocked()
        existing = _find_session_file_unlocked(session, file_id)
        if not existing:
            return {"ok": False, "error": "not_found", "detail": "Session file not found."}
        item = _remove_session_file_unlocked(session, file_id)
        _persist_session_files_unlocked()
    if not item:
        return {"ok": False, "error": "not_found", "detail": "Session file not found."}

    deleted_source = False
    if _session_file_is_managed_upload(item):
        unc = _wsl_unc_path(str(item.get("wsl_path") or ""))
        try:
            if os.path.isdir(unc):
                shutil.rmtree(unc)
            elif os.path.exists(unc):
                os.remove(unc)
            deleted_source = True
        except Exception:
            deleted_source = False
    return {
        "ok": True,
        "session": session,
        "item": _public_session_file_item(session, item),
        "deleted_source": deleted_source,
    }


@app.get("/codex/session/{session}/files/{file_id}/download")
def codex_session_files_download(session: str, file_id: str):
    session = _validate_session_name(session)
    with SESSION_FILES_LOCK:
        _load_session_files_unlocked()
        item = _find_session_file_unlocked(session, file_id)
        if not item:
            raise HTTPException(status_code=404, detail="Session file not found.")
        if _share_expired(item):
            raise HTTPException(status_code=410, detail="Session file has expired.")
        snap = json.loads(json.dumps(item))
    wsl_abs = _resolve_session_access_path(str(snap.get("wsl_path") or ""))
    unc = _wsl_unc_path(wsl_abs)
    if not os.path.exists(unc):
        raise HTTPException(status_code=404, detail="Session file is no longer available.")
    if os.path.isdir(unc):
        raise HTTPException(status_code=400, detail="Session path is a directory.")
    filename = str(snap.get("file_name") or os.path.basename(wsl_abs.rstrip("/")) or "download.bin")
    return FileResponse(unc, filename=filename)

def _legacy_result_page(title: str, payload: Dict[str, Any], status_code: int = 200) -> HTMLResponse:
    pretty = html_std.escape(json.dumps(payload, ensure_ascii=False, indent=2))
    safe_title = html_std.escape(title or "Result")
    content = f"""
<!doctype html>
<html>
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>{safe_title}</title>
    <style>
      body {{
        margin: 0;
        padding: 16px;
        font-family: system-ui, -apple-system, Segoe UI, Roboto, sans-serif;
        background: #f8fafc;
        color: #0f172a;
      }}
      .card {{
        background: #fff;
        border: 1px solid #dfe4ea;
        border-radius: 12px;
        padding: 14px;
      }}
      pre {{
        margin: 0;
        white-space: pre-wrap;
        background: #0b0d12;
        color: #e5e7eb;
        padding: 12px;
        border-radius: 10px;
        border: 1px solid #1f2937;
        font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
      }}
      a {{
        display: inline-block;
        margin-top: 12px;
        color: #0b4f6c;
      }}
    </style>
  </head>
  <body>
    <div class="card">
      <h2 style="margin-top: 0;">{safe_title}</h2>
      <pre>{pretty}</pre>
      <a href="/">Back to controller</a>
    </div>
  </body>
</html>
    """.strip()
    return HTMLResponse(content=content, status_code=status_code, headers={"Cache-Control": "no-store"})

def _legacy_truthy(v: Any) -> bool:
    return _truthy_flag(v)

def _legacy_error_payload(exc: Exception) -> Dict[str, Any]:
    if isinstance(exc, HTTPException):
        return {
            "ok": False,
            "error": "http_error",
            "detail": getattr(exc, "detail", "request failed"),
            "status_code": getattr(exc, "status_code", 400),
        }
    return {"ok": False, "error": "exception", "detail": f"{type(exc).__name__}: {exc}"}

@app.post("/legacy/desktop/mode")
def legacy_desktop_mode(request: Request, enabled: str = Form(""), next: str = Form("/")):
    on = _set_desktop_global_enabled(_truthy_flag(enabled))
    resp = Response(status_code=303, headers={"Location": _safe_next_path(next)})
    resp.set_cookie(
        key=CODEX_DESKTOP_MODE_COOKIE,
        value="1" if on else "0",
        httponly=True,
        secure=_cookie_secure_for_request(request),
        samesite="lax",
        max_age=60 * 60 * 24 * 30,
    )
    return resp

@app.post("/legacy/desktop/click")
def legacy_desktop_click(
    request: Request,
    button: str = Form("left"),
    double: str = Form("0"),
    x: str = Form(""),
    y: str = Form(""),
):
    payload: Dict[str, Any] = {"button": (button or "left").strip().lower(), "double": _legacy_truthy(double)}
    xs = (x or "").strip()
    ys = (y or "").strip()
    if xs or ys:
        if not xs or not ys:
            return _legacy_result_page(
                "Desktop Click",
                {"ok": False, "error": "bad_request", "detail": "x and y must be provided together."},
                400,
            )
        try:
            payload["x"] = int(xs)
            payload["y"] = int(ys)
        except ValueError:
            return _legacy_result_page(
                "Desktop Click",
                {"ok": False, "error": "bad_request", "detail": "x and y must be integers."},
                400,
            )
    try:
        out = desktop_input_click(request, payload)
    except Exception as e:
        err = _legacy_error_payload(e)
        status = int(err.get("status_code") or 400)
        return _legacy_result_page("Desktop Click", err, status)
    return _legacy_result_page("Desktop Click", out, 200 if out.get("ok") else 400)

@app.post("/legacy/desktop/tap")
def legacy_desktop_tap(
    request: Request,
    tap_x: Optional[int] = Form(default=None, alias="tap.x"),
    tap_y: Optional[int] = Form(default=None, alias="tap.y"),
    x: Optional[int] = Form(default=None),
    y: Optional[int] = Form(default=None),
    render_w: int = Form(0),
    render_h: int = Form(0),
    button: str = Form("left"),
    double: str = Form("0"),
):
    px = tap_x if tap_x is not None else x
    py = tap_y if tap_y is not None else y
    if px is None or py is None:
        return _legacy_result_page(
            "Desktop Tap Click",
            {"ok": False, "error": "bad_request", "detail": "Tap coordinates are required."},
            400,
        )
    try:
        tx = int(px)
        ty = int(py)
        mon = _desktop_monitor()
        native_w = max(1, int(mon.get("width") or 1))
        native_h = max(1, int(mon.get("height") or 1))
        rw = int(render_w or 0)
        rh = int(render_h or 0)
        if rw > 0 and rh > 0:
            tx = int(round((tx * native_w) / rw))
            ty = int(round((ty * native_h) / rh))
        tx = _clamp(tx, 0, native_w - 1)
        ty = _clamp(ty, 0, native_h - 1)
        out = desktop_input_click(
            request,
            {
                "x": tx,
                "y": ty,
                "button": (button or "left").strip().lower(),
                "double": _legacy_truthy(double),
            }
        )
    except Exception as e:
        err = _legacy_error_payload(e)
        status = int(err.get("status_code") or 400)
        return _legacy_result_page("Desktop Tap Click", err, status)
    return _legacy_result_page("Desktop Tap Click", out, 200 if out.get("ok") else 400)

@app.post("/legacy/desktop/scroll")
def legacy_desktop_scroll(request: Request, delta: int = Form(0)):
    if int(delta) == 0:
        return _legacy_result_page(
            "Desktop Scroll",
            {"ok": False, "error": "bad_request", "detail": "delta is required."},
            400,
        )
    try:
        out = desktop_input_scroll(request, {"delta": int(delta)})
    except Exception as e:
        err = _legacy_error_payload(e)
        status = int(err.get("status_code") or 400)
        return _legacy_result_page("Desktop Scroll", err, status)
    return _legacy_result_page("Desktop Scroll", out, 200 if out.get("ok") else 400)

@app.post("/legacy/desktop/key")
def legacy_desktop_key(request: Request, key: str = Form("")):
    if not (key or "").strip():
        return _legacy_result_page(
            "Desktop Key",
            {"ok": False, "error": "bad_request", "detail": "key is required."},
            400,
        )
    try:
        out = desktop_input_key(request, {"key": key})
    except Exception as e:
        err = _legacy_error_payload(e)
        status = int(err.get("status_code") or 400)
        return _legacy_result_page("Desktop Key", err, status)
    return _legacy_result_page("Desktop Key", out, 200 if out.get("ok") else 400)

@app.post("/legacy/desktop/text")
def legacy_desktop_text(request: Request, text: str = Form("")):
    t = text or ""
    if not t.strip():
        return _legacy_result_page(
            "Desktop Text",
            {"ok": False, "error": "bad_request", "detail": "text is required."},
            400,
        )
    try:
        out = desktop_input_type(request, {"text": t})
    except Exception as e:
        err = _legacy_error_payload(e)
        status = int(err.get("status_code") or 400)
        return _legacy_result_page("Desktop Text", err, status)
    return _legacy_result_page("Desktop Text", out, 200 if out.get("ok") else 400)

@app.post("/legacy/codex/create")
def legacy_codex_create(name: str = Form(""), cwd: str = Form("")):
    payload: Dict[str, Any] = {}
    if (name or "").strip():
        payload["name"] = name.strip()
    if (cwd or "").strip():
        payload["cwd"] = cwd.strip()
    out = codex_session_create(payload)
    return _legacy_result_page("Create Codex Session", out, 200 if out.get("ok") else 400)

@app.post("/legacy/codex/send")
def legacy_codex_send(session: str = Form(""), text: str = Form("")):
    session = (session or "").strip()
    text = text or ""
    if not session:
        return _legacy_result_page("Send Prompt", {"ok": False, "error": "bad_request", "detail": "session is required"}, 400)
    if not text.strip():
        return _legacy_result_page("Send Prompt", {"ok": False, "error": "bad_request", "detail": "text is required"}, 400)
    out = codex_session_send(session, text)
    return _legacy_result_page("Send Prompt", out, 200 if out.get("ok") else 400)

@app.post("/legacy/codex/interrupt")
def legacy_codex_interrupt(session: str = Form("")):
    session = (session or "").strip()
    if not session:
        return _legacy_result_page("Interrupt Session", {"ok": False, "error": "bad_request", "detail": "session is required"}, 400)
    out = codex_session_interrupt(session)
    return _legacy_result_page("Interrupt Session", out, 200 if out.get("ok") else 400)

@app.post("/legacy/codex/close")
def legacy_codex_close(session: str = Form("")):
    session = (session or "").strip()
    if not session:
        return _legacy_result_page("Close Session", {"ok": False, "error": "bad_request", "detail": "session is required"}, 400)
    out = codex_session_close(session)
    return _legacy_result_page("Close Session", out, 200 if out.get("ok") else 400)

@app.get("/legacy/codex/screen")
def legacy_codex_screen(session: str = ""):
    session = (session or "").strip()
    if not session:
        return _legacy_result_page("Session Screen", {"ok": False, "error": "bad_request", "detail": "session is required"}, 400)
    out = codex_session_screen(session)
    if not out.get("ok"):
        return _legacy_result_page("Session Screen", out, 400)
    state = html_std.escape(str(out.get("state", "")))
    cmd = html_std.escape(str(out.get("current_command", "")))
    text = html_std.escape(str(out.get("text") or ""))
    safe_session = html_std.escape(session)
    content = f"""
<!doctype html>
<html>
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>Session Screen - {safe_session}</title>
    <style>
      body {{
        margin: 0;
        padding: 16px;
        font-family: system-ui, -apple-system, Segoe UI, Roboto, sans-serif;
        background: #f8fafc;
        color: #0f172a;
      }}
      .meta {{
        margin-bottom: 10px;
        color: #475569;
        font-size: 13px;
      }}
      pre {{
        white-space: pre-wrap;
        background: #0b0d12;
        color: #e5e7eb;
        padding: 12px;
        border-radius: 10px;
        border: 1px solid #1f2937;
        font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
      }}
      a {{
        display: inline-block;
        margin-top: 12px;
        color: #0b4f6c;
      }}
    </style>
  </head>
  <body>
    <h2 style="margin: 0 0 6px;">Session Screen: {safe_session}</h2>
    <div class="meta">state: {state} | cmd: {cmd}</div>
    <pre>{text}</pre>
    <a href="/">Back to controller</a>
  </body>
</html>
    """.strip()
    return HTMLResponse(content=content, headers={"Cache-Control": "no-store"})

# -------------------------
# Screenshot endpoint
# -------------------------
@app.get("/shot")
def shot():
    with mss() as sct:
        mon = _desktop_monitor()
        img = sct.grab(mon)
        png_bytes = to_png(img.rgb, img.size)
        return Response(
            content=png_bytes,
            media_type="image/png",
            headers={"Cache-Control": "no-store"},
        )

# -------------------------
# tmux endpoints
# -------------------------
def _sse_event_bytes(event: str, payload: Dict[str, Any]) -> bytes:
    """
    Minimal Server-Sent Events (SSE) encoder.

    Notes:
    - We send JSON on a single `data:` line. Newlines in `text` become `\\n` escapes.
    - This keeps the client-side parser simple and avoids multi-line SSE edge cases.
    """
    ev = (event or "message").replace("\n", " ").replace("\r", " ").strip() or "message"
    try:
        data = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    except Exception:
        data = json.dumps({"ok": False, "error": "sse_encode_failed"}, separators=(",", ":"))
    return f"event: {ev}\ndata: {data}\n\n".encode("utf-8")

def _attach_repr(payload: Dict[str, Any]) -> Dict[str, Any]:
    out = dict(payload)
    out["stdout_repr"] = repr(out.get("stdout") or "")
    out["stderr_repr"] = repr(out.get("stderr") or "")
    return out

@app.get("/tmux/debug")
def tmux_debug():
    checks = {
        "whoami": _attach_repr(run_wsl_bash("whoami")),
        "pwd": _attach_repr(run_wsl_bash("pwd")),
        "tmux_version": _attach_repr(run_wsl_bash("tmux -V")),
        "list_sessions": _attach_repr(run_wsl_bash(
            "tmux list-sessions -F '#{session_name}\\t#{session_id}\\t#{session_created}'"
        )),
        "list_panes": _attach_repr(run_wsl_bash(
            "tmux list-panes -a -F '#{session_name}\\t#{window_index}\\t#{pane_index}\\t#{pane_id}\\t#{pane_active}\\t#{pane_current_command}\\t#{pane_current_path}'"
        )),
    }
    return {
        "ok": True,
        "wsl_exe": _wsl_executable(),
        "distro": WSL_DISTRO,
        "checks": checks,
    }

@app.get("/tmux/health")
def tmux_health():
    r = run_wsl_bash("tmux list-sessions -F '#{session_name}'")
    if r["exit_code"] == 0:
        sessions = sorted({line.strip() for line in (r.get("stdout") or "").splitlines() if line.strip()})
        return {"ok": True, "state": "ok" if sessions else "empty", "count": len(sessions), "sessions": sessions}

    if not _tmux_server_running(r.get("stderr") or ""):
        return {"ok": True, "state": "no_server", "count": 0, "sessions": [], "raw": r}

    return {"ok": False, "error": "tmux_error", "raw": r}

@app.post("/tmux/session")
def tmux_create_session(payload: Optional[Dict[str, Any]] = Body(default=None)):
    payload = payload or {}
    name = (payload.get("name") or "").strip()
    if name:
        _validate_session_name(name)
        cmd = "tmux new-session -d -s " + name
    else:
        cmd = "tmux new-session -d"

    r = run_wsl_bash(cmd)
    if r["exit_code"] == 0:
        return {"ok": True, "name": name or None}

    stderr_lower = (r.get("stderr") or "").lower()
    if "duplicate session" in stderr_lower or "session already exists" in stderr_lower:
        return {"ok": False, "error": "session_exists", "detail": f"Session '{name}' already exists.", "raw": r}

    return {"ok": False, "error": "create_failed", "raw": r}

@app.delete("/tmux/session/{session}")
def tmux_close_session(session: str):
    session = _validate_session_name(session)
    r = run_wsl_bash(f"tmux kill-session -t {session}")

    if r["exit_code"] == 0:
        return {"ok": True, "session": session}

    stderr_lower = (r.get("stderr") or "").lower()
    if "can't find session" in stderr_lower or "no such session" in stderr_lower:
        return {"ok": False, "error": "not_found", "detail": f"Session '{session}' not found.", "raw": r}

    if not _tmux_server_running(r.get("stderr") or ""):
        return {"ok": False, "error": "tmux_server_not_running", "raw": r}

    return {"ok": False, "error": "close_failed", "raw": r}

@app.get("/tmux/panes")
def tmux_panes(session: Optional[str] = None):
    if session:
        _validate_session_name(session)
        cmd = (
            "tmux list-panes -t " + session +
            " -F '#{session_name}\t#{window_index}\t#{pane_index}\t#{pane_id}\t#{pane_active}\t#{pane_current_command}\t#{pane_current_path}'"
        )
    else:
        cmd = (
            "tmux list-panes -a "
            "-F '#{session_name}\t#{window_index}\t#{pane_index}\t#{pane_id}\t#{pane_active}\t#{pane_current_command}\t#{pane_current_path}'"
        )

    r = run_wsl_bash(cmd)
    panes: List[Dict[str, Any]] = []

    if r["exit_code"] == 0:
        if r["stdout"]:
            for line in r["stdout"].splitlines():
                # tmux may emit literal "\t" sequences; normalize to real tabs.
                parts = line.replace("\\t", "\t").split("\t")
                if len(parts) >= 7:
                    panes.append({
                        "session": parts[0],
                        "window_index": parts[1],
                        "pane_index": parts[2],
                        "pane_id": parts[3],
                        "active": parts[4] == "1",
                        "current_command": parts[5],
                        "current_path": parts[6],
                    })
        return {"ok": True, "panes": panes}

    stderr_lower = (r["stderr"] or "").lower()
    if "no server running" in stderr_lower or "failed to connect to server" in stderr_lower:
        return {"ok": True, "panes": []}

    return {"ok": False, "panes": [], "raw": r}

@app.get("/tmux/pane/{pane_id}/screen")
def pane_screen(pane_id: str):
    pane_id = _validate_pane_id(pane_id)

    # Try alternate-screen first, then fallback.
    r = run_wsl_bash(f"tmux capture-pane -t {pane_id} -a -p -J", timeout_s=30)
    if r["exit_code"] != 0 and ("no alternate screen" in (r.get("stderr") or "").lower()):
        r = run_wsl_bash(f"tmux capture-pane -t {pane_id} -p -J -S -20000", timeout_s=30)

    if r["exit_code"] == 0:
        return {"ok": True, "pane_id": pane_id, "text": r["stdout"]}

    if not _tmux_server_running(r.get("stderr") or ""):
        return {"ok": False, "error": "tmux_server_not_running", "raw": r}

    return {"ok": False, "error": "capture_failed", "raw": r}

def _stream_capture_pane_text(pane_id: str, max_chars: int) -> Dict[str, Any]:
    """
    Capture the tmux pane as plain text (alternate-screen preferred).
    Returns the same shape as `/tmux/pane/{pane_id}/screen` for easy client reuse.
    """
    pane_id = _validate_pane_id(pane_id)
    max_chars = int(max_chars or 0)
    if max_chars < 2000:
        max_chars = 2000
    if max_chars > 100_000:
        max_chars = 100_000

    r = run_wsl_bash(f"tmux capture-pane -t {pane_id} -a -p -J", timeout_s=30)
    if r.get("exit_code") != 0 and ("no alternate screen" in (r.get("stderr") or "").lower()):
        r = run_wsl_bash(f"tmux capture-pane -t {pane_id} -p -J -S -20000", timeout_s=30)

    if r.get("exit_code") == 0:
        text = r.get("stdout") or ""
        if max_chars and len(text) > max_chars:
            text = text[-max_chars:]
        return {"ok": True, "pane_id": pane_id, "text": text}

    if not _tmux_server_running(r.get("stderr") or ""):
        return {"ok": False, "error": "tmux_server_not_running", "raw": r}

    return {"ok": False, "error": "capture_failed", "raw": r}

@app.get("/tmux/pane/{pane_id}/stream")
async def pane_stream(request: Request, pane_id: str, interval_ms: int = 800, max_chars: int = 25000):
    """
    SSE stream of a tmux pane's captured screen text.

    This is *not* a full terminal emulator; it pushes periodic `capture-pane` snapshots.
    It's fast, works on Windows+WSL, and is good enough for watching Codex output live.
    """
    pane_id = _validate_pane_id(pane_id)
    try:
        interval_ms = int(interval_ms or 800)
    except Exception:
        interval_ms = 800
    interval_ms = max(200, min(interval_ms, 5000))
    try:
        max_chars = int(max_chars or 25000)
    except Exception:
        max_chars = 25000

    async def _gen():
        yield _sse_event_bytes("hello", {"ok": True, "pane_id": pane_id, "interval_ms": interval_ms, "max_chars": max_chars})
        last_text: Optional[str] = None
        last_send = 0.0
        seq = 0
        while True:
            if await request.is_disconnected():
                break

            snap = await asyncio.to_thread(_stream_capture_pane_text, pane_id, max_chars)
            if not snap.get("ok"):
                yield _sse_event_bytes("error", {"ok": False, "pane_id": pane_id, "ts": time.time(), **snap})
                # Slow down on errors to avoid hammering wsl.exe / tmux.
                await asyncio.sleep(max(1.5, interval_ms / 1000.0))
                continue

            text = snap.get("text") or ""
            if text != last_text:
                last_text = text
                seq += 1
                yield _sse_event_bytes("screen", {"ok": True, "pane_id": pane_id, "seq": seq, "ts": time.time(), "text": text})
                last_send = time.time()
            else:
                # Keep the connection alive (mobile networks, proxies).
                if time.time() - last_send > 10:
                    yield _sse_event_bytes("ping", {"ok": True, "pane_id": pane_id, "ts": time.time()})
                    last_send = time.time()

            await asyncio.sleep(interval_ms / 1000.0)

    headers = {
        "Cache-Control": "no-cache",
        "Connection": "keep-alive",
        # Disables proxy buffering when deployed behind nginx; harmless elsewhere.
        "X-Accel-Buffering": "no",
    }
    return StreamingResponse(_gen(), media_type="text/event-stream", headers=headers)

@app.post("/tmux/pane/{pane_id}/send")
def pane_send(pane_id: str, text: str = Body(..., media_type="text/plain")):
    pane_id = _validate_pane_id(pane_id)
    r = _tmux_send_text(pane_id, text, codex_mode=None, timeout_s=30)

    if r["exit_code"] == 0:
        return {"ok": True, "pane_id": pane_id}

    if not _tmux_server_running(r.get("stderr") or ""):
        return {"ok": False, "error": "tmux_server_not_running", "raw": r}

    return {"ok": False, "error": "send_failed", "raw": r}

@app.post("/tmux/pane/{pane_id}/key")
def pane_send_key(pane_id: str, payload: Dict[str, Any] = Body(...)):
    pane_id = _validate_pane_id(pane_id)
    raw_key = str((payload or {}).get("key") or "").strip().lower()
    key_map = {
        "up": "Up",
        "down": "Down",
        "left": "Left",
        "right": "Right",
        "enter": "Enter",
        "arrowup": "Up",
        "arrowdown": "Down",
        "arrowleft": "Left",
        "arrowright": "Right",
    }
    tmux_key = key_map.get(raw_key)
    if not tmux_key:
        raise HTTPException(status_code=400, detail="Unsupported key. Use: up, down, left, right, enter.")
    r = run_wsl_bash(f"tmux send-keys -t {pane_id} {tmux_key}", timeout_s=20)
    if r.get("exit_code") == 0:
        return {"ok": True, "pane_id": pane_id, "key": raw_key}
    if not _tmux_server_running(r.get("stderr") or ""):
        return {"ok": False, "error": "tmux_server_not_running", "raw": r}
    return {"ok": False, "error": "key_failed", "raw": r}

@app.post("/tmux/pane/{pane_id}/ctrlc")
def pane_ctrlc(pane_id: str):
    pane_id = _validate_pane_id(pane_id)
    # For Codex panes, Esc is the safe "interrupt" key. Ctrl+C can terminate the TUI.
    key = "Escape" if _pane_is_codex_like(pane_id) else "C-c"
    r = run_wsl_bash(f"tmux send-keys -t {pane_id} {key}", timeout_s=20)

    if r["exit_code"] == 0:
        return {"ok": True, "pane_id": pane_id, "sent": "esc" if key == "Escape" else "ctrl+c"}

    if not _tmux_server_running(r.get("stderr") or ""):
        return {"ok": False, "error": "tmux_server_not_running", "raw": r}

    return {"ok": False, "error": "ctrlc_failed", "raw": r}

# -------------------------
# WSL file endpoints
# -------------------------
@app.get("/shares")
def shares_list():
    with SHARED_OUTBOX_LOCK:
        _load_shared_outbox_unlocked()
        snapshot = _shared_outbox_snapshot_unlocked()
    items = [_public_shared_item(item) for item in snapshot.get("items") or []]
    return {"ok": True, "items": items}


@app.get("/telegram/status")
def telegram_status():
    token = str(TELEGRAM_BOT_TOKEN or "").strip()
    resolved_chat_id = _telegram_resolve_chat_id(allow_discovery=True) if token else ""
    return {
        "ok": True,
        "configured": bool(token and resolved_chat_id),
        "default_send": bool(CODEX_TELEGRAM_DEFAULT_SEND),
        "chat_id_masked": _mask_sensitive(resolved_chat_id) if resolved_chat_id else "",
        "bot_token_masked": _mask_sensitive(token) if token else "",
        "api_base": TELEGRAM_API_BASE,
        "max_file_mb": max(1, TELEGRAM_MAX_FILE_MB),
    }


@app.post("/telegram/send-text")
def telegram_send_text(payload: Optional[Dict[str, Any]] = Body(default=None)):
    payload = payload or {}
    text = str(payload.get("text") or "").strip()
    if not text:
        raise HTTPException(status_code=400, detail="text is required.")
    telegram_result = _telegram_send_text(text)
    return {
        "ok": bool(telegram_result.get("ok")),
        "telegram": telegram_result,
        "detail": (
            "Sent to Telegram."
            if telegram_result.get("ok")
            else (telegram_result.get("detail") or telegram_result.get("error") or "Telegram send failed.")
        ),
    }


@app.get("/loop/status")
def loop_status():
    _ensure_loop_control_worker()
    with LOOP_CONTROL_LOCK:
        _load_loop_control_unlocked()
        settings = _public_loop_settings_unlocked()
        worker = dict(LOOP_CONTROL_DATA.get("worker") or {})
    return {
        "ok": True,
        "settings": settings,
        "worker": {
            "alive": bool(worker.get("alive")),
            "last_cycle_at": int(worker.get("last_cycle_at") or 0),
            "last_telegram_poll_at": int(worker.get("last_telegram_poll_at") or 0),
            "last_error": str(worker.get("last_error") or ""),
            "last_error_at": int(worker.get("last_error_at") or 0),
        },
    }


@app.post("/loop/settings")
def loop_settings_update(payload: Optional[Dict[str, Any]] = Body(default=None)):
    payload = payload or {}
    default_prompt = payload.get("default_prompt")
    global_preset = payload.get("global_preset")
    completion_checks = payload.get("completion_checks")
    telegram_windows_mirror_enabled = payload.get("telegram_windows_mirror_enabled")
    with LOOP_CONTROL_LOCK:
        _load_loop_control_unlocked()
        settings = _get_loop_settings_unlocked()
        dirty = False
        if default_prompt is not None:
            next_prompt = str(default_prompt or "").strip()
            settings["default_prompt"] = next_prompt or LOOP_CONTROL_DEFAULT_PROMPT
            settings["updated_at"] = _now_ms()
            dirty = True
        if global_preset is not None:
            normalized_preset = _normalize_loop_preset(global_preset)
            _loop_set_global_preset_unlocked(normalized_preset)
            settings = _get_loop_settings_unlocked()
            dirty = False
        if completion_checks is not None:
            next_commands: List[str]
            if isinstance(completion_checks, list):
                next_commands = _normalize_loop_commands(completion_checks)
            else:
                next_commands = _normalize_loop_commands(str(completion_checks or "").splitlines())
            settings["completion_checks"] = next_commands
            settings["updated_at"] = _now_ms()
            dirty = True
        if telegram_windows_mirror_enabled is not None:
            settings["telegram_windows_mirror_enabled"] = bool(telegram_windows_mirror_enabled)
            settings["updated_at"] = _now_ms()
            dirty = True
        if dirty:
            _persist_loop_control_unlocked()
        public_settings = _public_loop_settings_unlocked()
        worker = dict(LOOP_CONTROL_DATA.get("worker") or {})
    return {
        "ok": True,
        "settings": public_settings,
        "worker": {
            "alive": bool(worker.get("alive")),
            "last_cycle_at": int(worker.get("last_cycle_at") or 0),
            "last_telegram_poll_at": int(worker.get("last_telegram_poll_at") or 0),
            "last_error": str(worker.get("last_error") or ""),
            "last_error_at": int(worker.get("last_error_at") or 0),
        },
    }


@app.post("/loop/session/{session}/mode")
def loop_session_mode_update(session: str, payload: Optional[Dict[str, Any]] = Body(default=None)):
    session = _validate_session_name(session)
    payload = payload or {}
    raw_override_mode = str(payload.get("override_mode") or "").strip().lower()
    if raw_override_mode not in LOOP_OVERRIDE_MODE_VALUES:
        raise HTTPException(status_code=400, detail="Invalid loop override mode.")
    override_mode = _normalize_loop_override_mode(raw_override_mode)
    with LOOP_CONTROL_LOCK:
        _load_loop_control_unlocked()
        _loop_set_session_override_unlocked(session, override_mode)
        public_state = _public_loop_session_state_unlocked(session)
    return {"ok": True, "session": session, "loop": public_state}


@app.post("/shares")
def shares_create(payload: Optional[Dict[str, Any]] = Body(default=None)):
    payload = payload or {}
    path = str(payload.get("path") or "").strip()
    if not path:
        raise HTTPException(status_code=400, detail="path is required.")
    title = str(payload.get("title") or "").strip()
    expires_hours = payload.get("expires_hours")
    created_by = str(payload.get("created_by") or "manual").strip()[:64]
    item = _create_shared_outbox_item(
        path,
        title=title,
        expires_hours=expires_hours,
        created_by=created_by or "manual",
    )
    return {"ok": True, "item": _public_shared_item(item)}


@app.post("/shares/{share_id}/telegram")
def shares_send_telegram(share_id: str, payload: Optional[Dict[str, Any]] = Body(default=None)):
    share_id = _clean_entity_id(share_id)
    if not share_id:
        raise HTTPException(status_code=400, detail="Invalid share id.")
    payload = payload or {}
    caption = str(payload.get("caption") or "").strip()
    with SHARED_OUTBOX_LOCK:
        _load_shared_outbox_unlocked()
        item = _find_shared_item_unlocked(share_id)
        if not item:
            raise HTTPException(status_code=404, detail="Share not found.")
        if _share_expired(item):
            raise HTTPException(status_code=410, detail="Share has expired.")
        snap = json.loads(json.dumps(item))
    telegram_result = _telegram_send_shared_item(snap, caption_override=caption)
    return {
        "ok": bool(telegram_result.get("ok")),
        "share_id": share_id,
        "shared_file": _public_shared_item(snap),
        "telegram": telegram_result,
        "detail": (
            "Sent to Telegram."
            if telegram_result.get("ok")
            else (telegram_result.get("detail") or telegram_result.get("error") or "Telegram send failed.")
        ),
    }


@app.delete("/shares/{share_id}")
def shares_delete(share_id: str):
    share_id = _clean_entity_id(share_id)
    if not share_id:
        raise HTTPException(status_code=400, detail="Invalid share id.")
    with SHARED_OUTBOX_LOCK:
        _load_shared_outbox_unlocked()
        prev = SHARED_OUTBOX_DATA.get("items") or []
        next_items = [item for item in prev if (item or {}).get("id") != share_id]
        if len(next_items) == len(prev):
            return {"ok": False, "error": "not_found", "detail": f"Share '{share_id}' not found."}
        SHARED_OUTBOX_DATA["items"] = next_items
        _persist_shared_outbox_unlocked()
    return {"ok": True, "share_id": share_id}


@app.get("/share/file/{share_id}")
def share_file_download(share_id: str):
    share_id = _clean_entity_id(share_id)
    if not share_id:
        raise HTTPException(status_code=400, detail="Invalid share id.")
    with SHARED_OUTBOX_LOCK:
        _load_shared_outbox_unlocked()
        item = _find_shared_item_unlocked(share_id)
        if not item:
            raise HTTPException(status_code=404, detail="Share not found.")
        if _share_expired(item):
            raise HTTPException(status_code=410, detail="Share has expired.")
        wsl_path = str(item.get("wsl_path") or "")
        windows_path = str(item.get("windows_path") or "")
    filename = str(item.get("file_name") or "download.bin")
    if wsl_path.startswith("/"):
        wsl_abs = _resolve_session_access_path(wsl_path)
        unc = _wsl_unc_path(wsl_abs)
        if not os.path.exists(unc):
            raise HTTPException(status_code=404, detail="Shared file is no longer available.")
        if os.path.isdir(unc):
            raise HTTPException(status_code=400, detail="Shared path is a directory.")
        return FileResponse(unc, filename=filename or os.path.basename(wsl_abs.rstrip("/")) or "download.bin")
    host_path = _normalize_host_path(windows_path)
    if not os.path.exists(host_path):
        raise HTTPException(status_code=404, detail="Shared host file is no longer available.")
    if os.path.isdir(host_path):
        raise HTTPException(status_code=400, detail="Shared path is a directory.")
    return FileResponse(host_path, filename=filename or os.path.basename(host_path.rstrip("\\/")) or "download.bin")


@app.get("/wsl/file")
def wsl_file(path: str):
    wsl_abs = _resolve_wsl_path(path)
    unc = _wsl_unc_path(wsl_abs)

    if not os.path.exists(unc):
        raise HTTPException(status_code=404, detail="File not found.")
    if os.path.isdir(unc):
        raise HTTPException(status_code=400, detail="Path is a directory. Provide a file path.")

    # Stream the file via UNC path (supports binary)
    filename = os.path.basename(wsl_abs.rstrip("/"))
    return FileResponse(unc, filename=filename)


@app.post("/host/open-path")
def host_open_path(payload: Optional[Dict[str, Any]] = Body(default=None)):
    _ensure_windows_host()
    payload = payload or {}
    info = _resolve_openable_host_path(str(payload.get("path") or ""))
    return _open_resolved_host_path(info)


@app.post("/host/reveal-path")
def host_reveal_path(payload: Optional[Dict[str, Any]] = Body(default=None)):
    _ensure_windows_host()
    payload = payload or {}
    info = _resolve_openable_host_path(str(payload.get("path") or ""))
    return _reveal_resolved_host_path(info)


@app.post("/host/files/upload")
async def host_upload(
    file: UploadFile = File(...),
    destination: str = Form("default"),
    open_after: str = Form("0"),
    reveal_after: str = Form("0"),
):
    _ensure_windows_host()
    destination_info = _resolve_host_transfer_destination(destination)
    should_open = _truthy_flag(open_after)
    should_reveal = _truthy_flag(reveal_after)
    file_name = file.filename or "upload.bin"
    target_path = _host_unique_target_path(destination_info["directory"], file_name)
    try:
        with open(target_path, "wb") as f:
            while True:
                chunk = await file.read(1024 * 1024)
                if not chunk:
                    break
                f.write(chunk)
    except Exception as exc:
        try:
            if os.path.exists(target_path):
                os.remove(target_path)
        except Exception:
            pass
        raise HTTPException(status_code=500, detail=f"Failed to write host file: {type(exc).__name__}: {exc}")
    item = _create_host_shared_outbox_item(
        target_path,
        created_by="host_upload",
        source_kind="host_transfer",
    )
    detail = (
        f"Uploaded to {destination_info['directory']}"
        if destination_info["mode"] == "focused"
        else f"Uploaded to {CODEX_HOST_TRANSFER_ROOT}"
    )
    post_action = ""
    post_action_detail = ""
    if should_reveal:
        reveal_result = _reveal_resolved_host_path(_resolve_openable_host_path(target_path))
        post_action = "reveal"
        post_action_detail = str(reveal_result.get("detail") or "").strip()
    elif should_open:
        open_result = _open_resolved_host_path(_resolve_openable_host_path(target_path))
        post_action = "open"
        post_action_detail = str(open_result.get("detail") or "").strip()
    if post_action_detail:
        detail = f"{detail}. {post_action_detail}"
    return {
        "ok": True,
        "saved_path": target_path,
        "target_dir": destination_info["directory"],
        "destination_mode": destination_info["mode"],
        "focused_path": destination_info["selected_path"],
        "post_action": post_action,
        "shared_file": _public_shared_item(item),
        "detail": detail,
    }


@app.post("/host/files/pick-share")
def host_pick_share(payload: Optional[Dict[str, Any]] = Body(default=None)):
    _ensure_windows_host()
    payload = payload or {}
    picked_path = _desktop_pick_shareable_host_file()
    item = _create_host_shared_outbox_item(
        picked_path,
        title=str(payload.get("title") or "").strip(),
        expires_hours=payload.get("expires_hours"),
        created_by="host_picker",
        source_kind="host_picker",
    )
    return {
        "ok": True,
        "selected_path": picked_path,
        "shared_file": _public_shared_item(item),
        "detail": f"Shared host file: {picked_path}",
    }


@app.post("/host/files/share-selection")
def host_share_selection(payload: Optional[Dict[str, Any]] = Body(default=None)):
    _ensure_windows_host()
    payload = payload or {}
    allow_directory = _truthy_flag(payload.get("allow_directory"))
    selection = _desktop_selected_paths()
    selected_path = _normalize_host_path(str(selection.get("path") or ""))
    item = _create_host_shared_outbox_item(
        selected_path,
        title=str(payload.get("title") or "").strip(),
        expires_hours=payload.get("expires_hours"),
        allow_directory=allow_directory,
        created_by="host_selection",
        source_kind="host_selection",
    )
    return {
        "ok": True,
        "selected_path": selected_path,
        "shared_file": _public_shared_item(item),
        "detail": f"Shared host selection: {selected_path}",
    }


@app.post("/wsl/upload")
async def wsl_upload(file: UploadFile = File(...), dest: str = Form("")):
    # dest is relative to CODEX_FILE_ROOT; if blank, use original filename.
    rel = (dest or "").strip()
    if not rel:
        rel = file.filename or "upload.bin"

    wsl_abs = _resolve_wsl_path(rel)
    unc = _wsl_unc_path(wsl_abs)

    # ensure directory exists
    unc_dir = os.path.dirname(unc)
    os.makedirs(unc_dir, exist_ok=True)

    # write in chunks
    try:
        with open(unc, "wb") as f:
            while True:
                chunk = await file.read(1024 * 1024)
                if not chunk:
                    break
                f.write(chunk)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to write file: {type(e).__name__}: {e}")

    return {"ok": True, "saved_path": wsl_abs}

# -------------------------
# codex exec endpoints
# -------------------------
def _count_running_runs() -> int:
    with RUNS_LOCK:
        return sum(1 for rr in RUNS.values() if rr.get("status") == "running")

def _store_run(run_id: str, run: Dict[str, Any]) -> None:
    with RUNS_LOCK:
        RUNS[run_id] = run
        RUNS_ORDER.insert(0, run_id)
        while len(RUNS_ORDER) > MAX_RUNS_KEEP:
            old = RUNS_ORDER.pop()
            RUNS.pop(old, None)

def _run_codex_exec_in_thread(run_id: str, prompt: str):
    start = time.time()
    cmd = f"codex exec --cd {CODEX_WORKDIR} " + _bash_quote(prompt)
    r = run_wsl_bash(cmd, timeout_s=900)

    duration = round(time.time() - start, 1)
    output_parts = []
    if r.get("stdout"):
        output_parts.append(r["stdout"])
    if r.get("stderr"):
        output_parts.append("\n[stderr]\n" + r["stderr"])
    output = "\n".join(output_parts).strip()

    with RUNS_LOCK:
        rr = RUNS.get(run_id, {})
        rr["status"] = "done" if r.get("exit_code") == 0 else "error"
        rr["exit_code"] = r.get("exit_code")
        rr["duration_s"] = duration
        rr["output"] = output
        rr["finished_at"] = time.time()
        RUNS[run_id] = rr

@app.post("/codex/exec")
def codex_exec(payload: Dict[str, Any] = Body(...)):
    prompt = (payload.get("prompt") or "").strip()
    if not prompt:
        raise HTTPException(status_code=400, detail="Missing prompt.")
    if len(prompt) > 20000:
        raise HTTPException(status_code=400, detail="Prompt too long (max 20000 chars).")

    if _count_running_runs() >= MAX_CONCURRENT_RUNS:
        return {"ok": False, "error": "too_many_running", "detail": f"Max concurrent runs is {MAX_CONCURRENT_RUNS}."}

    run_id = uuid.uuid4().hex[:10]
    run = {
        "id": run_id,
        "status": "running",
        "prompt": prompt,
        "created_at": time.time(),
        "output": "",
        "exit_code": None,
        "duration_s": None,
    }
    _store_run(run_id, run)

    t = threading.Thread(target=_run_codex_exec_in_thread, args=(run_id, prompt), daemon=True)
    t.start()

    return {"ok": True, "id": run_id}

@app.get("/codex/run/{run_id}")
def codex_run(run_id: str):
    with RUNS_LOCK:
        rr = RUNS.get(run_id)
        if not rr:
            return {"ok": False, "error": "not_found"}
        return {"ok": True, **rr}

@app.get("/codex/runs")
def codex_runs():
    with RUNS_LOCK:
        items = []
        for rid in RUNS_ORDER[:20]:
            rr = RUNS.get(rid, {})
            items.append({
                "id": rr.get("id"),
                "status": rr.get("status"),
                "duration_s": rr.get("duration_s"),
                "prompt": rr.get("prompt", ""),
            })
        return {"ok": True, "runs": items}


_ensure_loop_control_worker()
