import importlib.util
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "tools" / "wsl" / "codex-account.py"

spec = importlib.util.spec_from_file_location("codex_account", MODULE_PATH)
codex_account = importlib.util.module_from_spec(spec)
assert spec and spec.loader
spec.loader.exec_module(codex_account)


class CodexAccountHelperTests(unittest.TestCase):
    def test_collect_terminal_probe_replies_returns_only_unsent_queries(self):
        transcript = (
            b"\x1b[6n"
            b"\x1b[c"
            b"\x1b]10;?\x1b\\"
            b"\x1b]11;?\x1b\\"
        )
        replies = codex_account.collect_terminal_probe_replies(transcript, {b"\x1b[c"})
        self.assertEqual(
            [probe for probe, _reply in replies],
            [b"\x1b[6n", b"\x1b]10;?\x1b\\", b"\x1b]11;?\x1b\\"],
        )

    def test_parse_usage_probe_output_extracts_status_and_tip(self):
        text = (
            "\x1b[5;1H  gpt-5.4 xhigh · /tmp · 100% left · weekly 91%\n"
            "  Tip: New 2x rate limits until April 2nd.\n"
        )
        out = codex_account.parse_usage_probe_output(text)
        self.assertTrue(out["ok"])
        self.assertEqual(out["context_left"], "100% left")
        self.assertEqual(out["weekly_left"], "91%")
        self.assertEqual(out["tip"], "New 2x rate limits until April 2nd.")

    def test_config_text_is_normalized_and_rendered_per_account(self):
        source_home = "/home/megha/.codex"
        target_home = "/home/megha/.local/share/codrex/accounts/profiles/second/codex-home"
        config_text = 'config_file = "/home/megha/.codex/agents/fast_worker.toml"\n'
        exported = codex_account.normalize_config_text_for_export(config_text, source_home)
        self.assertIn(codex_account.CONFIG_HOME_SENTINEL, exported)
        rendered = codex_account.render_config_text_for_target(exported, target_home)
        self.assertIn(target_home, rendered)
        self.assertNotIn(source_home, rendered)


if __name__ == "__main__":
    unittest.main()
