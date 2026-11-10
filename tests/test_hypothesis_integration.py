"""Exercise taste hypotheses through discovery and selection using synthetic state."""
import copy
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "skills/trurl/scripts"


def module(name):
    spec = importlib.util.spec_from_file_location("integration_" + name, SCRIPTS / (name + ".py"))
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


diversity = module("diversity")
graph = module("graph")
AXES = ("depth", "novelty", "relevance", "surprise", "perspective_change", "entertainment")
REGISTRY = {"version": "synthetic", "domains": [
    {"field": "Synthetic field " + str(index), "category": "synthetic"} for index in range(10)
]}


def selection_plan(mode="personal", scope="broad"):
    return {
        "mode": mode, "scope": scope,
        "effective_weights": {axis: 1 / len(AXES) for axis in AXES},
        "lane_mix": {"familiar": .75, "adjacent": .25, "distant": 0},
        "constraints": {"request": "A broad selection" if scope == "broad" else "Only tide prediction"},
    }


def original_profile():
    return {
        "schema_version": 3,
        "provenance": [{"id": "user-source", "kind": "user_statement",
                        "locator": "synthetic://statement/1", "captured_at": "2026-11-06T12:00:00Z"}],
        "interests": [{"id": "anchor", "topic": "Clockwork stories", "kind": "explicit",
                       "signal": "enjoyed", "scope": "persistent", "confidence": 1,
                       "source_provenance": ["user-source"], "knowledge_level": "unknown"}],
        "taste": {"axes_weights": {axis: 1 / len(AXES) for axis in AXES}},
    }


def cross_theme_profile():
    profile = original_profile()
    for identifier, topic in (("history", "History of machines"), ("craft", "Ceramic craft")):
        source = identifier + "-source"
        profile["provenance"].append({"id": source, "kind": "user_statement",
                                      "locator": "synthetic://statement/" + identifier})
        profile["interests"].append({"id": identifier, "topic": topic, "kind": "explicit",
                                     "signal": "interested", "scope": "persistent", "confidence": 1,
                                     "source_provenance": [source], "knowledge_level": "unknown"})
    return profile


def candidate(identifier, hypothesis_id=None, **updates):
    value = {
        "id": identifier, "title": "Synthetic work " + identifier,
        "creator": "Synthetic creator " + identifier,
        "canonical_url": "https://example.test/work/" + identifier,
        "medium": "book", "lane": "adjacent" if hypothesis_id else "familiar",
        "topics": ["Synthetic topic " + identifier],
        "scores": {axis: 4 for axis in AXES},
        "constraints_passed": True, "credibility_passed": True,
        "verification": {"checked_at": "2026-11-06T12:00:00Z",
                         "urls": ["https://example.test/work/" + identifier]},
        "personal_connection": {"basis": "explicit_interest", "anchor": "anchor",
                                "explanation": "Explores the mechanical storytelling in the stated work."},
    }
    if hypothesis_id is not None:
        value["hypothesis_id"] = hypothesis_id
    value.update(updates)
    return value


class HypothesisSelectionTests(unittest.TestCase):
    def test_legacy_profile_and_empty_hypotheses_preserve_seeded_discovery(self):
        profile = original_profile()
        before = copy.deepcopy(profile)
        expected = diversity.explore(selection_plan(), profile, seed=42, registry=REGISTRY)
        empty = dict(profile, taste_hypotheses=[])
        result = diversity.explore(selection_plan(), empty, seed=42, registry=REGISTRY)
        self.assertEqual(result, expected)
        self.assertEqual(profile, before)
        self.assertFalse(any("hypothesis_id" in brief for brief in result["briefs"]))

    def test_selection_allows_one_probe_even_when_candidates_cover_different_hypotheses(self):
        candidates = [candidate("probe-a", "hypothesis-a"), candidate("probe-b", "hypothesis-b"),
                      candidate("normal-a"), candidate("normal-b"), candidate("normal-c")]
        before = copy.deepcopy(candidates)
        result = diversity.select_slate(selection_plan(), candidates, 4, seed=11)
        self.assertEqual(len(result["selected"]), 4)
        self.assertEqual(sum("hypothesis_id" in item for item in result["selected"]), 1)
        self.assertEqual(candidates, before)
        self.assertTrue(any("hypothesis_probe_cap_reached" in item["reasons"]
                            for item in result["excluded"]))

    def test_probe_cannot_bypass_adjacent_scope_or_personal_connection_gates(self):
        cases = [
            (selection_plan(), candidate("familiar-probe", "hypothesis-a", lane="familiar")),
            (selection_plan(scope="focused"), candidate("focused-probe", "hypothesis-a")),
            (selection_plan(), candidate("unconnected-probe", "hypothesis-a", personal_connection=None)),
            (selection_plan(), candidate("blank-id", "")),
        ]
        low_fit = candidate("weak-probe", "hypothesis-a")
        low_fit["scores"]["relevance"] = 2
        cases.append((selection_plan(), low_fit))
        for plan, item in cases:
            with self.subTest(item=item["id"]):
                result = diversity.select_slate(plan, [item], 1, seed=11)
                self.assertEqual(result["selected"], [])
                self.assertEqual(result["shortfall"], 1)
                self.assertTrue(result["excluded"][0]["reasons"])


class HypothesisDiscoveryTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name) / "workspace"
        self.model = self.root / "model"
        self.model.mkdir(parents=True)
        self.hypotheses = module("hypotheses")
        self.write_profile(original_profile())
        self.feedback = []
        self.history = []
        self.write_ledgers()
        draft = self.hypotheses.snapshot(self.root)
        draft["taste_hypotheses"].append({
            "id": "mechanical-humour", "topic": "Mechanical humour",
            "anchor_ids": ["anchor"], "reason": "The stated stories may appeal through their mechanical humour.",
            "status": "testing", "evidence": [],
        })
        self.hypotheses.save(self.root, draft)

    def write_profile(self, profile):
        (self.model / "profile.json").write_text(json.dumps(profile), encoding="utf-8")

    def read_profile(self):
        return json.loads((self.model / "profile.json").read_text(encoding="utf-8"))

    def write_ledgers(self):
        for name, records in (("feedback", self.feedback), ("recommendations", self.history)):
            (self.model / (name + ".jsonl")).write_text(
                "".join(json.dumps(record) + "\n" for record in records), encoding="utf-8")

    def supported_profile(self):
        self.history = [
            {"id": "work-" + str(index), "title": "Synthetic work " + str(index),
             "creator": "Creator " + str(index), "canonical_url": "https://example.test/" + str(index)}
            for index in (1, 2)
        ]
        self.feedback = [
            {"id": "feedback-" + str(index), "signal": "enjoyed", "recommendation_id": "work-" + str(index),
             "recorded_at": "2026-11-06T12:00:00Z", "user_words": "I loved the mechanical humour in this work.",
             "source_provenance": ["user-feedback-message-" + str(index)]}
            for index in (1, 2)
        ]
        self.write_ledgers()
        draft = self.hypotheses.snapshot(self.root)
        draft["taste_hypotheses"][0]["evidence"] = [
            {"feedback_id": event["id"], "effect": "support", "scope": "work",
             "reason": "The person enjoyed the mechanical humour in this work."}
            for event in self.feedback
        ]
        self.hypotheses.save(self.root, draft)
        result = self.read_profile()
        self.assertEqual(result["taste_hypotheses"][0]["status"], "supported")
        return result

    def explore(self, profile=None, plan=None, **kwargs):
        return diversity.explore(
            plan or selection_plan(), profile or self.read_profile(), history=self.history,
            feedback=self.feedback, count=8, seed=19, registry=REGISTRY, **kwargs)

    def content_graph(self):
        return {
            "schema_version": 1,
            "sources": [{"id": "content-source", "kind": "synthetic_fixture",
                         "locator": "synthetic://graph", "checked_at": "2026-11-06"}],
            "nodes": [{"id": "origin", "type": "topic", "label": "Clockwork stories"},
                      {"id": "possibility", "type": "topic", "label": "Mechanical humour"},
                      {"id": "origin-neighbour", "type": "topic", "label": "Clockwork theatre"},
                      {"id": "possibility-neighbour", "type": "topic", "label": "Mechanical comedy"}],
            "edges": [
                {"id": "edge-" + str(index), "source": source, "target": target,
                 "relation": "related_to", "status": "verified", "confidence": .9,
                 "source_provenance": ["content-source"], "assertion_method": "synthetic_fixture"}
                for index, (source, target) in enumerate(
                    (("origin", "origin-neighbour"), ("possibility", "possibility-neighbour")))
            ],
        }

    def test_testing_hypothesis_gets_one_adjacent_slot_but_never_becomes_an_anchor(self):
        profile = self.read_profile()
        before = copy.deepcopy(profile)
        result = self.explore(profile)
        probes = [brief for brief in result["briefs"] if "hypothesis_id" in brief]
        self.assertEqual(len(probes), 1)
        self.assertEqual(probes[0]["lane"], "adjacent")
        self.assertEqual(probes[0]["field"], "Mechanical humour")
        self.assertEqual(probes[0]["interest_evidence"]["id"], "anchor")
        self.assertEqual({brief["interest_evidence"]["id"] for brief in result["briefs"]}, {"anchor"})
        self.assertEqual([anchor["id"] for anchor in graph.personal_anchors(profile)], ["anchor"])
        self.assertEqual(result, self.explore(profile))
        self.assertEqual(profile, before)

    def test_multi_interest_brief_keeps_two_origins_but_validates_every_origin(self):
        self.write_profile(cross_theme_profile())
        draft = self.hypotheses.snapshot(self.root)
        draft["taste_hypotheses"] = [{
            "id": "cross-theme", "topic": "Histories of technical craft",
            "reason": "The three original interests suggest a connection worth investigating.",
            "anchor_ids": ["anchor", "history", "craft"], "status": "testing", "evidence": [],
        }]
        self.hypotheses.save(self.root, draft)
        profile = self.read_profile()
        before = copy.deepcopy(profile)
        result = self.explore(profile)
        probes = [brief for brief in result["briefs"] if "hypothesis_id" in brief]
        self.assertEqual(len(probes), 1)
        probe = probes[0]
        self.assertEqual(probe["interest_evidence"]["id"], "anchor")
        self.assertEqual(probe["supporting_interest"]["id"], "history")
        self.assertEqual(probe["supporting_interest"]["source_refs"], ["history-source"])
        self.assertEqual(probe["taste_hypothesis"]["anchor_ids"], ["anchor", "history"])
        self.assertEqual(probe["taste_hypothesis"]["anchor_count"], 3)
        self.assertTrue(probe["taste_hypothesis"]["context_omitted"])
        self.assertFalse({"evidence", "evidence_hashes", "anchor_hashes"} & probe["taste_hypothesis"].keys())
        self.assertEqual(result, self.explore(profile))
        self.assertEqual(profile, before)
        for index in range(3):
            with self.subTest(corrected_origin=index):
                corrected = copy.deepcopy(profile)
                corrected["interests"][index]["topic"] += " corrected"
                self.assertFalse(any(brief.get("hypothesis_id") == "cross-theme"
                                     for brief in self.explore(corrected)["briefs"]))
        removed = copy.deepcopy(profile)
        removed["interests"].pop()
        self.assertFalse(any(brief.get("hypothesis_id") == "cross-theme"
                             for brief in self.explore(removed)["briefs"]))

    def test_compact_context_omits_large_ledgers_and_recomputes_evidence_summary(self):
        profile = cross_theme_profile()
        profile["interests"][1]["source_provenance"] = [
            {"id": "history-source", "quote": "long source context " * 1000},
            "history-extra-source", "history-third-source",
        ]
        self.write_profile(profile)
        self.history = [{"id": "same-work", "title": "One synthetic work", "creator": "An author",
                         "canonical_url": "https://example.test/same-work"}]
        self.feedback = [
            {"id": "large-feedback-" + str(index), "signal": "enjoyed", "recommendation_id": "same-work",
             "user_words": "I enjoyed this. " * 1000,
             "source_provenance": ["synthetic-reaction-" + str(index)]}
            for index in range(24)
        ]
        self.write_ledgers()
        draft = self.hypotheses.snapshot(self.root)
        draft["taste_hypotheses"] = [{
            "id": "large-hypothesis", "topic": "Technical craft histories", "status": "testing",
            "anchor_ids": ["anchor", "history", "craft"], "reason": "Possible connection. " * 2000,
            "evidence": [{"feedback_id": event["id"], "effect": "support", "scope": "work",
                          "reason": "Long interpretation of the same work. " * 1000}
                         for event in self.feedback],
        }]
        self.hypotheses.save(self.root, draft)
        profile = self.read_profile()
        self.assertEqual(profile["taste_hypotheses"][0]["status"], "testing")
        profile["taste_hypotheses"][0].update(
            supporting_work_count={"untrusted": "x" * 10000},
            conflicting_work_feedback="untrusted" * 10000,
            ambiguous_broad_feedback=["untrusted"] * 10000)
        before = copy.deepcopy(profile)
        probe = next(brief for brief in self.explore(profile)["briefs"] if "hypothesis_id" in brief)
        context = probe["taste_hypothesis"]
        self.assertEqual(context["supporting_work_count"], 1)
        self.assertIs(context["conflicting_work_feedback"], False)
        self.assertIs(context["ambiguous_broad_feedback"], False)
        self.assertEqual(probe["supporting_interest"]["source_refs"],
                         ["history-source", "history-extra-source"])
        serialized = json.dumps([context, probe["supporting_interest"]])
        self.assertLess(len(serialized), 1200)
        self.assertNotIn("large-feedback-", serialized)
        self.assertNotIn("Long interpretation", serialized)
        self.assertNotIn("long source context", serialized)
        self.assertNotIn("untrusted", serialized)
        self.assertEqual(profile, before)

    def test_pair_draft_uses_one_slot_without_changing_the_discovery_draw_or_inputs(self):
        profile, plan = cross_theme_profile(), selection_plan()
        history = [{"id": "earlier-work", "topics": ["Earlier synthetic topic"]}]
        inputs = copy.deepcopy((profile, plan, history))
        for seed in (7, 19, 42):
            arguments = {"history": history, "count": 8, "seed": seed, "registry": REGISTRY}
            with self.subTest(seed=seed):
                with patch.object(diversity, "_hypothesis_brief", return_value=None):
                    baseline = diversity.explore(plan, profile, **arguments)
                result = diversity.explore(plan, profile, **arguments)
                pairs = [brief for brief in result["briefs"] if brief.get("hypothesis_action") == "propose"]
                self.assertEqual(len(pairs), 1)
                self.assertEqual(pairs[0]["lane"], "adjacent")
                self.assertNotEqual(pairs[0]["interest_evidence"]["id"], pairs[0]["supporting_interest"]["id"])
                self.assertFalse(any("hypothesis_id" in brief for brief in result["briefs"]))
                self.assertEqual(len(result["briefs"]), len(baseline["briefs"]))
                self.assertEqual(result["selection_policy"], baseline["selection_policy"])
                for actual, previous in zip(result["briefs"], baseline["briefs"]):
                    if actual.get("hypothesis_action") == "propose":
                        actual = {key: value for key, value in actual.items()
                                  if key not in {"instruction", "supporting_interest", "hypothesis_action"}}
                        previous = {key: value for key, value in previous.items() if key != "instruction"}
                    self.assertEqual(actual, previous)
                self.assertEqual(result, diversity.explore(plan, profile, **arguments))
                self.assertEqual((profile, plan, history), inputs)

    def test_pair_origins_follow_save_eligibility_and_require_distinct_themes(self):
        changes = {
            "temporary": lambda a, p: a.update(scope="current_request"),
            "no-evidence": lambda a, p: a.pop("source_provenance"),
            "missing-id": lambda a, p: a.pop("id"),
            "managed": lambda a, p: a.update(hypothesis_id="unreviewed"),
            "reserved-id": lambda a, p: a.update(id="hypothesis:unreviewed"),
            "reference-only": lambda a, p: a.update(source_kind="reference_only"),
            "zero-confidence": lambda a, p: a.update(confidence=0),
            "rejected": lambda a, p: a.update(status="rejected"),
            "duplicate-topic": lambda a, p: a.update(topic="CLOCKWORK stories"),
            "same-graph-node": lambda a, p: (a.update(graph_node_id="shared"),
                                             p["interests"][0].update(graph_node_id="shared")),
        }
        for name, mutate in changes.items():
            profile = cross_theme_profile()
            profile["interests"].pop()
            mutate(profile["interests"][1], profile)
            before = copy.deepcopy(profile)
            with self.subTest(origin=name):
                for seed in (7, 19, 42):
                    result = diversity.explore(selection_plan(), profile, count=8, seed=seed, registry=REGISTRY)
                    self.assertFalse(any("hypothesis_action" in brief or "supporting_interest" in brief
                                         for brief in result["briefs"]))
                self.assertEqual(profile, before)

    def test_pair_enrichment_leaves_focused_wildcard_and_no_adjacent_plans_unchanged(self):
        profile = cross_theme_profile()
        no_adjacent = selection_plan()
        no_adjacent["lane_mix"] = {"familiar": 1, "adjacent": 0, "distant": 0}
        for plan in (selection_plan(scope="focused"), selection_plan(mode="wildcard"), no_adjacent):
            with self.subTest(plan=plan):
                with patch.object(diversity, "_hypothesis_brief", return_value=None):
                    baseline = diversity.explore(plan, profile, count=8, seed=19, registry=REGISTRY)
                result = diversity.explore(plan, profile, count=8, seed=19, registry=REGISTRY)
                self.assertEqual(result, baseline)
                self.assertFalse(any("hypothesis_id" in brief or "supporting_interest" in brief
                                     or "hypothesis_action" in brief for brief in result["briefs"]))

    def test_focused_and_wildcard_discovery_do_not_insert_hypothesis_probes(self):
        for plan in (selection_plan(scope="focused"), selection_plan(mode="wildcard")):
            with self.subTest(plan=plan):
                result = self.explore(plan=plan)
                self.assertFalse(any("hypothesis_id" in brief for brief in result["briefs"]))
        self.assertTrue(all(brief["lane"] == "focused"
                            for brief in self.explore(plan=selection_plan(scope="focused"))["briefs"]))

    def test_supported_inference_is_available_only_with_current_feedback_evidence(self):
        profile = self.supported_profile()
        managed = "hypothesis:mechanical-humour"
        current = self.explore(profile)
        self.assertIn(managed, {brief["interest_evidence"]["id"] for brief in current["briefs"]})
        self.assertTrue(any(brief["interest_evidence"]["id"] == managed
                            and brief["interest_evidence"]["kind"] == "inferred"
                            for brief in current["briefs"]))
        for feedback in (None, [], [dict(event, signal="completed") for event in self.feedback]):
            with self.subTest(feedback=feedback):
                result = diversity.explore(selection_plan(), profile, history=self.history,
                                           feedback=feedback, count=8, seed=19, registry=REGISTRY)
                self.assertNotIn(managed, {brief["interest_evidence"]["id"] for brief in result["briefs"]})
        self.assertNotIn(managed, {anchor["id"] for anchor in graph.personal_anchors(profile)})

    def test_graph_frontier_checks_evidence_and_original_anchor_corrections(self):
        profile = self.supported_profile()
        arguments = {"history": self.history, "seed": 19, "count": 8}
        current = graph.frontier(self.content_graph(), profile, feedback=self.feedback, **arguments)
        self.assertIn("hypothesis:mechanical-humour", {route["anchor_id"] for route in current["connected"]})
        without_feedback = graph.frontier(self.content_graph(), profile, **arguments)
        self.assertEqual({route["anchor_id"] for route in without_feedback["connected"]}, {"anchor"})
        corrected = copy.deepcopy(profile)
        corrected["interests"][0]["topic"] = "Different stated topic"
        result = self.explore(corrected)
        self.assertFalse(any("hypothesis_id" in brief for brief in result["briefs"]))
        self.assertNotIn("hypothesis:mechanical-humour",
                         {brief["interest_evidence"]["id"] for brief in result["briefs"]})

    def test_explicit_correction_removes_promotion_and_probe_with_raw_feedback_retained(self):
        self.supported_profile()
        self.feedback.append({
            "id": "correction", "signal": "rejected_interest", "recommendation_id": None,
            "recorded_at": "2026-11-07T12:00:00Z",
            "user_words": "Mechanical humour is not an interest of mine.",
            "source_provenance": ["user-correction-message"],
        })
        self.write_ledgers()
        ledger_before = (self.model / "feedback.jsonl").read_bytes()
        draft = self.hypotheses.snapshot(self.root)
        draft["taste_hypotheses"][0]["evidence"].append({
            "feedback_id": "correction", "effect": "contradict", "scope": "hypothesis",
            "reason": "The person directly corrected the inferred broader interest.",
        })
        self.hypotheses.save(self.root, draft)
        profile = self.read_profile()
        self.assertEqual(profile["taste_hypotheses"][0]["status"], "rejected")
        self.assertEqual((self.model / "feedback.jsonl").read_bytes(), ledger_before)
        result = self.explore(profile)
        self.assertFalse(any("hypothesis_id" in brief for brief in result["briefs"]))
        self.assertNotIn("hypothesis:mechanical-humour",
                         {brief["interest_evidence"]["id"] for brief in result["briefs"]})

    def test_managed_inference_cannot_seed_another_hypothesis(self):
        self.supported_profile()
        draft = self.hypotheses.snapshot(self.root)
        draft["taste_hypotheses"].append({
            "id": "chain", "topic": "Second speculative topic",
            "anchor_ids": ["hypothesis:mechanical-humour"],
            "reason": "An ungrounded second inference from a previous inference.",
            "status": "testing", "evidence": [],
        })
        before = (self.model / "profile.json").read_bytes()
        with self.assertRaises(ValueError):
            self.hypotheses.save(self.root, draft)
        self.assertEqual((self.model / "profile.json").read_bytes(), before)

    def test_hypothesis_origin_obeys_the_same_personal_evidence_policy_as_discovery(self):
        for change in ({"confidence": 0}, {"signal": "not_for_me"},
                       {"source_kind": "assistant_characterization"}):
            with self.subTest(change=change):
                profile = original_profile()
                profile["interests"][0].update(change)
                self.write_profile(profile)
                draft = self.hypotheses.snapshot(self.root)
                draft["taste_hypotheses"].append({
                    "id": "invalid-origin", "topic": "Mechanical humour", "anchor_ids": ["anchor"],
                    "reason": "A possibility from an ineligible observation.", "status": "testing", "evidence": [],
                })
                self.assertEqual(graph.personal_anchors(profile), [])
                with self.assertRaises(ValueError):
                    self.hypotheses.save(self.root, draft)

    def test_installed_cli_reads_sibling_evidence_and_does_not_read_an_atlas(self):
        self.supported_profile()
        installed = Path(self.temporary.name) / "installed"
        module("curation").install_skill(installed)
        runtime = installed / "scripts/curation.py"
        plan_path = Path(self.temporary.name) / "plan.json"
        plan_path.write_text(json.dumps(selection_plan()), encoding="utf-8")
        (self.model / "taste-atlas.html").write_text("unreadable as JSON; display output only", encoding="utf-8")
        command = [sys.executable, str(runtime), "explore", "--plan", str(plan_path),
                   "--profile", str(self.model / "profile.json"), "--count", "8", "--seed", "19"]
        before = {file.name: file.read_bytes() for file in self.model.iterdir()}
        first = subprocess.run(command, cwd=installed, capture_output=True, text=True, timeout=15)
        self.assertEqual(first.returncode, 0, first.stderr)
        anchors = {brief["interest_evidence"]["id"] for brief in json.loads(first.stdout)["briefs"]}
        self.assertIn("hypothesis:mechanical-humour", anchors)
        self.assertEqual({file.name: file.read_bytes() for file in self.model.iterdir()}, before)
        (self.model / "feedback.jsonl").unlink()
        second = subprocess.run(command, cwd=installed, capture_output=True, text=True, timeout=15)
        self.assertEqual(second.returncode, 0, second.stderr)
        anchors = {brief["interest_evidence"]["id"] for brief in json.loads(second.stdout)["briefs"]}
        self.assertNotIn("hypothesis:mechanical-humour", anchors)


if __name__ == "__main__":
    unittest.main()
