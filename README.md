# Codex CLI pet layout fork

This is an unofficial fork of [OpenAI Codex CLI](https://github.com/openai/codex)
that keeps transcript history and streaming responses at the full terminal width
when a pet is enabled. The pet occupies space beside the typing area (composer)
and its footer, instead of reserving columns alongside the entire conversation.
SIXEL sprite cleanup, text drawing, and replacement sprite output share one
synchronized update to avoid displaying a cleared sprite between frames.

The layout changes adapt [makoto-soracom's work](https://github.com/makoto-soracom/codex/tree/makoto/pet-flicker-25004)
to current upstream Codex. See [pet layout details and attribution](PET_LAYOUT.md).

## Install or update this fork

Install Node.js and npm, then run the command for your platform. These packages
include prebuilt binaries: no compiler, local build, or npm account is needed.

**Windows x64:**

```powershell
npm install -g https://github.com/imakris/codex/releases/latest/download/codex-pet-win32-x64.tgz
```

**Linux x64:**

```sh
npm install -g https://github.com/imakris/codex/releases/latest/download/codex-pet-linux-x64.tgz
```

Start the fork with:

```sh
codex-pet
```

Repeat the same installation command to update to the latest published release.
The separate `codex-pet` command can coexist with official `codex`; both use
normal Codex configuration and authentication. Packages are hosted on
[GitHub Releases](https://github.com/imakris/codex/releases/latest), using adapted
upstream npm packaging infrastructure. They are not published to npmjs.com.

## Automatic synchronization and releases

The [GitHub Actions workflow](https://github.com/imakris/codex/actions/workflows/pet-release.yml)
is scheduled daily at **07:17 Berlin time** (`Europe/Berlin`) year-round, and also
runs on branch pushes and manual dispatch. It merges upstream changes, builds
Windows x64 and Linux x64 packages, runs twelve selected pet regression tests on
each platform, and checks a fresh npm installation before publishing a release.
Scheduled runs attempt a new release even when source is unchanged. Push and
manual runs skip builds when a matching release exists. Conflicts or failed
checks leave the previous release available. GitHub can delay scheduled starts;
publication follows successful verification.

This happens on GitHub without your computer running. Installed copies do not
update themselves; rerun the installation command to update. See
[installation and maintenance details](PET_MAINTENANCE.md) for the download-only
Python installer, release checks, and troubleshooting.

---

## Original upstream README

The original README follows in full. Its installation commands install official
OpenAI Codex; use the commands above to install this fork.

<p align="center"><strong>Codex CLI</strong> is a coding agent from OpenAI that runs locally on your computer.
<p align="center">
  <img src="https://github.com/openai/codex/blob/main/.github/codex-cli-splash.png" alt="Codex CLI splash" width="80%" />
</p>
</br>
If you want Codex in your code editor (VS Code, Cursor, Windsurf), <a href="https://developers.openai.com/codex/ide">install in your IDE.</a>
</br>If you want the desktop app experience, run <code>codex app</code> or visit <a href="https://chatgpt.com/codex?app-landing-page=true">the Codex App page</a>.
</br>If you are looking for the <em>cloud-based agent</em> from OpenAI, <strong>Codex Web</strong>, go to <a href="https://chatgpt.com/codex">chatgpt.com/codex</a>.</p>

---

## Quickstart

### Installing and running Codex CLI

Run the following on Mac or Linux to install Codex CLI:

```shell
curl -fsSL https://chatgpt.com/codex/install.sh | sh
```

Run the following on Windows to install Codex CLI:

```shell
powershell -ExecutionPolicy ByPass -c "irm https://chatgpt.com/codex/install.ps1 | iex"
```

The standalone installers download from `https://releases.openai.com/codex` by default and fall back to GitHub Releases if a metadata or asset download is unavailable. To force GitHub Releases, set `CODEX_INSTALLER_USE_RELEASES_OPENAI_COM` to `false` (`0` and `no` are also accepted):

```shell
curl -fsSL https://chatgpt.com/codex/install.sh | CODEX_INSTALLER_USE_RELEASES_OPENAI_COM=false sh
```

```powershell
$env:CODEX_INSTALLER_USE_RELEASES_OPENAI_COM='false'; irm https://chatgpt.com/codex/install.ps1 | iex
```

Codex CLI can also be installed via the following package managers:

```shell
# Install using npm
npm install -g @openai/codex
```

```shell
# Install using Homebrew
brew install --cask codex
```

Then simply run `codex` to get started.

<details>
<summary>You can also go to the <a href="https://github.com/openai/codex/releases/latest">latest GitHub Release</a> and download the appropriate binary for your platform.</summary>

Each GitHub Release contains many executables, but in practice, you likely want one of these:

- macOS
  - Apple Silicon/arm64: `codex-aarch64-apple-darwin.tar.gz`
  - x86_64 (older Mac hardware): `codex-x86_64-apple-darwin.tar.gz`
- Linux
  - x86_64: `codex-x86_64-unknown-linux-musl.tar.gz`
  - arm64: `codex-aarch64-unknown-linux-musl.tar.gz`

Each archive contains a single entry with the platform baked into the name (e.g., `codex-x86_64-unknown-linux-musl`), so you likely want to rename it to `codex` after extracting it.

</details>

### Using Codex with your ChatGPT plan

Run `codex` and select **Sign in with ChatGPT**. We recommend signing into your ChatGPT account to use Codex as part of your Plus, Pro, Business, Edu, or Enterprise plan. [Learn more about what's included in your ChatGPT plan](https://help.openai.com/en/articles/11369540-codex-in-chatgpt).

You can also use Codex with an API key, but this requires [additional setup](https://developers.openai.com/codex/auth#sign-in-with-an-api-key).

## Docs

- [**Codex Documentation**](https://developers.openai.com/codex)
- [**Contributing**](./docs/contributing.md)
- [**Installing & building**](./docs/install.md)
- [**Open source fund**](./docs/open-source-fund.md)

This repository is licensed under the [Apache-2.0 License](LICENSE).
