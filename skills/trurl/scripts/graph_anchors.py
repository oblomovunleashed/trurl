#!/usr/bin/env python3
"""Represent durable interests in the content graph without inventing relationships.

Mappings are private derived state. Literal isolated nodes need no source claim;
only the separate researched graph-update workflow may create content edges.
"""
import argparse
import hashlib
import json
from pathlib import Path
import runpy
import sys


IO = runpy.run_path(str(Path(__file__).with_name("brief.py")))
GRAPH = runpy.run_path(str(Path(__file__).with_name("graph.py")))
UPDATES = runpy.run_path(str(Path(__file__).with_name("graph_updates.py")))
MAPPING_PATH = "model/graph-anchors.json"
INPUT_PATHS = ("model/profile.json", "model/feedback.jsonl", "model/recommendations.jsonl")
METHODS = {"profile", "explicit_binding", "exact", "generated"}


def _hash(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                    allow_nan=False, separators=(",", ":")).encode()).hexdigest()


def _anchors(profile, persistent_only=True):
    anchors = [item for item in GRAPH["personal_anchors"](profile)
               if not persistent_only or item.get("scope") != "current_request"]
    if any(not GRAPH["_text"](item.get("id")) for item in anchors):
        raise ValueError("personal anchor ids must be nonempty strings")
    if len({item["id"] for item in anchors}) != len(anchors):
        raise ValueError("duplicate personal anchor id")
    return anchors


def _anchor_fingerprint(profile, anchor):
    sources = {item["id"]: item for item in profile.get("provenance", [])
               if isinstance(item, dict) and GRAPH["_text"](item.get("id"))}
    refs = anchor.get("source_provenance", [])
    return _hash({"anchor": anchor,
                  "sources": {key: sources.get(key) for key in refs if isinstance(key, str)}})


def _node_fingerprint(node):
    # Aliases may be enriched without changing the entity's identity.
    return _hash({key: node[key] for key in ("id", "type", "label", "canonical_url") if key in node})


def _empty_mappings():
    return {"schema_version": 1, "mappings": [], "fingerprint": _hash([])}


def _validate_mappings(value):
    if (not isinstance(value, dict) or value.get("schema_version") != 1
            or not isinstance(value.get("mappings"), list)
            or value.get("fingerprint") != _hash(value["mappings"])):
        raise ValueError("invalid graph anchor mappings; inspect model/graph-anchors.json")
    seen = set()
    for record in value["mappings"]:
        if (not isinstance(record, dict) or set(record) != {
                "anchor_id", "anchor_fingerprint", "node_id", "node_fingerprint", "method"}
                or any(not GRAPH["_text"](record.get(key)) for key in ("anchor_id", "node_id"))
                or any(not isinstance(record.get(key), str) or not IO["HASH"].fullmatch(record[key])
                       for key in ("anchor_fingerprint", "node_fingerprint"))
                or not isinstance(record.get("method"), str) or record["method"] not in METHODS
                or record["anchor_id"] in seen):
            raise ValueError("invalid graph anchor mapping record")
        seen.add(record["anchor_id"])
    return value


def read_mappings(root):
    """Read private mappings safely; a missing sidecar is an empty mapping set."""
    root = IO["_root"](root)
    data = IO["_read"](root, MAPPING_PATH)
    return _empty_mappings() if data is None else _validate_mappings(
        IO["_json"](data.decode("utf-8"), MAPPING_PATH))


def _current_mapping(record, profile, anchor, nodes):
    return (record and record["anchor_fingerprint"] == _anchor_fingerprint(profile, anchor)
            and record["node_id"] in nodes
            and record["node_fingerprint"] == _node_fingerprint(nodes[record["node_id"]])
            and (record["method"] != "exact"
                 or GRAPH["_normal"](anchor.get("topic")) in GRAPH["_labels"](nodes[record["node_id"]])))


def match_anchors(graph, profile, mappings=None, persistent_only=True):
    """Pure matching shared by retrieval and Atlas; never edits the profile."""
    GRAPH["validate_graph"](graph)
    sidecar = _validate_mappings(mappings) if mappings is not None else _empty_mappings()
    saved = {item["anchor_id"]: item for item in sidecar["mappings"]}
    nodes = {item["id"]: item for item in graph["nodes"]}
    matches, unmatched, warnings = {}, [], []
    for anchor in _anchors(profile, persistent_only):
        identifier = anchor["id"]
        explicit = anchor.get("graph_node_id")
        if GRAPH["_text"](explicit):
            candidates = [explicit] if explicit in nodes else []
            if not candidates:
                warnings.append("Missing explicit graph node for anchor " + identifier + "; review its mapping.")
        elif _current_mapping(saved.get(identifier), profile, anchor, nodes):
            candidates = [saved[identifier]["node_id"]]
        else:
            candidates = sorted(node["id"] for node in nodes.values() if node["type"] == "topic"
                                and GRAPH["_normal"](anchor.get("topic")) in GRAPH["_labels"](node))
        if len(candidates) == 1:
            matches[identifier] = candidates[0]
        else:
            unmatched.append(identifier)
            if len(candidates) > 1:
                warnings.append("Ambiguous exact graph-label match for anchor " + identifier + "; supply an explicit binding.")
    return {"matches": matches, "unmatched_anchor_ids": unmatched, "warnings": warnings}


def _profile(root, snapshot):
    if snapshot["model/profile.json"] is None:
        raise ValueError("graph anchor sync requires model/profile.json")
    profile = IO["_json"](snapshot["model/profile.json"].decode("utf-8"), "model/profile.json")
    if not isinstance(profile, dict):
        raise ValueError("profile must be an object")
    if profile.get("taste_hypotheses"):
        def records(path):
            raw = snapshot[path]
            return [] if raw is None else [IO["_json"](line, path) for line in raw.decode("utf-8").splitlines() if line.strip()]
        helper = runpy.run_path(str(Path(__file__).with_name("hypotheses.py")))
        profile = helper["validated_profile"](profile, records("model/feedback.jsonl"), records("model/recommendations.jsonl"))
    return profile


def sync_anchors(root, bindings=None):
    """Idempotently save literal nodes and private mappings, never content edges.

Optional bindings are host-reviewed {anchor_id, node_id} records identifying
already-existing typed nodes. The host verifies identity and matching scope.
"""
    root = IO["_root"](root)
    if bindings is not None and (not isinstance(bindings, list) or any(
            not isinstance(item, dict) or set(item) != {"anchor_id", "node_id"}
            or any(not GRAPH["_text"](item.get(key)) for key in ("anchor_id", "node_id")) for item in bindings)):
        raise ValueError("bindings must be an array of {anchor_id, node_id} records")
    binding_map = {item["anchor_id"]: item["node_id"] for item in bindings or []}
    if len(binding_map) != len(bindings or []):
        raise ValueError("duplicate anchor binding")
    with UPDATES["_lock"](root):
        snapshot = {path: IO["_read"](root, path) for path in INPUT_PATHS + (MAPPING_PATH, "model/graph.json")}
        profile = _profile(root, snapshot)
        graph, _ = UPDATES["_load_graph"](root)
        sidecar = read_mappings(root)
        saved = {item["anchor_id"]: item for item in sidecar["mappings"]}
        nodes = {item["id"]: item for item in graph["nodes"]}
        anchors = _anchors(profile)
        if set(binding_map) - {item["id"] for item in anchors}:
            raise ValueError("binding refers to an ineligible or unknown personal anchor")
        if set(binding_map.values()) - set(nodes):
            raise ValueError("binding must refer to an existing graph node")
        updated, added, unresolved, warnings = [], 0, 0, []
        for anchor in anchors:
            identifier = anchor["id"]
            explicit, bound = anchor.get("graph_node_id"), binding_map.get(identifier)
            previous = saved.get(identifier)
            if bound and GRAPH["_text"](explicit) and explicit != bound:
                raise ValueError("binding conflicts with profile graph_node_id for " + identifier)
            if bound:
                node_id, method = bound, "explicit_binding"
            elif GRAPH["_text"](explicit):
                if explicit not in nodes:
                    unresolved += 1
                    warnings.append("Missing explicit graph node for anchor " + identifier + "; review its mapping.")
                    continue
                node_id, method = explicit, "profile"
            elif _current_mapping(previous, profile, anchor, nodes):
                node_id, method = previous["node_id"], previous["method"]
            else:
                if previous and previous["method"] == "explicit_binding":
                    warnings.append("Prior binding for anchor " + identifier + " is stale; its identity or evidence changed.")
                matches = [node["id"] for node in nodes.values() if node["type"] == "topic"
                           and GRAPH["_normal"](anchor.get("topic")) in GRAPH["_labels"](node)]
                if len(matches) > 1 or not GRAPH["_text"](anchor.get("topic")):
                    unresolved += 1
                    warnings.append("Ambiguous or missing topic for anchor " + identifier + "; supply an explicit binding.")
                    continue
                if matches:
                    node_id, method = matches[0], "exact"
                else:
                    node_id = "topic:anchor:" + _hash(GRAPH["_normal"](anchor["topic"]))[:24]
                    if any(record["id"] == node_id for section in ("sources", "nodes", "edges") for record in graph[section]):
                        raise ValueError("generated anchor node id collides with an existing graph record")
                    node = {"id": node_id, "type": "topic", "label": anchor["topic"].strip()}
                    graph["nodes"].append(node)
                    nodes[node_id] = node
                    method = "generated"
                    added += 1
            updated.append({"anchor_id": identifier, "anchor_fingerprint": _anchor_fingerprint(profile, anchor),
                            "node_id": node_id, "node_fingerprint": _node_fingerprint(nodes[node_id]), "method": method})
        updated.sort(key=lambda item: item["anchor_id"])
        next_sidecar = {"schema_version": 1, "mappings": updated, "fingerprint": _hash(updated)}
        _validate_mappings(next_sidecar)
        GRAPH["validate_graph"](graph)
        def unchanged():
            if any(IO["_read"](root, path) != data for path, data in snapshot.items()):
                raise ValueError("graph anchor inputs changed during save; retry synchronization")
        graph_changed = added > 0
        mapping_changed = next_sidecar != sidecar or bool(anchors) and snapshot[MAPPING_PATH] is None
        if graph_changed:
            UPDATES["_atomic"](root, "model/graph.json", graph, unchanged)
            snapshot["model/graph.json"] = IO["_read"](root, "model/graph.json")
            if IO["_json"](snapshot["model/graph.json"].decode("utf-8"), "model/graph.json") != graph:
                raise ValueError("graph changed before anchor mappings were saved; retry synchronization")
        if mapping_changed:
            UPDATES["_atomic"](root, MAPPING_PATH, next_sidecar, unchanged)
            snapshot[MAPPING_PATH] = IO["_read"](root, MAPPING_PATH)
            if IO["_json"](snapshot[MAPPING_PATH].decode("utf-8"), MAPPING_PATH) != next_sidecar:
                raise ValueError("graph anchor mappings changed during save; retry synchronization")
        unchanged()
        return {"status": "synced" if graph_changed or mapping_changed else "current",
                "counts": {"eligible_interests": len(anchors), "represented_interests": len(updated),
                           "nodes_added": added, "unresolved_interests": unresolved},
                "warnings": warnings[:10], "warnings_omitted": max(0, len(warnings) - 10)}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", required=True)
    parser.add_argument("--bindings", help="private JSON array of host-reviewed anchor_id/node_id mappings")
    args = parser.parse_args(argv)
    try:
        bindings = IO["_json"](Path(args.bindings).read_text(encoding="utf-8"), "bindings") if args.bindings else None
        print(json.dumps(sync_anchors(args.root, bindings), ensure_ascii=False, allow_nan=False, indent=2))
        return 0
    except (OSError, ValueError, TypeError, KeyError) as error:
        parser.exit(2, "trurl graph anchors: " + str(error) + "\n")


if __name__ == "__main__":
    sys.exit(main())
