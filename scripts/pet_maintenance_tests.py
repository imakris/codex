"""Exercise maintenance promotion using real local Git repositories, without compilers."""

import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import pet_maintenance as maintenance


def git(directory, *args):
    return subprocess.check_output(
        ["git", "-C", str(directory), *args], stderr=subprocess.STDOUT, text=True
    ).strip()


class MaintenanceTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.upstream = self.root / "upstream"
        self.upstream.mkdir()
        git(self.upstream, "init", "-b", "main")
        git(self.upstream, "config", "user.name", "Maintenance test")
        git(self.upstream, "config", "user.email", "maintenance-test@localhost")
        (self.upstream / "layout.txt").write_text("original\n")
        git(self.upstream, "add", ".")
        git(self.upstream, "commit", "-m", "Initial source")
        self.fork = self.root / "fork.git"
        subprocess.run(
            ["git", "clone", "--bare", str(self.upstream), str(self.fork)],
            check=True,
            capture_output=True,
        )
        self.base = git(self.upstream, "rev-parse", "HEAD")
        git(self.fork, "branch", "pet-composer-layout", self.base)
        self.config = {
            "checkout": str(self.root / "checkout"),
            "state_dir": str(self.root / "state"),
            "artifacts_dir": str(self.root / "releases"),
            "fork_url": str(self.fork),
            "upstream_url": str(self.upstream),
        }
        state = self.root / "state"
        state.mkdir()
        self.old_manifest = {
            "commit": self.base,
            "binary": "previous.exe",
            "sha256": "previous",
        }
        maintenance.atomic_json(state / "current.json", self.old_manifest)

    def advance(self, text="upstream change\n"):
        (self.upstream / "layout.txt").write_text(text)
        git(self.upstream, "add", ".")
        git(self.upstream, "commit", "-m", "Upstream change")
        return git(self.upstream, "rev-parse", "HEAD")

    def executable(self, attempt):
        binary = attempt.directory / "built.exe"
        binary.write_bytes(b"verified executable fixture")
        return binary

    def assert_unpublished(self):
        self.assertEqual(git(self.fork, "rev-parse", "pet-composer-layout"), self.base)
        manifest = json.loads((self.root / "state/current.json").read_text())
        self.assertEqual(manifest, self.old_manifest)

    def test_success_publishes_matching_commit_and_unchanged_run_skips_gate(self):
        upstream = self.advance()
        result = maintenance.maintain(self.config, verifier=self.executable)
        manifest = json.loads((self.root / "state/current.json").read_text())
        self.assertEqual(result["phase"], "passed")
        self.assertEqual(
            git(self.fork, "rev-parse", "pet-composer-layout"), manifest["commit"]
        )
        self.assertEqual(manifest["upstream"], upstream)
        self.assertEqual(maintenance.digest(manifest["binary"]), manifest["sha256"])

        def unexpected(_attempt):
            self.fail("unchanged source rebuilt")

        self.assertEqual(
            maintenance.maintain(self.config, verifier=unexpected)["phase"], "unchanged"
        )

    def test_failed_gate_preserves_branch_and_previous_binary(self):
        self.advance()

        def fail(_attempt):
            raise RuntimeError("regression gate failed")

        with self.assertRaisesRegex(RuntimeError, "regression gate failed"):
            maintenance.maintain(self.config, verifier=fail)
        self.assert_unpublished()
        status = json.loads((self.root / "state/status.json").read_text())
        self.assertEqual(status["phase"], "failed")
        self.assertTrue(Path(status["report"]).is_dir())

    def test_merge_conflict_is_archived_without_running_gates(self):
        self.advance("fork change\n")
        git(self.upstream, "push", str(self.fork), "HEAD:pet-composer-layout")
        self.base = git(self.upstream, "rev-parse", "HEAD")
        git(self.upstream, "reset", "--hard", "HEAD~1")
        self.advance("incompatible upstream change\n")

        def unexpected(_attempt):
            self.fail("merge conflict reached build")

        with self.assertRaises(RuntimeError):
            maintenance.maintain(self.config, verifier=unexpected)
        self.assert_unpublished()
        status = json.loads((self.root / "state/status.json").read_text())
        conflict = Path(status["report"]) / "changed-files/layout.txt"
        self.assertIn("<<<<<<<", conflict.read_text())

    def test_external_branch_advance_prevents_promotion(self):
        self.advance()
        external = self.root / "external"
        subprocess.run(
            ["git", "clone", str(self.fork), str(external)],
            check=True,
            capture_output=True,
        )
        git(external, "checkout", "pet-composer-layout")
        git(external, "config", "user.name", "Other editor")
        git(external, "config", "user.email", "other-editor@localhost")

        def advance_during_gate(attempt):
            (external / "external.txt").write_text("another change\n")
            git(external, "add", ".")
            git(external, "commit", "-m", "External branch update")
            git(external, "push", "origin", "pet-composer-layout")
            return self.executable(attempt)

        with self.assertRaisesRegex(RuntimeError, "advanced during verification"):
            maintenance.maintain(self.config, verifier=advance_during_gate)
        self.assertEqual(
            json.loads((self.root / "state/current.json").read_text()),
            self.old_manifest,
        )
        self.assertEqual(
            git(self.fork, "rev-parse", "pet-composer-layout"),
            git(external, "rev-parse", "HEAD"),
        )

    def test_missing_regression_selection_stops_before_execution(self):
        directory = self.root / "selection"
        directory.mkdir()
        config = self.config | {
            "target_dir": str(self.root / "target"),
            "path_prefix": [str(self.root / "tools")],
            "vcvars": str(self.root / "vcvars.bat"),
            "queued_build": "queued-build",
            "vswhere": "vswhere",
        }
        attempt = maintenance.Attempt(config, directory)

        def command(args, **_kwargs):
            if args[0] == "vswhere":
                return 0, '[{"isComplete": true, "isLaunchable": true}]'
            if str(args[-1]).endswith("list.cmd"):
                (directory / "tests.json").write_text('{"rust-suites": {}}')
            self.assertFalse(str(args[-1]).endswith("test.cmd"))
            return 0, ""

        with patch.object(attempt, "command", side_effect=command):
            with self.assertRaisesRegex(
                RuntimeError, "Required regression tests are missing"
            ):
                maintenance.verify_candidate(attempt)

    def test_lock_excludes_a_second_runner(self):
        with maintenance.exclusive_lock(self.root / "state/run.lock"):
            with self.assertRaises(OSError):
                maintenance.maintain(self.config, verifier=self.executable)

    def test_failed_pointer_swap_keeps_previous_executable(self):
        upstream = self.advance()
        original = maintenance.atomic_json

        def fail_current(path, value):
            if Path(path).name == "current.json":
                raise OSError("publication denied")
            original(path, value)

        with patch.object(maintenance, "atomic_json", side_effect=fail_current):
            with self.assertRaisesRegex(OSError, "publication denied"):
                maintenance.maintain(self.config, verifier=self.executable)
        self.assertEqual(
            json.loads((self.root / "state/current.json").read_text()),
            self.old_manifest,
        )
        self.assertEqual(git(self.fork, "rev-parse", "pet-composer-layout"), upstream)
        self.assertEqual(
            maintenance.maintain(self.config, verifier=self.executable)["phase"],
            "passed",
        )


if __name__ == "__main__":
    unittest.main()
