#!/usr/bin/env python3
"""Save bounded, source-linked content facts and a checked research receipt.

The host verifies meaning. This helper checks provenance structure, identity,
freshness and completion; graph facts never establish personal preferences.
"""
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
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit


IO = runpy.run_path(str(Path(__file__).with_name("brief.py")))
GRAPH = runpy.run_path(str(Path(__file__).with_name("graph.py")))
GRAPH_PATH = "model/graph.json"
RECEIPT_PATH = "model/graph-maintenance.json"
SECTIONS = ("sources", "nodes", "edges")
LIMITS = {"sources": 8, "nodes": 24, "edges": 24}
PERSONAL_FIELDS = {"hypothesis_id", "anchor_ids", "personal_connection", "personal_fit_status",
                   "supporting_words", "user_words", "knowledge_level", "knowledge_evidence",
                   "preference_signal", "preference_scope", "profile_changes"}


class GraphUpdateError(ValueError):
    pass


def _text(value):
    return isinstance(value, str) and bool(value.strip())


def _hash(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                    allow_nan=False, separators=(",", ":")).encode()).hexdigest()


def _digest(data):
    return hashlib.sha256(data).hexdigest() if data is not None else None


def _url(value):
    if not GRAPH["_web_url"](value):
        raise GraphUpdateError("research and new graph sources need valid HTTP(S) URLs")
    parts = urlsplit(value)
    host = parts.hostname.lower()
    port = parts.port
    if port and not (parts.scheme.lower() == "https" and port == 443 or parts.scheme.lower() == "http" and port == 80):
        host += ":" + str(port)
    query = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True)
             if not k.lower().startswith("utm_") and k.lower() not in {"fbclid", "gclid"}]
    return urlunsplit((parts.scheme.lower(), host, parts.path.rstrip("/") or "/",
                       urlencode(sorted(query)), ""))


def _research(research):
    if not isinstance(research, list) or not all(isinstance(item, dict) for item in research):
        raise GraphUpdateError("research must be an array of candidate records")
    records, seen, source_urls, work_sources = [], set(), set(), {}
    keys = ("id", "title", "creator", "medium", "canonical_url", "description", "verification")
    for item in research:
        identifier = item.get("id")
        if not _text(identifier) or identifier in seen:
            raise GraphUpdateError("research records need unique nonempty ids")
        seen.add(identifier)
        records.append({key: copy.deepcopy(item[key]) for key in keys if key in item})
        verification = item.get("verification", {})
        if not isinstance(verification, dict):
            raise GraphUpdateError("research verification must be an object")
        urls = verification.get("urls", [])
        if not isinstance(urls, list):
            raise GraphUpdateError("research verification.urls must be an array")
        normalized = {_url(url) for url in urls}
        if normalized and not GRAPH["_dated"](verification.get("checked_at"), unknown=False):
            raise GraphUpdateError("research source URLs require dated verification.checked_at")
        source_urls.update(normalized)
        if item.get("canonical_url"):
            work_sources.setdefault(_url(item["canonical_url"]), set()).update(normalized)
    return {"fingerprint": _hash(sorted(records, key=lambda item: item["id"])),
            "source_urls": source_urls, "work_sources": work_sources, "count": len(records)}


def _graph_fingerprint(graph):
    value = copy.deepcopy(graph)
    for section in SECTIONS:
        value[section] = sorted(value[section], key=lambda item: item["id"])
    return _hash(value)


def _load_graph(root):
    data = IO["_read"](root, GRAPH_PATH)
    graph = GRAPH["empty_graph"]() if data is None else IO["_json"](data.decode("utf-8"), GRAPH_PATH)
    GRAPH["validate_graph"](graph)
    return graph, _digest(data)


def _receipt(root):
    data = IO["_read"](root, RECEIPT_PATH)
    digest = _digest(data)
    if data is None:
        return None, digest
    try:
        value = IO["_json"](data.decode("utf-8"), RECEIPT_PATH)
        valid = (isinstance(value, dict) and value.get("schema_version") == 1
                 and value.get("outcome") in {"saved", "no_supported_changes"}
                 and _text(value.get("batch_id")) and _text(value.get("reason"))
                 and len(value["reason"]) <= 500
                 and GRAPH["_dated"](value.get("completed_at"), unknown=False)
                 and all(isinstance(value.get(key), str) and IO["HASH"].fullmatch(value[key])
                         for key in ("research_fingerprint", "graph_fingerprint"))
                 and isinstance(value.get("counts"), dict)
                 and set(value["counts"]) == set(SECTIONS)
                 and all(type(value["counts"][key]) is int and 0 <= value["counts"][key] <= LIMITS[key]
                         for key in SECTIONS)
                 and isinstance(value.get("changed_ids"), dict)
                 and set(value["changed_ids"]) == set(SECTIONS)
                 and all(isinstance(value["changed_ids"][key], list)
                         and len(value["changed_ids"][key]) == value["counts"][key]
                         and all(_text(identifier) for identifier in value["changed_ids"][key])
                         for key in SECTIONS)
                 and value.get("id") == _hash({key: item for key, item in value.items() if key != "id"}))
    except (ValueError, UnicodeError, TypeError):
        valid = False
    return (value if valid else None), digest


def _compact(receipt):
    return {key: copy.deepcopy(receipt[key]) for key in
            ("id", "outcome", "batch_id", "counts", "reason", "completed_at")}


def update_plan(root, research, batch_id):
    """Return constant-size review metadata; no graph or research prose is echoed."""
    if not _text(batch_id) or len(batch_id) > 200:
        raise GraphUpdateError("batch_id must be 1–200 characters")
    root = IO["_root"](root)
    inputs = _research(research)
    graph, graph_sha = _load_graph(root)
    previous, receipt_sha = _receipt(root)
    fingerprint = _graph_fingerprint(graph)
    triggers = []
    if previous is None:
        triggers.append("invalid_record" if receipt_sha else "missing_record")
    else:
        for field, current, trigger in (("batch_id", batch_id, "new_batch"),
                                        ("research_fingerprint", inputs["fingerprint"], "research_changed"),
                                        ("graph_fingerprint", fingerprint, "graph_changed")):
            if previous[field] != current:
                triggers.append(trigger)
    result = {"schema_version": 1, "batch_id": batch_id, "review_due": bool(triggers),
              "completed": not triggers, "triggers": triggers,
              "research_fingerprint": inputs["fingerprint"], "graph_fingerprint": fingerprint}
    if triggers:
        result.update(graph_sha256=graph_sha, receipt_sha256=receipt_sha,
                      counts={key: len(graph[key]) for key in SECTIONS}, limits=copy.deepcopy(LIMITS),
                      research_count=inputs["count"],
                      instruction="Save only source-verified content relationships from this research, or record no supported changes. Reuse existing identities. Never turn personal fit or a hypothesis into a content fact.")
    else:
        result["receipt"] = _compact(previous)
    return result


def check_update(root, research, batch_id):
    plan = update_plan(root, research, batch_id)
    return {key: value for key, value in plan.items() if key in {
        "batch_id", "completed", "review_due", "triggers", "research_fingerprint", "graph_fingerprint", "receipt"}}


def _personal_data(value):
    if isinstance(value, dict):
        return bool(PERSONAL_FIELDS.intersection(value)) or any(_personal_data(item) for item in value.values())
    if isinstance(value, list):
        return any(_personal_data(item) for item in value)
    return False


def _node_key(node):
    if node.get("type") == "work":
        if not node.get("canonical_url"):
            return ("work_label", GRAPH["_normal"](node.get("label")))
        return ("work", _url(node["canonical_url"]))
    return (node.get("type"), GRAPH["_normal"](node.get("label")))


def _edge_key(edge):
    ends = (edge.get("source"), edge.get("target"))
    if edge.get("relation") == "related_to":
        ends = tuple(sorted(ends))
    return (edge.get("relation"),) + ends


def _source_key(source):
    locator = source.get("locator")
    return _url(locator) if GRAPH["_web_url"](locator) else locator


def _upsert(graph, delta, research):
    if delta is None:
        delta = dict(schema_version=1, sources=[], nodes=[], edges=[])
    if not isinstance(delta, dict) or delta.get("schema_version") != 1 or set(delta) != {"schema_version", *SECTIONS}:
        raise GraphUpdateError("delta requires schema_version 1 and sources, nodes, edges arrays")
    incoming_ids = set()
    for section in SECTIONS:
        entries = delta[section]
        if not isinstance(entries, list) or len(entries) > LIMITS[section]:
            raise GraphUpdateError("delta exceeds " + section + " bound of " + str(LIMITS[section]))
        for entry in entries:
            if not isinstance(entry, dict) or not _text(entry.get("id")) or entry["id"] in incoming_ids:
                raise GraphUpdateError("delta records require globally unique ids")
            if _personal_data(entry):
                raise GraphUpdateError("personal preference or hypothesis data cannot become graph facts")
            incoming_ids.add(entry["id"])
    result = copy.deepcopy(graph)
    all_ids = {entry["id"]: section for section in SECTIONS for entry in result[section]}
    remap = {section: {} for section in SECTIONS}
    changed = {section: [] for section in SECTIONS}
    key_functions = {"sources": _source_key, "nodes": _node_key, "edges": _edge_key}
    inputs = _research(research)
    for section in SECTIONS:
        indexed = {entry["id"]: entry for entry in result[section]}
        identities = {}
        for entry in result[section]:
            key = key_functions[section](entry)
            if key in identities:
                raise GraphUpdateError("existing graph has duplicate semantic identities; reconcile " + section + " first")
            identities[key] = entry["id"]
        for raw in delta[section]:
            item = copy.deepcopy(raw)
            identifier = item["id"]
            if identifier in all_ids and all_ids[identifier] != section:
                raise GraphUpdateError("graph id collides across record types: " + identifier)
            if section == "sources":
                if _url(item.get("locator")) not in inputs["source_urls"]:
                    raise GraphUpdateError("graph source is absent from current verified research URLs: " + identifier)
                if not GRAPH["_dated"](item.get("checked_at"), unknown=False):
                    raise GraphUpdateError("updated sources require a dated checked_at")
            elif section == "nodes":
                if item.get("type") == "work" and (not item.get("canonical_url") or _url(item["canonical_url"]) not in inputs["work_sources"]):
                    raise GraphUpdateError("work nodes require a canonical URL in current research")
                if not _text(item.get("label")) or len(item["label"]) > 240:
                    raise GraphUpdateError("node labels must be 1–240 characters")
            else:
                if any(not _text(item.get(end)) for end in ("source", "target")):
                    raise GraphUpdateError("edge requires source and target ids")
                for end in ("source", "target"):
                    item[end] = remap["nodes"].get(item.get(end), item.get(end))
                if (not isinstance(item.get("source_provenance"), list)
                        or any(not _text(ref) for ref in item["source_provenance"])):
                    raise GraphUpdateError("edge requires source_provenance array")
                item["source_provenance"] = sorted({remap["sources"].get(ref, ref) for ref in item["source_provenance"]})
            key = key_functions[section](item)
            old_id = identities.get(key)
            if identifier in indexed and key_functions[section](indexed[identifier]) != key:
                raise GraphUpdateError("existing graph id cannot be retargeted: " + identifier)
            if old_id and identifier in indexed and old_id != identifier:
                raise GraphUpdateError("ambiguous graph identity collision: " + identifier)
            target_id = old_id or identifier
            previous = indexed.get(target_id)
            item["id"] = target_id
            if section == "edges":
                if previous and item.get("relation") == "related_to":
                    # Undirected identity should not churn the stored orientation.
                    item["source"], item["target"] = previous["source"], previous["target"]
            merged = copy.deepcopy(previous) if previous else {}
            merged.update(item)
            if previous and "created_at" in previous:
                merged["created_at"] = previous["created_at"]
            if section == "edges":
                if (previous and previous.get("status") == "retracted" and merged.get("status") != "retracted"
                        and identifier != target_id):
                    raise GraphUpdateError("reactivating a retracted edge requires its explicit existing id")
                substantive = {key: value for key, value in merged.items() if key not in {"created_at", "checked_at"}}
                old_substantive = {key: value for key, value in (previous or {}).items() if key not in {"created_at", "checked_at"}}
                if merged.get("status") == "verified" and substantive != old_substantive:
                    # A changed verified claim needs current explicit support;
                    # a partial update cannot reuse an old verification note.
                    if not _text(item.get("support_note")) or len(item["support_note"]) > 500:
                        raise GraphUpdateError("verified edge needs a support_note of 1–500 characters")
                    sources = {source["id"]: source for source in result["sources"]}
                    source_urls = set()
                    for ref in merged["source_provenance"]:
                        if ref not in sources or _url(sources[ref]["locator"]) not in inputs["source_urls"]:
                            raise GraphUpdateError("changed verified edge must cite current research sources")
                        source_urls.add(_url(sources[ref]["locator"]))
                    if previous and previous.get("status") == "retracted":
                        old_sources = {source["id"]: source for source in graph["sources"]}
                        def evidence_date(value):
                            if not GRAPH["_dated"](value, unknown=False):
                                return datetime.min.replace(tzinfo=timezone.utc)
                            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
                            return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed
                        if not any(ref not in old_sources or evidence_date(sources[ref]["checked_at"]) > max(
                                evidence_date(old_sources[ref].get("checked_at")),
                                evidence_date(previous.get("checked_at")))
                                   for ref in merged["source_provenance"]):
                            raise GraphUpdateError("reactivating a retracted edge requires newly checked evidence")
                    nodes = {node["id"]: node for node in result["nodes"]}
                    work = nodes.get(merged.get("source"), {})
                    if work.get("type") == "work" and not source_urls.issubset(inputs["work_sources"].get(_url(work.get("canonical_url")), set())):
                        raise GraphUpdateError("work relationship cites sources not verified for that work")
            if previous != merged:
                if previous:
                    result[section][result[section].index(previous)] = merged
                else:
                    result[section].append(merged)
                indexed[target_id] = merged
                identities[key] = target_id
                all_ids[target_id] = section
                if target_id not in changed[section]:
                    changed[section].append(target_id)
            remap[section][identifier] = target_id
    GRAPH["validate_graph"](result)
    return result, changed


@contextmanager
def _lock(root):
    path = IO["_path"](root, "model/.graph.lock")
    try:
        descriptor = os.open(str(path), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError as error:
        raise GraphUpdateError("another graph writer holds model/.graph.lock") from error
    try:
        os.close(descriptor)
        yield
    finally:
        path.unlink()


def _atomic(root, relative, value, check_current=None):
    destination = IO["_path"](root, relative)
    descriptor, staged = tempfile.mkstemp(prefix=".graph-update-", dir=str(destination.parent))
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(value, handle, ensure_ascii=False, allow_nan=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        if check_current is not None:
            check_current()
        os.replace(staged, destination)
    finally:
        if os.path.exists(staged):
            os.unlink(staged)


def complete_update(root, research, review, delta=None, reason=""):
    if (not isinstance(review, dict) or review.get("schema_version") != 1
            or review.get("review_due") is not True or review.get("completed") is not False
            or "graph_sha256" not in review or "receipt_sha256" not in review):
        raise GraphUpdateError("completion requires a due graph-update-plan review")
    if not _text(reason) or len(reason) > 500:
        raise GraphUpdateError("completion needs a reason of 1–500 characters")
    root = IO["_root"](root)
    with _lock(root):
        current = update_plan(root, research, review.get("batch_id"))
        fields = ("batch_id", "research_fingerprint", "graph_fingerprint", "graph_sha256", "receipt_sha256")
        if not current["review_due"] or any(current.get(key) != review.get(key) for key in fields):
            raise GraphUpdateError("graph, research or completion record changed since review; review again")
        graph, unused = _load_graph(root)
        result, changed = _upsert(graph, delta, research)
        did_change = _graph_fingerprint(result) != _graph_fingerprint(graph)
        receipt = {"schema_version": 1, "batch_id": review["batch_id"],
                   "research_fingerprint": current["research_fingerprint"],
                   "graph_fingerprint": _graph_fingerprint(result),
                   "outcome": "saved" if did_change else "no_supported_changes",
                   "counts": {key: len(changed[key]) for key in SECTIONS}, "changed_ids": changed,
                   "reason": reason.strip(),
                   "completed_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")}
        receipt["id"] = _hash(receipt)
        if (_load_graph(root)[1] != current["graph_sha256"] or _receipt(root)[1] != current["receipt_sha256"]):
            raise GraphUpdateError("graph sources changed during save; review again")
        def graph_current():
            if (_load_graph(root)[1] != current["graph_sha256"] or _receipt(root)[1] != current["receipt_sha256"]):
                raise GraphUpdateError("graph sources changed during staging; review again")
        if did_change:
            _atomic(root, GRAPH_PATH, result, graph_current)
        # If interrupted after graph replacement, the old receipt no longer
        # matches. Never write a successful receipt before the graph is saved.
        if _graph_fingerprint(_load_graph(root)[0]) != receipt["graph_fingerprint"]:
            raise GraphUpdateError("graph changed before completion was recorded; review again")
        if _receipt(root)[1] != current["receipt_sha256"]:
            raise GraphUpdateError("completion record changed during save; review again")
        def receipt_current():
            if (_graph_fingerprint(_load_graph(root)[0]) != receipt["graph_fingerprint"]
                    or _receipt(root)[1] != current["receipt_sha256"]):
                raise GraphUpdateError("graph or completion record changed during staging; review again")
        _atomic(root, RECEIPT_PATH, receipt, receipt_current)
    return {"status": "completed", "receipt": _compact(receipt)}


def _read_research(path):
    raw = Path(path).expanduser().read_text(encoding="utf-8")
    return (IO["_json"](raw, "research") if raw.lstrip().startswith("[") else
            [IO["_json"](line, "research") for line in raw.splitlines() if line.strip()])


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("graph-update-plan", "graph-update", "graph-update-check"):
        command = commands.add_parser(name)
        command.add_argument("--root", required=True)
        command.add_argument("--research", required=True)
        if name == "graph-update":
            command.add_argument("--review", help="saved graph-update-plan JSON; omit when passing --batch-id")
            command.add_argument("--batch-id", help="plan and complete in one call for this batch")
            command.add_argument("--delta")
            command.add_argument("--reason", required=True)
        else:
            command.add_argument("--batch-id", required=True)
    args = parser.parse_args(argv)
    if args.command == "graph-update" and bool(args.review) == bool(args.batch_id):
        parser.error("graph-update needs exactly one of --review or --batch-id")
    try:
        research = _read_research(args.research)
        if args.command == "graph-update":
            delta = IO["_json"](Path(args.delta).read_text(encoding="utf-8"), "delta") if args.delta else None
            if args.review:
                review = IO["_json"](Path(args.review).read_text(encoding="utf-8"), "review")
                result = complete_update(args.root, research, review, delta, args.reason)
            else:
                # One call: take the review now and complete it. The review holds only
                # fingerprints, so nothing needs inspecting between the two steps.
                anchors = runpy.run_path(str(Path(__file__).with_name("graph_anchors.py")))
                anchor_sync = anchors["sync_anchors"](args.root)
                review = update_plan(args.root, research, args.batch_id)
                result = (complete_update(args.root, research, review, delta, args.reason) if review["review_due"]
                          else {"status": "current", "receipt": review["receipt"]})
                if anchor_sync["status"] != "current" or anchor_sync["warnings"]:
                    result["graph_anchors"] = anchor_sync
        else:
            anchor_sync = None
            if args.command == "graph-update-plan":
                anchors = runpy.run_path(str(Path(__file__).with_name("graph_anchors.py")))
                anchor_sync = anchors["sync_anchors"](args.root)
            operation = update_plan if args.command == "graph-update-plan" else check_update
            result = operation(args.root, research, args.batch_id)
            if anchor_sync is not None and (anchor_sync["status"] != "current" or anchor_sync["warnings"]):
                result["graph_anchors"] = anchor_sync
        print(json.dumps(result, ensure_ascii=False, allow_nan=False, indent=2))
        return 1 if args.command == "graph-update-check" and result["review_due"] else 0
    except (OSError, ValueError, TypeError, KeyError) as error:
        parser.exit(2, "trurl graph update: " + str(error) + "\n")


if __name__ == "__main__":
    sys.exit(main())
