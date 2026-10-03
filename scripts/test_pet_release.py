"""Failure and source identity checks for hosted pet releases."""

import json
import os
from pathlib import Path
import subprocess
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
                tree = "e" * 40
                commands = [None, candidate, None, None, self.metadata["upstream"],
                            None, None, None, tree, self.metadata["upstream"], tree, None]
                with patch.dict(os.environ, environment), \
                        patch.object(pet_release, "run", side_effect=commands), \
                        patch.object(pet_release, "api", return_value=latest):
                    pet_release.prepare(self.directory / f"candidate-{index}")
                actual = dict(line.split("=", 1) for line in output.read_text().splitlines())
                expected = {
                    "base": candidate,
                    "commit": candidate,
                    "version": "0.0.0-pet.5.1",
                    "build": expected_build,
                }
                if event == "push" and latest == matching:
                    expected = {"build": "false"}
                self.assertEqual(actual, expected)

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
        self.assertEqual(commands[2], (
            "git", "push", f"--force-with-lease=refs/heads/{pet_release.BRANCH}:{self.metadata['base']}",
            "origin", f"{self.metadata['commit']}:refs/heads/{pet_release.BRANCH}",
        ))
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


class GitFixture:
    def __init__(self, test):
        temporary = tempfile.TemporaryDirectory()
        test.addCleanup(temporary.cleanup)
        self.directory = Path(temporary.name)
        self.upstream = self.directory / "upstream"
        self.fork = self.directory / "fork"
        self.runner = self.directory / "runner"
        self.attempt = 0
        self.upstream.mkdir()
        self.git(self.upstream, "init", "--initial-branch=main")
        self.identity(self.upstream)
        self.commit(self.upstream, "upstream.txt", "initial upstream\n", "Initial upstream")
        self.commit(self.upstream, "shared.txt", "initial shared content\n", "Shared upstream file")
        self.initial = self.git(self.upstream, "rev-parse", "HEAD")
        self.git(self.directory, "clone", self.upstream, self.fork)
        self.identity(self.fork)
        self.git(self.fork, "checkout", "-b", pet_release.BRANCH)
        self.commit(self.fork, "pet.txt", "published fork change\n", "Published fork change")
        self.published = self.git(self.fork, "rev-parse", "HEAD")
        self.git(self.fork, "config", "receive.denyCurrentBranch", "updateInstead")
        self.git(self.directory, "clone", "--branch", pet_release.BRANCH, self.fork, self.runner)
        self.git(self.runner, "config", f"url.{self.upstream.as_posix()}.insteadOf",
                 "https://github.com/openai/codex.git")

    def git(self, repository, *args):
        return subprocess.run(["git", *map(str, args)], cwd=repository, check=True,
                              text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE).stdout.strip()

    def identity(self, repository):
        self.git(repository, "config", "user.name", "Pet release fixture")
        self.git(repository, "config", "user.email", "pet-release@example.com")

    def commit(self, repository, name, contents, message):
        (repository / name).write_text(contents)
        self.git(repository, "add", name)
        self.git(repository, "commit", "-m", message)
        return self.git(repository, "rev-parse", "HEAD")

    def run_in(self, repository, before_push=None, commands=None):
        original_run = pet_release.run

        def routed_run(*args, **kwargs):
            if commands is not None:
                commands.append(args)
            if args[0] == "gh":
                return None
            if args[:2] == ("git", "push") and before_push is not None:
                before_push()
            return original_run(*args, cwd=repository, **kwargs)

        return routed_run

    def prepare(self, event="schedule", latest=None):
        self.attempt += 1
        self.candidate = self.directory / f"candidate-{self.attempt}"
        output = self.directory / f"output-{self.attempt}.txt"
        environment = {
            "GITHUB_EVENT_NAME": event,
            "GITHUB_OUTPUT": str(output),
            "GITHUB_RUN_NUMBER": str(self.attempt),
            "GITHUB_RUN_ATTEMPT": "1",
            "GITHUB_REPOSITORY": "imakris/codex",
        }
        with patch.dict(os.environ, environment), \
                patch.object(pet_release, "run", side_effect=self.run_in(self.runner)) as run, \
                patch.object(pet_release, "api", return_value=latest):
            pet_release.prepare(self.candidate)
        actual = dict(line.split("=", 1) for line in output.read_text().splitlines())
        metadata_path = self.candidate / "candidate.json"
        metadata = json.loads(metadata_path.read_text()) if metadata_path.exists() else None
        return metadata, actual, [call.args for call in run.call_args_list]

    def promote(self, metadata):
        self.git(self.runner, "push", f"--force-with-lease=refs/heads/{pet_release.BRANCH}:{metadata['base']}",
                 "origin", f"{metadata['commit']}:refs/heads/{pet_release.BRANCH}")

    def assets(self):
        directory = self.directory / "assets"
        directory.mkdir()
        for asset in pet_release.ASSETS:
            (directory / asset["name"]).write_bytes(b"verified fixture")
        return directory


class PreparationGitTests(unittest.TestCase):
    def assert_compact(self, fixture, metadata):
        self.assertEqual(fixture.git(fixture.runner, "rev-parse", metadata["commit"] + "^@"),
                         metadata["upstream"])
        self.assertEqual(fixture.git(fixture.runner, "rev-list", "--count",
                                    f"{metadata['upstream']}..{metadata['commit']}"), "1")

    def test_advanced_upstream_preserves_trigger_admission(self):
        cases = [
            ("push", "matching", "published", "false"),
            ("workflow_dispatch", "matching", "published", "true"),
            ("schedule", "matching", "published", "true"),
            ("push", "matching", "human", "true"),
            ("push", "missing", "published", "true"),
            ("push", "older", "published", "true"),
        ]
        for event, release, tip, expected_build in cases:
            with self.subTest(event=event, release=release, tip=tip):
                fixture = GitFixture(self)
                if tip == "human":
                    fixture.commit(fixture.fork, "human.txt", "new human change\n", "New human change")
                base = fixture.git(fixture.fork, "rev-parse", "HEAD")
                advanced = fixture.commit(fixture.upstream, "upstream.txt", "advanced upstream\n",
                                          "Advance upstream after publication")
                latest = None if release == "missing" else {
                    "tag_name": "pet-v0.0.0-pet.1.1-" + (fixture.initial if release == "older" else fixture.published)
                }
                metadata, actual, commands = fixture.prepare(event, latest)
                self.assertEqual(actual["build"], expected_build)
                if expected_build == "false":
                    self.assertEqual(fixture.git(fixture.runner, "rev-parse", "HEAD"), base)
                    self.assertEqual(commands, [
                        ("git", "fetch", "origin", pet_release.BRANCH),
                        ("git", "rev-parse", "FETCH_HEAD"),
                    ])
                else:
                    self.assertEqual(metadata["base"], base)
                    self.assertEqual(metadata["upstream"], advanced)
                    self.assertEqual(metadata["commit"], fixture.git(fixture.runner, "rev-parse", "HEAD"))
                    self.assert_compact(fixture, metadata)
                    self.assertEqual((fixture.runner / "pet.txt").read_text(), "published fork change\n")
                    self.assertEqual((fixture.runner / "upstream.txt").read_text(), "advanced upstream\n")
                    if tip == "human":
                        self.assertEqual((fixture.runner / "human.txt").read_text(), "new human change\n")

    def test_compaction_preserves_prior_conflict_resolution_and_human_changes(self):
        fixture = GitFixture(self)
        fixture.commit(fixture.fork, "shared.txt", "fork version\n", "Fork customization")
        upstream = fixture.commit(fixture.upstream, "shared.txt", "upstream version\n", "Upstream customization")
        fixture.git(fixture.fork, "fetch", fixture.upstream, "main")
        with self.assertRaises(subprocess.CalledProcessError):
            fixture.git(fixture.fork, "merge", "--no-edit", upstream)
        fixture.commit(fixture.fork, "shared.txt", "retained conflict resolution\n", "Resolve shared file")
        fixture.commit(fixture.fork, "human.txt", "new human change\n", "New human change")
        advanced = fixture.commit(fixture.upstream, "upstream.txt", "advanced upstream\n", "Advance upstream")
        expected = fixture.directory / "expected"
        fixture.git(fixture.directory, "clone", "--branch", pet_release.BRANCH, fixture.fork, expected)
        fixture.identity(expected)
        fixture.git(expected, "fetch", fixture.upstream, "main")
        fixture.git(expected, "merge", "--no-edit", advanced)
        expected_tree = fixture.git(expected, "rev-parse", "HEAD^{tree}")
        metadata, output, _ = fixture.prepare()
        self.assertEqual(output["build"], "true")
        self.assert_compact(fixture, metadata)
        self.assertEqual(fixture.git(fixture.runner, "rev-parse", "HEAD^{tree}"), expected_tree)
        self.assertEqual((fixture.runner / "shared.txt").read_text(), "retained conflict resolution\n")
        self.assertEqual((fixture.runner / "human.txt").read_text(), "new human change\n")

    def test_repeated_upstream_refresh_keeps_one_fork_commit(self):
        fixture = GitFixture(self)
        latest = None
        for index in (1, 2):
            with self.subTest(refresh=index):
                fixture.commit(fixture.upstream, "upstream.txt", f"upstream version {index}\n", "Advance upstream")
                metadata, _, _ = fixture.prepare(latest=latest)
                self.assert_compact(fixture, metadata)
                fixture.promote(metadata)
                latest = {"tag_name": metadata["tag"]}

    def test_unchanged_compact_source_reuses_identity_and_release_cadence(self):
        fixture = GitFixture(self)
        metadata, _, _ = fixture.prepare()
        fixture.promote(metadata)
        latest = {"tag_name": metadata["tag"]}
        for event, build in (("workflow_dispatch", "false"), ("schedule", "true"), ("push", "false")):
            with self.subTest(event=event):
                repeated, output, _ = fixture.prepare(event, latest)
                self.assertEqual(output["build"], build)
                if repeated is not None:
                    self.assertEqual(repeated["commit"], metadata["commit"])
                    self.assertEqual(repeated["base"], metadata["commit"])
                    self.assertFalse((fixture.candidate / "candidate.bundle").exists())

    def test_non_descendant_candidate_bundle_restores_exact_source(self):
        fixture = GitFixture(self)
        fixture.commit(fixture.fork, "human.txt", "new human change\n", "New human change")
        fixture.commit(fixture.upstream, "upstream.txt", "advanced upstream\n", "Advance upstream")
        metadata, _, _ = fixture.prepare()
        with self.assertRaises(subprocess.CalledProcessError):
            fixture.git(fixture.runner, "merge-base", "--is-ancestor", metadata["base"], metadata["commit"])
        builder = fixture.directory / "builder"
        fixture.git(fixture.directory, "clone", "--branch", pet_release.BRANCH, fixture.fork, builder)
        fixture.git(builder, "bundle", "verify", fixture.candidate / "candidate.bundle")
        with patch.object(pet_release, "run", side_effect=fixture.run_in(builder)):
            pet_release.restore(fixture.candidate)
        self.assertEqual(fixture.git(builder, "rev-parse", "HEAD"), metadata["commit"])
        self.assertEqual(fixture.git(builder, "rev-parse", "HEAD^{tree}"),
                         fixture.git(fixture.runner, "rev-parse", "HEAD^{tree}"))

    def test_guarded_rewrite_promotes_candidate_and_preserves_release_tag(self):
        fixture = GitFixture(self)
        fixture.git(fixture.fork, "tag", "previous-release", fixture.published)
        fixture.commit(fixture.upstream, "upstream.txt", "advanced upstream\n", "Advance upstream")
        metadata, _, _ = fixture.prepare()
        commands = []
        with patch.object(pet_release, "run", side_effect=fixture.run_in(fixture.runner, commands=commands)):
            pet_release.publish(fixture.candidate, fixture.assets())
        self.assertEqual(fixture.git(fixture.fork, "rev-parse", pet_release.BRANCH), metadata["commit"])
        self.assertEqual(fixture.git(fixture.fork, "rev-parse", "previous-release"), fixture.published)
        self.assertEqual([command[:3] for command in commands if command[0] == "gh"],
                         [("gh", "release", "create"), ("gh", "release", "edit")])

    def test_guarded_rewrite_preserves_concurrent_fork_changes(self):
        for stage in ("before-check", "after-check"):
            with self.subTest(stage=stage):
                fixture = GitFixture(self)
                fixture.git(fixture.fork, "tag", "previous-release", fixture.published)
                fixture.commit(fixture.upstream, "upstream.txt", "advanced upstream\n", "Advance upstream")
                fixture.prepare()
                commands = []

                def advance_fork():
                    fixture.commit(fixture.fork, "raced.txt", "concurrent human change\n", "Concurrent human change")

                if stage == "before-check":
                    advance_fork()
                expected_error = RuntimeError if stage == "before-check" else subprocess.CalledProcessError
                before_push = advance_fork if stage == "after-check" else None
                with patch.object(pet_release, "run", side_effect=fixture.run_in(
                        fixture.runner, before_push=before_push, commands=commands)):
                    with self.assertRaises(expected_error):
                        pet_release.publish(fixture.candidate, fixture.assets())
                self.assertEqual((fixture.fork / "raced.txt").read_text(), "concurrent human change\n")
                self.assertEqual(fixture.git(fixture.fork, "rev-parse", "previous-release"), fixture.published)
                self.assertFalse(any(command[0] == "gh" for command in commands))

    def test_new_upstream_conflict_stops_before_candidate_or_publication(self):
        fixture = GitFixture(self)
        fixture.commit(fixture.fork, "shared.txt", "fork version\n", "Fork customization")
        fixture.commit(fixture.upstream, "shared.txt", "upstream version\n", "Upstream customization")
        base = fixture.git(fixture.fork, "rev-parse", pet_release.BRANCH)
        with self.assertRaises(subprocess.CalledProcessError):
            fixture.prepare()
        self.assertFalse((fixture.candidate / "candidate.json").exists())
        self.assertEqual(fixture.git(fixture.fork, "rev-parse", pet_release.BRANCH), base)


if __name__ == "__main__":
    unittest.main()
