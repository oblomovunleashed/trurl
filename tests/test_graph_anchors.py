"""Automatic representation must preserve scope, provenance and personal state."""
import copy
from contextlib import redirect_stderr, redirect_stdout
import io
import json
from pathlib import Path
import runpy
import tempfile
import unittest
from unittest import mock


SCRIPTS = Path(__file__).resolve().parents[1] / "skills/trurl/scripts"
API = runpy.run_path(str(SCRIPTS / "graph_anchors.py"))
GRAPH = runpy.run_path(str(SCRIPTS / "graph.py"))
UPDATES = runpy.run_path(str(SCRIPTS / "graph_updates.py"))
CURATION = runpy.run_path(str(SCRIPTS / "curation.py"))
HYPOTHESES = runpy.run_path(str(SCRIPTS / "hypotheses.py"))


class GraphAnchorTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.model = self.root / "model"
        self.model.mkdir()
        self.profile = {"interests": [{"id": "tea", "topic": "Gongfu tea preparation", "kind": "explicit",
                                      "source_provenance": ["user-tea"]}],
                        "provenance": [{"id": "user-tea", "kind": "user_statement", "locator": "synthetic message"}],
                        "delivery": {"weekly": {"enabled": False}},
                        "source_permissions": {"past_chats": False}, "taste": {"axes_weights": {"novelty": 1}}}
        self.write("profile.json", self.profile)
        (self.model / "feedback.jsonl").write_text("")
        (self.model / "recommendations.jsonl").write_text("")

    def write(self, name, value):
        (self.model / name).write_text(json.dumps(value), encoding="utf-8")

    def graph(self):
        return json.loads((self.model / "graph.json").read_text())

    def mappings(self):
        return API["read_mappings"](self.root)

    def sync(self, bindings=None):
        return API["sync_anchors"](self.root, bindings)

    def match(self, profile=None):
        return API["match_anchors"](self.graph(), profile or self.profile, self.mappings())

    def seed_creator(self):
        graph = GRAPH["empty_graph"]()
        graph["nodes"].append({"id": "creator", "label": "Synthetic Creator", "type": "creator"})
        self.write("graph.json", graph)
        self.profile["interests"][0]["topic"] = "Synthetic Creator's works"
        self.write("profile.json", self.profile)

    def test_represents_all_25_literal_scopes_without_edges_or_personal_mutation(self):
        self.profile["interests"] = [{"id": "interest-" + str(n), "topic": "Specific interest " + str(n),
                                      "kind": "explicit", "source_provenance": ["user-tea"]} for n in range(25)]
        self.write("profile.json", self.profile)
        before = {path.name: path.read_bytes() for path in self.model.iterdir()}
        result = self.sync()
        self.assertEqual(result["counts"]["represented_interests"], 25)
        self.assertEqual(result["counts"]["nodes_added"], 25)
        graph = self.graph()
        self.assertEqual(graph["edges"], [])
        self.assertEqual(graph["sources"], [])
        self.assertEqual({node["label"] for node in graph["nodes"]},
                         {anchor["topic"] for anchor in self.profile["interests"]})
        self.assertTrue(all(set(node) == {"id", "type", "label"} for node in graph["nodes"]))
        self.assertEqual(before, {name: (self.model / name).read_bytes() for name in before})

    def test_unchanged_sync_does_not_rewrite_files(self):
        self.sync()
        before = {path.name: (path.read_bytes(), path.stat().st_mtime_ns) for path in self.model.iterdir()}
        result = self.sync()
        self.assertEqual(result["status"], "current")
        self.assertEqual(result["counts"]["nodes_added"], 0)
        self.assertEqual(before, {path.name: (path.read_bytes(), path.stat().st_mtime_ns) for path in self.model.iterdir()})

    def test_exact_topic_alias_reused_broader_topic_not_assumed(self):
        graph = GRAPH["empty_graph"]()
        graph["nodes"] = [{"id": "broad", "type": "topic", "label": "Tea trade"},
                          {"id": "precise", "type": "topic", "label": "Gongfu brewing",
                           "aliases": ["Gongfu tea preparation"]}]
        self.write("graph.json", graph)
        self.assertEqual(self.sync()["counts"]["nodes_added"], 0)
        self.assertEqual(self.match()["matches"], {"tea": "precise"})

    def test_broader_scope_stays_separate(self):
        graph = GRAPH["empty_graph"]()
        graph["nodes"] = [{"id": "broad", "type": "topic", "label": "Tea trade"}]
        self.write("graph.json", graph)
        self.sync()
        self.assertNotEqual(self.match()["matches"]["tea"], "broad")
        self.assertEqual(self.graph()["edges"], [])

    def test_removed_alias_invalidates_exact_match_and_restores_literal_scope(self):
        graph = GRAPH["empty_graph"]()
        graph["nodes"] = [{"id": "corrected", "type": "topic", "label": "Tea trade",
                           "aliases": ["Gongfu tea preparation"]}]
        self.write("graph.json", graph)
        self.sync()
        self.assertEqual(self.match()["matches"], {"tea": "corrected"})
        graph["nodes"][0]["aliases"] = []
        self.write("graph.json", graph)
        self.assertEqual(self.match()["matches"], {})
        self.sync()
        self.assertNotEqual(self.match()["matches"]["tea"], "corrected")
        self.assertEqual(self.graph()["edges"], [])

    def test_explicit_typed_binding_is_private_and_survives_unchanged_sync(self):
        self.seed_creator()
        before = (self.model / "profile.json").read_bytes()
        self.sync([{"anchor_id": "tea", "node_id": "creator"}])
        self.assertEqual(self.match()["matches"], {"tea": "creator"})
        self.assertEqual(self.sync()["status"], "current")
        self.assertEqual(before, (self.model / "profile.json").read_bytes())
        self.assertNotIn("anchor_id", json.dumps(self.graph()))

    def test_changed_scope_invalidates_prior_typed_binding(self):
        self.seed_creator()
        self.sync([{"anchor_id": "tea", "node_id": "creator"}])
        changed = copy.deepcopy(self.profile)
        changed["interests"][0]["topic"] = "Unrelated narrow topic"
        self.assertEqual(self.match(changed)["matches"], {})
        self.write("profile.json", changed)
        result = self.sync()
        self.assertTrue(result["warnings"])
        self.assertNotEqual(self.match(changed)["matches"]["tea"], "creator")

    def test_changed_source_evidence_invalidates_prior_binding(self):
        self.seed_creator()
        self.sync([{"anchor_id": "tea", "node_id": "creator"}])
        changed = copy.deepcopy(self.profile)
        changed["provenance"][0]["locator"] = "Corrected source"
        self.assertEqual(self.match(changed)["matches"], {})

    def test_retargeted_graph_node_invalidates_saved_binding(self):
        self.seed_creator()
        self.sync([{"anchor_id": "tea", "node_id": "creator"}])
        graph = self.graph()
        graph["nodes"][0]["label"] = "Different Creator"
        self.write("graph.json", graph)
        self.assertEqual(self.match()["matches"], {})

    def test_new_interest_automatically_represented_and_removed_interest_unmapped(self):
        self.sync()
        self.profile["interests"] = [{"id": "other", "topic": "Other narrow interest", "kind": "explicit"}]
        self.write("profile.json", self.profile)
        self.sync()
        self.assertEqual(set(self.match()["matches"]), {"other"})
        self.assertEqual(len(self.graph()["nodes"]), 2)  # Content identities are not preference records.

    def test_transient_quoted_negative_and_unsubstantiated_interests_not_seeded(self):
        for fields in ({"scope": "current_request"}, {"reference_only": True}, {"signal": "disliked"},
                       {"kind": "inferred", "source_provenance": []}):
            record = dict(self.profile["interests"][0], **fields)
            record["id"] = "excluded-" + str(len(self.profile["interests"]))
            record["topic"] = record["id"]
            self.profile["interests"].append(record)
        self.write("profile.json", self.profile)
        self.assertEqual(self.sync()["counts"]["eligible_interests"], 1)
        self.assertEqual(set(self.match()["matches"]), {"tea"})

    def test_ambiguous_exact_match_stays_pending_without_duplicate_identity(self):
        graph = GRAPH["empty_graph"]()
        graph["nodes"] = [{"id": key, "type": "topic", "label": key,
                           "aliases": ["Gongfu tea preparation"]} for key in ("one", "two")]
        self.write("graph.json", graph)
        result = self.sync()
        self.assertEqual(result["counts"]["unresolved_interests"], 1)
        self.assertEqual(result["counts"]["nodes_added"], 0)
        self.assertTrue(result["warnings"])

    def test_invalid_explicit_mapping_is_never_silently_retargeted(self):
        self.profile["interests"][0]["graph_node_id"] = "missing"
        self.write("profile.json", self.profile)
        result = self.sync()
        self.assertEqual(result["counts"]["represented_interests"], 0)
        self.assertEqual(result["counts"]["nodes_added"], 0)
        self.assertTrue(result["warnings"])
        self.assertFalse((self.model / "graph.json").exists())

    def test_unknown_duplicate_and_conflicting_bindings_fail_before_writes(self):
        self.seed_creator()
        for bindings in ([{"anchor_id": "unknown", "node_id": "creator"}],
                         [{"anchor_id": "tea", "node_id": "missing"}],
                         [{"anchor_id": "tea", "node_id": "creator"}] * 2):
            with self.subTest(bindings=bindings), self.assertRaises(ValueError):
                self.sync(bindings)
        self.profile["interests"][0]["graph_node_id"] = "some-other-node"
        self.write("profile.json", self.profile)
        with self.assertRaisesRegex(ValueError, "conflicts"):
            self.sync([{"anchor_id": "tea", "node_id": "creator"}])
        self.assertFalse((self.model / "graph-anchors.json").exists())

    def test_invalid_anchor_ids_fail_before_graph_or_mapping_writes(self):
        for identifier in (None, "", " ", 42, []):
            with self.subTest(identifier=identifier):
                self.profile["interests"][0]["id"] = identifier
                self.write("profile.json", self.profile)
                with self.assertRaisesRegex(ValueError, "nonempty strings"):
                    self.sync()
                self.assertFalse((self.model / "graph.json").exists())
                self.assertFalse((self.model / "graph-anchors.json").exists())

    def test_invalid_graph_or_sidecar_is_not_repaired(self):
        self.write("graph.json", {"wrong": "graph"})
        with self.assertRaises(ValueError):
            self.sync()
        self.assertEqual(self.graph(), {"wrong": "graph"})
        (self.model / "graph.json").unlink()
        self.write("graph-anchors.json", {"wrong": "mapping"})
        with self.assertRaises(ValueError):
            self.sync()
        self.assertFalse((self.model / "graph.json").exists())

    def test_empty_profile_creates_no_files(self):
        self.profile["interests"] = []
        self.write("profile.json", self.profile)
        before = set(self.model.iterdir())
        self.assertEqual(self.sync()["status"], "current")
        self.assertEqual(set(self.model.iterdir()), before)

    def test_graph_lock_and_symlink_mapping_fail_closed(self):
        lock = self.model / ".graph.lock"
        lock.write_text("")
        with self.assertRaisesRegex(ValueError, "writer"):
            self.sync()
        lock.unlink()
        target = self.root / "outside.json"
        target.write_text(json.dumps(API["_empty_mappings"]()))
        (self.model / "graph-anchors.json").symlink_to(target)
        with self.assertRaises(ValueError):
            self.sync()
        self.assertFalse((self.model / "graph.json").exists())

    def test_racing_profile_change_cannot_claim_success(self):
        original = API["UPDATES"]["_atomic"]
        def race(root, relative, value, check_current=None):
            if relative == "model/graph.json":
                self.write("profile.json", {"interests": []})
            return original(root, relative, value, check_current)
        with mock.patch.dict(API["UPDATES"], {"_atomic": race}):
            with self.assertRaisesRegex(ValueError, "changed"):
                self.sync()
        self.assertFalse((self.model / "graph-anchors.json").exists())
        self.assertFalse((self.model / "graph.json").exists())

    def test_graph_change_expires_research_receipt_without_rewriting_it(self):
        review = UPDATES["update_plan"](self.root, [], "fixture")
        UPDATES["complete_update"](self.root, [], review, reason="No source-supported facts in fixture.")
        receipt = (self.model / "graph-maintenance.json").read_bytes()
        self.sync()
        self.assertFalse(UPDATES["check_update"](self.root, [], "fixture")["completed"])
        self.assertEqual(receipt, (self.model / "graph-maintenance.json").read_bytes())

    def test_saved_hypothesis_remains_current_after_typed_binding_and_retrieval(self):
        self.seed_creator()
        draft = HYPOTHESES["snapshot"](self.root)
        draft["taste_hypotheses"] = [{"id": "h", "topic": "Synthetic quality", "reason": "The creator may suggest this quality.",
                                     "anchor_ids": ["tea"], "status": "testing", "evidence": []}]
        HYPOTHESES["save"](self.root, draft)
        profile = json.loads((self.model / "profile.json").read_text())
        self.sync([{"anchor_id": "tea", "node_id": "creator"}])
        result = GRAPH["frontier"](self.graph(), profile, feedback=[], history=[], seed=42,
                                   anchor_mappings=self.mappings())
        self.assertEqual(result["unmatched_anchor_ids"], [])
        self.assertEqual(HYPOTHESES["active_hypotheses"](profile)[0]["id"], "h")
        self.assertEqual(profile, json.loads((self.model / "profile.json").read_text()))

    def run_cli(self, args):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            try:
                code = CURATION["main"](args)
            except SystemExit as error:
                code = error.code
        self.assertEqual(code, 0, err.getvalue())
        return json.loads(out.getvalue())

    def test_rooted_explore_syncs_and_uses_default_graph(self):
        plan = {"scope": "broad", "mode": "wildcard", "lane_mix": {"familiar": 1, "adjacent": 0, "distant": 0},
                "constraints": {"request": "Synthetic research"}}
        plan_path = self.root / "plan.json"
        plan_path.write_text(json.dumps(plan))
        result = self.run_cli(["explore", "--root", str(self.root), "--profile", str(self.model / "profile.json"),
                               "--plan", str(plan_path), "--seed", "42", "--count", "1"])
        self.assertEqual(result["graph_anchors"]["counts"]["represented_interests"], 1)
        self.assertEqual(result["graph_frontier"]["unmatched_anchor_ids"], [])

    def test_custom_explore_graph_remains_read_only(self):
        plan = {"scope": "focused", "mode": "personal", "lane_mix": {"familiar": 1, "adjacent": 0, "distant": 0},
                "constraints": {"request": "Synthetic research"}}
        review = HYPOTHESES["maintenance_plan"](self.root, plan)
        HYPOTHESES["complete_maintenance"](
            self.root, review, "no_proposal", "Reviewed the supplied interest; no further proposal is supported.")
        plan_path, graph_path = self.root / "plan.json", self.root / "custom-graph.json"
        plan_path.write_text(json.dumps(plan))
        graph_path.write_text(json.dumps(GRAPH["empty_graph"]()))
        before = graph_path.read_bytes()
        result = self.run_cli(["explore", "--root", str(self.root), "--profile", str(self.model / "profile.json"),
                               "--graph", str(graph_path), "--plan", str(plan_path), "--count", "1"])
        self.assertNotIn("graph_anchors", result)
        self.assertFalse((self.model / "graph-anchors.json").exists())
        self.assertEqual(before, graph_path.read_bytes())

    def test_update_plan_cli_synchronizes_before_fingerprinting(self):
        research = self.root / "research.json"
        research.write_text("[]")
        plan = self.run_cli(["graph-update-plan", "--root", str(self.root), "--research", str(research),
                            "--batch-id", "fixture"])
        self.assertEqual(plan["counts"]["nodes"], 1)
        saved = UPDATES["complete_update"](self.root, [], plan, reason="No supported relationships.")
        self.assertEqual(saved["receipt"]["outcome"], "no_supported_changes")
        self.assertTrue(UPDATES["check_update"](self.root, [], "fixture")["completed"])


if __name__ == "__main__":
    unittest.main()
