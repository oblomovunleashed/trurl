"""Exercise the one-call request helpers with synthetic state."""
from contextlib import redirect_stdout, redirect_stderr
import io
import json
import os
from pathlib import Path
import runpy
import shutil
import subprocess
import sys
import tempfile
import unittest


REPOSITORY = Path(__file__).resolve().parents[1]
SCRIPTS = REPOSITORY / "skills/trurl/scripts"
WORKFLOW = runpy.run_path(str(SCRIPTS / "workflow.py"))
CURATION = runpy.run_path(str(SCRIPTS / "curation.py"))
CONTEXT = runpy.run_path(str(SCRIPTS / "context.py"))
HYPOTHESES = runpy.run_path(str(SCRIPTS / "hypotheses.py"))
AXES = ("depth", "novelty", "relevance", "surprise", "perspective_change", "entertainment")


def candidate(identifier, scores=(4, 3, 4, 3, 3, 3), medium="book", **extra):
    url = "https://example.org/works/" + identifier
    return dict({"id": identifier, "title": "Synthetic work " + identifier, "creator": "Creator " + identifier,
                 "canonical_url": url, "medium": medium, "lane": "familiar", "constraints_passed": True,
                 "credibility_passed": True, "topics": ["topic " + identifier],
                 "verification": {"checked_at": "2026-11-10T10:00:00Z", "urls": [url], "limitations": []},
                 "rationale": "Synthetic rationale.", "scores": dict(zip(AXES, scores))}, **extra)


def cli(argv):
    """Run the public entry point in-process and return status, parsed stdout and stderr."""
    stdout, stderr = io.StringIO(), io.StringIO()
    with redirect_stdout(stdout), redirect_stderr(stderr):
        try:
            status = CURATION["main"](list(argv))
        except SystemExit as error:
            status = error.code
    text = stdout.getvalue()
    return status, json.loads(text) if text.strip().startswith("{") else text, stderr.getvalue()


class RequestHelperTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name).resolve()
        self.root = self.base / "home" / "Trurl"
        CURATION["initialize"](self.root)
        shutil.copyfile(REPOSITORY / "examples/profile.demo.json", self.root / "model/profile.json")
        self.model = self.root / "model"
        self.work = self.base / "request"
        review = HYPOTHESES["maintenance_plan"](self.root, event="onboarding")
        if review["review_due"]:
            HYPOTHESES["complete_maintenance"](
                self.root, review, "no_proposal", "Fixture onboarding was reviewed; keep the supplied interests independent.")

    def state(self):
        return {path.name: path.read_bytes() for path in self.model.iterdir()}

    def lines(self, name):
        return [json.loads(line) for line in (self.model / name).read_text(encoding="utf-8").splitlines() if line]

    def begin(self, **options):
        return WORKFLOW["start"](root=self.root, request="Three things to read before bed", count=3, seed=7,
                                 discovery_seed=11, out=self.work, **options)

    def propose_hypothesis(self):
        profile = CURATION["generic_profile"]("Synthetic person")
        profile["interests"] = [{"id": "a", "topic": "Synthetic research", "kind": "explicit",
                                 "source_provenance": ["s"]}]
        profile["provenance"] = [{"id": "s", "kind": "user_statement", "locator": "fixture://statement"}]
        (self.model / "profile.json").write_text(json.dumps(profile), encoding="utf-8")
        draft = HYPOTHESES["snapshot"](self.root)
        draft["taste_hypotheses"] = [{"id": "h", "topic": "Synthetic research history",
                                     "reason": "A plausible direction from the stated research interest.",
                                     "anchor_ids": ["a"], "status": "testing", "evidence": []}]
        HYPOTHESES["save"](self.root, draft)

    def add_original_interests(self, count=28):
        profile = CURATION["generic_profile"]("Synthetic person")
        profile["interests"] = [
            {"id": "interest-" + str(i), "topic": "Synthetic topic " + str(i),
             "kind": "explicit", "scope": "persistent", "source_provenance": ["setup"]}
            for i in range(count)]
        profile["provenance"] = [{"id": "setup", "kind": "user_statement",
                                  "locator": "fixture://synthetic-onboarding"}]
        (self.model / "profile.json").write_text(json.dumps(profile), encoding="utf-8")
        (self.model / "hypothesis-maintenance.json").unlink(missing_ok=True)

    def select(self, started, candidates, count=3):
        """Research, complete the graph step in one call and select, as a host would."""
        work = Path(started["workdir"])
        (work / "candidates.json").write_text(json.dumps(candidates), encoding="utf-8")
        common = ["--root", str(self.root), "--batch-id", started["batch_id"]]
        status, update, error = cli(["graph-update", "--research", str(work / "candidates.json"),
                                     "--reason", "Synthetic sources support no content relationships."] + common)
        self.assertEqual(status, 0, error)
        status, selection, error = cli(["select", "--plan", started["files"]["plan"], "--candidates",
                                        str(work / "candidates.json"), "--count", str(count)] + common)
        self.assertEqual(status, 0, error)
        (work / "selection.json").write_text(json.dumps(selection), encoding="utf-8")
        return update, selection

    def test_start_returns_context_plan_and_briefs_in_one_call(self):
        before = self.state()
        started = self.begin()
        self.assertEqual(started["status"], "ready")
        self.assertEqual(started["root"], str(self.root))
        self.assertTrue(started["batch_id"].startswith("batch-"))
        self.assertEqual(json.loads(Path(started["files"]["plan"]).read_text(encoding="utf-8")), started["plan"])
        self.assertFalse(started["plan"]["baseline_changed"])
        self.assertEqual(started["plan"]["constraints"]["request"], "Three things to read before bed")
        self.assertEqual(len(started["exploration"]["briefs"]), 3)
        self.assertEqual(started["context"]["brief"]["status"], "missing")
        self.assertEqual([item["id"] for item in started["context"]["interests"]], ["synthetic-interest-representation"])
        self.assertFalse(started["hypothesis_maintenance"]["review_due"])
        self.assertEqual(json.loads((self.work / "start.json").read_text(encoding="utf-8")), started)
        # Preferences and ledgers are untouched; rooted discovery may only add anchor representation.
        after = self.state()
        self.assertEqual({name: data for name, data in before.items() if name != "graph.json"},
                         {name: after[name] for name in before if name != "graph.json"})

    def test_start_keeps_one_plan_per_working_folder_and_stays_out_of_the_skill(self):
        self.begin()
        with self.assertRaisesRegex(ValueError, "already holds a request"):
            self.begin()
        with self.assertRaisesRegex(ValueError, "outside the installed skill"):
            WORKFLOW["start"](root=self.root, request="x", out=SCRIPTS.parent / "scratch")
        self.assertFalse((SCRIPTS.parent / "scratch").exists())

    def test_start_without_a_model_creates_nothing(self):
        home = self.base / "empty-home"
        home.mkdir()
        environment = {key: value for key, value in os.environ.items()
                       if key not in {"TRURL_ROOT", "CURATION_ROOT", "XDG_CONFIG_HOME"}}
        environment.update(HOME=str(home), PYTHONDONTWRITEBYTECODE="1")
        result = subprocess.run([sys.executable, str(SCRIPTS / "curation.py"), "start", "--request", "A film"],
                                cwd=str(home), capture_output=True, text=True, env=environment)
        self.assertEqual(result.returncode, 0, result.stderr)
        output = json.loads(result.stdout)
        self.assertEqual(output["status"], "no_model")
        self.assertEqual(output["root_source"], "default")
        self.assertIn("onboarding", output["next"][0])
        self.assertEqual(list(home.iterdir()), [])

    def test_scheduled_start_stops_while_weekly_delivery_is_disabled(self):
        stopped = self.begin(context="weekly")
        self.assertEqual(stopped["status"], "weekly_delivery_disabled")
        self.assertNotIn("plan", stopped)
        self.assertFalse(self.work.exists())
        profile = json.loads((self.model / "profile.json").read_text(encoding="utf-8"))
        profile["delivery"]["weekly"]["enabled"] = True
        (self.model / "profile.json").write_text(json.dumps(profile), encoding="utf-8")
        self.assertEqual(self.begin(context="weekly")["plan"]["context"], "weekly")

    def test_disabled_scheduled_start_leaves_the_model_untouched(self):
        # A confirmed hypothesis whose managed interest is missing: preparing context would rewrite the profile.
        self.propose_hypothesis()
        saved = WORKFLOW["feedback"](root=self.root, words="I enjoy the history of research.",
                                     signal="confirmed_interest", hypothesis_id="h")
        draft = HYPOTHESES["snapshot"](self.root)
        draft["taste_hypotheses"][0]["evidence"] = [
            {"feedback_id": saved["id"], "effect": "confirm", "scope": "hypothesis",
             "reason": "The actual words directly confirm this broader interest."}]
        HYPOTHESES["save"](self.root, draft)
        profile = json.loads((self.model / "profile.json").read_text(encoding="utf-8"))
        profile["interests"] = [item for item in profile["interests"] if item.get("hypothesis_id") != "h"]
        (self.model / "profile.json").write_text(json.dumps(profile), encoding="utf-8")
        before = self.state()
        self.assertEqual(self.begin(context="weekly")["status"], "weekly_delivery_disabled")
        self.assertEqual(self.state(), before)
        self.assertFalse(self.work.exists())
        # The same model is reconciled by an ordinary request, so the guard above is what kept it unchanged.
        self.assertEqual(self.begin()["context"]["hypothesis_reconciliation"]["status"], "refreshed")
        self.assertNotEqual((self.model / "profile.json").read_bytes(), before["profile.json"])

    def test_start_hands_back_a_due_hypothesis_review_instead_of_briefs(self):
        profile = CURATION["generic_profile"]("Synthetic person")
        profile["interests"] = [
            {"id": "a", "topic": "Synthetic research", "kind": "explicit", "source_provenance": ["s"]},
            {"id": "b", "topic": "Synthetic history", "kind": "explicit", "source_provenance": ["s"]}]
        profile["provenance"] = [{"id": "s", "kind": "user_statement", "locator": "fixture://statement"}]
        (self.model / "profile.json").write_text(json.dumps(profile), encoding="utf-8")
        started = WORKFLOW["start"](root=self.root, request="Something new", scope="broad", seed=7, out=self.work)
        self.assertEqual(started["status"], "maintenance_due")
        self.assertIsNone(started["exploration"])
        self.assertTrue(started["hypothesis_maintenance"]["review_due"])
        review = json.loads(Path(started["files"]["maintenance_review"]).read_text(encoding="utf-8"))
        self.assertEqual(review, started["hypothesis_maintenance"])
        self.assertIn("maintenance-complete", started["next"][1])
        # The saved review completes the ordinary gate, and discovery then runs with the same plan.
        HYPOTHESES["complete_maintenance"](self.root, review, "no_proposal", "Connections are too speculative.")
        status, briefs, error = cli(["explore", "--root", str(self.root), "--plan", started["files"]["plan"],
                                     "--profile", str(self.model / "profile.json"), "--count", "2"])
        self.assertEqual(status, 0, error)
        self.assertEqual(len(briefs["briefs"]), 2)

    def test_one_generic_recommendation_after_28_interests_requires_review(self):
        self.add_original_interests()
        before = (self.model / "profile.json").read_bytes()
        started = WORKFLOW["start"](root=self.root, request="Give me one recommendation", count=1,
                                    seed=7, discovery_seed=11, out=self.work)
        self.assertEqual(started["status"], "maintenance_due")
        self.assertEqual(started["plan"]["scope"], "broad")
        self.assertIsNone(started["exploration"])
        self.assertEqual(len(started["context"]["interests"]), 28)
        self.assertEqual(started["hypothesis_maintenance"]["triggers"], ["first_review"])
        self.assertEqual((self.model / "profile.json").read_bytes(), before)

    def test_focused_one_pick_can_save_a_hypothesis_and_resume_without_broadening(self):
        self.add_original_interests()
        started = WORKFLOW["start"](root=self.root, request="One book about Synthetic topic 0",
                                    scope="focused", fixed=True, count=1, seed=7,
                                    discovery_seed=11, out=self.work)
        self.assertEqual(started["status"], "maintenance_due")
        self.assertEqual(started["plan"]["scope"], "focused")
        plan_bytes = Path(started["files"]["plan"]).read_bytes()
        pool_path = self.work / "candidates.json"
        pool_path.write_text(json.dumps([candidate("only-pick")]), encoding="utf-8")
        status, unused, error = cli(["select", "--root", str(self.root), "--batch-id", started["batch_id"],
                                     "--plan", started["files"]["plan"], "--candidates", str(pool_path),
                                     "--count", "1"])
        self.assertEqual(status, 2)
        self.assertIn("maintenance is due", error)
        draft = HYPOTHESES["snapshot"](self.root)
        draft["taste_hypotheses"] = [{"id": "joint-interest", "topic": "A synthetic shared question",
                                     "anchor_ids": ["interest-0", "interest-1"], "status": "testing", "evidence": [],
                                     "reason": "The two topics might share a question; independent enjoyment is an alternative. "
                                               "Research a work connecting both to distinguish them."}]
        HYPOTHESES["save"](self.root, draft)
        HYPOTHESES["complete_maintenance"](
            self.root, started["hypothesis_maintenance"], "saved",
            "Saved one tentative connection without changing the focused request.", ["joint-interest"])
        status, exploration, error = cli(["explore", "--root", str(self.root), "--plan", started["files"]["plan"],
                                           "--profile", str(self.model / "profile.json"), "--count", "1", "--seed", "11"])
        self.assertEqual(status, 0, error)
        self.assertEqual(len(exploration["briefs"]), 1)
        self.assertEqual(Path(started["files"]["plan"]).read_bytes(), plan_bytes)
        self.assertEqual(exploration["hypothesis_maintenance"]["receipt"]["hypothesis_ids"], ["joint-interest"])
        update, selection = self.select(started, [candidate("only-pick")], count=1)
        self.assertEqual([item["id"] for item in selection["selected"]], ["only-pick"])
        profile = json.loads((self.model / "profile.json").read_text())
        self.assertEqual(len(profile["interests"]), 28)
        self.assertEqual(profile["taste_hypotheses"][0]["status"], "testing")

    def test_graph_update_completes_in_one_call_and_reuses_a_current_record(self):
        started = self.begin()
        research = self.work / "candidates.json"
        research.write_text(json.dumps([candidate("c1")]), encoding="utf-8")
        common = ["--root", str(self.root), "--research", str(research), "--reason", "No supported relationships."]
        select = ["select", "--root", str(self.root), "--batch-id", started["batch_id"], "--plan",
                  started["files"]["plan"], "--candidates", str(research), "--count", "1"]
        status, unused, error = cli(select)
        self.assertEqual(status, 2)
        self.assertIn("graph update is pending", error)
        self.assertIn("--batch-id", error)
        self.assertEqual(cli(["graph-update"] + common)[0], 2)
        self.assertEqual(cli(["graph-update", "--batch-id", "b", "--review", "r.json"] + common)[0], 2)
        status, first, error = cli(["graph-update", "--batch-id", started["batch_id"]] + common)
        self.assertEqual((status, first["status"], first["receipt"]["outcome"]), (0, "completed", "no_supported_changes"))
        receipt = (self.model / "graph-maintenance.json").read_bytes()
        status, again, error = cli(["graph-update", "--batch-id", started["batch_id"]] + common)
        self.assertEqual((status, again["status"], again["receipt"]["id"]), (0, "current", first["receipt"]["id"]))
        self.assertEqual((self.model / "graph-maintenance.json").read_bytes(), receipt)
        self.assertEqual(cli(select)[0], 0)

    def test_record_appends_the_delivery_and_its_trace_exactly_once(self):
        started = self.begin()
        update, selection = self.select(started, [candidate("c1"), candidate("c2", (3, 4, 4, 3, 4, 3)),
                                                  candidate("c3", (5, 3, 4, 2, 3, 2), "scientific_paper"),
                                                  candidate("weak", (1, 1, 1, 1, 1, 1))])
        profile = (self.model / "profile.json").read_bytes()
        recorded = WORKFLOW["record"](workdir=self.work)
        batch_id = started["batch_id"]
        self.assertEqual((recorded["status"], recorded["pending"]), ("recorded", []))
        history, batches = self.lines("recommendations.jsonl"), self.lines("batches.jsonl")
        self.assertEqual([item["id"] for item in history], recorded["recommendation_ids"])
        self.assertEqual({item["id"] for item in history}, {batch_id + "." + name for name in ("c1", "c2", "c3")})
        for item in history:
            self.assertEqual((item["status"], item["engagement"], item["batch_id"]), ("recommended", "unknown", batch_id))
            self.assertEqual(item["canonical_url"], "https://example.org/works/" + item["candidate_id"])
            self.assertEqual(item["scoring_basis"], "six_axis_weighted_fit")
            self.assertAlmostEqual(item["weighted_total"], sum(
                started["plan"]["effective_weights"][axis] * item["scores"][axis] for axis in AXES))
            self.assertTrue(item["recommended_at"].endswith("Z"))
        self.assertEqual(len(batches), 1)
        trace = batches[0]
        self.assertEqual((trace["id"], trace["context"], trace["request"]),
                         (batch_id, "on_demand", "Three things to read before bed"))
        self.assertEqual(trace["weight_plan"], started["plan"])
        self.assertEqual(trace["recommendation_ids"], recorded["recommendation_ids"])
        self.assertEqual(trace["selection_plan"], selection)
        self.assertEqual(trace["discovery_plan"], started["exploration"])
        self.assertEqual(trace["graph_update"]["receipt"]["id"], update["receipt"]["id"])
        self.assertEqual(trace["hypothesis_maintenance"], selection["hypothesis_maintenance"])
        self.assertEqual(trace["curators_brief"]["status"], "raw_model_fallback")
        self.assertEqual(trace["generation_protocol"], "varied_briefs")
        self.assertEqual(trace["diversity_audit"]["n_items"], 3)
        pool = {item["id"]: item for item in trace["candidate_pool"]}
        self.assertEqual(pool["weak"]["outcome"], "excluded")
        self.assertEqual(pool["weak"]["reasons"], ["below_subjective_fit_threshold"])
        self.assertEqual(pool["c1"]["outcome"], "delivered")
        self.assertEqual(pool["c1"]["verification"]["urls"], ["https://example.org/works/c1"])
        # Recording a delivery is not preference evidence and is safe to repeat.
        self.assertEqual((self.model / "profile.json").read_bytes(), profile)
        self.assertEqual(self.lines("feedback.jsonl"), [])
        ledgers = self.state()
        self.assertEqual(WORKFLOW["record"](workdir=self.work)["status"], "already_recorded")
        self.assertEqual(self.state(), ledgers)
        self.assertEqual(CONTEXT["prepare"](self.root)["ledgers"]["recommendation"]["count"], 3)

    def test_record_keeps_only_what_was_actually_delivered(self):
        started = self.begin()
        self.select(started, [candidate("c1"), candidate("c2"), candidate("c3")])
        before = self.state()
        with self.assertRaisesRegex(ValueError, "distinct selected items"):
            WORKFLOW["record"](workdir=self.work, deliver=["missing"])
        with self.assertRaisesRegex(ValueError, "distinct selected items"):
            WORKFLOW["record"](workdir=self.work, deliver=["c1", "c1"])
        self.assertEqual(self.state(), before)
        recorded = WORKFLOW["record"](workdir=self.work, deliver=["c2"], protocol="direct")
        self.assertEqual(recorded["recommendation_ids"], [started["batch_id"] + ".c2"])
        self.assertEqual([item["candidate_id"] for item in self.lines("recommendations.jsonl")], ["c2"])
        trace = self.lines("batches.jsonl")[0]
        self.assertEqual(trace["generation_protocol"], "direct")
        self.assertEqual({item["id"]: item["outcome"] for item in trace["candidate_pool"]},
                         {"c1": "selected_not_delivered", "c2": "delivered", "c3": "selected_not_delivered"})
        with self.assertRaisesRegex(ValueError, "already recorded with different items"):
            WORKFLOW["record"](workdir=self.work)

    def test_record_finishes_an_interrupted_write_without_duplicates(self):
        started = self.begin()
        self.select(started, [candidate("c1"), candidate("c2")], count=2)
        WORKFLOW["record"](workdir=self.work)
        history = (self.model / "recommendations.jsonl").read_bytes()
        (self.model / "batches.jsonl").write_bytes(b"")  # the batch trace never landed
        self.assertEqual(WORKFLOW["record"](workdir=self.work)["status"], "recorded")
        self.assertEqual((self.model / "recommendations.jsonl").read_bytes(), history)
        self.assertEqual(len(self.lines("batches.jsonl")), 1)

    def test_record_accepts_jsonl_research_and_keeps_candidate_provenance(self):
        started = self.begin()
        researched = [candidate("c1", source_provenance=["synthetic-source-one"]),
                      candidate("c2", source_provenance=["synthetic-source-two"])]
        self.select(started, researched, count=1)
        research_path = self.work / "candidates.jsonl"
        research_path.write_text("\n".join(json.dumps(item) for item in researched) + "\n\n",
                                 encoding="utf-8")
        (self.work / "candidates.json").unlink()
        recorded = WORKFLOW["record"](workdir=self.work)
        self.assertEqual(recorded["status"], "recorded")
        pool = {item["id"]: item for item in self.lines("batches.jsonl")[0]["candidate_pool"]}
        self.assertEqual(set(pool), {"c1", "c2"})
        self.assertEqual(sorted(item["outcome"] for item in pool.values()), ["delivered", "excluded"])
        for item in researched:
            self.assertEqual(pool[item["id"]]["canonical_url"], item["canonical_url"])
            self.assertEqual(pool[item["id"]]["verification"], item["verification"])
            self.assertEqual(pool[item["id"]]["source_provenance"], item["source_provenance"])
        self.assertEqual(WORKFLOW["record"](workdir=self.work, candidates=research_path)["status"],
                         "already_recorded")

    def test_record_refuses_mismatched_or_incomplete_inputs_without_writing(self):
        started = self.begin()
        self.select(started, [candidate("c1")], count=1)
        before = self.state()
        with self.assertRaisesRegex(ValueError, "another batch"):
            WORKFLOW["record"](workdir=self.work, batch_id="batch-elsewhere")
        with self.assertRaisesRegex(ValueError, "needs the retained plan"):
            WORKFLOW["record"](root=self.root, batch_id="b")
        (self.work / "empty.json").write_text(json.dumps({"selected": []}), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "nothing was selected"):
            WORKFLOW["record"](workdir=self.work, selection=self.work / "empty.json")
        (self.work / "broken.json").write_text(json.dumps({"selected": [{"id": "c1"}]}), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "select command's JSON output"):
            WORKFLOW["record"](workdir=self.work, selection=self.work / "broken.json")
        (self.model / ".profile.lock").write_text("")
        with self.assertRaisesRegex(ValueError, "another profile writer"):
            WORKFLOW["record"](workdir=self.work)
        (self.model / ".profile.lock").unlink()
        self.assertEqual(self.state(), before)

    def test_recorded_history_excludes_the_same_work_next_time(self):
        started = self.begin()
        self.select(started, [candidate("c1")], count=1)
        WORKFLOW["record"](workdir=self.work)
        self.work = self.base / "second-request"
        again = self.begin()
        unused, selection = self.select(again, [candidate("c1"), candidate("c9")], count=1)
        self.assertEqual([item["id"] for item in selection["selected"]], ["c9"])
        self.assertIn({"id": "c1", "reasons": ["previously_recommended"]}, selection["excluded"])

    def test_feedback_appends_one_reaction_in_the_persons_words(self):
        started = self.begin()
        self.select(started, [candidate("c1")], count=1)
        target = WORKFLOW["record"](workdir=self.work)["recommendation_ids"][0]
        profile = (self.model / "profile.json").read_bytes()
        saved = WORKFLOW["feedback"](root=self.root, words=" Loved how it explained a hard idea. ", signal="Enjoyed",
                                     recommendation_id=target, kind="experienced_enjoyment")
        self.assertEqual(saved["status"], "recorded")
        event = self.lines("feedback.jsonl")[0]
        self.assertEqual((event["id"], event["recommendation_id"], event["signal"], event["user_words"]),
                         (saved["id"], target, "enjoyed", "Loved how it explained a hard idea."))
        self.assertEqual((event["batch_id"], event["feedback_kind"], event["profile_changes"]),
                         (started["batch_id"], "experienced_enjoyment", []))
        self.assertEqual(event["source_provenance"][0]["kind"], "current_conversation")
        repeated = WORKFLOW["feedback"](root=self.root, words="Loved how it explained a hard idea.", signal="enjoyed",
                                        recommendation_id=target)
        self.assertEqual((repeated["status"], repeated["id"]), ("already_recorded", saved["id"]))
        change = {"path": "/taste/presentation", "before": None, "after": "short", "reason": "Asked for brevity.",
                  "source_provenance": ["s"]}
        general = WORKFLOW["feedback"](root=self.root, words="Keep them short.", signal="want_less", sources=["s"],
                                       changes=[change])
        events = self.lines("feedback.jsonl")
        self.assertEqual(len(events), 2)
        self.assertEqual((events[1]["id"], events[1]["recommendation_id"], events[1]["source_provenance"],
                          events[1]["profile_changes"]), (general["id"], None, ["s"], [change]))
        # The helper records words; it never edits preferences or other ledgers itself.
        self.assertEqual((self.model / "profile.json").read_bytes(), profile)
        self.assertEqual(len(self.lines("recommendations.jsonl")), 1)
        self.assertEqual(CONTEXT["prepare"](self.root)["ledgers"]["feedback"]["count"], 2)

    def test_feedback_rejects_what_is_not_the_persons_reaction(self):
        before = self.state()
        for options, message in (
                ({"words": "x", "signal": "delivered"}, "not the person's feedback"),
                ({"words": "x", "signal": "assistant suggestion"}, "not the person's feedback"),
                ({"words": "   ", "signal": "useful"}, "actual words"),
                ({"words": "x", "signal": "?"}, "short label"),
                ({"words": "x", "signal": "useful", "recommendation_id": "unknown"}, "unknown recommendation id"),
                ({"words": "x", "signal": "useful", "kind": "guess"}, "kind must be"),
                ({"words": "x", "signal": "useful", "changes": [{"path": "/taste"}]}, "profile changes must be")):
            with self.assertRaisesRegex(ValueError, message):
                WORKFLOW["feedback"](root=self.root, **options)
        self.assertEqual(self.state(), before)

    def test_default_feedback_triggers_maintenance_and_can_confirm_a_hypothesis(self):
        self.propose_hypothesis()
        before = HYPOTHESES["maintenance_plan"](self.root, event="feedback")
        saved = WORKFLOW["feedback"](root=self.root, words="I enjoy the history of research.",
                                     signal="confirmed_interest", hypothesis_id="h")
        after = HYPOTHESES["maintenance_plan"](self.root, event="feedback")
        self.assertNotEqual(after["evidence_fingerprint"], before["evidence_fingerprint"])
        draft = HYPOTHESES["snapshot"](self.root)
        draft["taste_hypotheses"][0]["evidence"] = [
            {"feedback_id": saved["id"], "effect": "confirm", "scope": "hypothesis",
             "reason": "The actual words directly confirm this broader interest."}]
        HYPOTHESES["save"](self.root, draft)
        promoted = json.loads((self.model / "profile.json").read_text(encoding="utf-8"))
        self.assertEqual(promoted["taste_hypotheses"][0]["status"], "confirmed")
        learned = next(item for item in promoted["interests"] if item.get("hypothesis_id") == "h")
        self.assertEqual(learned["kind"], "explicit")

    def test_default_feedback_does_not_invent_independent_sources(self):
        self.propose_hypothesis()
        works = [candidate("c1"), candidate("c2")]
        (self.model / "recommendations.jsonl").write_text(
            "".join(json.dumps(item) + "\n" for item in works), encoding="utf-8")
        for located, expected in ((False, "testing"), (True, "supported")):
            with self.subTest(located_sources=located):
                evidence = []
                for work in works:
                    words = ("I enjoyed the historical structure in " if located else "I enjoyed ") + work["title"]
                    saved = WORKFLOW["feedback"](
                        root=self.root, words=words, signal="enjoyed", recommendation_id=work["id"],
                        hypothesis_id="h", sources=["synthetic-message-" + work["id"]] if located else ())
                    evidence.append({"feedback_id": saved["id"], "effect": "support", "scope": "work",
                                     "reason": "The shared historical quality may explain the enjoyment."})
                draft = HYPOTHESES["snapshot"](self.root)
                draft["taste_hypotheses"][0]["evidence"] = evidence
                result = HYPOTHESES["save"](self.root, draft)
                self.assertEqual(result["hypotheses"][0]["status"], expected)

    def test_feedback_preserves_identical_reactions_to_different_hypotheses(self):
        options = {"root": self.root, "words": "Yes, that is an interest of mine.",
                   "signal": "confirmed_interest", "sources": ["synthetic-message"]}
        first = WORKFLOW["feedback"](hypothesis_id="h-a", **options)
        second = WORKFLOW["feedback"](hypothesis_id="h-b", **options)
        self.assertEqual((first["status"], second["status"]), ("recorded", "recorded"))
        self.assertNotEqual(first["id"], second["id"])
        events = self.lines("feedback.jsonl")
        self.assertEqual([item["hypothesis_id"] for item in events], ["h-a", "h-b"])
        before = self.state()
        repeated = WORKFLOW["feedback"](hypothesis_id="h-b", **options)
        self.assertEqual((repeated["status"], repeated["id"]), ("already_recorded", second["id"]))
        self.assertEqual(self.state(), before)

    def test_public_entry_point_runs_the_helpers(self):
        status, started, error = cli(["start", "--root", str(self.root), "--request", "One book", "--count", "2",
                                      "--out", str(self.work)])
        self.assertEqual((status, started["status"]), (0, "ready"), error)
        self.select(started, [candidate("c1")], count=1)
        status, recorded, error = cli(["record", "--workdir", str(self.work)])
        self.assertEqual((status, recorded["status"]), (0, "recorded"), error)
        status, saved, error = cli(["feedback", "--root", str(self.root), "--recommendation-id",
                                    recorded["recommendation_ids"][0], "--signal", "useful", "--words", "Good pick."])
        self.assertEqual((status, saved["status"]), (0, "recorded"), error)
        status, unused, error = cli(["record", "--workdir", str(self.base / "nowhere")])
        self.assertEqual(status, 2)
        self.assertIn("needs the retained plan", error)


if __name__ == "__main__":
    unittest.main()
