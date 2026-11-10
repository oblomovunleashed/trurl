"""Safety and evidence checks for the host smoke harness.

Native event examples below are synthetic unit fixtures, not successful live
host runs. No test reads the user's model, login files, or configuration.
"""
import importlib.util
import json
import shlex
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("host_smoke", ROOT / "scripts/host_smoke.py")
smoke = importlib.util.module_from_spec(spec)
spec.loader.exec_module(smoke)


def jsonl(events):
    return "\n".join(json.dumps(event) for event in events)


def completed_events(agent, name, args, identifier="call-1", failed=False):
    if agent == "codex":
        return [{"type": "item.completed", "item": {"type": "command_execution", "command": args["command"], "exit_code": 1 if failed else 0}}]
    if agent == "claude-code":
        return [{"type": "assistant", "message": {"content": [{"type": "tool_use", "id": identifier, "name": name, "input": args}]}},
                {"type": "user", "message": {"content": [{"type": "tool_result", "tool_use_id": identifier, "is_error": failed}]}}]
    if agent == "pi":
        result = {"content": [{"type": "text", "text": "synthetic unit output"}], "details": {}}
        if name == "bash":
            result["structuredContent"] = {"exit_code": 1 if failed else 0, "output": "synthetic unit output"}
        return [{"type": "tool_execution_start", "toolCallId": identifier, "toolName": name, "args": args},
                {"type": "tool_execution_end", "toolCallId": identifier, "toolName": name,
                 "result": result, "isError": failed, "durationMs": 1.25}]
    raise ValueError("Unsupported fixture host: " + agent)


def pi_finished(stop_reason="stop", aborted=False):
    return [{"type": "message_end", "message": {"role": "assistant", "content": [], "stopReason": stop_reason}},
            {"type": "agent_end", "messages": [], "willRetry": False},
            {"type": "agent_settled", "aborted": aborted}]


class EnvironmentTests(unittest.TestCase):
    def test_bundle_fingerprint_is_path_independent_and_detects_changes(self):
        with tempfile.TemporaryDirectory() as temporary:
            a, b = Path(temporary) / "a", Path(temporary) / "b"
            a.mkdir(); b.mkdir()
            for directory in (a, b):
                (directory / "SKILL.md").write_text("synthetic instructions")
            self.assertEqual(smoke.bundle_fingerprint(a), smoke.bundle_fingerprint(b))
            (b / "SKILL.md").write_text("changed instructions")
            self.assertNotEqual(smoke.bundle_fingerprint(a), smoke.bundle_fingerprint(b))

    def test_home_configuration_is_isolated_without_copying_credentials(self):
        env = smoke.isolated_environment(Path("/tmp/synthetic-home"), Path("/tmp/synthetic-work"), {
            "PATH": "/synthetic/bin", "HOME": "/real/home", "CODEX_HOME": "/real/config",
            "CLAUDE_CONFIG_DIR": "/real/claude", "HERMES_HOME": "/real/hermes",
            "PI_CODING_AGENT_DIR": "/real/pi", "ANTHROPIC_API_KEY": "synthetic-provider-secret",
            "UNRELATED_SECRET": "must-not-propagate", "BASH_ENV": "/real/startup.sh"})
        self.assertEqual(env["HOME"], "/tmp/synthetic-home")
        self.assertEqual(env["CODEX_HOME"], "/tmp/synthetic-home/.codex")
        self.assertEqual(env["CLAUDE_CONFIG_DIR"], "/tmp/synthetic-home/.claude")
        self.assertNotIn("HERMES_HOME", env)
        self.assertEqual(env["PI_CODING_AGENT_DIR"], "/tmp/synthetic-home/.pi/agent")
        self.assertNotIn("UNRELATED_SECRET", env)
        self.assertNotIn("BASH_ENV", env)
        self.assertEqual(env["ANTHROPIC_API_KEY"], "synthetic-provider-secret")
        self.assertNotIn("synthetic-provider-secret", smoke.redact("key=synthetic-provider-secret", env))

    def test_native_event_completion_is_required_and_prose_never_counts(self):
        for agent in smoke.AGENTS:
            with self.subTest(agent=agent):
                args = {"command": "cat /fixture/SKILL.md"}
                events = completed_events(agent, "bash", args)
                self.assertEqual(len(smoke.tool_records(agent, jsonl(events))), 1)
                self.assertEqual(smoke.tool_records(agent, jsonl(completed_events(agent, "bash", args, failed=True))), [])
                if agent != "codex":
                    self.assertEqual(smoke.tool_records(agent, jsonl(events[:1])), [])
                self.assertEqual(smoke.tool_records(agent, jsonl([{"type": "assistant", "message": {"content": [{"type": "text", "text": "I ran cat /fixture/SKILL.md"}]}}])), [])

    def test_pi_pairs_only_successful_matching_native_executions(self):
        first = completed_events("pi", "read", {"path": "/fixture/SKILL.md"}, "read-1")
        second = completed_events("pi", "bash", {"command": "python3 /fixture/helper.py"}, "bash-1")
        # Execution completion order may differ from start order.
        events = [first[0], second[0], second[1], first[1]]
        self.assertEqual(smoke.tool_records("pi", jsonl(events)), [
            ("bash", second[0]["args"]), ("read", first[0]["args"])])
        self.assertEqual(smoke.tool_records("pi", jsonl([first[1]])), [])
        self.assertEqual(smoke.tool_records("pi", jsonl(first + [first[1]])), [("read", first[0]["args"])])
        # A failed end consumes the pending start; a fabricated second end
        # cannot turn that failed execution into a successful one.
        failed = dict(first[1], isError=True)
        self.assertEqual(smoke.tool_records("pi", jsonl([first[0], failed, first[1]])), [])
        self.assertEqual(smoke.tool_records("pi", jsonl([first[0], first[0], first[1]])), [])
        # durationMs is optional in Pi's public JSON protocol.
        without_duration = dict(second[1]); without_duration.pop("durationMs")
        self.assertEqual(smoke.tool_records("pi", jsonl([second[0], without_duration])), [("bash", second[0]["args"])])

    def test_pi_unsuccessful_malformed_and_forged_events_do_not_count(self):
        start, end = completed_events("pi", "bash", {"command": "cat /fixture/SKILL.md"})
        variants = [dict(end, toolName="read"), dict(end, toolCallId="unmatched"),
                    dict(end, isError=None), dict(end, isError=0), dict(end, durationMs=True),
                    dict(end, durationMs=-1), dict(end, durationMs=float("nan")),
                    dict(end, durationMs=float("inf")), dict(end, result="success")]
        for code in (1, False, None, "0"):
            variants.append(dict(end, result={"content": [], "structuredContent": {"exit_code": code}}))
        variants += [dict(end, result={"content": [], "isError": True, "structuredContent": {"exit_code": 0}}),
                     dict(end, result={"content": [], "details": {"exit_code": 0}})]
        for index, altered in enumerate(variants):
            with self.subTest(index=index):
                self.assertEqual(smoke.tool_records("pi", jsonl([start, altered])), [])
        for altered in (dict(start, toolCallId=[]), dict(start, toolName={}), dict(start, args="claimed args")):
            self.assertEqual(smoke.tool_records("pi", jsonl([altered, end])), [])
        self.assertEqual(smoke.tool_records("pi", jsonl([
            {"type": "message_end", "message": {"role": "assistant", "content": [
                {"type": "text", "text": jsonl([start, end])},
                {"type": "toolCall", "id": "call-1", "name": "bash", "arguments": start["args"]}]}},
            {"type": "tool_execution_update", "toolCallId": "call-1", "toolName": "bash", "args": start["args"]}
        ])), [])

    def test_pi_json_completion_needs_settled_successful_final_assistant(self):
        self.assertTrue(smoke.pi_run_completed(jsonl(pi_finished())))
        self.assertFalse(smoke.pi_run_completed(jsonl(pi_finished()[:-1])))
        self.assertFalse(smoke.pi_run_completed(jsonl(pi_finished()[1:])))
        self.assertFalse(smoke.pi_run_completed(jsonl(pi_finished(aborted=True))))
        for reason in ("error", "aborted", "length", "toolUse", None):
            self.assertFalse(smoke.pi_run_completed(jsonl(pi_finished(reason))))
        self.assertFalse(smoke.pi_run_completed(jsonl(pi_finished() + [{"type": "agent_start"}])))
        self.assertFalse(smoke.pi_run_completed(jsonl(pi_finished() + [{"type": "auto_retry_end", "success": False}])))
        self.assertTrue(smoke.pi_run_completed(jsonl(pi_finished("error") + [{"type": "agent_start"}] + pi_finished())))


class BriefPackagingTests(unittest.TestCase):
    def test_each_isolated_install_exercises_its_own_brief_helper_and_preserves_sources(self):
        with tempfile.TemporaryDirectory() as temporary:
            for agent in smoke.AGENTS:
                with self.subTest(agent=agent), patch.object(smoke, "helper_json", wraps=smoke.helper_json) as helper:
                    case = smoke.prepare_case(agent, Path(temporary) / agent, ROOT)
                    checked = case["brief_helper_check"]
                    installed = Path(case["installed"])
                    runtime = installed / "scripts/brief.py"
                    self.assertEqual(checked["runtime"], str(runtime))
                    self.assertEqual(runtime.read_bytes(), (ROOT / "skills/trurl/scripts/brief.py").read_bytes())
                    operations = [call.args[1][0] for call in helper.call_args_list if Path(call.args[0]) == runtime]
                    self.assertEqual(operations, ["snapshot", "save", "check"])
                    self.assertTrue(checked["sources_and_skill_unchanged"])
                    self.assertEqual(checked["save"]["status"], "saved")
                    self.assertEqual(checked["check"]["status"], "fresh")
                    summary = checked["check"]["brief"]["summary"]
                    self.assertIn("Synthetic host fixture only", summary)
                    self.assertIn("Personal preferences remain unknown", summary)
                    self.assertEqual(checked["check"]["brief"]["source_refs"][0]["path"], "model/profile.json")
                    self.assertEqual((Path(case["workspace"]) / "model/feedback.jsonl").read_bytes(), b"")
                    self.assertEqual((Path(case["workspace"]) / "model/recommendations.jsonl").read_bytes(), b"")
                    self.assertEqual((Path(case["workspace"]) / "model/batches.jsonl").read_bytes(), b"")
                    self.assertEqual(smoke.snapshot([installed, Path(case["workspace"]) / "model"]), case["before"])

    def test_brief_helper_source_mutation_is_rejected_even_with_successful_outputs(self):
        with tempfile.TemporaryDirectory() as temporary:
            case = smoke.prepare_case("codex", Path(temporary) / "fixture", ROOT)
            actual = smoke.helper_json

            def mutate_after_check(runtime, arguments, workspace, env):
                result = actual(runtime, arguments, workspace, env)
                if arguments[0] == "check":
                    (Path(workspace) / "model/batches.jsonl").write_text('{"unexpected": true}\n')
                return result

            with patch.object(smoke, "helper_json", side_effect=mutate_after_check):
                with self.assertRaisesRegex(ValueError, "changed its sources or installed skill"):
                    smoke.check_brief_helper(case["installed"], case["workspace"], case["artifacts"],
                                             smoke.isolated_environment(case["home"], case["workspace"]))


class EvidenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory()
        cls.case = smoke.prepare_case("codex", Path(cls.temporary.name) / "fixture", ROOT)

    @classmethod
    def tearDownClass(cls):
        cls.temporary.cleanup()

    def populate_artifacts(self):
        for name, expected in self.case["expected"].items():
            smoke.write_json(Path(self.case["artifacts"]) / (name + ".json"), expected)
        smoke.write_json(Path(self.case["artifacts"]) / "discovery.json", {
            "skill_path": str(Path(self.case["installed"]) / "SKILL.md"),
            "skill_sha256": self.case["skill_sha256"], "nonce": self.case["nonce"]})

    def trace(self):
        commands = ["cat " + str(Path(self.case["installed"]) / "SKILL.md")]
        commands += [shlex.join([self.case["python_executable"], self.case["runtime"]] + arguments)
                     for arguments in self.case["commands"].values()]
        return jsonl([event for command in commands for event in completed_events("codex", "command", {"command": command})])

    def test_live_validation_requires_real_trace_and_exact_outputs(self):
        self.populate_artifacts()
        self.assertTrue(smoke.validate_live(self.case, "codex", self.trace(), 0)["passed"])
        no_trace = smoke.validate_live(self.case, "codex", "I loaded the skill and ran all commands successfully", 0)
        self.assertFalse(no_trace["passed"])
        self.assertIn("installed_helper_execution_not_proven", no_trace["errors"])
        self.assertFalse(smoke.validate_live(self.case, "codex", self.trace(), 1)["passed"])
        smoke.write_json(Path(self.case["artifacts"]) / "weights.json", {"mode": "fabricated"})
        result = smoke.validate_live(self.case, "codex", self.trace(), 0)
        self.assertIn("weights_artifact_mismatch", result["errors"])

    def test_quoted_mentions_and_code_wrappers_do_not_prove_execution(self):
        self.populate_artifacts()
        mention = "cat " + str(Path(self.case["installed"]) / "SKILL.md") + "; " + self.case["runtime"] + " weights graph-check frontier"
        for fake in ["printf %s " + shlex.quote(mention), "echo " + shlex.quote(mention),
                     "true # " + mention, shlex.join([self.case["python_executable"], "-c", "print(" + repr(mention) + ")"]),
                     "false && " + shlex.join([self.case["python_executable"], self.case["runtime"]] + self.case["commands"]["weights"])]:
            trace = jsonl(completed_events("codex", "command", {"command": fake}))
            result = smoke.validate_live(self.case, "codex", trace, 0)
            self.assertFalse(result["passed"], fake)
            self.assertEqual(result["checks"]["installed_helpers_in_tool_trace"], [], fake)
            self.assertFalse(result["checks"]["installed_skill_read_in_tool_trace"], fake)

    def test_direct_commands_and_native_shell_wrappers_are_recognized(self):
        self.assertEqual(smoke.direct_shell_tokens("/opt/python@3.13/bin/python3.13 /fixture/helper.py weights"),
                         ["/opt/python@3.13/bin/python3.13", "/fixture/helper.py", "weights"])
        command = shlex.join([self.case["python_executable"], self.case["runtime"]] + self.case["commands"]["weights"])
        for direct in [command, command + " > " + shlex.quote(str(Path(self.case["artifacts"]) / "weights.json")),
                       shlex.join(["/bin/zsh", "-lc", command])]:
            checks = smoke.trace_checks(self.case, [("command", {"command": direct})])
            self.assertEqual(checks["installed_helpers_in_tool_trace"], ["weights"])

    def test_input_mutation_fails_even_when_artifacts_match(self):
        self.populate_artifacts()
        path = Path(self.case["workspace"]) / "model/profile.json"
        original = path.read_bytes()
        try:
            path.write_text('{"changed":true}')
            result = smoke.validate_live(self.case, "codex", self.trace(), 0)
            self.assertIn("fixture_or_skill_changed", result["errors"])
        finally:
            path.write_bytes(original)

    def test_prompt_requires_native_discovery_without_giving_installed_path(self):
        prompt = smoke.make_prompt(self.case)
        self.assertTrue(prompt.startswith("$trurl"))
        self.assertNotIn(self.case["installed"], prompt)
        self.assertIn("explicitly read", prompt)
        self.assertIn(self.case["workspace"], prompt)

    def test_prompt_command_paths_are_shell_quoted_without_expanding_metacharacters(self):
        workspace = "/tmp/space here $(do_not_run) `also_no` \"double\" 'single'"
        prompt = smoke.make_prompt(dict(self.case, workspace=workspace))
        commands = {line[:2]: shlex.split(line[3:]) for line in prompt.splitlines() if line.startswith(("1. ", "2. ", "3. "))}
        self.assertEqual(commands["1."][2], workspace)
        self.assertEqual(commands["2."][2], str(Path(workspace) / "model/graph.json"))
        self.assertEqual(commands["3."][2], str(Path(workspace) / "model/graph.json"))
        self.assertEqual(commands["3."][4], str(Path(workspace) / "model/profile.json"))
        self.assertIn(shlex.quote(workspace), prompt)

    def test_read_paths_resolve_installed_skill_and_ignore_unrelated_files(self):
        absolute = str(Path(self.case["installed"]) / "SKILL.md")
        self.assertTrue(smoke.trace_checks(self.case, [("Read", {"file_path": absolute})])["installed_skill_read_in_tool_trace"])
        self.assertFalse(smoke.trace_checks(self.case, [("Read", {"file_path": absolute + ".other"})])["installed_skill_read_in_tool_trace"])
        relative = "../home/.agents/skills/trurl/SKILL.md"
        self.assertTrue(smoke.trace_checks(self.case, [("read", {"path": relative})])["installed_skill_read_in_tool_trace"])

    def test_commands_are_real_host_invocations_with_no_credential_arguments(self):
        for agent in smoke.AGENTS:
            with self.subTest(agent=agent):
                case = dict(self.case, agent=agent)
                argv = smoke.host_command(agent, "/fixture/bin/host", case, "fixture-model")
                self.assertEqual(argv[0], "/fixture/bin/host")
                self.assertIn("--model", argv)
                self.assertNotIn("--api-key", argv)
                if agent == "claude-code":
                    self.assertIn("--bare", argv)
                    self.assertEqual(argv[-2], "-p")
                elif agent == "pi":
                    self.assertEqual(argv[1:5], ["--mode", "json", "--print", "--no-session"])
                    for flag in ("--no-extensions", "--no-mcp", "--no-prompt-templates", "--no-themes",
                                 "--no-context-files", "--no-approve"):
                        self.assertIn(flag, argv)
                    self.assertEqual(argv[argv.index("--tools") + 1], "read,bash,write")
                    self.assertNotIn("--skill", argv)
                    self.assertNotIn("--no-skills", argv)
                    self.assertTrue(argv[-1].startswith("/skill:trurl Run "))
                    self.assertNotIn(case["installed"], argv[-1])

    def test_removed_hosts_are_rejected_before_preparation_or_execution(self):
        for agent in ("hermes", "unsupported"):
            with self.subTest(agent=agent), tempfile.TemporaryDirectory() as directory:
                destination = Path(directory) / agent
                with self.assertRaisesRegex(ValueError, "Unsupported host"):
                    smoke.prepare_case(agent, destination, ROOT)
                self.assertFalse(destination.exists())
                with patch.object(smoke, "prepare_case") as prepare, patch.object(smoke, "execute") as execute:
                    with self.assertRaisesRegex(ValueError, "Unsupported host"):
                        smoke.run_host(agent, destination, ROOT, live=True)
                prepare.assert_not_called()
                execute.assert_not_called()
                with self.assertRaisesRegex(ValueError, "Unsupported host"):
                    smoke.host_command(agent, "/fixture/bin/host", dict(self.case, agent=agent))

    def test_offline_packaging_does_not_invoke_host_or_claim_live_pass(self):
        with patch.object(smoke, "prepare_case", return_value=self.case), patch.object(smoke, "execute") as execute:
            result = smoke.run_host("codex", self.case["directory"], ROOT)
        execute.assert_not_called()
        self.assertEqual(result["status"], "packaging_passed")
        self.assertEqual(result["live_status"], "not_run")
        self.assertEqual(result["evidence_level"], "packaging_only")
        self.assertEqual(result["bundle_sha256"], self.case["bundle_sha256"])

    def test_missing_host_and_auth_failure_are_blocked(self):
        with patch.object(smoke, "prepare_case", return_value=self.case), patch.object(smoke.shutil, "which", return_value=None):
            missing = smoke.run_host("codex", self.case["directory"], ROOT, live=True)
        self.assertEqual(missing["status"], "blocked")
        version = {"stdout": "synthetic-host-version", "stderr": "", "returncode": 0, "timed_out": False, "duration_seconds": .01}
        auth = dict(version, stdout="Authentication required; please log in", returncode=1)
        with patch.object(smoke, "prepare_case", return_value=self.case), patch.object(smoke, "execute", side_effect=[version, auth]):
            result = smoke.run_host("codex", self.case["directory"], ROOT, live=True, executable="/synthetic/host")
        self.assertEqual(result["status"], "blocked")
        self.assertEqual(result["reason"], "provider_authentication_required_or_failed")

    def test_zero_exit_with_no_evidence_is_failure(self):
        empty = {"stdout": "All done", "stderr": "", "returncode": 0, "timed_out": False, "duration_seconds": .01}
        with patch.object(smoke, "prepare_case", return_value=self.case), patch.object(smoke, "execute", return_value=empty):
            result = smoke.run_host("codex", self.case["directory"], ROOT, live=True, executable="/synthetic/host")
        self.assertEqual(result["status"], "failed")

    def test_pi_success_requires_skill_read_all_helpers_and_terminal_success(self):
        self.populate_artifacts()
        events = completed_events("pi", "read", {"path": str(Path(self.case["installed"]) / "SKILL.md")}, "read")
        for operation, arguments in self.case["commands"].items():
            command = shlex.join([self.case["python_executable"], self.case["runtime"]] + arguments)
            events += completed_events("pi", "bash", {"command": command}, operation)
        self.assertTrue(smoke.validate_live(self.case, "pi", jsonl(events + pi_finished()), 0)["passed"])
        missing_terminal = smoke.validate_live(self.case, "pi", jsonl(events), 0)
        self.assertIn("native_run_completion_not_proven", missing_terminal["errors"])
        failed_terminal = smoke.validate_live(self.case, "pi", jsonl(events + pi_finished("error")), 0)
        self.assertFalse(failed_terminal["passed"])
        self.assertFalse(smoke.validate_live(self.case, "pi", jsonl(events[2:] + pi_finished()), 0)["passed"])

    def test_pi_unavailable_cli_and_credentials_remain_blocked(self):
        case = dict(self.case, agent="pi")
        with patch.object(smoke, "prepare_case", return_value=case), patch.object(smoke.shutil, "which", return_value=None):
            missing = smoke.run_host("pi", case["directory"], ROOT, live=True)
        self.assertEqual(missing["reason"], "host_cli_not_found")
        result = {"stdout": "", "stderr": "No API key found for openai", "returncode": 1,
                  "timed_out": False, "duration_seconds": .01}
        with patch.object(smoke, "prepare_case", return_value=case), patch.object(smoke, "execute", return_value=result):
            blocked = smoke.run_host("pi", case["directory"], ROOT, live=True, executable="/synthetic/pi")
        self.assertEqual(blocked["status"], "blocked")
        self.assertEqual(blocked["reason"], "provider_authentication_required_or_failed")

    def test_codex_native_auth_is_opt_in_and_only_overrides_native_home(self):
        empty = {"stdout": "Authentication required", "stderr": "", "returncode": 1, "timed_out": False, "duration_seconds": .01}
        for use_existing in (False, True):
            with self.subTest(use_existing=use_existing), tempfile.TemporaryDirectory() as auth_home:
                with patch.object(smoke, "prepare_case", return_value=self.case), patch.object(smoke, "execute", return_value=empty) as execute:
                    result = smoke.run_host("codex", self.case["directory"], ROOT, live=True, executable="/synthetic/host",
                                            codex_auth_home=auth_home if use_existing else None)
                env = execute.call_args_list[-1].args[2]
                expected = str(Path(auth_home).resolve()) if use_existing else str(Path(self.case["home"]) / ".codex")
                self.assertEqual(env["CODEX_HOME"], expected)
                self.assertEqual(env["HOME"], self.case["home"])
                self.assertEqual(result["auth_home_isolated"], not use_existing)
                self.assertEqual(result["auth_scope"], "existing_codex_native_auth_state" if use_existing else "isolated_home_provider_environment_only")
                self.assertIn("--ignore-user-config", result["argv"])
                self.assertIn("--ignore-rules", result["argv"])
                self.assertEqual(list(Path(auth_home).iterdir()), [])

    def test_codex_auth_override_rejects_wrong_host_offline_and_missing_directory(self):
        for agent, live, directory in [("claude-code", True, self.case["home"]), ("codex", False, self.case["home"]),
                                       ("codex", True, str(Path(self.case["home"]) / "missing-auth"))]:
            with self.subTest(agent=agent, live=live), patch.object(smoke, "prepare_case") as prepare:
                with self.assertRaises(ValueError):
                    smoke.run_host(agent, "/unused", ROOT, live=live, codex_auth_home=directory)
                prepare.assert_not_called()


if __name__ == "__main__":
    unittest.main()
