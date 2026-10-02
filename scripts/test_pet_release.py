"""Failure and source identity checks for hosted pet releases."""

import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import pet_release


class ReleaseTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)
        self.metadata = {"base": "a" * 40, "commit": "b" * 40, "upstream": "c" * 40,
                         "version": "0.0.0-pet.1.1", "repository": "imakris/codex",
                         "tag": "pet-v0.0.0-pet.1.1-" + "b" * 40, "assets": pet_release.ASSETS}
        (self.directory / "candidate.json").write_text(json.dumps(self.metadata))

    def test_prepare_build_decision_for_release_cadence(self):
        candidate = self.metadata["base"]
        matching = {"tag_name": "pet-v0.0.0-pet.1.1-" + candidate}
        different = {"tag_name": self.metadata["tag"]}
        cases = [
            ("schedule", matching, "true"),
            ("push", matching, "false"),
            ("workflow_dispatch", matching, "false"),
            ("schedule", different, "true"),
            ("push", different, "true"),
            ("workflow_dispatch", different, "true"),
            ("schedule", None, "true"),
            ("push", None, "true"),
            ("workflow_dispatch", None, "true"),
        ]
        for index, (event, latest, expected_build) in enumerate(cases):
            with self.subTest(event=event, latest=latest):
                output = self.directory / f"output-{index}.txt"
                environment = {
                    "GITHUB_EVENT_NAME": event,
                    "GITHUB_OUTPUT": str(output),
                    "GITHUB_RUN_NUMBER": "5",
                    "GITHUB_RUN_ATTEMPT": "1",
                    "GITHUB_REPOSITORY": "imakris/codex",
                }
                commands = [None, candidate, None, None, self.metadata["upstream"],
                            None, None, None, candidate]
                with patch.dict(os.environ, environment), \
                        patch.object(pet_release, "run", side_effect=commands), \
                        patch.object(pet_release, "api", return_value=latest):
                    pet_release.prepare(self.directory / f"candidate-{index}")
                actual = dict(line.split("=", 1) for line in output.read_text().splitlines())
                self.assertEqual(actual, {
                    "base": candidate,
                    "commit": candidate,
                    "version": "0.0.0-pet.5.1",
                    "build": expected_build,
                })

    def test_missing_platform_prevents_any_publication(self):
        with patch.object(pet_release, "run") as run:
            with self.assertRaisesRegex(RuntimeError, "Missing release asset"):
                pet_release.publish(self.directory, self.directory)
        run.assert_not_called()

    def test_concurrent_branch_change_prevents_push(self):
        for asset in pet_release.ASSETS:
            (self.directory / asset["name"]).write_bytes(b"verified fixture")
        with patch.object(pet_release, "run", side_effect=[None, "d" * 40]) as run:
            with self.assertRaisesRegex(RuntimeError, "Fork changed"):
                pet_release.publish(self.directory, self.directory)
        self.assertEqual([call.args[:2] for call in run.call_args_list],
                         [("git", "fetch"), ("git", "rev-parse")])

    def test_release_remains_draft_until_assets_uploaded(self):
        for asset in pet_release.ASSETS:
            (self.directory / asset["name"]).write_bytes(b"verified fixture")
        with patch.object(pet_release, "run", side_effect=[None, self.metadata["base"], None, None, None]) as run:
            pet_release.publish(self.directory, self.directory)
        commands = [call.args for call in run.call_args_list]
        self.assertEqual(commands[2][:3], ("git", "push", "origin"))
        self.assertIn("--draft", commands[3])
        self.assertEqual(commands[4][-2:], ("--draft=false", "--latest"))
        self.assertNotIn("--force", commands[2])
        sums = (self.directory / "SHA256SUMS").read_text()
        self.assertIn("  release.json\n", sums)
        self.assertIn("  pet_install.py\n", sums)

    def test_missing_required_test_stops_execution(self):
        listing = json.dumps({"rust-suites": {}})
        with patch.object(pet_release, "run", return_value=listing) as run:
            with self.assertRaisesRegex(RuntimeError, "Missing required pet"):
                pet_release.verify_tests("x86_64-pc-windows-msvc")
        self.assertEqual(run.call_count, 1)

    def test_candidate_restore_verifies_identity(self):
        with patch.object(pet_release, "run", side_effect=[None, None, "d" * 40]):
            with self.assertRaisesRegex(RuntimeError, "does not match"):
                pet_release.restore(self.directory)


if __name__ == "__main__":
    unittest.main()
