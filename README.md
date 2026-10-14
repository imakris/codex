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
runs on branch pushes and manual dispatch. It integrates current upstream changes
and publishes verified Windows x64 and Linux x64 packages. GitHub can delay
scheduled starts; conflicts or failed checks leave the previous release available.

The native executable reports the latest official stable Codex release version;
the npm package adds a `pet` build suffix. The fork branch is rewritten after
upstream updates, so existing source clones need the
[resynchronization steps](PET_MAINTENANCE.md#source-clones).

This happens on GitHub without your computer running. Installed copies do not
update themselves; rerun the installation command to update. See
[installation and maintenance details](PET_MAINTENANCE.md) for the download-only
Python installer, release checks, and troubleshooting.

---

## Upstream Codex

The following overview and links are from upstream Codex. Use the installation
commands above for this fork.

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

To install official OpenAI Codex, see the
[upstream installation instructions](https://github.com/openai/codex#installing-and-running-codex-cli).

### Using Codex with your ChatGPT plan

Run `codex` and select **Sign in with ChatGPT**. We recommend signing into your ChatGPT account to use Codex as part of your Plus, Pro, Business, Edu, or Enterprise plan. [Learn more about what's included in your ChatGPT plan](https://help.openai.com/en/articles/11369540-codex-in-chatgpt).

You can also use Codex with an API key, but this requires [additional setup](https://developers.openai.com/codex/auth#sign-in-with-an-api-key).

## Docs

- [**Codex Documentation**](https://developers.openai.com/codex)
- [**Contributing**](./docs/contributing.md)
- [**Installing & building**](./docs/install.md)
- [**Open source fund**](./docs/open-source-fund.md)

This repository is licensed under the [Apache-2.0 License](LICENSE).
