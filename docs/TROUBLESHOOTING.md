# Troubleshooting

## The agent does not find the skill

Install for the agent you use: `python3 trurl.py install --agent claude-code`, `python3 trurl.py install --agent codex`, or `python3 trurl.py install --agent pi`. The installer reports the directory. Start a new session and invoke Trurl with `/trurl` in Claude Code, `$trurl` in Codex, or `/skill:trurl` in Pi. [Host setup](HOSTS.md)

Run `python3 trurl.py doctor --agent claude-code --root /absolute/path/to/private-trurl`, substituting your chosen agent. Check the destination against its active home/profile, then check duplicate or disabled copies. The Codex default is `~/.agents/skills/trurl`; an explicit `CODEX_HOME` retains its legacy location. See [install options](HOSTS.md#install-options-and-diagnostics) for other overrides.

In Pi, run `/reload` after installation during an active session. The default is `~/.pi/agent/skills/trurl`, with `PI_CODING_AGENT_DIR` selecting a different agent directory. Pi also discovers `~/.agents/skills`; a second Trurl copy there can cause a name collision. Inspect startup diagnostics and keep the intended copy current. Project `.pi/skills` loads after project trust. Skill metadata in the catalog does not prove that the full instructions were read; use `/skill:trurl` to load them explicitly.

`doctor` checks local installation and the Python runtime. A CLI found on `PATH` is not proof of authentication, skill discovery, or a completed host workflow. Inspect `hosts[].errors` and `hosts[].cli.available`; missing CLIs are informational and do not fail an otherwise valid local installation. Exit 1 indicates failed local checks, while exit 2 indicates invalid arguments or paths. You can tell a file-capable agent to read the installed `SKILL.md` directly and supply your root, but that fallback does not establish that native discovery worked.

## An install already exists

The installer stops rather than replacing it. To see whether the installed copy is behind, run `python3 trurl.py doctor --agent claude-code` from the downloaded repository, substituting your agent, and read `hosts[].update.current`. To replace it with the repository's version, run `python3 trurl.py install --agent claude-code --update`. The previous copy moves to a temporary folder named in the output, so the host never sees two copies; start a new session afterwards. Personal state belongs in the curation workspace's `model/`, outside the installed skill. An update does not touch it; preserve that workspace when switching hosts.

## I changed agents and cannot find my model

Run `python3 trurl.py root` to see the model location. New local models default to `~/Trurl/model`. To reuse an existing model elsewhere, run `python3 trurl.py use --root /absolute/path/to/curation-root`. The registered path works across sessions that share the same filesystem and user configuration.

Explicit paths, `TRURL_ROOT`, legacy `CURATION_ROOT` and an existing workspace model take precedence. A desktop app may need access to the folder. A remote session may require a shared mount. If a registered model is missing, restore its access or correct its registered path before starting another profile.

## There is no private model

Run `python3 trurl.py root` to check the selected location, then `python3 trurl.py init` to create a new local model. The default is `~/Trurl/model`. For a custom persistent folder, pass `init --root /absolute/path` and remember it with `use --root /absolute/path`. Initialization refuses to overwrite existing model files.

## The model is inside a session folder

Copy it to a persistent folder before relying on it across sessions. Follow the [migration steps](../skills/trurl/references/onboarding.md#choose-a-lasting-home) to preserve evidence and any scheduled job's root.

Claude Code Desktop supports both project folders and disposable worktrees. Its worktrees can lose uncommitted files during cleanup. Add the persistent Trurl folder to sessions that need access. A statement about deleting session data must refer to the actual host and folder involved. [Claude Code Desktop](https://code.claude.com/docs/en/desktop#keep-uncommitted-changes-when-a-session-is-archived)

## The agent cannot access prior conversations

Start with the current request and any preferences the person explicitly supplies. Record that history was unavailable. A useful first selection can be made with an incomplete model; do not fill it with guessed expertise or preferences.

## I allowed memory, but the host has none available

Memory permission and access are different. The skill uses only relevant memory that the host actually exposes within the chosen scope. Record the source as unavailable or partial and continue from supplied anchors. Switching hosts does not merge memory stores or authorize a new source. The skill does not turn on host memory or search old chats as a substitute. A category plus one curiosity, enjoyed item, or goal is enough to begin; a category alone supports starter picks with personalization left uncertain.

## The agent asks the same onboarding questions again

It should reuse the categories, anchors, and source choices already supplied. A model with useful observations can continue even without the newer `onboarding` fields. Ask only for information needed by the current request, and honor an earlier explicit source authorization. A declined or unanswered memory offer is not a reason to stop curation or repeatedly ask for access.

## The host cannot research or verify links

State that verification is unavailable and describe the resulting limit. Ask for accessible source material when needed, or use a research-capable host. Do not claim titles, durations, availability, or factual claims were verified when they were not. The Python demo remains usable because it demonstrates weighting with synthetic data.

Pi's default coding tools do not include a research service. Trurl does not install one. Use accessible supplied material or a research capability you have configured and authorized; the same applies to personal memory services and scheduling. See [Pi setup](HOSTS.md#pi).

## Recommendations repeat

Check that the agent read the intended workspace's `model/recommendations.jsonl`. Match canonical work identity as well as URLs: tracking parameters and alternate video links do not create a new work. Record delivered items once. Preserve history when changing hosts or updating the skill.

## The weights are not changing

Personal mode, fixed-weight instructions, and focused requests intentionally suppress unrequested rotation. Repeated broad on-demand rotation starts with two preceding broad requests. To inspect an explicitly broad weekly plan without changing any model:

```sh
python3 trurl.py weights --profile examples/profile.example.json --context weekly --scope broad --seed 42
```

The CLI's phrase matching is limited. A host should interpret the request and pass the appropriate mode and scope. Its seed supports replay of the weighting plan with the same inputs and implementation; it does not guarantee identical web search results.

## Sunday delivery did not run

Check the host scheduler for an active Trurl job and compare its local slot and timezone with the profile. A new profile can still be pending if first-time setup has yet to disclose the Sunday slot and opt-out. The profile shows weekly delivery as enabled after the host confirms the job. If you opted out or already had a profile, say “Send me a Sunday edition every week” to request a schedule. Use an on-demand edition on hosts without scheduling.

## Local checks pass, but a host run fails

Run `python3 trurl.py doctor --agent claude-code --root /absolute/path/to/private-trurl`, substituting your chosen agent. A successful local installation does not prove that the agent is authenticated, discovers the skill or has the required file and research tools. See [what the diagnostics establish](HOSTS.md#what-the-diagnostics-establish).

Inspect the agent's native error, active profile, permissions and provider login. Confirm that its session can read the installed `SKILL.md` and access the stated private curation root. Include the host version and a synthetic reproduction when reporting a problem; keep personal state and authentication files out of the report.

## Surprise has no suitable candidates

Connected surprise requires a concrete interest, request detail, or feedback anchor and a minimum relevance score. If context is absent, provide one interest or current goal. If only unrelated or weak-fit items are available, the host should report a shortfall instead of padding the set. Use explicit `wildcard` only when unrelated exploration is wanted. The connection and numerical fit are editorial judgments, not guaranteed enjoyment.

## The graph has no paths for an interest

The initial graph is empty, and existing models need not have a graph file. Keep using the profile and current request while researching sourced relationships. A direct new interest is valid without a route back to older ones. Check `graph_node_id` or an exact normalized topic/alias match; do not guess an entity mapping. Hypothesis, retracted, insufficiently sourced, and below-threshold edges are intentionally unavailable to default retrieval.

## I want something outside the existing profile

Say “Try a new area” to request a bounded open selection. It can offer an independent probe even with no existing graph anchor, with personal fit left unknown. Ordinary connected surprise keeps its fit requirements. The open policy preserves your baseline weights, and neither request enrolls you in Sunday delivery. A provisional old distant allocation does not count as a standing open opt-in.

## A relationship or inference is wrong

Correct the content assertion and the personal observation separately. Retract the edge and invalidate its dependent routes; remove private contents and caches when forgetting is requested. A path never established a preference in the first place. Keep item-specific corrections narrow, and preserve the difference between familiarity, curiosity, enjoyment, and expertise.
