"""Post-research completion is checked against the actual selected candidate pool."""
from contextlib import redirect_stdout, redirect_stderr
import io
import json
from pathlib import Path
import runpy
import subprocess
import sys
import tempfile
import unittest

SCRIPTS = Path(__file__).resolve().parents[1] / "skills/trurl/scripts"
GRAPH = runpy.run_path(str(SCRIPTS / "graph_updates.py"))
CURATION = runpy.run_path(str(SCRIPTS / "curation.py"))
DIVERSITY = runpy.run_path(str(SCRIPTS / "diversity.py"))


class GraphUpdateWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        CURATION["initialize"](self.root)
        self.profile = json.loads((self.root / "model/profile.json").read_text())
        self.plan = CURATION["make_plan"](self.profile, scope="focused")
        self.research = []
        self.write("plan.json", self.plan)
        self.write("candidates.json", self.research)

    def write(self, name, value):
        (self.root / name).write_text(json.dumps(value), encoding="utf-8")

    def select(self, rooted=True, batch="fixture"):
        args = ["select", "--plan", str(self.root / "plan.json"), "--candidates",
                str(self.root / "candidates.json"), "--count", "1"]
        if rooted:
            args += ["--root", str(self.root)]
        if batch:
            args += ["--batch-id", batch]
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            try:
                status = DIVERSITY["main"](args)
            except SystemExit as error:
                status = error.code
        return status, out.getvalue(), err.getvalue()

    def complete(self):
        review = GRAPH["update_plan"](self.root, self.research, "fixture")
        return GRAPH["complete_update"](self.root, self.research, review,
                                        reason="No source-supported content facts in this fixture.")

    def test_all_generated_modes_require_post_research_check(self):
        for mode in ("personal", "surprise", "wildcard", "open"):
            for scope in ("broad", "focused"):
                plan = CURATION["make_plan"](self.profile, mode=mode, scope=scope, seed=19)
                self.assertTrue(plan["graph_update_required"])

    def test_selection_requires_root_batch_and_actual_completion(self):
        self.assertIn("pass --root and --batch-id", self.select(rooted=False)[2])
        self.assertIn("pass --root and --batch-id", self.select(batch=None)[2])
        self.assertIn("graph update is pending", self.select()[2])
        self.complete()
        status, output, error = self.select()
        self.assertEqual(status, 0, error)
        result = json.loads(output)
        self.assertTrue(result["graph_update"]["completed"])
        self.assertEqual(result["graph_update"]["receipt"]["outcome"], "no_supported_changes")
        self.assertIn("graph update is pending", self.select(batch="another-batch")[2])

    def test_changed_research_or_graph_makes_completion_stale(self):
        self.complete()
        self.write("candidates.json", [{"id": "new", "title": "New source to review"}])
        self.assertIn("graph update is pending", self.select()[2])
        self.write("candidates.json", [])
        graph_path = self.root / "model/graph.json"
        graph = json.loads(graph_path.read_text())
        graph["nodes"].append({"id": "new-topic", "type": "topic", "label": "Synthetic topic"})
        graph_path.write_text(json.dumps(graph))
        self.assertIn("graph update is pending", self.select()[2])

    def test_exploration_precedes_graph_updates(self):
        output = io.StringIO()
        with redirect_stdout(output):
            status = DIVERSITY["main"](["explore", "--root", str(self.root), "--profile",
                str(self.root / "model/profile.json"), "--plan", str(self.root / "plan.json"), "--count", "1"])
        self.assertEqual(status, 0)
        self.assertNotIn("graph_update", json.loads(output.getvalue()))
        self.assertFalse((self.root / "model/graph-maintenance.json").exists())

    def test_historical_plan_remains_compatible_without_claiming_completion(self):
        self.plan.pop("graph_update_required")
        self.write("plan.json", self.plan)
        status, output, error = self.select(rooted=False, batch=None)
        self.assertEqual(status, 0, error)
        self.assertNotIn("graph_update", json.loads(output))

    def test_three_installed_hosts_run_update_workflow_outside_repository(self):
        for host in ("codex", "claude-code", "pi"):
            with self.subTest(host=host):
                install = self.root / ("installed-" + host)
                CURATION["install_skill"](destination=install, agent=host)
                runtime = install / "scripts/curation.py"
                base = [sys.executable, str(runtime)]
                planned = subprocess.run(base + ["graph-update-plan", "--root", str(self.root),
                    "--research", str(self.root / "candidates.json"), "--batch-id", host],
                    cwd=install, capture_output=True, text=True, check=True)
                self.write("review.json", json.loads(planned.stdout))
                saved = subprocess.run(base + ["graph-update", "--root", str(self.root),
                    "--research", str(self.root / "candidates.json"), "--review", str(self.root / "review.json"),
                    "--reason", "No source-supported relations in this fixture."], cwd=install,
                    capture_output=True, text=True)
                self.assertEqual(saved.returncode, 0, saved.stderr)
                checked = subprocess.run(base + ["graph-update-check", "--root", str(self.root),
                    "--research", str(self.root / "candidates.json"), "--batch-id", host],
                    cwd=install, capture_output=True, text=True, check=True)
                self.assertTrue(json.loads(checked.stdout)["completed"])

    def test_receipts_are_excluded_from_installed_skill(self):
        source = self.root / "source"
        CURATION["install_skill"](destination=source)
        for name in ("graph-maintenance.json", "hypothesis-maintenance.json"):
            (source / name).write_text('{"private":"receipt"}')
        target = self.root / "clean-install"
        CURATION["install_skill"](destination=target, source=source)
        self.assertFalse((target / "graph-maintenance.json").exists())
        self.assertFalse((target / "hypothesis-maintenance.json").exists())


if __name__ == "__main__":
    unittest.main()
