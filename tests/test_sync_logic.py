import json
import tempfile
import unittest
import warnings
from pathlib import Path
from unittest.mock import patch

from src.filter import get_ignore_match_source, get_ignore_spec
from src.config_loader import validate_config
from src.sync import comm
from src.sync import manager
from src.sync import remote_scan
from src.sync import view
from src.sync.scanner import SYNC_STATE_FILENAME


class SyncLogicTests(unittest.TestCase):
    def test_load_filtered_local_state_writes_clean_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            (project / ".gitignore").write_text("cache/\n*.log\n", encoding="utf-8")
            state = {
                "index.html": {"type": "file", "size": 10, "md5": "a"},
                "debug.log": {"type": "file", "size": 20, "md5": "b"},
                "cache": {"type": "dir", "size": 0},
            }
            (project / SYNC_STATE_FILENAME).write_text(json.dumps(state), encoding="utf-8")

            spec = get_ignore_spec(project)
            clean_state, ignored = manager._load_filtered_local_state(project, spec)

            self.assertEqual(set(clean_state), {"index.html"})
            self.assertEqual(set(ignored), {"debug.log", "cache"})
            saved_state = json.loads((project / SYNC_STATE_FILENAME).read_text(encoding="utf-8"))
            self.assertEqual(set(saved_state), {"index.html"})

    def test_resolve_remote_target_scans_when_state_differs(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            (project / ".gitignore").write_text("server.json\n", encoding="utf-8")
            spec = get_ignore_spec(project)
            local_state = {"index.html": {"type": "file", "size": 10, "md5": "a"}}
            remote_state = {"index.html": {"type": "file", "size": 11, "md5": "b"}}
            scanned = {"index.html": {"type": "file", "size": 10}}

            def fake_scan(protocol, cfg, scan_spec, ignored_paths):
                ignored_paths["server.json"] = {"type": "file", "size": 1, "origin": "remote"}
                return scanned

            with patch("src.sync.remote.get_real_remote_structure", side_effect=fake_scan) as scan:
                scan_meta = {"remote_scan": False}
                target, remote_ignored = manager._resolve_remote_target("ftp", {}, local_state, remote_state, spec, scan_meta)

        scan.assert_called_once()
        self.assertEqual(target, scanned)
        self.assertEqual(set(remote_ignored), {"server.json"})
        self.assertTrue(scan_meta["remote_scan"])

    def test_resolve_remote_target_respects_scan_mismatch_config(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            (project / ".gitignore").write_text("server.json\n", encoding="utf-8")
            spec = get_ignore_spec(project)
            local_state = {"index.html": {"type": "file", "size": 10, "md5": "a"}}
            remote_state = {"index.html": {"type": "file", "size": 11, "md5": "b"}}

            with patch("src.sync.remote.load_config", return_value={"remote_scan_on_state_mismatch": False}):
                with patch("src.sync.remote.get_real_remote_structure") as scan:
                    target, remote_ignored = manager._resolve_remote_target("ftp", {}, local_state, remote_state, spec)

        scan.assert_not_called()
        self.assertEqual(target, remote_state)
        self.assertEqual(remote_ignored, {})

    def test_config_validates_remote_scan_toggle(self):
        self.assertTrue(validate_config({})["remote_scan_on_state_mismatch"])
        self.assertFalse(validate_config({"remote_scan_on_state_mismatch": False})["remote_scan_on_state_mismatch"])
        self.assertTrue(validate_config({"remote_scan_on_state_mismatch": "no"})["remote_scan_on_state_mismatch"])

    def test_merge_ignored_preserves_multiple_origins(self):
        merged = manager._merge_ignored(
            {"debug.log": {"type": "file", "size": 1, "origin": "state"}},
            {"debug.log": {"type": "file", "size": 1, "origin": "local", "ignored_by": ".gitignore:1"}},
        )

        self.assertEqual(set(merged["debug.log"]["origin"].split("+")), {"local", "state"})
        self.assertEqual(merged["debug.log"]["ignored_by"], ".gitignore:1")

    def test_ignore_match_source_reports_rule_location(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            (project / ".gitignore").write_text("*.log\n", encoding="utf-8")

            spec = get_ignore_spec(project)
            source = get_ignore_match_source("debug.log", spec)

            self.assertEqual(source, ".gitignore:1")

    def test_ignore_spec_uses_non_deprecated_syntax(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            (project / ".gitignore").write_text("*.log\n", encoding="utf-8")

            with warnings.catch_warnings(record=True) as caught:
                warnings.simplefilter("always")
                spec = get_ignore_spec(project)
                self.assertTrue(spec.match_file("debug.log"))

            deprecated = [w for w in caught if issubclass(w.category, DeprecationWarning)]
            self.assertEqual(deprecated, [])

    def test_sync_tree_uses_custom_added_label(self):
        captured = []

        class FakeConsole:
            def print(self, value):
                captured.append(str(getattr(value, "renderable", value)))

        original_console = view.console
        try:
            view.console = FakeConsole()
            view.display_sync_tree(
                {"index.html": "added"},
                {"index.html": {"type": "file", "size": 1}},
                {},
                "demo",
                {"added": 1, "updated": 0, "deleted": 0, "conflict": 0},
                added_label="将重建远程"
            )
        finally:
            view.console = original_console

        self.assertTrue(any("将重建远程" in item for item in captured))

    def test_remote_scan_stats_output(self):
        captured = []

        with patch("src.sync.remote_scan.print_info", side_effect=captured.append):
            remote_scan._print_remote_scan_stats({"dirs": 2, "files": 3, "filtered": 1}, 0)

        self.assertTrue(any("目录 2" in item and "文件 3" in item and "已过滤 1" in item for item in captured))

    def test_log_action_writes_enhanced_fields(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            manager.log_action(
                project,
                "Incremental Sync",
                {"added": 1, "updated": 2, "deleted": 3, "conflict": 4},
                direction="upload",
                force=False,
                filtered_count=5,
                failed_count=6,
                elapsed=1.25,
                remote_scan=True,
                status="failed"
            )

            log_text = (project / SYNC_STATE_FILENAME.replace("state", "log")).read_text(encoding="utf-8")

        self.assertIn("Incremental Sync", log_text)
        self.assertIn("status=failed", log_text)
        self.assertIn("direction=upload", log_text)
        self.assertIn("filtered=5", log_text)
        self.assertIn("failed=6", log_text)
        self.assertIn("remote_scan=True", log_text)
        self.assertIn("elapsed=1.25s", log_text)


if __name__ == "__main__":
    unittest.main()
