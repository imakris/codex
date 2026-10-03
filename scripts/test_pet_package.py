#!/usr/bin/env python3
"""Regression checks for the standalone fork npm package."""

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))

import pet_package
from codex_package.layout import build_package_dir
from codex_package.targets import PackageInputs, PACKAGE_VARIANTS, TARGET_SPECS


class PetPackageTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)

    def canonical_package(self, target="x86_64-pc-windows-msvc"):
        spec = TARGET_SPECS[target]
        executable = self.root / "fixture.exe"
        executable.write_bytes(b"native fixture")
        executable.chmod(0o755)
        package = self.root / "canonical"
        package.mkdir()
        build_package_dir(
            package, "1.2.3", PACKAGE_VARIANTS["codex"], spec,
            PackageInputs(
                entrypoint_bin=executable,
                code_mode_host_bin=executable,
                rg_bin=executable,
                zsh_bin=executable if spec.is_linux else None,
                bwrap_bin=executable if spec.is_linux else None,
                codex_command_runner_bin=executable if spec.is_windows else None,
                codex_windows_sandbox_setup_bin=executable if spec.is_windows else None,
            ),
        )
        return package

    def test_staging_preserves_complete_payload_and_isolates_npm_identity(self):
        target = "x86_64-pc-windows-msvc"
        canonical = self.canonical_package(target)
        stage = self.root / "stage"
        pet_package.stage_package(canonical, stage, target, "1.2.3")
        package = json.loads((stage / "package.json").read_text())
        self.assertEqual(
            {key: package[key] for key in ("name", "version", "bin", "os", "cpu", "files")},
            {"name": "@imakris/codex-pet", "version": "1.2.3",
             "bin": {"codex-pet": "bin/codex.js"}, "os": ["win32"], "cpu": ["x64"],
             "files": ["bin", "vendor", "LICENSE", "NOTICE"]},
        )
        self.assertNotIn("optionalDependencies", package)
        expected = {p.relative_to(canonical): p.read_bytes() for p in canonical.rglob("*") if p.is_file()}
        vendor = stage / "vendor" / target
        actual = {p.relative_to(vendor): p.read_bytes() for p in vendor.rglob("*") if p.is_file()}
        self.assertEqual(actual, expected)
        self.assertEqual((stage / "LICENSE").read_bytes(), (pet_package.REPO_ROOT / "LICENSE").read_bytes())

    def test_missing_native_helper_rejects_package(self):
        canonical = self.canonical_package()
        (canonical / "codex-resources/codex-command-runner.exe").unlink()
        with self.assertRaisesRegex(RuntimeError, "Missing package file"):
            pet_package.stage_package(canonical, self.root / "stage", "x86_64-pc-windows-msvc", "1.2.3")

    def test_wrong_target_rejects_package(self):
        with self.assertRaisesRegex(RuntimeError, "Invalid package metadata field 'target'"):
            pet_package.stage_package(
                self.canonical_package(), self.root / "stage", "x86_64-unknown-linux-musl", "1.2.3"
            )

    def test_wrong_version_rejects_package(self):
        with self.assertRaisesRegex(RuntimeError, "version does not match"):
            pet_package.stage_package(
                self.canonical_package(), self.root / "stage", "x86_64-pc-windows-msvc", "1.2.4"
            )

    def test_launcher_drift_requires_review(self):
        with self.assertRaisesRegex(RuntimeError, "Upstream launcher changed"):
            pet_package.fork_launcher("// changed upstream launcher\n")

    @unittest.skipUnless(shutil.which("node"), "Node.js required")
    def test_launcher_ignores_neighboring_official_package(self):
        target = "x86_64-pc-windows-msvc" if sys.platform == "win32" else "x86_64-unknown-linux-musl"
        stage = self.root / "node_modules/@imakris/codex-pet"
        pet_package.stage_package(self.canonical_package(), stage, "x86_64-pc-windows-msvc", "1.2.3")
        shutil.rmtree(stage / "vendor")
        official = self.root / "node_modules/@openai" / f"codex-{pet_package.TARGETS[target]}-x64"
        official.mkdir(parents=True)
        (official / "package.json").write_text('{"name":"unrelated-official-fixture"}')
        result = subprocess.run(
            ["node", str(stage / "bin/codex.js"), "--version"], capture_output=True, text=True
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Missing bundled Codex executable", result.stderr)
        self.assertIn("github.com/imakris/codex/releases/latest/download", result.stderr)
        self.assertNotIn("Missing optional dependency", result.stderr)

    @unittest.skipUnless(shutil.which("node"), "Node.js required")
    def test_launcher_uses_bundled_binary_without_official_update_flags(self):
        target = "x86_64-pc-windows-msvc" if sys.platform == "win32" else "x86_64-unknown-linux-musl"
        stage = self.root / "stage"
        pet_package.stage_package(self.canonical_package(target), stage, target, "1.2.3")
        launcher = stage / "bin/codex.js"
        source = launcher.read_text(encoding="utf-8")
        source = source.replace(
            'import { spawn } from "node:child_process";',
            '''function spawn(binary, args, options) {
  console.log(JSON.stringify({binary, env: options.env}));
  return {on(event, callback) {
    if (event === "exit") setImmediate(() => callback(0, null));
  }};
}''',
        )
        launcher.write_text(source, encoding="utf-8")
        env = os.environ.copy()
        flags = [f"CODEX_MANAGED_BY_{manager}" for manager in ("NPM", "BUN", "PNPM", "VITE_PLUS")]
        env.update({flag: "1" for flag in flags})
        result = subprocess.check_output(["node", str(launcher)], env=env, text=True)
        actual = json.loads(result)
        executable = f"codex{TARGET_SPECS[target].exe_suffix}"
        self.assertEqual(Path(actual["binary"]), stage / "vendor" / target / "bin" / executable)
        self.assertEqual(Path(actual["env"]["CODEX_MANAGED_PACKAGE_ROOT"]), stage)
        self.assertTrue(all(flag not in actual["env"] for flag in flags))

    @unittest.skipUnless(shutil.which("npm.cmd" if sys.platform == "win32" else "npm"), "npm required")
    def test_npm_tarball_contains_native_helpers_and_license(self):
        target = "x86_64-pc-windows-msvc"
        stage = self.root / "stage"
        pet_package.stage_package(self.canonical_package(), stage, target, "1.2.3")
        tarball = pet_package.pack_package(stage, self.root / "codex-pet-win32-x64.tgz")
        with tarfile.open(tarball) as archive:
            names = set(archive.getnames())
            self.assertTrue({
                "package/LICENSE", "package/NOTICE", "package/bin/codex.js",
                f"package/vendor/{target}/codex-resources/codex-command-runner.exe",
                f"package/vendor/{target}/codex-resources/codex-windows-sandbox-setup.exe",
                f"package/vendor/{target}/bin/codex-code-mode-host.exe",
                f"package/vendor/{target}/codex-path/rg.exe",
            }.issubset(names))


if __name__ == "__main__":
    unittest.main()
