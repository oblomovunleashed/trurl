"""Behavioral checks for read-only planning and model initialization."""
import copy
import importlib.util
import json
import math
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

MODULE = Path(__file__).resolve().parents[1] / "skills/trurl/scripts/curation.py"
spec = importlib.util.spec_from_file_location("curation", MODULE)
curation = importlib.util.module_from_spec(spec)
spec.loader.exec_module(curation)


class WeightPlanTests(unittest.TestCase):
    def setUp(self):
        self.profile = curation.generic_profile()
        self.profile["taste"]["axes_weights"] = dict(zip(curation.AXES, (0.2, 0.2, 0.15, 0.2, 0.1, 0.15)))

    def test_connected_surprise_overrides_baseline_without_discarding_fit(self):
        self.profile["taste"]["axes_weights"] = {axis: float(axis == "relevance") for axis in curation.AXES}
        before = copy.deepcopy(self.profile)
        plan = curation.make_plan(self.profile, "surprise me", seed=42)
        weights = plan["effective_weights"]
        self.assertEqual(plan["mode"], "surprise")
        self.assertGreaterEqual(weights["surprise"], 0.20 - 1e-12)
        self.assertGreaterEqual(weights["novelty"], 0.16 - 1e-12)
        self.assertGreaterEqual(weights["relevance"], 0.20 - 1e-12)
        self.assertGreater(plan["rotation_distance_l1"], 1.0)
        self.assertEqual(plan["lane_mix"], {"familiar": .75, "adjacent": .25, "distant": 0.0})
        self.assertEqual(plan["policy_version"], "connected_surprise_v1")
        self.assertTrue(plan["selection_policy"]["require_personal_connection"])
        self.assertEqual(plan["selection_policy"]["min_relevance_score"], 3.0)
        self.assertFalse(plan["selection_policy"]["allow_distant"])
        self.assertEqual(self.profile, before)
        self.assertFalse(plan["baseline_changed"])
        self.assertFalse(plan["constraints"]["weekly_delivery_enabled"])

    def test_connected_surprise_floors_survive_seeded_variation(self):
        for seed in range(100):
            with self.subTest(seed=seed):
                plan = curation.make_plan(self.profile, "surprise me", seed=seed)
                weights = plan["effective_weights"]
                self.assertTrue(math.isclose(sum(weights.values()), 1.0))
                self.assertGreaterEqual(weights["relevance"], .20 - 1e-12)
                self.assertGreaterEqual(weights["surprise"], .20 - 1e-12)
                self.assertGreaterEqual(weights["novelty"], .16 - 1e-12)
                self.assertEqual(plan["lane_mix"]["distant"], 0)

    def test_extreme_wildcard_needs_explicit_intent(self):
        for request in ("Give me something completely random", "An unrelated wildcard", "Take me completely outside my interests"):
            with self.subTest(request=request):
                plan = curation.make_plan(self.profile, request, seed=42)
                self.assertEqual(plan["mode"], "wildcard")
                self.assertEqual(plan["scope"], "broad")
                self.assertEqual(plan["lane_mix"]["distant"], .70)
                self.assertIsNone(plan["selection_policy"])
                self.assertEqual(plan["policy_version"], "explicit_wildcard_v1")
        explicit = curation.make_plan(self.profile, mode="wildcard", seed=42)
        self.assertEqual(explicit["mode"], "wildcard")
        fixed = curation.make_plan(self.profile, mode="wildcard", fixed=True, seed=42)
        self.assertEqual(fixed["effective_weights"], fixed["baseline_weights"])

    def test_wildcard_negation_preserves_connected_surprise(self):
        for request in ("Surprise me, but not completely random", "Surprise me, but don't ignore my interests", "Surprise me, no unrelated wildcards", "Surprise me, don't give me an unrelated wildcard"):
            with self.subTest(request=request):
                plan = curation.make_plan(self.profile, request, seed=42)
                self.assertEqual(plan["mode"], "surprise")
                self.assertTrue(plan["selection_policy"]["require_personal_connection"])
        for request in ("Not completely random", "Don't ignore my interests"):
            self.assertNotEqual(curation.make_plan(self.profile, request, seed=42)["mode"], "wildcard")

    def test_automatic_rotation_never_chooses_explicit_wildcard(self):
        for axis in curation.AXES:
            current = copy.deepcopy(self.profile)
            current["taste"]["axes_weights"] = {a: float(a == axis) for a in curation.AXES}
            for seed in range(60):
                with self.subTest(axis=axis, seed=seed):
                    plan = curation.make_plan(current, "A few recommendations", context="weekly", seed=seed)
                    self.assertNotIn(plan["mode"], {"wildcard", "open"})
                    if plan["mode"] == "surprise":
                        self.assertEqual(plan["selection_policy"]["kind"], "connected_surprise_v1")

    def test_open_exploration_is_explicit_and_preserves_all_six_baseline_weights(self):
        before = copy.deepcopy(self.profile)
        for request in ("Try a new area", "Explore an unfamiliar field", "Open exploration"):
            for seed in (1, 42):
                with self.subTest(request=request, seed=seed):
                    current = curation.make_plan(self.profile, request, seed=seed)
                    self.assertEqual(current["mode"], "open")
                    self.assertEqual(current["scope"], "broad")
                    self.assertEqual(current["effective_weights"], current["baseline_weights"])
                    self.assertEqual(current["target_weights"], current["baseline_weights"])
                    self.assertEqual(current["lane_mix"], {"familiar": .5, "adjacent": .25, "distant": .25})
                    self.assertEqual(current["policy_version"], "open_exploration_v1")
                    self.assertEqual(current["selection_policy"]["max_open_fraction"], .25)
                    self.assertFalse(current["variation_applied"])
                    self.assertIsNone(current["seed"])
        self.assertEqual(curation.make_plan(self.profile, mode="open")["scope"], "broad")
        self.assertEqual(self.profile, before)

    def test_fixed_and_negated_open_requests_do_not_authorize_open_exploration(self):
        for request in ("Try a new area", "Open exploration"):
            fixed = curation.make_plan(self.profile, request, mode="open", fixed=True)
            self.assertEqual(fixed["mode"], "personal")
            self.assertIsNone(fixed["selection_policy"])
            self.assertEqual(fixed["lane_mix"]["distant"], 0)
            self.assertEqual(fixed["effective_weights"], fixed["baseline_weights"])
        for request in ("No open exploration", "Don't try a new area", "Do not explore an unfamiliar field"):
            self.assertNotEqual(curation.make_plan(self.profile, request)["mode"], "open")

    def test_known_modes_are_connected_until_distant_research_is_opted_in(self):
        for mode in ("personal", "deep", "playful", "perspective", "surprise"):
            with self.subTest(mode=mode):
                self.assertEqual(curation.make_plan(self.profile, mode=mode)["lane_mix"]["distant"], 0)
        self.profile["discovery"]["lane_mix"] = {"familiar": .4, "adjacent": .4, "distant": .2}
        before = copy.deepcopy(self.profile)
        closed = curation.make_plan(self.profile, scope="broad")
        self.assertEqual(closed["lane_mix"], {"familiar": .5, "adjacent": .5, "distant": 0})
        self.assertTrue(closed["warnings"])
        self.assertEqual(self.profile, before)
        self.profile["discovery"]["open_exploration"]["enabled"] = True
        authorized = curation.make_plan(self.profile, scope="broad")
        self.assertEqual(authorized["lane_mix"], self.profile["discovery"]["lane_mix"])
        self.assertTrue(authorized["constraints"]["open_exploration_enabled"])
        self.assertEqual(authorized["selection_policy"]["kind"], "open_exploration_v1")
        self.assertEqual(authorized["effective_weights"], authorized["baseline_weights"])

    def test_older_profile_without_optional_discovery_fields_remains_usable(self):
        del self.profile["discovery"]
        planned = curation.make_plan(self.profile)
        self.assertEqual(planned["lane_mix"], {"familiar": .75, "adjacent": .25, "distant": 0})
        self.assertFalse(planned["constraints"]["open_exploration_enabled"])
        self.assertEqual(planned["constraints"]["graph_max_hops"], 2)

    def test_current_open_opt_out_overrides_standing_permission_for_only_this_batch(self):
        self.profile["discovery"]["open_exploration"]["enabled"] = True
        self.profile["discovery"]["lane_mix"] = {"familiar": .2, "adjacent": .2, "distant": .6}
        before = copy.deepcopy(self.profile)
        requests = (
            "Stay close to my existing interests; no open exploration.",
            "No open exploration",
            "Stay close to my existing interests",
            "Keep this close to my interests",
            "Stick to my known interests",
            "Don't explore an unfamiliar field",
            "Avoid unrelated picks",
        )
        for request in requests:
            for mode in ("auto", "personal", "open", "wildcard"):
                with self.subTest(request=request, mode=mode):
                    planned = curation.make_plan(self.profile, request, mode=mode, scope="broad", context="weekly", seed=42)
                    self.assertEqual(planned["mode"], "personal")
                    self.assertEqual(planned["lane_mix"], {"familiar": .5, "adjacent": .5, "distant": 0})
                    self.assertIsNone(planned["selection_policy"])
                    self.assertFalse(planned["constraints"]["open_exploration_enabled"])
                    self.assertTrue(planned["constraints"]["open_exploration_disabled_for_request"])
                    self.assertEqual(planned["effective_weights"], planned["baseline_weights"])
        self.assertEqual(self.profile, before)
        later = curation.make_plan(self.profile, "A few recommendations", mode="personal", scope="broad")
        self.assertEqual(later["lane_mix"], before["discovery"]["lane_mix"])
        self.assertTrue(later["constraints"]["open_exploration_enabled"])
        self.assertEqual(later["selection_policy"]["kind"], "open_exploration_v1")
        self.assertEqual(self.profile, before)

    def test_connected_surprise_can_coexist_with_a_current_open_opt_out(self):
        self.profile["discovery"]["open_exploration"]["enabled"] = True
        planned = curation.make_plan(self.profile, "Surprise me, but no open exploration", seed=42, scope="broad")
        self.assertEqual(planned["mode"], "surprise")
        self.assertEqual(planned["selection_policy"]["kind"], "connected_surprise_v1")
        self.assertEqual(planned["lane_mix"]["distant"], 0)
        self.assertFalse(planned["constraints"]["open_exploration_enabled"])

    def test_seed_reproduces_weights_and_different_seeds_vary_them(self):
        a = curation.make_plan(self.profile, "surprise me", seed=123)
        b = curation.make_plan(self.profile, "surprise me", seed=123)
        c = curation.make_plan(self.profile, "surprise me", seed=456)
        self.assertEqual(a, b)
        self.assertNotEqual(a["effective_weights"], c["effective_weights"])

    def test_weekly_rotation_and_repeated_broad_requests_change_priorities(self):
        for seed in range(40):
            plan = curation.make_plan(self.profile, "A few recommendations", context="weekly", seed=seed)
            self.assertTrue(plan["variation_applied"])
            self.assertGreaterEqual(plan["rotation_distance_l1"], 0.15)
            self.assertTrue(math.isclose(sum(plan["effective_weights"].values()), 1.0))
        first = curation.make_plan(self.profile, "A few recommendations", repeat_count=0, seed=3)
        repeated = curation.make_plan(self.profile, "A few recommendations", repeat_count=2, seed=3)
        self.assertFalse(first["variation_applied"])
        self.assertEqual(repeated["trigger"], "repeated_broad_rotation")

    def test_fixed_overrides_randomness_and_mode_and_normal_language(self):
        for request in ("surprise me", "Don't surprise me", "no surprises", "use my normal weights"):
            plan = curation.make_plan(self.profile, request, context="weekly", mode="surprise", fixed=True, seed=7)
            self.assertEqual(plan["effective_weights"], plan["baseline_weights"])
            self.assertFalse(plan["variation_applied"])
            self.assertIsNone(plan["seed"])
        for request in ("Don't surprise me", "no surprises", "use my normal weights", "I'm not looking for surprises"):
            self.assertFalse(curation.make_plan(self.profile, request, context="weekly")["variation_applied"])

    def test_public_example_requests_select_expected_modes(self):
        self.assertEqual(curation.make_plan(self.profile, "Go deeper", seed=8)["mode"], "deep")
        self.assertEqual(curation.make_plan(self.profile, "Give me a playful selection", seed=8)["mode"], "playful")
        self.assertEqual(curation.make_plan(self.profile, "Something rigorous", seed=8)["mode"], "deep")
        self.assertEqual(curation.make_plan(self.profile, "Something fun", seed=8)["mode"], "playful")
        self.assertEqual(curation.make_plan(self.profile, "Something outside my usual interests", seed=8)["mode"], "surprise")
        for request in ("Use my usual mix", "Keep the same priorities", "Keep my weights unchanged"):
            plan = curation.make_plan(self.profile, request, context="weekly", seed=8)
            self.assertEqual(plan["mode"], "personal")
            self.assertFalse(plan["variation_applied"])

    def test_narrow_requests_never_receive_unrequested_weekly_or_repeat_rotation(self):
        requests = (
            "Give me a paper about transformer activation patching",
            "A selection of transformer activation patching papers",
            "A few recommendations on medieval manuscript conservation",
            "Some recommendations under 20 minutes",
            "An eclectic smattering",
        )
        for request in requests:
            for context in ("weekly", "on_demand"):
                with self.subTest(request=request, context=context):
                    plan = curation.make_plan(self.profile, request, context=context, repeat_count=5, seed=42)
                    self.assertEqual(plan["scope"], "focused")
                    self.assertEqual(plan["mode"], "personal")
                    self.assertFalse(plan["variation_applied"])
        rigorous = curation.make_plan(self.profile, "Give me a rigorous paper about transformer activation patching", context="weekly", seed=42)
        self.assertEqual(rigorous["mode"], "deep")
        self.assertEqual(rigorous["trigger"], "request_intent:deep")
        self.assertGreater(rigorous["effective_weights"]["depth"], 0.35)

    def test_explicit_scope_controls_unrequested_rotation_not_deliberate_surprise(self):
        focused = curation.make_plan(self.profile, "A few recommendations", context="weekly", scope="focused", seed=42)
        self.assertFalse(focused["variation_applied"])
        broad = curation.make_plan(self.profile, "An eclectic smattering", context="weekly", scope="broad", seed=42)
        self.assertEqual(broad["scope_requested"], "broad")
        self.assertTrue(broad["variation_applied"])
        surprise = curation.make_plan(self.profile, "Surprise me with one film under 90 minutes", context="weekly", scope="focused", seed=42)
        self.assertEqual(surprise["scope"], "focused")
        self.assertEqual(surprise["mode"], "surprise")
        self.assertGreater(surprise["effective_weights"]["surprise"], 0.20)
        self.assertEqual(surprise["constraints"]["request"], "Surprise me with one film under 90 minutes")

    def test_empty_weekly_and_clear_broad_phrases_are_eligible(self):
        for request in ("", "A few recommendations", "Give me a selection", "Things worth my time", "My Sunday personal curation"):
            with self.subTest(request=request):
                plan = curation.make_plan(self.profile, request, context="weekly", seed=42)
                self.assertEqual(plan["scope"], "broad")
                self.assertEqual(plan["trigger"], "weekly_broad_rotation")

    def test_open_surprise_draws_broadly_but_constraints_stay_focused(self):
        broad = curation.make_plan(self.profile, "Surprise me!", seed=42)
        self.assertEqual(broad["scope"], "broad")
        self.assertEqual(broad["mode"], "surprise")
        focused = curation.make_plan(self.profile, "Surprise me with one film under 90 minutes", seed=42)
        self.assertEqual(focused["scope"], "focused")
        self.assertEqual(focused["mode"], "surprise")

    def test_constrained_factual_request_does_not_trigger_rotation(self):
        plan = curation.make_plan(self.profile, "Explain the phrase surprise me", context="weekly", seed=1)
        self.assertEqual(plan["trigger"], "constrained_factual_request")
        self.assertEqual(plan["mode"], "personal")
        resolved = curation.make_plan(self.profile, "Explain the phrase surprise me", mode="deep", seed=1)
        self.assertEqual(resolved["mode"], "deep")

    def test_time_and_medium_constraints_are_preserved_in_plan(self):
        request = "surprise me with one film under 90 minutes"
        plan = curation.make_plan(self.profile, request, seed=5)
        self.assertEqual(plan["constraints"]["request"], request)
        self.assertTrue(plan["constraints"]["preserve_explicit_constraints"])
        self.assertTrue(plan["constraints"]["credibility_gate"])

    def test_fixed_profile_stops_unrequested_rotation_but_intent_still_overrides(self):
        self.profile["taste"]["weighting_policy"]["mode"] = "fixed"
        plan = curation.make_plan(self.profile, "A selection", context="weekly", seed=2)
        self.assertFalse(plan["variation_applied"])
        self.assertEqual(curation.make_plan(self.profile, "surprise me", seed=2)["mode"], "surprise")

    def test_request_can_protect_long_term_profile_without_disabling_surprise(self):
        request = "Surprise me, but don't change my profile permanently"
        plan = curation.make_plan(self.profile, request, seed=4)
        self.assertEqual(plan["mode"], "surprise")
        self.assertFalse(plan["baseline_changed"])

    def test_policy_can_disable_specific_variation_contexts_and_heuristics(self):
        policy = self.profile["taste"]["weighting_policy"]
        policy["variation_contexts"] = []
        self.assertFalse(curation.make_plan(self.profile, context="weekly", seed=3)["variation_applied"])
        policy["request_intent_overrides"] = False
        self.assertEqual(curation.make_plan(self.profile, "surprise me", seed=3)["mode"], "personal")
        self.assertEqual(curation.make_plan(self.profile, mode="surprise", seed=3)["mode"], "surprise")

    def test_invalid_weights_fail(self):
        invalids = ({axis: 0 for axis in curation.AXES}, {"depth": 1},
                    dict(self.profile["taste"]["axes_weights"], depth=float("nan")),
                    dict(self.profile["taste"]["axes_weights"], depth=-1),
                    dict(self.profile["taste"]["axes_weights"], depth=True))
        for invalid in invalids:
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                curation.normalize_weights(invalid)

    def test_unknown_timezone_fails_before_initialization(self):
        with tempfile.TemporaryDirectory() as temporary:
            with self.assertRaises(ValueError):
                curation.initialize(temporary, local_timezone="not/a-real-timezone")
            self.assertFalse((Path(temporary) / "model/profile.json").exists())

    def test_generic_onboarding_does_not_assume_choices_or_context_access(self):
        profile = curation.generic_profile()
        onboarding = profile["onboarding"]
        self.assertEqual(onboarding["status"], "not_started")
        self.assertEqual(onboarding["categories"], [])
        self.assertEqual(onboarding["anchors"], [])
        self.assertEqual(set(onboarding["context_sources"]), {"agent_memory", "past_chats"})
        for source in onboarding["context_sources"].values():
            self.assertEqual(source["permission"], "not_asked")
            self.assertIsNone(source["scope"])
            self.assertEqual(source["availability"], "unknown")
            self.assertEqual(source["source_provenance"], [])
        self.assertEqual(profile["interests"], [])
        self.assertEqual(profile["discovery"]["graph_max_hops"], 2)
        self.assertFalse(profile["discovery"]["open_exploration"]["enabled"])
        self.assertEqual(profile["provenance"], [])
        self.assertEqual(set(profile["media"]["enabled"]),
                         {"youtube_video", "book", "scientific_paper", "film", "podcast", "lecture"})
        self.assertFalse(profile["media"]["music_enabled"])
        self.assertEqual(profile["taste"]["weights_status"], "provisional_equal_weight_default")
        self.assertTrue(all(weight == 1.0 / len(curation.AXES)
                            for weight in profile["taste"]["axes_weights"].values()))

    def test_onboarding_state_is_independent_between_sources_and_profiles(self):
        first = curation.generic_profile()
        second = curation.generic_profile()
        expected = copy.deepcopy(second)
        first["onboarding"]["status"] = "ready"
        first["onboarding"]["categories"].append("podcast")
        first["onboarding"]["anchors"].append({"topic": "synthetic interest"})
        memory = first["onboarding"]["context_sources"]["agent_memory"]
        memory["permission"] = "allowed"
        memory["source_provenance"].append("synthetic-memory-record")
        self.assertEqual(first["onboarding"]["context_sources"]["past_chats"]["permission"], "not_asked")
        self.assertEqual(first["onboarding"]["context_sources"]["past_chats"]["source_provenance"], [])
        self.assertEqual(second, expected)

    def test_init_marks_default_enrollment_without_enabling_delivery(self):
        with tempfile.TemporaryDirectory() as temporary:
            curation.initialize(temporary)
            root = Path(temporary) / "model"
            profile = json.loads((root / "profile.json").read_text())
            self.assertEqual(profile["person"]["id"], "local-user")
            self.assertFalse(profile["delivery"]["weekly"]["enabled"])
            self.assertIs(profile["delivery"]["weekly"]["onboarding_default_pending"], True)
            self.assertIsNone(profile["delivery"]["weekly"]["timezone"])
            self.assertTrue(profile["delivery"]["weekly"]["requires_timezone"])
            self.assertEqual(profile["interests"], [])
            self.assertEqual(profile["provenance"], [])
            self.assertEqual(profile["onboarding"]["status"], "not_started")
            self.assertEqual(profile["onboarding"]["categories"], [])
            self.assertEqual(profile["onboarding"]["anchors"], [])
            self.assertEqual({p.name for p in root.iterdir()}, {"profile.json", "graph.json", "recommendations.jsonl", "feedback.jsonl", "batches.jsonl"})
            self.assertEqual(json.loads((root / "graph.json").read_text()),
                             {"schema_version": 1, "sources": [], "nodes": [], "edges": []})
            self.assertTrue(all((root / (ledger + ".jsonl")).read_bytes() == b""
                                for ledger in ("recommendations", "feedback", "batches")))
            before = (root / "profile.json").read_bytes()
            with self.assertRaises(ValueError):
                curation.initialize(temporary)
            self.assertEqual((root / "profile.json").read_bytes(), before)

    def test_initializer_preserves_a_preexisting_graph_even_without_a_profile(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "model"
            root.mkdir()
            graph = root / "graph.json"
            graph.write_text('{"private_graph":"preserve"}')
            with self.assertRaises(ValueError):
                curation.initialize(temporary)
            self.assertEqual(graph.read_text(), '{"private_graph":"preserve"}')
            self.assertFalse((root / "profile.json").exists())

    def test_cli_weights_does_not_change_any_model_file(self):
        with tempfile.TemporaryDirectory() as temporary:
            curation.initialize(temporary)
            root = Path(temporary) / "model"
            before = {p.name: p.read_bytes() for p in root.iterdir()}
            result = subprocess.run([sys.executable, str(MODULE), "weights", "--root", temporary, "--request", "surprise me", "--seed", "42"], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(result.stdout)["mode"], "surprise")
            self.assertEqual({p.name: p.read_bytes() for p in root.iterdir()}, before)

    def test_cli_scope_is_forwarded(self):
        with tempfile.TemporaryDirectory() as temporary:
            curation.initialize(temporary)
            command = [sys.executable, str(MODULE), "weights", "--root", temporary, "--context", "weekly", "--request", "A few recommendations", "--scope", "focused", "--seed", "42"]
            result = subprocess.run(command, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            plan = json.loads(result.stdout)
            self.assertEqual(plan["scope_requested"], "focused")
            self.assertEqual(plan["scope"], "focused")
            self.assertFalse(plan["variation_applied"])

    def test_demo_does_not_depend_on_working_directory_private_model(self):
        with tempfile.TemporaryDirectory() as temporary:
            private = Path(temporary) / "model"
            private.mkdir()
            (private / "profile.json").write_text("not valid JSON")
            result = subprocess.run([sys.executable, str(MODULE), "demo", "--seed", "42"], cwd=temporary, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(result.stdout)["mode"], "surprise")


if __name__ == "__main__":
    unittest.main()
