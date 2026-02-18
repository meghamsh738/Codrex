import sys
import unittest
from contextlib import ExitStack
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest import mock

def _install_fastapi_stubs():
    if "fastapi" in sys.modules:
        return

    fastapi = ModuleType("fastapi")
    responses = ModuleType("fastapi.responses")

    class DummyResponse:
        def __init__(self, *args, **kwargs):
            pass

        def set_cookie(self, *args, **kwargs):
            return None

        def delete_cookie(self, *args, **kwargs):
            return None

    class DummyFastAPI:
        def __init__(self, *args, **kwargs):
            pass

        def get(self, *args, **kwargs):
            def decorator(fn):
                return fn
            return decorator

        def post(self, *args, **kwargs):
            def decorator(fn):
                return fn
            return decorator

        def delete(self, *args, **kwargs):
            def decorator(fn):
                return fn
            return decorator

        def middleware(self, *args, **kwargs):
            def decorator(fn):
                return fn
            return decorator

    def _identity(*_args, **_kwargs):
        return None

    class DummyRequest:
        def __init__(self, *args, **kwargs):
            self.headers = {}
            self.cookies = {}
            self.url = SimpleNamespace(path="/")

    fastapi.FastAPI = DummyFastAPI
    fastapi.HTTPException = Exception
    fastapi.Body = _identity
    fastapi.UploadFile = object
    fastapi.File = _identity
    fastapi.Form = _identity
    fastapi.Request = DummyRequest

    responses.HTMLResponse = DummyResponse
    responses.Response = DummyResponse
    responses.FileResponse = DummyResponse
    responses.JSONResponse = DummyResponse
    responses.StreamingResponse = DummyResponse
    responses.RedirectResponse = DummyResponse

    sys.modules["fastapi"] = fastapi
    sys.modules["fastapi.responses"] = responses


_install_fastapi_stubs()


def _install_mss_stubs():
    if "mss" in sys.modules:
        return

    mss_mod = ModuleType("mss")
    tools_mod = ModuleType("mss.tools")

    class DummyMSS:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        @property
        def monitors(self):
            return [None, {}]

        def grab(self, _mon):
            return SimpleNamespace(rgb=b"", size=(0, 0))

    def to_png(_rgb, _size):
        return b""

    mss_mod.mss = DummyMSS
    tools_mod.to_png = to_png

    sys.modules["mss"] = mss_mod
    sys.modules["mss.tools"] = tools_mod


_install_mss_stubs()

APP_DIR = Path(__file__).resolve().parents[1] / "app"
sys.path.insert(0, str(APP_DIR))

import server as server_mod


class DummyStartupInfo:
    def __init__(self):
        self.dwFlags = 0
        self.wShowWindow = 1


class RunWslBashTests(unittest.TestCase):
    def _patch_windows_env(self, devnull):
        return ExitStack(), [
            mock.patch.object(server_mod.os, "name", "nt"),
            mock.patch.object(server_mod.subprocess, "CREATE_NEW_PROCESS_GROUP", 0x200, create=True),
            mock.patch.object(server_mod.subprocess, "DETACHED_PROCESS", 0x8, create=True),
            mock.patch.object(server_mod.subprocess, "CREATE_NO_WINDOW", 0x08000000, create=True),
            mock.patch.object(server_mod.subprocess, "STARTF_USESHOWWINDOW", 0x1, create=True),
            mock.patch.object(server_mod.subprocess, "STARTUPINFO", DummyStartupInfo, create=True),
            mock.patch.object(server_mod.subprocess, "DEVNULL", devnull, create=True),
        ]

    def test_windows_flags_added(self):
        devnull = object()
        run_result = SimpleNamespace(returncode=0, stdout="ok\n", stderr="")

        stack, patches = self._patch_windows_env(devnull)
        with stack:
            for p in patches:
                stack.enter_context(p)
            with mock.patch.object(server_mod.subprocess, "run", return_value=run_result) as run_mock:
                result = server_mod.run_wsl_bash("echo hi")

        _, kwargs = run_mock.call_args
        self.assertEqual(kwargs.get("creationflags"), 0x200 | 0x08000000)
        self.assertIs(kwargs.get("stdin"), devnull)
        self.assertIn("startupinfo", kwargs)
        self.assertEqual(result["stdout"], "ok")
        self.assertEqual(result["attempts"], 1)

    def test_retries_on_interrupt_exit(self):
        devnull = object()
        outputs = [
            SimpleNamespace(returncode=3221225786, stdout="", stderr=""),
            SimpleNamespace(returncode=0, stdout="ready\n", stderr=""),
        ]

        def fake_run(*_args, **_kwargs):
            return outputs.pop(0)

        stack, patches = self._patch_windows_env(devnull)
        with stack:
            for p in patches:
                stack.enter_context(p)
            with mock.patch.object(server_mod.subprocess, "run", side_effect=fake_run) as run_mock:
                with mock.patch.object(server_mod.time, "sleep", return_value=None) as sleep_mock:
                    result = server_mod.run_wsl_bash("echo hi")

        self.assertEqual(run_mock.call_count, 2)
        sleep_mock.assert_called_once()
        self.assertEqual(result["stdout"], "ready")
        self.assertEqual(result["exit_code"], 0)
        self.assertEqual(result["attempts"], 2)


class TmuxPanesTests(unittest.TestCase):
    def test_ok_when_no_output(self):
        with mock.patch.object(server_mod, "run_wsl_bash", return_value={
            "exit_code": 0,
            "stdout": "",
            "stderr": "",
        }):
            result = server_mod.tmux_panes()
        self.assertTrue(result["ok"])
        self.assertEqual(result["panes"], [])

    def test_parses_literal_tab_sequences(self):
        stdout = "codex\\t0\\t0\\t%1\\t1\\tbash\\t/home/megha"
        with mock.patch.object(server_mod, "run_wsl_bash", return_value={
            "exit_code": 0,
            "stdout": stdout,
            "stderr": "",
        }):
            result = server_mod.tmux_panes()
        self.assertTrue(result["ok"])
        self.assertEqual(len(result["panes"]), 1)
        pane = result["panes"][0]
        self.assertEqual(pane["session"], "codex")
        self.assertEqual(pane["pane_id"], "%1")


class TmuxCreateSessionTests(unittest.TestCase):
    def test_create_session_with_name(self):
        with mock.patch.object(server_mod, "run_wsl_bash", return_value={
            "exit_code": 0,
            "stdout": "",
            "stderr": "",
        }) as run_mock:
            result = server_mod.tmux_create_session({"name": "codex"})
        run_mock.assert_called_once_with("tmux new-session -d -s codex")
        self.assertTrue(result["ok"])
        self.assertEqual(result["name"], "codex")

    def test_create_session_without_name(self):
        with mock.patch.object(server_mod, "run_wsl_bash", return_value={
            "exit_code": 0,
            "stdout": "",
            "stderr": "",
        }) as run_mock:
            result = server_mod.tmux_create_session({})
        run_mock.assert_called_once_with("tmux new-session -d")
        self.assertTrue(result["ok"])
        self.assertIsNone(result["name"])

    def test_create_session_invalid_name(self):
        with self.assertRaises(Exception):
            server_mod.tmux_create_session({"name": "bad name"})


class TmuxCloseSessionTests(unittest.TestCase):
    def test_close_session_ok(self):
        with mock.patch.object(server_mod, "run_wsl_bash", return_value={
            "exit_code": 0,
            "stdout": "",
            "stderr": "",
        }) as run_mock:
            result = server_mod.tmux_close_session("codex")
        run_mock.assert_called_once_with("tmux kill-session -t codex")
        self.assertTrue(result["ok"])
        self.assertEqual(result["session"], "codex")

    def test_close_session_not_found(self):
        with mock.patch.object(server_mod, "run_wsl_bash", return_value={
            "exit_code": 1,
            "stdout": "",
            "stderr": "can't find session: codex",
        }):
            result = server_mod.tmux_close_session("codex")
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "not_found")

    def test_close_session_no_server(self):
        with mock.patch.object(server_mod, "run_wsl_bash", return_value={
            "exit_code": 1,
            "stdout": "",
            "stderr": "failed to connect to server",
        }):
            result = server_mod.tmux_close_session("codex")
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "tmux_server_not_running")


class WslExecutableTests(unittest.TestCase):
    def test_prefers_explicit_wsl_exe(self):
        with mock.patch.object(server_mod.os, "name", "nt"), \
             mock.patch.object(server_mod, "WSL_EXE", r"C:\\Tools\\wsl.exe"), \
             mock.patch.object(server_mod.os.path, "exists", return_value=True):
            self.assertEqual(server_mod._wsl_executable(), r"C:\\Tools\\wsl.exe")

    def test_falls_back_to_system32(self):
        def fake_exists(path):
            return path.endswith("System32\\wsl.exe") or path.endswith("System32/wsl.exe")

        with mock.patch.object(server_mod.os, "name", "nt"), \
             mock.patch.object(server_mod, "WSL_EXE", "wsl"), \
             mock.patch.object(server_mod.os.environ, "get", return_value=r"C:\\Windows"), \
             mock.patch.object(server_mod.os.path, "exists", side_effect=fake_exists):
            got = server_mod._wsl_executable().replace("/", "\\")
            self.assertTrue(got.lower().endswith("windows\\system32\\wsl.exe"))

    def test_non_windows_uses_wsl_exe(self):
        with mock.patch.object(server_mod.os, "name", "posix"), \
             mock.patch.object(server_mod, "WSL_EXE", "wsl"):
            self.assertEqual(server_mod._wsl_executable(), "wsl")


class TmuxDebugTests(unittest.TestCase):
    def test_debug_includes_repr(self):
        results = [
            {"exit_code": 0, "stdout": "megha", "stderr": ""},
            {"exit_code": 0, "stdout": "/home/megha", "stderr": ""},
            {"exit_code": 0, "stdout": "tmux 3.4", "stderr": ""},
            {"exit_code": 0, "stdout": "codex\\t$1", "stderr": ""},
            {"exit_code": 0, "stdout": "codex\\t0\\t0\\t%1\\t1\\tbash\\t/home/megha", "stderr": ""},
        ]

        def fake_run(*_args, **_kwargs):
            return results.pop(0)

        with mock.patch.object(server_mod, "run_wsl_bash", side_effect=fake_run):
            out = server_mod.tmux_debug()

        self.assertTrue(out["ok"])
        checks = out["checks"]
        self.assertIn("stdout_repr", checks["whoami"])
        self.assertIn("stdout_repr", checks["list_panes"])


class TmuxHealthTests(unittest.TestCase):
    def test_health_with_sessions(self):
        with mock.patch.object(server_mod, "run_wsl_bash", return_value={
            "exit_code": 0,
            "stdout": "codex\ncodex_trial\n",
            "stderr": "",
        }):
            out = server_mod.tmux_health()
        self.assertTrue(out["ok"])
        self.assertEqual(out["state"], "ok")
        self.assertEqual(out["count"], 2)

    def test_health_empty(self):
        with mock.patch.object(server_mod, "run_wsl_bash", return_value={
            "exit_code": 0,
            "stdout": "",
            "stderr": "",
        }):
            out = server_mod.tmux_health()
        self.assertTrue(out["ok"])
        self.assertEqual(out["state"], "empty")
        self.assertEqual(out["count"], 0)

    def test_health_no_server(self):
        with mock.patch.object(server_mod, "run_wsl_bash", return_value={
            "exit_code": 1,
            "stdout": "",
            "stderr": "failed to connect to server",
        }):
            out = server_mod.tmux_health()
        self.assertTrue(out["ok"])
        self.assertEqual(out["state"], "no_server")
        self.assertEqual(out["count"], 0)

    def test_health_error(self):
        with mock.patch.object(server_mod, "run_wsl_bash", return_value={
            "exit_code": 1,
            "stdout": "",
            "stderr": "some other error",
        }):
            out = server_mod.tmux_health()
        self.assertFalse(out["ok"])
        self.assertEqual(out["error"], "tmux_error")


class ProgressAndAuthTests(unittest.TestCase):
    def test_progress_state_error(self):
        self.assertEqual(server_mod._infer_progress_state("Traceback: failed to open file"), "error")

    def test_progress_state_waiting(self):
        self.assertEqual(server_mod._infer_progress_state("Please approve this command (y/n)"), "waiting")

    def test_progress_state_running_from_command(self):
        self.assertEqual(server_mod._infer_progress_state("", current_command="codex"), "running")

    def test_progress_state_idle(self):
        self.assertEqual(server_mod._infer_progress_state("ready"), "idle")

    def test_auth_token_required(self):
        with mock.patch.object(server_mod, "CODEX_AUTH_REQUIRED", True), \
             mock.patch.object(server_mod, "CODEX_AUTH_TOKEN", "secret"):
            self.assertTrue(server_mod._is_valid_auth_token("secret"))
            self.assertFalse(server_mod._is_valid_auth_token("wrong"))
            self.assertFalse(server_mod._is_valid_auth_token(""))


class DesktopModeTests(unittest.TestCase):
    def test_desktop_mode_default_on(self):
        req = SimpleNamespace(query_params={}, cookies={})
        self.assertTrue(server_mod._desktop_enabled_from_request(req))

    def test_desktop_mode_cookie_off(self):
        req = SimpleNamespace(
            query_params={},
            cookies={server_mod.CODEX_DESKTOP_MODE_COOKIE: "0"},
        )
        self.assertFalse(server_mod._desktop_enabled_from_request(req))

    def test_desktop_mode_query_overrides_cookie(self):
        req = SimpleNamespace(
            query_params={"desktop": "on"},
            cookies={server_mod.CODEX_DESKTOP_MODE_COOKIE: "off"},
        )
        self.assertTrue(server_mod._desktop_enabled_from_request(req))


class CompactModeTests(unittest.TestCase):
    def test_compact_mode_default_off(self):
        req = SimpleNamespace(query_params={})
        self.assertFalse(server_mod._compact_enabled_from_request(req))

    def test_compact_mode_enabled_by_flag(self):
        req = SimpleNamespace(query_params={"compact": "1"})
        self.assertTrue(server_mod._compact_enabled_from_request(req))

    def test_compact_mode_enabled_by_alias(self):
        req = SimpleNamespace(query_params={"compact": "mobile"})
        self.assertTrue(server_mod._compact_enabled_from_request(req))

    def test_mobile_entry_redirects_to_compact(self):
        class _Resp:
            def __init__(self):
                self.headers = {}

        fake_resp = _Resp()
        with mock.patch.object(server_mod, "RedirectResponse", return_value=fake_resp) as redirect_mock:
            out = server_mod.mobile_entry()
        redirect_mock.assert_called_once_with(url="/?compact=1", status_code=307)
        self.assertIs(out, fake_resp)
        self.assertEqual(out.headers.get("Cache-Control"), "no-store")


class DesktopKeyRoutingTests(unittest.TestCase):
    def test_desktop_send_key_native_backspace(self):
        with mock.patch.object(server_mod, "_send_vk") as send_vk_mock:
            out = server_mod._desktop_send_key("backspace")
        send_vk_mock.assert_called_once()
        self.assertEqual(out["exit_code"], 0)
        self.assertEqual(out["mode"], "native")

    def test_desktop_send_key_native_combo(self):
        with mock.patch.object(server_mod, "_send_vk_combo") as combo_mock:
            out = server_mod._desktop_send_key("ctrl+a")
        combo_mock.assert_called_once()
        self.assertEqual(out["exit_code"], 0)
        self.assertEqual(out["mode"], "native_combo")

    def test_desktop_send_key_unsupported(self):
        with self.assertRaises(Exception):
            server_mod._desktop_send_key("capslock")


class SseEncodingTests(unittest.TestCase):
    def test_sse_event_bytes_format(self):
        payload = {"ok": True, "x": 1}
        b = server_mod._sse_event_bytes("screen", payload)
        s = b.decode("utf-8")
        self.assertTrue(s.startswith("event: screen\n"))
        self.assertIn("\ndata: ", s)
        self.assertTrue(s.endswith("\n\n"))
        self.assertIn('"ok":true', s)
        self.assertIn('"x":1', s)

    def test_sse_event_sanitizes_newlines(self):
        b = server_mod._sse_event_bytes("bad\nev\rname", {"ok": True})
        s = b.decode("utf-8")
        self.assertIn("event: bad ev name\n", s)


class LegacyFallbackTests(unittest.TestCase):
    def test_safe_next_path_blocks_external(self):
        self.assertEqual(server_mod._safe_next_path("/"), "/")
        self.assertEqual(server_mod._safe_next_path("/diag/status"), "/diag/status")
        self.assertEqual(server_mod._safe_next_path("https://evil.example"), "/")
        self.assertEqual(server_mod._safe_next_path("//evil.example"), "/")

    def test_legacy_desktop_tap_uses_coords(self):
        fake_page = lambda title, payload, status_code=200: {
            "title": title,
            "payload": payload,
            "status_code": status_code,
        }
        with mock.patch.object(server_mod, "_legacy_result_page", side_effect=fake_page), \
             mock.patch.object(server_mod, "_desktop_monitor", return_value={"left": 0, "top": 0, "width": 1920, "height": 1080}), \
             mock.patch.object(server_mod, "desktop_input_click", return_value={"ok": True, "button": "left"}) as click_mock:
            out = server_mod.legacy_desktop_tap(tap_x=44, tap_y=55, button="left", double="0")

        click_mock.assert_called_once()
        payload = click_mock.call_args.args[0]
        self.assertEqual(payload["x"], 44)
        self.assertEqual(payload["y"], 55)
        self.assertEqual(payload["button"], "left")
        self.assertFalse(payload["double"])
        self.assertEqual(out["status_code"], 200)
        self.assertTrue(out["payload"]["ok"])

    def test_legacy_desktop_tap_scales_from_render_size(self):
        fake_page = lambda title, payload, status_code=200: {
            "title": title,
            "payload": payload,
            "status_code": status_code,
        }
        with mock.patch.object(server_mod, "_legacy_result_page", side_effect=fake_page), \
             mock.patch.object(server_mod, "_desktop_monitor", return_value={"left": 0, "top": 0, "width": 1920, "height": 1080}), \
             mock.patch.object(server_mod, "desktop_input_click", return_value={"ok": True, "button": "left"}) as click_mock:
            out = server_mod.legacy_desktop_tap(
                tap_x=210,
                tap_y=118,
                render_w=420,
                render_h=236,
                button="left",
                double="0",
            )

        payload = click_mock.call_args.args[0]
        self.assertEqual(payload["x"], 960)
        self.assertEqual(payload["y"], 540)
        self.assertEqual(out["status_code"], 200)

    def test_legacy_desktop_click_requires_pair_coords(self):
        fake_page = lambda title, payload, status_code=200: {
            "title": title,
            "payload": payload,
            "status_code": status_code,
        }
        with mock.patch.object(server_mod, "_legacy_result_page", side_effect=fake_page):
            out = server_mod.legacy_desktop_click(button="left", double="0", x="120", y="")

        self.assertEqual(out["status_code"], 400)
        self.assertFalse(out["payload"]["ok"])
        self.assertIn("provided together", out["payload"]["detail"])

    def test_legacy_auth_login_invalid_token(self):
        fake_page = lambda title, payload, status_code=200: {
            "title": title,
            "payload": payload,
            "status_code": status_code,
        }
        with mock.patch.object(server_mod, "_legacy_result_page", side_effect=fake_page), \
             mock.patch.object(server_mod, "CODEX_AUTH_REQUIRED", True), \
             mock.patch.object(server_mod, "CODEX_AUTH_TOKEN", "secret"):
            out = server_mod.legacy_auth_login(token="wrong", next="/")

        self.assertEqual(out["status_code"], 401)
        self.assertFalse(out["payload"]["ok"])
        self.assertEqual(out["payload"]["error"], "unauthorized")


if __name__ == "__main__":
    unittest.main()
