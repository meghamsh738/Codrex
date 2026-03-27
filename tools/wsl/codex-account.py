#!/usr/bin/env python3

from __future__ import annotations

import argparse
import base64
import fcntl
import hashlib
import json
import os
import pty
import re
import select
import shutil
import signal
import struct
import subprocess
import sys
import termios
import time
from pathlib import Path


ROOT = Path("/mnt/d/codex-remote-ui")
REGISTRY_PATH = Path("/home/megha/.local/share/codrex/accounts/registry.json")
REAL_CODEX_PATH_FILE = Path("/home/megha/.local/share/codrex/accounts/real_codex_path.txt")
SESSION_ACCOUNTS_PATH = Path("/home/megha/.local/state/codrex-remote-ui/state/session-accounts.json")
SESSION_FILES_PATH = Path("/home/megha/.local/state/codrex-remote-ui/state/session-files.json")
USAGE_CACHE_PATH = Path("/home/megha/.local/state/codrex-remote-ui/state/account-usage-cache.json")
BACKUP_ROOT = Path("/home/megha/.local/share/codrex/backups")
PROTECTED_PATHS_PATH = ROOT / "tools" / "wsl" / "protected-paths.json"
STATUS_PROBE_CWD = Path(os.environ.get("CODEX_ACCOUNT_STATUS_CWD", "/mnt/d/codex-remote-ui")).expanduser()
USAGE_CACHE_TTL_S = int(os.environ.get("CODEX_ACCOUNT_USAGE_CACHE_TTL_S", "900") or "900")
DEFAULT_BASELINE_SOURCE_ID = str(os.environ.get("CODEX_ACCOUNT_BASELINE_SOURCE_ID", "primary") or "primary").strip() or "primary"
AUTO_SYNC_ENABLED = str(os.environ.get("CODEX_ACCOUNT_AUTO_SYNC", "1") or "1").strip().lower() not in {"0", "false", "no", "off"}
ANSI_ESCAPE_RE = re.compile(r"\x1b(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~]|\][^\x07]*(?:\x07|\x1b\\))")
USAGE_STATUS_RE = re.compile(r"(?P<context>\d+% left)\s+[·|]\s+weekly\s+(?P<weekly>\d+%)", re.IGNORECASE)
TRUST_PROMPT_RE = re.compile(r"Do\s+you\s+trust\s+the\s+contents\s+of\s+this\s+directory\?", re.IGNORECASE)
TIP_RE = re.compile(r"Tip:\s*(?P<tip>.+?)(?:\n|$)", re.IGNORECASE)
TIP_TRAILING_NOISE_RE = re.compile(r"\s*(?:[›>].*|\bgpt-[a-z0-9._-]+.*)$", re.IGNORECASE)
TIP_LEADING_LABEL_RE = re.compile(r"^(?:new[\s:.-]+){2,}", re.IGNORECASE)
JWT_SEGMENT_PADDING = "==="
CONFIG_HOME_SENTINEL = "__CODEX_HOME__"
SYNC_DIR_ITEMS = ("agents", "skills", ".agents")
SYNC_FILE_ITEMS = ("AGENTS.md",)
CRITICAL_ACCOUNT_ITEMS = ("AGENTS.md", "config.toml", "auth.json", ".credentials.json", "agents", "skills", ".agents")
TERMINAL_QUERY_REPLIES: tuple[tuple[bytes, bytes], ...] = (
    (b"\x1b[6n", b"\x1b[1;1R"),
    (b"\x1b[c", b"\x1b[?62;c"),
    (b"\x1b]10;?\x1b\\", b"\x1b]10;rgb:ffff/ffff/ffff\x07"),
    (b"\x1b]11;?\x1b\\", b"\x1b]11;rgb:0000/0000/0000\x07"),
)


def load_json(path: Path, default: dict) -> dict:
    if not path.exists():
        return json.loads(json.dumps(default))
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return json.loads(json.dumps(default))


def save_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def load_registry() -> dict:
    return load_json(REGISTRY_PATH, {"accounts": {}, "active_account_id": None, "version": 1})


def save_registry(registry: dict) -> None:
    save_json(REGISTRY_PATH, registry)


def load_session_accounts() -> dict:
    return load_json(SESSION_ACCOUNTS_PATH, {"sessions": {}})


def save_session_accounts(payload: dict) -> None:
    save_json(SESSION_ACCOUNTS_PATH, payload)


def load_session_files() -> dict:
    return load_json(SESSION_FILES_PATH, {"items": []})


def load_usage_cache() -> dict:
    return load_json(USAGE_CACHE_PATH, {"accounts": {}})


def save_usage_cache(payload: dict) -> None:
    save_json(USAGE_CACHE_PATH, payload)


def utc_timestamp_slug() -> str:
    return time.strftime("%Y%m%d_%H%M%S", time.gmtime())


def read_text_if_exists(path: Path) -> str:
    if not path.exists():
        return ""
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return ""


def copy_path(src: Path, dest: Path) -> None:
    if src.is_dir() and not src.is_symlink():
        shutil.copytree(src, dest, dirs_exist_ok=False)
        return
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dest)


def remove_path(path: Path) -> None:
    if not path.exists() and not path.is_symlink():
        return
    if path.is_dir() and not path.is_symlink():
        shutil.rmtree(path)
        return
    path.unlink()


def path_digest(path: Path) -> str:
    if not path.exists():
        return ""
    digest = hashlib.sha256()
    if path.is_file() or path.is_symlink():
        digest.update(b"file\0")
        digest.update(path.read_bytes())
        return digest.hexdigest()
    digest.update(b"dir\0")
    for child in sorted(p for p in path.rglob("*") if p.is_file()):
        digest.update(str(child.relative_to(path)).encode("utf-8"))
        digest.update(b"\0")
        digest.update(child.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def normalize_config_text_for_export(config_text: str, source_home: str) -> str:
    if not config_text:
        return ""
    return config_text.replace(source_home, CONFIG_HOME_SENTINEL)


def render_config_text_for_target(config_text: str, target_home: str) -> str:
    if not config_text:
        return ""
    return config_text.replace(CONFIG_HOME_SENTINEL, target_home)


def load_protected_paths() -> dict:
    return load_json(PROTECTED_PATHS_PATH, {"paths": [], "cleanup_policy": []})


def get_accounts() -> dict[str, dict]:
    registry = load_registry()
    return registry.get("accounts", {})


def get_real_codex_path() -> str:
    if REAL_CODEX_PATH_FILE.exists():
        try:
            return REAL_CODEX_PATH_FILE.read_text(encoding="utf-8").strip()
        except Exception:
            return ""
    return ""


def strip_ansi(text: str) -> str:
    cleaned = ANSI_ESCAPE_RE.sub("", text or "")
    return cleaned.replace("\r", "\n").replace("\x08", "").replace("\x00", "")


def collect_terminal_probe_replies(transcript: bytes, sent_probes: set[bytes] | None = None) -> list[tuple[bytes, bytes]]:
    sent = sent_probes or set()
    replies: list[tuple[bytes, bytes]] = []
    for probe, reply in TERMINAL_QUERY_REPLIES:
        if probe in transcript and probe not in sent:
            replies.append((probe, reply))
    return replies


def parse_usage_probe_output(text: str) -> dict:
    cleaned = strip_ansi(text)
    status_match = USAGE_STATUS_RE.search(cleaned)
    tip_match = TIP_RE.search(cleaned)
    tip_text = ""
    if tip_match:
        tip_text = TIP_TRAILING_NOISE_RE.sub("", tip_match.group("tip")).strip()
        tip_text = TIP_LEADING_LABEL_RE.sub("", tip_text).strip()
    if not status_match:
        return {
            "ok": False,
            "detail": "Could not read usage line from Codex.",
            "raw_excerpt": cleaned[-1000:],
        }
    return {
        "ok": True,
        "context_left": status_match.group("context"),
        "weekly_left": status_match.group("weekly"),
        "tip": tip_text,
        "probed_at": int(time.time()),
    }


def decode_jwt_payload(token: str) -> dict:
    raw = str(token or "").strip()
    if not raw or raw.count(".") < 2:
        return {}
    try:
        payload_segment = raw.split(".")[1]
        payload_segment += JWT_SEGMENT_PADDING[: (4 - len(payload_segment) % 4) % 4]
        decoded = base64.urlsafe_b64decode(payload_segment.encode("utf-8"))
        parsed = json.loads(decoded.decode("utf-8"))
        return parsed if isinstance(parsed, dict) else {}
    except Exception:
        return {}


def iso_date_only(value: str) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    return raw.split("T", 1)[0]


def read_auth_profile(account_id: str, account: dict) -> dict:
    codex_home = Path(str(account.get("codex_home", "")).strip())
    auth_path = codex_home / "auth.json"
    if not auth_path.exists():
        return {}
    try:
        auth_payload = json.loads(auth_path.read_text(encoding="utf-8"))
    except Exception:
        return {}

    tokens = auth_payload.get("tokens", {}) if isinstance(auth_payload, dict) else {}
    id_claims = decode_jwt_payload(str(tokens.get("id_token", "")))
    auth_claims = id_claims.get("https://api.openai.com/auth", {}) if isinstance(id_claims, dict) else {}
    profile = {
        "account_id": str(tokens.get("account_id", "")).strip(),
        "email": str(id_claims.get("email", "")).strip(),
        "plan_type": str(auth_claims.get("chatgpt_plan_type", "")).strip(),
        "subscription_active_until": iso_date_only(str(auth_claims.get("chatgpt_subscription_active_until", ""))),
        "subscription_last_checked": iso_date_only(str(auth_claims.get("chatgpt_subscription_last_checked", ""))),
    }
    return {key: value for key, value in profile.items() if value}


def resolve_probe_cwd() -> str:
    raw = str(STATUS_PROBE_CWD).strip()
    if raw and Path(raw).exists():
        return raw
    fallback = "/home/megha/codrex-work"
    return fallback if Path(fallback).exists() else "/home/megha"


def run_codex_status_probe(codex_home: str) -> dict:
    real_codex = get_real_codex_path()
    if not real_codex or not Path(real_codex).exists():
        return {"ok": False, "detail": "Real codex binary not found."}

    env = os.environ.copy()
    env["CODEX_HOME"] = codex_home
    env.setdefault("TERM", "xterm-256color")
    env.setdefault("COLORTERM", "truecolor")
    command = [real_codex, "--no-alt-screen", "-C", resolve_probe_cwd()]

    master_fd, slave_fd = pty.openpty()
    try:
        fcntl.ioctl(slave_fd, termios.TIOCSWINSZ, struct.pack("HHHH", 24, 120, 0, 0))
    except OSError:
        pass
    transcript = b""
    try:
        process = subprocess.Popen(
            command,
            stdin=slave_fd,
            stdout=slave_fd,
            stderr=slave_fd,
            env=env,
            start_new_session=True,
            close_fds=True,
        )
    except Exception as exc:
        os.close(master_fd)
        os.close(slave_fd)
        return {"ok": False, "detail": str(exc)}
    finally:
        try:
            os.close(slave_fd)
        except OSError:
            pass

    trust_sent = False
    sent_terminal_replies: set[bytes] = set()
    deadline = time.time() + 10.0
    try:
        while time.time() < deadline:
            ready, _, _ = select.select([master_fd], [], [], 0.2)
            if ready:
                try:
                    chunk = os.read(master_fd, 65536)
                except OSError:
                    break
                if not chunk:
                    break
                transcript += chunk
                decoded = transcript.decode("utf-8", errors="ignore")
                for probe, reply in collect_terminal_probe_replies(transcript, sent_terminal_replies):
                    try:
                        os.write(master_fd, reply)
                        sent_terminal_replies.add(probe)
                    except OSError:
                        break
                cleaned = strip_ansi(decoded)
                if not trust_sent and TRUST_PROMPT_RE.search(cleaned):
                    os.write(master_fd, b"1\n")
                    trust_sent = True
                if USAGE_STATUS_RE.search(cleaned):
                    break
            if process.poll() is not None:
                break
    finally:
        try:
            os.killpg(process.pid, signal.SIGINT)
        except Exception:
            pass
        try:
            process.wait(timeout=2)
        except Exception:
            try:
                os.killpg(process.pid, signal.SIGTERM)
            except Exception:
                pass
        try:
            os.close(master_fd)
        except OSError:
            pass

    return parse_usage_probe_output(transcript.decode("utf-8", errors="ignore"))


def get_account_usage(account_id: str, account: dict, *, force: bool = False) -> dict:
    cache = load_usage_cache()
    cached = (cache.get("accounts", {}) or {}).get(account_id)
    if isinstance(cached, dict) and not force:
        cached_at = int(cached.get("probed_at", 0) or 0)
        if cached_at and (time.time() - cached_at) < USAGE_CACHE_TTL_S:
            return cached

    usage = run_codex_status_probe(str(account.get("codex_home", "")).strip())
    if usage.get("ok"):
        cache.setdefault("accounts", {})[account_id] = usage
        save_usage_cache(cache)
        return usage

    if isinstance(cached, dict):
        return {
            **cached,
            "stale": True,
            "detail": usage.get("detail", ""),
        }
    return usage


def build_account_summary(account_id: str, data: dict, active_id: str | None, *, include_usage: bool = False, force_usage: bool = False) -> dict:
    summary = {
        "id": account_id,
        "label": data.get("label", account_id),
        "codex_home": data.get("codex_home", ""),
        "implicit_primary": bool(data.get("implicit_primary", False)),
        "created_at": data.get("created_at"),
        "last_used_at": data.get("last_used_at"),
        "active": account_id == active_id,
        "auth_profile": read_auth_profile(account_id, data),
    }
    if include_usage:
        summary["usage"] = get_account_usage(account_id, data, force=force_usage)
    return summary


def get_active_account(registry: dict | None = None) -> tuple[str | None, dict | None]:
    registry = registry or load_registry()
    active_id = registry.get("active_account_id")
    accounts = registry.get("accounts", {})
    return active_id, accounts.get(active_id)


def list_accounts_payload(*, include_usage: bool = False, force_usage: bool = False) -> dict:
    registry = load_registry()
    active_id, _active = get_active_account(registry)
    accounts = registry.get("accounts", {})
    real_codex_path = get_real_codex_path()
    return {
        "active_account_id": active_id,
        "real_codex_path": real_codex_path,
        "accounts": [
            build_account_summary(account_id, data, active_id, include_usage=include_usage, force_usage=force_usage)
            for account_id, data in sorted(accounts.items())
        ],
    }


def backup_path_bundle(items: list[tuple[Path, Path]], *, reason: str) -> str:
    if not items:
        return ""
    backup_root = BACKUP_ROOT / f"{utc_timestamp_slug()}_{reason}"
    for src, rel_dest in items:
        if not src.exists():
            continue
        dest = backup_root / rel_dest
        dest.parent.mkdir(parents=True, exist_ok=True)
        copy_path(src, dest)
    return str(backup_root)


def build_account_backup_items(account_id: str, account: dict, *, relative_items: tuple[str, ...] | None = None) -> list[tuple[Path, Path]]:
    account_home = Path(str(account.get("codex_home", "")).strip())
    items: list[tuple[Path, Path]] = []
    for rel_path in relative_items or CRITICAL_ACCOUNT_ITEMS:
        src = account_home / rel_path
        if src.exists():
            items.append((src, Path("accounts") / account_id / rel_path))
    return items


def backup_critical_state(*, reason: str = "manual-backup") -> dict:
    registry = load_registry()
    items: list[tuple[Path, Path]] = []
    for src, rel in (
        (REGISTRY_PATH, Path("state/registry.json")),
        (REAL_CODEX_PATH_FILE, Path("state/real_codex_path.txt")),
        (SESSION_ACCOUNTS_PATH, Path("state/session-accounts.json")),
        (SESSION_FILES_PATH, Path("state/session-files.json")),
        (USAGE_CACHE_PATH, Path("state/account-usage-cache.json")),
        (PROTECTED_PATHS_PATH, Path("state/protected-paths.json")),
    ):
        if src.exists():
            items.append((src, rel))
    for account_id, account in sorted((registry.get("accounts", {}) or {}).items()):
        items.extend(build_account_backup_items(account_id, account))
    backup_root = backup_path_bundle(items, reason=reason)
    return {
        "ok": bool(backup_root),
        "backup_root": backup_root,
        "account_count": len((registry.get("accounts", {}) or {})),
        "item_count": len(items),
    }


def sync_status_for_account(source_id: str, source_account: dict, target_id: str, target_account: dict) -> dict:
    source_home = Path(str(source_account.get("codex_home", "")).strip())
    target_home = Path(str(target_account.get("codex_home", "")).strip())
    sync_items: list[dict] = []
    config_source = normalize_config_text_for_export(read_text_if_exists(source_home / "config.toml"), str(source_home))
    config_target = normalize_config_text_for_export(read_text_if_exists(target_home / "config.toml"), str(target_home))
    sync_items.append(
        {
            "path": "config.toml",
            "match": config_source == config_target,
            "source_exists": bool(config_source),
            "target_exists": bool(config_target),
        }
    )
    for rel_path in SYNC_FILE_ITEMS + SYNC_DIR_ITEMS:
        src = source_home / rel_path
        tgt = target_home / rel_path
        sync_items.append(
            {
                "path": rel_path,
                "match": path_digest(src) == path_digest(tgt),
                "source_exists": src.exists(),
                "target_exists": tgt.exists(),
            }
        )
    mismatches = [item["path"] for item in sync_items if not item["match"]]
    return {
        "source_account_id": source_id,
        "target_account_id": target_id,
        "source_codex_home": str(source_home),
        "target_codex_home": str(target_home),
        "in_sync": len(mismatches) == 0,
        "mismatches": mismatches,
        "items": sync_items,
    }


def baseline_status_payload(source_account_id: str | None = None) -> dict:
    registry = load_registry()
    accounts = registry.get("accounts", {}) or {}
    source_id = (source_account_id or DEFAULT_BASELINE_SOURCE_ID or registry.get("active_account_id") or "").strip()
    if source_id not in accounts:
        raise SystemExit(f"Unknown baseline source account: {source_id}")
    source_account = accounts[source_id]
    targets = []
    for account_id, account in sorted(accounts.items()):
        if account_id == source_id:
            continue
        targets.append(sync_status_for_account(source_id, source_account, account_id, account))
    return {
        "source_account_id": source_id,
        "source_codex_home": accounts[source_id].get("codex_home", ""),
        "auto_sync_enabled": AUTO_SYNC_ENABLED,
        "protected_paths": load_protected_paths(),
        "targets": targets,
    }


def sync_account_baseline(source_account_id: str, target_account_id: str, *, reason: str = "baseline-sync") -> dict:
    registry = load_registry()
    accounts = registry.get("accounts", {}) or {}
    if source_account_id not in accounts:
        raise SystemExit(f"Unknown source account: {source_account_id}")
    if target_account_id not in accounts:
        raise SystemExit(f"Unknown target account: {target_account_id}")
    if source_account_id == target_account_id:
        return {
            "source_account_id": source_account_id,
            "target_account_id": target_account_id,
            "changed_items": [],
            "backup_root": "",
            "skipped": True,
        }

    source_home = Path(str(accounts[source_account_id].get("codex_home", "")).strip())
    target_home = Path(str(accounts[target_account_id].get("codex_home", "")).strip())
    changed_paths: list[str] = []
    backup_items: list[tuple[Path, Path]] = []

    rendered_config = render_config_text_for_target(
        normalize_config_text_for_export(read_text_if_exists(source_home / "config.toml"), str(source_home)),
        str(target_home),
    )
    target_config_path = target_home / "config.toml"
    if rendered_config and rendered_config != read_text_if_exists(target_config_path):
        changed_paths.append("config.toml")
        if target_config_path.exists():
            backup_items.append((target_config_path, Path("accounts") / target_account_id / "config.toml"))

    for rel_path in SYNC_FILE_ITEMS + SYNC_DIR_ITEMS:
        src = source_home / rel_path
        tgt = target_home / rel_path
        if not src.exists():
            continue
        if path_digest(src) == path_digest(tgt):
            continue
        changed_paths.append(rel_path)
        if tgt.exists():
            backup_items.append((tgt, Path("accounts") / target_account_id / rel_path))

    backup_root = backup_path_bundle(backup_items, reason=reason) if backup_items else ""

    if "config.toml" in changed_paths:
        target_config_path.parent.mkdir(parents=True, exist_ok=True)
        target_config_path.write_text(rendered_config, encoding="utf-8")

    for rel_path in SYNC_FILE_ITEMS + SYNC_DIR_ITEMS:
        if rel_path not in changed_paths:
            continue
        src = source_home / rel_path
        tgt = target_home / rel_path
        remove_path(tgt)
        copy_path(src, tgt)

    return {
        "source_account_id": source_account_id,
        "target_account_id": target_account_id,
        "changed_items": changed_paths,
        "backup_root": backup_root,
        "target_codex_home": str(target_home),
    }


def sync_baseline_payload(source_account_id: str | None = None, target_account_ids: list[str] | None = None) -> dict:
    registry = load_registry()
    accounts = registry.get("accounts", {}) or {}
    source_id = (source_account_id or DEFAULT_BASELINE_SOURCE_ID or registry.get("active_account_id") or "").strip()
    if source_id not in accounts:
        raise SystemExit(f"Unknown baseline source account: {source_id}")
    if target_account_ids:
        targets = [account_id for account_id in target_account_ids if account_id and account_id != source_id]
    else:
        targets = [account_id for account_id in sorted(accounts) if account_id != source_id]
    results = [sync_account_baseline(source_id, target_id) for target_id in targets]
    return {
        "source_account_id": source_id,
        "target_account_ids": targets,
        "results": results,
    }


def activate_account(account_id: str) -> dict:
    registry = load_registry()
    accounts = registry.get("accounts", {})
    if account_id not in accounts:
        raise SystemExit(f"Unknown account: {account_id}")
    registry["active_account_id"] = account_id
    accounts[account_id]["last_used_at"] = int(time.time())
    save_registry(registry)
    payload = {
        "active_account_id": account_id,
        "label": accounts[account_id].get("label", account_id),
        "codex_home": accounts[account_id].get("codex_home", ""),
    }
    if AUTO_SYNC_ENABLED and DEFAULT_BASELINE_SOURCE_ID in accounts and account_id != DEFAULT_BASELINE_SOURCE_ID:
        payload["baseline_sync"] = sync_account_baseline(
            DEFAULT_BASELINE_SOURCE_ID,
            account_id,
            reason="auto-activate-sync",
        )
    return payload


def current_account_payload(*, include_usage: bool = False, force_usage: bool = False) -> dict:
    registry = load_registry()
    active_id, active = get_active_account(registry)
    real_codex_path = get_real_codex_path()
    payload = {
        "active_account_id": active_id,
        "label": (active or {}).get("label", ""),
        "codex_home": (active or {}).get("codex_home", ""),
        "real_codex_path": real_codex_path,
    }
    if active_id and active:
        payload["auth_profile"] = read_auth_profile(active_id, active)
        if include_usage:
            payload["usage"] = get_account_usage(active_id, active, force=force_usage)
    return payload


def session_list_payload() -> dict:
    sessions = load_session_accounts().get("sessions", {})
    active_id, active = get_active_account()
    return {
        "active_account_id": active_id,
        "active_account_label": (active or {}).get("label", ""),
        "sessions": [
            {
                "name": session_name,
                "account_id": data.get("account_id", ""),
                "account_label": data.get("account_label", ""),
                "codex_home": data.get("codex_home", ""),
                "updated_at": data.get("updated_at"),
            }
            for session_name, data in sorted(sessions.items())
        ],
        "session_files": load_session_files().get("items", []),
    }


def activate_session(session_name: str) -> dict:
    sessions = load_session_accounts().get("sessions", {})
    if session_name not in sessions:
        raise SystemExit(f"Unknown session: {session_name}")
    session = sessions[session_name]
    result = activate_account(str(session.get("account_id", "")))
    result["session_name"] = session_name
    return result


def bind_session(session_name: str, account_id: str) -> dict:
    accounts = get_accounts()
    if account_id not in accounts:
        raise SystemExit(f"Unknown account: {account_id}")
    payload = load_session_accounts()
    payload.setdefault("sessions", {})[session_name] = {
        "account_id": account_id,
        "account_label": accounts[account_id].get("label", account_id),
        "codex_home": accounts[account_id].get("codex_home", ""),
        "updated_at": time.time(),
    }
    save_session_accounts(payload)
    return payload["sessions"][session_name]


def remove_session(session_name: str) -> None:
    payload = load_session_accounts()
    sessions = payload.setdefault("sessions", {})
    if session_name in sessions:
        del sessions[session_name]
        save_session_accounts(payload)


def print_payload(payload: dict, *, as_json: bool) -> None:
    if as_json:
        print(json.dumps(payload, indent=2))
        return
    print(json.dumps(payload, indent=2))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Switch between saved Codex account profiles.")
    sub = parser.add_subparsers(dest="command", required=True)

    list_parser = sub.add_parser("list", help="List saved accounts")
    list_parser.add_argument("--json", action="store_true")
    list_parser.add_argument("--with-usage", action="store_true")
    list_parser.add_argument("--force-usage", action="store_true")

    current_parser = sub.add_parser("current", help="Show the active account")
    current_parser.add_argument("--json", action="store_true")
    current_parser.add_argument("--with-usage", action="store_true")
    current_parser.add_argument("--force-usage", action="store_true")
    current_parser.add_argument("--field", choices=["active_account_id", "label", "codex_home", "real_codex_path"])

    activate_parser = sub.add_parser("activate", help="Set the active account")
    activate_parser.add_argument("account_id")
    activate_parser.add_argument("--json", action="store_true")

    use_parser = sub.add_parser("use", help="Alias for activate")
    use_parser.add_argument("account_id")
    use_parser.add_argument("--json", action="store_true")

    sessions_parser = sub.add_parser("session-list", help="List saved session mappings")
    sessions_parser.add_argument("--json", action="store_true")

    session_activate_parser = sub.add_parser("session-activate", help="Switch to the account assigned to a saved session")
    session_activate_parser.add_argument("session_name")
    session_activate_parser.add_argument("--json", action="store_true")

    session_bind_parser = sub.add_parser("session-bind", help="Bind a session name to an account")
    session_bind_parser.add_argument("session_name")
    session_bind_parser.add_argument("account_id")
    session_bind_parser.add_argument("--json", action="store_true")

    session_remove_parser = sub.add_parser("session-remove", help="Remove a saved session mapping")
    session_remove_parser.add_argument("session_name")

    usage_parser = sub.add_parser("usage", help="Probe the visible Codex usage line for an account")
    usage_parser.add_argument("account_id", nargs="?")
    usage_parser.add_argument("--json", action="store_true")
    usage_parser.add_argument("--force", action="store_true")

    baseline_status_parser = sub.add_parser("baseline-status", help="Show whether accounts match the canonical baseline")
    baseline_status_parser.add_argument("source_account_id", nargs="?")
    baseline_status_parser.add_argument("--json", action="store_true")

    baseline_sync_parser = sub.add_parser("baseline-sync", help="Copy the canonical non-auth baseline from one account to the others")
    baseline_sync_parser.add_argument("source_account_id", nargs="?")
    baseline_sync_parser.add_argument("--target", action="append", dest="targets")
    baseline_sync_parser.add_argument("--json", action="store_true")

    baseline_apply_parser = sub.add_parser("baseline-apply", help="Apply the canonical non-auth baseline to one account")
    baseline_apply_parser.add_argument("account_id", nargs="?")
    baseline_apply_parser.add_argument("--active", action="store_true")
    baseline_apply_parser.add_argument("--source", dest="source_account_id")
    baseline_apply_parser.add_argument("--json", action="store_true")

    backup_parser = sub.add_parser("backup-state", help="Back up critical Codex launcher and account state")
    backup_parser.add_argument("--json", action="store_true")

    protected_parser = sub.add_parser("protected-paths", help="Show paths that must not be removed during cleanup")
    protected_parser.add_argument("--json", action="store_true")

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    if args.command == "list":
        print_payload(
            list_accounts_payload(include_usage=args.with_usage, force_usage=args.force_usage),
            as_json=args.json,
        )
        return 0

    if args.command == "current":
        payload = current_account_payload(include_usage=args.with_usage, force_usage=args.force_usage)
        if args.field:
            print(payload.get(args.field, ""))
        else:
            print_payload(payload, as_json=args.json)
        return 0

    if args.command in {"activate", "use"}:
        payload = activate_account(args.account_id)
        print_payload(payload, as_json=args.json)
        return 0

    if args.command == "session-list":
        print_payload(session_list_payload(), as_json=args.json)
        return 0

    if args.command == "session-activate":
        payload = activate_session(args.session_name)
        print_payload(payload, as_json=args.json)
        return 0

    if args.command == "session-bind":
        payload = bind_session(args.session_name, args.account_id)
        print_payload(payload, as_json=args.json)
        return 0

    if args.command == "session-remove":
        remove_session(args.session_name)
        return 0

    if args.command == "usage":
        registry = load_registry()
        account_id = (args.account_id or registry.get("active_account_id") or "").strip()
        accounts = registry.get("accounts", {})
        if account_id not in accounts:
            raise SystemExit(f"Unknown account: {account_id}")
        payload = {
            "account_id": account_id,
            "label": accounts[account_id].get("label", account_id),
            "usage": get_account_usage(account_id, accounts[account_id], force=args.force),
        }
        print_payload(payload, as_json=args.json)
        return 0

    if args.command == "baseline-status":
        payload = baseline_status_payload(args.source_account_id)
        print_payload(payload, as_json=args.json)
        return 0

    if args.command == "baseline-sync":
        payload = sync_baseline_payload(args.source_account_id, target_account_ids=args.targets)
        print_payload(payload, as_json=args.json)
        return 0

    if args.command == "baseline-apply":
        registry = load_registry()
        source_id = (args.source_account_id or DEFAULT_BASELINE_SOURCE_ID or registry.get("active_account_id") or "").strip()
        target_id = ""
        if args.active:
            target_id = str(registry.get("active_account_id") or "").strip()
        elif args.account_id:
            target_id = str(args.account_id).strip()
        else:
            parser.error("baseline-apply requires an account id or --active")
        payload = sync_account_baseline(source_id, target_id, reason="manual-apply")
        print_payload(payload, as_json=args.json)
        return 0

    if args.command == "backup-state":
        payload = backup_critical_state()
        print_payload(payload, as_json=args.json)
        return 0

    if args.command == "protected-paths":
        payload = load_protected_paths()
        print_payload(payload, as_json=args.json)
        return 0

    parser.error(f"Unsupported command: {args.command}")
    return 2


if __name__ == "__main__":
    sys.exit(main())
