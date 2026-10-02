"""Prepare, verify, and publish the pet fork's GitHub-hosted releases."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import urllib.error
import urllib.request

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


BRANCH = "pet-composer-layout"
ROOT = Path(__file__).resolve().parent.parent
ASSETS = [
    {"name": "codex-pet-win32-x64.tgz", "target": "x86_64-pc-windows-msvc",
     "os": "win32", "arch": "x64",
     "binary": "vendor/x86_64-pc-windows-msvc/bin/codex.exe"},
    {"name": "codex-pet-linux-x64.tgz", "target": "x86_64-unknown-linux-musl",
     "os": "linux", "arch": "x64",
     "binary": "vendor/x86_64-unknown-linux-musl/bin/codex"},
]


def run(*args, cwd=ROOT, capture=False):
    print("+", " ".join(map(str, args)), flush=True)
    result = subprocess.run(list(map(str, args)), cwd=cwd, check=True,
                            text=True, stdout=subprocess.PIPE if capture else None)
    return result.stdout.strip() if capture else None


def api(path):
    request = urllib.request.Request(
        f"https://api.github.com/repos/{os.environ['GITHUB_REPOSITORY']}/{path}",
        headers={"Authorization": f"Bearer {os.environ['GH_TOKEN']}",
                 "Accept": "application/vnd.github+json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            return json.load(response)
    except urllib.error.HTTPError as error:
        if error.code == 404:
            return None
        raise


def write_json(path, value):
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


def prepare(directory):
    directory.mkdir(parents=True, exist_ok=True)
    run("git", "fetch", "origin", BRANCH)
    base = run("git", "rev-parse", "FETCH_HEAD", capture=True)
    latest = api("releases/latest")
    # Promotion pushes must not chase upstream changes that arrived during the previous build.
    if (os.environ.get("GITHUB_EVENT_NAME") == "push" and latest is not None
            and latest["tag_name"].endswith("-" + base)):
        with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as output:
            output.write("build=false\n")
        return
    run("git", "checkout", "--detach", base)
    run("git", "fetch", "https://github.com/openai/codex.git", "main")
    upstream = run("git", "rev-parse", "FETCH_HEAD", capture=True)
    run("git", "config", "user.name", "github-actions[bot]")
    run("git", "config", "user.email", "41898282+github-actions[bot]@users.noreply.github.com")
    run("git", "merge", "--no-edit", upstream)
    candidate = run("git", "rev-parse", "HEAD", capture=True)
    # Manual refreshes can skip a candidate that already has a published release.
    unchanged = latest is not None and latest["tag_name"].endswith("-" + candidate)
    skip_build = unchanged and os.environ.get("GITHUB_EVENT_NAME") != "schedule"
    version = f"0.0.0-pet.{os.environ['GITHUB_RUN_NUMBER']}.{os.environ['GITHUB_RUN_ATTEMPT']}"
    metadata = {"base": base, "commit": candidate, "upstream": upstream,
                "version": version, "repository": os.environ["GITHUB_REPOSITORY"],
                "tag": f"pet-v{version}-{candidate}", "assets": ASSETS}
    write_json(directory / "candidate.json", metadata)
    if candidate != base:
        run("git", "branch", "-f", "pet-candidate", candidate)
        run("git", "bundle", "create", directory / "candidate.bundle",
            "refs/heads/pet-candidate", "^" + base)
    with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as output:
        output.write(f"base={base}\ncommit={candidate}\nversion={version}\n")
        output.write(f"build={'false' if skip_build else 'true'}\n")


def restore(directory):
    metadata = json.loads((directory / "candidate.json").read_text())
    if metadata["commit"] != metadata["base"]:
        run("git", "fetch", directory / "candidate.bundle", "refs/heads/pet-candidate")
    run("git", "checkout", "--detach", metadata["commit"])
    actual = run("git", "rev-parse", "HEAD", capture=True)
    if actual != metadata["commit"]:
        raise RuntimeError("The checked-out source does not match the prepared candidate")


def verify_tests(target):
    # Fail when upstream removes/renames a required test, rather than passing zero tests.
    args = ["-p", "codex-tui", "--locked", "--target", target,
            "--build-jobs=4", "--cargo-profile", "dev-small", "-E", TEST_FILTER]
    listing = json.loads(run("cargo", "nextest", "list", *args,
                             "--message-format", "json", cwd=ROOT / "codex-rs", capture=True))
    selected = {name for suite in listing["rust-suites"].values()
                for name, case in suite["testcases"].items()
                if not case["ignored"] and case["filter-match"]["status"] == "matches"}
    missing = set(REQUIRED_TESTS) - selected
    if missing:
        raise RuntimeError(f"Missing required pet regression tests: {sorted(missing)}")
    run("just", "test", *args, "--test-threads=4", "--no-tests=fail")


def publish(directory, assets_dir):
    metadata = json.loads((directory / "candidate.json").read_text())
    for asset in metadata["assets"]:
        path = assets_dir / asset["name"]
        if not path.is_file() or path.stat().st_size == 0:
            raise RuntimeError(f"Missing release asset: {path}")
    release = {key: metadata[key] for key in ("version", "commit", "upstream", "repository", "assets")}
    write_json(assets_dir / "release.json", release)
    paths = [assets_dir / asset["name"] for asset in metadata["assets"]]
    paths.append(assets_dir / "release.json")
    installer = assets_dir / "pet_install.py"
    shutil.copyfile(ROOT / "scripts" / "pet_install.py", installer)
    paths.append(installer)
    checksums = []
    for path in paths:
        with path.open("rb") as stream:
            checksums.append(f"{hashlib.file_digest(stream, 'sha256').hexdigest()}  {path.name}")
    sums = assets_dir / "SHA256SUMS"
    sums.write_text("\n".join(checksums) + "\n", encoding="utf-8")
    run("git", "fetch", "origin", BRANCH)
    actual = run("git", "rev-parse", "FETCH_HEAD", capture=True)
    if actual != metadata["base"]:
        raise RuntimeError("Fork changed during verification; rerun against its new tip")
    # No force push: concurrent divergent updates remain protected by Git itself.
    run("git", "push", "origin", f"{metadata['commit']}:refs/heads/{BRANCH}")
    notes = assets_dir / "notes.md"
    notes.write_text(
        f"Pet layout fork, source `{metadata['commit']}`, upstream `{metadata['upstream']}`.\n\n"
        "Windows x64 and Linux x64 packages passed the pet regression tests and clean npm installation smoke checks.\n\n"
        "Install or update (choose your platform):\n\n"
        "```sh\n"
        f"npm install -g https://github.com/{metadata['repository']}/releases/download/{metadata['tag']}/codex-pet-win32-x64.tgz\n"
        f"npm install -g https://github.com/{metadata['repository']}/releases/download/{metadata['tag']}/codex-pet-linux-x64.tgz\n"
        "codex-pet\n```\n\n"
        "These are fork builds, not OpenAI-signed releases. No compiler or npm registry account is required.\n",
        encoding="utf-8",
    )
    # A draft is invisible to /latest until every asset has been uploaded.
    run("gh", "release", "create", metadata["tag"], *paths, sums,
        "--target", metadata["commit"], "--draft", "--title", f"Codex Pet {metadata['version']}",
        "--notes-file", notes)
    run("gh", "release", "edit", metadata["tag"], "--draft=false", "--latest")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["prepare", "restore", "test", "publish"])
    parser.add_argument("--directory", type=Path, default=ROOT / "candidate")
    parser.add_argument("--assets-dir", type=Path, default=ROOT / "release-assets")
    parser.add_argument("--target")
    args = parser.parse_args()
    if args.command == "prepare":
        prepare(args.directory.resolve())
    elif args.command == "restore":
        restore(args.directory.resolve())
    elif args.command == "test":
        verify_tests(args.target)
    else:
        publish(args.directory.resolve(), args.assets_dir.resolve())


if __name__ == "__main__":
    main()
