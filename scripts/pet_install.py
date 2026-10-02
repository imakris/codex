#!/usr/bin/env python3
"""Install published Codex pet binaries without a compiler (Python 3.10+)."""

import argparse
import contextlib
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import platform
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
from datetime import datetime, timezone
from urllib.request import Request, urlopen


REPOSITORY = "imakris/codex"


@contextlib.contextmanager
def installation_lock(path):
    with path.open("a+b") as lock:
        if os.name == "nt":
            import msvcrt
            lock.seek(0)
            if not lock.read(1):
                lock.write(b"0")
                lock.flush()
            lock.seek(0)
            msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        try:
            yield
        finally:
            lock.seek(0)
            if os.name == "nt":
                msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(lock, fcntl.LOCK_UN)


def atomic_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, name = tempfile.mkstemp(dir=path.parent, prefix=path.name + ".")
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(value, stream, indent=2)
            stream.write("\n")
        os.replace(name, path)
    finally:
        with contextlib.suppress(FileNotFoundError):
            os.unlink(name)


def download(url, destination):
    request = Request(url, headers={"User-Agent": "codex-pet-installer"})
    with urlopen(request, timeout=120) as response, destination.open("wb") as stream:
        shutil.copyfileobj(response, stream)


def digest(path):
    result = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            result.update(chunk)
    return result.hexdigest()


def verify(path, checksums):
    expected = checksums.get(path.name)
    if expected is None or digest(path) != expected:
        raise ValueError(f"SHA256 verification failed: {path.name}")


def unpack(archive, destination):
    # npm packages contain regular files/directories. Reject links and paths
    # escaping package/ before writing anything from a downloaded archive.
    with tarfile.open(archive, "r:gz") as package:
        members = package.getmembers()
        for member in members:
            parts = PurePosixPath(member.name).parts
            if (not parts or parts[0] != "package" or ".." in parts
                    or "\\" in member.name or ":" in member.name
                    or not (member.isfile() or member.isdir())):
                raise ValueError(f"Unsafe package member: {member.name}")
        for member in members:
            relative = PurePosixPath(member.name).parts[1:]
            path = destination.joinpath(*relative)
            if member.isdir():
                path.mkdir(parents=True, exist_ok=True)
                continue
            path.parent.mkdir(parents=True, exist_ok=True)
            with package.extractfile(member) as source, path.open("wb") as output:
                shutil.copyfileobj(source, output)
            path.chmod(member.mode & 0o777)


def install(install_dir, state_dir):
    system = {"Windows": "win32", "Linux": "linux"}.get(platform.system())
    if system is None or platform.machine().lower() not in ("amd64", "x86_64"):
        raise ValueError("Published Codex pet packages support Windows/Linux x64.")
    install_dir.mkdir(parents=True, exist_ok=True)
    state_dir.mkdir(parents=True, exist_ok=True)
    with installation_lock(state_dir / "install.lock"):
        with tempfile.TemporaryDirectory(dir=install_dir, prefix="download-") as temp:
            staging = Path(temp)
            download(f"https://api.github.com/repos/{REPOSITORY}/releases/latest",
                     staging / "github.json")
            release = json.loads((staging / "github.json").read_text())
            tag = release["tag_name"]
            if (not re.fullmatch(r"pet-v[0-9A-Za-z.+-]+", tag)
                    or release["draft"] or release["prerelease"]):
                raise ValueError("Latest release is not a published Codex pet release.")
            urls = {asset["name"]: asset["browser_download_url"]
                    for asset in release["assets"]}
            for name in ("SHA256SUMS", "release.json"):
                download(urls[name], staging / name)
            checksums = {}
            for line in (staging / "SHA256SUMS").read_text().splitlines():
                checksum, name = line.split(maxsplit=1)
                checksums[name.lstrip("*")] = checksum
            verify(staging / "release.json", checksums)
            metadata = json.loads((staging / "release.json").read_text())
            expected_tag = f"pet-v{metadata['version']}-{metadata['commit']}"
            if metadata["repository"] != REPOSITORY or tag != expected_tag:
                raise ValueError("Release metadata does not match its GitHub release.")
            asset = next(item for item in metadata["assets"]
                         if item["os"] == system and item["arch"] == "x64")
            name = asset["name"]
            expected_name = f"codex-pet-{system}-x64.tgz"
            if name != expected_name:
                raise ValueError(f"Unexpected package name: {name}")
            current_path = state_dir / "current.json"
            if current_path.exists():
                current = json.loads(current_path.read_text(encoding="utf-8"))
                if (current.get("release") == tag and Path(current["binary"]).is_file()
                        and digest(Path(current["binary"])) == current["sha256"]):
                    return current
            archive = staging / name
            download(urls[name], archive)
            verify(archive, checksums)
            extracted = staging / "package"
            unpack(archive, extracted)
            relative = PurePosixPath(asset["binary"])
            if (relative.is_absolute() or ".." in relative.parts
                    or "\\" in str(relative) or ":" in str(relative)):
                raise ValueError("Invalid binary path in release metadata.")
            binary = extracted.joinpath(*relative.parts)
            vendor = binary.parent.parent
            helpers = (["bin/codex-code-mode-host.exe", "codex-path/rg.exe",
                        "codex-resources/codex-command-runner.exe",
                        "codex-resources/codex-windows-sandbox-setup.exe"]
                       if system == "win32" else
                       ["bin/codex-code-mode-host", "codex-path/rg", "codex-resources/bwrap"])
            for helper in helpers:
                if not (vendor / helper).is_file():
                    raise ValueError(f"Package is missing required helper: {helper}")
            flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
            result = subprocess.run([str(binary), "--version"], check=True,
                                    capture_output=True, text=True, timeout=60,
                                    creationflags=flags)
            if "codex" not in result.stdout.lower():
                raise ValueError("Downloaded binary did not identify itself as Codex.")
            subprocess.run([str(binary), "--help"], check=True, capture_output=True,
                           timeout=60, creationflags=flags)
            # A unique immutable directory also permits updating while Codex runs.
            published = Path(tempfile.mkdtemp(prefix=tag + "-", dir=install_dir))
            published.rmdir()
            extracted.rename(published)
            binary = published.joinpath(*relative.parts)
            manifest = {
                "release": tag, "version": metadata["version"],
                "commit": metadata["commit"], "upstream": metadata["upstream"],
                "binary": str(binary.resolve()), "sha256": digest(binary),
                "verified_at": datetime.now(timezone.utc).isoformat(),
            }
            atomic_json(current_path, manifest)
            return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--install-dir", type=Path,
                        default=Path.home() / ".local/share/codex-pet/releases")
    parser.add_argument("--state-dir", type=Path,
                        default=Path.home() / ".local/state/codex-pet")
    parser.add_argument("action", choices=["install", "update", "launch", "status"])
    parser.add_argument("arguments", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    if args.action in ("install", "update"):
        status_path = args.state_dir / "status.json"
        try:
            manifest = install(args.install_dir.resolve(), args.state_dir.resolve())
        except Exception as error:
            atomic_json(status_path, {"phase": "failed", "error": str(error),
                                      "checked_at": datetime.now(timezone.utc).isoformat()})
            raise
        atomic_json(status_path, {"phase": "passed", "release": manifest["release"],
                                  "checked_at": datetime.now(timezone.utc).isoformat()})
        print(json.dumps(manifest, indent=2))
    else:
        manifest = json.loads((args.state_dir / "current.json").read_text(encoding="utf-8"))
        if args.action == "status":
            status_path = args.state_dir / "status.json"
            status = json.loads(status_path.read_text()) if status_path.exists() else None
            print(json.dumps({"current": manifest, "last_update": status}, indent=2))
        else:
            arguments = args.arguments[1:] if args.arguments[:1] == ["--"] else args.arguments
            return subprocess.call([manifest["binary"], *arguments])
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as error:
        if sys.stderr is not None:
            print(f"Codex pet install failed: {error}", file=sys.stderr)
        sys.exit(1)
