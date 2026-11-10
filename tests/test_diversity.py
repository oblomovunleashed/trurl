"""Behavioral checks for reproducible exploration and evidence-gated diversity.

All profiles, candidates, histories, and registries in this file are synthetic.
No test reads or writes the user's private curation model.
"""
import copy
import importlib.util
from pathlib import Path
import unittest


MODULE = Path(__file__).resolve().parents[1] / "skills/trurl/scripts/diversity.py"
spec = importlib.util.spec_from_file_location("diversity", MODULE)
diversity = importlib.util.module_from_spec(spec)
spec.loader.exec_module(diversity)

AXES = ("depth", "novelty", "relevance", "surprise", "perspective_change", "entertainment")


def plan(scope="broad", lane_mix=None):
    return {
        "scope": scope,
        "effective_weights": {axis: 1.0 / len(AXES) for axis in AXES},
        "lane_mix": lane_mix or {"familiar": 0.5, "adjacent": 0.3, "distant": 0.2},
        "constraints": {"request": "A selection across different fields"},
    }


def profile(interests=None):
    return {
        "interests": interests or [],
        "media": {"enabled": ["book", "film", "scientific_paper", "youtube_video"]},
        "controls": {"knowledge_default": "unknown"},
    }


def candidate(identifier, score=4.0, **overrides):
    result = {
        "id": identifier,
        "title": "Work " + identifier,
        "creator": "Creator " + identifier,
        "canonical_url": "https://example.com/work/" + identifier,
        "medium": "book",
        "lane": "familiar",
        "topics": ["topic-" + identifier],
        "scores": {axis: score for axis in AXES},
        "constraints_passed": True,
        "credibility_passed": True,
        "verification": {
            "checked_at": "2026-11-03T12:00:00Z",
            "urls": ["https://example.com/work/" + identifier],
        },
    }
    result.update(overrides)
    return result


def selected_ids(result):
    return [item["id"] for item in result["selected"]]


def connected_plan(**policy_overrides):
    result = plan(lane_mix={"familiar": .75, "adjacent": .25, "distant": 0})
    result["mode"] = "surprise"
    result["constraints"]["request"] = "Surprise me"
    result["selection_policy"] = {
        "kind": "connected_surprise_v1", "min_relevance_score": 3.0,
        "require_personal_connection": True, "max_exploratory_fraction": .25,
        "allow_distant": False,
    }
    result["selection_policy"].update(policy_overrides)
    return result


def connected_candidate(identifier, **overrides):
    values = {"personal_connection": {
        "basis": "tentative_interest", "anchor": "computing-observation",
        "explanation": "Connects computation to the mechanisms of biological evolution.",
    }}
    values.update(overrides)
    return candidate(identifier, **values)


def open_plan(scope="broad"):
    result = plan(scope, {"familiar": .5, "adjacent": .25, "distant": .25})
    result["mode"] = "open"
    result["constraints"]["request"] = "Try a new area"
    result["selection_policy"] = {
        "kind": "open_exploration_v1", "min_relevance_score": 3,
        "require_personal_connection": True, "max_open_fraction": .25,
        "max_exploratory_fraction": .25, "allow_distant": True,
    }
    return result


def open_candidate(identifier, **overrides):
    values = {"lane": "distant", "personal_fit_status": "unknown",
              "value_rationale": "Offers a concrete account of a documented process through accessible original evidence."}
    values.update(overrides)
    result = candidate(identifier, **values)
    result["scores"]["relevance"] = None
    return result


def synthetic_graph():
    return {"schema_version": 1,
            "sources": [{"id": "source-fixture", "kind": "synthetic_fixture", "locator": "fixture://graph-test", "checked_at": "2026-11-03"}],
            "nodes": [{"id": "topic-alpha", "type": "topic", "label": "Synthetic field alpha"},
                      {"id": "topic-beta", "type": "topic", "label": "Synthetic process beta"}],
            "edges": [{"id": "edge-alpha-beta", "source": "topic-alpha", "relation": "related_to", "target": "topic-beta",
                       "status": "verified", "confidence": .8, "source_provenance": ["source-fixture"], "assertion_method": "synthetic fixture"}]}


class ExplorationTests(unittest.TestCase):
    def setUp(self):
        fields = (
            "bell casting", "cave surveying", "choral singing", "cloud physics",
            "glass conservation", "lichen ecology", "medieval navigation", "oral history",
            "paper engineering", "puppet theatre", "soil microscopy", "tide prediction",
        )
        self.registry = {
            "version": "synthetic-test-v1",
            "domains": [{"field": field, "category": "synthetic"} for field in fields],
        }
        self.plan = plan(lane_mix={"familiar": 0, "adjacent": 0, "distant": 1})
        self.profile = profile()

    def test_seed_replays_exact_pool_and_briefs(self):
        first = diversity.explore(self.plan, self.profile, seed=37, count=5, registry=self.registry)
        replay = diversity.explore(self.plan, self.profile, seed=37, count=5, registry=self.registry)
        self.assertEqual(first, replay)
        self.assertEqual(first["seed"], 37)
        self.assertEqual(first["registry_version"], self.registry["version"])
        self.assertEqual(set(first["eligible_pool"]), {entry["field"] for entry in self.registry["domains"]})
        self.assertEqual(len(first["briefs"]), 5)
        for brief in first["briefs"]:
            self.assertEqual(brief["lane"], "distant")
            self.assertIn(brief["field"], first["eligible_pool"])
            self.assertTrue(brief["source_family"])
            self.assertTrue(brief["approach"])

    def test_different_seeds_really_change_the_exploration_draw(self):
        draws = {
            tuple(brief["field"] for brief in diversity.explore(
                self.plan, self.profile, seed=seed, count=5, registry=self.registry
            )["briefs"])
            for seed in range(6)
        }
        self.assertGreater(len(draws), 1)

    def test_generated_seed_is_recorded_and_can_be_replayed(self):
        first = diversity.explore(self.plan, self.profile, count=5, registry=self.registry)
        self.assertIsInstance(first["seed"], int)
        replay = diversity.explore(self.plan, self.profile, seed=first["seed"], count=5, registry=self.registry)
        self.assertEqual(first, replay)

    def test_focused_request_keeps_every_brief_inside_the_request(self):
        focused = plan(scope="focused", lane_mix={"familiar": 0, "adjacent": 0, "distant": 1})
        focused["constraints"]["request"] = "Only papers on underwater bioacoustics"
        result = diversity.explore(focused, self.profile, seed=7, count=5, registry=self.registry)
        self.assertEqual(len(result["briefs"]), 5)
        for brief in result["briefs"]:
            self.assertIsNone(brief["field"])
            self.assertEqual(brief["lane"], "focused")
            self.assertEqual(brief["request_constraint"], focused["constraints"]["request"])

    def test_explicit_niche_is_available_without_inventing_knowledge(self):
        niche = {
            "id": "synthetic-interest", "topic": "underwater bioacoustics",
            "kind": "explicit", "confidence": 1.0, "knowledge_level": "unknown",
            "knowledge_evidence": [], "source_provenance": ["synthetic-user-request"],
        }
        current_profile = profile([niche])
        before = copy.deepcopy(current_profile)
        current_plan = plan(lane_mix={"familiar": 1, "adjacent": 0, "distant": 0})
        result = diversity.explore(current_plan, current_profile, seed=11, count=2, registry=self.registry)
        self.assertTrue(result["briefs"])
        self.assertTrue(all(brief["lane"] == "familiar" for brief in result["briefs"]))
        self.assertTrue(all(brief["field"] == niche["topic"] for brief in result["briefs"]))
        self.assertEqual(current_profile, before)
        for brief in result["briefs"]:
            self.assertEqual(brief["interest_evidence"]["kind"], "explicit")
            self.assertEqual(brief["interest_evidence"]["knowledge_level"], "unknown")
            self.assertEqual(brief["interest_evidence"]["source_provenance"], niche["source_provenance"])

    def test_exploration_does_not_mutate_any_input(self):
        history = [candidate("old", topics=["bell casting"])]
        originals = copy.deepcopy((self.plan, self.profile, history, self.registry))
        diversity.explore(self.plan, self.profile, history=history, seed=4, count=5, registry=self.registry)
        self.assertEqual((self.plan, self.profile, history, self.registry), originals)


class SlateSelectionTests(unittest.TestCase):
    def test_edition_limits_picks_to_requested_categories_without_changing_regular_selection(self):
        candidates = [candidate("one", score=5), candidate("two", score=4.5),
                      candidate("film", score=3, medium="film"),
                      candidate("lecture", score=4, medium="lecture")]
        regular = diversity.select_slate(plan(), candidates, 2, seed=17)
        edition = diversity.select_slate(plan(), candidates, None, seed=17, categories=["film", "book"])

        self.assertEqual(selected_ids(regular), ["one", "two"])
        self.assertNotIn("requested_categories", regular)
        self.assertCountEqual(selected_ids(edition), ["one", "film"])
        self.assertEqual(edition["requested_categories"], ["film", "book"])
        self.assertEqual(edition["missing_categories"], [])
        self.assertIn({"id": "lecture", "reasons": ["category_not_requested"]}, edition["excluded"])

    def test_edition_reports_shortfall_and_does_not_fill_it_with_another_medium(self):
        candidates = [candidate("book"), candidate("backup"),
                      candidate("unchecked", medium="film", credibility_passed=False)]
        edition = diversity.select_slate(plan(), candidates, 3, seed=17, categories=["podcast", "book", "film"])

        self.assertEqual(len(edition["selected"]), 1)
        self.assertEqual(edition["selected"][0]["medium"], "book")
        self.assertEqual(edition["missing_categories"], ["podcast", "film"])
        self.assertEqual(edition["shortfall"], 2)

    def test_edition_preserves_full_coverage_under_the_shared_adjacent_cap(self):
        candidates = [connected_candidate("adjacent-book", score=5, lane="adjacent"),
                      connected_candidate("familiar-book", score=3.5),
                      connected_candidate("adjacent-film", score=4, medium="film", lane="adjacent")]
        edition = diversity.select_slate(connected_plan(), candidates, 2, seed=17, categories=["book", "film"])

        self.assertCountEqual(selected_ids(edition), ["familiar-book", "adjacent-film"])
        self.assertEqual(edition["missing_categories"], [])
        self.assertEqual(edition["max_exploratory_items"], 1)

    def test_edition_reserves_open_item_without_crowding_out_its_category(self):
        candidates = [connected_candidate("familiar-book", score=5),
                      open_candidate("open-book", score=3.5),
                      connected_candidate("familiar-film", score=4, medium="film")]
        edition = diversity.select_slate(open_plan(), candidates, 2, seed=17, categories=["book", "film"])

        self.assertCountEqual(selected_ids(edition), ["open-book", "familiar-film"])
        self.assertEqual(edition["selected_open_items"], 1)
        self.assertEqual(edition["open_shortfall"], 0)

    def setUp(self):
        self.plan = plan()

    def test_complete_scores_use_the_supplied_effective_weights(self):
        self.plan["effective_weights"] = {axis: 0.0 for axis in AXES}
        self.plan["effective_weights"]["depth"] = 0.75
        self.plan["effective_weights"]["entertainment"] = 0.25
        scores = {axis: 0.0 for axis in AXES}
        scores.update(depth=4.0, entertainment=2.0)
        result = diversity.select_slate(self.plan, [candidate("weighted", scores=scores)], 1, seed=1)
        self.assertEqual(selected_ids(result), ["weighted"])
        self.assertAlmostEqual(result["selected"][0]["base_score"], 3.5)

    def test_missing_or_invalid_scores_are_excluded_instead_of_imputed(self):
        candidates = []
        missing = candidate("missing-scores")
        del missing["scores"]
        candidates.append(missing)
        incomplete = candidate("incomplete")
        del incomplete["scores"]["novelty"]
        candidates.append(incomplete)
        for name, invalid in (("nan", float("nan")), ("inf", float("inf")),
                              ("negative", -0.1), ("too-high", 5.1),
                              ("boolean", True), ("text", "4")):
            entry = candidate(name)
            entry["scores"]["depth"] = invalid
            candidates.append(entry)
        result = diversity.select_slate(self.plan, candidates, len(candidates), seed=1)
        self.assertEqual(result["selected"], [])
        self.assertEqual(result["shortfall"], len(candidates))
        self.assertEqual({item["id"] for item in result["excluded"]}, {item["id"] for item in candidates})
        self.assertTrue(all(item["reasons"] for item in result["excluded"]))

    def test_verification_credibility_and_constraints_are_hard_gates(self):
        unverified = candidate("unverified")
        del unverified["verification"]
        candidates = [
            unverified,
            candidate("empty-sources", verification={"checked_at": "2026-11-03T12:00:00Z", "urls": []}),
            candidate("unchecked", verification={"urls": ["https://example.com/source"]}),
            candidate("not-credible", credibility_passed=False),
            candidate("out-of-scope", constraints_passed=False),
            candidate("verified"),
        ]
        result = diversity.select_slate(self.plan, candidates, 6, seed=1)
        self.assertEqual(selected_ids(result), ["verified"])
        self.assertEqual(result["shortfall"], 5)
        self.assertEqual({item["id"] for item in result["excluded"]}, {item["id"] for item in candidates[:-1]})

    def test_malformed_candidate_id_and_url_are_excluded_without_crashing(self):
        malformed_id = candidate("malformed-id")
        malformed_id["id"] = ["a-list-is-not-an-id"]
        candidates = [malformed_id, candidate("bad-url", canonical_url="https://["), candidate("good")]
        result = diversity.select_slate(self.plan, candidates, 3, seed=4)
        self.assertEqual(selected_ids(result), ["good"])
        self.assertEqual(result["shortfall"], 2)
        self.assertEqual(len(result["excluded"]), 2)
        self.assertTrue(all(item["reasons"] for item in result["excluded"]))
        self.assertIn("bad-url", [item["id"] for item in result["excluded"]])

    def test_low_quality_material_never_fills_a_lane_quota(self):
        self.plan["lane_mix"] = {"familiar": 0, "adjacent": 0, "distant": 1}
        candidates = [candidate("strong", score=4.5), candidate("weak-distant", score=2.0, lane="distant")]
        result = diversity.select_slate(self.plan, candidates, 2, seed=1, min_score=2.5)
        self.assertEqual(selected_ids(result), ["strong"])
        self.assertEqual(result["shortfall"], 1)
        self.assertIn("weak-distant", {item["id"] for item in result["excluded"]})

    def test_normalized_creator_and_title_identify_the_same_work(self):
        candidates = [
            candidate("first", creator="Ada Example", title="An Ocean of Sound"),
            candidate("duplicate", creator="  ADA   EXAMPLE ", title=" an ocean OF sound "),
            candidate("other"),
        ]
        result = diversity.select_slate(self.plan, candidates, 3, seed=3)
        self.assertEqual(len(result["selected"]), 2)
        self.assertEqual(len(set(selected_ids(result)) & {"first", "duplicate"}), 1)
        self.assertIn("other", selected_ids(result))

    def test_youtube_aliases_identify_the_same_video(self):
        candidates = [
            candidate("watch", canonical_url="https://www.youtube.com/watch?v=abc123DEF45&feature=share"),
            candidate("short-link", canonical_url="https://youtu.be/abc123DEF45?t=90"),
            candidate("shorts", canonical_url="https://www.youtube.com/shorts/abc123DEF45"),
        ]
        result = diversity.select_slate(self.plan, candidates, 3, seed=5)
        self.assertEqual(len(result["selected"]), 1)
        self.assertEqual(result["shortfall"], 2)

    def test_history_blocks_prior_work_by_url_or_title_creator(self):
        history = [
            {"title": "Old Title", "creator": "Old Creator", "canonical_url": "https://youtu.be/abc123DEF45"},
            {"title": "An Ocean of Sound", "creator": "Ada Example", "canonical_url": "https://example.com/old-edition"},
        ]
        candidates = [
            candidate("old-url", canonical_url="https://youtube.com/watch?v=abc123DEF45"),
            candidate("old-work", title=" an OCEAN of sound ", creator="ADA EXAMPLE"),
            candidate("new"),
        ]
        result = diversity.select_slate(self.plan, candidates, 3, history=history, seed=5)
        self.assertEqual(selected_ids(result), ["new"])
        self.assertEqual(result["shortfall"], 2)

    def test_comparable_quality_alternative_prevents_creator_repetition(self):
        candidates = [
            candidate("a1", score=4.5, creator="Creator A"),
            candidate("a2", score=4.4, creator="creator a"),
            candidate("b", score=4.3, creator="Creator B"),
        ]
        result = diversity.select_slate(self.plan, candidates, 2, seed=7)
        self.assertIn("b", selected_ids(result))
        self.assertEqual(len(set(selected_ids(result)) & {"a1", "a2"}), 1)

    def test_seed_makes_tied_slate_selection_replayable(self):
        candidates = [candidate(str(number)) for number in range(12)]
        first = diversity.select_slate(self.plan, candidates, 4, seed=31)
        second = diversity.select_slate(self.plan, candidates, 4, seed=31)
        self.assertEqual(first, second)
        self.assertEqual(first["seed"], 31)
        draws = {tuple(selected_ids(diversity.select_slate(self.plan, candidates, 4, seed=seed))) for seed in range(6)}
        self.assertGreater(len(draws), 1)

    def test_model_generation_probability_annotations_do_not_affect_selection(self):
        candidates = [candidate("a", score=4.5), candidate("b", score=4.1), candidate("c", score=3.7)]
        annotated = copy.deepcopy(candidates)
        for item, probability in zip(annotated, (0.999, 0.5, 0.000001)):
            item["model_generation_probability"] = probability
        ordinary = diversity.select_slate(self.plan, candidates, 2, seed=9)
        with_annotations = diversity.select_slate(self.plan, annotated, 2, seed=9)
        self.assertEqual(selected_ids(ordinary), selected_ids(with_annotations))
        for left, right in zip(ordinary["selected"], with_annotations["selected"]):
            self.assertEqual(left["base_score"], right["base_score"])
            self.assertEqual(left["selection_score"], right["selection_score"])

    def test_duplicate_aliases_do_not_add_sampling_tickets(self):
        originals = [candidate("a"), candidate("b"), candidate("c")]
        aliases = [candidate("alias-%d" % n, title=originals[0]["title"], creator=originals[0]["creator"],
                             canonical_url=originals[0]["canonical_url"]) for n in range(15)]
        for seed in range(12):
            ordinary = diversity.select_slate(self.plan, originals, 1, seed=seed)
            duplicated = diversity.select_slate(self.plan, originals + aliases, 1, seed=seed)
            self.assertEqual(diversity.work_keys(ordinary["selected"][0]), diversity.work_keys(duplicated["selected"][0]))

    def test_selection_does_not_mutate_plan_candidates_or_history(self):
        candidates = [candidate("a"), candidate("b")]
        history = [candidate("prior")]
        before = copy.deepcopy((self.plan, candidates, history))
        diversity.select_slate(self.plan, candidates, 2, history=history, seed=17)
        self.assertEqual((self.plan, candidates, history), before)


class ConnectedSurpriseTests(unittest.TestCase):
    def test_high_novelty_cannot_compensate_for_low_personal_relevance(self):
        current_plan = connected_plan()
        current_plan["effective_weights"] = dict(zip(AXES, (.10, .25, .05, .40, .15, .05)))
        unrelated = connected_candidate("unrelated", scores={axis: 5.0 for axis in AXES})
        unrelated["scores"]["relevance"] = 1.2
        relevant = connected_candidate("connected", score=3.5, lane="adjacent")
        result = diversity.select_slate(current_plan, [unrelated, relevant], 2, seed=4)
        self.assertEqual(selected_ids(result), ["connected"])
        self.assertEqual(result["shortfall"], 1)
        self.assertIn("relevance_below_connected_floor", result["excluded"][0]["reasons"])

    def test_connection_evidence_is_required_and_generic_claims_do_not_pass(self):
        candidates = [
            candidate("missing"),
            connected_candidate("empty", personal_connection={"basis": "current_request", "anchor": "", "explanation": ""}),
            connected_candidate("generic", personal_connection={"basis": "current_request", "anchor": "surprise me", "explanation": "Fits your interests"}),
            connected_candidate("malformed", personal_connection={"basis": [], "anchor": "computing", "explanation": "Connects computation to biological evolution."}),
            connected_candidate("valid"),
        ]
        result = diversity.select_slate(connected_plan(), candidates, 5, seed=7)
        self.assertEqual(selected_ids(result), ["valid"])
        self.assertEqual(result["shortfall"], 4)
        self.assertTrue(all("personal_connection_missing_or_invalid" in r["reasons"] for r in result["excluded"]))

    def test_distant_and_unrecognized_lanes_cannot_bypass_connection_guard(self):
        candidates = [connected_candidate("distant", lane="distant"), connected_candidate("unknown", lane="unrelated"), connected_candidate("good")]
        result = diversity.select_slate(connected_plan(), candidates, 3, seed=3)
        self.assertEqual(selected_ids(result), ["good"])
        self.assertEqual(result["shortfall"], 2)

    def test_broad_plan_cannot_use_focused_lane_to_bypass_exploration_cap(self):
        candidates = [connected_candidate("focused-%d" % n, lane="focused") for n in range(4)]
        result = diversity.select_slate(connected_plan(), candidates, 4, seed=3)
        self.assertEqual(result["selected"], [])
        self.assertEqual(result["shortfall"], 4)
        self.assertTrue(all("focused_lane_requires_focused_scope" in r["reasons"] for r in result["excluded"]))

    def test_explicit_focused_scope_can_select_within_request_lane(self):
        current_plan = connected_plan()
        current_plan["scope"] = "focused"
        current_plan["constraints"]["request"] = "Surprise me with films about memory"
        candidates = [connected_candidate("focused-%d" % n, lane="focused", personal_connection={
            "basis": "current_request", "anchor": "films about memory",
            "explanation": "Examines how unreliable recollection changes a film's account of the past.",
        }) for n in range(4)]
        result = diversity.select_slate(current_plan, candidates, 4, seed=3)
        self.assertEqual(len(result["selected"]), 4)
        self.assertEqual(result["shortfall"], 0)

    def test_four_adjacent_candidates_do_not_fill_the_entire_collection(self):
        candidates = [connected_candidate(str(n), score=4.5, lane="adjacent") for n in range(4)]
        result = diversity.select_slate(connected_plan(), candidates, 4, seed=4)
        self.assertEqual(len(result["selected"]), 1)
        self.assertEqual(result["shortfall"], 3)
        self.assertEqual(result["max_exploratory_items"], 1)
        self.assertTrue(all("connected_exploratory_cap_reached" in r["reasons"] for r in result["excluded"]))

    def test_three_matched_and_one_adjacent_fill_a_four_item_collection(self):
        candidates = [connected_candidate("core-%d" % n, score=3.8) for n in range(3)]
        candidates += [connected_candidate("adjacent-%d" % n, score=4.5, lane="adjacent") for n in range(3)]
        result = diversity.select_slate(connected_plan(), candidates, 4, seed=8)
        self.assertEqual(len(result["selected"]), 4)
        self.assertEqual(sum(i["lane"] == "familiar" for i in result["selected"]), 3)
        self.assertEqual(sum(i["lane"] == "adjacent" for i in result["selected"]), 1)

    def test_singleton_can_be_one_connected_adjacent_discovery(self):
        result = diversity.select_slate(connected_plan(), [connected_candidate("one", lane="adjacent")], 1, seed=2)
        self.assertEqual(selected_ids(result), ["one"])

    def test_legacy_surprise_plan_receives_guard_and_explicit_wildcard_does_not(self):
        legacy = plan(lane_mix={"familiar": .05, "adjacent": .25, "distant": .7})
        legacy["mode"] = "surprise"
        far = candidate("far", lane="distant")
        guarded = diversity.select_slate(legacy, [far], 1, seed=1)
        self.assertEqual(guarded["selected"], [])
        wildcard = copy.deepcopy(legacy)
        wildcard["mode"] = "wildcard"
        free = diversity.select_slate(wildcard, [far, candidate("unverified", lane="distant", credibility_passed=False)], 2, seed=1)
        self.assertEqual(selected_ids(free), ["far"])
        self.assertEqual(free["shortfall"], 1)

    def test_policy_cannot_disable_fit_but_can_raise_the_floor(self):
        bad_overrides = [
            {"min_relevance_score": 0}, {"min_relevance_score": -1},
            {"min_relevance_score": float("nan")}, {"min_relevance_score": True},
            {"require_personal_connection": False}, {"allow_distant": True},
            {"max_exploratory_fraction": 1}, {"max_exploratory_fraction": 0},
        ]
        for override in bad_overrides:
            with self.subTest(override=override), self.assertRaises(ValueError):
                diversity.select_slate(connected_plan(**override), [connected_candidate("one")], 1)
        result = diversity.select_slate(connected_plan(min_relevance_score=4), [connected_candidate("one", score=3.5)], 1)
        self.assertEqual(result["selected"], [])

    def test_exploration_cycles_evidenced_anchors_without_promoting_tentative_kind(self):
        interests = [
            {"id": "computing-observation", "topic": "computing", "kind": "inferred", "confidence": .45, "knowledge_level": "unknown", "source_provenance": ["user-question"]},
            {"id": "craft-interest", "topic": "craft", "kind": "explicit", "confidence": 1, "knowledge_level": "unknown", "source_provenance": ["user-preference"]},
        ]
        current_profile = profile(interests)
        original = copy.deepcopy(current_profile)
        result = diversity.explore(connected_plan(), current_profile, seed=1701, count=4)
        self.assertFalse(result["registry_used"])
        self.assertFalse(result["insufficient_context"])
        self.assertEqual(result["eligible_pool"], [])
        self.assertEqual([b["lane"] for b in result["briefs"]].count("familiar"), 3)
        self.assertEqual([b["lane"] for b in result["briefs"]].count("adjacent"), 1)
        evidence = [b["interest_evidence"] for b in result["briefs"]]
        self.assertEqual({e["id"] for e in evidence}, {i["id"] for i in interests})
        self.assertTrue(all(e["kind"] == "inferred" and e["confidence"] == .45 for e in evidence if e["id"] == "computing-observation"))
        self.assertEqual(current_profile, original)
        self.assertEqual(result, diversity.explore(connected_plan(), current_profile, seed=1701, count=4))

    def test_empty_context_is_reported_instead_of_replaced_with_random_domains(self):
        result = diversity.explore(connected_plan(), profile(), seed=7)
        self.assertTrue(result["insufficient_context"])
        self.assertFalse(result["registry_used"])
        self.assertEqual(result["briefs"], [])
        self.assertEqual(result["eligible_pool"], [])

    def test_format_and_randomness_only_requests_are_not_personal_context(self):
        for request in (
            "Surprise me, but not completely random",
            "Surprise me please, one video under 20 minutes",
            "Could you give me two short books, nothing too weird?",
            "Can you surprise me with something different tonight?",
            "Please recommend three podcasts of less than one hour",
            "I'd like a couple of videos under twenty minutes; don't make it random",
        ):
            with self.subTest(request=request):
                current_plan = connected_plan()
                current_plan["constraints"]["request"] = request
                result = diversity.explore(current_plan, profile(), seed=7, count=4)
                self.assertTrue(result["insufficient_context"])
                self.assertEqual(result["briefs"], [])

    def test_subject_or_concrete_current_goal_supplies_context(self):
        for request in (
            "Surprise me with one video about memory under 20 minutes",
            "Help me unwind after a stressful day with a short film",
            "I want to understand how cities develop, surprise me",
        ):
            with self.subTest(request=request):
                current_plan = connected_plan()
                current_plan["constraints"]["request"] = request
                result = diversity.explore(current_plan, profile(), seed=7, count=4)
                self.assertFalse(result["insufficient_context"])
                self.assertEqual(len(result["briefs"]), 4)

    def test_focused_request_is_the_context_and_is_preserved(self):
        current_plan = connected_plan()
        current_plan["scope"] = "focused"
        current_plan["constraints"]["request"] = "Surprise me with a film about memory under 90 minutes"
        result = diversity.explore(current_plan, profile(), seed=8, count=5)
        self.assertFalse(result["insufficient_context"])
        self.assertTrue(all(b["lane"] == "focused" and b["request_constraint"] == current_plan["constraints"]["request"] for b in result["briefs"]))
        self.assertTrue(all(b["field"] is None for b in result["briefs"]))

    def test_connected_selection_preserves_all_inputs(self):
        current_plan = connected_plan()
        candidates = [connected_candidate("core"), connected_candidate("adjacent", lane="adjacent")]
        history = [candidate("prior")]
        before = copy.deepcopy((current_plan, candidates, history))
        diversity.select_slate(current_plan, candidates, 2, history=history, seed=17)
        self.assertEqual((current_plan, candidates, history), before)


class OpenExplorationTests(unittest.TestCase):
    def setUp(self):
        self.registry = {"version": "synthetic-open-v1", "domains": [
            {"field": "Synthetic field alpha", "category": "stratum-a"},
            {"field": "Synthetic process beta", "category": "stratum-a"},
            {"field": "Synthetic field gamma", "category": "stratum-b"},
            {"field": "Synthetic field delta", "category": "stratum-c"},
        ]}
        self.interest = {"id": "interest-alpha", "topic": "Synthetic field alpha", "kind": "explicit",
                         "source_provenance": ["synthetic-current-request"], "knowledge_level": "unknown"}

    def test_empty_context_open_draw_is_authorized_replayable_and_not_a_preference(self):
        current_plan, current_profile, graph = open_plan(), profile(), synthetic_graph()
        before = copy.deepcopy((current_plan, current_profile, graph, self.registry))
        first = diversity.explore(current_plan, current_profile, seed=17, count=4, registry=self.registry, graph=graph)
        self.assertEqual(first, diversity.explore(current_plan, current_profile, seed=17, count=4, registry=self.registry, graph=graph))
        distant = [b for b in first["briefs"] if b["lane"] == "distant"]
        self.assertEqual(len(distant), 1)
        self.assertEqual(distant[0]["selection_channel"], "open")
        self.assertEqual(distant[0]["personal_fit_status"], "unknown")
        self.assertIsNone(distant[0]["interest_evidence"])
        self.assertTrue(first["registry_used"])
        self.assertTrue(first["graph_frontier"]["eligible_strata"])
        self.assertFalse(first["profile_changed"])
        self.assertEqual((current_plan, current_profile, graph, self.registry), before)
        singleton = diversity.explore(current_plan, current_profile, seed=17, count=1, registry=self.registry)
        self.assertEqual([b["lane"] for b in singleton["briefs"]], ["distant"])

    def test_new_explicit_interest_is_an_independent_anchor_not_a_graph_inference(self):
        prior = copy.deepcopy(self.interest)
        added = {"id": "interest-delta", "topic": "Synthetic field delta", "kind": "explicit",
                 "source_provenance": ["synthetic-new-user-statement"], "knowledge_level": "unknown"}
        current_profile = profile([prior, added])
        result = diversity.explore(open_plan(), current_profile, seed=3, count=8, registry=self.registry)
        evidence = [b["interest_evidence"] for b in result["briefs"] if b.get("interest_evidence")]
        self.assertEqual({e["id"] for e in evidence}, {prior["id"], added["id"]})
        self.assertTrue(all(e["kind"] == "explicit" and e["knowledge_level"] == "unknown" for e in evidence))
        self.assertEqual(current_profile["interests"], [prior, added])

    def test_known_closed_modes_do_not_inherit_legacy_distant_allocation(self):
        current = plan(lane_mix={"familiar": 0, "adjacent": 0, "distant": 1})
        current["mode"] = "personal"
        result = diversity.explore(current, profile([self.interest]), seed=2, count=4, registry=self.registry)
        self.assertFalse(any(b["lane"] == "distant" for b in result["briefs"]))
        self.assertFalse(result["registry_used"])
        self.assertTrue(result["warnings"])
        current["constraints"]["open_exploration_enabled"] = True
        authorized = diversity.explore(current, profile(), seed=2, count=4, registry=self.registry)
        self.assertEqual(sum(b["lane"] == "distant" for b in authorized["briefs"]), 1)
        self.assertEqual(authorized["selection_policy"]["kind"], "open_exploration_v1")
        legacy = plan(lane_mix={"familiar": 0, "adjacent": 0, "distant": 1})
        self.assertEqual(sum(b["lane"] == "distant" for b in diversity.explore(legacy, profile(), seed=2, count=4, registry=self.registry)["briefs"]), 4)

    def test_optional_graph_enrichment_retains_real_path_without_open_fallback(self):
        current = connected_plan()
        current_profile = profile([self.interest])
        graph = synthetic_graph()
        before = copy.deepcopy((current, current_profile, graph))
        result = diversity.explore(current, current_profile, seed=13, count=4, registry=self.registry, graph=graph)
        routes = result["graph_frontier"]["connected"]
        self.assertTrue(routes)
        self.assertEqual(routes[0]["edge_ids"], ["edge-alpha-beta"])
        self.assertEqual(routes[0]["anchor_id"], self.interest["id"])
        self.assertEqual(result["graph_frontier"]["open"], [])
        self.assertFalse(result["registry_used"])
        self.assertEqual((current, current_profile, graph), before)

    def test_focused_open_never_generates_or_selects_independent_distant_items(self):
        current = open_plan("focused")
        current["constraints"]["request"] = "Only works about Synthetic field alpha"
        result = diversity.explore(current, profile([self.interest]), seed=5, registry=self.registry, graph=synthetic_graph())
        self.assertTrue(all(b["lane"] == "focused" and b["field"] is None for b in result["briefs"]))
        self.assertFalse(result["registry_used"])
        self.assertNotIn("graph_frontier", result)
        unknown = open_candidate("unknown")
        numeric = open_candidate("numeric")
        numeric["scores"]["relevance"] = 4
        slate = diversity.select_slate(current, [unknown, numeric, connected_candidate("in-scope", lane="focused")], 3, seed=1)
        self.assertEqual(selected_ids(slate), ["in-scope"])
        self.assertEqual(slate["shortfall"], 2)

    def test_unknown_relevance_uses_only_other_five_weights_without_imputation(self):
        current = open_plan()
        current["effective_weights"] = {axis: 0.0 for axis in AXES}
        current["effective_weights"].update(relevance=.6, depth=.2, novelty=.2)
        item = open_candidate("value")
        item["scores"].update(depth=4, novelty=2)
        before = copy.deepcopy((current, item))
        result = diversity.select_slate(current, [item], 1, seed=1)
        self.assertEqual(selected_ids(result), ["value"])
        selected = result["selected"][0]
        self.assertIsNone(selected["scores"]["relevance"])
        self.assertEqual(selected["base_score"], 3)
        self.assertEqual(selected["scoring_basis"], "open_value_without_personal_relevance")
        self.assertNotIn("relevance", selected["scoring_weights"])
        self.assertAlmostEqual(sum(selected["scoring_weights"].values()), 1)
        self.assertEqual((current, item), before)

    def test_open_numeric_and_null_relevance_receive_identical_value_and_tie_treatment(self):
        current = open_plan()
        current["effective_weights"] = {axis: .1 for axis in AXES}
        current["effective_weights"]["relevance"] = .5
        variants = []
        for relevance in (0, 5, None):
            pool = [open_candidate("a"), open_candidate("b")]
            pool[0]["scores"]["relevance"] = relevance
            result = diversity.select_slate(current, pool, 1, seed=17)
            variants.append((selected_ids(result), result["selected"][0]["base_score"], result["selected"][0]["selection_score"]))
        self.assertEqual(variants[0], variants[1])
        self.assertEqual(variants[1], variants[2])

    def test_null_relevance_cannot_escape_its_explicit_broad_open_lane(self):
        cases = [(plan(), "distant"), (connected_plan(), "adjacent"), (open_plan(), "familiar"),
                 (open_plan(), "adjacent"), (dict(plan(), mode="wildcard"), "distant")]
        for current, lane in cases:
            with self.subTest(mode=current.get("mode"), lane=lane):
                result = diversity.select_slate(current, [open_candidate("unknown", lane=lane)], 1, seed=1)
                self.assertEqual(result["selected"], [])
                self.assertEqual(result["shortfall"], 1)

    def test_open_value_source_credibility_constraints_and_threshold_all_remain_gates(self):
        bad = [open_candidate("unverified", verification={}), open_candidate("unreliable", credibility_passed=False),
               open_candidate("constraint", constraints_passed=False), open_candidate("generic-value", value_rationale="Interesting and new"),
               open_candidate("claimed-fit", personal_fit_status="known"), open_candidate("low-value", score=1.0)]
        result = diversity.select_slate(open_plan(), bad + [open_candidate("good")], 7, seed=2)
        self.assertEqual(selected_ids(result), ["good"])
        self.assertEqual(result["shortfall"], 6)
        self.assertTrue(all(e["reasons"] for e in result["excluded"]))

    def test_zero_nonrelevance_weight_mass_does_not_invent_a_value_score(self):
        current = open_plan()
        current["effective_weights"] = {axis: float(axis == "relevance") for axis in AXES}
        result = diversity.select_slate(current, [open_candidate("unscorable")], 1)
        self.assertEqual(result["selected"], [])
        self.assertIn("no_nonrelevance_weight_for_open_value", result["excluded"][0]["reasons"])

    def test_standing_personal_open_allocation_cannot_bypass_value_checks_or_caps(self):
        current = plan(lane_mix={"familiar": .5, "adjacent": .3, "distant": .2})
        current["mode"] = "personal"
        current["constraints"]["open_exploration_enabled"] = True
        no_value = candidate("missing-value", lane="distant", personal_fit_status="unknown")
        result = diversity.select_slate(current, [no_value] + [open_candidate("open-%d" % n) for n in range(4)], 4, seed=2)
        self.assertEqual(result["selection_policy"]["kind"], "open_exploration_v1")
        self.assertEqual(len(result["selected"]), 1)
        self.assertEqual(result["shortfall"], 3)
        self.assertIn("open_value_rationale_missing_or_invalid", next(e for e in result["excluded"] if e["id"] == "missing-value")["reasons"])
        self.assertEqual(result["selected"][0]["scoring_basis"], "open_value_without_personal_relevance")

    def test_current_opt_out_closes_manual_retained_plans_without_changing_permission(self):
        for request in ("Stay close to my existing interests; no open exploration.", "Stay close to my existing interests",
                        "Keep this close to my interests", "Stick to my known interests", "Don't explore an unfamiliar field", "Avoid unrelated picks"):
            for mode in (None, "personal", "open", "wildcard"):
                with self.subTest(request=request, mode=mode):
                    current = open_plan()
                    if mode is None:
                        del current["mode"]
                    else:
                        current["mode"] = mode
                    current["lane_mix"] = {"familiar": .2, "adjacent": .2, "distant": .6}
                    current["constraints"].update(request=request, open_exploration_enabled=True)
                    current_profile, graph = profile([self.interest]), synthetic_graph()
                    before = copy.deepcopy((current, current_profile, graph))
                    discovery = diversity.explore(current, current_profile, seed=17, count=4, registry=self.registry, graph=graph)
                    self.assertFalse(any(b["lane"] == "distant" for b in discovery["briefs"]))
                    self.assertFalse(discovery["registry_used"])
                    self.assertIsNone(discovery["selection_policy"])
                    self.assertEqual(discovery["graph_frontier"]["open"], [])
                    numeric = candidate("numeric-distant", lane="distant", personal_fit_status="unknown", value_rationale="A concrete original account of a synthetic process.")
                    slate = diversity.select_slate(current, [numeric, open_candidate("null-distant"), connected_candidate("connected")], 3, seed=17)
                    self.assertEqual(selected_ids(slate), ["connected"])
                    self.assertEqual(slate["shortfall"], 2)
                    self.assertEqual(slate["lane_mix_target"]["distant"], 0)
                    self.assertIsNone(slate["selection_policy"])
                    self.assertEqual((current, current_profile, graph), before)
        later = open_plan()
        later["mode"] = "personal"
        later["constraints"].update(request="A few recommendations", open_exploration_enabled=True)
        allowed = diversity.explore(later, profile([self.interest]), seed=17, count=4, registry=self.registry)
        self.assertEqual(sum(b["lane"] == "distant" for b in allowed["briefs"]), 1)
        self.assertEqual(allowed["selection_policy"]["kind"], "open_exploration_v1")

    def test_retained_request_opt_out_flag_is_authoritative_when_text_is_not_repeated(self):
        current = open_plan()
        current["constraints"].update(request="", open_exploration_enabled=True, open_exploration_disabled_for_request=True)
        result = diversity.explore(current, profile(), seed=17, count=4, registry=self.registry)
        self.assertFalse(any(b["lane"] == "distant" for b in result["briefs"]))
        slate = diversity.select_slate(current, [open_candidate("open")], 1, seed=17)
        self.assertEqual(slate["selected"], [])

    def test_connected_open_items_require_relevance_and_real_bridge(self):
        low = connected_candidate("low")
        low["scores"]["relevance"] = 2
        result = diversity.select_slate(open_plan(), [low, candidate("missing-bridge"), connected_candidate("good")], 3, seed=1)
        self.assertEqual(selected_ids(result), ["good"])
        self.assertEqual(result["shortfall"], 2)

    def test_open_and_adjacent_caps_are_independent_and_do_not_pad_a_slate(self):
        distant = [open_candidate("open-%d" % n) for n in range(4)]
        adjacent = [connected_candidate("adjacent-%d" % n, lane="adjacent") for n in range(4)]
        familiar = [connected_candidate("familiar-%d" % n) for n in range(2)]
        result = diversity.select_slate(open_plan(), distant + adjacent + familiar, 4, seed=4)
        self.assertEqual(len(result["selected"]), 4)
        self.assertEqual(sum(i["lane"] == "distant" for i in result["selected"]), 1)
        self.assertEqual(sum(i["lane"] == "adjacent" for i in result["selected"]), 1)
        only_open = diversity.select_slate(open_plan(), distant, 4, seed=4)
        self.assertEqual(len(only_open["selected"]), 1)
        self.assertEqual(only_open["shortfall"], 3)

    def test_explicit_broad_open_reserves_one_slot_against_higher_scoring_familiar_items(self):
        familiar = [connected_candidate("core-%d" % n, score=4.8) for n in range(4)]
        distant = open_candidate("qualified-open", score=4.0)
        before = copy.deepcopy((familiar, distant))
        result = diversity.select_slate(open_plan(), familiar + [distant], 4, seed=17)
        self.assertEqual(len(result["selected"]), 4)
        self.assertEqual(result["required_open_items"], 1)
        self.assertEqual(result["selected_open_items"], 1)
        self.assertEqual(result["open_shortfall"], 0)
        self.assertIn("qualified-open", selected_ids(result))
        self.assertEqual(sum(i["lane"] == "familiar" for i in result["selected"]), 3)
        self.assertEqual(result["shortfall"], 0)
        self.assertEqual((familiar, distant), before)

    def test_invalid_open_candidate_leaves_reserved_slot_unfilled_without_padding(self):
        familiar = [connected_candidate("core-%d" % n, score=4.8) for n in range(4)]
        invalid = [open_candidate("unverified", verification={}), open_candidate("valueless", value_rationale=""),
                   open_candidate("constraint", constraints_passed=False), open_candidate("below-threshold", score=1.0)]
        result = diversity.select_slate(open_plan(), familiar + invalid, 4, seed=17)
        self.assertEqual(len(result["selected"]), 3)
        self.assertEqual(result["required_open_items"], 1)
        self.assertEqual(result["selected_open_items"], 0)
        self.assertEqual(result["open_shortfall"], 1)
        self.assertEqual(result["shortfall"], 1)
        reasons = {e["id"]: e["reasons"] for e in result["excluded"]}
        self.assertIn("verification_missing_or_invalid", reasons["unverified"])
        self.assertIn("open_value_rationale_missing_or_invalid", reasons["valueless"])
        self.assertIn("constraints_not_confirmed", reasons["constraint"])
        self.assertIn("below_subjective_fit_threshold", reasons["below-threshold"])
        self.assertTrue(any("explicit_open_slot_reserved" in values for values in reasons.values()))

    def test_explicit_singleton_open_requires_a_qualified_independent_item(self):
        familiar = connected_candidate("higher-core", score=5.0)
        distant = open_candidate("open", score=3.5)
        result = diversity.select_slate(open_plan(), [familiar, distant], 1, seed=17)
        self.assertEqual(selected_ids(result), ["open"])
        self.assertEqual(result["required_open_items"], 1)
        self.assertEqual(result["open_shortfall"], 0)
        missing = diversity.select_slate(open_plan(), [familiar], 1, seed=17)
        self.assertEqual(missing["selected"], [])
        self.assertEqual(missing["open_shortfall"], 1)
        self.assertEqual(missing["shortfall"], 1)

    def test_standing_permission_can_select_no_open_items_without_reserving_a_slot(self):
        current = open_plan()
        current["mode"] = "personal"
        current["constraints"]["open_exploration_enabled"] = True
        familiar = [connected_candidate("core-%d" % n, score=4.8) for n in range(4)]
        result = diversity.select_slate(current, familiar + [open_candidate("qualified-open", score=4.0)], 4, seed=17)
        self.assertEqual(len(result["selected"]), 4)
        self.assertEqual(result["required_open_items"], 0)
        self.assertEqual(result["selected_open_items"], 0)
        self.assertEqual(result["open_shortfall"], 0)
        self.assertEqual(result["shortfall"], 0)

    def test_current_opt_out_and_focused_scope_suppress_open_reservation(self):
        familiar = [connected_candidate("core-%d" % n, score=4.8) for n in range(4)]
        closed = open_plan()
        closed["constraints"]["request"] = "Stay close to my existing interests; no open exploration."
        result = diversity.select_slate(closed, familiar + [open_candidate("open")], 4, seed=17)
        self.assertEqual(len(result["selected"]), 4)
        self.assertEqual(result["required_open_items"], 0)
        self.assertEqual(result["selected_open_items"], 0)
        self.assertEqual(result["open_shortfall"], 0)
        focused = diversity.select_slate(open_plan("focused"), familiar + [open_candidate("open")], 4, seed=17)
        self.assertEqual(len(focused["selected"]), 4)
        self.assertEqual(focused["required_open_items"], 0)
        self.assertEqual(focused["selected_open_items"], 0)
        self.assertEqual(focused["open_shortfall"], 0)

    def test_tentative_anchors_need_evidence_and_nonpositive_examples_stay_out(self):
        records = [dict(self.interest, id="unevidenced", kind="inferred", source_provenance=[], confidence=.9),
                   dict(self.interest, id="illustration", illustrative=True),
                   dict(self.interest, id="negative", polarity="negative"),
                   dict(self.interest, id="reference", scope="reference_only"),
                   dict(self.interest, id="retracted", status="retracted")]
        current_profile = profile(records + [self.interest])
        before = copy.deepcopy(current_profile)
        result = diversity.explore(open_plan(), current_profile, seed=7, count=8, registry=self.registry)
        evidence = [b["interest_evidence"] for b in result["briefs"] if b.get("interest_evidence")]
        self.assertTrue(evidence)
        self.assertEqual({e["id"] for e in evidence}, {self.interest["id"]})
        self.assertEqual(current_profile, before)

    def test_quoted_and_assistant_only_records_never_anchor_ordinary_briefs(self):
        markings = [
            {"quoted": True}, {"origin": "quoted_third_party"},
            {"assistant_only": True}, {"source_kind": "assistant_suggestion"},
            {"basis": "assistant_characterization"},
            {"source_provenance": [{"kind": "third_party_quote", "locator": "synthetic-quote"}]},
            {"source_provenance": [{"kind": "assistant_generated", "locator": "synthetic-assistant-output"}]},
        ]
        for marking in markings:
            for graph in (None, synthetic_graph()):
                for current in (connected_plan(), open_plan(), dict(plan(), mode="personal")):
                    with self.subTest(marking=marking, graph_supplied=graph is not None, mode=current["mode"]):
                        record = dict(self.interest, **marking)
                        current_profile = profile([record])
                        before = copy.deepcopy(current_profile)
                        result = diversity.explore(current, current_profile, seed=17, count=4, registry=self.registry, graph=graph)
                        self.assertTrue(all(b.get("interest_evidence") is None for b in result["briefs"]))
                        self.assertTrue(all(b["field"] is None for b in result["briefs"] if b["lane"] != "distant"))
                        if "graph_frontier" in result:
                            self.assertEqual(result["graph_frontier"]["connected"], [])
                        self.assertEqual(current_profile, before)

    def test_shared_anchor_copies_preserve_explicit_and_evidenced_observations(self):
        explicit = dict(self.interest)
        del explicit["knowledge_level"]
        tentative = {"id": "tentative-beta", "topic": "Synthetic process beta", "kind": "tentative", "confidence": .4,
                     "source_provenance": [{"id": "synthetic-personal-observation", "locator": "synthetic-current-input"}]}
        graph_only = {"id": "graph-only", "kind": "explicit", "graph_node_id": "topic-alpha"}
        current_profile = profile([explicit, tentative, graph_only])
        before = copy.deepcopy(current_profile)
        anchors = diversity._connection_anchors(current_profile)
        self.assertEqual({a["id"] for a in anchors}, {explicit["id"], tentative["id"]})
        self.assertTrue(all(a["knowledge_level"] == "unknown" and a["knowledge_evidence"] == [] for a in anchors))
        observed = next(a for a in anchors if a["id"] == tentative["id"])
        self.assertEqual(observed["kind"], "tentative")
        self.assertEqual(observed["confidence"], .4)
        self.assertEqual(observed["source_provenance"], tentative["source_provenance"])
        observed["source_provenance"][0]["locator"] = "edited-output-copy"
        self.assertEqual(current_profile, before)


class DiversityAuditTests(unittest.TestCase):
    def test_absent_prior_history_is_not_a_zero_repeat_claim(self):
        unknown_history = diversity.audit_items([candidate("one")])
        empty_history = diversity.audit_items([candidate("one")], previous=[])
        self.assertFalse(unknown_history["previous_supplied"])
        self.assertIsNone(unknown_history["repeat_count"])
        self.assertIsNone(unknown_history["repeat_fraction"])
        self.assertIsNone(unknown_history["work_jaccard_with_previous"])
        self.assertTrue(empty_history["previous_supplied"])
        self.assertEqual(empty_history["repeat_count"], 0)
        self.assertEqual(empty_history["repeat_fraction"], 0)

    def test_unique_repeats_and_concentrations_match_hand_calculations(self):
        items = [
            candidate("a", creator="Maker A", topics=["x"]),
            candidate("b", creator="maker a", topics=["x", "y"]),
            candidate("c", creator="Maker B", topics=["y"]),
            candidate("d", creator="Maker C", topics=["z"]),
        ]
        previous = [candidate("previous-a", canonical_url=items[0]["canonical_url"])]
        metrics = diversity.audit_items(items, previous=previous)
        self.assertEqual(metrics["n_items"], 4)
        self.assertEqual(metrics["unique_work_count"], 4)
        self.assertEqual(metrics["identity_observed_count"], 4)
        self.assertEqual(metrics["identity_missing_count"], 0)
        self.assertEqual(metrics["repeat_count"], 1)
        self.assertAlmostEqual(metrics["repeat_fraction"], 0.25)
        self.assertEqual(sorted(metrics["creator_counts"].values()), [1, 1, 2])
        self.assertEqual(metrics["creator_observed_count"], 4)
        self.assertEqual(metrics["creator_missing_count"], 0)
        self.assertAlmostEqual(metrics["creator_hhi"], 0.375)
        self.assertEqual(metrics["topic_coverage_count"], 3)
        self.assertEqual(metrics["topic_observed_items"], 4)
        self.assertEqual(metrics["topic_missing_count"], 0)
        self.assertEqual(metrics["topic_counts"], {"x": 2, "y": 2, "z": 1})
        self.assertAlmostEqual(metrics["topic_hhi"], 0.36)

    def test_audit_deduplicates_work_identity_and_counts_history_repeats(self):
        items = [
            candidate("one", canonical_url="https://youtu.be/abc123DEF45"),
            candidate("alias", canonical_url="https://www.youtube.com/watch?v=abc123DEF45"),
            candidate("new"),
        ]
        previous = [{"canonical_url": "https://youtube.com/shorts/abc123DEF45"}]
        metrics = diversity.audit_items(items, previous=previous)
        self.assertEqual(metrics["unique_work_count"], 2)
        self.assertEqual(metrics["repeat_count"], 2)
        self.assertAlmostEqual(metrics["repeat_fraction"], 2.0 / 3.0)

    def test_unknown_data_remains_visible_without_fabricated_concentration(self):
        metrics = diversity.audit_items([{"id": "unknown"}])
        self.assertEqual(metrics["n_items"], 1)
        self.assertEqual(metrics["identity_observed_count"], 0)
        self.assertEqual(metrics["identity_missing_count"], 1)
        self.assertIsNone(metrics["repeat_fraction"])
        self.assertEqual(metrics["creator_missing_count"], 1)
        self.assertIsNone(metrics["creator_hhi"])
        self.assertEqual(metrics["topic_missing_count"], 1)
        self.assertIsNone(metrics["topic_hhi"])

    def test_malformed_creator_and_topics_do_not_fabricate_metadata(self):
        items = [
            {"id": "null", "creator": None, "topics": None},
            {"id": "list-creator", "creator": ["invented creator"], "topics": "not a topic list"},
            {"id": "object-creator", "creator": {"name": "invented"}, "topics": {"label": "invented"}},
            {"id": "numeric-creator", "creator": 123, "topics": [None, 123, {"label": "invented"}]},
        ]
        metrics = diversity.audit_items(items)
        self.assertEqual(metrics["creator_observed_count"], 0)
        self.assertEqual(metrics["creator_missing_count"], 4)
        self.assertEqual(metrics["creator_counts"], {})
        self.assertIsNone(metrics["creator_hhi"])
        self.assertEqual(metrics["topic_observed_items"], 0)
        self.assertEqual(metrics["topic_missing_count"], 4)
        self.assertEqual(metrics["topic_coverage_count"], 0)
        self.assertEqual(metrics["topic_counts"], {})
        self.assertIsNone(metrics["topic_hhi"])

    def test_previous_alias_bridge_keeps_work_jaccard_within_unit_interval(self):
        items = [
            {"canonical_url": "https://example.com/x", "title": "Title A", "creator": "Creator Q"},
            {"canonical_url": "https://example.com/y", "title": "Title B", "creator": "Creator Q"},
        ]
        previous = [{"canonical_url": "https://example.com/x", "title": "Title B", "creator": "Creator Q"}]
        for current in (items, list(reversed(items))):
            with self.subTest(order=[item["title"] for item in current]):
                metrics = diversity.audit_items(current, previous=previous)
                self.assertEqual(metrics["unique_work_count"], 2)
                self.assertGreaterEqual(metrics["work_jaccard_with_previous"], 0)
                self.assertLessEqual(metrics["work_jaccard_with_previous"], 1)
                self.assertAlmostEqual(metrics["work_jaccard_with_previous"], 1.0)

    def test_audit_is_read_only(self):
        items = [candidate("one"), candidate("two")]
        previous = [candidate("old")]
        before = copy.deepcopy((items, previous))
        diversity.audit_items(items, previous=previous)
        self.assertEqual((items, previous), before)


if __name__ == "__main__":
    unittest.main()
