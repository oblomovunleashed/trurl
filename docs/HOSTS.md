# Use Trurl across hosts

Choose **Claude Code, Codex or Pi**. The same standalone skill folder and Python runtime support each agent independently; install it for the one you use. Their discovery, tools, permissions, and model behavior can differ.

The Codex and Claude Code conventions below were checked against official documentation on **4 November 2026**, and Pi's on **9 November 2026**. Live behavior must be checked separately for the host version and configuration you use.

## Prepare your chosen agent's workspace

Run commands from the downloaded repository. Python 3.9 or later is required. The helpers are tested on macOS and Linux; Windows is untested. New local models default to `~/Trurl/model`. Check the resolved root before initializing it.

```sh
python3 trurl.py root
python3 trurl.py init
```

Skip `init` when continuing an existing model. It refuses to overwrite existing state. The profile, graph, recommendation history, feedback and batch traces live in that root's `model/` folder.

To reuse a model in another persistent folder, remember its root.

```sh
python3 trurl.py use --root "/absolute/path/to/private-trurl"
```

New sessions with access to the same user configuration can resolve that location. Explicit roots, `TRURL_ROOT`, legacy `CURATION_ROOT` and an existing workspace model take precedence. Use `root` to inspect the effective choice. Registration stores a path in `~/.config/trurl/config.json`, or beneath an absolute `XDG_CONFIG_HOME`.

Desktop apps may need the persistent folder added to the session. Remote or sandboxed hosts need access to a persistent shared folder. Confirm the host's actual filesystem before promising reuse across sessions or devices. See [persistent storage and migration](../skills/trurl/references/onboarding.md#choose-a-lasting-home).

The diagnostics below find the model location the same way. Pass `--root /absolute/path` only to require a model at a specific path.

## Codex

```sh
python3 trurl.py install --agent codex
python3 trurl.py doctor --agent codex
```

The default installation is `~/.agents/skills/trurl`. Start a new Codex session with access to the curation root, then send:

```text
$trurl Set up my profile. Books and podcasts; I am curious about how maps shape perception.
Use only what I share here.
```

Add “Use /absolute/path as my curation root.” when your model lives somewhere other than the default; the same applies to the other agents. Codex documents user skills under `~/.agents/skills`, explicit `$` mentions, and `/skills` discovery. See [official OpenAI documentation](https://learn.chatgpt.com/docs/build-skills). If an installed skill does not appear, restart Codex and check that local skills are enabled.

## Claude Code

```sh
python3 trurl.py install --agent claude-code
python3 trurl.py doctor --agent claude-code
```

The default installation is `~/.claude/skills/trurl`. Start a new local Claude Code session with access to the root, then send:

```text
/trurl Set up my profile. Books and podcasts; I am curious about how maps shape perception.
Use only what I share here.
```

Claude Code documents personal skill folders and `/skill-name` invocation. Local personal skills are not automatically available in its cloud or Cowork sessions. See [Claude Code skills documentation](https://code.claude.com/docs/en/skills). The Python `doctor` command above is this package's diagnostic, separate from Claude Code's own `/doctor`.

## Pi

Install and configure the Pi CLI separately using its [official getting-started guide](https://github.com/earendil-works/pi/tree/main/packages/coding-agent#getting-started), then install Trurl:

```sh
python3 trurl.py install --agent pi
python3 trurl.py doctor --agent pi
```

The default installation is `~/.pi/agent/skills/trurl`. Start Pi with access to your curation root, or run `/reload` in an existing session after installation, then send:

```text
/skill:trurl Set up my profile. Books and podcasts; I am curious about how maps shape perception.
Use only what I share here. One-off only for now.
```

Pi advertises each skill's name, description and path at startup and loads its full instructions when needed. `/skill:trurl` explicitly loads Trurl; automatic matching may miss it. The bundled Python scripts and references resolve relative to the loaded skill directory. See the [official skills documentation](https://github.com/earendil-works/pi/blob/main/packages/coding-agent/docs/skills.md).

For a project installation, pass `--destination /absolute/path/to/project/.pi/skills/trurl` and start Pi in that project. Project `.pi` configuration requires project trust. `PI_CODING_AGENT_DIR` changes the user agent directory, with skills beneath its `skills/` folder. Pi also discovers `~/.agents/skills` and project `.agents/skills`; avoid maintaining conflicting copies with the same `trurl` name. Check startup collision warnings and the loaded path when you also use Codex. See [Pi configuration](https://github.com/earendil-works/pi/blob/main/packages/coding-agent/docs/configuration.md).

Pi's default coding tools include `read`, `bash`, `edit` and `write`. They can access the model and run Python when local permissions allow. Research services, personal memory services and a scheduler are separate capabilities: use only extensions, MCP tools or source material actually available and authorized. Trurl installs none of those services. Without research access, report verification limits; without scheduling, use on-demand editions. Stored Pi sessions do not authorize past-chat review. [Pi tool settings](https://github.com/earendil-works/pi/blob/main/packages/coding-agent/docs/settings.md#tools)

## OpenAI dots and Claude Duet

- **OpenAI dots.** Install Trurl for Codex on a computer connected to your dot. Ask the dot to start or continue a local Codex task using Trurl and give it the path to your private curation workspace. Keep the computer online and the ChatGPT app open. [Connect a computer to your dot](https://learn.chatgpt.com/docs/dots/computers-and-apps)
- **Claude Duet (research preview).** With code execution enabled, upload a ZIP of the `skills/trurl/` folder under **Customize → Skills** and enable it in the Claude account you use for Duet. Duet picks up enabled skills from that account. For a taste model that carries across requests, Duet needs Python and a private workspace it can read and update from the cloud. [Upload a Claude skill](https://support.claude.com/en/articles/12512180-use-skills-in-claude) · [Claude Duet access and limits](https://support.claude.com/en/articles/17631495-get-started-with-claude-duet)

## Install options and diagnostics

For normal use, select one agent. `--destination /absolute/skill-directory` can select its exact skill directory. Developers can use `install --agent all` to check all three installation targets; that option is not needed for personal use and cannot be combined with `--destination`.

To replace an existing installation with the version in this repository, add `--update`, for example `python3 trurl.py install --agent claude-code --update`. An installation that already matches is left alone. Otherwise the previous copy moves to a temporary folder named in the output, so the host never sees two copies, and your taste model is untouched. Start a new session afterwards.

Native home overrides are honored when set: `CODEX_HOME` uses its legacy `skills/` location, `CLAUDE_CONFIG_DIR` selects the Claude configuration directory, and `PI_CODING_AGENT_DIR` selects Pi's agent directory. See the [Claude environment reference](https://code.claude.com/docs/en/env-vars) and [Pi configuration](https://github.com/earendil-works/pi/blob/main/packages/coding-agent/docs/configuration.md) for their native settings. Use the installer's reported path and match the environment used to launch the host. `--home /temporary/home` deliberately selects isolated defaults for testing and ignores these native overrides.

Run `python3 trurl.py doctor --agent claude-code`, substituting your chosen agent, for a JSON report. It checks the install path, bundled files, CLI availability, and an installed Python runtime smoke test. `hosts[].update.current` says whether the installed copy matches the repository you ran the command from. The root check reports the model location a session would resolve and records file presence without reading profile contents; a model need not exist before first use. Pass `--root` to require a model at a specific path. CLI availability means a command was found on `PATH`; it proves neither authentication nor skill discovery. A missing CLI is informational, so inspect `hosts[].cli.available` even when `ok` is true. `full_host_tested: false` is intentional: `doctor` does not launch an agent, browse, import memory, or create a schedule.

## Keep source choices and schedules explicit

The model carries observations and their provenance. If you move it to another agent, that does not transfer access to the previous agent's memory or transcripts. Record actual source availability, keep agent memory separate from past-chat review, and use supplied anchors when a source is declined or unavailable.

The host must provide file and Python execution access for the helper commands. Verified recommendations also need suitable research tools or supplied source material. If verification is unavailable, the agent must describe that limit. Installing the skill does not add a browser, account connection, credentials, or a research backend.

On hosts with a scheduler, first-time profile setup includes a Sunday edition by default. The setup message shows the local delivery slot and how to opt out. Each scheduled edition runs as an ordinary request and uses your agent's usage allowance. If you continue with that setup, the host schedules the edition unless you decline. You can say “Turn off Sunday delivery” at any time.

The host checks existing jobs first and marks weekly delivery active after confirming the native schedule. Existing profiles and one-off requests use the delivery setting already in place. If your host lacks scheduling, you can request an edition on demand. When you move a model to another host, check where its Sunday job runs before creating another.

## What the diagnostics establish

The installer copies a standalone skill for your chosen agent. `doctor` checks the folder, references and Python helpers locally. These diagnostics do not establish authentication, native skill discovery, research access, recommendation quality or successful scheduling.

When diagnosing an agent session, keep its version, active profile, permissions and native error messages with your report. Use a synthetic model for reproductions and keep personal state and credentials private.
