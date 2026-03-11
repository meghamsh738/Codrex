import importlib.util
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock


def _load_module():
    script = Path(__file__).resolve().parents[1] / "tools" / "codrex-send.py"
    spec = importlib.util.spec_from_file_location("codrex_send_mod", script)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)  # type: ignore[attr-defined]
    return module


codrex_send = _load_module()


class CodrexSendConfigTests(unittest.TestCase):
    def test_merge_controller_configs_keeps_main_when_local_blank(self):
        merged = codrex_send._merge_controller_configs(
            {"token": "main-token", "port": 8787},
            {"token": "", "port": 9797},
        )
        self.assertEqual(merged["token"], "main-token")
        self.assertEqual(merged["port"], 9797)

    def test_get_controller_defaults_prefers_local_token(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            main_cfg = root / "controller.config.json"
            local_cfg = root / "controller.config.local.json"
            main_cfg.write_text('{"port": 8787, "token": ""}', encoding="utf-8")
            local_cfg.write_text('{"token": "local-token"}', encoding="utf-8")

            with mock.patch.dict(os.environ, {"CODREX_CONTROLLER_CONFIG": str(main_cfg)}, clear=False), \
                 mock.patch.object(codrex_send, "_windows_local_appdata_wsl", return_value=None), \
                 mock.patch.object(codrex_send, "_build_controller_candidates", return_value=["http://127.0.0.1:8787"]), \
                 mock.patch.object(codrex_send, "_controller_reachable", return_value=True):
                base, token, cfg = codrex_send._get_controller_defaults()

            self.assertEqual(base, "http://127.0.0.1:8787")
            self.assertEqual(token, "local-token")
            self.assertEqual(cfg.get("token"), "local-token")

    def test_get_controller_defaults_env_token_wins(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            main_cfg = root / "controller.config.json"
            local_cfg = root / "controller.config.local.json"
            main_cfg.write_text('{"port": 8787, "token": "main-token"}', encoding="utf-8")
            local_cfg.write_text('{"token": "local-token"}', encoding="utf-8")

            with mock.patch.dict(
                os.environ,
                {
                    "CODREX_CONTROLLER_CONFIG": str(main_cfg),
                    "CODREX_AUTH_TOKEN": "env-token",
                },
                clear=False,
            ), mock.patch.object(codrex_send, "_windows_local_appdata_wsl", return_value=None), \
                mock.patch.object(codrex_send, "_build_controller_candidates", return_value=["http://127.0.0.1:8787"]), \
                mock.patch.object(codrex_send, "_controller_reachable", return_value=True):
                _base, token, _cfg = codrex_send._get_controller_defaults()

            self.assertEqual(token, "env-token")

    def test_get_controller_defaults_prefers_runtime_state_urls_and_token(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            main_cfg = root / "controller.config.json"
            main_cfg.write_text('{"port": 48787, "token": ""}', encoding="utf-8")

            runtime_base = root / "AppData" / "Local"
            runtime_state = runtime_base / "Codrex" / "remote-ui" / "state"
            runtime_state.mkdir(parents=True, exist_ok=True)
            (runtime_state / "controller.config.local.json").write_text(
                '{"token": "runtime-token"}',
                encoding="utf-8",
            )
            (runtime_state / "mobile.session.json").write_text(
                '{"controller_port": 48787, "network_app_url": "http://100.64.0.9:48787/"}',
                encoding="utf-8",
            )

            with mock.patch.dict(os.environ, {"CODREX_CONTROLLER_CONFIG": str(main_cfg)}, clear=False), \
                 mock.patch.object(codrex_send, "_windows_local_appdata_wsl", return_value=runtime_base), \
                 mock.patch.object(
                     codrex_send,
                     "_controller_reachable",
                     side_effect=lambda base, token: base.rstrip("/") == "http://100.64.0.9:48787" and token == "runtime-token",
                 ):
                base, token, cfg = codrex_send._get_controller_defaults()

            self.assertEqual(base, "http://100.64.0.9:48787")
            self.assertEqual(token, "runtime-token")
            self.assertEqual(cfg.get("network_app_url"), "http://100.64.0.9:48787/")

    def test_stage_file_for_outside_root(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            share_root = root / "codrex-work"
            outside_file = root / "external" / "icon.png"
            outside_file.parent.mkdir(parents=True, exist_ok=True)
            outside_file.write_bytes(b"\x89PNG\r\n\x1a\n")

            staged = codrex_send._stage_file_into_share_root(outside_file, share_root)
            self.assertTrue(staged.exists())
            self.assertTrue(codrex_send._path_within_root(staged, share_root))
            self.assertEqual(staged.read_bytes(), outside_file.read_bytes())


if __name__ == "__main__":
    unittest.main()
