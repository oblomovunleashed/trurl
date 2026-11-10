"""Evidence and privacy boundaries of the offline Atlas connection view."""
import copy
import json
from pathlib import Path
import runpy
import subprocess
import sys
import tempfile
import unittest

from test_atlas import AtlasDocument


ROOT = Path(__file__).resolve().parents[1]
ATLAS = ROOT / "skills/trurl/scripts/atlas.py"
HYPOTHESES = ROOT / "skills/trurl/scripts/hypotheses.py"


class AtlasConnectionTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.model = self.root / "model"
        self.model.mkdir()
        self.atlas = runpy.run_path(str(ATLAS))
        self.profile = {"interests": [
            {"id": "bells", "topic": "Bells", "kind": "explicit"},
            {"id": "history", "topic": "History", "kind": "explicit"},
        ]}
        self.graph = {
            "schema_version": 1,
            "sources": [{"id": "source", "kind": "synthetic_fixture",
                         "locator": "https://publisher.example.test/bronze",
                         "title": "Synthetic publisher record", "checked_at": "2026-01-01"}],
            "nodes": [
                {"id": "topic:bells", "type": "topic", "label": "Bells"},
                {"id": "topic:history", "type": "topic", "label": "History"},
                {"id": "work:bronze", "type": "work", "label": "The Bronze Bell",
                 "canonical_url": "https://books.example.test/bronze"},
            ],
            "edges": [
                self.edge("bell-subject", "work:bronze", "about", "topic:bells"),
                self.edge("history-genre", "work:bronze", "in_genre", "topic:history"),
            ],
        }
        self.recommendation = {
            "id": "rec-bronze", "title": "The Bronze Bell", "creator": "A. Founder",
            "canonical_url": "https://books.example.test/bronze",
            "recommended_at": "2026-01-03T15:00:00Z", "status": "recommended",
            "anchor_ids": ["bells", "history"],
            "personal_connection": {"basis": "explicit_interest", "anchor": "bells",
                                    "explanation": "Follows a stated curiosity about bells."},
        }
        self.write_json("profile.json", self.profile)
        self.write_json("graph.json", self.graph)

    @staticmethod
    def edge(identifier, source, relation, target, **changes):
        return {"id": identifier, "source": source, "relation": relation, "target": target,
                "status": "verified", "confidence": 0.9, "source_provenance": ["source"],
                "assertion_method": "synthetic_fixture",
                "support_note": "Synthetic fixture states this relationship.", **changes}

    def write_json(self, name, value):
        (self.model / name).write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")

    def write_recommendations(self, *records):
        (self.model / "recommendations.jsonl").write_text(
            "".join(json.dumps(record, ensure_ascii=False) + "\n" for record in records), encoding="utf-8")

    def data(self):
        return self.atlas["atlas_data"](self.model)

    def connections(self):
        return self.data()["connections"]

    @staticmethod
    def work(connections, identifier="work:bronze"):
        return next(work for work in connections["works"] if work["id"] == identifier)

    def test_two_interests_reach_one_work_with_inspectable_source_edges(self):
        self.write_recommendations(self.recommendation)

        connections = self.connections()
        work = self.work(connections)

        self.assertEqual(connections["status"], "available")
        self.assertTrue(work["recommended"])
        self.assertEqual({route["anchor_id"] for route in work["routes"]}, {"bells", "history"})
        self.assertEqual({tuple(route["edge_ids"]) for route in work["routes"]},
                         {("bell-subject",), ("history-genre",)})
        edges = {edge["id"]: edge for edge in connections["edges"]}
        sources = {source["id"]: source for source in connections["sources"]}
        for route in work["routes"]:
            self.assertIn("work:bronze", route["node_ids"])
            for edge_id in route["edge_ids"]:
                self.assertTrue(edges[edge_id]["support_note"])
                for source_id in edges[edge_id]["source_provenance"]:
                    self.assertEqual(sources[source_id]["checked_at"], "2026-01-01")
                    self.assertTrue(sources[source_id]["locator"].startswith("https://"))

    def test_nearby_labels_do_not_fabricate_personal_anchor_matches(self):
        self.profile["interests"] = [{"id": "local-bells", "topic": "Bells of the Northern Isles", "kind": "explicit"}]
        self.write_json("profile.json", self.profile)

        connections = self.connections()

        self.assertEqual(self.work(connections)["routes"], [])
        anchor = next(anchor for anchor in connections["anchors"] if anchor["id"] == "local-bells")
        self.assertFalse(anchor.get("node_id"))
        self.assertEqual(connections["counts"]["matched_interests"], 0)

    def test_explicit_creator_mapping_reaches_works_without_inferring_creator_preference(self):
        self.profile["interests"] = [{"id": "artisan", "topic": "An artisan’s wider work", "kind": "explicit",
                                     "graph_node_id": "creator:founder"}]
        self.graph["nodes"].extend([
            {"id": "creator:founder", "type": "creator", "label": "A. Founder"},
            {"id": "work:craft", "type": "work", "label": "Craft and Bronze", "canonical_url": "https://books.example.test/craft"},
        ])
        self.graph["edges"].extend([
            self.edge("bronze-author", "work:bronze", "created_by", "creator:founder"),
            self.edge("craft-author", "work:craft", "created_by", "creator:founder"),
        ])
        self.write_json("profile.json", self.profile)
        self.write_json("graph.json", self.graph)

        connections = self.connections()
        routes = self.work(connections)["routes"]

        self.assertEqual(routes[0]["anchor_id"], "artisan")
        self.assertEqual(set(routes[0]["node_ids"]), {"creator:founder", "work:bronze"})
        self.assertEqual(routes[0]["edge_ids"], ["bronze-author"])
        self.assertEqual(self.work(connections, "work:craft")["routes"][0]["edge_ids"], ["craft-author"])

    def test_two_hop_route_keeps_the_intermediate_topic_and_stops_before_third_hop(self):
        self.profile["interests"] = [{"id": "metal", "topic": "Metal crafts", "kind": "explicit"}]
        self.graph["nodes"].extend([
            {"id": "topic:metal", "type": "topic", "label": "Metal crafts"},
            {"id": "creator:founder", "type": "creator", "label": "A. Founder"},
            {"id": "work:other", "type": "work", "label": "An unrelated craft", "canonical_url": "https://books.example.test/other"},
        ])
        self.graph["edges"].extend([
            self.edge("metal-bells", "topic:metal", "broader_than", "topic:bells"),
            self.edge("bronze-author", "work:bronze", "created_by", "creator:founder"),
            self.edge("other-author", "work:other", "created_by", "creator:founder"),
        ])
        self.write_json("profile.json", self.profile)
        self.write_json("graph.json", self.graph)

        connections = self.connections()
        route = self.work(connections)["routes"][0]

        self.assertEqual(set(route["node_ids"]), {"topic:metal", "topic:bells", "work:bronze"})
        self.assertEqual(set(route["edge_ids"]), {"metal-bells", "bell-subject"})
        self.assertEqual(self.work(connections, "work:other")["routes"], [])

    def test_ambiguous_exact_label_match_is_not_guessed(self):
        self.graph["nodes"].append({"id": "topic:other-bells", "type": "topic", "label": "Bells"})
        self.write_json("graph.json", self.graph)

        connections = self.connections()

        self.assertEqual({r["anchor_id"] for r in self.work(connections)["routes"]}, {"history"})
        self.assertEqual(connections["counts"]["unmatched_interests"], 1)

    def test_unverified_retracted_and_low_confidence_edges_never_become_sourced_paths(self):
        for changes in ({"status": "hypothesis"}, {"status": "retracted"}, {"confidence": 0.49}):
            with self.subTest(changes=changes):
                graph = copy.deepcopy(self.graph)
                graph["edges"][0].update(changes)
                self.write_json("graph.json", graph)
                connections = self.connections()
                self.assertEqual({r["anchor_id"] for r in self.work(connections)["routes"]}, {"history"})
                self.assertNotIn("bell-subject", {edge["id"] for edge in connections["edges"]})

    def test_verified_edge_without_provenance_reports_invalid_graph_without_bad_facts(self):
        self.graph["edges"][0]["source_provenance"] = []
        self.write_json("graph.json", self.graph)

        connections = self.connections()

        self.assertEqual(connections["status"], "invalid")
        self.assertTrue(connections["notice"])
        self.assertEqual(connections["edges"], [])
        self.assertEqual(connections["works"], [])
        self.assertEqual(self.data()["counts"]["stated"], 2)

    def test_missing_empty_and_malformed_graph_are_distinct_nonfatal_states(self):
        (self.model / "graph.json").unlink()
        self.assertEqual(self.connections()["status"], "missing")
        self.write_json("graph.json", {"schema_version": 1, "nodes": [], "edges": [], "sources": []})
        self.assertEqual(self.connections()["status"], "empty")
        (self.model / "graph.json").write_text("{not JSON", encoding="utf-8")
        self.assertEqual(self.connections()["status"], "invalid")

    def test_same_title_different_url_does_not_mark_a_researched_work_as_recommended(self):
        recommendation = {**self.recommendation, "canonical_url": "https://books.example.test/different-work"}
        self.write_recommendations(recommendation)

        work = self.work(self.connections())

        self.assertFalse(work["recommended"])
        self.assertEqual(work["editorial_links"], [])

    def test_tracking_and_fragment_normalization_preserves_meaningful_url_queries(self):
        for key in ("edition", "si", "ref", "feature"):
            with self.subTest(query=key):
                self.graph["nodes"][2]["canonical_url"] = "https://books.example.test/bronze?" + key + "=1"
                self.write_json("graph.json", self.graph)
                record = {**self.recommendation, "canonical_url":
                          "https://books.example.test/bronze?utm_source=fixture&" + key + "=1#details"}
                self.write_recommendations(record)
                self.assertTrue(self.work(self.connections())["recommended"])

                record["canonical_url"] = "https://books.example.test/bronze?" + key + "=2"
                self.write_recommendations(record)
                self.assertFalse(self.work(self.connections())["recommended"])

    def test_youtube_aliases_preserve_delivery_and_recorded_reason_in_both_directions(self):
        canonical = "https://youtube.com/watch?v=abc123"
        for alias in ("https://youtu.be/abc123", "https://youtube.com/watch?v=abc123&si=sharing-token",
                      "https://www.youtube.com:443/watch?v=abc123&feature=shared",
                      "https://m.youtube.com/shorts/abc123", "https://youtube.com/embed/abc123",
                      "http://youtube.com/live/abc123"):
            for graph_url, delivered_url in ((canonical, alias), (alias, canonical)):
                with self.subTest(graph_url=graph_url, delivered_url=delivered_url):
                    self.graph["nodes"][2]["canonical_url"] = graph_url
                    self.write_json("graph.json", self.graph)
                    self.write_recommendations({**self.recommendation, "canonical_url": delivered_url})

                    work = self.work(self.connections())

                    self.assertTrue(work["recommended"])
                    self.assertEqual(work["canonical_url"], graph_url)
                    self.assertEqual(len(work["editorial_links"]), 1)
                    self.assertEqual(work["editorial_links"][0]["reason"],
                                     self.recommendation["personal_connection"]["explanation"])

    def test_same_title_or_unsafe_youtube_alias_does_not_establish_delivery(self):
        self.graph["nodes"][2]["canonical_url"] = "https://youtube.com/watch?v=abc123"
        self.write_json("graph.json", self.graph)
        for url in ("https://youtu.be/def456", "https://youtube.com/watch?v=def456&si=abc123",
                    "https://youtu.be.evil.example.test/abc123", "https://user@youtu.be/abc123",
                    "https://youtu.be:8443/abc123", "https://youtu.be:not-a-port/abc123"):
            with self.subTest(url=url):
                self.write_recommendations({**self.recommendation, "canonical_url": url})

                work = self.work(self.connections())

                self.assertFalse(work["recommended"])
                self.assertEqual(work["editorial_links"], [])

    def test_non_video_youtube_paths_do_not_alias_a_delivered_video(self):
        canonical = "https://youtube.com/watch?v=abc123"
        for non_video in ("https://youtube.com/results?search_query=history&v=abc123",
                          "https://youtube.com/channel/some-channel?v=abc123",
                          "https://youtu.be/abc123/unrelated",
                          "https://youtube.com/shorts/abc123/unrelated"):
            for graph_url, delivered_url in ((canonical, non_video), (non_video, canonical)):
                with self.subTest(graph_url=graph_url, delivered_url=delivered_url):
                    self.graph["nodes"][2]["canonical_url"] = graph_url
                    self.write_json("graph.json", self.graph)
                    self.write_recommendations({**self.recommendation, "canonical_url": delivered_url})

                    work = self.work(self.connections())

                    self.assertFalse(work["recommended"])
                    self.assertEqual(work["editorial_links"], [])

    def test_non_video_youtube_paths_preserve_generic_url_identity(self):
        for url in ("https://youtube.com/results?search_query=history&v=abc123",
                    "https://youtube.com/channel/some-channel?v=abc123",
                    "https://youtu.be/abc123/unrelated"):
            with self.subTest(url=url):
                self.graph["nodes"][2]["canonical_url"] = url
                self.write_json("graph.json", self.graph)
                self.write_recommendations({**self.recommendation, "canonical_url": url})
                self.assertTrue(self.work(self.connections())["recommended"])

                separator = "&" if "?" in url else "?"
                self.write_recommendations({**self.recommendation, "canonical_url": url + separator + "si=different"})
                self.assertFalse(self.work(self.connections())["recommended"])

    def test_ambiguous_video_parameters_do_not_establish_delivery(self):
        canonical = "https://youtube.com/watch?v=abc123"
        for ambiguous in ("https://youtube.com/watch?v=def456&v=abc123",
                          "https://youtube.com/watch?v=abc123&v=abc123",
                          "https://youtu.be/abc123?v=def456",
                          "https://youtube.com/shorts/abc123?v=def456"):
            for graph_url, delivered_url in ((canonical, ambiguous), (ambiguous, canonical),
                                             (ambiguous, ambiguous)):
                with self.subTest(graph_url=graph_url, delivered_url=delivered_url):
                    self.graph["nodes"][2]["canonical_url"] = graph_url
                    self.write_json("graph.json", self.graph)
                    self.write_recommendations({**self.recommendation, "canonical_url": delivered_url})

                    work = self.work(self.connections())

                    self.assertFalse(work["recommended"])
                    self.assertEqual(work["editorial_links"], [])

    def test_ambiguous_youtube_graph_aliases_do_not_receive_delivery_or_recorded_reason(self):
        self.graph["nodes"][2]["canonical_url"] = "https://youtube.com/watch?v=abc123"
        self.graph["nodes"].append({"id": "work:ambiguous", "type": "work", "label": "Different title",
                                    "canonical_url": "https://youtu.be/abc123?si=sharing-token"})
        self.write_json("graph.json", self.graph)
        for url in ("https://youtube.com/watch?v=abc123", "https://youtu.be/abc123",
                    "https://youtu.be/abc123?si=sharing-token"):
            with self.subTest(url=url):
                self.write_recommendations({**self.recommendation, "canonical_url": url})

                connections = self.connections()

                for identifier in ("work:bronze", "work:ambiguous"):
                    work = self.work(connections, identifier)
                    self.assertFalse(work["recommended"])
                    self.assertEqual(work["editorial_links"], [])

    def test_ambiguous_graph_work_urls_do_not_receive_a_delivery_claim(self):
        self.graph["nodes"].append({"id": "work:ambiguous", "type": "work", "label": "Different work",
                                    "canonical_url": self.recommendation["canonical_url"]})
        self.write_json("graph.json", self.graph)
        self.write_recommendations(self.recommendation)

        connections = self.connections()

        self.assertFalse(self.work(connections)["recommended"])
        self.assertFalse(self.work(connections, "work:ambiguous")["recommended"])

    def test_reference_negative_temporary_and_unsupported_interests_are_not_connection_anchors(self):
        self.profile["interests"].extend([
            {"id": "quoted", "topic": "Bells", "kind": "explicit", "signal": "reference_only"},
            {"id": "avoided", "topic": "Bells", "kind": "explicit", "signal": "disliked"},
            {"id": "temporary", "topic": "Bells", "kind": "explicit", "scope": "current_request"},
            {"id": "unsupported", "topic": "Bells", "kind": "inferred"},
        ])
        self.write_json("profile.json", self.profile)
        self.write_recommendations({**self.recommendation, "anchor_ids": ["quoted", "avoided", "temporary", "unsupported"],
                                    "personal_connection": {"basis": "explicit_interest", "anchor": "temporary",
                                                            "explanation": "Temporary request context should not become a lasting taste link."}})

        connections = self.connections()

        self.assertEqual({anchor["id"] for anchor in connections["anchors"]}, {"bells", "history"})
        self.assertEqual(self.work(connections)["editorial_links"], [])

    def test_anchor_ids_alone_do_not_invent_a_recommendation_rationale(self):
        record = dict(self.recommendation)
        record.pop("personal_connection")
        self.write_recommendations(record)

        work = self.work(self.connections())

        self.assertTrue(work["recommended"])
        self.assertEqual(work["editorial_links"], [])

    def test_recorded_rationale_is_separate_from_sourced_connections(self):
        self.profile["interests"].append({"id": "cooking", "topic": "Cooking", "kind": "explicit"})
        self.write_json("profile.json", self.profile)
        recommendation = {**self.recommendation, "anchor_ids": ["cooking", "missing-interest"],
                          "personal_connection": {"basis": "explicit_interest", "anchor": "cooking",
                                                  "explanation": "A tentative comparison with hands-on cooking."}}
        self.write_recommendations(recommendation)

        work = self.work(self.connections())

        self.assertNotIn("cooking", {r["anchor_id"] for r in work["routes"]})
        self.assertTrue(work["editorial_links"])
        editorial = work["editorial_links"][0]
        self.assertEqual(editorial["kind"], "recommendation")
        self.assertEqual(editorial["anchor_ids"], ["cooking"])
        self.assertEqual(editorial["reason"], recommendation["personal_connection"]["explanation"])

        counts = self.connections()["counts"]
        self.assertEqual(counts["represented_interests"], 2)
        self.assertEqual(counts["sourced_interests"], 2)
        self.assertEqual(counts["recorded_interests"], 1)

    def test_export_automatically_represents_new_interest_without_inventing_relationships(self):
        self.profile["interests"].append({"id": "northern-bells", "topic": "Bells of the Northern Isles", "kind": "explicit"})
        self.write_json("profile.json", self.profile)
        original_profile = (self.model / "profile.json").read_bytes()

        self.atlas["export_atlas"](self.root)

        graph = json.loads((self.model / "graph.json").read_text())
        self.assertEqual(graph["edges"], self.graph["edges"])
        self.assertEqual(graph["sources"], self.graph["sources"])
        self.assertEqual((self.model / "profile.json").read_bytes(), original_profile)
        connections = self.connections()
        self.assertEqual(connections["counts"]["represented_interests"], 3)
        self.assertEqual(connections["counts"]["sourced_interests"], 2)
        self.assertEqual(connections["counts"]["represented_without_routes"], 1)
        scoped = next(anchor for anchor in connections["anchors"] if anchor["id"] == "northern-bells")
        self.assertIn("node_id", scoped)
        self.assertNotEqual(scoped["node_id"], "topic:bells")
        self.assertEqual(scoped["sourced_work_ids"], [])
        self.assertEqual(scoped["recorded_work_ids"], [])

        before = {name: (self.model / name).read_bytes() for name in ("graph.json", "graph-anchors.json", "profile.json")}
        self.atlas["export_atlas"](self.root)
        for name, original in before.items():
            self.assertEqual((self.model / name).read_bytes(), original)

    def test_export_sync_does_not_repair_or_replace_invalid_graph(self):
        self.graph["edges"][0]["source_provenance"] = []
        self.write_json("graph.json", self.graph)
        original = (self.model / "graph.json").read_bytes()

        result = self.atlas["export_atlas"](self.root)

        self.assertEqual((self.model / "graph.json").read_bytes(), original)
        self.assertEqual(self.connections()["status"], "invalid")
        self.assertFalse(result["anchors_sync"]["completed"])
        self.assertTrue((self.model / "taste-atlas.html").is_file())

    def test_private_binding_maps_creator_and_stops_after_interest_correction(self):
        self.profile["interests"] = [{"id": "artisan", "topic": "A. Founder’s wider work", "kind": "explicit"}]
        self.graph["nodes"].append({"id": "creator:founder", "type": "creator", "label": "A. Founder"})
        self.graph["edges"].append(self.edge("bronze-author", "work:bronze", "created_by", "creator:founder"))
        self.write_json("profile.json", self.profile)
        self.write_json("graph.json", self.graph)
        original_profile = (self.model / "profile.json").read_bytes()
        helper = runpy.run_path(str(ROOT / "skills/trurl/scripts/graph_anchors.py"))
        helper["sync_anchors"](self.root, bindings=[{"anchor_id": "artisan", "node_id": "creator:founder"}])

        connections = self.connections()

        self.assertEqual(connections["counts"]["represented_interests"], 1)
        self.assertEqual(connections["counts"]["sourced_interests"], 1)
        self.assertEqual(connections["anchors"][0]["node_id"], "creator:founder")
        self.assertEqual((self.model / "profile.json").read_bytes(), original_profile)
        self.profile["interests"][0]["topic"] = "Only a different artisan’s work"
        self.write_json("profile.json", self.profile)
        corrected = self.connections()
        self.assertEqual(corrected["counts"]["sourced_interests"], 0)
        self.assertNotIn("node_id", corrected["anchors"][0])

    def test_direct_work_mapping_is_representation_but_not_a_sourced_relationship(self):
        self.profile["interests"] = [{"id": "bronze", "topic": "The Bronze Bell", "kind": "explicit",
                                     "graph_node_id": "work:bronze"}]
        self.write_json("profile.json", self.profile)

        connections = self.connections()

        self.assertEqual(connections["counts"]["represented_interests"], 1)
        self.assertEqual(connections["counts"]["sourced_interests"], 0)
        self.assertEqual(connections["anchors"][0]["mapped_work_ids"], ["work:bronze"])
        self.assertEqual(self.work(connections)["routes"][0]["edge_ids"], [])

    def seed_hypothesis(self):
        self.profile["interests"] = [
            {"id": "novels", "topic": "Fictional encounters", "kind": "explicit",
             "source_provenance": [{"id": "synthetic-original", "locator": "synthetic-stated-interest"}]},
            {"id": "local-history", "topic": "First encounters in the Northern Isles", "kind": "explicit",
             "source_provenance": [{"id": "synthetic-original", "locator": "synthetic-stated-interest"}]},
        ]
        self.write_json("profile.json", self.profile)
        helper = runpy.run_path(str(HYPOTHESES))
        draft = helper["snapshot"](self.root)
        draft["taste_hypotheses"].append({
            "id": "observer-assumptions", "topic": "How encounters challenge assumptions",
            "anchor_ids": ["novels", "local-history"], "reason": "The two interests may share an appeal in revising an observer’s assumptions.",
            "status": "testing", "evidence": [],
        })
        helper["save"](self.root, draft)
        self.write_recommendations({**self.recommendation, "hypothesis_id": "observer-assumptions",
                                    "anchor_ids": ["novels", "local-history"],
                                    "personal_connection": {"basis": "explicit_interest", "anchor": "local-history",
                                                            "explanation": "Tests a possible shared interest in encounters."}})

    def test_hypothesis_connects_original_anchors_without_inventing_content_paths(self):
        self.seed_hypothesis()

        work = self.work(self.connections())

        self.assertEqual(work["routes"], [])
        hypothesis = next(link for link in work["editorial_links"] if link["kind"] == "hypothesis")
        self.assertEqual(set(hypothesis["anchor_ids"]), {"novels", "local-history"})
        self.assertEqual(hypothesis["hypothesis_id"], "observer-assumptions")

    def test_corrected_hypothesis_anchor_removes_stale_editorial_explanation(self):
        self.seed_hypothesis()
        profile = json.loads((self.model / "profile.json").read_text())
        profile["interests"][0]["topic"] = "Different subject"
        self.write_json("profile.json", profile)

        work = self.work(self.connections())

        self.assertEqual(work["routes"], [])
        self.assertFalse(any(link["kind"] == "hypothesis" for link in work["editorial_links"]))
        self.assertFalse(any("observer-assumptions" == link.get("hypothesis_id") for link in work["editorial_links"]))

    def test_export_never_copies_raw_private_records_or_mutates_state(self):
        self.graph["sources"][0]["extra"] = "unused-source-secret"
        self.graph["nodes"][2]["extra"] = "unused-node-secret"
        self.profile["interests"][0]["supporting_words"] = "raw-user-words-secret"
        self.profile["provenance"] = [{"id": "private", "locator": "private-message-location-secret"}]
        self.write_json("graph.json", self.graph)
        self.write_json("profile.json", self.profile)
        self.write_recommendations({**self.recommendation, "unused_trace": "unused-candidate-secret"})
        (self.model / "feedback.jsonl").write_text(json.dumps({"id": "feedback", "user_words": "feedback-secret"}) + "\n")
        (self.model / "curators-brief.json").write_text("unused-brief-secret")
        before = {p.name: p.read_bytes() for p in self.model.iterdir()}

        payload = json.dumps(self.data())

        for marker in ("unused-source-secret", "unused-node-secret", "raw-user-words-secret",
                       "private-message-location-secret", "unused-candidate-secret", "feedback-secret", "unused-brief-secret"):
            self.assertNotIn(marker, payload)
        for filename, original in before.items():
            self.assertEqual((self.model / filename).read_bytes(), original)

    def test_unsafe_urls_never_become_clickable_sources_or_work_links(self):
        self.graph["sources"][0]["locator"] = "javascript:alert(1)"
        self.write_json("graph.json", self.graph)

        connections = self.connections()

        for source in connections["sources"]:
            self.assertNotEqual(source.get("locator"), "javascript:alert(1)")
            if source.get("locator"):
                self.assertTrue(source["locator"].startswith(("https://", "http://")))
        self.graph["nodes"][2]["canonical_url"] = "javascript:alert(2)"
        self.write_json("graph.json", self.graph)
        self.assertEqual(self.connections()["status"], "invalid")

    def test_graph_text_cannot_escape_the_embedded_json_or_load_resources(self):
        marker = '</script><script src="https://evil.example.test/run.js"></script>'
        self.graph["nodes"][2]["label"] = marker
        self.graph["edges"][0]["support_note"] = marker
        self.graph["sources"][0]["title"] = marker
        self.write_json("graph.json", self.graph)

        result = subprocess.run([sys.executable, str(ROOT / "trurl.py"), "atlas", "--root", str(self.root)],
                                cwd=self.root, capture_output=True, text=True, timeout=15)

        self.assertEqual(result.returncode, 0, result.stderr)
        html = (self.model / "taste-atlas.html").read_text()
        document = AtlasDocument(html)
        self.assertEqual(document.external_resources, [])
        self.assertEqual(len(document.data_blocks), 1)
        payload = json.loads("".join(document.data_blocks[0]))
        self.assertEqual(self.work(payload["connections"])["label"], marker)
        self.assertNotIn(marker, html)

    def test_many_interest_routes_are_bounded_and_report_omission(self):
        self.profile["interests"] = []
        self.graph["nodes"] = [self.graph["nodes"][2]]
        self.graph["edges"] = []
        for index in range(7):
            topic = "Subject " + str(index)
            self.profile["interests"].append({"id": "interest-" + str(index), "topic": topic, "kind": "explicit"})
            self.graph["nodes"].append({"id": "topic:" + str(index), "type": "topic", "label": topic})
            self.graph["edges"].append(self.edge("edge-" + str(index), "work:bronze", "about", "topic:" + str(index)))
        self.write_json("profile.json", self.profile)
        self.write_json("graph.json", self.graph)

        connections = self.connections()
        work = self.work(connections)

        self.assertEqual(len(work["routes"]), 4)
        self.assertTrue(work["routes_truncated"])
        self.assertTrue(connections["limits"]["truncated"])
        self.assertEqual(connections["counts"]["sourced_interests"], 7)
        self.assertEqual(len(work["connected_anchor_ids"]), 7)
        exported_edges = {edge["id"] for edge in connections["edges"]}
        for anchor in connections["anchors"]:
            self.assertEqual(anchor["sourced_work_ids"], ["work:bronze"])
            self.assertEqual(anchor["sample_route"]["anchor_id"], anchor["id"])
            self.assertTrue(set(anchor["sample_route"]["edge_ids"]) <= exported_edges)

    def test_large_work_catalog_is_bounded_with_visible_truncation(self):
        self.graph["nodes"] = self.graph["nodes"][:2]
        self.graph["edges"] = []
        for index in range(125):
            identifier = "work:" + str(index)
            self.graph["nodes"].append({"id": identifier, "type": "work", "label": "Synthetic Work " + str(index),
                                        "canonical_url": "https://books.example.test/" + str(index)})
            self.graph["edges"].append(self.edge("edge-" + str(index), identifier, "about", "topic:bells"))
        self.write_json("graph.json", self.graph)

        connections = self.connections()

        self.assertEqual(len(connections["works"]), 120)
        self.assertEqual(connections["limits"]["omitted_works"], 5)
        self.assertTrue(connections["limits"]["truncated"])


if __name__ == "__main__":
    unittest.main()
