"""Published-package installation and failure preservation checks."""

import hashlib
import io
import json
from pathlib import Path
import shutil
import subprocess
import tarfile
import tempfile
import unittest
from unittest.mock import patch

import pet_install


class InstallTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.assets = self.root / "assets"
        self.assets.mkdir()
        self.install_dir = self.root / "installed"
        self.state_dir = self.root / "state"
        self.state_dir.mkdir()
        self.current = self.state_dir / "current.json"
        self.previous = {"binary": "previous.exe", "sha256": "previous"}
        self.current.write_text(json.dumps(self.previous))
        self.binary_path = "vendor/x86_64-pc-windows-msvc/bin/codex.exe"
        self.package_name = "codex-pet-win32-x64.tgz"
        self.make_assets()

    def make_assets(self, member=None, system="win32", version="0.0.0-pet.17"):
        target = "x86_64-pc-windows-msvc" if system == "win32" else "x86_64-unknown-linux-musl"
        self.binary_path = f"vendor/{target}/bin/codex" + (".exe" if system == "win32" else "")
        self.package_name = f"codex-pet-{system}-x64.tgz"
        with tarfile.open(self.assets / self.package_name, "w:gz") as archive:
            entry = tarfile.TarInfo(member or "package/" + self.binary_path)
            content = b"codex fixture binary"
            entry.size = len(content)
            entry.mode = 0o755
            archive.addfile(entry, io.BytesIO(content))
            helpers = (["bin/codex-code-mode-host.exe", "codex-path/rg.exe",
                        "codex-resources/codex-command-runner.exe",
                        "codex-resources/codex-windows-sandbox-setup.exe"] if system == "win32"
                       else ["bin/codex-code-mode-host", "codex-path/rg", "codex-resources/bwrap"])
            for helper in helpers:
                entry = tarfile.TarInfo(f"package/vendor/{target}/" + helper)
                entry.size = len(content)
                archive.addfile(entry, io.BytesIO(content))
        metadata = {
            "version": version, "commit": "candidate", "upstream": "upstream",
            "repository": "imakris/codex",
            "assets": [{"name": self.package_name, "os": system, "arch": "x64",
                        "binary": self.binary_path}],
        }
        (self.assets / "release.json").write_text(json.dumps(metadata))
        names = [self.package_name, "release.json"]
        (self.assets / "SHA256SUMS").write_text("".join(
            f"{hashlib.sha256((self.assets / name).read_bytes()).hexdigest()}  {name}\n"
            for name in names))
        release = {"tag_name": f"pet-v{version}-candidate", "draft": False, "prerelease": False,
                   "assets": [{"name": name, "browser_download_url": name}
                              for name in [*names, "SHA256SUMS"]]}
        (self.assets / "github.json").write_text(json.dumps(release))

    def download(self, url, destination):
        name = "github.json" if url.endswith("/latest") else url
        shutil.copyfile(self.assets / name, destination)

    def run_install(self, smoke_error=None, system="Windows", arguments=None):
        with (patch.object(pet_install, "download", side_effect=self.download),
              patch.object(pet_install.platform, "system", return_value=system),
              patch.object(pet_install.platform, "machine", return_value="AMD64"),
              patch.object(pet_install.subprocess, "run", side_effect=smoke_error,
                           return_value=subprocess.CompletedProcess([], 0, "codex 0.0.0"))):
            if arguments is None:
                return pet_install.install(self.install_dir, self.state_dir)
            output = io.StringIO()
            argv = ["pet_install.py", "--state-dir", str(self.state_dir), *arguments]
            with (patch.object(pet_install.sys, "argv", argv),
                  patch.object(pet_install.sys, "stdout", output),
                  patch.object(Path, "home", return_value=self.root / "home")):
                self.assertEqual(pet_install.main(), 0)
            return json.loads(output.getvalue())

    def test_install_and_repeat_preserve_immutable_binary(self):
        first = self.run_install()
        self.assertEqual(Path(first["binary"]).read_bytes(), b"codex fixture binary")
        self.assertEqual(json.loads(self.current.read_text()), first)
        second = self.run_install(smoke_error=AssertionError("Existing installation was rebuilt"))
        self.assertEqual(first, second)
        self.assertEqual(len(list(self.install_dir.iterdir())), 1)

    def test_explicit_destination_relocates_current_release(self):
        for action in ("install", "update"):
            with self.subTest(action=action):
                first = self.run_install()
                first_binary = Path(first["binary"])
                self.install_dir = self.root / action

                second = self.run_install(arguments=["--install-dir", str(self.install_dir), action])

                second_binary = Path(second["binary"])
                self.assertTrue(second_binary.is_relative_to(self.install_dir))
                self.assertEqual(second_binary.read_bytes(), first_binary.read_bytes())
                self.assertTrue((second_binary.parent.parent / "codex-path/rg.exe").is_file())
                self.assertTrue((first_binary.parent.parent / "codex-path/rg.exe").is_file())
                self.assertEqual(second["release"], first["release"])
                self.assertEqual(json.loads(self.current.read_text()), second)

    def test_equivalent_destination_reuses_current_release(self):
        first = self.run_install()
        equivalent = self.install_dir / ".." / self.install_dir.name

        second = self.run_install(
            smoke_error=AssertionError("Existing installation was rebuilt"),
            arguments=["--install-dir", str(equivalent), "update"])

        self.assertEqual(first, second)
        self.assertEqual(len(list(self.install_dir.iterdir())), 1)

    def test_ancestor_destination_relocates_current_release(self):
        first = self.run_install()

        second = self.run_install(arguments=["--install-dir", str(self.root), "update"])

        self.assertNotEqual(first["binary"], second["binary"])
        installed_path = Path(second["binary"]).relative_to(self.root)
        self.assertEqual(installed_path.parts[1:], Path(self.binary_path).parts)
        self.assertEqual(json.loads(self.current.read_text()), second)

    def test_failed_relocation_preserves_current_install(self):
        first = self.run_install()
        destination = self.root / "relocated"

        with self.assertRaises(subprocess.CalledProcessError):
            self.run_install(
                smoke_error=subprocess.CalledProcessError(1, "codex"),
                arguments=["--install-dir", str(destination), "update"])

        self.assertEqual(json.loads(self.current.read_text()), first)
        self.assertEqual(Path(first["binary"]).read_bytes(), b"codex fixture binary")
        self.assertEqual(list(destination.iterdir()), [])

    def test_omitted_destination_reuses_current_release(self):
        first = self.run_install()

        for action in ("install", "update"):
            with self.subTest(action=action):
                second = self.run_install(
                    smoke_error=AssertionError("Existing installation was rebuilt"),
                    arguments=[action])

                self.assertEqual(first, second)
                self.assertEqual(json.loads(self.current.read_text()), first)
                self.assertEqual(len(list(self.install_dir.iterdir())), 1)

    def test_omitted_destination_installs_new_release_in_default_directory(self):
        default_dir = self.root / "home/.local/share/codex-pet/releases"
        for index, action in enumerate(("install", "update"), start=18):
            with self.subTest(action=action):
                first = self.run_install()
                self.make_assets(version=f"0.0.0-pet.{index}")

                second = self.run_install(arguments=[action])

                self.assertNotEqual(first["release"], second["release"])
                self.assertTrue(Path(second["binary"]).is_relative_to(default_dir))
                self.assertEqual(json.loads(self.current.read_text()), second)
                self.assertEqual(Path(first["binary"]).read_bytes(), b"codex fixture binary")

    def test_bad_checksum_preserves_current_install(self):
        (self.assets / self.package_name).write_bytes(b"damaged download")
        with self.assertRaisesRegex(ValueError, "SHA256"):
            self.run_install()
        self.assertEqual(json.loads(self.current.read_text()), self.previous)

    def test_linux_package_installs_with_helpers(self):
        self.make_assets(system="linux")
        manifest = self.run_install(system="Linux")
        binary = Path(manifest["binary"])
        self.assertEqual(binary.name, "codex")
        self.assertTrue((binary.parent.parent / "codex-resources/bwrap").is_file())

    def test_failed_smoke_preserves_current_install(self):
        with self.assertRaises(subprocess.CalledProcessError):
            self.run_install(subprocess.CalledProcessError(1, "codex"))
        self.assertEqual(json.loads(self.current.read_text()), self.previous)

    def test_archive_escape_rejected_before_writing(self):
        self.make_assets("package/../../escape.exe")
        with self.assertRaisesRegex(ValueError, "Unsafe package member"):
            self.run_install()
        self.assertEqual(json.loads(self.current.read_text()), self.previous)
        self.assertFalse((self.root / "escape.exe").exists())

    def test_manifest_failure_preserves_current_install(self):
        with patch.object(pet_install.os, "replace", side_effect=OSError("in use")):
            with self.assertRaisesRegex(OSError, "in use"):
                self.run_install()
        self.assertEqual(json.loads(self.current.read_text()), self.previous)

    def test_lock_released_after_failure(self):
        with self.assertRaises(subprocess.CalledProcessError):
            self.run_install(subprocess.CalledProcessError(1, "codex"))
        self.assertEqual(self.run_install()["release"], "pet-v0.0.0-pet.17-candidate")


if __name__ == "__main__":
    unittest.main()
