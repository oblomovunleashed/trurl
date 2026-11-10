"""Exercise private, standalone exports from the Trurl command line."""
from html.parser import HTMLParser
import json
from pathlib import Path
import runpy
import subprocess
import sys
import tempfile
import unittest


TRURL = Path(__file__).resolve().parents[1] / "trurl.py"
HYPOTHESES = TRURL.parent / "skills/trurl/scripts/hypotheses.py"


class AtlasDocument(HTMLParser):
    def __init__(self, html):
        super().__init__()
        self.data_blocks = []
        self.current_data = None
        self.external_resources = []
        self.feed(html)
        self.close()

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "script" and attrs.get("id") == "atlas-data" and attrs.get("type") == "application/json":
            self.current_data = []
            self.data_blocks.append(self.current_data)
        for attribute in ("src", "srcset", "poster", "data"):
            if attribute in attrs and tag in {"script", "img", "source", "iframe", "video", "audio", "embed", "object"}:
                self.external_resources.append((tag, attrs[attribute]))
        if tag == "link" and "href" in attrs:
            self.external_resources.append((tag, attrs["href"]))

    def handle_endtag(self, tag):
        if tag == "script":
            self.current_data = None

    def handle_data(self, data):
        if self.current_data is not None:
            self.current_data.append(data)


class AtlasExportTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.model = self.root / "model"
        self.model.mkdir()

    def write_profile(self, profile):
        (self.model / "profile.json").write_text(json.dumps(profile, ensure_ascii=False), encoding="utf-8")

    def write_ledger(self, filename, records):
        content = "".join(json.dumps(record) + "\n" for record in records)
        (self.model / filename).write_text(content, encoding="utf-8")

    def export(self):
        result = subprocess.run(
            [sys.executable, str(TRURL), "atlas", "--root", str(self.root)],
            cwd=self.root, capture_output=True, text=True, timeout=15,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIsInstance(json.loads(result.stdout), dict)
        html = (self.model / "taste-atlas.html").read_text(encoding="utf-8")
        parsed = AtlasDocument(html)
        self.assertEqual(len(parsed.data_blocks), 1)
        self.assertEqual(parsed.external_resources, [])
        return html, json.loads("".join(parsed.data_blocks[0])), result.stdout

    def seed_hypothesis(self):
        self.write_profile({"interests": [{
            "id": "interest-1", "topic": "Mushroom field guides", "kind": "explicit",
            "source_provenance": [{"id": "source-1", "locator": "private-anchor-message"}],
        }]})
        helper = runpy.run_path(str(HYPOTHESES))
        draft = helper["snapshot"](self.root)
        draft["taste_hypotheses"].append({
            "id": "hypothesis-1", "topic": "Botanical illustration",
            "anchor_ids": ["interest-1"], "reason": "May enjoy close observation through drawing.",
            "status": "testing", "evidence": [],
        })
        helper["save"](self.root, draft)

    def test_older_profile_with_no_ledgers_exports_an_empty_atlas(self):
        self.write_profile({"schema_version": 1})

        _, payload, _ = self.export()

        self.assertEqual(payload["interests"], [])
        self.assertEqual(payload["months"], [])
        self.assertEqual(payload["counts"], {"stated": 0, "tentative": 0, "suggestions": 0, "feedback": 0})
        self.assertEqual(payload["undated"], {"suggestions": 0, "feedback": 0})
        self.assertEqual({path.name for path in self.model.iterdir()}, {"profile.json", "taste-atlas.html"})

    def test_dates_preserve_distinct_activity_without_exporting_source_records(self):
        self.write_profile({
            "schema_version": 3,
            "interests": [
                {"topic": "Bells and bellfounding", "kind": "explicit", "recorded_at": "2025-12-22T18:00:00Z",
                 "source_provenance": [{"locator": "private-source-marker"}]},
                {"topic": "Marsh restoration", "kind": "inferred", "source_provenance": ["synthetic-note-1"]},
                {"topic": "Ensemble film", "kind": "tentative", "source_provenance": ["synthetic-note-2"]},
                {"topic": "One-off topic", "kind": "explicit", "scope": "current_request"},
                {"topic": "Example work", "kind": "explicit", "signal": "reference_only"},
            ],
        })
        self.write_ledger("recommendations.jsonl", [
            {"id": "work-1", "recommended_at": "2025-12-30T16:00:00Z", "status": "completed",
             "title": "private-work-title-marker"},
            {"id": "work-2", "recommended_at": "2026-01-06T14:00:00Z", "status": "recommended"},
            {"id": "work-3", "recommended_at": None, "imported_at": "2026-02-01T12:00:00Z"},
        ])
        self.write_ledger("feedback.jsonl", [
            {"id": "reaction-1", "recorded_at": "2026-01-07T09:00:00Z", "signal": "already_knew",
             "user_words": "private-feedback-marker"},
            {"id": "reaction-2", "recorded_at": "2026-01-20T13:00:00Z", "signal": "want_more"},
            {"id": "reaction-3", "recorded_at": None},
        ])
        (self.model / "curators-brief.json").write_text("private-brief-marker", encoding="utf-8")
        before = {path.name: path.read_bytes() for path in self.model.iterdir()}

        html, payload, stdout = self.export()

        self.assertCountEqual(payload["interests"], [
            {"topic": "Bells and bellfounding", "kind": "stated", "recorded": "2025-12-22"},
            {"topic": "Marsh restoration", "kind": "tentative", "recorded": None},
            {"topic": "Ensemble film", "kind": "tentative", "recorded": None},
        ])
        self.assertEqual(payload["months"], [
            {"month": "2025-12", "suggestions": 1, "feedback": 0},
            {"month": "2026-01", "suggestions": 1, "feedback": 2},
        ])
        self.assertEqual(payload["counts"], {"stated": 1, "tentative": 2, "suggestions": 3, "feedback": 3})
        self.assertEqual(payload["undated"], {"suggestions": 1, "feedback": 1})
        for marker in ("private-source-marker", "private-work-title-marker", "private-feedback-marker", "private-brief-marker"):
            self.assertNotIn(marker, html)
            self.assertNotIn(marker, stdout)
        for filename, original in before.items():
            self.assertEqual((self.model / filename).read_bytes(), original)

    def test_embedded_topic_cannot_end_the_json_script_or_load_a_resource(self):
        topic = 'Sound & light </ScRiPt><script src="//atlas.example.test/payload.js"></script>'
        self.write_profile({"interests": [{"topic": topic, "kind": "explicit"}]})

        _, payload, stdout = self.export()

        self.assertEqual(payload["interests"], [{"topic": topic, "kind": "stated", "recorded": None}])
        self.assertNotIn("atlas.example.test", stdout)

    def test_hypothesis_is_a_possibility_with_its_origin_and_leaves_state_untouched(self):
        self.seed_hypothesis()
        before = {path.name: path.read_bytes() for path in self.model.iterdir()}

        html, payload, _ = self.export()

        self.assertEqual(payload["counts"], {"stated": 1, "tentative": 0, "suggestions": 0, "feedback": 0})
        self.assertEqual(len(payload["interests"]), 1)
        self.assertEqual(len(payload["possibilities"]), 1)
        possibility = payload["possibilities"][0]
        self.assertEqual(possibility["topic"], "Botanical illustration")
        self.assertEqual(possibility["kind"], "possibility")
        self.assertEqual(possibility["anchors"], ["Mushroom field guides"])
        self.assertEqual(possibility["reason"], "May enjoy close observation through drawing.")
        self.assertRegex(possibility["recorded"], r"^\d{4}-\d{2}-\d{2}$")
        self.assertNotIn("private-anchor-message", html)
        for filename, original in before.items():
            self.assertEqual((self.model / filename).read_bytes(), original)

    def test_correcting_the_origin_removes_a_stale_possibility_from_the_export(self):
        self.seed_hypothesis()
        profile = json.loads((self.model / "profile.json").read_text(encoding="utf-8"))
        profile["interests"][0]["topic"] = "Underwater photography"
        self.write_profile(profile)
        original = (self.model / "profile.json").read_bytes()

        _, payload, _ = self.export()

        self.assertEqual(payload["possibilities"], [])
        self.assertEqual([interest["topic"] for interest in payload["interests"]], ["Underwater photography"])
        self.assertEqual((self.model / "profile.json").read_bytes(), original)

    def test_a_confirmed_interest_requires_its_current_feedback_evidence(self):
        self.seed_hypothesis()
        self.write_ledger("feedback.jsonl", [{
            "id": "reaction-1", "recommendation_id": None,
            "recorded_at": "2026-11-06T12:00:00Z", "signal": "confirmed_interest",
            "user_words": "I enjoy botanical illustration.",
            "source_provenance": [{"locator": "private-confirmation-message"}],
        }])
        helper = runpy.run_path(str(HYPOTHESES))
        draft = helper["snapshot"](self.root)
        draft["taste_hypotheses"][0]["evidence"] = [{
            "feedback_id": "reaction-1", "scope": "hypothesis", "effect": "confirm",
            "reason": "The person stated their interest in this topic.",
        }]
        helper["save"](self.root, draft)

        html, payload, _ = self.export()

        self.assertEqual(payload["counts"]["stated"], 2)
        self.assertEqual(payload["possibilities"], [])
        self.assertNotIn("private-confirmation-message", html)
        self.write_ledger("feedback.jsonl", [])
        original = (self.model / "profile.json").read_bytes()

        _, refreshed, _ = self.export()

        self.assertEqual(refreshed["counts"]["stated"], 1)
        self.assertEqual(refreshed["possibilities"], [])
        self.assertEqual((self.model / "profile.json").read_bytes(), original)


if __name__ == "__main__":
    unittest.main()
