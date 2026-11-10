"""Default availability checks and optional strict native-integration checks."""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("host_evidence", ROOT / "scripts/check_host_evidence.py")
gate = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gate)


class HostEvidenceTests(unittest.TestCase):
    def report(self):
        smoke = gate.smoke_module()
        fingerprint = smoke.bundle_fingerprint(ROOT / "skills/trurl")
        return {"mode": "live", "results": [
            {"agent": host, "mode": "live", "evidence_level": "authenticated_host",
             "evidence_protocol": smoke.EVIDENCE_PROTOCOL, "validator_sha256": smoke.digest(Path(smoke.__file__)),
             "status": "passed", "live_status": "passed", "bundle_sha256": fingerprint,
             "returncode": 0, "synthetic_inputs_only": True, "host_version": "synthetic-unit-fixture",
             "validation": {"passed": True, "errors": [], "inputs_unchanged": True,
                            "checks": {"installed_skill_read_in_tool_trace": True,
                                       "installed_helpers_in_tool_trace": ["frontier", "graph-check", "weights"],
                                       "native_tool_events": 4, "native_run_completed": True}}}
            for host in smoke.AGENTS]}

    def packaging_report(self):
        report = self.report()
        report["mode"] = "packaging_only"
        for result in report["results"]:
            for key in ("returncode", "host_version", "validation"):
                result.pop(key)
            result.update(mode="packaging_only", evidence_level="packaging_only", status="packaging_passed",
                          packaging_status="passed", live_status="not_run")
        return report

    def evaluate(self, report, require_live=False):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "summary.json"
            path.write_text(json.dumps(report))
            return gate.review(ROOT, [path], require_live=require_live)

    def test_complete_current_live_evidence_passes(self):
        self.assertTrue(self.evaluate(self.report(), require_live=True)["ready_to_publish"])

    def test_packaging_results_cannot_unlock_strict_native_scope(self):
        report = self.report()
        report["mode"] = "packaging_only"
        self.assertFalse(self.evaluate(report, require_live=True)["ready_to_publish"])

    def test_missing_host_blocks_publication(self):
        report = self.report(); report["results"].pop()
        result = self.evaluate(report, require_live=True)
        self.assertEqual(result["missing_live_passes"], ["pi"])
        self.assertFalse(result["ready_to_publish"])

    def test_old_bundle_pass_is_stale(self):
        report = self.report(); report["results"][0]["bundle_sha256"] = "old-bundle"
        self.assertEqual(self.evaluate(report, require_live=True)["missing_live_passes"], ["codex"])

    def test_false_pass_without_execution_or_integrity_fails(self):
        for field, value in [("installed_skill_read_in_tool_trace", False),
                             ("installed_helpers_in_tool_trace", ["weights"]), ("native_tool_events", 0)]:
            with self.subTest(field=field):
                report = self.report(); report["results"][0]["validation"]["checks"][field] = value
                self.assertFalse(self.evaluate(report, require_live=True)["ready_to_publish"])
        for field, value in [("inputs_unchanged", False), ("errors", ["mismatch"])]:
            report = self.report(); report["results"][0]["validation"][field] = value
            self.assertFalse(self.evaluate(report, require_live=True)["ready_to_publish"])

    def test_blocked_authentication_does_not_count_as_pass(self):
        report = self.report(); report["results"][1].update(status="blocked", live_status="blocked")
        self.assertFalse(self.evaluate(report, require_live=True)["ready_to_publish"])

    def test_malformed_report_is_an_explicit_error(self):
        result = self.evaluate({"results": "bad"}, require_live=True)
        self.assertTrue(result["errors"])
        self.assertFalse(result["ready_to_publish"])

    def test_malformed_nested_validation_cannot_pass(self):
        for value in (None, [], "claimed pass"):
            report = self.report(); report["results"][0]["validation"]["checks"] = value
            self.assertFalse(self.evaluate(report, require_live=True)["ready_to_publish"])

    def test_boolean_execution_counts_are_not_numeric_evidence(self):
        report = self.report(); report["results"][0]["returncode"] = False
        self.assertFalse(self.evaluate(report, require_live=True)["ready_to_publish"])
        report = self.report(); report["results"][0]["validation"]["checks"]["native_tool_events"] = True
        self.assertFalse(self.evaluate(report, require_live=True)["ready_to_publish"])

    def test_missing_current_bundle_fails_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            result = gate.review(Path(directory), [], require_live=True)
            self.assertFalse(result["ready_to_publish"])
            self.assertTrue(result["errors"])

    def test_old_validation_protocol_cannot_unlock_release(self):
        for field, value in [("evidence_protocol", "old-substring-validation"), ("validator_sha256", "old-code")]:
            report = self.report(); report["results"][0][field] = value
            self.assertFalse(self.evaluate(report, require_live=True)["ready_to_publish"])

    def test_unhashable_host_name_is_an_explicit_error(self):
        report = self.report(); report["results"][0]["agent"] = []
        self.assertTrue(self.evaluate(report, require_live=True)["errors"])

    def test_default_accepts_all_packaging_passes_without_native_claims(self):
        result = self.evaluate(self.packaging_report())
        self.assertTrue(result["ready_to_publish"])
        self.assertEqual(result["required_scope"], "packaging_only")
        self.assertEqual(result["missing_host_passes"], [])
        self.assertNotIn("missing_live_passes", result)
        self.assertEqual({value["accepted_scope"] for value in result["passed_hosts"].values()}, {"packaging_only"})
        self.assertTrue(all("host_version" not in value for value in result["passed_hosts"].values()))

    def test_default_packaging_evidence_needs_no_host_cli_or_credentials(self):
        smoke = gate.smoke_module()
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {"PATH": ""}, clear=True), \
                patch.object(smoke, "host_command", side_effect=AssertionError("native host must not run")):
            reports = [smoke.run_host(agent, Path(directory) / agent, ROOT) for agent in smoke.AGENTS]
            self.assertTrue(all(report["status"] == "packaging_passed" for report in reports), reports)
            result = self.evaluate({"mode": "packaging_only", "results": reports})
            self.assertTrue(result["ready_to_publish"])
            self.assertEqual(result["required_scope"], "packaging_only")

    def test_default_requires_each_host_and_current_packaging_proof(self):
        incomplete = self.packaging_report()
        incomplete["results"].pop()
        result = self.evaluate(incomplete)
        self.assertFalse(result["ready_to_publish"])
        self.assertEqual(result["missing_host_passes"], ["pi"])
        for key, value in (("bundle_sha256", "old-bundle"), ("validator_sha256", "old-validator"),
                           ("evidence_protocol", "old-protocol"), ("packaging_status", "failed"),
                           ("synthetic_inputs_only", False), ("mode", "live")):
            report = self.packaging_report()
            report["results"][0][key] = value
            with self.subTest(key=key):
                self.assertFalse(self.evaluate(report)["ready_to_publish"])

    def test_default_can_combine_stronger_live_and_packaging_evidence(self):
        packaging, live = self.packaging_report(), self.report()
        packaging["results"] = packaging["results"][1:]
        live["results"] = live["results"][:1]
        with tempfile.TemporaryDirectory() as directory:
            paths = []
            for name, report in (("packaging", packaging), ("live", live)):
                path = Path(directory) / (name + ".json")
                path.write_text(json.dumps(report))
                paths.append(path)
            result = gate.review(ROOT, paths)
            self.assertTrue(result["ready_to_publish"])
            self.assertEqual(result["passed_hosts"]["codex"]["accepted_scope"], "authenticated_host")
            self.assertEqual(result["passed_hosts"]["claude-code"]["accepted_scope"], "packaging_only")
            strict = gate.review(ROOT, paths, require_live=True)
            self.assertFalse(strict["ready_to_publish"])
            self.assertEqual(strict["missing_live_passes"], ["claude-code", "pi"])

    def test_strict_mode_keeps_packaging_insufficient(self):
        result = self.evaluate(self.packaging_report(), require_live=True)
        self.assertFalse(result["ready_to_publish"])
        self.assertEqual(result["required_scope"], "authenticated_host")
        self.assertEqual(result["missing_live_passes"], ["codex", "claude-code", "pi"])

    def test_pi_requires_completed_native_run_even_with_successful_tool_checks(self):
        for value in (None, False, "true", 1):
            report = self.report()
            pi = next(result for result in report["results"] if result["agent"] == "pi")
            pi["validation"]["checks"]["native_run_completed"] = value
            result = self.evaluate(report, require_live=True)
            self.assertEqual(result["missing_live_passes"], ["pi"])
            self.assertFalse(result["ready_to_publish"])

    def test_default_fails_closed_for_missing_bundle_and_malformed_host(self):
        with tempfile.TemporaryDirectory() as directory:
            result = gate.review(Path(directory), [])
            self.assertFalse(result["ready_to_publish"])
            self.assertEqual(result["required_scope"], "packaging_only")
            self.assertNotIn("missing_live_passes", result)
        report = self.packaging_report()
        report["results"][0]["agent"] = []
        result = self.evaluate(report)
        self.assertTrue(result["errors"])
        self.assertFalse(result["ready_to_publish"])

    def test_cli_default_and_opt_in_strict_scope(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "summary.json"
            path.write_text(json.dumps(self.packaging_report()))
            command = [sys.executable, str(ROOT / "scripts/check_host_evidence.py"), "--root", str(ROOT), "--evidence", str(path)]
            default = subprocess.run(command, capture_output=True, text=True)
            strict = subprocess.run(command + ["--require-live"], capture_output=True, text=True)
            self.assertEqual(default.returncode, 0, default.stderr)
            self.assertEqual(json.loads(default.stdout)["required_scope"], "packaging_only")
            self.assertEqual(strict.returncode, 1, strict.stderr)
            self.assertEqual(json.loads(strict.stdout)["required_scope"], "authenticated_host")


if __name__ == "__main__":
    unittest.main()
