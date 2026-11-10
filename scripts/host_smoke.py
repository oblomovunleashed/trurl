#!/usr/bin/env python3
"""Isolated packaging checks and opt-in, real-host skill smoke runs.

No personal model, login file, host config, or history is copied. Live runs use
only inherited provider environment keys. Configuration isolation is not an OS
sandbox; use a disposable runner for untrusted hosts or skills.
"""
import argparse
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
import re
import secrets
import shlex
import shutil
import signal
import subprocess
import sys
import time

sys.dont_write_bytecode = True

AGENTS = ("codex", "claude-code", "pi")
EVIDENCE_PROTOCOL = "native_trace_v3"
BINARIES = {"codex": "codex", "claude-code": "claude", "pi": "pi"}
KEYS = ("CODEX_API_KEY", "OPENAI_API_KEY", "ANTHROPIC_API_KEY", "OPENROUTER_API_KEY",
        "GEMINI_API_KEY", "GOOGLE_API_KEY", "XAI_API_KEY", "MISTRAL_API_KEY",
        "GROQ_API_KEY", "DEEPSEEK_API_KEY", "NOUS_API_KEY")
ENDPOINTS = ("OPENAI_BASE_URL", "ANTHROPIC_BASE_URL", "OPENROUTER_BASE_URL")
INVOCATION = {"codex": "$trurl", "claude-code": "/trurl", "pi": "/skill:trurl"}
AUTH_FAILURE = re.compile(r"(?i)(not logged in|login required|authentication (?:failed|required)|"
                          r"invalid (?:api[- ]?key|authentication)|missing (?:api[- ]?key|credentials)|"
                          r"no (?:api[- ]?key|credentials|provider configured|model selected|models available)|unauthorized|\b401\b|please (?:log|sign) in)")


def write_json(path, value):
    Path(path).write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def bundle_fingerprint(directory):
    """Hash sorted relative paths and file digests, independent of host path."""
    directory = Path(directory)
    hasher = hashlib.sha256()
    for path in sorted(directory.rglob("*")):
        relative = path.relative_to(directory)
        if path.is_file() and "__pycache__" not in relative.parts and path.suffix != ".pyc":
            hasher.update((relative.as_posix() + "\0" + digest(path) + "\n").encode("utf-8"))
    return hasher.hexdigest()


def snapshot(paths):
    return {str(p): digest(p) for directory in paths for p in sorted(Path(directory).rglob("*")) if p.is_file()}


def load_runtime(root):
    spec = importlib.util.spec_from_file_location("curation_host_smoke", Path(root) / "skills/trurl/scripts/curation.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def isolated_environment(home, workspace, inherited=None):
    inherited = os.environ if inherited is None else inherited
    home, workspace = Path(home), Path(workspace)
    env = {k: inherited[k] for k in ("PATH", "LANG", "LC_ALL", "SYSTEMROOT", "WINDIR") if k in inherited}
    env.update({k: inherited[k] for k in KEYS + ENDPOINTS if inherited.get(k)})
    env.update({"HOME": str(home), "USERPROFILE": str(home), "CODEX_HOME": str(home / ".codex"),
                "CLAUDE_CONFIG_DIR": str(home / ".claude"), "TRURL_ROOT": str(workspace),
                "PI_CODING_AGENT_DIR": str(home / ".pi/agent"),
                "XDG_CONFIG_HOME": str(home / ".config"), "XDG_DATA_HOME": str(home / ".local/share"),
                "XDG_CACHE_HOME": str(home / ".cache"), "PYTHONDONTWRITEBYTECODE": "1",
                "TERMINAL_CWD": str(workspace), "NO_COLOR": "1",
                "CLAUDE_CODE_DISABLE_BACKGROUND_TASKS": "1", "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1"})
    return env


def redact(text, env):
    for key in KEYS:
        value = env.get(key)
        if value and len(value) >= 6:
            text = text.replace(value, "[REDACTED:" + key + "]")
    return text


def execute(argv, cwd, env, timeout):
    started = time.monotonic()
    process = subprocess.Popen(argv, cwd=str(cwd), env=env, stdin=subprocess.DEVNULL,
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                               start_new_session=(os.name != "nt"))
    timed_out = False
    try:
        stdout, stderr = process.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        timed_out = True
        if os.name != "nt":
            os.killpg(process.pid, signal.SIGKILL)
        else:
            process.kill()
        stdout, stderr = process.communicate()
    return {"returncode": process.returncode, "stdout": redact(stdout, env),
            "stderr": redact(stderr, env), "timed_out": timed_out,
            "duration_seconds": round(time.monotonic() - started, 3)}


def helper_json(runtime, arguments, workspace, env):
    result = execute([sys.executable, str(runtime)] + arguments, workspace, env, 20)
    if result["returncode"] != 0 or result["timed_out"]:
        raise RuntimeError("Installed helper failed: " + result["stderr"][:500])
    return json.loads(result["stdout"])


def check_brief_helper(installed, workspace, artifacts, env):
    """Exercise the copied cache helper without changing its synthetic sources."""
    installed, workspace, artifacts = Path(installed), Path(workspace), Path(artifacts)
    runtime = installed / "scripts/brief.py"
    draft_path = artifacts / "curators-brief.draft.json"
    commands = {
        "snapshot": ["snapshot", "--root", str(workspace)],
        "save": ["save", "--root", str(workspace), "--draft", str(draft_path)],
        "check": ["check", "--root", str(workspace)],
    }
    before = snapshot([installed, workspace / "model"])
    captured = helper_json(runtime, commands["snapshot"], workspace, env)
    draft = dict(captured)
    draft.update({
        "summary": "Synthetic host fixture only. Demonstration profile anchors are software test data, "
                   "not evidence of a real person's taste. Personal preferences remain unknown.",
        "source_refs": [{"path": "model/profile.json", "locator": "#",
                         "note": "Synthetic demonstration profile supplied by the packaging check."}],
        "limits": ["No real person, personal history or recommendation quality is evaluated."],
    })
    write_json(draft_path, draft)
    saved = helper_json(runtime, commands["save"], workspace, env)
    checked = helper_json(runtime, commands["check"], workspace, env)
    after = snapshot([installed, workspace / "model"])
    cache_path = str(workspace / "model/curators-brief.json")
    if ({path: value for path, value in after.items() if path != cache_path}
            != {path: value for path, value in before.items() if path != cache_path}):
        raise ValueError("brief helper check changed its sources or installed skill")
    if saved.get("status") != "saved" or checked.get("status") != "fresh" or cache_path not in after:
        raise ValueError("installed brief helper did not save a fresh cache")
    return {"runtime": str(runtime), "commands": commands, "snapshot": captured,
            "save": saved, "check": checked, "sources_and_skill_unchanged": True}


def prepare_case(agent, directory, root):
    """Create only synthetic state and install through the public installer."""
    if agent not in AGENTS:
        raise ValueError("Unsupported host: " + str(agent))
    directory, root = Path(directory).resolve(), Path(root).resolve()
    directory.mkdir(parents=True, exist_ok=False)
    home, workspace = directory / "home", directory / "workspace"
    home.mkdir(); workspace.mkdir()
    for relative in (".codex", ".claude", ".pi/agent"):
        (home / relative).mkdir(parents=True, exist_ok=True)
    write_json(home / "empty-mcp.json", {"mcpServers": {}})
    artifacts = workspace / "artifacts"
    artifacts.mkdir()
    env = isolated_environment(home, workspace)
    targets = load_runtime(root).resolve_install_targets(agent=agent, home=home)
    installation = load_runtime(root).install_skill(agent=agent, home=home)
    installed = Path(targets[0]["path"])
    runtime = installed / "scripts/curation.py"
    init = helper_json(runtime, ["init", "--root", str(workspace)], workspace, env)
    if len(init["files"]) != 5:
        raise ValueError("initializer did not produce five model files")
    blank = json.loads((workspace / "model/graph.json").read_text())
    if blank["nodes"] != [] or blank["edges"] != []:
        raise ValueError("initializer graph was not empty")
    fresh = json.loads((workspace / "model/profile.json").read_text())
    if fresh["delivery"]["weekly"]["enabled"] is not False:
        raise ValueError("initializer enabled weekly delivery")
    for name, source in (("profile.json", "profile.graph-demo.json"), ("graph.json", "graph.example.json")):
        shutil.copyfile(root / "examples" / source, workspace / "model" / name)
    commands = {
        "weights": ["weights", "--root", str(workspace), "--request", "surprise me", "--mode", "surprise", "--scope", "broad", "--seed", "42"],
        "graph-check": ["graph-check", "--graph", str(workspace / "model/graph.json")],
        "frontier": ["frontier", "--graph", str(workspace / "model/graph.json"), "--profile", str(workspace / "model/profile.json"), "--seed", "42", "--count", "3"],
    }
    before = snapshot([installed, workspace / "model"])
    expected = {name: helper_json(runtime, args, workspace, env) for name, args in commands.items()}
    if snapshot([installed, workspace / "model"]) != before:
        raise ValueError("packaging helper check changed its model or installed skill")
    brief_check = check_brief_helper(installed, workspace, artifacts, env)
    before = snapshot([installed, workspace / "model"])
    case = {"agent": agent, "directory": str(directory), "home": str(home), "workspace": str(workspace),
            "installed": str(installed), "runtime": str(runtime), "artifacts": str(artifacts),
            "nonce": secrets.token_hex(16), "expected": expected, "commands": commands,
            "skill_sha256": digest(installed / "SKILL.md"),
            "bundle_sha256": bundle_fingerprint(installed),
            "python_executable": sys.executable,
            "before": before, "installation": installation, "brief_helper_check": brief_check}
    write_json(directory / "case.json", case)
    (directory / "prompt.txt").write_text(make_prompt(case), encoding="utf-8")
    return case


def make_prompt(case):
    # Intentionally omit the installed skill path: native discovery must find it.
    # Pi 1.5 parses /skill:name at the first literal space, not any whitespace.
    separator = " " if case["agent"] == "pi" else "\n"
    return """{invocation}{separator}Run a local integration smoke test using your installed trurl skill.
Use your native skill discovery to locate it, then explicitly read its installed
SKILL.md with a tool even if the invocation already expanded its instructions.
Do not use a repository source copy or create a replacement skill. If discovery
fails, state that and stop. This is a synthetic software fixture, not onboarding
or a recommendation request. Do not ask questions, browse, access real memory,
other chats/accounts, configure providers, send messages, or schedule anything.
Read and write only inside this isolated home and workspace. Do not inspect or
print credentials or environment variables. Do not alter the fixture model or skill.

Curation root: {workspace}
Artifact directory: {artifacts}
Python executable: {python}

Resolve scripts/curation.py relative to the discovered installed skill. Execute
these three commands as separate direct tool executions using the ABSOLUTE
installed helper path and Python above. Do not use a Python -c/-m code wrapper,
shell variables, command substitutions, pipelines, or combined shell statements
for these proof commands. Simple stdout redirection to its artifact is allowed:
1. weights --root {workspace_shell} --request "surprise me" --mode surprise --scope broad --seed 42
2. graph-check --graph {graph_shell}
3. frontier --graph {graph_shell} --profile {profile_shell} --seed 42 --count 3
Save each command's actual JSON stdout, without reconstruction, to respectively
weights.json, graph-check.json, and frontier.json inside the artifact directory.
Use tools to write discovery.json in that directory with these exact keys:
skill_path (absolute installed SKILL.md path), skill_sha256 (SHA256 of its bytes),
nonce (the literal value {nonce}). Finish with a short pass/failure account.
""".format(invocation=INVOCATION[case["agent"]], separator=separator, workspace=case["workspace"], artifacts=case["artifacts"],
           python=sys.executable, workspace_shell=shlex.quote(case["workspace"]),
           graph_shell=shlex.quote(str(Path(case["workspace"]) / "model/graph.json")),
           profile_shell=shlex.quote(str(Path(case["workspace"]) / "model/profile.json")), nonce=case["nonce"])


def host_command(agent, executable, case, model=None):
    if agent not in AGENTS:
        raise ValueError("Unsupported host: " + str(agent))
    prompt = make_prompt(case)
    if agent == "codex":
        argv = [executable, "exec", "--json", "--ephemeral", "--ignore-user-config", "--ignore-rules",
                "--skip-git-repo-check", "--sandbox", "workspace-write", "-c", 'approval_policy="never"',
                "-C", case["workspace"], "--add-dir", case["home"]]
    elif agent == "claude-code":
        # Bare avoids real subscription/keychain reads. --add-dir retains the
        # isolated home's .claude/skills discovery in bare mode.
        argv = [executable, "--bare", "--add-dir", case["home"], "--output-format", "stream-json",
                "--verbose", "--no-session-persistence", "--allowedTools", "Read,Bash,Write,Edit",
                "--strict-mcp-config", "--mcp-config", str(Path(case["home"]) / "empty-mcp.json")]
    elif agent == "pi":
        # Verified against earendil-works/pi v1.5.0 cli.md and args.ts.
        # Native user-skill discovery remains enabled in the isolated HOME;
        # no-approve excludes project/ancestor resources, including .agents.
        argv = [executable, "--mode", "json", "--print", "--no-session", "--no-extensions",
                "--no-mcp", "--no-prompt-templates", "--no-themes", "--no-context-files",
                "--no-approve", "--tools", "read,bash,write"]
    if model:
        argv += ["--model", model]
    if agent == "claude-code":
        # Terminate variadic --mcp-config/--add-dir before the positional prompt.
        argv.append("-p")
    return argv + [prompt]


def json_events(stdout):
    """Read top-level native JSONL records; never parse prose or nested output."""
    for line in stdout.split("\n"):
        try:
            event = json.loads(line)
        except ValueError:
            continue
        if not isinstance(event, dict):
            continue
        yield event


def tool_records(agent, stdout):
    """Extract completed native tools; assistant prose is never tool evidence."""
    records, pending, seen = [], {}, set()
    for event in json_events(stdout):
        if agent == "codex":
            item = event.get("item", {})
            if event.get("type") == "item.completed" and item.get("type") == "command_execution" and item.get("exit_code") == 0:
                records.append(("command", {"command": item.get("command", "")}))
        elif agent == "claude-code" and event.get("type") in {"assistant", "user"}:
            for part in event.get("message", {}).get("content", []):
                if not isinstance(part, dict):
                    continue
                if part.get("type") == "tool_use":
                    pending[part.get("id")] = (part.get("name", ""), part.get("input", {}))
                elif part.get("type") == "tool_result" and not part.get("is_error", False):
                    record = pending.pop(part.get("tool_use_id"), None)
                    if record:
                        records.append(record)
        elif agent == "pi":
            # Pi emits separate execution-start and execution-end records.
            # Updates, assistant tool-call proposals, and result text do not
            # establish execution. Consume failed/mismatched ends as well.
            identifier = event.get("toolCallId")
            if not isinstance(identifier, str) or not identifier:
                continue
            if event.get("type") == "tool_execution_start":
                if identifier in seen:
                    pending.pop(identifier, None)
                    continue
                seen.add(identifier)
                name, args = event.get("toolName"), event.get("args")
                if isinstance(name, str) and name in {"read", "bash", "write"} and isinstance(args, dict):
                    pending[identifier] = (name, args)
            elif event.get("type") == "tool_execution_end":
                record = pending.pop(identifier, None)
                if record is None or event.get("toolName") != record[0] or event.get("isError") is not False:
                    continue
                elapsed, result = event.get("durationMs"), event.get("result")
                if ("durationMs" in event and (type(elapsed) not in (int, float)
                        or (type(elapsed) is float and not math.isfinite(elapsed)) or elapsed < 0)):
                    continue
                if (not isinstance(result, dict) or not isinstance(result.get("content"), list)
                        or result.get("isError", False) is not False):
                    continue
                if record[0] == "bash":
                    structured = result.get("structuredContent")
                    if (not isinstance(structured, dict) or type(structured.get("exit_code")) is not int
                            or structured["exit_code"] != 0):
                        continue
                records.append(record)
    return records


def pi_run_completed(stdout):
    """JSON mode can exit zero after model errors; require native completion.

    agent_end is only a low-level boundary. A final successful assistant and
    agent_settled are needed after any retry. Neither prose nor tool success
    alone establishes that the invocation completed.
    """
    last_assistant, ended, settled = None, False, False
    for event in json_events(stdout):
        kind = event.get("type")
        if kind == "agent_start":
            last_assistant, ended, settled = None, False, False
        elif kind == "message_end":
            message = event.get("message")
            if isinstance(message, dict) and message.get("role") == "assistant":
                last_assistant = message
                settled = False
        elif kind == "agent_end":
            ended = event.get("willRetry") is False
            settled = False
        elif kind == "agent_settled":
            settled = event.get("aborted") is False
        elif kind == "auto_retry_end" and event.get("success") is not True:
            ended, settled = False, False
    return (ended and settled and isinstance(last_assistant, dict)
            and last_assistant.get("stopReason") == "stop" and not last_assistant.get("errorMessage"))


def trace_checks(case, records):
    skill = str(Path(case["installed"]) / "SKILL.md")
    runtime = case["runtime"]
    read, commands = False, set()
    for name, args in records:
        if not isinstance(args, dict):
            continue
        if name.lower() in {"read", "read_file"}:
            location = args.get("file_path", args.get("path"))
            if isinstance(location, str):
                location = location.replace("~/", case["home"] + "/", 1) if location.startswith("~/") else location
                location = Path(location)
                if not location.is_absolute():
                    location = Path(case["workspace"]) / location
                if str(location.resolve()) == skill:
                    read = True
        command = args.get("command", "")
        if not isinstance(command, str):
            continue
        tokens = direct_shell_tokens(command)
        if not tokens:
            continue
        program = Path(tokens[0]).name
        if ((program == "cat" and tokens[1:] in ([skill], ["--", skill])) or
                (program == "sed" and len(tokens) == 4 and tokens[1] == "-n" and tokens[3] == skill
                 and re.fullmatch(r"1,\d+p", tokens[2]))):
            read = True
        expected_python = Path(case.get("python_executable", sys.executable)).resolve()
        if len(tokens) >= 3 and Path(tokens[0]).is_absolute() and Path(tokens[0]).resolve() == expected_python and tokens[1] == runtime:
            operation = tokens[2]
            if operation not in case["commands"]:
                continue
            arguments = tokens[2:]
            if ">" in arguments:
                index = arguments.index(">")
                target = str(Path(case["artifacts"]) / (operation + ".json"))
                if arguments[index:] != [">", target]:
                    continue
                arguments = arguments[:index]
            if arguments == case["commands"][operation]:
                commands.add(operation)
    return {"installed_skill_read_in_tool_trace": read,
            "installed_helpers_in_tool_trace": sorted(commands), "native_tool_events": len(records)}


def direct_shell_tokens(command):
    """Recognize one direct command, optionally inside the host's shell wrapper.

    This deliberately is not a shell interpreter. Composite commands, shell
    expansions, pipes, and input redirection fail closed rather than claiming
    that a quoted mention of a helper establishes execution.
    """
    try:
        outer = shlex.split(command, comments=True, posix=True)
        if len(outer) == 3 and Path(outer[0]).name in {"sh", "bash", "zsh"} and outer[1] in {"-c", "-lc", "-cl"}:
            command = outer[2]
        if "$" in command or "`" in command:
            return None
        lexer = shlex.shlex(command, posix=True, punctuation_chars=";&|<>()\n")
        lexer.whitespace = " \t\r"
        lexer.whitespace_split = True
        lexer.commenters = "#"
        tokens = list(lexer)
    except ValueError:
        return None
    if any(token and all(c in ";&|<>()\n" for c in token) and token != ">" for token in tokens):
        return None
    return tokens or None


def validate_live(case, agent, stdout, returncode):
    errors = []
    checks = trace_checks(case, tool_records(agent, stdout))
    if agent == "pi":
        checks["native_run_completed"] = pi_run_completed(stdout)
        if not checks["native_run_completed"]:
            errors.append("native_run_completion_not_proven")
    if returncode != 0:
        errors.append("host_exit_nonzero")
    if not checks["installed_skill_read_in_tool_trace"]:
        errors.append("no_installed_skill_read_in_native_tool_trace")
    if checks["installed_helpers_in_tool_trace"] != ["frontier", "graph-check", "weights"]:
        errors.append("installed_helper_execution_not_proven")
    for name, expected in case["expected"].items():
        path = Path(case["artifacts"]) / (name + ".json")
        try:
            if path.is_symlink() or json.loads(path.read_text()) != expected:
                errors.append(name + "_artifact_mismatch")
        except (OSError, ValueError):
            errors.append(name + "_artifact_missing_or_invalid")
    try:
        path = Path(case["artifacts"]) / "discovery.json"
        found = json.loads(path.read_text()) if not path.is_symlink() else {}
        if found != {"skill_path": str(Path(case["installed"]) / "SKILL.md"),
                     "skill_sha256": case["skill_sha256"], "nonce": case["nonce"]}:
            errors.append("discovery_artifact_mismatch")
    except (OSError, ValueError):
        errors.append("discovery_artifact_missing_or_invalid")
    unchanged = snapshot([Path(case["installed"]), Path(case["workspace"]) / "model"]) == case["before"]
    if not unchanged:
        errors.append("fixture_or_skill_changed")
    return {"passed": not errors, "errors": errors, "checks": checks, "inputs_unchanged": unchanged}


def run_host(agent, directory, root, live=False, executable=None, model=None, timeout=120, codex_auth_home=None):
    if agent not in AGENTS:
        raise ValueError("Unsupported host: " + str(agent))
    if codex_auth_home is not None:
        if agent != "codex" or not live:
            raise ValueError("codex_auth_home requires one live Codex run")
        codex_auth_home = Path(codex_auth_home).expanduser().resolve()
        if not codex_auth_home.is_dir():
            raise ValueError("codex_auth_home must be an existing directory")
    result = {"agent": agent, "mode": "live" if live else "packaging_only", "live_status": "not_run",
              "evidence_protocol": EVIDENCE_PROTOCOL, "validator_sha256": digest(Path(__file__)),
              "auth_scope": "existing_codex_native_auth_state" if codex_auth_home else "isolated_home_provider_environment_only",
              "auth_home_isolated": codex_auth_home is None,
              "evidence_level": "authenticated_host" if live else "packaging_only",
              "scope": "explicit native skill invocation and installed helper execution" if live else "isolated bundle installation and helper execution"}
    try:
        case = prepare_case(agent, directory, root)
        result.update({"packaging_status": "passed", "case": str(Path(directory) / "case.json"),
                       "installed": case["installed"], "synthetic_inputs_only": True})
        result["bundle_sha256"] = case["bundle_sha256"]
    except (OSError, ValueError, RuntimeError, AssertionError, TypeError) as error:
        result.update({"status": "failed", "packaging_status": "failed", "reason": str(error)})
        return result
    if not live:
        result["status"] = "packaging_passed"
        return result
    binary = executable or shutil.which(BINARIES[agent])
    if not binary:
        result.update({"status": "blocked", "live_status": "blocked", "reason": "host_cli_not_found"})
        write_json(Path(directory) / "result.json", result)
        return result
    env = isolated_environment(case["home"], case["workspace"])
    if codex_auth_home is not None:
        # Explicit opt-in only. Python never reads or copies login/config files;
        # the native CLI may use and refresh authentication in this directory.
        env["CODEX_HOME"] = str(codex_auth_home)
    result["provider_environment_names_present"] = [key for key in KEYS if env.get(key)]
    argv = host_command(agent, str(binary), case, model)
    result["argv"] = argv[:-1] + ["<prompt.txt>"]
    try:
        version = execute([str(binary), "--version"], case["workspace"], env, 15)
        result["host_version"] = (version["stdout"] or version["stderr"]).strip()[:300]
        execution = execute(argv, case["workspace"], env, timeout)
    except OSError as error:
        result.update({"status": "blocked", "live_status": "blocked", "reason": "host_launch_failed: " + str(error)})
    else:
        Path(directory, "stdout.jsonl").write_text(execution["stdout"], encoding="utf-8")
        Path(directory, "stderr.txt").write_text(execution["stderr"], encoding="utf-8")
        validation = validate_live(case, agent, execution["stdout"], execution["returncode"])
        result.update({k: execution[k] for k in ("returncode", "timed_out", "duration_seconds")})
        result["validation"] = validation
        if execution["timed_out"]:
            result.update({"status": "blocked", "live_status": "blocked", "reason": "host_timeout"})
        elif validation["passed"]:
            result.update({"status": "passed", "live_status": "passed"})
        elif AUTH_FAILURE.search(execution["stdout"] + execution["stderr"]):
            result.update({"status": "blocked", "live_status": "blocked", "reason": "provider_authentication_required_or_failed"})
        else:
            result.update({"status": "failed", "live_status": "failed", "reason": "host_run_or_artifact_validation_failed"})
    write_json(Path(directory) / "result.json", result)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--agent", choices=AGENTS + ("all",), default="all")
    parser.add_argument("--output", type=Path, required=True, help="fresh evidence directory; never overwritten")
    parser.add_argument("--live", action="store_true", help="invoke real hosts (provider access and possible inference cost)")
    parser.add_argument("--executable", help="exact host executable; single agent only")
    parser.add_argument("--model", help="optional real host model selection")
    parser.add_argument("--codex-auth-home", type=Path,
                        help="opt into existing native Codex auth directory; only --live --agent codex; CLI may refresh login")
    parser.add_argument("--timeout", type=int, default=120, help="per-host live timeout, 10–600 seconds")
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()
    if args.agent == "all" and args.executable:
        parser.error("--executable requires one --agent")
    if args.codex_auth_home is not None:
        if args.agent != "codex" or not args.live:
            parser.error("--codex-auth-home requires --live --agent codex")
        args.codex_auth_home = args.codex_auth_home.expanduser().resolve()
        if not args.codex_auth_home.is_dir():
            parser.error("--codex-auth-home must be an existing directory")
    if not 10 <= args.timeout <= 600:
        parser.error("--timeout must be 10–600 seconds")
    try:
        args.output.mkdir(parents=True, exist_ok=False)
    except OSError as error:
        parser.exit(2, str(error) + "\n")
    agents = AGENTS if args.agent == "all" else (args.agent,)
    results = [run_host(agent, args.output / agent, args.root, args.live, args.executable,
                        args.model, args.timeout, args.codex_auth_home) for agent in agents]
    summary = {"schema_version": 1, "mode": "live" if args.live else "packaging_only",
               "evidence_protocol": EVIDENCE_PROTOCOL, "validator_sha256": digest(Path(__file__)),
               "evidence_level": "authenticated_host" if args.live else "packaging_only", "results": results,
               "limits": ["Packaging checks do not establish native host discovery or model behavior.",
                          "Live smoke checks explicit skill invocation and local helper execution, not recommendation quality.",
                          "Home/config isolation is not an operating-system security sandbox."]}
    write_json(args.output / "summary.json", summary)
    print(json.dumps({"evidence": str(args.output.resolve() / "summary.json"),
                      "mode": summary["mode"], "outcomes": {r["agent"]: r["status"] for r in results}}, indent=2))
    return 0 if all(r["status"] in {"passed", "packaging_passed"} for r in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
