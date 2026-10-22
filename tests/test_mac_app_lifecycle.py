import subprocess
import tempfile
import unittest
from unittest.mock import patch

from personal_context.mac_app_lifecycle import collected_app


class MacAppLifecycleTests(unittest.TestCase):
    def test_cold_app_is_ready_before_collection_and_restored_afterward(self):
        state = {"running": False, "launched": False, "ready_probes": 0}

        def boundary(args, **kwargs):
            if args[0] == "/usr/bin/open":
                state["launched"] = True
                return subprocess.CompletedProcess(args, 0, "", "")
            if "quit()" in args[-1]:
                state["running"] = False
                return subprocess.CompletedProcess(args, 0, "", "")
            if state["launched"]:
                state["ready_probes"] += 1
                state["running"] = state["ready_probes"] >= 2
            return subprocess.CompletedProcess(args, 0, str(state["running"]).lower(), "")

        with tempfile.TemporaryDirectory() as directory, patch.dict(
                "os.environ", {"PERSONAL_CONTEXT_DATA_DIR": directory}), patch(
                "personal_context.mac_app_lifecycle.subprocess.run", side_effect=boundary), patch(
                "time.sleep"):
            with collected_app("Notes"):
                self.assertTrue(state["running"], "snapshot would fail with macOS -600")
            self.assertFalse(state["running"])

    def test_failed_launch_never_enters_collection(self):
        def boundary(args, **kwargs):
            if args[0] == "/usr/bin/open":
                return subprocess.CompletedProcess(args, 1, "", "synthetic launch failure")
            return subprocess.CompletedProcess(args, 0, "false", "")

        with tempfile.TemporaryDirectory() as directory, patch.dict(
                "os.environ", {"PERSONAL_CONTEXT_DATA_DIR": directory}), patch(
                "personal_context.mac_app_lifecycle.subprocess.run", side_effect=boundary):
            with self.assertRaisesRegex(RuntimeError, "launch"):
                with collected_app("Contacts"):
                    self.fail("Collection must not start after a failed launch")

    def test_app_that_never_starts_does_not_reach_snapshot(self):
        calls = []

        def boundary(args, **kwargs):
            calls.append(args)
            return subprocess.CompletedProcess(args, 0, "false", "")

        with tempfile.TemporaryDirectory() as directory, patch.dict(
                "os.environ", {"PERSONAL_CONTEXT_DATA_DIR": directory}), patch(
                "personal_context.mac_app_lifecycle.subprocess.run", side_effect=boundary), patch(
                "time.sleep"):
            with self.assertRaisesRegex(RuntimeError, "did not become ready"):
                with collected_app("Notes"):
                    self.fail("Collection must wait for a running app")
        self.assertLess(len(calls), 25, "startup must have a finite retry bound")

    def test_running_app_stays_running_without_launch_or_quit(self):
        def boundary(args, **kwargs):
            self.assertNotEqual(args[0], "/usr/bin/open")
            self.assertNotIn("quit()", args[-1])
            return subprocess.CompletedProcess(args, 0, "true", "")

        with tempfile.TemporaryDirectory() as directory, patch.dict(
                "os.environ", {"PERSONAL_CONTEXT_DATA_DIR": directory}), patch(
                "personal_context.mac_app_lifecycle.subprocess.run", side_effect=boundary):
            with collected_app("Contacts"):
                pass
