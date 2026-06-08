import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.filter import get_ignore_match_source, get_ignore_spec
from src.sync import manager
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

            with patch("src.sync.manager.get_real_remote_structure", side_effect=fake_scan) as scan:
                target, remote_ignored = manager._resolve_remote_target("ftp", {}, local_state, remote_state, spec)

        scan.assert_called_once()
        self.assertEqual(target, scanned)
        self.assertEqual(set(remote_ignored), {"server.json"})

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


if __name__ == "__main__":
    unittest.main()
