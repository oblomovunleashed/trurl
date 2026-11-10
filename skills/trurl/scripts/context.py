#!/usr/bin/env python3
"""Prepare compact current taste context and fetch raw records selectively.

The helper reads local evidence without sending entire ledgers to the host model.
It reconciles existing hypotheses before checking the brief, never synthesizes
preferences, and never returns stale brief prose. Output grows with the interest
inventory and explicit settings, rather than with recommendation history.
"""
import argparse
import hashlib
import json
from pathlib import Path
import runpy
import sys


SKILL = Path(__file__).resolve().parents[1]
IO = runpy.run_path(str(SKILL / "scripts" / "brief.py"))
GRAPH = runpy.run_path(str(SKILL / "scripts" / "graph.py"))
LEDGERS = {"recommendation": "model/recommendations.jsonl",
           "feedback": "model/feedback.jsonl", "batch": "model/batches.jsonl"}
PROFILE_LISTS = {"interest": "interests", "hypothesis": "taste_hypotheses",
                 "provenance": "provenance"}
INTEREST_FIELDS = ("id", "topic", "kind", "confidence", "knowledge_level", "scope",
                   "status", "signal", "polarity", "valence", "source_kind",
                   "origin", "basis", "hypothesis_id") + tuple(sorted(
                       GRAPH["SOURCE_ONLY_SIGNALS"] | {"rejected", "retracted"}))
SETTINGS = ("person", "taste", "discovery", "media", "delivery", "controls",
            "coverage", "pending_questions", "onboarding")


def _digest(data):
    return hashlib.sha256(data).hexdigest() if data is not None else None


def _profile(root):
    data = IO["_read"](root, "model/profile.json")
    if data is None:
        raise ValueError("profile.json is missing; resolve the existing model before onboarding")
    return IO["_parse_source"](data, "model/profile.json")


def _ledger(root, path):
    data = IO["_read"](root, path)
    records = []
    for number, line in enumerate((data or b"").decode("utf-8").splitlines(), 1):
        if line.strip():
            value = IO["_json"](line, path + ":" + str(number))
            if not isinstance(value, dict):
                raise ValueError("JSONL records must be objects: " + path)
            records.append({"locator": "line:" + str(number), "record": value})
    return data, records


def prepare(root):
    """Return current settings/inventory and only checked fresh brief prose.

    Existing hypothesis reconciliation can update managed interests, using its
    normal evidence/atomic-write checks. No brief or personal evidence is authored.
    """
    root = IO["_root"](root)
    profile = _profile(root)
    reconciliation = {"status": "not_needed"}
    if profile.get("taste_hypotheses") or any(
            isinstance(item, dict) and item.get("hypothesis_id")
            for item in profile.get("interests", [])):
        helper = runpy.run_path(str(SKILL / "scripts" / "hypotheses.py"))
        refreshed = helper["refresh"](root)
        reconciliation = {"status": refreshed["status"]}
    profile_bytes = IO["_read"](root, "model/profile.json")
    profile = IO["_parse_source"](profile_bytes, "model/profile.json")
    cache_bytes = IO["_read"](root, IO["BRIEF_PATH"])
    checked = IO["check"](root)
    interests = profile.get("interests", [])
    hypotheses = profile.get("taste_hypotheses", [])
    if not isinstance(interests, list) or any(not isinstance(item, dict) for item in interests):
        raise ValueError("profile interests must be an array of objects")
    if not isinstance(hypotheses, list) or any(not isinstance(item, dict) for item in hypotheses):
        raise ValueError("taste_hypotheses must be an array of objects")
    inventory = [{**{key: item[key] for key in INTEREST_FIELDS if key in item},
                  "has_source_evidence": bool(item.get("source_provenance") or item.get("evidence")),
                  "locator": "#/interests/" + str(index)}
                 for index, item in enumerate(interests)]
    possibility_index = [{**{key: item[key] for key in ("id", "topic", "status", "anchor_ids") if key in item},
                          "locator": "#/taste_hypotheses/" + str(index)}
                         for index, item in enumerate(hypotheses)]
    ledgers = {}
    for kind, path in LEDGERS.items():
        data, records = _ledger(root, path)
        ledgers[kind] = {"path": path, "count": len(records), "sha256": _digest(data)}
    brief = {key: checked[key] for key in ("status", "version", "reasons") if key in checked}
    if checked["status"] == "fresh":
        saved = checked["brief"]
        brief.update(summary=saved["summary"], limits=saved["limits"],
                     source_refs=[{key: ref[key] for key in ("path", "locator")}
                                  for ref in saved["source_refs"]],
                     file_sha256=_digest(cache_bytes))
    # Do not return a brief that was checked against another profile/cache or
    # concurrent evidence revision. The next invocation can take a clean view.
    if (profile_bytes != IO["_read"](root, "model/profile.json")
            or cache_bytes != IO["_read"](root, IO["BRIEF_PATH"])
            or checked != IO["check"](root)):
        raise ValueError("state changed while preparing context; retry")
    return {"root": str(root), "profile_sha256": _digest(profile_bytes),
            "settings": {key: profile[key] for key in SETTINGS if key in profile},
            "other_profile_fields": sorted(set(profile) - set(SETTINGS) - {
                "schema_version", "updated_at", "provenance", "interests", "taste_hypotheses"}),
            "interests": inventory, "taste_hypotheses": possibility_index,
            "hypothesis_reconciliation": reconciliation, "brief": brief,
            "ledgers": ledgers,
            "limits": ["Inventory is an index, not a replacement for original evidence.",
                       "Fetch original records before interpreting selected anchors or feedback.",
                       "Inspect other_profile_fields in the original profile when relevant to this request.",
                       "Missing or stale briefs require source review; no old prose is returned."]}


def records(root, kind, identifiers=(), offset=0, limit=10):
    """Fetch original records by exact ID, or in an explicitly bounded page."""
    root = IO["_root"](root)
    if not 1 <= limit <= 20 or offset < 0 or len(identifiers) > 20:
        raise ValueError("use a nonnegative offset and a limit or ID count of 1–20")
    if identifiers and offset:
        raise ValueError("ID lookup cannot be combined with an offset")
    if kind in PROFILE_LISTS:
        field = PROFILE_LISTS[kind]
        values = _profile(root).get(field, [])
        if not isinstance(values, list) or any(not isinstance(item, dict) for item in values):
            raise ValueError(field + " must be an array of objects")
        path = "model/profile.json"
        found = [{"locator": "#/" + field + "/" + str(index), "record": item}
                 for index, item in enumerate(values)]
    elif kind in LEDGERS:
        path = LEDGERS[kind]
        unused, found = _ledger(root, path)
    else:
        raise ValueError("unknown record kind")
    if identifiers:
        selected = []
        for identifier in dict.fromkeys(identifiers):
            matches = [item for item in found if item["record"].get("id") == identifier]
            if len(matches) != 1:
                raise ValueError("record ID is missing or ambiguous: " + identifier)
            selected.extend(matches)
        next_offset = None
    else:
        selected = found[offset:offset + limit]
        next_offset = offset + len(selected) if offset + len(selected) < len(found) else None
    return {"path": path, "total": len(found), "items": selected, "next_offset": next_offset}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    preparation = commands.add_parser("prepare", help="current compact taste context; reconciles existing hypotheses")
    preparation.add_argument("--root", required=True)
    lookup = commands.add_parser("records", help="fetch original evidence without dumping full ledgers")
    lookup.add_argument("--root", required=True)
    lookup.add_argument("--kind", choices=tuple(PROFILE_LISTS) + tuple(LEDGERS), required=True)
    lookup.add_argument("--id", action="append", default=[], dest="identifiers")
    lookup.add_argument("--offset", type=int, default=0)
    lookup.add_argument("--limit", type=int, default=10)
    args = parser.parse_args(argv)
    try:
        value = (prepare(args.root) if args.command == "prepare" else
                 records(args.root, args.kind, args.identifiers, args.offset, args.limit))
        print(json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":")))
        return 0
    except (ValueError, OSError, TypeError) as error:
        parser.exit(2, "trurl context: %s\n" % error)


if __name__ == "__main__":
    sys.exit(main())
