# Daily Windows maintenance for the pet fork

`scripts/pet_maintenance.py` follows upstream `main` while preserving the
`pet-composer-layout` patch. It uses the existing Git, Python 3.11+, Rust,
`just`, `cargo-nextest`, Visual Studio 2026/MSVC v145 and `queued-build` tools.
No GitHub Actions workflow, model calls, or outbound issue/comment messages
are involved.

## Run and launch

Install a reviewed copy of the runner outside the checkout, alongside a local
JSON configuration. The installed runner does not replace itself with fetched
code. One dedicated checkout and Cargo target directory retain their paths
across attempts; do not share that target with other checkouts.

Example configuration (adjust the username and tool locations):

```json
{
  "checkout": "C:/Users/imak/.local/share/codex-pet-maintenance/checkout",
  "state_dir": "C:/Users/imak/.local/state/codex-pet-maintenance",
  "target_dir": "C:/Users/imak/.local/share/codex-pet-maintenance/target",
  "artifacts_dir": "C:/Users/imak/.local/share/codex-pet-maintenance/releases",
  "fork_url": "https://github.com/imakris/codex.git",
  "upstream_url": "https://github.com/openai/codex.git",
  "branch": "pet-composer-layout",
  "queued_build": "C:/Users/imak/.local/bin/queued-build.cmd",
  "vcvars": "C:/Program Files/Microsoft Visual Studio/18/Community/VC/Auxiliary/Build/vcvarsall.bat",
  "path_prefix": [
    "C:/Users/imak/.cargo/bin",
    "C:/Users/imak/.local/share/codex-pet-maintenance/tools",
    "C:/Users/imak/AppData/Local/Programs/cmake-4.4.2-windows-x86_64/bin"
  ],
  "slots": 4
}
```

Run `python pet_maintenance.py --config config.json run` for an immediate
attempt, `status` for its result/report directory, or `launch -- <arguments>`
to start the last successfully published executable. The normal user wrapper
should invoke this `launch` action, which reads the atomic `current.json`
pointer. Existing running processes keep their immutable executable.

Register the installed runner with Windows Task Scheduler using `pythonw.exe`,
the `run` action, and an absolute config path: daily at **09:00 local time**,
current user, interactive logon, limited privileges, StartWhenAvailable,
IgnoreNew, no idle condition and no execution timeout. The user must be logged
in; a missed run starts when Windows can run it. The file lock also prevents
scheduled and manual runs from overlapping. Scheduler registration is a local
installation operation, not performed by the runner.

## Verification and publication

Each attempt fetches exact fork/upstream commits, merges into the dedicated
checkout detached from any user branch, and records those revisions. A conflict
stops before compilation. All build/test compilation uses `queued-build`
with the same CPU width as Cargo. Pending reboot indicators are recorded and
are informational; an incomplete/unlaunchable VS 2026 installation fails the gate.

The job builds the native CLI, verifies that every name in `REQUIRED_TESTS`
exists and is selected/nonignored, runs that explicit set through `just test`
with `--no-tests=fail`, and checks the resulting executable's `--version`.
These gates cover full transcript width, streaming and history reflow,
composer height, notification visibility, sprite cleanup, resizing, and
synchronized frame ordering/error release. This is a focused regression gate,
not a claim that the entire upstream test suite passes: the initial Windows
validation reproduced fourteen unrelated failures on untouched upstream.
A renamed or removed required test blocks the update until reviewed.

Only a clean, unchanged candidate can publish. The executable is copied into
an immutable commit/attempt directory with its SHA256 and source manifest.
The remote fork tip must still match the one fetched before verification; the
push is normal, never forced. Only after that push succeeds does an atomic
manifest replacement select the new executable. If that final local write
fails, the remote has a tested commit and the previous executable remains
selected; the next run can retry. Matching source commits and a verified
published executable make subsequent runs a no-op.

Logs, selected test names, source SHAs, status and failure diffs/files live in
`state_dir/runs/<attempt>`. A failed candidate is archived before the next run
resets the automation-owned checkout. The job refuses to reset a checkout
without its matching ownership marker. Previous releases/reports are retained;
manage their disk usage after reviewing which versions you still need.

Offline promotion/rollback fixtures can be run with:
`python -m unittest discover -s scripts -p pet_maintenance_tests.py -v`.
They use real local Git repositories and synthetic executables; installation
must also complete a real native build/test/publication run before scheduling.

## Upstream test compatibility

Upstream commit `8f195c93d7` introduced a blank-session regression test calling
`start_fresh_session_with_summary_hint`, after upstream `449d42ced9` had renamed
that method to `start_fresh_session`. The first real maintenance trial rejected
the candidate at test compilation and preserved the previous publication.
This fork updates that single test call to the renamed method with identical
arguments and assertions; it does not skip the test or restore the removed API.
