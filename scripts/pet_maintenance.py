"""Merge upstream into the pet fork and publish only a verified Windows executable."""

import argparse
import contextlib
import datetime
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import uuid


REQUIRED_TESTS = [
    "app::owned_transcript::tests::owned_transcript_uses_full_width_above_the_pet",
    "app::tests::resize_reflow_preserves_transcript_width_when_pet_is_enabled",
    "chatwidget::tests::status_and_layout::added_history_with_pet_uses_full_terminal_width",
    "chatwidget::tests::status_and_layout::ambient_pet_preserves_history_wrap_width",
    "chatwidget::tests::status_and_layout::ambient_pet_preserves_stream_width_and_reserves_composer_text_width",
    "chatwidget::tests::status_and_layout::ambient_pet_fits_beside_short_and_multiline_composers",
    "chatwidget::tests::status_and_layout::ambient_pet_hides_when_the_composer_viewport_cannot_fit_it",
    "chatwidget::tests::status_and_layout::ambient_pet_hides_notification_text_overlay",
    "pets::ambient::tests::ambient_sprite_only_clears_its_own_rows",
    "pets::tests::clearing_before_frame_clips_old_sprite_after_terminal_resize",
    "tui::tests::synchronized_frame_keeps_clear_text_and_sprite_in_one_update",
    "tui::tests::synchronized_frame_finishes_after_draw_error",
]
TEST_FILTER = " | ".join(f"test(={name})" for name in REQUIRED_TESTS)


def atomic_json(path, value):
    path = Path(path)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def digest(path):
    with Path(path).open("rb") as source:
        return hashlib.file_digest(source, "sha256").hexdigest()


@contextlib.contextmanager
def exclusive_lock(path):
    with Path(path).open("a+b") as lock:
        lock.seek(0)
        if os.name == "nt":
            import msvcrt

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


class Attempt:
    def __init__(self, config, directory):
        self.config = config
        self.directory = Path(directory)
        self.checkout = Path(config["checkout"])
        self.status = {
            "phase": "starting",
            "started": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        }

    def record(self, phase, **values):
        self.status.update(phase=phase, **values)
        atomic_json(self.directory / "status.json", self.status)
        atomic_json(
            Path(self.config["state_dir"]) / "status.json",
            self.status | {"report": str(self.directory)},
        )

    def command(self, args, *, cwd=None, check=True, output=None):
        with (self.directory / "commands.log").open("a", encoding="utf-8") as log:
            log.write(json.dumps([str(arg) for arg in args]) + "\n")
            log.flush()
            with contextlib.ExitStack() as stack:
                destination = (
                    stack.enter_context(Path(output).open("wb"))
                    if output
                    else subprocess.PIPE
                )
                result = subprocess.run(
                    [str(arg) for arg in args],
                    cwd=cwd,
                    stdout=destination,
                    stderr=subprocess.STDOUT,
                    check=False,
                    creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
                    env=os.environ | {"GIT_TERMINAL_PROMPT": "0"},
                )
            text = (
                result.stdout.decode("utf-8", errors="replace") if result.stdout else ""
            )
            log.write(text)
            log.write(f"exit={result.returncode}\n")
        if check and result.returncode:
            raise RuntimeError(
                f"Command failed ({result.returncode}): {args[0]}; see {output or self.directory / 'commands.log'}"
            )
        return result.returncode, text.strip()

    def git(self, *args, check=True):
        return self.command(["git", "-C", self.checkout, *args], check=check)

    def archive_checkout(self):
        if not (self.checkout / ".git").exists():
            return
        _, status = self.git("status", "--porcelain=v1", "--untracked-files=all")
        (self.directory / "checkout-status.txt").write_text(status, encoding="utf-8")
        _, patch = self.git("diff", "--binary", "HEAD")
        (self.directory / "checkout.patch").write_text(patch, encoding="utf-8")
        _, changed = self.git("diff", "--name-only", "HEAD")
        _, untracked = self.git("ls-files", "--others", "--exclude-standard")
        for relative in set(changed.splitlines() + untracked.splitlines()):
            source = self.checkout / relative
            if source.is_file():
                destination = self.directory / "changed-files" / relative
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, destination)


def batch_quote(value):
    text = str(value)
    if any(char in text for char in '\r\n"%!&|<>^'):
        raise ValueError(f"Unsupported batch path or argument: {text!r}")
    return '"' + text + '"'


def verify_candidate(attempt):
    """Every compiler invocation stays inside one bounded queued-build admission."""
    config = attempt.config
    slots = int(config.get("slots", 4))
    if not 1 <= slots <= 8:
        raise ValueError("slots must be between 1 and 8")
    directory = attempt.directory
    target = Path(config["target_dir"])
    prefix = ";".join(config["path_prefix"])
    for value in [prefix, target, config["vcvars"], attempt.checkout, directory]:
        batch_quote(value)
    vswhere = config.get(
        "vswhere",
        r"C:\Program Files (x86)\Microsoft Visual Studio\Installer\vswhere.exe",
    )
    _, installations = attempt.command(
        [
            vswhere,
            "-latest",
            "-products",
            "*",
            "-version",
            "[18.0,19.0)",
            "-format",
            "json",
            "-utf8",
        ]
    )
    installation = next(iter(json.loads(installations.lstrip("\ufeff"))), {})
    if not installation.get("isComplete") or not installation.get("isLaunchable"):
        raise RuntimeError("Visual Studio 2026 is incomplete or unlaunchable")
    reboot = {}
    if os.name == "nt":
        import winreg

        for label, key, value in [
            (
                "cbs",
                r"SOFTWARE\Microsoft\Windows\CurrentVersion\Component Based Servicing\RebootPending",
                None,
            ),
            (
                "windows_update",
                r"SOFTWARE\Microsoft\Windows\CurrentVersion\WindowsUpdate\Auto Update\RebootRequired",
                None,
            ),
            (
                "pending_rename",
                r"SYSTEM\CurrentControlSet\Control\Session Manager",
                "PendingFileRenameOperations",
            ),
        ]:
            try:
                with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, key) as handle:
                    reboot[label] = (
                        bool(winreg.QueryValueEx(handle, value)[0]) if value else True
                    )
            except FileNotFoundError:
                reboot[label] = False
        atomic_json(
            directory / "toolchain.json",
            {"installation": installation, "reboot": reboot},
        )
    attempt.command(
        [config["queued_build"], "--check-xenia"],
        check=False,
        output=directory / "xenia.log",
    )
    setup = [
        "@echo off",
        "setlocal",
        f"call {batch_quote(config['vcvars'])} x64 -vcvars_ver=14.51 > {batch_quote(directory / 'vcvars.log')} 2>&1",
        "if errorlevel 1 exit /b %errorlevel%",
        f'set "PATH={prefix};%PATH%"',
        f'set "CARGO_TARGET_DIR={target}"',
        f'set "CARGO_BUILD_JOBS={slots}"',
        'set "CARGO_PROFILE_DEV_DEBUG=0"',
        'set "CARGO_PROFILE_TEST_DEBUG=0"',
        'set "CARGO_INCREMENTAL=0"',
        'set "CLICOLOR=0"',
        'set "INSTA_UPDATE=no"',
        f"cd /d {batch_quote(attempt.checkout / 'codex-rs')}",
    ]
    for name, command in [
        ("build", f"cargo build -p codex-cli --bin codex --locked -j{slots}"),
        (
            "list",
            f'cargo nextest list -p codex-tui --locked --build-jobs={slots} --message-format json -E "{TEST_FILTER}"',
        ),
        (
            "test",
            f'just test -p codex-tui --locked --build-jobs={slots} --test-threads={slots} --no-tests=fail -E "{TEST_FILTER}"',
        ),
    ]:
        # Redirect Cargo's JSON stream separately from environment setup and build diagnostics.
        output = directory / ("tests.json" if name == "list" else f"{name}.log")
        redirect = (
            f"> {batch_quote(output)} 2> {batch_quote(directory / 'list.stderr.log')}"
            if name == "list"
            else f"> {batch_quote(output)} 2>&1"
        )
        batch = directory / f"{name}.cmd"
        batch.write_text(
            "\n".join(setup + [command + " " + redirect, "exit /b %errorlevel%", ""]),
            encoding="utf-8",
        )
        attempt.record(name)
        attempt.command(
            [
                config["queued_build"],
                "--slots",
                str(slots),
                "--",
                "cmd.exe",
                "/d",
                "/c",
                batch,
            ],
            output=directory / f"{name}-queue.log",
        )
        if name == "list":
            listing = json.loads(output.read_text(encoding="utf-8"))
            selected = {
                name
                for suite in listing["rust-suites"].values()
                for name, case in suite["testcases"].items()
                if not case["ignored"] and case["filter-match"]["status"] == "matches"
            }
            missing = set(REQUIRED_TESTS) - selected
            if missing:
                raise RuntimeError(
                    f"Required regression tests are missing or excluded: {sorted(missing)}"
                )
            attempt.record("tests-selected", selected_tests=sorted(selected))
    executable = target / "debug" / "codex.exe"
    attempt.command([executable, "--version"], output=directory / "version.log")
    return executable


def maintain(config, *, verifier=verify_candidate):
    state = Path(config["state_dir"])
    state.mkdir(parents=True, exist_ok=True)
    with exclusive_lock(state / "run.lock"):
        identifier = (
            datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
            + "-"
            + uuid.uuid4().hex[:8]
        )
        directory = state / "runs" / identifier
        directory.mkdir(parents=True)
        attempt = Attempt(config, directory)
        try:
            checkout = attempt.checkout
            marker = checkout.parent / (checkout.name + ".pet-maintenance-owned")
            if not checkout.exists():
                checkout.parent.mkdir(parents=True, exist_ok=True)
                attempt.command(["git", "clone", config["fork_url"], checkout])
                marker.write_text(str(checkout.resolve()), encoding="utf-8")
            if not marker.exists() or marker.read_text(encoding="utf-8") != str(
                checkout.resolve()
            ):
                raise RuntimeError(
                    "Checkout ownership marker missing or mismatched; refusing to reset it"
                )
            if attempt.git("remote", "get-url", "origin")[1] != config["fork_url"]:
                raise RuntimeError("Checkout origin differs from configured fork")
            attempt.archive_checkout()
            attempt.git("reset", "--hard", "HEAD")
            attempt.git("clean", "-fd")
            branch = config.get("branch", "pet-composer-layout")
            attempt.git("check-ref-format", "--branch", branch)
            attempt.record("fetch")
            attempt.git(
                "fetch", "origin", f"refs/heads/{branch}:refs/remotes/origin/{branch}"
            )
            attempt.git(
                "fetch",
                config["upstream_url"],
                "refs/heads/main:refs/remotes/pet-upstream/main",
            )
            base = attempt.git("rev-parse", f"refs/remotes/origin/{branch}")[1]
            upstream = attempt.git("rev-parse", "refs/remotes/pet-upstream/main")[1]
            attempt.record("merge", base=base, upstream=upstream)
            current_path = state / "current.json"
            current = (
                json.loads(current_path.read_text(encoding="utf-8"))
                if current_path.exists()
                else {}
            )
            if current.get("commit") == base and current.get("upstream") == upstream:
                executable = Path(current["binary"])
                if executable.is_file() and digest(executable) == current["sha256"]:
                    attempt.record("unchanged", commit=base)
                    return attempt.status
            attempt.git("checkout", "--detach", base)
            attempt.git(
                "-c",
                "user.name=Codex pet maintenance",
                "-c",
                "user.email=codex-pet-maintenance@localhost",
                "merge",
                "--no-edit",
                upstream,
            )
            candidate = attempt.git("rev-parse", "HEAD")[1]
            attempt.git(
                "update-ref", f"refs/pet-maintenance/attempts/{identifier}", candidate
            )
            attempt.record("verify", commit=candidate)
            executable = Path(verifier(attempt))
            if attempt.git("status", "--porcelain=v1", "--untracked-files=all")[1]:
                raise RuntimeError(
                    "Build or tests changed the candidate checkout; refusing promotion"
                )
            if attempt.git("rev-parse", "HEAD")[1] != candidate:
                raise RuntimeError("Candidate HEAD changed during verification")
            release = Path(config["artifacts_dir"]) / candidate / identifier
            if release.exists():
                raise RuntimeError(
                    f"Immutable release already exists without matching publication: {release}"
                )
            release.mkdir(parents=True)
            published_binary = release / "codex.exe"
            shutil.copy2(executable, published_binary)
            manifest = {
                "commit": candidate,
                "upstream": upstream,
                "base": base,
                "binary": str(published_binary.resolve()),
                "sha256": digest(published_binary),
                "verified_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                "report": str(directory),
            }
            atomic_json(release / "manifest.json", manifest)
            attempt.record("publish")
            remote = attempt.git("ls-remote", "origin", f"refs/heads/{branch}")[
                1
            ].split()
            if not remote or remote[0] != base:
                raise RuntimeError(
                    "Fork branch advanced during verification; refusing promotion"
                )
            attempt.git("push", "origin", f"{candidate}:refs/heads/{branch}")
            # Remote promotion happens before local publication. A failed pointer swap
            # keeps the previous executable available; the tested remote commit is safe.
            atomic_json(current_path, manifest)
            attempt.record("passed", **manifest)
            return attempt.status
        except Exception as error:
            with contextlib.suppress(Exception):
                attempt.archive_checkout()
            attempt.record("failed", error=str(error))
            raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument("action", choices=["run", "status", "launch"])
    parser.add_argument("arguments", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    config = json.loads(args.config.read_text(encoding="utf-8-sig"))
    state = Path(config["state_dir"])
    if args.action == "run":
        maintain(config)
    elif args.action == "status":
        print((state / "status.json").read_text(encoding="utf-8"))
    else:
        manifest = json.loads((state / "current.json").read_text(encoding="utf-8"))
        arguments = (
            args.arguments[1:] if args.arguments[:1] == ["--"] else args.arguments
        )
        return subprocess.call([manifest["binary"], *arguments])
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as error:
        if sys.stderr is not None:
            print(str(error), file=sys.stderr)
        sys.exit(1)
