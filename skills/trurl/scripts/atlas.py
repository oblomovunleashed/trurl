#!/usr/bin/env python3
"""Export a private, offline atlas of recorded taste evidence and activity."""

import argparse
from collections import Counter, defaultdict, deque
from datetime import date, datetime
import json
import os
from pathlib import Path
import re
import runpy
from tempfile import NamedTemporaryFile
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit


SKILL = Path(__file__).resolve().parents[1]
DATA_TOKEN = "__TRURL_ATLAS_DATA__"
ATLAS_MAX_WORKS = 120
ATLAS_MAX_ROUTES = 4
ATLAS_MAX_NEIGHBORS = 24
ATLAS_MAX_HOPS = 2


def _date(value):
    if not isinstance(value, str) or len(value) < 10:
        return None
    try:
        if len(value) == 10:
            parsed = date.fromisoformat(value)
        else:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00")).date()
        return parsed.isoformat()
    except ValueError:
        return None


def _records(path):
    try:
        with path.open(encoding="utf-8") as file:
            for line_number, line in enumerate(file, 1):
                if not line.strip():
                    continue
                try:
                    record = json.loads(line)
                    if not isinstance(record, dict):
                        raise ValueError("expected an object")
                except ValueError:
                    raise ValueError(f"Invalid record in {path.name} at line {line_number}") from None
                yield record
    except FileNotFoundError:
        return


def _interest_dates(entry, sources):
    values = [entry.get("recorded_at"), entry.get("created_at")]
    references = entry.get("source_provenance") or []
    if isinstance(references, list):
        for reference in references:
            source = sources.get(reference) if isinstance(reference, str) else reference
            if isinstance(source, dict):
                values.append(source.get("captured_at"))
    return min(filter(None, map(_date, values)), default=None)


def _interests(profile):
    provenance = profile.get("provenance")
    sources = {
        source["id"]: source for source in (provenance if isinstance(provenance, list) else [])
        if isinstance(source, dict) and isinstance(source.get("id"), str)
    }
    anchors = runpy.run_path(str(SKILL / "scripts" / "graph.py"))["personal_anchors"](profile)
    by_topic = {}
    for entry in anchors:
        topic = entry.get("topic")
        if not isinstance(topic, str) or not topic.strip() or entry.get("scope") == "current_request":
            continue
        topic = " ".join(topic.split())
        kind = "stated" if entry["kind"] == "explicit" else "tentative"
        recorded = _interest_dates(entry, sources)
        key = topic.casefold()
        prior = by_topic.get(key)
        if prior is None or (kind == "stated" and prior["kind"] != "stated"):
            by_topic[key] = {"topic": topic, "kind": kind, "recorded": recorded}
        elif prior["kind"] == kind and recorded and (prior["recorded"] is None or recorded < prior["recorded"]):
            prior["recorded"] = recorded
    return list(by_topic.values())


def _possibilities(profile, helper):
    anchors = {interest.get("id"): interest for interest in profile.get("interests", [])}
    result = []
    for hypothesis in helper["active_hypotheses"](profile):
        origins = [anchors[identifier] for identifier in hypothesis["anchor_ids"]]
        if any(origin.get("scope") == "current_request" for origin in origins):
            continue
        result.append({
            "topic": hypothesis["topic"], "kind": "possibility",
            "recorded": _date(hypothesis.get("created_at")),
            "anchors": [origin["topic"] for origin in origins],
            "reason": hypothesis["reason"],
        })
    return result


def _activity(records, date_key):
    months = Counter()
    undated = 0
    for event in records:
        recorded = _date(event.get(date_key))
        if recorded is None:
            undated += 1
        else:
            months[recorded[:7]] += 1
    return months, undated


def _short_text(value, limit=1200):
    if not isinstance(value, str):
        return ""
    value = value.strip()
    return value if len(value) <= limit else value[:limit].rstrip() + "…"


def _work_url(value, graph_helper, canonical_url):
    """Match work identity without treating titles or arbitrary URL aliases as proof."""
    if not graph_helper["_web_url"](value):
        return None
    parsed = urlsplit(value)
    host = parsed.hostname.lower()
    if host.startswith("www."):
        host = host[4:]
    port = parsed.port
    default_port = port is None or (parsed.scheme.lower(), port) in {("http", 80), ("https", 443)}
    query_pairs = parse_qsl(parsed.query, keep_blank_values=True)
    if host in {"youtube.com", "m.youtube.com", "youtu.be"} and default_port:
        # Share discovery's aliases only for exact video paths. Search/channel
        # pages keep ordinary URL identity; conflicting video IDs prove nothing.
        parts = parsed.path.split("/")
        watch = host != "youtu.be" and parsed.path == "/watch"
        path_video = None
        if host == "youtu.be" and len(parts) == 2:
            path_video = parts[1]
        elif host != "youtu.be" and len(parts) == 3 and parts[1] in {"shorts", "embed", "live"}:
            path_video = parts[2]
        if watch or path_video:
            videos = [val for key, val in query_pairs if key == "v"]
            if len(videos) > 1:
                return None
            video_id = (videos[0] if videos else None) if watch else path_video
            if videos and videos[0] != video_id:
                return None
            if video_id and re.fullmatch(r"[A-Za-z0-9_-]+", video_id):
                return canonical_url(value)
    if ":" in host:
        host = "[" + host + "]"
    if not default_port:
        host += ":" + str(port)
    query = [(key, val) for key, val in query_pairs
             if not key.lower().startswith("utm_") and key.lower() not in {"fbclid", "gclid"}]
    return urlunsplit((parsed.scheme.lower(), host, parsed.path.rstrip("/") or "/",
                       urlencode(sorted(query)), ""))


def _connections(model, profile, recommendations, hypothesis_helper=None):
    """An offline, bounded current graph view; never reconstruct past discovery."""
    result = {
        "status": "missing", "notice": "No content graph yet. Verified recommendation research will add connections here.",
        "counts": {"nodes": 0, "edges": 0, "sources": 0, "works": 0,
                   "matched_interests": 0, "unmatched_interests": 0,
                   "represented_interests": 0, "sourced_interests": 0,
                   "recorded_interests": 0, "represented_without_routes": 0},
        "anchors": [], "nodes": [], "edges": [], "sources": [], "works": [],
        "limits": {"max_hops": ATLAS_MAX_HOPS, "max_routes_per_work": ATLAS_MAX_ROUTES,
                   "max_works": ATLAS_MAX_WORKS, "max_neighbors": ATLAS_MAX_NEIGHBORS,
                   "truncated": False, "omitted_works": 0, "omitted_relationships": 0,
                   "route_search_truncated": False},
    }
    try:
        graph = json.loads((model / "graph.json").read_text(encoding="utf-8"))
    except FileNotFoundError:
        return result
    except (OSError, ValueError):
        result.update(status="invalid", notice="The saved content graph could not be read. Its connections are hidden until it is repaired.")
        return result
    helper = runpy.run_path(str(SKILL / "scripts" / "graph.py"))
    try:
        result["graph_counts"] = helper["validate_graph"](graph)["counts"]
    except (ValueError, TypeError):
        result.update(status="invalid", notice="The saved content graph is invalid. Its connections are hidden until it is repaired.")
        return result
    nodes = {node["id"]: node for node in graph["nodes"]}
    edges = {edge["id"]: edge for edge in graph["edges"]
             if edge["status"] == "verified" and edge["confidence"] >= helper["MIN_EDGE_CONFIDENCE"]}
    sources = {source["id"]: source for source in graph["sources"]}
    adjacency = defaultdict(list)
    for edge in sorted(edges.values(), key=lambda item: item["id"]):
        adjacency[edge["source"]].append((edge["id"], edge["target"]))
        adjacency[edge["target"]].append((edge["id"], edge["source"]))

    anchor_helper = runpy.run_path(str(SKILL / "scripts" / "graph_anchors.py"))
    try:
        mappings = anchor_helper["read_mappings"](model.parent)
    except (OSError, ValueError):
        mappings = None
        result["mapping_notice"] = "Saved interest mappings could not be read. Only current explicit or exact matches are shown."
    matched = anchor_helper["match_anchors"](graph, profile, mappings=mappings)
    if matched.get("warnings"):
        result["mapping_notice"] = "Some interest mappings need review. Uncertain mappings are excluded."
    anchors, anchors_by_node = {}, defaultdict(list)
    for interest in helper["personal_anchors"](profile):
        identifier = interest.get("id")
        if not isinstance(identifier, str) or not identifier or interest.get("scope") == "current_request":
            continue
        mapped = matched["matches"].get(identifier)
        label = interest.get("topic") or (nodes[mapped]["label"] if mapped else "")
        if not isinstance(label, str) or not label.strip():
            continue
        anchor = {"id": identifier, "label": _short_text(label, 240),
                  "kind": "stated" if interest["kind"] == "explicit" else "tentative"}
        if mapped:
            anchor["node_id"] = mapped
            anchors_by_node[mapped].append(identifier)
        anchor.update(sourced_work_ids=[], recorded_work_ids=[], mapped_work_ids=[])
        anchors[identifier] = anchor

    # Only canonical identities connect delivered events to graph works. A title
    # shared by several works, or an ambiguous graph URL, cannot establish a match.
    canonical_url = runpy.run_path(str(SKILL / "scripts" / "diversity.py"))["canonical_url"]
    by_url = defaultdict(list)
    for node in nodes.values():
        if node["type"] == "work":
            canonical = _work_url(node.get("canonical_url"), helper, canonical_url)
            if canonical:
                by_url[canonical].append(node["id"])
    records_by_work = defaultdict(list)
    for record in recommendations:
        canonical = _work_url(record.get("canonical_url"), helper, canonical_url)
        matches = by_url.get(canonical, [])
        if len(matches) == 1:
            records_by_work[matches[0]].append(record)

    active_hypotheses = {}
    if hypothesis_helper:
        active_hypotheses = {item["id"]: item for item in hypothesis_helper["active_hypotheses"](profile)}

    def editorial_links(records):
        links, seen = [], set()
        for record in reversed(records):
            hypothesis_id = record.get("hypothesis_id")
            if hypothesis_id is not None:
                hypothesis = active_hypotheses.get(hypothesis_id) if isinstance(hypothesis_id, str) else None
                if not hypothesis or any(key not in anchors for key in hypothesis["anchor_ids"]):
                    continue
                key = ("hypothesis", hypothesis_id)
                link = {"kind": "hypothesis", "hypothesis_id": hypothesis_id,
                        "anchor_ids": list(hypothesis["anchor_ids"]), "label": _short_text(hypothesis["topic"], 240),
                        "reason": _short_text(hypothesis["reason"])}
            else:
                connection = record.get("personal_connection")
                if not isinstance(connection, dict) or connection.get("basis") not in {"explicit_interest", "tentative_interest"}:
                    continue
                primary = connection.get("anchor")
                if not isinstance(primary, str) or primary not in anchors:
                    continue
                identifiers = record.get("anchor_ids")
                identifiers = identifiers if isinstance(identifiers, list) else []
                identifiers = list(dict.fromkeys([primary] + [key for key in identifiers if isinstance(key, str) and key in anchors]))
                reason = _short_text(connection.get("explanation"))
                if not reason:
                    continue
                key = ("recommendation", tuple(identifiers), reason)
                link = {"kind": "recommendation", "anchor_ids": identifiers,
                        "label": "Recorded recommendation connection", "reason": reason}
            if key not in seen:
                seen.add(key)
                links.append(link)
            if len(links) == ATLAS_MAX_ROUTES:
                break
        return links

    def current_routes(work_id):
        queue = deque([(work_id, [work_id], [])])
        seen = {work_id}
        found = {}
        trimmed = False
        while queue:
            node_id, path_nodes, path_edges = queue.popleft()
            for anchor_id in sorted(anchors_by_node[node_id]):
                found.setdefault(anchor_id, {"anchor_id": anchor_id, "node_ids": list(reversed(path_nodes)),
                                             "edge_ids": list(reversed(path_edges))})
            if len(path_edges) >= ATLAS_MAX_HOPS:
                continue
            neighbors = adjacency[node_id]
            trimmed = trimmed or len(neighbors) > ATLAS_MAX_NEIGHBORS
            for edge_id, neighbor in neighbors[:ATLAS_MAX_NEIGHBORS]:
                if neighbor not in seen:
                    seen.add(neighbor)
                    queue.append((neighbor, path_nodes + [neighbor], path_edges + [edge_id]))
        routes = sorted(found.values(), key=lambda item: (len(item["edge_ids"]), anchors[item["anchor_id"]]["label"].casefold(), item["anchor_id"]))
        return routes[:ATLAS_MAX_ROUTES], trimmed or len(routes) > ATLAS_MAX_ROUTES, routes

    works = []
    for node in nodes.values():
        if node["type"] != "work":
            continue
        records = records_by_work[node["id"]]
        dates = [record.get("recommended_at") for record in records if _date(record.get("recommended_at"))]
        work = {"id": node["id"], "label": _short_text(node["label"], 240),
                "recommended": bool(records), "recommended_at": max(dates, default=None)}
        if helper["_web_url"](node.get("canonical_url")):
            work["canonical_url"] = node["canonical_url"]
        works.append(work)
    works.sort(key=lambda item: (item["label"].casefold(), item["id"]))
    works.sort(key=lambda item: item["recommended_at"] or "", reverse=True)
    works.sort(key=lambda item: item["recommended"], reverse=True)
    result["limits"]["omitted_works"] = max(0, len(works) - ATLAS_MAX_WORKS)
    works = works[:ATLAS_MAX_WORKS]
    included_nodes, included_edges = set(), set()
    for work in works:
        work_id = work["id"]
        included_nodes.add(work_id)
        work["routes"], work["routes_truncated"], coverage_routes = current_routes(work_id)
        work["connected_anchor_ids"] = [route["anchor_id"] for route in coverage_routes]
        for route in coverage_routes:
            anchor = anchors[route["anchor_id"]]
            anchor["sourced_work_ids" if route["edge_ids"] else "mapped_work_ids"].append(work_id)
            if route["edge_ids"] and "sample_route" not in anchor:
                anchor["sample_route"] = {"work_id": work_id, **route}
                included_nodes.update(route["node_ids"])
                included_edges.update(route["edge_ids"])
        result["limits"]["route_search_truncated"] |= work["routes_truncated"]
        direct = adjacency[work_id]
        result["limits"]["omitted_relationships"] += max(0, len(direct) - ATLAS_MAX_NEIGHBORS)
        work["edge_ids"] = [edge_id for edge_id, _ in direct[:ATLAS_MAX_NEIGHBORS]]
        included_edges.update(work["edge_ids"])
        creators = sorted({nodes[edges[edge_id]["target"]]["label"] for edge_id in work["edge_ids"]
                           if edges[edge_id]["relation"] == "created_by" and edges[edge_id]["source"] == work_id})
        if creators:
            work["creator"] = "; ".join(creators)
        for route in work["routes"]:
            included_nodes.update(route["node_ids"])
            included_edges.update(route["edge_ids"])
        work["editorial_links"] = editorial_links(records_by_work[work_id])
        for link in work["editorial_links"]:
            for anchor_id in link["anchor_ids"]:
                if work_id not in anchors[anchor_id]["recorded_work_ids"]:
                    anchors[anchor_id]["recorded_work_ids"].append(work_id)
    for identifier in included_edges:
        included_nodes.update((edges[identifier]["source"], edges[identifier]["target"]))
    included_nodes.update(anchor["node_id"] for anchor in anchors.values() if "node_id" in anchor)
    for identifier in sorted(included_nodes):
        node = nodes[identifier]
        exported = {"id": identifier, "type": node["type"], "label": _short_text(node["label"], 240)}
        if helper["_web_url"](node.get("canonical_url")):
            exported["canonical_url"] = node["canonical_url"]
        result["nodes"].append(exported)
    included_sources = set()
    for identifier in sorted(included_edges):
        edge = edges[identifier]
        result["edges"].append({key: edge[key] for key in ("id", "source", "target", "relation", "source_provenance")})
        result["edges"][-1]["support_note"] = _short_text(edge.get("support_note"))
        included_sources.update(edge["source_provenance"])
    for identifier in sorted(included_sources):
        source = sources[identifier]
        exported = {"id": identifier, "title": _short_text(source.get("title"), 240) or "Recorded source",
                    "checked_at": source["checked_at"]}
        if helper["_web_url"](source.get("locator")):
            exported["locator"] = source["locator"]
        result["sources"].append(exported)
    result["anchors"] = sorted(anchors.values(), key=lambda item: (item["label"].casefold(), item["id"]))
    result["works"] = works
    result["counts"] = {"nodes": len(result["nodes"]), "edges": len(result["edges"]),
                        "sources": len(result["sources"]), "works": len(works),
                        "matched_interests": sum("node_id" in anchor for anchor in anchors.values()),
                        "unmatched_interests": sum("node_id" not in anchor for anchor in anchors.values()),
                        "represented_interests": sum("node_id" in anchor for anchor in anchors.values()),
                        "sourced_interests": sum(bool(anchor["sourced_work_ids"]) for anchor in anchors.values()),
                        "recorded_interests": sum(bool(anchor["recorded_work_ids"]) for anchor in anchors.values()),
                        "represented_without_routes": sum("node_id" in anchor and not anchor["sourced_work_ids"]
                                                           for anchor in anchors.values())}
    result["limits"]["truncated"] = bool(result["limits"]["omitted_works"] or result["limits"]["omitted_relationships"] or result["limits"]["route_search_truncated"])
    result.update(status="available" if works else "empty",
                  notice="Sourced paths show the graph as it stands now. Recorded recommendation connections are separate interpretations, not proof of taste or a reconstruction of the original discovery." if works else "No researched works are stored in the content graph yet.")
    return result


def atlas_data(model):
    try:
        profile = json.loads((model / "profile.json").read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise ValueError("No profile.json in this curation root. Set up a taste profile first.") from None
    if not isinstance(profile, dict):
        raise ValueError("profile.json must contain a profile object")
    recommendations = list(_records(model / "recommendations.jsonl"))
    reactions = list(_records(model / "feedback.jsonl"))
    possibilities = []
    helper = None
    if profile.get("taste_hypotheses"):
        helper = runpy.run_path(str(SKILL / "scripts" / "hypotheses.py"))
        profile = helper["validated_profile"](profile, reactions, recommendations)
        possibilities = _possibilities(profile, helper)
    interests = _interests(profile)
    suggestions, undated_suggestions = _activity(recommendations, "recommended_at")
    feedback, undated_feedback = _activity(reactions, "recorded_at")
    stated = sum(interest["kind"] == "stated" for interest in interests)
    return {
        "interests": interests,
        "possibilities": possibilities,
        "months": [
            {"month": month, "suggestions": suggestions[month], "feedback": feedback[month]}
            for month in sorted(suggestions.keys() | feedback.keys())
        ],
        "counts": {"stated": stated, "tentative": len(interests) - stated,
                   "suggestions": sum(suggestions.values()) + undated_suggestions,
                   "feedback": sum(feedback.values()) + undated_feedback},
        "undated": {"suggestions": undated_suggestions, "feedback": undated_feedback},
        "connections": _connections(model, profile, recommendations, helper),
    }


def export_atlas(root):
    model = root.expanduser().resolve() / "model"
    anchor_helper = runpy.run_path(str(SKILL / "scripts" / "graph_anchors.py"))
    try:
        sync = anchor_helper["sync_anchors"](model.parent)
    except (OSError, ValueError) as error:
        sync = {"completed": False, "status": "pending", "reason": str(error)}
    data = atlas_data(model)
    if sync.get("completed") is False:
        data["connections"]["mapping_notice"] = "Automatic interest mapping is pending because saved state could not be updated. Current safe matches are shown."
    template = (SKILL / "assets" / "taste-atlas-template.html").read_text(encoding="utf-8")
    if template.count(DATA_TOKEN) != 1:
        raise ValueError("The bundled taste atlas template is invalid")
    encoded = json.dumps(data, ensure_ascii=False, separators=(",", ":")).translate(
        str.maketrans({"<": r"\u003c", ">": r"\u003e", "&": r"\u0026"})
    )
    output = model / "taste-atlas.html"
    with NamedTemporaryFile(mode="w", encoding="utf-8", dir=model, prefix=".taste-atlas-", delete=False) as file:
        staged = Path(file.name)
        try:
            file.write(template.replace(DATA_TOKEN, encoded))
            file.close()
            os.replace(staged, output)
        finally:
            staged.unlink(missing_ok=True)
    return {"output": str(output), "counts": data["counts"], "undated": data["undated"],
            "connections": data["connections"]["counts"], "anchors_sync": sync}


def main(argv=None):
    parser = argparse.ArgumentParser(prog="trurl atlas", description=__doc__)
    parser.add_argument("--root", type=Path, required=True, help="private curation workspace")
    args = parser.parse_args(argv)
    try:
        result = export_atlas(args.root)
    except (OSError, ValueError) as error:
        parser.exit(2, f"trurl atlas: {error}\n")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
