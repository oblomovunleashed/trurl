"""A broad batch cannot bypass an outstanding review in the active CLI workflow."""
from contextlib import redirect_stdout, redirect_stderr
import io
import json
from pathlib import Path
import runpy
import tempfile
import unittest


SCRIPTS = Path(__file__).resolve().parents[1] / "skills/trurl/scripts"
HYPOTHESES = runpy.run_path(str(SCRIPTS / "hypotheses.py"))
DIVERSITY = runpy.run_path(str(SCRIPTS / "diversity.py"))
CURATION = runpy.run_path(str(SCRIPTS / "curation.py"))
GRAPH_UPDATES = runpy.run_path(str(SCRIPTS / "graph_updates.py"))


class MaintenanceWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.model = self.root / "model"
        self.model.mkdir()
        self.profile = CURATION["generic_profile"]("Synthetic person")
        self.profile["interests"] = [
            {"id": "a", "topic": "Synthetic research", "kind": "explicit", "source_provenance": ["s"]},
            {"id": "b", "topic": "Synthetic history", "kind": "explicit", "source_provenance": ["s"]}]
        self.profile["provenance"] = [{"id": "s", "kind": "user_statement", "locator": "fixture://statement"}]
        self.write(self.model / "profile.json", self.profile)
        self.plan = CURATION["make_plan"](self.profile, scope="broad", seed=7)
        self.write(self.root / "plan.json", self.plan)

    def write(self, path, value):
        path.write_text(json.dumps(value), encoding="utf-8")

    def run_cli(self, command, rooted=True, extra=()):
        argv = [command, "--plan", str(self.root / "plan.json"), "--count", "4", "--seed", "7"]
        if command == "explore":
            argv += ["--profile", str(self.model / "profile.json")]
        else:
            self.write(self.root / "candidates.json", [])
            argv += ["--candidates", str(self.root / "candidates.json"), "--batch-id", "synthetic-batch"]
        if rooted:
            argv += ["--root", str(self.root)]
        stdout, stderr = io.StringIO(), io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            try:
                status = DIVERSITY["main"](argv + list(extra))
            except SystemExit as error:
                status = error.code
        return status, stdout.getvalue(), stderr.getvalue()

    def complete(self):
        review = HYPOTHESES["maintenance_plan"](self.root, self.plan)
        HYPOTHESES["complete_maintenance"](
            self.root, review, "no_proposal", "The available connections are too speculative.")

    def complete_graph_research(self):
        graph_review = GRAPH_UPDATES["update_plan"](self.root, [], "synthetic-batch")
        GRAPH_UPDATES["complete_update"](
            self.root, [], graph_review, reason="No researched content relationships in this fixture.")

    def test_generated_broad_plan_requires_root_at_research_and_selection(self):
        self.assertTrue(self.plan["hypothesis_maintenance_required"])
        for command in ("explore", "select"):
            status, stdout, stderr = self.run_cli(command, rooted=False)
            self.assertEqual(status, 2)
            self.assertEqual(stdout, "")
            self.assertIn("pass --root", stderr)

    def test_missing_and_stale_completion_stop_research_and_selection(self):
        for command in ("explore", "select"):
            self.assertIn("maintenance is due", self.run_cli(command)[2])
        self.complete()
        self.profile["interests"][0]["topic"] = "Changed synthetic research"
        self.write(self.model / "profile.json", self.profile)
        for command in ("explore", "select"):
            self.assertIn("anchors_changed", self.run_cli(command)[2])

    def test_completed_review_is_in_both_traces_without_reproposing(self):
        self.complete()
        personal_before = {p.name: p.read_bytes() for p in self.model.iterdir()}
        # Discovery represents interests before research completes its graph update.
        status, stdout, stderr = self.run_cli("explore")
        self.assertEqual(status, 0, stderr)
        self.assertEqual(json.loads(stdout)["graph_anchors"]["counts"]["nodes_added"], 2)
        self.assertEqual(personal_before, {name: (self.model / name).read_bytes() for name in personal_before})
        self.complete_graph_research()
        before = {p.name: p.read_bytes() for p in self.model.iterdir()}
        for command in ("explore", "select"):
            status, stdout, stderr = self.run_cli(command)
            self.assertEqual(status, 0, stderr)
            result = json.loads(stdout)
            self.assertTrue(result["hypothesis_maintenance"]["completed"])
            self.assertEqual(result["hypothesis_maintenance"]["receipt"]["outcome"], "no_proposal")
            self.assertFalse(any(b.get("hypothesis_action") == "propose" for b in result.get("briefs", [])))
        self.assertEqual(before, {p.name: p.read_bytes() for p in self.model.iterdir()})

    def test_receipt_cannot_authorize_another_profile_or_evidence_ledger(self):
        self.complete()
        self.complete_graph_research()
        self.write(self.root / "other.json", self.profile)
        for option in ("--profile", "--feedback", "--history"):
            status, unused, stderr = self.run_cli("explore", extra=(option, str(self.root / "other.json")))
            self.assertEqual(status, 2)
            self.assertIn("must use the same model/", stderr)
        self.assertIn("must use the same model/", self.run_cli("select", extra=("--history", str(self.root / "other.json")))[2])

    def test_wildcard_plans_do_not_require_maintenance(self):
        for options in ({"scope": "focused", "mode": "wildcard", "seed": 5},
                        {"scope": "broad", "mode": "wildcard", "seed": 5}):
            plan = CURATION["make_plan"](self.profile, **options)
            self.assertFalse(plan["hypothesis_maintenance_required"])
            self.write(self.root / "plan.json", plan)
            self.assertEqual(self.run_cli("explore", rooted=False)[0], 0)

    def test_focused_plan_cannot_skip_a_pending_profile_review_by_omitting_root(self):
        self.plan = CURATION["make_plan"](self.profile, scope="focused", seed=7)
        self.write(self.root / "plan.json", self.plan)
        self.assertTrue(self.plan["hypothesis_maintenance_required"])
        for command in ("explore", "select"):
            self.assertIn("--root", self.run_cli(command, rooted=False)[2])
            self.assertIn("maintenance is due", self.run_cli(command)[2])
        review = HYPOTHESES["maintenance_plan"](self.root, self.plan)
        HYPOTHESES["complete_maintenance"](self.root, review, "no_proposal",
                                          "The original interests are useful independently; no sound shared proposal.")
        self.assertEqual(self.run_cli("explore")[0], 0)

    def test_untried_hypothesis_gets_existing_adjacent_opportunity(self):
        draft = HYPOTHESES["snapshot"](self.root)
        draft["taste_hypotheses"] = [
            {"id": key, "topic": "Synthetic direction " + key, "reason": "Plausible connection to the original.",
             "anchor_ids": ["a"], "status": "testing", "evidence": []} for key in ("old", "new")]
        HYPOTHESES["save"](self.root, draft)
        profile = json.loads((self.model / "profile.json").read_text())
        history = [{"id": "r", "hypothesis_id": "old", "title": "An earlier delivered work"}]
        for seed in range(10):
            result = DIVERSITY["explore"](self.plan, profile, history=history, feedback=[], seed=seed, count=8)
            probes = [b for b in result["briefs"] if b.get("hypothesis_id")]
            self.assertEqual([b["hypothesis_id"] for b in probes], ["new"])
            self.assertEqual(probes[0]["lane"], "adjacent")
            self.assertFalse(result["profile_changed"])


if __name__ == "__main__":
    unittest.main()
