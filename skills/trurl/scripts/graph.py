#!/usr/bin/env python3
"""Read-only, sourced content-graph discovery; no preference propagation.

Graph paths are retrieval explanations, not logical entailments or predictions of
enjoyment. Validation checks supplied structure and provenance, not remote truth.
"""
import argparse
import copy
from collections import deque
from datetime import date, datetime
import json
import math
from pathlib import Path
import random
import re
import runpy
import secrets
import sys
import unicodedata
from urllib.parse import urlsplit


SCHEMA_VERSION = 1
MIN_EDGE_CONFIDENCE = 0.5  # Retrieval heuristic, not a calibrated probability.
MAX_NEIGHBORS = 100
MAX_CONVERGING_ROUTES = 2
MAX_CONVERGENCE_EXPANSIONS = 64
RECENT_HISTORY_COUNT = 24
RELATIONS = {
    "about": ("work", "topic"),
    "in_genre": ("work", "topic"),
    "created_by": ("work", "creator"),
    "has_quality": ("work", "quality"),
    "broader_than": ("topic", "topic"),
    "related_to": ("topic", "topic"),
}
NODE_TYPES = {"topic", "work", "creator", "quality"}
NEGATIVE_SIGNALS = {"avoid", "disliked", "dislike", "negative", "not_for_me"}
SOURCE_ONLY_SIGNALS = {"reference_only", "illustrative", "example", "quoted", "third_party",
                       "quoted_third_party", "third_party_quote", "assistant_only",
                       "assistant_suggestion", "assistant_characterization", "assistant_generated"}
SIGNAL_FIELDS = ("status", "signal", "scope", "polarity", "valence", "source_kind", "origin", "basis")
LIMITS = [
    "Graph validation checks supplied structure and provenance, not semantic truth or remote sources.",
    "Paths support candidate discovery only; they establish neither user preference, familiarity nor causation.",
    "Edge confidence and the 0.5 traversal threshold are supplied judgments and a retrieval heuristic, not calibrated probabilities.",
    "Bounded, seeded traversal can omit connections; graph coverage and node degree are not measures of importance.",
    "Open draws are category-stratified over a finite editorial registry, not uniform over all knowledge; personal fit remains unknown.",
]


def empty_graph():
    return {"schema_version": SCHEMA_VERSION, "sources": [], "nodes": [], "edges": []}


def _text(value):
    return isinstance(value, str) and bool(value.strip())


def _normal(value):
    if not isinstance(value, str):
        return ""
    return " ".join(re.sub(r"[^\w]+", " ", unicodedata.normalize("NFKC", value).casefold()).split())


def _dated(value, unknown=True):
    if unknown and (value is None or value == "unknown"):
        return True
    if not _text(value):
        return False
    try:
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
            date.fromisoformat(value)
        else:
            if not re.match(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}", value):
                return False
            datetime.fromisoformat(value[:-1] + "+00:00" if value.endswith("Z") else value)
        return True
    except ValueError:
        return False


def _confidence(value):
    return (not isinstance(value, bool) and isinstance(value, (int, float))
            and math.isfinite(value) and 0 <= value <= 1)


def _web_url(value):
    if not _text(value) or re.search(r"\s", value):
        return False
    try:
        parsed = urlsplit(value)
        return (parsed.scheme.lower() in {"http", "https"} and bool(parsed.hostname)
                and parsed.username is None and parsed.password is None
                and (parsed.port is None or 0 < parsed.port <= 65535))
    except ValueError:
        return False


def validate_graph(graph):
    """Return counts or raise ValueError; no network or state mutation."""
    if not isinstance(graph, dict) or type(graph.get("schema_version")) is not int or graph["schema_version"] != SCHEMA_VERSION:
        raise ValueError("graph requires schema_version 1")
    identifiers = set()
    for section in ("sources", "nodes", "edges"):
        if not isinstance(graph.get(section), list):
            raise ValueError("graph requires a %s array" % section)
        for record in graph[section]:
            if not isinstance(record, dict) or not _text(record.get("id")):
                raise ValueError("each %s record needs an id" % section)
            if record["id"] in identifiers:
                raise ValueError("duplicate graph id: " + record["id"])
            identifiers.add(record["id"])
    sources = {s["id"]: s for s in graph["sources"]}
    for source in sources.values():
        if (not _text(source.get("kind")) or not _text(source.get("locator"))
                or "checked_at" not in source or not _dated(source["checked_at"])):
            raise ValueError("source requires kind, locator and ISO checked_at or unknown: " + source["id"])
    nodes = {n["id"]: n for n in graph["nodes"]}
    for node in nodes.values():
        if not isinstance(node.get("type"), str) or node["type"] not in NODE_TYPES or not _text(node.get("label")):
            raise ValueError("node requires a supported type and label: " + node["id"])
        aliases = node.get("aliases", [])
        if not isinstance(aliases, list) or any(not _text(a) for a in aliases):
            raise ValueError("node aliases must be nonempty strings: " + node["id"])
        if "canonical_url" in node and not _web_url(node["canonical_url"]):
            raise ValueError("node canonical_url must be a valid HTTP(S) URL: " + node["id"])
    for edge in graph["edges"]:
        source_id, target_id = edge.get("source"), edge.get("target")
        if not _text(source_id) or not _text(target_id) or source_id not in nodes or target_id not in nodes:
            raise ValueError("edge has a dangling endpoint: " + edge["id"])
        relation = edge.get("relation")
        if not isinstance(relation, str) or relation not in RELATIONS:
            raise ValueError("unsupported content relation: " + str(relation))
        if (nodes[source_id]["type"], nodes[target_id]["type"]) != RELATIONS[relation]:
            raise ValueError("unsupported relation endpoint types: " + edge["id"])
        if not isinstance(edge.get("status"), str) or edge["status"] not in {"verified", "hypothesis", "retracted"} or not _confidence(edge.get("confidence")):
            raise ValueError("edge requires supported status and finite confidence in [0,1]: " + edge["id"])
        provenance = edge.get("source_provenance")
        if (not isinstance(provenance, list) or any(not _text(p) or p not in sources for p in provenance)
                or len(provenance) != len(set(provenance))):
            raise ValueError("edge source_provenance must reference unique graph sources: " + edge["id"])
        if edge["status"] == "verified" and (not provenance or any(not _dated(sources[p]["checked_at"], unknown=False) for p in provenance)):
            raise ValueError("verified edge requires dated source provenance: " + edge["id"])
        if not _text(edge.get("assertion_method")):
            raise ValueError("edge requires assertion_method: " + edge["id"])
        if any(not _dated(edge[k]) for k in ("created_at", "checked_at") if k in edge):
            raise ValueError("edge timestamps must be ISO dates/times or unknown: " + edge["id"])
    return {"schema_version": SCHEMA_VERSION, "valid": True,
            "counts": {section: len(graph[section]) for section in ("sources", "nodes", "edges")}}


def _positive_integer(value, name, maximum=None):
    if isinstance(value, bool) or not isinstance(value, int) or value < 1 or (maximum is not None and value > maximum):
        message = " must be an integer between 1 and " + str(maximum) if maximum else " must be a positive integer"
        raise ValueError(name + message)


def _has_evidence(value):
    if _text(value):
        return True
    if isinstance(value, list):
        return any(_has_evidence(item) for item in value)
    if isinstance(value, dict):
        return any(_text(value.get(key)) for key in ("id", "locator", "quote", "text", "thread_id", "message_id"))
    return False


def _signals(record, fields=SIGNAL_FIELDS):
    return {record[key].strip().casefold().replace("-", "_").replace(" ", "_")
            for key in fields if isinstance(record.get(key), str)}


def _personal_record(interest, allow_negative=False):
    """Only personal evidence can influence anchors or the open-field pool.

    A genuine avoidance can restrict an open draw without becoming a positive
    graph anchor. Quoted/reference material and assistant suggestions do neither.
    """
    if not isinstance(interest, dict) or not isinstance(interest.get("kind"), str) or interest["kind"] not in {"explicit", "inferred", "tentative"}:
        return False
    signals = _signals(interest)
    if signals & (SOURCE_ONLY_SIGNALS | {"rejected", "retracted"}):
        return False
    if any(interest.get(key) is True for key in SOURCE_ONLY_SIGNALS | {"rejected", "retracted"}):
        return False
    provenance = interest.get("source_provenance")
    if (isinstance(provenance, list) and provenance
            and all(isinstance(source, dict) and _signals(source, SIGNAL_FIELDS + ("kind",)) & SOURCE_ONLY_SIGNALS
                    for source in provenance)):
        return False
    negative = bool(signals & NEGATIVE_SIGNALS)
    if negative and not allow_negative:
        return False
    if "signal" in interest and interest["signal"] not in (
            "interested", "enjoyed", "like", "liked", "positive", "curious", "want_more"):
        if not (allow_negative and _signals(interest, ("signal",)) & NEGATIVE_SIGNALS):
            return False
    if "confidence" in interest and (not _confidence(interest["confidence"]) or interest["confidence"] <= 0):
        return False
    if interest["kind"] != "explicit" and not (_has_evidence(provenance) or _has_evidence(interest.get("evidence"))):
        return False
    return _text(interest.get("topic")) or _text(interest.get("graph_node_id"))


def _anchors(profile):
    interests = profile.get("interests", [])
    if not isinstance(interests, list):
        raise ValueError("profile interests must be an array")
    result = []
    for index, interest in enumerate(interests):
        if isinstance(interest, dict) and "hypothesis_id" in interest:
            helper = runpy.run_path(str(Path(__file__).resolve().with_name("hypotheses.py")))
            if not helper["managed_interest_valid"](profile, interest):
                continue
        if not _personal_record(interest):
            continue
        anchor = copy.deepcopy(interest)
        anchor.setdefault("id", "interest-%d" % (index + 1))
        anchor.setdefault("knowledge_level", "unknown")
        anchor.setdefault("knowledge_evidence", [])
        result.append(anchor)
    return result


def personal_anchors(profile):
    """Return independent copies of eligible positive personal observations."""
    if not isinstance(profile, dict):
        raise ValueError("profile must be an object")
    return _anchors(profile)


def _labels(record, key="label"):
    aliases = record.get("aliases", [])
    return {_normal(v) for v in [record.get(key)] + (aliases if isinstance(aliases, list) else []) if _normal(v)}


def _routes(anchor, node_id, nodes, adjacency, rng, max_hops, max_neighbors, anchor_nodes, truncated):
    """Seeded breadth-first retrieval, one shortest route per destination/anchor."""
    pending = deque([(node_id, [node_id], [], [])])
    visited = {node_id}
    while pending:
        current, node_ids, edge_ids, steps = pending.popleft()
        if len(edge_ids) == max_hops:
            continue
        neighbors = list(adjacency.get(current, []))
        rng.shuffle(neighbors)
        if len(neighbors) > max_neighbors:
            truncated.add(current)
        for edge, destination in neighbors[:max_neighbors]:
            if destination in visited:
                continue
            visited.add(destination)
            next_nodes, next_edges = node_ids + [destination], edge_ids + [edge["id"]]
            next_steps = steps + [{"edge_id": edge["id"], "relation": edge["relation"],
                                   "source": edge["source"], "target": edge["target"],
                                   "traversed_reverse": current != edge["source"]}]
            pending.append((destination, next_nodes, next_edges, next_steps))
            if destination not in anchor_nodes:
                yield {"anchor_id": anchor["id"], "anchor_evidence": copy.deepcopy(anchor),
                       "destination": copy.deepcopy(nodes[destination]), "node_ids": next_nodes,
                       "edge_ids": next_edges, "steps": next_steps, "hops": len(next_edges)}


def _converging_routes(connected, anchors, adjacency, edges, seed, max_hops, max_neighbors):
    """Attach compact alternate paths without changing primary retrieval.

    Search backwards from the selected destinations so a count-one frontier can
    still reveal a second anchor. The separate RNG, expansion budget and output
    cap keep this optional context bounded and leave primary/open draws intact.
    """
    by_node = {}
    for anchor, node_id in sorted(anchors, key=lambda item: (item[1], str(item[0]["id"]))):
        by_node.setdefault(node_id, anchor["id"])
    if len(by_node) < 2 or not connected:
        return None
    rng = random.Random(str(seed) + ":convergence")
    expansions, added, truncated = 0, 0, False
    for primary in connected:
        if added == MAX_CONVERGING_ROUTES or expansions == MAX_CONVERGENCE_EXPANSIONS:
            truncated = True
            break
        origin = primary["node_ids"][0]
        destination = primary["destination"]["id"]
        pending = deque([(destination, [destination], [])])
        visited = {destination}
        alternate = None
        while pending and alternate is None:
            current, node_ids, edge_ids = pending.popleft()
            if len(edge_ids) == max_hops:
                continue
            if expansions == MAX_CONVERGENCE_EXPANSIONS:
                truncated = True
                break
            expansions += 1
            neighbors = adjacency.get(current, [])
            if len(neighbors) > max_neighbors:
                truncated = True
                neighbors = rng.sample(neighbors, max_neighbors)
            else:
                neighbors = list(neighbors)
                rng.shuffle(neighbors)
            for edge, neighbor in neighbors:
                if neighbor in visited:
                    continue
                visited.add(neighbor)
                # Returning through the original anchor is not a second bridge.
                if neighbor == origin:
                    continue
                next_nodes = [neighbor] + node_ids
                next_edges = [edge["id"]] + edge_ids
                anchor_id = by_node.get(neighbor)
                if anchor_id is not None and anchor_id != primary["anchor_id"]:
                    alternate = {
                        "anchor_id": anchor_id, "node_ids": next_nodes, "edge_ids": next_edges,
                        "traversed_reverse": [edges[identifier]["source"] != next_nodes[n]
                                              for n, identifier in enumerate(next_edges)],
                        "evidence_confidence_min": min(edges[identifier]["confidence"] for identifier in next_edges),
                    }
                    break
                pending.append((neighbor, next_nodes, next_edges))
        if alternate is not None:
            primary["converging_route"] = alternate
            added += 1
    if not added and not truncated:
        return None
    return {"max_additional_routes": MAX_CONVERGING_ROUTES,
            "max_node_expansions": MAX_CONVERGENCE_EXPANSIONS,
            "node_expansions": expansions, "truncated": truncated}


def _open_draw(registry, profile, history, connected, nodes, rng, count):
    if registry is None:
        registry = json.loads((Path(__file__).resolve().parents[1] / "references" / "domains.json").read_text(encoding="utf-8"))
    if not isinstance(registry, dict) or not isinstance(registry.get("domains"), list) or not registry["domains"]:
        raise ValueError("registry requires a nonempty domains array")
    excluded = set()
    for interest in profile.get("interests", []):
        if _personal_record(interest, allow_negative=True):
            excluded.update(_labels(interest, "topic"))
            if _text(interest.get("graph_node_id")) and interest["graph_node_id"] in nodes:
                excluded.update(_labels(nodes[interest["graph_node_id"]]))
            elif _text(interest.get("topic")):
                for candidate in nodes.values():
                    if candidate["type"] == "topic" and _normal(interest["topic"]) in _labels(candidate):
                        excluded.update(_labels(candidate))
    for route in connected:
        excluded.update(_labels(route["destination"]))
    for item in history[-RECENT_HISTORY_COUNT:]:
        if isinstance(item, dict):
            topics = item.get("topics", [])
            if isinstance(topics, list):
                excluded.update(_normal(t) for t in topics if isinstance(t, str))
    strata, seen = {}, set()
    for entry in registry["domains"]:
        if not isinstance(entry, dict) or not _text(entry.get("field")) or not _text(entry.get("category")):
            raise ValueError("registry domains require field and category")
        key = _normal(entry["field"])
        if key in seen:
            raise ValueError("registry fields must be unique")
        seen.add(key)
        if key not in excluded and not (_labels(entry, "field") & excluded):
            strata.setdefault(entry["category"].strip(), []).append(entry["field"].strip())
    strata = {category: sorted(fields) for category, fields in sorted(strata.items())}
    available = copy.deepcopy(strata)
    for fields in available.values():
        rng.shuffle(fields)
    draws = []
    while available and len(draws) < count:
        categories = sorted(available)
        rng.shuffle(categories)
        for category in categories:
            field = available[category].pop()
            draws.append({"id": "open-%02d" % (len(draws) + 1), "field": field, "category": category,
                          "selection_channel": "open", "personal_fit_status": "unknown",
                          "reason": "Independent category-stratified editorial-registry probe; verify concrete value without inventing a personal connection."})
            if not available[category]:
                del available[category]
            if len(draws) == count:
                break
    return draws, strata, registry.get("version", "unversioned")


def frontier(graph, profile, history=None, seed=None, count=5, max_hops=2,
             max_neighbors=12, allow_open=False, open_count=0, registry=None, feedback=None,
             anchor_mappings=None):
    """Discover bounded sourced connections and explicitly authorized open probes."""
    validate_graph(graph)
    if not isinstance(profile, dict) or (history is not None and not isinstance(history, list)):
        raise ValueError("profile must be an object and history an array")
    if profile.get("taste_hypotheses"):
        helper = runpy.run_path(str(Path(__file__).resolve().with_name("hypotheses.py")))
        profile = helper["validated_profile"](profile, feedback, history)
    _positive_integer(count, "count")
    _positive_integer(max_hops, "max_hops", 3)
    _positive_integer(max_neighbors, "max_neighbors", MAX_NEIGHBORS)
    if not isinstance(allow_open, bool) or isinstance(open_count, bool) or not isinstance(open_count, int) or open_count < 0:
        raise ValueError("allow_open must be boolean and open_count a nonnegative integer")
    if open_count and not allow_open:
        raise ValueError("open_count requires allow_open=True")
    if open_count > max(1, count // 4):
        raise ValueError("open_count exceeds the one-in-four allowance")
    if seed is not None and (isinstance(seed, bool) or not isinstance(seed, int)):
        raise ValueError("seed must be an integer")
    actual_seed = secrets.randbits(64) if seed is None else seed
    rng = random.Random(actual_seed)
    nodes = {n["id"]: n for n in graph["nodes"]}
    edges = {e["id"]: e for e in graph["edges"]}
    adjacency = {}
    for edge in sorted(graph["edges"], key=lambda e: e["id"]):
        if edge["status"] != "verified" or edge["confidence"] < MIN_EDGE_CONFIDENCE:
            continue
        adjacency.setdefault(edge["source"], []).append((edge, edge["target"]))
        adjacency.setdefault(edge["target"], []).append((edge, edge["source"]))
    anchors, unmatched, warnings = [], [], []
    mapped = None
    if anchor_mappings is not None:
        helper = runpy.run_path(str(Path(__file__).resolve().with_name("graph_anchors.py")))
        mapped = helper["match_anchors"](graph, profile, anchor_mappings, persistent_only=False)
        warnings.extend(mapped["warnings"])
    for anchor in _anchors(profile):
        if mapped is not None:
            matches = [mapped["matches"][anchor["id"]]] if anchor["id"] in mapped["matches"] else []
        elif _text(anchor.get("graph_node_id")):
            matches = [anchor["graph_node_id"]] if anchor["graph_node_id"] in nodes else []
        else:
            matches = sorted(n["id"] for n in nodes.values() if n["type"] == "topic" and _normal(anchor.get("topic")) in _labels(n))
        if len(matches) == 1:
            anchors.append((anchor, matches[0]))
        else:
            unmatched.append(anchor["id"])
            if len(matches) > 1:
                warnings.append("Ambiguous exact graph-label match for anchor " + str(anchor["id"]) + "; supply graph_node_id.")
    anchor_nodes = {node_id for _, node_id in anchors}
    rng.shuffle(anchors)
    truncated = set()
    active = deque(_routes(anchor, node_id, nodes, adjacency, rng, max_hops, max_neighbors, anchor_nodes, truncated)
                   for anchor, node_id in anchors)
    connected, destinations = [], set()
    while active and len(connected) < count - open_count:
        routes = active.popleft()
        for route in routes:
            destination = route["destination"]["id"]
            if destination in destinations:
                continue
            destinations.add(destination)
            route["id"] = "connected-%02d" % (len(connected) + 1)
            route["evidence_confidence_min"] = min(edges[e]["confidence"] for e in route["edge_ids"])
            connected.append(route)
            active.append(routes)
            break
    convergence = _converging_routes(connected, anchors, adjacency, edges, actual_seed, max_hops, max_neighbors)
    opened, strata, registry_version = [], {}, None
    if open_count:
        # Open category draws do not depend on how many random graph branches
        # were considered. Exact graph destinations still inform exclusions.
        open_rng = random.Random(str(actual_seed) + ":open")
        opened, strata, registry_version = _open_draw(registry, profile, history or [], connected, nodes, open_rng, open_count)
        if len(opened) < open_count:
            warnings.append("Eligible editorial registry cannot fill the requested open probes; no excluded field was reintroduced.")
    if len(connected) < count - open_count:
        warnings.append("Insufficient eligible graph connections; no unrelated fallback or preference inference was used.")
    if truncated:
        warnings.append("Neighbor bound truncated exploration at: " + ", ".join(sorted(truncated)))
    result = {"schema_version": SCHEMA_VERSION, "seed": actual_seed, "connected": connected, "open": opened,
            "unmatched_anchor_ids": unmatched, "eligible_pool": sorted(f for fields in strata.values() for f in fields),
            "eligible_strata": strata, "registry_version": registry_version,
            "open_sampling": "category_then_field_without_replacement" if open_count else None,
            "recent_history_count": RECENT_HISTORY_COUNT, "warnings": warnings, "limits": list(LIMITS),
            "profile_changed": False, "graph_changed": False}
    if convergence is not None:
        result["convergence_search"] = convergence
        result["limits"].append("Converging routes are bounded editorial clues, not independent preference evidence or a relevance bonus; routes can share hubs and sources.")
    return result


def _read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _read_history(path):
    raw = Path(path).read_text(encoding="utf-8")
    return json.loads(raw) if raw.lstrip().startswith("[") else [json.loads(line) for line in raw.splitlines() if line.strip()]


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    check = commands.add_parser("graph-check", help="Validate a supplied content graph without writing it")
    check.add_argument("--graph", required=True)
    discover = commands.add_parser("frontier", help="Discover sourced paths and explicitly opted-in open probes")
    discover.add_argument("--graph", required=True)
    discover.add_argument("--profile", required=True)
    discover.add_argument("--history")
    discover.add_argument("--feedback", help="feedback JSONL; defaults to the profile's sibling ledger")
    discover.add_argument("--seed", type=int)
    discover.add_argument("--count", type=int, default=5)
    discover.add_argument("--max-hops", type=int, default=2)
    discover.add_argument("--max-neighbors", type=int, default=12)
    discover.add_argument("--allow-open", action="store_true")
    discover.add_argument("--open-count", type=int, default=0)
    arguments = parser.parse_args(argv)
    try:
        graph = _read_json(arguments.graph)
        if arguments.command == "graph-check":
            result = validate_graph(graph)
        else:
            profile = _read_json(arguments.profile)
            profile_path = Path(arguments.profile).expanduser()
            feedback_path = Path(arguments.feedback).expanduser() if arguments.feedback else profile_path.with_name("feedback.jsonl")
            history_path = Path(arguments.history).expanduser() if arguments.history else profile_path.with_name("recommendations.jsonl")
            history = _read_history(history_path) if arguments.history else None
            if profile.get("taste_hypotheses") and history is None:
                history = _read_history(history_path) if history_path.exists() else []
            feedback = _read_history(feedback_path) if arguments.feedback else []
            if profile.get("taste_hypotheses") and not arguments.feedback and feedback_path.exists():
                feedback = _read_history(feedback_path)
            result = frontier(graph, profile, history=history,
                              seed=arguments.seed, count=arguments.count, max_hops=arguments.max_hops,
                              max_neighbors=arguments.max_neighbors, allow_open=arguments.allow_open,
                              open_count=arguments.open_count,
                              feedback=feedback)
        print(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False))
        return 0
    except (OSError, ValueError) as error:
        print("error: " + str(error), file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
