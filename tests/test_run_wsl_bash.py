import sys
import tempfile
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


class TailscaleDetectionTests(unittest.TestCase):
    def test_tailscale_exe_path_uses_path_lookup(self):
        exe_path = r"C:\tools\tailscale.exe"
        exists = lambda p: p == exe_path
        which = lambda cmd: exe_path if cmd == "tailscale.exe" else ""

        with mock.patch.object(server_mod.os, "name", "nt"), \
             mock.patch.dict(server_mod.os.environ, {}, clear=True), \
             mock.patch.object(server_mod.os.path, "exists", side_effect=exists), \
             mock.patch.object(server_mod.shutil, "which", side_effect=which):
            out = server_mod._tailscale_exe_path()

        self.assertEqual(out, exe_path)

    def test_tailscale_exe_path_uses_where_fallback(self):
        exe_path = r"C:\Users\me\AppData\Local\Tailscale\tailscale.exe"
        exists = lambda p: p == exe_path

        with mock.patch.object(server_mod.os, "name", "nt"), \
             mock.patch.dict(server_mod.os.environ, {}, clear=True), \
             mock.patch.object(server_mod.os.path, "exists", side_effect=exists), \
             mock.patch.object(server_mod.shutil, "which", return_value=""), \
             mock.patch.object(server_mod.subprocess, "check_output", return_value=exe_path + "\n") as where_mock:
            out = server_mod._tailscale_exe_path()

        self.assertEqual(out, exe_path)
        where_mock.assert_called_once()

    def test_get_tailscale_ipv4_falls_back_to_ipconfig_without_exe(self):
        ipconfig_out = """
Windows IP Configuration

Ethernet adapter Tailscale:

   Connection-specific DNS Suffix  . :
   IPv4 Address. . . . . . . . . . . : 100.90.80.70
""".strip()
        with mock.patch.object(server_mod.os, "name", "nt"), \
             mock.patch.object(server_mod, "_tailscale_exe_path", return_value=""), \
             mock.patch.object(server_mod.subprocess, "check_output", return_value=ipconfig_out):
            out = server_mod.get_tailscale_ipv4()

        self.assertEqual(out, "100.90.80.70")

    def test_get_tailscale_ipv4_falls_back_to_ipconfig_after_cli_failures(self):
        exe = r"C:\Program Files\Tailscale\tailscale.exe"
        ipconfig_out = """
Windows IP Configuration

Ethernet adapter Tailscale:

   IPv4 Address. . . . . . . . . . . : 100.64.12.34
""".strip()

        def fake_check_output(args, **_kwargs):
            if args == [exe, "ip", "-4"]:
                raise RuntimeError("ip command failed")
            if args == [exe, "status", "--json"]:
                raise RuntimeError("json status failed")
            if args == [exe, "status"]:
                return ""
            if args == ["ipconfig"]:
                return ipconfig_out
            raise AssertionError(f"unexpected command: {args}")

        with mock.patch.object(server_mod.os, "name", "nt"), \
             mock.patch.object(server_mod, "_tailscale_exe_path", return_value=exe), \
             mock.patch.object(server_mod.subprocess, "check_output", side_effect=fake_check_output):
            out = server_mod.get_tailscale_ipv4()

        self.assertEqual(out, "100.64.12.34")


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


class CodexSessionConfigTests(unittest.TestCase):
    def test_reasoning_efforts_for_codex_family_model(self):
        out = server_mod._reasoning_efforts_for_model("gpt-5-codex")
        self.assertEqual(out, ["low", "medium", "high"])

    def test_codex_options_exposes_defaults(self):
        out = server_mod.codex_options()
        self.assertTrue(out["ok"])
        self.assertIn("models", out)
        self.assertIn("default_model", out)
        self.assertIn("reasoning_efforts", out)
        self.assertIn("default_reasoning_effort", out)
        self.assertTrue(out["models"])
        self.assertTrue(out["reasoning_efforts"])

    def test_codex_session_create_uses_model_and_reasoning(self):
        with mock.patch.object(server_mod, "run_wsl_bash", return_value={
            "exit_code": 0,
            "stdout": "",
            "stderr": "",
        }) as run_mock:
            out = server_mod.codex_session_create({
                "name": "demo",
                "cwd": "/home/megha/work",
                "model": "gpt-5",
                "reasoning_effort": "high",
            })

        self.assertTrue(out["ok"])
        self.assertEqual(out["model"], "gpt-5")
        self.assertEqual(out["reasoning_effort"], "high")
        cmd = run_mock.call_args.args[0]
        self.assertIn("tmux new-session", cmd)
        self.assertIn("codex -c model=gpt-5", cmd)
        self.assertIn("model=gpt-5", cmd)
        self.assertIn("model_reasoning_effort=high", cmd)

    def test_codex_session_create_clamps_reasoning_for_codex_prefixed_models(self):
        with mock.patch.object(server_mod, "run_wsl_bash", return_value={
            "exit_code": 0,
            "stdout": "",
            "stderr": "",
        }) as run_mock:
            out = server_mod.codex_session_create({
                "name": "demo",
                "cwd": "/home/megha/work",
                "model": "codex-1p-q-20251024-ev3",
                "reasoning_effort": "xhigh",
            })

        self.assertTrue(out["ok"])
        self.assertEqual(out["model"], "codex-1p-q-20251024-ev3")
        self.assertEqual(out["reasoning_effort"], "high")
        cmd = run_mock.call_args.args[0]
        self.assertIn("model=codex-1p-q-20251024-ev3", cmd)
        self.assertIn("model_reasoning_effort=high", cmd)

    def test_codex_session_create_clamps_reasoning_for_codex_family_model(self):
        with mock.patch.object(server_mod, "run_wsl_bash", return_value={
            "exit_code": 0,
            "stdout": "",
            "stderr": "",
        }) as run_mock:
            out = server_mod.codex_session_create({
                "name": "demo",
                "cwd": "/home/megha/work",
                "model": "gpt-5-codex",
                "reasoning_effort": "xhigh",
            })

        self.assertTrue(out["ok"])
        self.assertEqual(out["model"], "gpt-5-codex")
        self.assertEqual(out["reasoning_effort"], "high")
        cmd = run_mock.call_args.args[0]
        self.assertIn("model=gpt-5-codex", cmd)
        self.assertIn("model_reasoning_effort=high", cmd)

    def test_codex_session_apply_profile_sends_model_command(self):
        fake_sessions = {"codex_demo": {"session": "codex_demo"}}
        with mock.patch.object(server_mod, "_session_pane", return_value={"pane_id": "%9"}), \
             mock.patch.object(server_mod, "_tmux_send_text", return_value={
                 "exit_code": 0,
                 "stdout": "",
                 "stderr": "",
             }) as send_mock, \
             mock.patch.object(server_mod, "SESSIONS", fake_sessions):
            out = server_mod.codex_session_apply_profile(
                "codex_demo",
                {"model": "gpt-5", "reasoning_effort": "xhigh"},
            )

        self.assertTrue(out["ok"])
        self.assertEqual(out["model"], "gpt-5")
        self.assertEqual(out["reasoning_effort"], "xhigh")
        self.assertEqual(out["applied_command"], "/model gpt-5 xhigh")
        send_mock.assert_called_once_with("%9", "/model gpt-5 xhigh", codex_mode=True, timeout_s=20)
        self.assertEqual(fake_sessions["codex_demo"]["model"], "gpt-5")
        self.assertEqual(fake_sessions["codex_demo"]["reasoning_effort"], "xhigh")

    def test_codex_session_apply_profile_clamps_reasoning_for_codex_prefixed_models(self):
        fake_sessions = {"codex_demo": {"session": "codex_demo"}}
        with mock.patch.object(server_mod, "_session_pane", return_value={"pane_id": "%9"}), \
             mock.patch.object(server_mod, "_tmux_send_text", return_value={
                 "exit_code": 0,
                 "stdout": "",
                 "stderr": "",
             }) as send_mock, \
             mock.patch.object(server_mod, "SESSIONS", fake_sessions):
            out = server_mod.codex_session_apply_profile(
                "codex_demo",
                {"model": "codex-1p-q-20251024-ev3", "reasoning_effort": "xhigh"},
            )

        self.assertTrue(out["ok"])
        self.assertEqual(out["model"], "codex-1p-q-20251024-ev3")
        self.assertEqual(out["reasoning_effort"], "high")
        self.assertEqual(out["applied_command"], "/model codex-1p-q-20251024-ev3 high")
        send_mock.assert_called_once_with("%9", "/model codex-1p-q-20251024-ev3 high", codex_mode=True, timeout_s=20)
        self.assertEqual(fake_sessions["codex_demo"]["reasoning_effort"], "high")

    def test_codex_session_apply_profile_requires_session_pane(self):
        with mock.patch.object(server_mod, "_session_pane", return_value=None):
            out = server_mod.codex_session_apply_profile(
                "codex_demo",
                {"model": "gpt-5", "reasoning_effort": "high"},
            )
        self.assertFalse(out["ok"])
        self.assertEqual(out["error"], "not_found")

    def test_maybe_repair_codex_session_reasoning_clamps_xhigh(self):
        fake_sessions = {
            "codex_demo": {
                "session": "codex_demo",
                "model": "codex-1p-q-20251024-ev3",
                "reasoning_effort": "xhigh",
            }
        }
        with mock.patch.object(server_mod, "SESSIONS", fake_sessions), \
             mock.patch.object(server_mod, "_tmux_send_text", return_value={
                 "exit_code": 0,
                 "stdout": "",
                 "stderr": "",
             }) as send_mock:
            out = server_mod._maybe_repair_codex_session_reasoning("codex_demo", "%9")

        self.assertTrue(out["ok"])
        self.assertTrue(out["applied"])
        self.assertEqual(out["reasoning_effort"], "high")
        self.assertEqual(fake_sessions["codex_demo"]["reasoning_effort"], "high")
        send_mock.assert_called_once_with(
            "%9",
            "/model codex-1p-q-20251024-ev3 high",
            codex_mode=True,
            timeout_s=20,
        )

    def test_maybe_repair_codex_session_reasoning_for_codex_family_model(self):
        fake_sessions = {
            "codex_demo": {
                "session": "codex_demo",
                "model": "gpt-5-codex",
                "reasoning_effort": "xhigh",
            }
        }
        with mock.patch.object(server_mod, "SESSIONS", fake_sessions), \
             mock.patch.object(server_mod, "_tmux_send_text", return_value={
                 "exit_code": 0,
                 "stdout": "",
                 "stderr": "",
             }) as send_mock:
            out = server_mod._maybe_repair_codex_session_reasoning("codex_demo", "%9")

        self.assertTrue(out["ok"])
        self.assertTrue(out["applied"])
        self.assertEqual(out["reasoning_effort"], "high")
        self.assertEqual(fake_sessions["codex_demo"]["reasoning_effort"], "high")
        send_mock.assert_called_once_with(
            "%9",
            "/model gpt-5-codex high",
            codex_mode=True,
            timeout_s=20,
        )

    def test_codex_session_send_reports_profile_repaired(self):
        with mock.patch.object(server_mod, "_session_pane", return_value={"pane_id": "%9"}), \
             mock.patch.object(server_mod, "_maybe_repair_codex_session_reasoning", return_value={
                 "ok": True,
                 "applied": True,
                 "model": "codex-1p-q-20251024-ev3",
                 "reasoning_effort": "high",
             }), \
             mock.patch.object(server_mod, "_tmux_send_text", return_value={
                 "exit_code": 0,
                 "stdout": "",
                 "stderr": "",
             }) as send_mock:
            out = server_mod.codex_session_send("codex_demo", "hello")

        self.assertTrue(out["ok"])
        self.assertTrue(out["profile_repaired"])
        self.assertEqual(out["profile_model"], "codex-1p-q-20251024-ev3")
        self.assertEqual(out["profile_reasoning_effort"], "high")
        send_mock.assert_called_once_with("%9", "hello", codex_mode=True, timeout_s=20)

    def test_parse_share_command_valid(self):
        out = server_mod._parse_share_command(
            'codrex-send "/home/megha/codrex-work/output/result.png" --title "Result" --expires 24'
        )
        self.assertTrue(out["is_command"])
        self.assertTrue(out["ok"])
        self.assertEqual(out["path"], "/home/megha/codrex-work/output/result.png")
        self.assertEqual(out["title"], "Result")
        self.assertEqual(out["expires_hours"], 24)
        self.assertFalse(out["send_telegram"])
        self.assertEqual(out["caption"], "")

    def test_parse_share_command_with_telegram(self):
        out = server_mod._parse_share_command(
            'codrex-send "/home/megha/codrex-work/output/result.png" --telegram --caption "Run output"'
        )
        self.assertTrue(out["is_command"])
        self.assertTrue(out["ok"])
        self.assertTrue(out["send_telegram"])
        self.assertEqual(out["caption"], "Run output")

    def test_parse_share_command_tgsend_defaults_to_telegram(self):
        out = server_mod._parse_share_command(
            'tgsend "/home/megha/codrex-work/output/result.png" --title "Result"'
        )
        self.assertTrue(out["is_command"])
        self.assertTrue(out["ok"])
        self.assertTrue(out["send_telegram"])

    def test_parse_share_command_respects_default_send_toggle(self):
        with mock.patch.object(server_mod, "CODEX_TELEGRAM_DEFAULT_SEND", True):
            out = server_mod._parse_share_command(
                'codrex-send "/home/megha/codrex-work/output/result.png"'
            )
        self.assertTrue(out["is_command"])
        self.assertTrue(out["ok"])
        self.assertTrue(out["send_telegram"])

    def test_parse_share_command_allows_no_telegram_override(self):
        with mock.patch.object(server_mod, "CODEX_TELEGRAM_DEFAULT_SEND", True):
            out = server_mod._parse_share_command(
                'codrex-send "/home/megha/codrex-work/output/result.png" --no-telegram'
            )
        self.assertTrue(out["is_command"])
        self.assertTrue(out["ok"])
        self.assertFalse(out["send_telegram"])

    def test_parse_share_command_invalid_option(self):
        out = server_mod._parse_share_command('codrex-send "/tmp/a.png" --bad 1')
        self.assertTrue(out["is_command"])
        self.assertFalse(out["ok"])
        self.assertIn("Unknown option", out["detail"])

    def test_codex_session_send_intercepts_share_command(self):
        fake_item = {
            "id": "shr_demo123",
            "title": "Result",
            "file_name": "result.png",
            "mime_type": "image/png",
            "size_bytes": 1200,
            "created_at": 1,
            "expires_at": 2,
            "created_by": "session:codex_demo",
            "is_image": True,
            "wsl_path": "/home/megha/codrex-work/output/result.png",
        }
        with mock.patch.object(server_mod, "_session_pane", return_value={"pane_id": "%9"}), \
             mock.patch.object(server_mod, "_create_shared_outbox_item", return_value=fake_item) as create_mock, \
             mock.patch.object(server_mod, "_tmux_send_text") as send_mock:
            out = server_mod.codex_session_send(
                "codex_demo",
                'codrex-send "/home/megha/codrex-work/output/result.png" --title "Result" --expires 24',
            )

        self.assertTrue(out["ok"])
        self.assertIn("shared_file", out)
        self.assertEqual(out["shared_file"]["id"], "shr_demo123")
        create_mock.assert_called_once_with(
            "/home/megha/codrex-work/output/result.png",
            title="Result",
            expires_hours=24,
            created_by="session:codex_demo",
        )
        send_mock.assert_not_called()

    def test_codex_session_send_share_command_with_telegram(self):
        fake_item = {
            "id": "shr_demo123",
            "title": "Result",
            "file_name": "result.png",
            "mime_type": "image/png",
            "size_bytes": 1200,
            "created_at": 1,
            "expires_at": 2,
            "created_by": "session:codex_demo",
            "is_image": True,
            "wsl_path": "/home/megha/codrex-work/output/result.png",
        }
        with mock.patch.object(server_mod, "_session_pane", return_value={"pane_id": "%9"}), \
             mock.patch.object(server_mod, "_create_shared_outbox_item", return_value=fake_item), \
             mock.patch.object(server_mod, "_telegram_send_shared_item", return_value={"ok": True, "message_id": 99}) as tg_mock:
            out = server_mod.codex_session_send(
                "codex_demo",
                'codrex-send "/home/megha/codrex-work/output/result.png" --telegram --caption "Result"',
            )

        self.assertTrue(out["ok"])
        self.assertIn("shared_file", out)
        self.assertIn("telegram", out)
        self.assertTrue(out["telegram"]["ok"])
        tg_mock.assert_called_once()

    def test_codex_sessions_live_includes_recent_known_session_without_pane(self):
        now = server_mod.time.time()
        fake_sessions = {
            "codex_demo": {
                "session": "codex_demo",
                "cwd": "/home/megha/work",
                "state": "starting",
                "created_at": now,
                "updated_at": now,
                "model": "gpt-5-codex",
                "reasoning_effort": "high",
            }
        }
        with mock.patch.object(server_mod, "_tmux_list_panes", return_value=[]), \
             mock.patch.object(server_mod, "SESSIONS", fake_sessions):
            out = server_mod.codex_sessions_live()

        self.assertTrue(out["ok"])
        self.assertEqual(len(out["sessions"]), 1)
        self.assertEqual(out["sessions"][0]["session"], "codex_demo")
        self.assertEqual(out["sessions"][0]["state"], "starting")

    def test_codex_sessions_live_drops_stale_known_session_without_pane(self):
        old = server_mod.time.time() - 600
        fake_sessions = {
            "codex_stale": {
                "session": "codex_stale",
                "cwd": "/home/megha/work",
                "state": "starting",
                "created_at": old,
                "updated_at": old,
                "model": "gpt-5-codex",
                "reasoning_effort": "high",
            }
        }
        with mock.patch.object(server_mod, "_tmux_list_panes", return_value=[]), \
             mock.patch.object(server_mod, "SESSIONS", fake_sessions):
            out = server_mod.codex_sessions_live()

        self.assertTrue(out["ok"])
        self.assertEqual(out["sessions"], [])
        self.assertNotIn("codex_stale", fake_sessions)

    def test_codex_session_screen_prunes_session_without_pane(self):
        fake_sessions = {"codex_demo": {"session": "codex_demo", "state": "starting"}}
        with mock.patch.object(server_mod, "_session_pane", return_value=None), \
             mock.patch.object(server_mod, "SESSIONS", fake_sessions):
            out = server_mod.codex_session_screen("codex_demo")

        self.assertFalse(out["ok"])
        self.assertEqual(out["error"], "not_found")
        self.assertNotIn("codex_demo", fake_sessions)

    def test_auth_bootstrap_local_rejects_non_localhost(self):
        req = SimpleNamespace(headers={"host": "100.64.0.9:8787", "origin": "http://100.64.0.9:8787"})
        with mock.patch.object(server_mod, "CODEX_AUTH_REQUIRED", True), \
             mock.patch.object(server_mod, "CODEX_AUTH_TOKEN", "secret"):
            out = server_mod.auth_bootstrap_local(req)
        self.assertFalse(out["ok"])
        self.assertEqual(out["error"], "forbidden")

    def test_auth_bootstrap_local_sets_cookie_for_localhost(self):
        req = SimpleNamespace(headers={"host": "localhost:8787", "origin": "http://localhost:8787"})

        class _Resp:
            def __init__(self, payload):
                self.payload = payload
                self.cookies = {}

            def set_cookie(self, key, value, **_kwargs):
                self.cookies[key] = value

        with mock.patch.object(server_mod, "CODEX_AUTH_REQUIRED", True), \
             mock.patch.object(server_mod, "CODEX_AUTH_TOKEN", "secret"), \
             mock.patch.object(server_mod, "JSONResponse", side_effect=lambda payload: _Resp(payload)):
            out = server_mod.auth_bootstrap_local(req)

        self.assertTrue(out.payload["ok"])
        self.assertEqual(out.cookies.get(server_mod.CODEX_AUTH_COOKIE), "secret")


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

    def test_require_desktop_enabled_rejects_when_off(self):
        req = SimpleNamespace(
            query_params={},
            cookies={server_mod.CODEX_DESKTOP_MODE_COOKIE: "0"},
        )
        with self.assertRaises(Exception) as ctx:
            server_mod._require_desktop_enabled(req)
        self.assertIn("Desktop control is disabled", str(ctx.exception))

    def test_desktop_info_reports_mode_flag(self):
        req = SimpleNamespace(
            query_params={},
            cookies={server_mod.CODEX_DESKTOP_MODE_COOKIE: "0"},
        )
        with mock.patch.object(server_mod, "_ensure_windows_host"), \
             mock.patch.object(server_mod, "_desktop_monitor", return_value={"left": 0, "top": 0, "width": 1920, "height": 1080}):
            out = server_mod.desktop_info(req)
        self.assertTrue(out["ok"])
        self.assertFalse(out["enabled"])

    def test_desktop_input_click_blocked_when_mode_off(self):
        req = SimpleNamespace(
            query_params={},
            cookies={server_mod.CODEX_DESKTOP_MODE_COOKIE: "off"},
        )
        with mock.patch.object(server_mod, "_ensure_windows_host"), \
             mock.patch.object(server_mod, "_desktop_click") as click_mock:
            with self.assertRaises(Exception) as ctx:
                server_mod.desktop_input_click(req, {"button": "left"})
        self.assertIn("Desktop control is disabled", str(ctx.exception))
        click_mock.assert_not_called()

    def test_downsample_rgb_nearest_reduces_size(self):
        # 2x2 image: R, G, B, W
        rgb = bytes([
            255, 0, 0,
            0, 255, 0,
            0, 0, 255,
            255, 255, 255,
        ])
        out_rgb, out_size = server_mod._downsample_rgb_nearest(rgb, (2, 2), 2)
        self.assertEqual(out_size, (1, 1))
        self.assertEqual(out_rgb, bytes([255, 0, 0]))

    def test_rgb_to_grayscale_equal_channels(self):
        rgb = bytes([10, 20, 30, 100, 120, 140])
        gray = server_mod._rgb_to_grayscale(rgb)
        self.assertEqual(len(gray), len(rgb))
        self.assertEqual(gray[0], gray[1])
        self.assertEqual(gray[1], gray[2])
        self.assertEqual(gray[3], gray[4])
        self.assertEqual(gray[4], gray[5])


class SharedOutboxTests(unittest.TestCase):
    def test_detect_mime_from_bytes(self):
        self.assertEqual(server_mod._detect_mime_from_bytes(b"%PDF-1.4\n"), "application/pdf")
        self.assertEqual(server_mod._detect_mime_from_bytes(b"\x89PNG\r\n\x1a\n\x00\x00\x00\r"), "image/png")
        self.assertEqual(server_mod._detect_mime_from_bytes(b"hello world\n"), "text/plain")

    def test_create_shared_item_prefers_detected_mime_over_extension(self):
        with tempfile.TemporaryDirectory() as tmp:
            fake_png = Path(tmp) / "proof.png"
            fake_png.write_bytes(b"%PDF-1.4\n1 0 obj\n<<>>\nendobj\n")
            outbox = Path(tmp) / "shared-outbox.json"
            with mock.patch.object(server_mod, "SHARED_OUTBOX_FILE", str(outbox)), \
                 mock.patch.object(server_mod, "SHARED_OUTBOX_LOADED", False), \
                 mock.patch.object(server_mod, "SHARED_OUTBOX_DATA", {"version": 1, "items": []}), \
                 mock.patch.object(server_mod, "_resolve_wsl_path", return_value=str(fake_png)), \
                 mock.patch.object(server_mod, "_wsl_unc_path", return_value=str(fake_png)):
                item = server_mod._create_shared_outbox_item(str(fake_png), title="", expires_hours=24, created_by="test")
        self.assertEqual(item["mime_type"], "application/pdf")
        self.assertFalse(item["is_image"])

    def test_telegram_send_corrects_mime_and_filename_from_content(self):
        class _DummyResp:
            def __init__(self, body: bytes):
                self.status = 200
                self._body = body

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def read(self):
                return self._body

        with tempfile.TemporaryDirectory() as tmp:
            fake_png = Path(tmp) / "proof.png"
            fake_png.write_bytes(b"%PDF-1.4\n1 0 obj\n<<>>\nendobj\n")
            item = {
                "id": "shr_demo",
                "title": "Proof",
                "file_name": "proof.png",
                "mime_type": "image/png",
                "wsl_path": "/home/megha/codrex-work/output/proof.png",
            }
            with mock.patch.object(server_mod, "TELEGRAM_BOT_TOKEN", "123:abc"), \
                 mock.patch.object(server_mod, "_telegram_resolve_chat_id", return_value="12345"), \
                 mock.patch.object(server_mod, "_resolve_wsl_path", return_value=str(fake_png)), \
                 mock.patch.object(server_mod, "_wsl_unc_path", return_value=str(fake_png)), \
                 mock.patch.object(server_mod.urllib.request, "urlopen", return_value=_DummyResp(b'{"ok":true,"result":{"message_id":7}}')):
                out = server_mod._telegram_send_shared_item(item)
        self.assertTrue(out["ok"])
        self.assertTrue(out["mime_corrected"])
        self.assertEqual(out["mime_type"], "application/pdf")
        self.assertTrue(str(out["file_name"]).endswith(".pdf"))

    def test_parse_telegram_secret_text(self):
        raw = """
        # comment
        token = 123456:ABC_DEF-ghi
        chat_id = -1001234567890
        """
        out = server_mod._parse_telegram_secret_text(raw)
        self.assertEqual(out["token"], "123456:ABC_DEF-ghi")
        self.assertEqual(out["chat_id"], "-1001234567890")

    def test_telegram_resolve_chat_id_from_file(self):
        with mock.patch.object(server_mod, "TELEGRAM_CHAT_ID", ""), \
             mock.patch.object(server_mod, "TELEGRAM_CHAT_FILE", "/tmp/chat-id.txt"), \
             mock.patch.object(server_mod, "_read_text_file", return_value="-1001234567890\n"), \
             mock.patch.object(server_mod, "_telegram_discover_chat_id", return_value=""):
            out = server_mod._telegram_resolve_chat_id(allow_discovery=True)
        self.assertEqual(out, "-1001234567890")

    def test_telegram_resolve_chat_id_discovers_when_missing(self):
        with mock.patch.object(server_mod, "TELEGRAM_CHAT_ID", ""), \
             mock.patch.object(server_mod, "TELEGRAM_BOT_TOKEN", "123:abc"), \
             mock.patch.object(server_mod, "_read_text_file", return_value=""), \
             mock.patch.object(server_mod, "_telegram_discover_chat_id", return_value="123456789") as discover_mock, \
             mock.patch.object(server_mod, "_persist_telegram_chat_id", return_value=None) as persist_mock:
            out = server_mod._telegram_resolve_chat_id(allow_discovery=True)
        self.assertEqual(out, "123456789")
        discover_mock.assert_called_once()
        persist_mock.assert_called_once_with("123456789")

    def test_shares_list_returns_public_download_url(self):
        fake_item = {
            "id": "shr_abc123",
            "title": "Result",
            "file_name": "result.png",
            "mime_type": "image/png",
            "size_bytes": 1200,
            "created_at": 1,
            "expires_at": 9999999999999,
            "created_by": "session:codex_demo",
            "is_image": True,
            "wsl_path": "/home/megha/codrex-work/output/result.png",
        }
        with mock.patch.object(server_mod, "SHARED_OUTBOX_LOADED", True), \
             mock.patch.object(server_mod, "SHARED_OUTBOX_DATA", {"items": [fake_item]}):
            out = server_mod.shares_list()
        self.assertTrue(out["ok"])
        self.assertEqual(len(out["items"]), 1)
        self.assertEqual(out["items"][0]["download_url"], "/share/file/shr_abc123")

    def test_shares_delete_removes_item(self):
        data = {"items": [{"id": "shr_keep"}, {"id": "shr_drop"}]}
        with mock.patch.object(server_mod, "SHARED_OUTBOX_DATA", data), \
             mock.patch.object(server_mod, "SHARED_OUTBOX_LOADED", True), \
             mock.patch.object(server_mod, "_load_shared_outbox_unlocked", return_value=None), \
             mock.patch.object(server_mod, "_persist_shared_outbox_unlocked", return_value=None):
            out = server_mod.shares_delete("shr_drop")

        self.assertTrue(out["ok"])
        self.assertEqual(out["share_id"], "shr_drop")
        self.assertEqual(len(data["items"]), 1)
        self.assertEqual(data["items"][0]["id"], "shr_keep")

    def test_shares_send_telegram(self):
        fake_item = {
            "id": "shr_abc123",
            "title": "Result",
            "file_name": "result.png",
            "mime_type": "image/png",
            "size_bytes": 1200,
            "created_at": 1,
            "expires_at": 9999999999999,
            "created_by": "session:codex_demo",
            "is_image": True,
            "wsl_path": "/home/megha/codrex-work/output/result.png",
        }
        data = {"items": [fake_item]}
        with mock.patch.object(server_mod, "SHARED_OUTBOX_DATA", data), \
             mock.patch.object(server_mod, "SHARED_OUTBOX_LOADED", True), \
             mock.patch.object(server_mod, "_load_shared_outbox_unlocked", return_value=None), \
             mock.patch.object(server_mod, "_telegram_send_shared_item", return_value={"ok": True, "message_id": 7}) as tg_mock:
            out = server_mod.shares_send_telegram("shr_abc123", {"caption": "Result"})

        self.assertTrue(out["ok"])
        self.assertEqual(out["share_id"], "shr_abc123")
        self.assertTrue(out["telegram"]["ok"])
        tg_mock.assert_called_once()

    def test_telegram_status_masked(self):
        with mock.patch.object(server_mod, "TELEGRAM_BOT_TOKEN", "123456:ABCDEF"), \
             mock.patch.object(server_mod, "TELEGRAM_CHAT_ID", "123456789"), \
             mock.patch.object(server_mod, "TELEGRAM_API_BASE", "https://api.telegram.org"), \
             mock.patch.object(server_mod, "TELEGRAM_MAX_FILE_MB", 45):
            out = server_mod.telegram_status()

        self.assertTrue(out["ok"])
        self.assertTrue(out["configured"])
        self.assertEqual(out["api_base"], "https://api.telegram.org")
        self.assertEqual(out["max_file_mb"], 45)
        self.assertTrue("*" in out["chat_id_masked"])

    def test_telegram_send_text_success(self):
        class _DummyResp:
            def __init__(self, body: bytes):
                self.status = 200
                self._body = body

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def read(self):
                return self._body

        with mock.patch.object(server_mod, "TELEGRAM_BOT_TOKEN", "123:abc"), \
             mock.patch.object(server_mod, "_telegram_resolve_chat_id", return_value="12345"), \
             mock.patch.object(server_mod.urllib.request, "urlopen", return_value=_DummyResp(b'{"ok":true,"result":{"message_id":11}}')):
            out = server_mod._telegram_send_text("remote ping")

        self.assertTrue(out["ok"])
        self.assertEqual(out["message_id"], 11)
        self.assertEqual(out["length"], len("remote ping"))

    def test_telegram_send_text_endpoint(self):
        with mock.patch.object(server_mod, "_telegram_send_text", return_value={"ok": True, "message_id": 17}) as send_mock:
            out = server_mod.telegram_send_text({"text": "hello"})
        self.assertTrue(out["ok"])
        self.assertEqual(out["detail"], "Sent to Telegram.")
        send_mock.assert_called_once_with("hello")


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
        req = SimpleNamespace(query_params={}, cookies={server_mod.CODEX_DESKTOP_MODE_COOKIE: "1"})
        with mock.patch.object(server_mod, "_legacy_result_page", side_effect=fake_page), \
             mock.patch.object(server_mod, "_desktop_monitor", return_value={"left": 0, "top": 0, "width": 1920, "height": 1080}), \
             mock.patch.object(server_mod, "desktop_input_click", return_value={"ok": True, "button": "left"}) as click_mock:
            out = server_mod.legacy_desktop_tap(request=req, tap_x=44, tap_y=55, button="left", double="0")

        click_mock.assert_called_once()
        payload = click_mock.call_args.args[1]
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
        req = SimpleNamespace(query_params={}, cookies={server_mod.CODEX_DESKTOP_MODE_COOKIE: "1"})
        with mock.patch.object(server_mod, "_legacy_result_page", side_effect=fake_page), \
             mock.patch.object(server_mod, "_desktop_monitor", return_value={"left": 0, "top": 0, "width": 1920, "height": 1080}), \
             mock.patch.object(server_mod, "desktop_input_click", return_value={"ok": True, "button": "left"}) as click_mock:
            out = server_mod.legacy_desktop_tap(
                request=req,
                tap_x=210,
                tap_y=118,
                render_w=420,
                render_h=236,
                button="left",
                double="0",
            )

        payload = click_mock.call_args.args[1]
        self.assertEqual(payload["x"], 960)
        self.assertEqual(payload["y"], 540)
        self.assertEqual(out["status_code"], 200)

    def test_legacy_desktop_click_requires_pair_coords(self):
        fake_page = lambda title, payload, status_code=200: {
            "title": title,
            "payload": payload,
            "status_code": status_code,
        }
        req = SimpleNamespace(query_params={}, cookies={server_mod.CODEX_DESKTOP_MODE_COOKIE: "1"})
        with mock.patch.object(server_mod, "_legacy_result_page", side_effect=fake_page):
            out = server_mod.legacy_desktop_click(request=req, button="left", double="0", x="120", y="")

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


class ThreadStoreTests(unittest.TestCase):
    def _reset_threads_store(self):
        server_mod.THREADS_LOADED = False
        server_mod.THREADS_DATA = {"threads": [], "messages": {}}

    def test_thread_create_message_and_read(self):
        with tempfile.TemporaryDirectory() as tmp:
            store_path = str(Path(tmp) / "threads-store.json")
            with mock.patch.object(server_mod, "THREADS_FILE", store_path):
                self._reset_threads_store()

                created = server_mod.thread_create({"session": "codex_demo", "title": "Release Prep"})
                self.assertTrue(created["ok"])
                thread = created["thread"]
                self.assertEqual(thread["session"], "codex_demo")
                self.assertEqual(thread["title"], "Release Prep")

                msg = server_mod.thread_add_message(thread["id"], {"role": "user", "text": "Summarize blockers"})
                self.assertTrue(msg["ok"])
                self.assertEqual(msg["message"]["thread_id"], thread["id"])

                snap = server_mod.threads_store_get()
                self.assertTrue(snap["ok"])
                self.assertEqual(len(snap["threads"]), 1)
                self.assertEqual(len(snap["messages"].get(thread["id"], [])), 1)
                self.assertTrue(Path(store_path).exists())

    def test_thread_update_and_delete(self):
        with tempfile.TemporaryDirectory() as tmp:
            store_path = str(Path(tmp) / "threads-store.json")
            with mock.patch.object(server_mod, "THREADS_FILE", store_path):
                self._reset_threads_store()

                created = server_mod.thread_create({"session": "codex_demo", "title": "Initial"})
                tid = created["thread"]["id"]

                updated = server_mod.thread_update(tid, {"title": "Renamed Thread"})
                self.assertTrue(updated["ok"])
                self.assertEqual(updated["thread"]["title"], "Renamed Thread")

                deleted = server_mod.thread_delete(tid)
                self.assertTrue(deleted["ok"])

                snap = server_mod.threads_store_get()
                self.assertEqual(snap["threads"], [])
                self.assertEqual(snap["messages"], {})

    def test_thread_message_dedup_by_id(self):
        with tempfile.TemporaryDirectory() as tmp:
            store_path = str(Path(tmp) / "threads-store.json")
            with mock.patch.object(server_mod, "THREADS_FILE", store_path):
                self._reset_threads_store()

                created = server_mod.thread_create({"session": "codex_demo", "title": "Dedup"})
                tid = created["thread"]["id"]

                first = server_mod.thread_add_message(
                    tid,
                    {"id": "msg_fixed_1", "role": "user", "text": "First"},
                )
                second = server_mod.thread_add_message(
                    tid,
                    {"id": "msg_fixed_1", "role": "user", "text": "Second"},
                )
                self.assertTrue(first["ok"])
                self.assertTrue(second["ok"])
                self.assertEqual(first["message"]["id"], second["message"]["id"])
                self.assertEqual(first["message"]["text"], "First")

                snap = server_mod.threads_store_get()
                self.assertEqual(len(snap["messages"].get(tid, [])), 1)


if __name__ == "__main__":
    unittest.main()
