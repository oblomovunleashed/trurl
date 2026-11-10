"""Content graph behavior using fictional public fixtures only.

These tests never read or write the user's private model or external accounts.
"""
import copy
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch


MODULE = Path(__file__).resolve().parents[1] / "skills/trurl/scripts/graph.py"
SPEC = importlib.util.spec_from_file_location("curation_graph", MODULE)
graph = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(graph)


def node(identifier, kind="topic", **values):
    result = {"id": identifier, "type": kind, "label": "Synthetic " + identifier}
    result.update(values)
    return result


def edge(identifier, source, target, relation="related_to", **values):
    result = {"id": identifier, "source": source, "relation": relation, "target": target,
              "status": "verified", "confidence": .8, "source_provenance": ["fixture-source"],
              "assertion_method": "synthetic_fixture"}
    result.update(values)
    return result


def fixture(nodes=None, edges=None):
    return {"schema_version": 1,
            "sources": [{"id": "fixture-source", "kind": "synthetic_fixture",
                         "locator": "fictional public test fixture", "checked_at": "2026-11-03"}],
            "nodes": nodes or [node("a"), node("b"), node("c")],
            "edges": edges if edges is not None else [edge("a-b", "a", "b"), edge("b-c", "b", "c")]}


def profile(*interests):
    return {"interests": list(interests) or [{"id": "interest-a", "topic": "Synthetic a",
                                            "kind": "explicit", "confidence": 1.0,
                                            "knowledge_level": "unknown", "knowledge_evidence": []}]}


REGISTRY = {"version": "synthetic-registry-1", "domains": [
    {"field": "Synthetic field %d" % number, "category": category}
    for number, category in enumerate(["one"] * 10 + ["two", "three"])
]}


class GraphValidationTests(unittest.TestCase):
    def test_empty_graph_valid_and_independent(self):
        first, second = graph.empty_graph(), graph.empty_graph()
        self.assertEqual(graph.validate_graph(first)["counts"], {"sources": 0, "nodes": 0, "edges": 0})
        first["nodes"].append(node("new"))
        self.assertEqual(second["nodes"], [])

    def test_all_supported_typed_relations_validate(self):
        value = fixture([node("w", "work"), node("t"), node("u"), node("q", "quality"), node("c", "creator")],
                        [edge("e1", "w", "t", "about"), edge("e2", "w", "q", "has_quality"),
                         edge("e3", "w", "c", "created_by"), edge("e4", "t", "u", "broader_than")])
        original = copy.deepcopy(value)
        self.assertTrue(graph.validate_graph(value)["valid"])
        self.assertEqual(value, original)

    def test_user_relations_wrong_types_dangling_and_duplicate_ids_fail(self):
        mutations = [
            lambda g: g["edges"][0].update(relation="likes"),
            lambda g: g["edges"][0].update(relation="knows"),
            lambda g: g["edges"][0].update(relation="viewed"),
            lambda g: g["edges"][0].update(relation="about"),
            lambda g: g["edges"][0].update(target="missing"),
            lambda g: g["nodes"].append(copy.deepcopy(g["nodes"][0])),
            lambda g: g["nodes"][0].update(type="user"),
            lambda g: g["nodes"][0].update(type=[]),
            lambda g: g["edges"][0].update(status=[]),
        ]
        for mutate in mutations:
            value = fixture()
            mutate(value)
            with self.subTest(value=value), self.assertRaises(ValueError):
                graph.validate_graph(value)

    def test_provenance_and_real_iso_date_are_required_for_verified_edges(self):
        for provenance in ([], ["missing"], ["fixture-source", "fixture-source"], "fixture-source"):
            value = fixture()
            value["edges"][0]["source_provenance"] = provenance
            with self.subTest(provenance=provenance), self.assertRaises(ValueError):
                graph.validate_graph(value)
        for timestamp in (None, "unknown", "yesterday", "2026-02-30", "2026-11-03T25:12:00Z"):
            value = fixture()
            value["sources"][0]["checked_at"] = timestamp
            with self.subTest(timestamp=timestamp), self.assertRaises(ValueError):
                graph.validate_graph(value)
        for timestamp in ("2026-11-03", "2026-11-03T12:30:00Z", "2026-11-03T12:30:00+01:00"):
            value = fixture()
            value["sources"][0]["checked_at"] = timestamp
            self.assertTrue(graph.validate_graph(value)["valid"])

    def test_hypothesis_can_retain_unknown_source_without_becoming_traversable(self):
        for unknown in (None, "unknown"):
            value = fixture()
            value["sources"][0]["checked_at"] = unknown
            for relation in value["edges"]:
                relation["status"] = "hypothesis"
            self.assertTrue(graph.validate_graph(value)["valid"])
            self.assertEqual(graph.frontier(value, profile(), seed=1)["connected"], [])

    def test_optional_canonical_identity_requires_http_url_and_locator_can_be_local(self):
        for canonical in ("javascript:alert(1)", "not a URL", "https://[", "https:///missing-host",
                          "https://example.com:invalid/work", "https://user:secret@example.com/work", "https://bad host/work"):
            value = fixture()
            value["nodes"][0]["canonical_url"] = canonical
            with self.subTest(canonical=canonical), self.assertRaises(ValueError):
                graph.validate_graph(value)
        value = fixture()
        value["nodes"][0]["canonical_url"] = "https://example.com/synthetic-work?part=1"
        value["sources"][0]["locator"] = "a fictional local fixture"
        self.assertTrue(graph.validate_graph(value)["valid"])

    def test_confidence_must_be_finite_numeric_and_not_boolean(self):
        for confidence in (float("nan"), float("inf"), -.1, 1.1, True, "0.8"):
            value = fixture()
            value["edges"][0]["confidence"] = confidence
            with self.subTest(confidence=confidence), self.assertRaises(ValueError):
                graph.validate_graph(value)


class ConnectedFrontierTests(unittest.TestCase):
    def test_public_personal_anchors_reuses_gating_and_returns_independent_evidence(self):
        current = profile(
            {"id": "personal", "topic": "Synthetic a", "kind": "tentative", "confidence": .4,
             "source_provenance": [{"id": "synthetic-personal-source", "locator": "synthetic-observation"}]},
            {"id": "quoted", "topic": "Synthetic b", "kind": "explicit", "quoted": True},
            {"id": "assistant", "topic": "Synthetic c", "kind": "explicit", "source_kind": "assistant_suggestion"},
            {"id": "avoid", "topic": "Synthetic d", "kind": "explicit", "signal": "avoid"})
        original = copy.deepcopy(current)
        anchors = graph.personal_anchors(current)
        self.assertEqual([anchor["id"] for anchor in anchors], ["personal"])
        self.assertEqual(anchors[0]["knowledge_level"], "unknown")
        self.assertEqual(anchors[0]["confidence"], .4)
        anchors[0]["source_provenance"][0]["locator"] = "changed-output-copy"
        self.assertEqual(current, original)
        for invalid in (None, [], "profile", {"interests": {}}):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                graph.personal_anchors(invalid)

    def test_paths_keep_direction_source_ids_and_anchor_uncertainty(self):
        value = fixture([node("a"), node("w", "work"), node("c", "creator")],
                        [edge("w-a", "w", "a", "about", confidence=.7),
                         edge("w-c", "w", "c", "created_by", confidence=.6)])
        interest = {"id": "tentative-a", "topic": "Synthetic a", "kind": "tentative", "confidence": .4,
                    "source_provenance": ["synthetic-observation"], "supporting_words": "A tentative fixture observation"}
        result = graph.frontier(value, profile(interest), seed=3)
        route = next(r for r in result["connected"] if r["destination"]["id"] == "c")
        self.assertEqual(route["node_ids"], ["a", "w", "c"])
        self.assertEqual(route["edge_ids"], ["w-a", "w-c"])
        self.assertEqual([step["traversed_reverse"] for step in route["steps"]], [True, False])
        self.assertEqual(route["steps"][0]["source"], "w")
        self.assertEqual(route["anchor_evidence"]["confidence"], .4)
        self.assertEqual(route["anchor_evidence"]["knowledge_level"], "unknown")
        self.assertEqual(route["anchor_evidence"]["source_provenance"], ["synthetic-observation"])
        self.assertEqual(route["evidence_confidence_min"], .6)
        self.assertNotIn("preference", route)

    def test_hypothesis_retracted_and_low_confidence_edges_are_not_traversed(self):
        value = fixture([node("a"), node("b"), node("c"), node("d"), node("e")],
                        [edge("a-b", "a", "b", status="hypothesis"), edge("a-c", "a", "c", status="retracted"),
                         edge("a-d", "a", "d", confidence=.499), edge("a-e", "a", "e", confidence=.5)])
        result = graph.frontier(value, profile(), seed=1)
        self.assertEqual([r["destination"]["id"] for r in result["connected"]], ["e"])

    def test_no_context_or_unmatched_interest_returns_no_arbitrary_fallback(self):
        self.assertEqual(graph.frontier(fixture(), {"interests": []}, seed=1)["connected"], [])
        result = graph.frontier(fixture(), profile({"id": "unmatched", "kind": "explicit", "topic": "Synthetic absent"}), seed=1)
        self.assertEqual(result["connected"], [])
        self.assertEqual(result["open"], [])
        self.assertEqual(result["unmatched_anchor_ids"], ["unmatched"])

    def test_only_evidenced_positive_interest_records_become_anchors(self):
        interests = [
            {"id": "unsupported", "kind": "inferred", "topic": "Synthetic a", "confidence": .9},
            {"id": "not-evidence", "kind": "tentative", "topic": "Synthetic a", "source_provenance": [True, {}]},
            {"id": "rejected", "kind": "explicit", "topic": "Synthetic a", "status": "rejected"},
            {"id": "reference", "kind": "explicit", "topic": "Synthetic a", "signal": "reference_only"},
            {"id": "illustrative", "kind": "explicit", "topic": "Synthetic a", "illustrative": True},
            {"id": "negative", "kind": "explicit", "topic": "Synthetic a", "signal": "avoid"},
            {"id": "zero", "kind": "explicit", "topic": "Synthetic a", "confidence": 0},
        ]
        self.assertEqual(graph.frontier(fixture(), profile(*interests), seed=1)["connected"], [])
        interests.append({"id": "evidenced", "kind": "inferred", "topic": "Synthetic a", "confidence": .6,
                          "source_provenance": ["synthetic-source"]})
        result = graph.frontier(fixture(), profile(*interests), seed=1)
        self.assertTrue(result["connected"])
        self.assertTrue(all(r["anchor_id"] == "evidenced" for r in result["connected"]))

    def test_reference_and_negative_valence_never_become_positive_anchors(self):
        for valence in ("reference_only", "reference-only", "avoid", "disliked", "dislike", "negative", "not_for_me"):
            current = profile({"id": "not-positive", "kind": "explicit", "topic": "Synthetic a", "valence": valence,
                               "source_provenance": ["synthetic-current-input"]})
            with self.subTest(valence=valence):
                result = graph.frontier(fixture(), current, seed=3)
                self.assertEqual(result["connected"], [])
                self.assertEqual(result["unmatched_anchor_ids"], [])

    def test_exact_alias_match_and_explicit_non_topic_node_anchor(self):
        value = fixture([node("a", aliases=["Synthetic other name"]), node("w", "work")], [edge("w-a", "w", "a", "about")])
        interests = [
            {"id": "alias", "kind": "explicit", "topic": "  SYNTHETIC other-name  "},
            {"id": "partial", "kind": "explicit", "topic": "Synthetic other"},
        ]
        result = graph.frontier(value, profile(*interests), seed=1)
        self.assertEqual([r["anchor_id"] for r in result["connected"]], ["alias"])
        self.assertEqual(result["unmatched_anchor_ids"], ["partial"])
        result = graph.frontier(value, profile({"id": "work-anchor", "kind": "explicit", "graph_node_id": "w"}), seed=1)
        self.assertEqual(result["connected"][0]["destination"]["id"], "a")

    def test_ambiguous_label_requires_node_id(self):
        value = fixture([node("a"), node("b", label="Synthetic a"), node("c")])
        result = graph.frontier(value, profile(), seed=1)
        self.assertEqual(result["connected"], [])
        self.assertEqual(result["unmatched_anchor_ids"], ["interest-a"])
        self.assertTrue(any("Ambiguous" in warning for warning in result["warnings"]))

    def test_cycles_are_bounded_and_do_not_add_transitive_edges(self):
        value = fixture(edges=[edge("a-b", "a", "b"), edge("b-c", "b", "c"), edge("c-a", "c", "a")])
        before = copy.deepcopy(value)
        result = graph.frontier(value, profile(), seed=1, max_hops=3, count=10)
        self.assertEqual(len(result["connected"]), 2)
        self.assertTrue(all(len(r["node_ids"]) == len(set(r["node_ids"])) for r in result["connected"]))
        self.assertEqual(value, before)
        self.assertTrue(result["graph_changed"] is False)
        one_hop = graph.frontier(fixture(), profile(), seed=1, max_hops=1)
        self.assertEqual([r["destination"]["id"] for r in one_hop["connected"]], ["b"])

    def test_neighbor_cap_seed_replay_and_anchor_rotation_limit_hub_dominance(self):
        nodes = [node("a"), node("z")] + [node("spoke-%d" % n) for n in range(20)] + [node("small")]
        edges = [edge("edge-%d" % n, "a", "spoke-%d" % n) for n in range(20)] + [edge("small-edge", "z", "small")]
        value = fixture(nodes, edges)
        interests = profile({"id": "hub", "kind": "explicit", "graph_node_id": "a"},
                            {"id": "independent", "kind": "explicit", "graph_node_id": "z"})
        first = graph.frontier(value, interests, count=2, max_hops=1, max_neighbors=3, seed=12)
        self.assertEqual(first, graph.frontier(value, interests, count=2, max_hops=1, max_neighbors=3, seed=12))
        self.assertEqual({r["anchor_id"] for r in first["connected"]}, {"hub", "independent"})
        capped = graph.frontier(value, profile({"id": "hub", "kind": "explicit", "graph_node_id": "a"}),
                                count=30, max_hops=1, max_neighbors=3, seed=12)
        self.assertEqual(len(capped["connected"]), 3)
        draws = {tuple(r["destination"]["id"] for r in graph.frontier(value, interests, count=2, max_hops=1, seed=s)["connected"])
                 for s in range(6)}
        self.assertGreater(len(draws), 1)

    def test_destinations_are_unique_across_anchors_and_new_anchor_is_independent(self):
        value = fixture([node("a"), node("z"), node("b"), node("c")],
                        [edge("a-b", "a", "b"), edge("z-b", "z", "b"), edge("z-c", "z", "c")])
        prior = graph.frontier(value, profile(), seed=6, max_hops=1)
        self.assertEqual({r["destination"]["id"] for r in prior["connected"]}, {"b"})
        extended = profile({"id": "a", "kind": "explicit", "topic": "Synthetic a"},
                           {"id": "z", "kind": "explicit", "topic": "Synthetic z"})
        result = graph.frontier(value, extended, count=5, seed=6, max_hops=1)
        self.assertEqual({r["destination"]["id"] for r in result["connected"]}, {"b", "c"})
        self.assertEqual(len(result["connected"]), 2)
        self.assertEqual(next(r for r in result["connected"] if r["destination"]["id"] == "c")["anchor_id"], "z")

    def test_invalid_limits_and_seed_are_rejected(self):
        for options in ({"max_hops": 0}, {"max_hops": 4}, {"max_hops": True}, {"max_neighbors": 0},
                        {"max_neighbors": 101}, {"count": 0}, {"count": True}, {"seed": "1"}):
            with self.subTest(options=options), self.assertRaises(ValueError):
                graph.frontier(fixture(), profile(), **options)


class ConvergingRouteTests(unittest.TestCase):
    def anchors(self, *names):
        return profile(*[{"id": "interest-" + name, "kind": "explicit", "graph_node_id": name}
                         for name in names])

    def test_single_destination_keeps_second_anchor_direction_and_its_own_confidence(self):
        value = fixture([node("a"), node("z"), node("b")],
                        [edge("a-b", "a", "b", confidence=.9), edge("b-z", "b", "z", confidence=.6)])
        current = self.anchors("a", "z")
        for seed in range(6):
            result = graph.frontier(value, current, seed=seed, count=1, max_hops=1)
            self.assertEqual(len(result["connected"]), 1)
            primary = result["connected"][0]
            alternate = primary["converging_route"]
            self.assertEqual({primary["anchor_id"], alternate["anchor_id"]}, {"interest-a", "interest-z"})
            self.assertEqual(alternate["node_ids"][-1], primary["destination"]["id"])
            expected = (["a-b"], [False], .9) if alternate["anchor_id"] == "interest-a" else (["b-z"], [True], .6)
            self.assertEqual((alternate["edge_ids"], alternate["traversed_reverse"], alternate["evidence_confidence_min"]), expected)
            self.assertEqual(set(alternate), {"anchor_id", "node_ids", "edge_ids", "traversed_reverse", "evidence_confidence_min"})
            self.assertFalse(result["convergence_search"]["truncated"])
            self.assertTrue(any("not independent preference evidence" in item for item in result["limits"]))

    def test_hop_limit_applies_to_alternate_and_original_anchor_is_not_a_bridge(self):
        value = fixture([node(name) for name in ("a", "z", "b", "middle")],
                        [edge("a-b", "a", "b"), edge("z-middle", "z", "middle"), edge("middle-b", "middle", "b")])
        current = self.anchors("a", "z")
        short = graph.frontier(value, current, seed=0, count=8, max_hops=1)
        self.assertTrue(all("converging_route" not in route for route in short["connected"]))
        longer = graph.frontier(value, current, seed=0, count=8, max_hops=2)
        target = next(route for route in longer["connected"] if route["destination"]["id"] == "b")
        self.assertEqual(target["converging_route"]["node_ids"], ["z", "middle", "b"])
        via_primary = fixture([node(name) for name in ("a", "z", "b")],
                              [edge("a-b", "a", "b"), edge("z-a", "z", "a")])
        result = graph.frontier(via_primary, current, seed=0, count=1, max_hops=2)
        self.assertEqual(result["connected"][0]["anchor_id"], "interest-a")
        self.assertNotIn("converging_route", result["connected"][0])

    def test_added_context_is_capped_at_one_route_each_for_two_destinations(self):
        names = ["destination-%d" % index for index in range(6)]
        value = fixture([node(name) for name in ["a", "z", "third"] + names],
                        [edge(anchor + "-" + target, anchor, target)
                         for anchor in ("a", "z", "third") for target in names])
        result = graph.frontier(value, self.anchors("a", "z", "third"), seed=3, count=6, max_hops=1)
        additions = [route["converging_route"] for route in result["connected"] if "converging_route" in route]
        self.assertEqual(len(result["connected"]), 6)
        self.assertEqual(len(additions), 2)
        self.assertTrue(all(isinstance(route, dict) and "destination" not in route and "anchor_evidence" not in route
                            for route in additions))
        self.assertEqual(result["convergence_search"]["max_additional_routes"], 2)
        self.assertTrue(result["convergence_search"]["truncated"])

    def test_same_graph_node_in_multiple_personal_records_is_not_convergence(self):
        current = profile({"id": "first", "kind": "explicit", "graph_node_id": "a"},
                          {"id": "alias", "kind": "explicit", "topic": "Synthetic a"})
        result = graph.frontier(fixture(), current, seed=3, count=1)
        self.assertNotIn("converging_route", result["connected"][0])
        self.assertNotIn("convergence_search", result)

    def test_disjoint_reachable_anchors_add_no_output_overhead(self):
        value = fixture([node(name) for name in ("a", "z", "b", "c")],
                        [edge("a-b", "a", "b"), edge("z-c", "z", "c")])
        current = self.anchors("a", "z")
        with patch.object(graph, "_converging_routes", return_value=None):
            original = graph.frontier(value, current, seed=1, count=2)
        result = graph.frontier(value, current, seed=1, count=2)
        self.assertEqual(len(result["connected"]), 2)
        self.assertEqual(result, original)

    def test_alternate_paths_use_only_eligible_edges_and_personal_anchors(self):
        for marking in ({"status": "hypothesis"}, {"status": "retracted"}, {"confidence": .499}):
            value = fixture([node(name) for name in ("a", "z", "b")],
                            [edge("a-b", "a", "b"), edge("z-b", "z", "b", **marking)])
            with self.subTest(marking=marking):
                result = graph.frontier(value, self.anchors("a", "z"), seed=1, count=1, max_hops=1)
                self.assertNotIn("converging_route", result["connected"][0])
        value["edges"][1] = edge("z-b", "z", "b")
        current = self.anchors("a", "z")
        current["interests"][1]["source_kind"] = "assistant_suggestion"
        result = graph.frontier(value, current, seed=1, count=1)
        self.assertNotIn("convergence_search", result)

    def test_extra_search_has_a_global_expansion_budget_and_reports_truncation(self):
        branches = ["branch-%d" % number for number in range(80)]
        value = fixture([node(name) for name in ["a", "z", "b"] + branches],
                        [edge("a-b", "a", "b")] + [edge("b-" + name, "b", name) for name in branches])
        result = graph.frontier(value, self.anchors("a", "z"), seed=1, count=1, max_hops=3, max_neighbors=100)
        self.assertNotIn("converging_route", result["connected"][0])
        search = result["convergence_search"]
        self.assertEqual(search["node_expansions"], search["max_node_expansions"])
        self.assertEqual(search["node_expansions"], 64)
        self.assertTrue(search["truncated"])

    def test_convergence_does_not_change_primary_or_open_draws_and_never_mutates_inputs(self):
        value = fixture([node(name) for name in ("a", "z", "b", "c", "d")],
                        [edge("a-b", "a", "b"), edge("z-b", "z", "b"),
                         edge("a-c", "a", "c"), edge("z-d", "z", "d")])
        current, history = self.anchors("a", "z"), [{"topics": ["Synthetic history"]}]
        inputs = (value, current, history, copy.deepcopy(REGISTRY))
        before = copy.deepcopy(inputs)
        for seed in range(8):
            options = dict(seed=seed, count=4, max_hops=2, history=history, registry=inputs[3], allow_open=True, open_count=1)
            with patch.object(graph, "_converging_routes", return_value=None):
                original = graph.frontier(value, current, **options)
            result = graph.frontier(value, current, **options)
            self.assertEqual(result, graph.frontier(value, current, **options))
            primary = [{key: val for key, val in route.items() if key != "converging_route"}
                       for route in result["connected"]]
            self.assertEqual(primary, original["connected"])
            self.assertEqual(result["open"], original["open"])
            self.assertEqual(result["eligible_pool"], original["eligible_pool"])
            self.assertEqual(inputs, before)


class OpenFrontierTests(unittest.TestCase):
    def test_open_opt_in_cap_and_empty_context(self):
        for options in ({"open_count": 1}, {"allow_open": True, "open_count": 2, "count": 5},
                        {"allow_open": True, "open_count": -1}, {"allow_open": "yes", "open_count": 1}):
            with self.subTest(options=options), self.assertRaises(ValueError):
                graph.frontier(graph.empty_graph(), {"interests": []}, **options)
        result = graph.frontier(graph.empty_graph(), {"interests": []}, seed=2, count=1,
                                allow_open=True, open_count=1, registry=REGISTRY)
        self.assertEqual(result["connected"], [])
        self.assertEqual(len(result["open"]), 1)
        self.assertEqual(result["open"][0]["personal_fit_status"], "unknown")
        self.assertEqual(result["open"][0]["selection_channel"], "open")

    def test_category_stratified_draw_does_not_let_large_stratum_dominate(self):
        result = graph.frontier(graph.empty_graph(), {"interests": []}, seed=3, count=12,
                                allow_open=True, open_count=3, registry=REGISTRY)
        self.assertEqual({r["category"] for r in result["open"]}, {"one", "two", "three"})
        self.assertEqual(len(result["eligible_strata"]["one"]), 10)
        self.assertEqual(result["registry_version"], REGISTRY["version"])
        self.assertEqual(len(result["eligible_pool"]), 12)
        self.assertEqual(result, graph.frontier(graph.empty_graph(), {"interests": []}, seed=3, count=12,
                                               allow_open=True, open_count=3, registry=REGISTRY))

    def test_open_excludes_known_aliases_connected_destinations_and_recent_history(self):
        registry = {"domains": [{"field": "Synthetic " + name, "category": "fixture"}
                                for name in ("a", "alias", "b", "history", "available")]}
        current = profile({"id": "a", "kind": "explicit", "topic": "Synthetic a", "aliases": ["Synthetic alias"]})
        history = [{"topics": ["Synthetic history"]}]
        result = graph.frontier(fixture(), current, history=history, count=4, max_hops=1, seed=1,
                                allow_open=True, open_count=1, registry=registry)
        self.assertEqual(result["eligible_pool"], ["Synthetic available"])
        self.assertEqual(result["open"][0]["field"], "Synthetic available")

    def test_source_only_records_neither_anchor_nor_suppress_an_open_field(self):
        registry = {"version": "synthetic-one-field", "domains": [{"field": "Synthetic a", "category": "fixture"}]}
        markings = [{"valence": "reference_only"}, {"reference_only": True}, {"illustrative": True},
                    {"quoted": True}, {"assistant_only": True}, {"origin": "quoted_third_party"},
                    {"source_kind": "assistant_suggestion"}, {"basis": "assistant_characterization"},
                    {"source_provenance": [{"kind": "third_party_quote", "locator": "synthetic-quote"}]}]
        for marking in markings:
            interest = {"id": "source-only", "kind": "explicit", "topic": "Synthetic a",
                        "source_provenance": ["synthetic-nonpersonal-source"]}
            interest.update(marking)
            current = profile(interest)
            original = copy.deepcopy(current)
            with self.subTest(marking=marking):
                connected = graph.frontier(fixture(), current, seed=1701)
                opened = graph.frontier(graph.empty_graph(), current, count=1, seed=1701,
                                        allow_open=True, open_count=1, registry=registry)
                self.assertEqual(connected["connected"], [])
                self.assertEqual(opened["eligible_pool"], ["Synthetic a"])
                self.assertEqual(opened["open"][0]["field"], "Synthetic a")
                self.assertEqual(current, original)

    def test_genuine_negative_constraints_exclude_open_fields_without_becoming_anchors(self):
        registry = {"domains": [{"field": "Synthetic a", "category": "fixture"}]}
        for marking in ({"signal": "avoid"}, {"valence": "negative"}, {"polarity": "dislike"}):
            current = profile(dict({"id": "actual-avoidance", "kind": "explicit", "topic": "Synthetic a",
                                    "source_provenance": ["synthetic-current-user-input"]}, **marking))
            with self.subTest(marking=marking):
                result = graph.frontier(fixture(), current, count=4, seed=3,
                                        allow_open=True, open_count=1, registry=registry)
                self.assertEqual(result["connected"], [])
                self.assertEqual(result["eligible_pool"], [])
                self.assertEqual(result["open"], [])
        unsupported = profile({"id": "unsupported", "kind": "inferred", "topic": "Synthetic a", "signal": "avoid"})
        result = graph.frontier(graph.empty_graph(), unsupported, count=1, seed=3,
                                allow_open=True, open_count=1, registry=registry)
        self.assertEqual(result["open"][0]["field"], "Synthetic a")

    def test_graph_anchor_aliases_are_excluded_and_open_seed_is_independent_of_traversal(self):
        registry = copy.deepcopy(REGISTRY)
        registry["domains"].append({"field": "Synthetic graph alias", "category": "alias"})
        value = fixture([node("a", aliases=["Synthetic graph alias"]), node("b"), node("c")])
        first = graph.frontier(value, profile(), seed=1, count=4, max_hops=1,
                               allow_open=True, open_count=1, registry=registry)
        second = graph.frontier(value, profile(), seed=1, count=4, max_hops=2,
                                allow_open=True, open_count=1, registry=registry)
        self.assertNotIn("Synthetic graph alias", first["eligible_pool"])
        self.assertEqual(first["open"], second["open"])

    def test_no_mutation_and_generated_seed_replays(self):
        values = (fixture(), profile(), [{"topics": ["Synthetic history"]}], copy.deepcopy(REGISTRY))
        original = copy.deepcopy(values)
        result = graph.frontier(values[0], values[1], history=values[2], count=4,
                                allow_open=True, open_count=1, registry=values[3])
        self.assertEqual(values, original)
        self.assertEqual(result, graph.frontier(values[0], values[1], history=values[2], seed=result["seed"], count=4,
                                               allow_open=True, open_count=1, registry=values[3]))
        self.assertFalse(result["profile_changed"])

    def test_exhausted_pool_reports_shortfall_without_reintroducing_exclusions(self):
        registry = {"domains": [{"field": "Synthetic a", "category": "fixture"}]}
        result = graph.frontier(graph.empty_graph(), profile(), count=4, seed=1,
                                allow_open=True, open_count=1, registry=registry)
        self.assertEqual(result["open"], [])
        self.assertEqual(result["eligible_pool"], [])
        self.assertTrue(any("cannot fill" in warning for warning in result["warnings"]))

    def test_invalid_registry_is_rejected_only_when_open_is_requested(self):
        invalid = {"domains": [{"field": "Synthetic field"}]}
        self.assertTrue(graph.frontier(fixture(), profile(), registry=invalid, seed=1)["connected"])
        with self.assertRaises(ValueError):
            graph.frontier(fixture(), profile(), registry=invalid, count=4, allow_open=True, open_count=1)


class GraphCommandTests(unittest.TestCase):
    def test_read_only_commands_with_explicit_synthetic_files_and_jsonl_history(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            graph_path, profile_path, history_path = root / "graph.json", root / "profile.json", root / "history.jsonl"
            graph_path.write_text(json.dumps(fixture()), encoding="utf-8")
            profile_path.write_text(json.dumps(profile()), encoding="utf-8")
            history_path.write_text(json.dumps({"topics": ["Synthetic history"]}) + "\n", encoding="utf-8")
            originals = {path: path.read_bytes() for path in root.iterdir()}
            check = subprocess.run([sys.executable, str(MODULE), "graph-check", "--graph", str(graph_path)], capture_output=True, text=True)
            self.assertEqual(check.returncode, 0, check.stderr)
            self.assertTrue(json.loads(check.stdout)["valid"])
            discover = subprocess.run([sys.executable, str(MODULE), "frontier", "--graph", str(graph_path),
                                       "--profile", str(profile_path), "--history", str(history_path), "--seed", "7"], capture_output=True, text=True)
            self.assertEqual(discover.returncode, 0, discover.stderr)
            self.assertEqual(json.loads(discover.stdout)["seed"], 7)
            self.assertEqual({path: path.read_bytes() for path in root.iterdir()}, originals)

    def test_invalid_graph_command_returns_clean_error(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "invalid.json"
            path.write_text(json.dumps({"schema_version": 1}), encoding="utf-8")
            result = subprocess.run([sys.executable, str(MODULE), "graph-check", "--graph", str(path)], capture_output=True, text=True)
            self.assertEqual(result.returncode, 2)
            self.assertIn("error:", result.stderr)
            self.assertNotIn("Traceback", result.stderr)


if __name__ == "__main__":
    unittest.main()
