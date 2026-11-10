# Host capabilities

The same skill folder runs on Codex, Claude Code and Pi. The scripts use Python 3.9 or later and the standard library. They do not call a model API, install a host, import its memory, or start a scheduler. A host's skill support and available tools are separate capabilities.

## Activate and locate resources

| Host | Explicit invocation |
| --- | --- |
| Codex | `$trurl` |
| Claude Code | `/trurl` |
| Pi | `/skill:trurl` |

Use the host's resolved path to this skill. Scripts are beneath its `scripts/` directory; supporting instructions are beneath `references/`. Resolve them from the skill's directory, not from the curation workspace or the host's configuration directory. A display name or invocation string is not a filesystem path.

Pi discovers the user installation at `~/.pi/agent/skills/trurl`, or `skills/trurl` beneath `PI_CODING_AGENT_DIR` when set. A project installation can use `.pi/skills/trurl` in a trusted project. Pi advertises skill metadata first and loads the full instructions when needed; `/skill:trurl` explicitly loads them. Use `/reload` after installing or editing during an active session. Pi also discovers Agent Skills directories such as `~/.agents/skills`, so check duplicate-name warnings when another host has installed Trurl there. See Pi's [skills](https://github.com/earendil-works/pi/blob/main/packages/coding-agent/docs/skills.md) and [configuration](https://github.com/earendil-works/pi/blob/main/packages/coding-agent/docs/configuration.md) documentation.

Resolve the private root with `curation.py root`. New local models default to `~/Trurl`, and `curation.py use --root <existing-root>` remembers a custom location in the user's Trurl configuration. Explicit paths, environment overrides and existing workspace models take precedence. Reuse that root across sessions and agents with access to the same filesystem.

Keep the model in persistent storage outside the installed skill and disposable session directories. Desktop applications may need a folder added to the session. Remote and sandboxed hosts may need a persistent shared mount. Verify the actual access and location during onboarding. The root resolver reports paths and file presence, while the host establishes whether that storage survives session cleanup.

## Check the capabilities the request needs

Use the current host's equivalent file, terminal, research, memory, and scheduling tools. Do not assume that a tool name from another host exists.

Pi's default coding tools include `read`, `bash`, `edit` and `write`. Research, personal memory services and scheduling are not provided by this skill or those default tools. Use only capabilities actually configured and authorized, such as available extensions, MCP tools or accessible supplied sources. Stored Pi sessions are not permission to read past chats. With no scheduler, keep on-demand curation available and follow the existing unavailable-scheduling path; do not create a substitute background job. See Pi's [tool settings](https://github.com/earendil-works/pi/blob/main/packages/coding-agent/docs/settings.md#tools).

- **File and terminal access:** read the selected model and run the installed helpers with explicit paths. If Python or execution is unavailable, record the limitation in the private trace when possible and mention it in the reply if it prevents a requested outcome. A manual plan must retain the documented fit and source gates.
- **Research:** use available direct-source browsing/search tools or sources actually supplied by the person. If verification is unavailable, report the limit and avoid presenting unchecked leads as verified recommendations.
- **Memory and chats:** inspect only sources within their recorded permission and actual availability. Sharing a taste model does not expand a source permission to another host's memories, chat archive, or online accounts. Preserve provenance and gaps; do not substitute one source for an unavailable source.
- **Scheduling.** Use the host’s native scheduler for the disclosed first-time Sunday default or a direct scheduling request. Check for a matching job and confirm it is active before setting weekly delivery to enabled. If scheduling is unavailable, keep weekly delivery disabled and offer an on-demand edition.

Respect explicit source restrictions even if another host exposes additional tools. Preserve unknown knowledge, baseline weights, and delivery choices across host changes. A source becoming available does not turn illustrative examples or assistant suggestions into personal evidence.

## Understand the test boundary

Installation checks can establish that a complete, private-state-free folder is placed in a documented location and that its helpers work outside the repository. Native host checks must additionally observe that the host discovers/loads the installed skill and executes its helpers. Authenticated model runs require the host's own credentials and tool permissions. Do not label a missing CLI, missing login, or packaging-only check as a passing complete host run.

Skill discovery and helper integration do not establish better recommendations. Evaluate the research, attribution, feedback, and scheduling behavior separately using the repository's behavioral scenarios before making broader quality claims.
