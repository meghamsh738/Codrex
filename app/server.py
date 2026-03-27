from fastapi import FastAPI, HTTPException, Body, UploadFile, File, Form, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, Response, FileResponse, JSONResponse, StreamingResponse, RedirectResponse
import asyncio
import json
import time
import os
import shutil
import subprocess
import socket
import io
import re
import shlex
import mimetypes
import html as html_std
import threading
import uuid
import posixpath
import secrets
import ctypes
import ipaddress
from ctypes import wintypes
from typing import List, Dict, Any, Optional, Tuple
from urllib.parse import quote, urlparse
import urllib.request
import urllib.error
import atexit
import base64

from mss import mss
from mss.tools import to_png

START_TIME = time.time()
app = FastAPI(title="Codrex Remote UI", version="1.5.0")
APP_ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
UI_DIST_DIR = os.path.join(APP_ROOT_DIR, "ui", "dist")
UI_DIST_ASSETS_DIR = os.path.join(UI_DIST_DIR, "assets")

WSL_DISTRO = os.environ.get("CODEX_WSL_DISTRO", "Ubuntu")
WSL_EXE = os.environ.get("CODEX_WSL_EXE", "wsl")
CODEX_WORKDIR = os.environ.get("CODEX_WORKDIR", "/home/megha/codrex-work")
CODEX_AUTH_TOKEN = os.environ.get("CODEX_AUTH_TOKEN", "").strip()
CODEX_AUTH_COOKIE = os.environ.get("CODEX_AUTH_COOKIE", "codrex_remote_auth").strip() or "codrex_remote_auth"
CODEX_DESKTOP_MODE_COOKIE = os.environ.get("CODEX_DESKTOP_MODE_COOKIE", "codrex_remote_desktop_mode").strip() or "codrex_remote_desktop_mode"
CODEX_AUTH_REQUIRED = bool(CODEX_AUTH_TOKEN)
BLANK_IMAGE_DATA_URL = "data:image/gif;base64,R0lGODlhAQABAAD/ACwAAAAAAQABAAACADs="
DEFAULT_CODEX_MODELS = ["gpt-5-codex", "gpt-5", "gpt-5-mini", "gpt-4.1", "o4-mini"]
DEFAULT_REASONING_EFFORTS = ["minimal", "low", "medium", "high", "xhigh"]
BUILT_UI_ROOT_FILES = {
    "apple-touch-icon.png",
    "icon-192.png",
    "icon-512.png",
    "icon-maskable-192.png",
    "icon-maskable-512.png",
    "icon-maskable.svg",
    "icon.svg",
    "manifest.webmanifest",
    "sw.js",
}


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


def _tailscale_ipv4_from_ipconfig() -> str:
    """
    Best-effort fallback for Windows setups where tailscale.exe is unavailable
    to this process (PATH/service context), but the Tailscale adapter exists.
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

    in_tailscale_block = False
    for raw_line in out.splitlines():
        line = (raw_line or "").strip()
        low = line.lower()

        # Adapter section headers are not indented in ipconfig output.
        is_section_header = bool(line) and line.endswith(":") and raw_line == raw_line.lstrip()
        if is_section_header:
            in_tailscale_block = "tailscale" in low
            continue
        if not in_tailscale_block:
            continue

        m = re.search(r"(\d+\.\d+\.\d+\.\d+)", line)
        if not m:
            continue
        ip = m.group(1).strip()
        if ip and ip != "127.0.0.1" and not ip.startswith("169.254."):
            return ip
    return ""


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
LEGACY_RUNTIME_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))

VALID_NAME_RE = re.compile(r"^[A-Za-z0-9_.-]+$")
VALID_PANE_RE = re.compile(r"^%\d+$")
VALID_ENTITY_ID_RE = re.compile(r"^[A-Za-z0-9_.-]{3,96}$")
VALID_CODEX_MODEL_RE = re.compile(r"^[A-Za-z0-9._:/-]{2,120}$")

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
APP_RUNTIME_SESSION_FILE = os.path.abspath(
    os.environ.get(
        "CODEX_APP_RUNTIME_SESSION_FILE",
        os.path.join(CODEX_RUNTIME_STATE_DIR, "mobile.session.json"),
    )
)
LEGACY_APP_RUNTIME_SESSION_FILE = os.path.abspath(os.path.join(LEGACY_RUNTIME_DIR, "logs", "mobile.session.json"))

# -------------------------
# Session output stream state
# -------------------------
SESSION_STREAM_LOCK = threading.Lock()
SESSION_STREAM_REPLAY_MAX = int(os.environ.get("CODEX_SESSION_STREAM_REPLAY_MAX", "240") or "240")
SESSION_STREAM_STATES: Dict[str, Dict[str, Any]] = {}
SESSION_RECOVERING_AFTER_S = float(os.environ.get("CODEX_SESSION_RECOVERING_AFTER_S", "20") or "20")
SESSION_STALE_TTL_S = float(os.environ.get("CODEX_SESSION_STALE_TTL_S", "180") or "180")
SESSION_BACKGROUND_MODE = "selected_only"

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
        with open(p, "r", encoding="utf-8") as f:
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
    try:
        with open(p, "r", encoding="utf-8") as f:
            parsed = json.load(f)
    except Exception:
        return {}
    return parsed if isinstance(parsed, dict) else {}


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
    file_name = str(raw.get("file_name") or "").strip()
    if not item_id or not wsl_path.startswith("/") or not file_name:
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
    windows_path = str(raw.get("windows_path") or _wsl_to_windows_path(wsl_path) or "").strip()
    display_path = str(raw.get("display_path") or windows_path or wsl_path).strip()
    is_image = item_kind == "file" and (bool(raw.get("is_image")) or mime_type.startswith("image/"))
    return {
        "id": item_id,
        "title": _normalize_share_title(raw.get("title"), file_name),
        "wsl_path": wsl_path,
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


def _telegram_get_updates(token: str) -> Dict[str, Any]:
    endpoint = f"{TELEGRAM_API_BASE.rstrip('/')}/bot{token}/getUpdates?limit=20"
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


ULONG_PTR = getattr(wintypes, "ULONG_PTR", ctypes.c_size_t)

INPUT_MOUSE = 0
INPUT_KEYBOARD = 1
INPUT_HARDWARE = 2

KEYEVENTF_EXTENDEDKEY = 0x0001
KEYEVENTF_KEYUP = 0x0002
KEYEVENTF_UNICODE = 0x0004

VK_BACK = 0x08
VK_TAB = 0x09
VK_RETURN = 0x0D
VK_ESCAPE = 0x1B
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

# -------------------------
# Live codex session state
# -------------------------
SESSIONS_LOCK = threading.Lock()
SESSIONS: Dict[str, Dict[str, Any]] = {}

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


atexit.register(_restore_desktop_perf_mode)


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
        "/auth/pair/exchange",
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
        "config_port": (persisted or {}).get("port"),
        "runtime_token_present": bool(str((local_cfg or {}).get("token") or "").strip()),
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

def _desktop_monitor() -> Dict[str, int]:
    with mss() as sct:
        mon = sct.monitors[1] if len(sct.monitors) > 1 else sct.monitors[0]
        return {
            "left": int(mon.get("left", 0)),
            "top": int(mon.get("top", 0)),
            "width": int(mon.get("width", 0)),
            "height": int(mon.get("height", 0)),
        }

def _clamp(v: int, lo: int, hi: int) -> int:
    return max(lo, min(hi, v))


def _parse_stream_scale(raw: Any, default: int = 1) -> int:
    try:
        value = int(raw if raw is not None else default)
    except Exception:
        value = int(default)
    return _clamp(value, 1, 6)


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

def _desktop_click(button: str = "left", double: bool = False, action: str = "click") -> None:
    user32 = _win_user32()
    btn = (button or "left").strip().lower()
    click_action = (action or "click").strip().lower()
    mapping = {
        "left": (0x0002, 0x0004),
        "right": (0x0008, 0x0010),
        "middle": (0x0020, 0x0040),
    }
    if btn not in mapping:
        raise HTTPException(status_code=400, detail="Unsupported mouse button.")
    if click_action not in {"click", "down", "up"}:
        raise HTTPException(status_code=400, detail="Unsupported mouse action.")
    down, up = mapping[btn]
    if click_action == "down":
        user32.mouse_event(down, 0, 0, 0, 0)
        return
    if click_action == "up":
        user32.mouse_event(up, 0, 0, 0, 0)
        return
    times = 2 if double else 1
    for _ in range(times):
        user32.mouse_event(down, 0, 0, 0, 0)
        user32.mouse_event(up, 0, 0, 0, 0)

def _desktop_scroll(delta: int) -> None:
    user32 = _win_user32()
    user32.mouse_event(0x0800, 0, 0, int(delta), 0)

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
        "Set-Clipboard -Value $txt; "
        "[System.Windows.Forms.SendKeys]::SendWait('^v')"
    )
    return _run_powershell(script, timeout_s=10)


def _desktop_paste_image_file(path_for_windows: str) -> Dict[str, Any]:
    quoted_path = _ps_single_quote(path_for_windows)
    script = (
        "Add-Type -AssemblyName System.Windows.Forms; "
        "Add-Type -AssemblyName System.Drawing; "
        "$path = " + quoted_path + "; "
        "if (!(Test-Path -LiteralPath $path)) { throw 'image_not_found' }; "
        "$img = [System.Drawing.Image]::FromFile($path); "
        "try { "
        "[System.Windows.Forms.Clipboard]::SetImage($img); "
        "[System.Windows.Forms.SendKeys]::SendWait('^v') "
        "} finally { $img.Dispose() }"
    )
    return _run_powershell(script, timeout_s=12, sta=True)

def _desktop_send_key(key: str) -> Dict[str, Any]:
    k = (key or "").strip().lower()
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
        "alt+tab": ([VK_MENU], VK_TAB),
        "win+tab": ([VK_LWIN], VK_TAB),
    }
    if k in native_combos:
        mods, vk = native_combos[k]
        _send_vk_combo(mods, vk, extended=(k in {"alt+tab", "win+tab"}))
        return {"exit_code": 0, "stdout": "", "stderr": "", "mode": "native_combo", "key": k, "alt_held": False}

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
        raise HTTPException(status_code=400, detail="Unsupported key. Try: enter, esc, tab, arrows, alt+tab, alt+tab-hold, alt+release, win+tab, ctrl+c.")
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
    # Helper for UI to suggest reachable base URLs (LAN vs Tailscale).
    mac_info = _wake_mac_info()
    return {
        "ok": True,
        "lan_ip": guess_lan_ipv4(),
        "tailscale_ip": get_tailscale_ipv4(),
        "primary_mac": str(mac_info.get("primary_mac") or ""),
        "wake_candidate_macs": list(mac_info.get("wake_candidate_macs") or []),
        "wake_supported": bool(mac_info.get("wake_supported")),
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

    resp = JSONResponse({"ok": True, "auth_required": CODEX_AUTH_REQUIRED})
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
        **mon,
    }

@app.get("/desktop/shot")
def desktop_shot(request: Request, level: Optional[int] = None, scale: Optional[int] = None, bw: Optional[str] = None):
    _ensure_windows_host()
    png_level = _clamp(int(level if level is not None else DESKTOP_STREAM_PNG_LEVEL_DEFAULT), 0, 9)
    scale_factor = _parse_stream_scale(scale, default=1)
    grayscale = _truthy_flag(bw)
    with mss() as sct:
        mon = sct.monitors[1] if len(sct.monitors) > 1 else sct.monitors[0]
        img = sct.grab(mon)
        rgb = img.rgb
        if SHOW_CURSOR_OVERLAY:
            cur = _desktop_cursor_pos()
            if cur:
                left = int(mon.get("left", 0))
                top = int(mon.get("top", 0))
                rel_x = int(cur[0]) - left
                rel_y = int(cur[1]) - top
                rgb = _overlay_cursor_rgb(rgb, img.size, rel_x, rel_y)
        out_size = img.size
        if scale_factor > 1:
            rgb, out_size = _downsample_rgb_nearest(rgb, img.size, scale_factor)
        if grayscale:
            rgb = _rgb_to_grayscale(rgb)
        png_bytes = to_png(rgb, out_size, level=png_level)
        return Response(
            content=png_bytes,
            media_type="image/png",
            headers={"Cache-Control": "no-store"},
        )

@app.get("/desktop/stream")
async def desktop_stream(
    request: Request,
    fps: Optional[float] = None,
    level: Optional[int] = None,
    scale: Optional[int] = None,
    bw: Optional[str] = None,
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
    fps_val = max(0.5, min(fps_val, 12.0))
    png_level = _clamp(int(level if level is not None else DESKTOP_STREAM_PNG_LEVEL_DEFAULT), 0, 9)
    scale_factor = _parse_stream_scale(scale, default=1)
    grayscale = _truthy_flag(bw)
    frame_delay = 1.0 / fps_val
    boundary = "frame"

    async def _gen():
        with mss() as sct:
            mon = sct.monitors[1] if len(sct.monitors) > 1 else sct.monitors[0]
            while True:
                if await request.is_disconnected():
                    break
                img = sct.grab(mon)
                rgb = img.rgb
                if SHOW_CURSOR_OVERLAY:
                    cur = _desktop_cursor_pos()
                    if cur:
                        left = int(mon.get("left", 0))
                        top = int(mon.get("top", 0))
                        rel_x = int(cur[0]) - left
                        rel_y = int(cur[1]) - top
                        rgb = _overlay_cursor_rgb(rgb, img.size, rel_x, rel_y)
                out_size = img.size
                if scale_factor > 1:
                    rgb, out_size = _downsample_rgb_nearest(rgb, img.size, scale_factor)
                if grayscale:
                    rgb = _rgb_to_grayscale(rgb)
                png_bytes = to_png(rgb, out_size, level=png_level)
                chunk = (
                    f"--{boundary}\r\n"
                    "Content-Type: image/png\r\n"
                    "Cache-Control: no-store\r\n"
                    f"Content-Length: {len(png_bytes)}\r\n\r\n"
                ).encode("utf-8") + png_bytes + b"\r\n"
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
    x = int(payload.get("x", 0))
    y = int(payload.get("y", 0))
    p = _desktop_point(x, y)
    _desktop_move_abs(p["x"], p["y"])
    return {"ok": True, "x": p["rel_x"], "y": p["rel_y"], "alt_held": _desktop_alt_held()}

@app.post("/desktop/input/click")
def desktop_input_click(request: Request, payload: Dict[str, Any] = Body(...)):
    _ensure_windows_host()
    _require_desktop_enabled(request)
    alt_held_before_click = _desktop_alt_held()
    x = payload.get("x")
    y = payload.get("y")
    button = (payload.get("button") or "left").strip().lower()
    double = bool(payload.get("double", False))
    action = (payload.get("action") or "click").strip().lower()
    if x is not None and y is not None:
        p = _desktop_point(int(x), int(y))
        _desktop_move_abs(p["x"], p["y"])
    _desktop_click(button=button, double=double, action=action)
    if alt_held_before_click:
        _desktop_release_alt_if_held()
    return {"ok": True, "button": button, "double": double, "action": action, "alt_held": _desktop_alt_held()}

@app.post("/desktop/input/scroll")
def desktop_input_scroll(request: Request, payload: Dict[str, Any] = Body(...)):
    _ensure_windows_host()
    _require_desktop_enabled(request)
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
    _desktop_release_alt_if_held()
    text = payload.get("text")
    if not isinstance(text, str):
        raise HTTPException(status_code=400, detail="text must be a string.")
    if not text:
        return {"ok": True, "sent": 0, "alt_held": _desktop_alt_held()}
    if len(text) > 20000:
        raise HTTPException(status_code=400, detail="text too long (max 20000).")
    sent = _send_unicode_text_chunked(text, chunk_size=240)
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

    if backspace:
        _send_vk_repeat(VK_BACK, backspace)
    if text:
        _send_unicode_text(text)
    return {"ok": True, "backspace": backspace, "sent": len(text), "alt_held": _desktop_alt_held()}

@app.post("/desktop/input/key")
def desktop_input_key(request: Request, payload: Dict[str, Any] = Body(...)):
    _ensure_windows_host()
    _require_desktop_enabled(request)
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
    codex_cmd = "codex resume --last" if resume_last else _build_codex_launch_command(model, reasoning_effort)
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
        }
    return {
        "ok": True,
        "session": name,
        "cwd": cwd,
        "model": model,
        "reasoning_effort": reasoning_effort,
        "resume_last": resume_last,
    }

@app.delete("/codex/session/{session}")
def codex_session_close(session: str):
    session = _validate_session_name(session)
    r = run_wsl_bash(f"tmux kill-session -t {session}", timeout_s=20)
    if r.get("exit_code") != 0:
        stderr = (r.get("stderr") or "").lower()
        if "can't find session" in stderr or "no such session" in stderr:
            return {"ok": False, "error": "not_found", "detail": f"Session '{session}' not found."}
        return {"ok": False, "error": "close_failed", "raw": r}
    with SESSIONS_LOCK:
        SESSIONS.pop(session, None)
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
    out: Dict[str, Any] = {"ok": True, "session": session}
    if repair_applied:
        out["profile_repaired"] = True
        out["profile_model"] = repair.get("model")
        out["profile_reasoning_effort"] = repair.get("reasoning_effort")
    if repair_warning:
        out["profile_repair_warning"] = repair_warning
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
        return {"ok": False, "error": "not_found", "detail": f"Session '{session}' has no panes."}
    # Full pane capture is needed for Codex because it renders in the alternate screen.
    text = _capture_pane_full(pane["pane_id"], max_chars=25000)
    snippet = _capture_snippet(pane["pane_id"], lines=80)
    state = _infer_progress_state(text or snippet, pane.get("current_command", ""))
    with SESSIONS_LOCK:
        prev = SESSIONS.get(session, {})
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
        }
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
        live.append(item)
        with SESSIONS_LOCK:
            SESSIONS[session] = {**prev, **item}

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
            continue
        fallback_snippet = _session_cached_snippet(prev)
        fallback_state = str(prev.get("state") or "").strip().lower()
        if age_s > SESSION_RECOVERING_AFTER_S and fallback_state not in {"done", "error"}:
            fallback_state = "recovering"
        elif not fallback_state:
            fallback_state = "starting"
        live.append(
            {
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
        )
    live.sort(key=lambda x: x["session"])
    return {
        "ok": True,
        "sessions": live,
        "meta": {
            "total_sessions": len(live),
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
        mon = sct.monitors[1]
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
    wsl_abs = _resolve_session_access_path(wsl_path)
    unc = _wsl_unc_path(wsl_abs)
    if not os.path.exists(unc):
        raise HTTPException(status_code=404, detail="Shared file is no longer available.")
    if os.path.isdir(unc):
        raise HTTPException(status_code=400, detail="Shared path is a directory.")
    filename = str(item.get("file_name") or os.path.basename(wsl_abs.rstrip("/")) or "download.bin")
    return FileResponse(unc, filename=filename)


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
