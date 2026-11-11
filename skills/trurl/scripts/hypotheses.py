#!/usr/bin/env python3
"""Review and save host-authored taste hypotheses against personal evidence."""
import argparse
from contextlib import contextmanager
import copy
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import runpy
import sys
import tempfile

FILES = ("model/profile.json", "model/feedback.jsonl", "model/recommendations.jsonl")
STATUSES = {"testing", "supported", "confirmed", "rejected", "retired", "stale"}
ENJOYMENT = {"enjoyed", "liked", "loved", "experienced_enjoyment"}
EXCLUDED = {"first_impression", "willingness_to_try", "would_try", "completed", "clicked",
            "skipped", "silence", "current_request", "reference_only", "hypothetical", "assistant_suggestion"}
PREFIX = "hypothesis:"
MAINTENANCE_PATH = "model/hypothesis-maintenance.json"
MAINTENANCE_OUTCOMES = {"saved", "reviewed", "no_proposal"}
MAINTENANCE_COMPONENTS = {"anchors", "feedback", "pool", "low_untried_pool"}
MAINTENANCE_TRIGGERS = {"first_review", "invalid_record", "anchors_changed", "feedback_changed", "pool_changed", "low_untried_pool"}
IO = runpy.run_path(str(Path(__file__).with_name("brief.py")))
GRAPH = runpy.run_path(str(Path(__file__).with_name("graph.py")))
EXCLUDED |= GRAPH["SOURCE_ONLY_SIGNALS"]


class HypothesisError(ValueError):
    pass


class ReviewedProfile(dict):
    """An in-memory review marker that JSON serialization cannot preserve."""


def _hash(value):
    data = json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
    return hashlib.sha256(data.encode()).hexdigest()


def _text(value):
    return isinstance(value, str) and bool(value.strip())


def _signals(record):
    return GRAPH["_signals"](record, GRAPH["SIGNAL_FIELDS"] + ("kind", "feedback_kind"))


def _anchors(profile):
    interests = profile.get("interests", [])
    if not isinstance(interests, list):
        raise HypothesisError("profile interests must be an array")
    raw = [entry for entry in interests if isinstance(entry, dict) and _text(entry.get("id"))
           and not entry.get("hypothesis_id") and not entry["id"].startswith(PREFIX)]
    result = {}
    for entry in GRAPH["personal_anchors"]({"interests": raw}):
        if entry.get("scope") == "current_request" or not _text(entry.get("topic")):
            continue
        if not (entry.get("source_provenance") or entry.get("evidence")):
            continue
        if entry["id"] in result:
            raise HypothesisError("duplicate anchor id: " + entry["id"])
        result[entry["id"]] = entry
    return result


def original_anchors(profile):
    """Return evidence-backed origins eligible for saving a new hypothesis."""
    if not isinstance(profile, dict):
        raise HypothesisError("profile must be an object")
    return list(_anchors(profile).values())


def _anchor_hash(profile, anchor):
    sources = {item["id"]: item for item in profile.get("provenance", [])
               if isinstance(item, dict) and _text(item.get("id"))}
    refs = anchor.get("source_provenance", [])
    referenced = {key: sources.get(key) for key in refs if isinstance(key, str)}
    return _hash({"anchor": anchor, "sources": referenced})


def _origin_current(profile, hypothesis):
    anchors = _anchors(profile)
    expected = hypothesis.get("anchor_hashes")
    ids = hypothesis.get("anchor_ids", [])
    return (isinstance(expected, dict) and bool(ids) and set(expected) == set(ids)
            and all(key in anchors and expected[key] == _anchor_hash(profile, anchors[key]) for key in ids))


def _records(records, label):
    if not isinstance(records, list):
        raise HypothesisError(label + " must be an array")
    indexed = {}
    for record in records:
        if not isinstance(record, dict) or not _text(record.get("id")):
            raise HypothesisError(label + " records need unique ids")
        if record["id"] in indexed:
            raise HypothesisError("duplicate " + label + " id: " + record["id"])
        indexed[record["id"]] = record
    return indexed


def _source_keys(record):
    sources = record.get("source_provenance")
    if not isinstance(sources, list) or not sources:
        raise HypothesisError("feedback requires source provenance")
    keys = set()
    for source in sources:
        if _text(source):
            keys.add(source)
        elif isinstance(source, dict):
            if _signals(source) & EXCLUDED or any(source.get(key) is True for key in EXCLUDED):
                raise HypothesisError("feedback source must be personal evidence")
            if source.get("message_id"):
                keys.add(_hash({"message": source["message_id"], "thread": source.get("thread_id")}))
            elif source.get("locator"):
                keys.add(str(source["locator"]))
            elif source.get("id"):
                keys.add(str(source["id"]))
    if not keys:
        raise HypothesisError("feedback requires identifiable source provenance")
    return keys


def _work_keys(record):
    diversity = runpy.run_path(str(Path(__file__).with_name("diversity.py")))
    keys = diversity["work_keys"](record)
    if not keys:
        raise HypothesisError("supporting recommendation requires a work identity")
    return keys


def _recorded_at(record):
    value = record.get("recorded_at")
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed


def _evidence_state(hypothesis, feedback, history, profile):
    evidence = hypothesis.get("evidence", [])
    if not isinstance(evidence, list):
        raise HypothesisError("hypothesis evidence must be an array")
    feedback_map = _records(feedback, "feedback")
    history_map = _records(history, "recommendation")
    seen, fingerprints, groups, broad = set(), {}, [], []
    contrary_works = set()
    provenance = {source["id"]: source for source in profile.get("provenance", [])
                  if isinstance(source, dict) and _text(source.get("id"))}
    for reference in evidence:
        if not isinstance(reference, dict) or not _text(reference.get("feedback_id")) or not _text(reference.get("reason")):
            raise HypothesisError("evidence needs feedback_id and an interpretation reason")
        identifier = reference["feedback_id"]
        if identifier in seen or identifier not in feedback_map:
            raise HypothesisError("feedback evidence is missing or repeated: " + identifier)
        seen.add(identifier)
        record = feedback_map[identifier]
        if (not _text(record.get("user_words")) or _signals(record) & EXCLUDED
                or any(record.get(key) is True for key in EXCLUDED)):
            raise HypothesisError("feedback cannot support taste learning: " + identifier)
        resolved = dict(record)
        source_refs = record.get("source_provenance")
        if isinstance(source_refs, list):
            resolved["source_provenance"] = [provenance.get(source, source) if isinstance(source, str) else source
                                             for source in source_refs]
        source_keys = _source_keys(resolved)
        effect, scope = reference.get("effect"), reference.get("scope")
        if effect not in {"support", "confirm", "contradict"} or scope not in {"work", "hypothesis"}:
            raise HypothesisError("evidence effect or scope is invalid")
        work = None
        if effect == "support":
            if record.get("signal") not in ENJOYMENT or scope != "work":
                raise HypothesisError("support requires experienced enjoyment of a work")
            recommendation_id = record.get("recommendation_id")
            if recommendation_id not in history_map:
                raise HypothesisError("support requires an existing recommendation")
            work = history_map[recommendation_id]
            identities = _work_keys(work)
            matched = [group for group in groups if group["works"] & identities or group["sources"] & source_keys]
            for group in matched:
                identities.update(group["works"])
                source_keys.update(group["sources"])
                groups.remove(group)
            groups.append({"works": identities, "sources": source_keys})
        elif effect == "confirm":
            if scope != "hypothesis" or record.get("signal") != "confirmed_interest":
                raise HypothesisError("confirmation requires confirmed_interest feedback at hypothesis scope")
            broad.append((_recorded_at(record), list(feedback_map).index(identifier), "confirm"))
        elif scope == "hypothesis":
            if record.get("signal") != "rejected_interest":
                raise HypothesisError("hypothesis rejection requires rejected_interest feedback")
            broad.append((_recorded_at(record), list(feedback_map).index(identifier), "contradict"))
        elif record.get("signal") not in {"not_for_me", "disliked", "want_less"}:
            raise HypothesisError("contrary work evidence requires a negative reaction")
        else:
            recommendation_id = record.get("recommendation_id")
            if recommendation_id not in history_map:
                raise HypothesisError("contrary work evidence requires an existing recommendation")
            work = history_map[recommendation_id]
            contrary_works.update(_work_keys(work))
        fingerprints[identifier] = _hash({"feedback": record, "work": work,
                                         "sources": resolved.get("source_provenance")})
    effects = {item[2] for item in broad}
    ambiguous = len(effects) > 1 and any(item[0] is None for item in broad)
    if broad and all(item[0] is not None for item in broad):
        latest = max(broad)[2]
    else:
        latest = next(iter(effects)) if len(effects) == 1 else None
    return {"confirmed": latest == "confirm", "contradicted": latest == "contradict",
            "supporting_work_count": len(groups), "conflicting_work_feedback": bool(contrary_works),
            "ambiguous_broad_feedback": ambiguous,
            "evidence_hashes": fingerprints}


def _entry(value):
    if not isinstance(value, dict):
        raise HypothesisError("each hypothesis must be an object")
    result = copy.deepcopy(value)
    if any(not _text(result.get(key)) for key in ("id", "topic", "reason")):
        raise HypothesisError("hypothesis needs id, topic and reason")
    if result["id"].startswith(PREFIX):
        raise HypothesisError("hypothesis id uses the reserved managed-interest prefix")
    ids = result.get("anchor_ids")
    if not isinstance(ids, list) or not ids or any(not _text(key) for key in ids) or len(set(ids)) != len(ids):
        raise HypothesisError("hypothesis needs distinct actual anchor_ids")
    result.setdefault("status", "testing")
    result.setdefault("evidence", [])
    if result["status"] not in STATUSES:
        raise HypothesisError("invalid hypothesis status")
    return result


def _status(state):
    if state["ambiguous_broad_feedback"]:
        return "testing"
    if state["contradicted"]:
        return "rejected"
    if state["confirmed"]:
        return "confirmed"
    if state["conflicting_work_feedback"]:
        return "testing"
    if state["supporting_work_count"] >= 2:
        return "supported"
    return "testing"


def _promotion(hypothesis):
    if hypothesis.get("status") not in {"supported", "confirmed"}:
        return None
    return {"id": PREFIX + hypothesis["id"], "topic": hypothesis["topic"],
            "kind": "explicit" if hypothesis["status"] == "confirmed" else "inferred",
            "hypothesis_id": hypothesis["id"], "knowledge_level": "unknown", "knowledge_evidence": [],
            "source_provenance": [{"id": ref["feedback_id"], "kind": "feedback", "locator": "model/feedback.jsonl"}
                                  for ref in hypothesis["evidence"] if ref["effect"] in {"support", "confirm"}],
            "recorded_at": hypothesis.get("updated_at"), "scope": "persistent"}


def validated_profile(profile, feedback=None, history=None):
    """Suppress stale or unreviewable managed interests without modifying state."""
    if not isinstance(profile, dict):
        raise HypothesisError("profile must be an object")
    result = ReviewedProfile(copy.deepcopy(profile))
    result._hypothesis_evidence_reviewed = feedback is not None and history is not None
    entries = profile.get("taste_hypotheses", [])
    if not isinstance(entries, list):
        raise HypothesisError("taste_hypotheses must be an array")
    reviewed, ids = [], set()
    for item in entries:
        current = _entry(item)
        if current["id"] in ids:
            raise HypothesisError("duplicate hypothesis id")
        ids.add(current["id"])
        if current["status"] == "retired":
            reviewed.append(current)
            continue
        if not _origin_current(profile, current):
            current["status"] = "stale"
        elif current["status"] not in {"retired", "stale"}:
            if current["evidence"] and not result._hypothesis_evidence_reviewed:
                current["status"] = "stale"
            else:
                try:
                    state = _evidence_state(current, feedback or [], history or [], profile)
                    if (state["evidence_hashes"] != current.get("evidence_hashes")
                            or _status(state) != current["status"]):
                        current["status"] = "stale"
                    else:
                        # Recompute compact evidence summaries from the checked
                        # ledgers rather than trusting editable cached values.
                        current.update(state)
                except HypothesisError:
                    current["status"] = "stale"
        reviewed.append(current)
    if "taste_hypotheses" in profile:
        result["taste_hypotheses"] = reviewed
    if entries or any(isinstance(item, dict) and item.get("hypothesis_id") for item in profile.get("interests", [])):
        result["interests"] = [copy.deepcopy(item) for item in profile.get("interests", [])
                               if not (isinstance(item, dict) and (item.get("hypothesis_id") or str(item.get("id", "")).startswith(PREFIX)))]
        if result._hypothesis_evidence_reviewed:
            for item in reviewed:
                promoted = _promotion(item)
                if promoted:
                    result["interests"].append(promoted)
    return result


def active_hypotheses(profile):
    """Return testing possibilities rooted in current personal evidence."""
    result = []
    for item in profile.get("taste_hypotheses", []):
        current = _entry(item)
        if current["status"] != "testing" or not _origin_current(profile, current):
            continue
        if current["evidence"] and not getattr(profile, "_hypothesis_evidence_reviewed", False):
            continue
        result.append(copy.deepcopy(current))
    return result


def managed_interest_valid(profile, interest):
    if not getattr(profile, "_hypothesis_evidence_reviewed", False):
        return False
    for entry in profile.get("taste_hypotheses", []):
        if entry.get("id") == interest.get("hypothesis_id") and _origin_current(profile, entry):
            return _promotion(entry) == interest
    return False


def _load(root):
    root = IO["_root"](root)
    data = {path: IO["_read"](root, path) for path in FILES}
    if data[FILES[0]] is None:
        raise HypothesisError("profile.json is missing")
    profile = IO["_json"](data[FILES[0]].decode("utf-8"), FILES[0])
    if not isinstance(profile, dict):
        raise HypothesisError("profile.json must contain an object")
    ledgers = []
    for path in FILES[1:]:
        ledgers.append([IO["_json"](line, path) for line in (data[path] or b"").decode("utf-8").splitlines() if line.strip()])
    sources = [{"path": path, "sha256": hashlib.sha256(data[path]).hexdigest() if data[path] is not None else None}
               for path in FILES]
    return root, profile, ledgers[0], ledgers[1], sources


def snapshot(root):
    unused, profile, feedback, history, sources = _load(root)
    validated_profile(profile, feedback, history)
    return {"schema_version": 1, "sources": sources,
            "taste_hypotheses": copy.deepcopy(profile.get("taste_hypotheses", []))}


@contextmanager
def _lock(root):
    lock = IO["_path"](root, "model/.profile.lock")
    try:
        descriptor = os.open(str(lock), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError as error:
        raise HypothesisError("another profile writer holds model/.profile.lock") from error
    try:
        os.close(descriptor)
        yield
    finally:
        lock.unlink()


def _write(root, profile, expected_sources):
    if _load(root)[4] != expected_sources:
        raise HypothesisError("sources changed during save; review and retry")
    destination = IO["_path"](root, FILES[0])
    descriptor, staged = tempfile.mkstemp(prefix=".profile-hypotheses-", dir=str(destination.parent))
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(profile, handle, ensure_ascii=False, allow_nan=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        if _load(root)[4] != expected_sources:
            raise HypothesisError("sources changed during save; review and retry")
        os.replace(staged, destination)
    finally:
        if os.path.exists(staged):
            os.unlink(staged)


def save(root, draft):
    if not isinstance(draft, dict) or draft.get("schema_version") != 1:
        raise HypothesisError("draft schema_version must be 1")
    entries = draft.get("taste_hypotheses")
    if not isinstance(entries, list):
        raise HypothesisError("draft needs a taste_hypotheses array")
    root = IO["_root"](root)
    with _lock(root):
        unused, profile, feedback, history, sources = _load(root)
        if draft.get("sources") != sources:
            raise HypothesisError("sources changed since snapshot; review current evidence and retry")
        anchors, seen, reviewed = _anchors(profile), set(), []
        now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        old = {item["id"]: item for item in profile.get("taste_hypotheses", [])}
        for item in entries:
            current = _entry(item)
            if current["id"] in seen:
                raise HypothesisError("duplicate hypothesis id")
            seen.add(current["id"])
            previous = old.get(current["id"])
            if previous and (current["topic"] != previous["topic"] or current["anchor_ids"] != previous["anchor_ids"]):
                raise HypothesisError("a changed topic or origin needs a new hypothesis id")
            if current["status"] in {"retired", "stale"} and previous:
                retained = copy.deepcopy(previous)
                retained.update(status=current["status"], reason=current["reason"], updated_at=now)
                reviewed.append(retained)
                continue
            if any(key not in anchors for key in current["anchor_ids"]):
                raise HypothesisError("hypotheses require current personal anchors and cannot anchor other hypotheses")
            state = _evidence_state(current, feedback, history, profile)
            if (current["status"] == "rejected" and not state["contradicted"]
                    and not state["confirmed"] and not state["ambiguous_broad_feedback"]):
                raise HypothesisError("rejection requires explicit broader negative feedback")
            if current["status"] != "retired":
                current["status"] = _status(state)
            current["anchor_hashes"] = {key: _anchor_hash(profile, anchors[key]) for key in current["anchor_ids"]}
            current.update(state)
            current["created_at"] = old.get(current["id"], {}).get("created_at", now)
            current["updated_at"] = now
            reviewed.append(current)
        if sum(item["status"] == "testing" for item in reviewed) > 8:
            raise HypothesisError("keep at most eight hypotheses under exploration")
        result = copy.deepcopy(profile)
        result["taste_hypotheses"] = reviewed
        result = dict(validated_profile(result, feedback, history))
        result["updated_at"] = now
        _write(root, result, sources)
    return {"status": "saved", "hypotheses": reviewed}


def refresh(root):
    root = IO["_root"](root)
    with _lock(root):
        unused, profile, feedback, history, sources = _load(root)
        result = dict(validated_profile(profile, feedback, history))
        if result == profile:
            return {"status": "unchanged", "hypotheses": result.get("taste_hypotheses", [])}
        result["updated_at"] = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        _write(root, result, sources)
    return {"status": "refreshed", "hypotheses": result.get("taste_hypotheses", [])}


def _semantic_hypothesis(item):
    # Save timestamps and cached evidence counts do not constitute a revision.
    ignored = {"created_at", "updated_at", "supporting_work_count", "conflicting_work_feedback",
               "ambiguous_broad_feedback", "confirmed", "contradicted"}
    return {key: value for key, value in item.items() if key not in ignored}


def _maintenance_state(profile, feedback, history):
    anchors = _anchors(profile)
    anchor_hashes = {key: _anchor_hash(profile, anchor) for key, anchor in anchors.items()}
    view = validated_profile(profile, feedback, history)
    pool = view.get("taste_hypotheses", [])
    before = {item["id"]: _hash(_semantic_hypothesis(item))
              for item in profile.get("taste_hypotheses", [])}
    active = active_hypotheses(view)
    active_ids = sorted(item["id"] for item in active)
    history_map = _records(history, "recommendation")
    feedback_map = _records(feedback, "feedback")
    provenance = {source["id"]: source for source in profile.get("provenance", [])
                  if isinstance(source, dict) and _text(source.get("id"))}
    meaningful = {}
    for identifier, record in feedback_map.items():
        if (not _text(record.get("user_words")) or not _signals(record)
                or _signals(record) & (EXCLUDED | {"delivered", "suggested", "consumed", "exposure"})
                or any(record.get(key) is True for key in EXCLUDED)):
            continue
        resolved = copy.deepcopy(record)
        refs = record.get("source_provenance")
        if isinstance(refs, list):
            resolved["source_provenance"] = [provenance.get(ref, ref) if isinstance(ref, str) else ref
                                             for ref in refs]
        try:
            _source_keys(resolved)
        except HypothesisError:
            continue
        meaningful[identifier] = {"feedback": resolved,
                                  "work": history_map.get(record.get("recommendation_id"))}
    exposed = sorted({item["hypothesis_id"] for item in history
                      if _text(item.get("hypothesis_id"))})
    untried = sorted(set(active_ids) - set(exposed))
    # A delivered probe can exhaust research opportunities, never supply taste
    # evidence. Only a sparse untried pool makes this a new review trigger.
    low_pool = sorted(set(active_ids) & set(exposed)) if len(untried) < 2 else None
    components = {"anchors": _hash(anchor_hashes), "feedback": _hash(meaningful),
                  "pool": _hash({item["id"]: _semantic_hypothesis(item) for item in pool}),
                  "low_untried_pool": _hash(low_pool)}
    return {"components": components, "evidence_fingerprint": _hash(components),
            "anchor_hashes": anchor_hashes, "anchors": anchors, "before_hypotheses": before,
            "active": active, "view": view, "exposure_fingerprint": _hash(exposed),
            "pool": {"testing_ids": active_ids, "untried_ids": untried, "count": len(active_ids)}}


def _hashes(value):
    return isinstance(value, dict) and all(_text(key) and isinstance(item, str)
                                          and IO["HASH"].fullmatch(item)
                                          for key, item in value.items())


def _maintenance_receipt(root):
    data = IO["_read"](root, MAINTENANCE_PATH)
    if data is None:
        return None, None
    receipt_hash = hashlib.sha256(data).hexdigest()
    try:
        value = IO["_json"](data.decode("utf-8"), MAINTENANCE_PATH)
    except (ValueError, UnicodeError):
        # A cache is not evidence. Keep its byte hash for concurrency checks but
        # require a new review before replacing an incomplete or damaged record.
        return None, receipt_hash
    if (not isinstance(value, dict) or value.get("schema_version") != 1
            or not isinstance(value.get("outcome"), str)
            or value.get("outcome") not in MAINTENANCE_OUTCOMES
            or not _text(value.get("reason")) or len(value["reason"]) > 500
            or not _text(value.get("completed_at"))
            or not _hashes(value.get("components"))
            or set(value["components"]) != MAINTENANCE_COMPONENTS
            or not _hashes(value.get("anchor_hashes"))
            or value.get("evidence_fingerprint") != _hash(value["components"])
            or not isinstance(value.get("triggers"), list) or not value["triggers"]
            or any(not isinstance(item, str) or item not in MAINTENANCE_TRIGGERS for item in value["triggers"])
            or not isinstance(value.get("hypothesis_ids"), list)
            or any(not _text(item) for item in value["hypothesis_ids"])
            or len(set(value["hypothesis_ids"])) != len(value["hypothesis_ids"])
            or value.get("id") != _hash({key: item for key, item in value.items() if key != "id"})):
        return None, receipt_hash
    return value, receipt_hash


def _maintenance_eligible(anchors, plan, event):
    if event not in {"broad", "onboarding", "feedback"}:
        raise HypothesisError("maintenance event must be broad, onboarding or feedback")
    if event == "broad" and not isinstance(plan, dict):
        raise HypothesisError("broad maintenance requires the retained request plan")
    return bool(anchors) and (event != "broad" or (plan.get("scope") in {"broad", "focused"}
                                                   and plan.get("mode") != "wildcard"))


def _maintenance_pair(state, previous):
    previous_hashes = previous.get("anchor_hashes", {}) if previous else {}
    counts = {key: 0 for key in state["anchors"]}
    for item in state["active"]:
        for key in item["anchor_ids"]:
            if key in counts:
                counts[key] += 1
    keys = sorted(state["anchors"], key=lambda key: (
        previous_hashes.get(key) == state["anchor_hashes"][key], counts[key], key))
    chosen = []
    for key in keys:
        anchor = state["anchors"][key]
        if any(anchor["topic"].strip().casefold() == item["topic"].strip().casefold()
               or (anchor.get("graph_node_id") and anchor.get("graph_node_id") == item.get("graph_node_id"))
               for item in chosen):
            continue
        chosen.append(anchor)
        if len(chosen) == 2:
            break
    result = []
    for anchor in chosen:
        entry = {"id": anchor["id"], "topic_excerpt": anchor["topic"][:240],
                 "kind": str(anchor.get("kind", "unknown"))[:40], "context_omitted": True}
        refs = anchor.get("source_provenance", [])
        if isinstance(refs, list):
            entry["source_refs"] = [str(ref if isinstance(ref, str) else ref.get("id", ref.get("locator", "")))[:240]
                                    for ref in refs[:2] if isinstance(ref, (str, dict))]
        result.append(entry)
    return result


def maintenance_plan(root, plan=None, event="broad"):
    """Plan a bounded host-authored review; do not generate taste or write state."""
    root, profile, feedback, history, unused = _load(root)
    state = _maintenance_state(profile, feedback, history)
    previous, receipt_hash = _maintenance_receipt(root)
    eligible = _maintenance_eligible(state["anchors"], plan, event)
    triggers = []
    if eligible:
        if previous is None:
            triggers.append("invalid_record" if receipt_hash else "first_review")
        else:
            labels = {"anchors": "anchors_changed", "feedback": "feedback_changed",
                      "pool": "pool_changed", "low_untried_pool": "low_untried_pool"}
            if event == "broad" and plan.get("scope") == "focused":
                # Profile evidence still needs review before a narrow request.
                # Replenishing exploration opportunities belongs to broad discovery.
                labels = {key: labels[key] for key in ("anchors", "feedback")}
            for component, label in labels.items():
                if previous["components"][component] != state["components"][component]:
                    triggers.append(label)
    result = {"schema_version": 1, "eligible": eligible, "review_due": bool(triggers),
              "triggers": triggers, "evidence_fingerprint": state["evidence_fingerprint"],
              "event": event, "request_scope": plan.get("scope") if isinstance(plan, dict) else None,
              "request_mode": plan.get("mode") if isinstance(plan, dict) else None}
    if triggers:
        result.update(components=state["components"], before_hypotheses=state["before_hypotheses"],
                      exposure_fingerprint=state["exposure_fingerprint"], receipt_hash=receipt_hash,
                      anchor_pair=_maintenance_pair(state, previous), pool=state["pool"],
                      limits={"max_new_hypotheses": 1, "max_testing_hypotheses": 8},
                      instruction=("Review current originals and feedback. Save at most one defensible new hypothesis "
                                   "with each anchor's contribution, a competing explanation and a testable direction, "
                                   "or revise an existing hypothesis. Record saved, reviewed or no_proposal before research. "
                                   "Use the existing adjacent opportunity; delivery is not enjoyment evidence."))
    elif previous and eligible:
        result["receipt_id"] = previous["id"]
    return result


def maintenance_check(root, plan=None, event="broad"):
    """Return a compact workflow gate; a current receipt records human/agent review."""
    review = maintenance_plan(root, plan, event)
    result = {key: review[key] for key in ("eligible", "review_due", "triggers", "evidence_fingerprint")}
    result["completed"] = review["eligible"] and not review["review_due"]
    if result["completed"]:
        receipt, unused = _maintenance_receipt(IO["_root"](root))
        if receipt is None or receipt["id"] != review.get("receipt_id"):
            raise HypothesisError("maintenance record changed during check; retry")
        result["receipt"] = {key: receipt[key] for key in
                             ("id", "outcome", "hypothesis_ids", "reason", "triggers", "completed_at")}
    return result


def complete_maintenance(root, review, outcome, reason, hypothesis_ids=None):
    """Record a completed review against current evidence without editing preferences."""
    if (not isinstance(review, dict) or review.get("schema_version") != 1
            or review.get("eligible") is not True or review.get("review_due") is not True
            or not _hashes(review.get("components"))
            or set(review["components"]) != MAINTENANCE_COMPONENTS
            or not _hashes(review.get("before_hypotheses"))
            or review.get("evidence_fingerprint") != _hash(review["components"])
            or not isinstance(review.get("triggers"), list) or not review["triggers"]
            or any(not isinstance(item, str) or item not in MAINTENANCE_TRIGGERS for item in review["triggers"])
            or "receipt_hash" not in review):
        raise HypothesisError("completion requires a due maintenance-plan review")
    if outcome not in MAINTENANCE_OUTCOMES or not _text(reason) or len(reason) > 500:
        raise HypothesisError("completion needs a valid outcome and a reason of 1–500 characters")
    ids = hypothesis_ids if hypothesis_ids is not None else []
    if not isinstance(ids, list) or any(not _text(key) for key in ids) or len(ids) != len(set(ids)):
        raise HypothesisError("completion hypothesis_ids must be distinct ids")
    root = IO["_root"](root)
    with _lock(root):
        unused, profile, feedback, history, sources = _load(root)
        state = _maintenance_state(profile, feedback, history)
        unused_receipt, receipt_hash = _maintenance_receipt(root)
        plan = {"scope": review.get("request_scope"), "mode": review.get("request_mode")}
        if not _maintenance_eligible(state["anchors"], plan, review.get("event")):
            raise HypothesisError("this review is not eligible for hypothesis maintenance")
        if (any(review["components"][key] != state["components"][key] for key in ("anchors", "feedback"))
                or review.get("exposure_fingerprint") != state["exposure_fingerprint"]
                or review["receipt_hash"] != receipt_hash):
            raise HypothesisError("maintenance evidence changed since review; plan and review again")
        before, after = review["before_hypotheses"], state["before_hypotheses"]
        new_ids = set(after) - set(before)
        changed_ids = {key for key in after if after[key] != before.get(key)}
        if len(new_ids) > 1:
            raise HypothesisError("maintenance permits at most one new hypothesis per review")
        current = {item["id"]: item for item in state["view"].get("taste_hypotheses", [])}
        if outcome == "saved":
            if len(ids) != 1 or ids[0] not in changed_ids or current[ids[0]]["status"] == "stale":
                raise HypothesisError("saved completion requires one actual new or revised current hypothesis")
            if new_ids - set(ids):
                raise HypothesisError("saved completion must identify the new hypothesis")
        elif outcome == "reviewed":
            if not ids or not set(ids).issubset(state["pool"]["testing_ids"]) or new_ids:
                raise HypothesisError("reviewed completion requires existing usable testing hypotheses")
        elif ids or new_ids:
            raise HypothesisError("no_proposal completion cannot claim hypothesis ids or a new proposal")
        receipt = {"schema_version": 1, "components": state["components"],
                   "anchor_hashes": state["anchor_hashes"],
                   "evidence_fingerprint": state["evidence_fingerprint"], "outcome": outcome,
                   "hypothesis_ids": ids, "reason": reason.strip(),
                   "triggers": review["triggers"],
                   "completed_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")}
        receipt["id"] = _hash(receipt)
        destination = IO["_path"](root, MAINTENANCE_PATH)
        descriptor, staged = tempfile.mkstemp(prefix=".hypothesis-maintenance-", dir=str(destination.parent))
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                json.dump(receipt, handle, ensure_ascii=False, allow_nan=False, indent=2)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            if _load(root)[4] != sources or _maintenance_receipt(root)[1] != receipt_hash:
                raise HypothesisError("sources changed during completion; review and retry")
            os.replace(staged, destination)
        finally:
            if os.path.exists(staged):
                os.unlink(staged)
    return {"status": "completed", "receipt": {key: receipt[key] for key in
                                               ("id", "outcome", "hypothesis_ids", "reason", "triggers", "completed_at")}}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    for command in ("snapshot", "check", "refresh", "save", "maintenance-plan",
                    "maintenance-check", "maintenance-complete"):
        sub = commands.add_parser(command)
        sub.add_argument("--root", required=True)
        if command == "save":
            sub.add_argument("--draft", required=True)
        elif command in {"maintenance-plan", "maintenance-check"}:
            sub.add_argument("--plan", help="retained request-plan JSON; required for broad maintenance")
            sub.add_argument("--event", choices=("broad", "onboarding", "feedback"), default="broad")
        elif command == "maintenance-complete":
            sub.add_argument("--review", required=True, help="saved maintenance-plan JSON")
            sub.add_argument("--outcome", choices=sorted(MAINTENANCE_OUTCOMES), required=True)
            sub.add_argument("--reason", required=True)
            sub.add_argument("--hypothesis-id", action="append", default=[])
    args = parser.parse_args(argv)
    try:
        if args.command == "snapshot":
            result = snapshot(args.root)
        elif args.command == "refresh":
            result = refresh(args.root)
        elif args.command == "check":
            unused, profile, feedback, history, unused_sources = _load(args.root)
            view = validated_profile(profile, feedback, history)
            result = {"status": "checked", "hypotheses": view.get("taste_hypotheses", [])}
        elif args.command in {"maintenance-plan", "maintenance-check"}:
            plan = IO["_json"](Path(args.plan).read_text(encoding="utf-8"), "plan") if args.plan else None
            operation = maintenance_plan if args.command == "maintenance-plan" else maintenance_check
            result = operation(args.root, plan, args.event)
        elif args.command == "maintenance-complete":
            review = IO["_json"](Path(args.review).read_text(encoding="utf-8"), "review")
            result = complete_maintenance(args.root, review, args.outcome, args.reason, args.hypothesis_id)
        else:
            result = save(args.root, IO["_json"](Path(args.draft).read_text(encoding="utf-8"), "draft"))
        print(json.dumps(result, ensure_ascii=False, allow_nan=False, indent=2))
        if args.command == "maintenance-check" and result["eligible"] and result["review_due"]:
            return 1
        return 0
    except (ValueError, OSError, UnicodeError) as error:
        parser.exit(2, "trurl hypotheses: " + str(error) + "\n")


if __name__ == "__main__":
    sys.exit(main())
