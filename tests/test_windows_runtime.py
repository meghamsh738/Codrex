import json
import os
import shutil
import socket
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RUNTIME_SCRIPT = ROOT / "tools" / "windows" / "codrex-runtime.ps1"


def _to_windows_path(path: Path) -> str:
    raw = str(path)
    if raw.startswith("/mnt/") and len(raw) > 6:
        drive = raw[5].upper()
        rest = raw[7:].replace("/", "\\")
        return f"{drive}:\\{rest}"
    return raw


@unittest.skipUnless(shutil.which("powershell.exe"), "powershell.exe not available")
class WindowsRuntimeScriptTests(unittest.TestCase):
    def _free_port(self) -> int:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
        sock.close()
        return port

    def _run_runtime(self, action: str, runtime_dir: Path):
        env = os.environ.copy()
        env["CODEX_RUNTIME_DIR"] = _to_windows_path(runtime_dir)
        cmd = [
            "powershell.exe",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            _to_windows_path(RUNTIME_SCRIPT),
            "-RuntimeDir",
            _to_windows_path(runtime_dir),
            "-Action",
            action,
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, env=env, check=False)
        output = (result.stdout or "").strip()
        self.assertTrue(output, msg=result.stderr)
        payload = json.loads(output.splitlines()[-1])
        return result, payload

    def test_status_reports_stopped_for_empty_runtime(self):
        with tempfile.TemporaryDirectory(dir=str(ROOT)) as td:
            runtime_dir = Path(td)
            test_port = self._free_port()
            state_dir = runtime_dir / "state"
            state_dir.mkdir(parents=True, exist_ok=True)
            (state_dir / "controller.config.local.json").write_text(
                json.dumps({"port": test_port, "token": "test-token"}),
                encoding="utf-8",
            )
            result, payload = self._run_runtime("status", runtime_dir)

        self.assertEqual(result.returncode, 0)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["status"], "stopped")
        self.assertFalse(payload["session_present"])

    def test_repair_removes_stale_session(self):
        with tempfile.TemporaryDirectory(dir=str(ROOT)) as td:
            runtime_dir = Path(td)
            test_port = self._free_port()
            state_dir = runtime_dir / "state"
            state_dir.mkdir(parents=True, exist_ok=True)
            (state_dir / "controller.config.local.json").write_text(
                json.dumps({"port": test_port, "token": "test-token"}),
                encoding="utf-8",
            )
            session_path = state_dir / "mobile.session.json"
            session_path.write_text(
                json.dumps({"controller_port": test_port, "ui_mode": "built"}),
                encoding="utf-8",
            )

            status_result, status_payload = self._run_runtime("status", runtime_dir)
            repair_result, repair_payload = self._run_runtime("repair", runtime_dir)

            self.assertEqual(status_result.returncode, 0)
            self.assertEqual(status_payload["status"], "recovering")
            self.assertEqual(repair_result.returncode, 0)
            self.assertTrue(repair_payload["ok"])
            self.assertTrue(repair_payload["repaired"])
            self.assertEqual(repair_payload["status"], "stopped")
            self.assertFalse(session_path.exists())


if __name__ == "__main__":
    unittest.main()
