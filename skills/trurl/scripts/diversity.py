#!/usr/bin/env python3
"""Read-only discovery briefs, eligible-slate selection, and coverage audits.

The host verifies source evidence and request constraints. This module does not
search, verify remote pages, estimate enjoyment probabilities, or update taste.
"""
import argparse
import copy
import json
import math
from pathlib import Path
import random
import re
import runpy
import secrets
import sys
import unicodedata
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

AXES = ("depth", "novelty", "relevance", "surprise", "perspective_change", "entertainment")
LANES = ("familiar", "adjacent", "distant")
EDITION_CATEGORIES = ("book", "podcast", "film", "youtube_video", "lecture", "scientific_paper")
DEFAULT_MIXES = {
    "personal": {"familiar": .75, "adjacent": .25, "distant": 0.0},
    "surprise": {"familiar": .75, "adjacent": .25, "distant": 0.0},
    "deep": {"familiar": .70, "adjacent": .30, "distant": 0.0},
    "playful": {"familiar": .65, "adjacent": .35, "distant": 0.0},
    "perspective": {"familiar": .55, "adjacent": .45, "distant": 0.0},
    "open": {"familiar": .50, "adjacent": .25, "distant": .25},
    "wildcard": {"familiar": .05, "adjacent": .25, "distant": .70},
}
APPROACHES = (
    ("historical context", "museum_or_library"),
    ("methods and mechanisms", "original_research"),
    ("original evidence", "author_or_publisher"),
    ("practitioner perspective", "practitioner_or_official_channel"),
    ("critical or contrasting account", "journal_or_archive"),
)
LIMITS = [
    "The domain registry is a small editorial pool, not a uniform sample of all knowledge.",
    "Source and constraint checks are supplied by the host; this tool does not verify remote evidence.",
    "Diversity counts are descriptive metadata proxies, not measures of identity, quality, or enjoyment.",
    "Personal-connection evidence and relevance scores are supplied judgments, not calibrated enjoyment predictions.",
]
CONNECTION_BASES = {"explicit_interest", "tentative_interest", "current_request", "first_impression_feedback"}
# Keep these conservative current-request controls aligned with the planner.
OPEN_OPT_OUT_PATTERNS = (
    r"\b(?:no|not)\s+(?:open|distant|unrelated|independent)\s+(?:exploration|discoveries|draws|picks|items)\b",
    r"\b(?:do not|don't|dont|never)\s+(?:try (?:a |an )?new area|explore (?:an? )?unfamiliar field|(?:use|enable|include|add|give me) (?:open|distant|unrelated|independent) (?:exploration|discoveries|draws|picks|items))\b",
    r"\b(?:skip|avoid|exclude|disable)\s+(?:all\s+)?(?:open|distant|unrelated|independent)\s+(?:exploration|discoveries|draws|picks|items)\b",
    r"\b(?:stay|keep(?: it| this| the selection| the recommendations)?)\s+(?:close|near)\s+to\s+(?:my |the )?(?:(?:existing|current|usual|known|established)\s+)?interests\b",
    r"\b(?:stick|keep|stay)\s+(?:to|with|within)\s+(?:my |the )?(?:(?:existing|current|usual|known|established)\s+)?interests\b",
)
GENERIC_ANCHORS = {"surprise me", "my interests", "your interests", "me", "unknown", "none", "n a", "profile"}
GENERIC_BRIDGES = {"fits your interests", "matches your interests", "it is surprising", "because surprise", "interesting and new", "this matches you", "good fit"}
BRIEF_TEXT_LIMIT = 240
BRIEF_SOURCE_LIMIT = 2
REQUEST_CONTEXT_FILLER = set("""
    a an the i me my you your we our can could would will do does please thanks
    d s t ll ve don doesn isn aren wasn won wouldn shouldn couldn
    want like prefer give show find get recommend suggest choose pick send make
    surprise surprising surprises wildcard random randomness unrelated connected
    familiar adjacent distant different new unusual weird wild interesting
    inspiration inspire ideas stimulating thought provoking completely entirely
    totally quite very too really just still not no non but and or with without
    within outside usual normal interests interest something anything nothing some
    it that this these those for of to from about on in as by at than more less
    only under over up maximum minimum max min below above between around
    one two three four five six seven eight nine ten eleven twelve thirteen
    fourteen fifteen sixteen seventeen eighteen nineteen twenty thirty forty
    fifty sixty seventy eighty ninety hundred thousand half quarter couple few
    several dozen first second third
    item items recommendation recommendations pick picks selection selections
    video videos film films movie movies book books paper papers article articles
    essay essays podcast podcasts episode episodes talk talks song songs album albums
    short shorter long longer length duration minute minutes min mins hour hours
    hr hrs second seconds sec secs page pages read reading watch watching
    listen listening today tonight now weekly week sunday
""".split())


def _normal(value):
    return " ".join(re.findall(r"\w+", unicodedata.normalize("NFKC", value).casefold())) if isinstance(value, str) else ""


def canonical_url(value):
    """Normalize ordinary tracking parameters and common YouTube aliases."""
    if not isinstance(value, str):
        return None
    try:
        parsed = urlparse(value.strip())
        host = parsed.hostname
    except ValueError:
        return None
    if parsed.scheme not in ("http", "https") or not host:
        return None
    host = host.lower().removeprefix("www.")
    query = dict(parse_qsl(parsed.query, keep_blank_values=True))
    if host in ("youtube.com", "m.youtube.com", "youtu.be"):
        video = query.get("v")
        parts = [p for p in parsed.path.split("/") if p]
        if host == "youtu.be" and parts:
            video = parts[0]
        elif parts and parts[0] in ("shorts", "embed", "live") and len(parts) > 1:
            video = parts[1]
        if video:
            return "https://youtube.com/watch?v=" + video
    query = [(k, v) for k, v in parse_qsl(parsed.query, keep_blank_values=True)
             if not k.lower().startswith("utm_") and k.lower() not in {"ref", "referrer", "feature", "si", "fbclid", "gclid"}]
    return urlunparse(("https", host, parsed.path.rstrip("/") or "/", "", urlencode(sorted(query)), ""))


def work_keys(item):
    keys = set()
    url = canonical_url(item.get("canonical_url") or item.get("url"))
    if url:
        keys.add("url:" + url)
    title, creator = _normal(item.get("title", "")), _normal(item.get("creator", ""))
    if title and creator:
        keys.add("work:" + creator + "|" + title)
    return keys


def _seed(seed):
    if seed is not None and (isinstance(seed, bool) or not isinstance(seed, int)):
        raise ValueError("seed must be an integer")
    return secrets.randbits(64) if seed is None else seed


def _positive_count(count):
    if isinstance(count, bool) or not isinstance(count, int) or count < 1:
        raise ValueError("count must be a positive integer")


def _weights(plan):
    values = plan.get("effective_weights")
    if not isinstance(values, dict) or set(values) != set(AXES):
        raise ValueError("plan requires six effective_weights")
    if any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) or v < 0 for v in values.values()):
        raise ValueError("effective weights must be finite and nonnegative")
    total = math.fsum(values.values())
    if not math.isfinite(total) or total <= 0:
        raise ValueError("effective weights need a finite positive sum")
    return {a: values[a] / total for a in AXES}


def _lane_mix(plan):
    values = plan.get("lane_mix", DEFAULT_MIXES.get(plan.get("mode"), {"familiar": .5, "adjacent": .3, "distant": .2}))
    if not isinstance(values, dict) or set(values) != set(LANES):
        raise ValueError("lane_mix requires familiar, adjacent, distant")
    if any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) or v < 0 for v in values.values()):
        raise ValueError("lane_mix must be finite and nonnegative")
    total = math.fsum(values.values())
    if not math.isclose(total, 1.0):
        raise ValueError("lane_mix must sum to 1")
    return dict(values)


def _allocate(mix, count):
    raw = {lane: count * mix[lane] for lane in LANES}
    counts = {lane: int(raw[lane]) for lane in LANES}
    remainder = count - sum(counts.values())
    ordered = sorted(LANES, key=lambda lane: (-(raw[lane] - counts[lane]), LANES.index(lane)))
    for lane in ordered[:remainder]:
        counts[lane] += 1
    return counts


def _connected_policy(plan):
    """A surprise plan cannot turn off its minimum-fit safeguards."""
    supplied = plan.get("selection_policy")
    active = plan.get("mode") == "surprise" or (isinstance(supplied, dict) and supplied.get("kind") == "connected_surprise_v1")
    if not active:
        return None
    if supplied is not None and not isinstance(supplied, dict):
        raise ValueError("connected surprise selection_policy must be an object")
    supplied = supplied or {}
    if supplied.get("kind", "connected_surprise_v1") != "connected_surprise_v1":
        raise ValueError("surprise requires connected_surprise_v1 policy")
    minimum = supplied.get("min_relevance_score", 3.0)
    fraction = supplied.get("max_exploratory_fraction", .25)
    if isinstance(minimum, bool) or not isinstance(minimum, (int, float)) or not math.isfinite(minimum) or not 3 <= minimum <= 5:
        raise ValueError("connected surprise min_relevance_score must be between 3 and 5")
    if isinstance(fraction, bool) or not isinstance(fraction, (int, float)) or not math.isfinite(fraction) or not 0 < fraction <= .25:
        raise ValueError("connected surprise max_exploratory_fraction must be greater than 0 and at most 0.25")
    if supplied.get("require_personal_connection", True) is not True or supplied.get("allow_distant", False) is not False:
        raise ValueError("connected surprise requires a personal connection and disallows distant items")
    return {"kind": "connected_surprise_v1", "min_relevance_score": float(minimum),
            "require_personal_connection": True, "max_exploratory_fraction": float(fraction), "allow_distant": False}


def _connected_mix(policy):
    fraction = policy["max_exploratory_fraction"]
    return {"familiar": 1 - fraction, "adjacent": fraction, "distant": 0.0}


def _open_policy(plan):
    if _open_opt_out(plan):
        return None
    supplied = plan.get("selection_policy")
    requested = isinstance(supplied, dict) and supplied.get("kind") == "open_exploration_v1"
    standing = plan.get("constraints", {}).get("open_exploration_enabled") is True
    standing_personal = plan.get("mode") == "personal" and standing and _lane_mix(plan)["distant"] > 0
    if requested and plan.get("mode") not in (None, "open") and not standing:
        raise ValueError("open exploration policy requires explicit open mode or standing opt-in")
    if plan.get("mode") != "open" and not requested and not standing_personal:
        return None
    if supplied is not None and not isinstance(supplied, dict):
        raise ValueError("open exploration selection_policy must be an object")
    supplied = supplied or {}
    if supplied.get("kind", "open_exploration_v1") != "open_exploration_v1":
        raise ValueError("open mode requires open_exploration_v1 policy")
    result = {"kind": "open_exploration_v1", "require_personal_connection": True, "allow_distant": True}
    for key, default, lower, upper in (("min_relevance_score", 3.0, 3, 5),
                                        ("max_open_fraction", .25, 0, .25),
                                        ("max_exploratory_fraction", .25, 0, .25)):
        value = supplied.get(key, default)
        if (isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value)
                or not lower <= value <= upper or (lower == 0 and value == 0)):
            raise ValueError("open exploration %s is outside its permitted range" % key)
        result[key] = float(value)
    if supplied.get("require_personal_connection", True) is not True or supplied.get("allow_distant", True) is not True:
        raise ValueError("open exploration requires connected-item safeguards and explicit distant permission")
    return result


def _distant_authorized(plan):
    return (not _open_opt_out(plan) and plan.get("scope", "focused") == "broad" and
            (plan.get("mode") in {"open", "wildcard"} or
             plan.get("constraints", {}).get("open_exploration_enabled") is True))


def _open_opt_out(plan):
    constraints = plan.get("constraints", {})
    if constraints.get("open_exploration_disabled_for_request") is True:
        return True
    request = constraints.get("request", "")
    text = " ".join(request.lower().replace("\u2019", "'").split()) if isinstance(request, str) else ""
    return any(re.search(pattern, text) for pattern in OPEN_OPT_OUT_PATTERNS)


def _research_mix(plan, warnings):
    mix = _lane_mix(plan)
    # Supplied legacy plans without a mode keep their caller's allocation.
    if (plan.get("mode") is not None or _open_opt_out(plan)) and mix["distant"] and not _distant_authorized(plan):
        total = mix["familiar"] + mix["adjacent"]
        mix = ({"familiar": mix["familiar"] / total, "adjacent": mix["adjacent"] / total, "distant": 0.0}
               if total else {"familiar": .75, "adjacent": .25, "distant": 0.0})
        warnings.append("Distant research was not authorized for this plan; its allocation was returned to connected lanes without changing inputs.")
    return mix


def _open_allocation(policy, count, mix):
    counts = _allocate(mix, count)
    counts["distant"] = min(max(1, counts["distant"]), max(1, math.floor(count * policy["max_open_fraction"])))
    counts["adjacent"] = min(counts["adjacent"], max(1, math.floor(count * policy["max_exploratory_fraction"])), count - counts["distant"])
    counts["familiar"] = count - counts["distant"] - counts["adjacent"]
    return counts


def _graph_api():
    return runpy.run_path(str(Path(__file__).resolve().with_name("graph.py")))


def _hypotheses_api():
    return runpy.run_path(str(Path(__file__).resolve().with_name("hypotheses.py")))


def _has_request_context(request):
    # A format, randomness setting, or polite command is not a personal anchor.
    # This conservative lexical check only establishes that some subject/goal
    # detail is present; the host still checks its meaning and the claimed fit.
    tokens = _normal(request).split()
    return any(not token.isdigit() and token not in REQUEST_CONTEXT_FILLER for token in tokens)


def _connection_anchors(profile):
    """Use the shared personal-evidence policy; ordinary briefs need a topic."""
    return [anchor for anchor in _graph_api()["personal_anchors"](profile)
            if isinstance(anchor.get("topic"), str) and anchor["topic"].strip()]


def _distinct_theme(left, right):
    """Different records alone do not establish different interests."""
    return (left["id"] != right["id"] and _normal(left["topic"]) != _normal(right["topic"])
            and not (left.get("graph_node_id") and left.get("graph_node_id") == right.get("graph_node_id")))


def _supporting_interest(anchor):
    """A bounded pointer to original evidence, never a replacement profile."""
    result = {"id": anchor["id"], "topic_excerpt": anchor["topic"][:BRIEF_TEXT_LIMIT],
              "kind": anchor["kind"], "context_omitted": True}
    if "confidence" in anchor:
        result["confidence"] = anchor["confidence"]
    if isinstance(anchor.get("scope"), str):
        result["scope_excerpt"] = anchor["scope"][:BRIEF_TEXT_LIMIT]
    refs = []
    sources = anchor.get("source_provenance", [])
    for source in sources if isinstance(sources, list) else [sources]:
        if isinstance(source, dict):
            source = source.get("id") or source.get("locator")
        if isinstance(source, str) and 0 < len(source) <= BRIEF_TEXT_LIMIT and source not in refs:
            refs.append(source)
        if len(refs) == BRIEF_SOURCE_LIMIT:
            break
    if refs:
        result["source_refs"] = refs
    return result


def _hypothesis_context(hypothesis, anchor_ids):
    """Do not duplicate feedback ledgers, hashes or unbounded rationale text."""
    result = {"status": hypothesis["status"], "reason_excerpt": hypothesis["reason"][:BRIEF_TEXT_LIMIT],
              "anchor_ids": anchor_ids, "anchor_count": len(hypothesis["anchor_ids"]),
              "context_omitted": True}
    for key in ("supporting_work_count", "conflicting_work_feedback", "ambiguous_broad_feedback"):
        if key in hypothesis:
            result[key] = hypothesis[key]
    return result


def _hypothesis_brief(briefs, profile, seed, history=None, maintenance=None):
    """Enrich at most one existing adjacent slot; never write a hypothesis."""
    adjacent = next((brief for brief in briefs if brief["lane"] == "adjacent"), None)
    if adjacent is None:
        return
    helper = _hypotheses_api()
    anchors = {anchor["id"]: anchor for anchor in helper["original_anchors"](profile)}
    hypotheses = helper["active_hypotheses"](profile) if profile.get("taste_hypotheses") else []
    if hypotheses:
        tried = {item.get("hypothesis_id") for item in (history or []) if isinstance(item, dict)}
        untried = [item for item in hypotheses if item["id"] not in tried]
        hypothesis = random.Random(str(seed) + ":taste-hypothesis").choice(untried or hypotheses)
        primary = anchors[hypothesis["anchor_ids"][0]]
        secondary = next((anchors[key] for key in hypothesis["anchor_ids"][1:]
                          if _distinct_theme(primary, anchors[key])), None)
        selected_ids = [primary["id"]] + ([secondary["id"]] if secondary else [])
        adjacent.update({
            "field": hypothesis["topic"], "interest_evidence": copy.deepcopy(primary),
            "hypothesis_id": hypothesis["id"],
            "taste_hypothesis": _hypothesis_context(hypothesis, selected_ids),
            "personal_fit_status": "hypothesis",
            "instruction": (
                "Research this tentative hypothesis using its original interests. Read full originals by ID, "
                "including omitted anchors/rationale; excerpts are not evidence. Explain each interest's contribution "
                "and uncertainty without forcing every connection. Verify a worthwhile work under the request constraints. "
                "Retain hypothesis_id, lane adjacent and personal_connection to an original anchor. "
                "Keep reasoning private; more anchors do not increase preference confidence."
            ),
        })
        if secondary:
            adjacent["supporting_interest"] = _supporting_interest(secondary)
        return
    if maintenance and maintenance.get("completed"):
        # A recorded no-proposal review must not prompt another generation pass.
        return
    primary = adjacent.get("interest_evidence")
    if not primary or primary["id"] not in anchors:
        return
    choices = [anchor for anchor in anchors.values() if _distinct_theme(primary, anchor)]
    if not choices:
        return
    secondary = random.Random(str(seed) + ":hypothesis-pair").choice(choices)
    adjacent.update({
        "supporting_interest": _supporting_interest(secondary), "hypothesis_action": "propose",
        "instruction": (
            "Consider one tentative connection between these two original interests. Read full originals by ID; "
            "excerpts are not evidence. Explain what each contributes and keep weak links uncertain. "
            "Check existing rejected or retired explanations before proposing it. If useful, save it through "
            "the hypothesis workflow and retain its ID on adjacent candidates; otherwise use the original brief's "
            "single-interest direction. Verify sources and request fit. No extra pick or preference update; keep reasoning private."
        ),
    })


def _connection_errors(item, policy, scope):
    errors = []
    if item["scores"]["relevance"] < policy["min_relevance_score"]:
        errors.append("relevance_below_connected_floor")
    if item["lane"] == "distant":
        errors.append("distant_not_enabled_for_connected_surprise")
    elif item["lane"] == "focused" and scope != "focused":
        errors.append("focused_lane_requires_focused_scope")
    elif item["lane"] not in {"familiar", "adjacent", "focused"}:
        errors.append("unrecognized_connected_lane")
    connection = item.get("personal_connection")
    if (not isinstance(connection, dict) or not isinstance(connection.get("basis"), str) or connection.get("basis") not in CONNECTION_BASES
            or not _normal(connection.get("anchor")) or _normal(connection.get("anchor")) in GENERIC_ANCHORS
            or not _normal(connection.get("explanation")) or _normal(connection.get("explanation")) in GENERIC_BRIDGES):
        errors.append("personal_connection_missing_or_invalid")
    return errors


def explore(plan, profile, history=None, seed=None, count=5, registry=None, graph=None, feedback=None,
            maintenance=None, anchor_mappings=None):
    """Create external-randomness briefs before model candidate generation."""
    _positive_count(count)
    if not isinstance(plan, dict) or not isinstance(profile, dict):
        raise ValueError("plan and profile must be JSON objects")
    if profile.get("taste_hypotheses"):
        profile = _hypotheses_api()["validated_profile"](profile, feedback, history)
    connected = _connected_policy(plan)
    open_policy = _open_policy(plan)
    if registry is None:
        registry = json.loads((Path(__file__).resolve().parents[1] / "references" / "domains.json").read_text(encoding="utf-8"))
    entries = registry.get("domains") if isinstance(registry, dict) else None
    if not isinstance(entries, list) or not entries:
        raise ValueError("registry requires nonempty domains")
    fields = []
    for entry in entries:
        if not isinstance(entry, dict) or not isinstance(entry.get("field"), str) or not entry["field"].strip():
            raise ValueError("each registry domain needs a field")
        fields.append(entry["field"].strip())
    if len({_normal(f) for f in fields}) != len(fields):
        raise ValueError("registry fields must be unique")
    explicit = _connection_anchors(profile)
    known = {_normal(i["topic"]) for i in explicit}
    recent = {t for item in list(history or [])[-24:] for t in _topics(item)}
    eligible = sorted(f for f in fields if _normal(f) not in known | recent)
    actual_seed = _seed(seed)
    rng = random.Random(actual_seed)
    scope = plan.get("scope", "focused")
    if scope not in ("focused", "broad"):
        raise ValueError("plan scope must be focused or broad")
    request = plan.get("constraints", {}).get("request", "")
    if not isinstance(request, str):
        raise ValueError("plan request must be text")
    approaches = list(APPROACHES)
    rng.shuffle(approaches)
    warnings = []
    if actual_seed == plan.get("seed"):
        warnings.append("Discovery and weight seeds coincide; retain them as separate recorded inputs, preferably generate a fresh discovery seed.")
    briefs = []
    graph_frontier = None
    insufficient_context = False
    if open_policy and scope == "broad":
        allocation = _open_allocation(open_policy, count, _lane_mix(plan))
        graph_api = _graph_api()
        graph_frontier = graph_api["frontier"](
            graph if graph is not None else graph_api["empty_graph"](), profile, history=history,
            seed=actual_seed, count=count, max_hops=plan.get("constraints", {}).get("graph_max_hops", 2),
            allow_open=True, open_count=allocation["distant"], registry=registry, feedback=feedback,
            anchor_mappings=anchor_mappings)
        anchors = list(explicit)
        rng.shuffle(anchors)
        for lane in ("familiar", "adjacent"):
            for n in range(allocation[lane]):
                approach, source = approaches[len(briefs) % len(approaches)]
                anchor = anchors[len(briefs) % len(anchors)] if anchors else None
                briefs.append({"id": "brief-%02d" % (len(briefs) + 1), "lane": lane,
                               "field": anchor["topic"] if anchor else None,
                               "approach": approach, "source_family": source, "request_constraint": request,
                               "interest_evidence": copy.deepcopy(anchor),
                               "personal_fit_status": "evidenced_anchor" if anchor else "unknown",
                               "instruction": ("Develop this evidenced interest or a concrete neighboring connection; retain its evidence and uncertainty." if anchor else
                                               "Offer an honestly labeled generic starter under the request constraints; do not invent a personal connection or a known preference.")})
        for route in graph_frontier["open"]:
            approach, source = approaches[len(briefs) % len(approaches)]
            briefs.append({"id": "brief-%02d" % (len(briefs) + 1), "lane": "distant",
                           "field": route["field"], "category": route.get("category"),
                           "approach": approach, "source_family": source, "request_constraint": request,
                           "interest_evidence": None, "selection_channel": "open", "personal_fit_status": "unknown",
                           "instruction": "Research this independently drawn field on its concrete merits. Verify sources and constraints, explain its value, and leave personal relevance unknown; do not fabricate a personal bridge."})
        eligible = graph_frontier.get("eligible_pool", [])
        if not anchors:
            warnings.append("No evidenced personal anchors were available; connected briefs are generic starters, while the authorized open draw has unknown personal fit.")
        warnings.extend(graph_frontier.get("warnings", []))
    elif connected:
        anchors = _connection_anchors(profile)
        rng.shuffle(anchors)
        has_request_context = _has_request_context(request)
        insufficient_context = not anchors and not has_request_context
        if insufficient_context:
            warnings.append("Insufficient personal context: ask for one interest or current goal before claiming a connected surprise; no random-domain fallback was used.")
        elif scope == "focused":
            for n in range(count):
                approach, source = approaches[n % len(approaches)]
                interest = anchors[n % len(anchors)] if anchors else None
                briefs.append({"id": "brief-%02d" % (n + 1), "lane": "focused", "field": None,
                               "approach": approach, "source_family": source, "request_constraint": request,
                               "interest_evidence": copy.deepcopy(interest),
                               "instruction": "Find an unexpected connection within the exact requested subject and limits. Explain the bridge to the supplied interest or current request; do not invent personal fit."})
        else:
            allocation = _allocate(_connected_mix(connected), count)
            if count == 1:
                allocation = {"familiar": 0, "adjacent": 1, "distant": 0}
            for lane in ("familiar", "adjacent"):
                for n in range(allocation[lane]):
                    approach, source = approaches[len(briefs) % len(approaches)]
                    interest = anchors[len(briefs) % len(anchors)] if anchors else None
                    briefs.append({"id": "brief-%02d" % (len(briefs) + 1), "lane": lane,
                                   "field": interest["topic"] if interest else None,
                                   "approach": approach, "source_family": source, "request_constraint": request,
                                   "interest_evidence": copy.deepcopy(interest),
                                   "instruction": ("Develop an unexpected angle within this evidenced interest or current goal." if lane == "familiar" else
                                                   "Find one connected neighboring idea and explain its concrete bridge to this evidenced interest or current goal. Do not replace the anchor with an unrelated registry field.")})
        eligible = []
    elif scope == "focused":
        for n in range(count):
            approach, source = approaches[n % len(approaches)]
            briefs.append({"id": "brief-%02d" % (n + 1), "lane": "focused", "field": None,
                           "approach": approach, "source_family": source,
                           "request_constraint": request, "knowledge_level": "unknown",
                           "instruction": "Keep the exact requested subject, medium and limits; explore this approach within that request. Adapt the source family to the requested medium."})
    else:
        allocation = _allocate(_research_mix(plan, warnings), count)
        drawn = rng.sample(eligible, min(allocation["distant"], len(eligible)))
        if len(drawn) < allocation["distant"]:
            warnings.append("The eligible editorial domain pool cannot fill the distant allocation; no excluded field was silently reintroduced.")
        rng.shuffle(explicit)
        for lane in LANES:
            for n in range(allocation[lane]):
                approach, source = approaches[len(briefs) % len(approaches)]
                if lane == "distant":
                    if n >= len(drawn):
                        continue
                    field, evidence = drawn[n], None
                else:
                    interest = explicit[n % len(explicit)] if explicit else None
                    field = interest["topic"] if interest else None
                    evidence = copy.deepcopy(interest) if interest else None
                brief = {"id": "brief-%02d" % (len(briefs) + 1), "lane": lane, "field": field,
                         "approach": approach, "source_family": source, "request_constraint": request,
                         "interest_evidence": evidence,
                         "instruction": ("Research this drawn field without forcing a personal analogy." if lane == "distant" else
                                         "Develop this evidenced interest, retaining any tentative status." if lane == "familiar" and evidence else
                                         "Find a genuinely neighboring discipline or method for this evidenced interest, retaining any tentative status." if evidence else
                                         "No confirmed interest is available: use the current request and mark personalization as unknown.")}
                briefs.append(brief)
        if not explicit and (allocation["familiar"] or allocation["adjacent"]):
            warnings.append("No evidenced interests were available for familiar/adjacent anchors; none were inferred from identity or assistant characterizations.")
    if graph is not None and graph_frontier is None:
        if scope == "focused":
            warnings.append("Graph frontier enrichment was suppressed for this focused request; no independent graph or registry probes were added.")
        else:
            graph_api = _graph_api()
            mix = _connected_mix(connected) if connected else _research_mix(plan, [])
            open_count = min(_allocate(mix, count)["distant"], max(1, math.floor(count * .25))) if _distant_authorized(plan) and not connected else 0
            graph_frontier = graph_api["frontier"](graph, profile, history=history, seed=actual_seed, count=count,
                                                    max_hops=plan.get("constraints", {}).get("graph_max_hops", 2),
                                                    allow_open=bool(open_count), open_count=open_count, registry=registry,
                                                    feedback=feedback, anchor_mappings=anchor_mappings)
    if scope == "broad" and plan.get("mode") != "wildcard":
        _hypothesis_brief(briefs, profile, actual_seed, history, maintenance)
    result = {"schema_version": 1, "seed": actual_seed, "weight_seed": plan.get("seed"), "scope": scope,
            "registry_version": registry.get("version", "unversioned"), "eligible_pool": eligible,
            "registry_used": bool(any(b["lane"] == "distant" for b in briefs)) if plan.get("mode") is not None or _open_opt_out(plan) else not bool(connected), "insufficient_context": insufficient_context,
            "selection_policy": connected or open_policy,
            "pool_exclusion_rule": ("Connected surprise uses evidenced interest/request anchors, not independent domain draws." if connected else
                                    "Category-stratified registry probes exclude known topic labels/aliases, connected destinations and recent history; see graph_frontier for the actual pool and strata." if open_policy and scope == "broad" else
                                    "Exact normalized evidenced topics and topics from the last 24 supplied history items; semantic distance is not guaranteed."),
            "briefs": briefs, "generation_instruction": "Generate five substantively different candidate directions, not five variations of a bestseller list. Research works from several briefs and source families before ranking. Optional verbalized generation likelihood is uncalibrated and must not be used as enjoyment probability or selection weight.",
            "warnings": warnings, "limits": list(LIMITS), "profile_changed": False}
    if graph_frontier is not None:
        result["graph_frontier"] = graph_frontier
    if maintenance is not None:
        result["hypothesis_maintenance"] = copy.deepcopy(maintenance)
    return result


def _candidate_errors(item, allow_unknown_relevance=False):
    if not isinstance(item, dict):
        return ["candidate_not_object"]
    errors = []
    for field in ("id", "title", "creator", "canonical_url", "medium", "lane"):
        if not isinstance(item.get(field), str) or not item[field].strip():
            errors.append("missing_" + field)
    if canonical_url(item.get("canonical_url")) is None:
        errors.append("invalid_canonical_url")
    if item.get("constraints_passed") is not True:
        errors.append("constraints_not_confirmed")
    if item.get("credibility_passed") is not True:
        errors.append("credibility_not_confirmed")
    verification = item.get("verification", {})
    if (not isinstance(verification, dict) or not isinstance(verification.get("checked_at"), str)
            or not verification["checked_at"].strip() or not isinstance(verification.get("urls"), list)
            or not verification["urls"] or not all(canonical_url(u) for u in verification["urls"])):
        errors.append("verification_missing_or_invalid")
    if not isinstance(item.get("topics"), list) or not all(isinstance(t, str) and t.strip() for t in item.get("topics", [])):
        errors.append("topics_missing_or_invalid")
    scores = item.get("scores")
    if (not isinstance(scores, dict) or set(scores) != set(AXES)
            or any(not (allow_unknown_relevance and axis == "relevance" and v is None)
                   and (isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) or not 0 <= v <= 5)
                   for axis, v in scores.items())):
        errors.append("scores_missing_or_invalid")
    return errors


def _open_candidate_errors(item, policy, scope):
    if item["lane"] != "distant":
        return _connection_errors(item, policy, scope)
    errors = []
    if scope != "broad":
        errors.append("distant_open_requires_broad_scope")
    if item.get("personal_fit_status") != "unknown":
        errors.append("open_personal_fit_must_be_unknown")
    rationale = _normal(item.get("value_rationale"))
    if not rationale or rationale in GENERIC_BRIDGES | {"interesting", "novel", "new", "unknown", "good", "valuable"}:
        errors.append("open_value_rationale_missing_or_invalid")
    return errors


def _topics(item):
    labels = item.get("topics")
    return {_normal(t) for t in labels if isinstance(t, str) and _normal(t)} if isinstance(labels, list) else set()


def _overlap(left, right):
    return len(left & right) / len(left | right) if left and right else 0.0


def _category_choices(pool, adjacent_left, distant_left, non_open_left, needs_open):
    """Keep choices that can fill the most distinct categories under the lane caps."""
    lanes_by_category = {}
    for record in pool:
        item = record["item"]
        lanes_by_category.setdefault(item["medium"], set()).add(item["lane"])

    completion = {}
    for category, lanes in lanes_by_category.items():
        for lane in lanes:
            # Track reachable counts for other categories. Skipping a category
            # remains possible when the eligible pool cannot fill every slot.
            reachable = {(int(lane == "adjacent"), int(lane == "distant"), int(lane != "distant"))}
            for other, other_lanes in lanes_by_category.items():
                if other == category:
                    continue
                additions = set()
                for adjacent, distant, non_open in reachable:
                    for option in other_lanes:
                        counts = (adjacent + (option == "adjacent"), distant + (option == "distant"),
                                  non_open + (option != "distant"))
                        if counts[0] <= adjacent_left and counts[1] <= distant_left and counts[2] <= non_open_left:
                            additions.add(counts)
                reachable.update(additions)
            completion[category, lane] = max((needs_open and distant > 0, distant + non_open)
                                             for _, distant, non_open in reachable)
    best = max(completion.values())
    return [record for record in pool if completion[record["item"]["medium"], record["item"]["lane"]] == best]


def select_slate(plan, candidates, count, history=None, seed=None, min_score=2.5, allow_creator_repeat=False,
                 *, categories=None):
    """Greedy diversity heuristics after strict host-supplied eligibility gates."""
    if categories is not None:
        if (not isinstance(categories, (list, tuple)) or not categories
                or any(category not in EDITION_CATEGORIES for category in categories)
                or len(set(categories)) != len(categories)):
            raise ValueError("categories must be distinct Sunday edition medium IDs")
        if count is None:
            count = len(categories)
        elif count != len(categories):
            raise ValueError("count must match the number of requested categories")
    _positive_count(count)
    selection_warnings = []
    weights, mix = _weights(plan), _research_mix(plan, selection_warnings)
    connected = _connected_policy(plan)
    open_policy = _open_policy(plan)
    if connected:
        mix = _connected_mix(connected)
    policy = connected or open_policy
    exploratory_cap = max(1, math.floor(count * policy["max_exploratory_fraction"])) if policy else None
    open_cap = max(1, math.floor(count * open_policy["max_open_fraction"])) if open_policy else None
    # Explicit broad discovery promises one qualified independent item. Saved
    # permission merely permits open picks; it does not reserve a delivered slot.
    required_open = 1 if open_policy and plan.get("mode") == "open" and plan.get("scope") == "broad" else 0
    non_open_cap = count - required_open
    if isinstance(min_score, bool) or not isinstance(min_score, (int, float)) or not math.isfinite(min_score) or not 0 <= min_score <= 5:
        raise ValueError("min_score must be a finite subjective weighted-fit threshold from 0 to 5")
    if not isinstance(candidates, list) or not all(isinstance(i, dict) for i in (history or [])):
        raise ValueError("candidates and history must be arrays of objects")
    actual_seed = _seed(seed)
    rng = random.Random(actual_seed)
    history_supplied = history is not None
    history = list(history or [])
    previous_keys = set().union(*(work_keys(i) for i in history)) if history else set()
    excluded, pool, seen_ids = [], [], set()
    for position, item in enumerate(candidates):
        unknown_allowed = bool(open_policy and plan.get("scope") == "broad" and isinstance(item, dict) and item.get("lane") == "distant")
        errors = _candidate_errors(item, allow_unknown_relevance=unknown_allowed)
        identifier = item.get("id") if isinstance(item, dict) else None
        identifier = identifier if isinstance(identifier, str) else "candidate-%d" % position
        if identifier in seen_ids:
            errors.append("duplicate_candidate_id")
        seen_ids.add(identifier)
        if not errors and connected:
            errors.extend(_connection_errors(item, connected, plan.get("scope")))
        elif not errors and open_policy:
            errors.extend(_open_candidate_errors(item, open_policy, plan.get("scope")))
        elif (not errors and (plan.get("mode") is not None or _open_opt_out(plan)) and item.get("lane") == "distant"
              and not _distant_authorized(plan)):
            errors.append("distant_not_enabled_for_plan")
        if not errors and "hypothesis_id" in item:
            if not isinstance(item["hypothesis_id"], str) or not item["hypothesis_id"].strip():
                errors.append("invalid_hypothesis_id")
            if item["lane"] != "adjacent" or plan.get("scope") != "broad":
                errors.append("hypothesis_probe_requires_broad_adjacent_lane")
            errors.extend(_connection_errors(item, {"min_relevance_score": 3.0}, plan.get("scope")))
        if not errors:
            if categories is not None and item["medium"] not in categories:
                errors.append("category_not_requested")
            if work_keys(item) & previous_keys:
                errors.append("previously_recommended")
            scoring_weights = weights
            scoring_basis = "six_axis_weighted_fit"
            if unknown_allowed:
                value_total = math.fsum(weights[a] for a in AXES if a != "relevance")
                if value_total <= 0:
                    errors.append("no_nonrelevance_weight_for_open_value")
                else:
                    scoring_weights = {a: weights[a] / value_total for a in AXES if a != "relevance"}
                    scoring_basis = "open_value_without_personal_relevance"
            base = math.fsum(scoring_weights[a] * item["scores"][a] for a in scoring_weights) if not errors else None
            if base is not None and base < min_score:
                errors.append("below_subjective_fit_threshold")
        if errors:
            excluded.append({"id": identifier, "reasons": errors})
        else:
            pool.append({"item": copy.deepcopy(item), "base": base,
                         "scoring_basis": scoring_basis, "scoring_weights": dict(scoring_weights)})
    # Collapse work identities before random tie draws: several source aliases
    # must not give a frequently surfaced work several lottery tickets.
    groups = []
    for record in pool:
        keys = work_keys(record["item"])
        overlap = [g for g in groups if g["keys"] & keys]
        members = [record] + [m for g in overlap for m in g["members"]]
        groups = [g for g in groups if g not in overlap]
        groups.append({"keys": keys.union(*(g["keys"] for g in overlap)), "members": members})
    pool = []
    for group in sorted(groups, key=lambda g: sorted(g["keys"])):
        representative = max(group["members"], key=lambda r: (r["base"], r["item"]["id"]))
        representative["tie"] = rng.random()
        pool.append(representative)
        for alias in group["members"]:
            if alias is not representative:
                excluded.append({"id": alias["item"]["id"], "reasons": ["duplicate_work"], "duplicate_of": representative["item"]["id"]})
    recent = history[-24:]
    recent_creators = {_normal(i.get("creator", "")) for i in recent if i.get("creator")}
    recent_topics = [_topics(i) for i in recent]
    selected, selected_keys, filled_categories = [], set(), set()
    while pool and len(selected) < count:
        remaining = []
        exploratory_count = sum(i["lane"] == "adjacent" for i in selected)
        hypothesis_selected = any("hypothesis_id" in item for item in selected)
        open_count = sum(i["lane"] == "distant" for i in selected)
        non_open_count = len(selected) - open_count
        for record in pool:
            if work_keys(record["item"]) & selected_keys:
                excluded.append({"id": record["item"]["id"], "reasons": ["duplicate_work"]})
            elif categories is not None and record["item"]["medium"] in filled_categories:
                excluded.append({"id": record["item"]["id"], "reasons": ["category_already_selected"]})
            elif hypothesis_selected and "hypothesis_id" in record["item"]:
                excluded.append({"id": record["item"]["id"], "reasons": ["hypothesis_probe_cap_reached"]})
            elif required_open and record["item"]["lane"] != "distant" and non_open_count >= non_open_cap:
                excluded.append({"id": record["item"]["id"], "reasons": ["explicit_open_slot_reserved"]})
            elif policy and record["item"]["lane"] == "adjacent" and exploratory_count >= exploratory_cap:
                excluded.append({"id": record["item"]["id"], "reasons": ["connected_exploratory_cap_reached"]})
            elif open_policy and record["item"]["lane"] == "distant" and open_count >= open_cap:
                excluded.append({"id": record["item"]["id"], "reasons": ["open_exploration_cap_reached"]})
            else:
                remaining.append(record)
        pool = remaining
        if not pool:
            break
        choices = pool
        if categories is not None and policy:
            choices = _category_choices(pool, exploratory_cap - exploratory_count,
                                        open_cap - open_count if open_cap is not None else count,
                                        non_open_cap - non_open_count, open_count < required_open)
        creators = {_normal(i["creator"]) for i in selected}
        best_base = max(r["base"] for r in choices)
        comparable_new_creator = any(_normal(r["item"]["creator"]) not in creators and r["base"] >= best_base - .75 for r in choices)
        ranked = []
        for record in choices:
            item = record["item"]
            creator = _normal(item["creator"])
            same_creator = creator in creators
            if not allow_creator_repeat and same_creator and comparable_new_creator:
                continue
            same_creator_penalty = .6 if same_creator and not allow_creator_repeat else 0.0
            recent_creator_penalty = .2 if creator in recent_creators and not allow_creator_repeat else 0.0
            intra_topic_penalty = .25 * max((_overlap(_topics(item), _topics(s)) for s in selected), default=0.0)
            recent_topic_penalty = .15 * max((_overlap(_topics(item), t) for t in recent_topics), default=0.0)
            lane = item["lane"]
            lane_bonus = .25 * max(0.0, mix.get(lane, 0.0) - sum(s["lane"] == lane for s in selected) / max(1, len(selected)))
            score = record["base"] - same_creator_penalty - recent_creator_penalty - intra_topic_penalty - recent_topic_penalty + lane_bonus
            ranked.append((score, record["base"], record["tie"], record, {
                "same_creator": same_creator_penalty, "recent_creator": recent_creator_penalty,
                "intra_slate_topic": intra_topic_penalty, "recent_topic": recent_topic_penalty,
                "lane_bonus": lane_bonus}))
        _, _, _, chosen, adjustment = max(ranked, key=lambda r: r[:3])
        item = chosen["item"]
        item.update({"base_score": chosen["base"], "selection_score": ranked_score(chosen["base"], adjustment),
                     "diversity_adjustment": adjustment, "scoring_basis": chosen["scoring_basis"],
                     "scoring_weights": chosen["scoring_weights"]})
        selected.append(item)
        selected_keys.update(work_keys(item))
        filled_categories.add(item["medium"])
        pool.remove(chosen)
    for record in pool:
        excluded.append({"id": record["item"]["id"], "reasons": ["not_selected"]})
    selected_open = sum(i["lane"] == "distant" for i in selected)
    result = {"schema_version": 1, "seed": actual_seed, "selected": selected, "excluded": excluded,
            "requested_count": count, "shortfall": max(0, count - len(selected)), "min_score": min_score,
            "required_open_items": required_open, "selected_open_items": selected_open,
            "open_shortfall": max(0, required_open - selected_open),
            "threshold_interpretation": "Minimum subjective weighted fit for connected items or five-axis value for open items; not an intrinsic quality score or calibrated probability.",
            "effective_weights": weights, "lane_mix_target": mix,
            "selection_policy": policy, "max_exploratory_items": exploratory_cap, "max_open_items": open_cap,
            "policy": {"within_slate_creator_repeat": "allowed" if allow_creator_repeat else "avoid when a new creator is within 0.75 base-score points",
                       "explicit_broad_open": "reserve one eligible distant item; leave its slot empty if no candidate passes the gates",
                       "recent_history_window": 24, "diversity_coefficients": {"same_creator": .6, "recent_creator": .2, "intra_topic": .25, "recent_topic": .15, "lane_bonus": .25},
                       "status": "experimental editorial heuristics; not validated effect sizes from the cited research"},
            "history_supplied": history_supplied,
            "warnings": selection_warnings,
            "audit": audit_items(selected, history if history_supplied else None), "limits": list(LIMITS), "inputs_changed": False}
    if categories is not None:
        result.update(requested_categories=list(categories),
                      missing_categories=[category for category in categories if category not in filled_categories])
    return result


def ranked_score(base, adjustment):
    return base - sum(v for k, v in adjustment.items() if k != "lane_bonus") + adjustment["lane_bonus"]


def audit_items(items, previous=None):
    """Descriptive concentration and overlap, with missing coverage exposed."""
    if not isinstance(items, list) or not all(isinstance(i, dict) for i in items):
        raise ValueError("items must be an array of objects")
    if previous is not None and (not isinstance(previous, list) or not all(isinstance(i, dict) for i in previous)):
        raise ValueError("previous must be an array of objects")
    previous_supplied = previous is not None
    previous = previous or []
    previous_keys = set().union(*(work_keys(i) for i in previous)) if previous else set()
    identity_items = [i for i in items if work_keys(i)]
    groups = []
    for item in identity_items:
        keys = work_keys(item)
        overlapping = [g for g in groups if g & keys]
        if not overlapping:
            groups.append(keys)
        else:
            merged = set(keys).union(*overlapping)
            groups = [g for g in groups if g not in overlapping] + [merged]
    creators, topics = {}, {}
    creator_observed = topic_observed = 0
    for item in items:
        creator = _normal(item.get("creator", ""))
        if creator:
            creator_observed += 1
            creators[creator] = creators.get(creator, 0) + 1
        labels = _topics(item)
        if labels:
            topic_observed += 1
            for topic in labels:
                topics[topic] = topics.get(topic, 0) + 1
    repeated = sum(bool(work_keys(i) & previous_keys) for i in identity_items)
    def hhi(counts):
        total = sum(counts.values())
        return math.fsum((n / total) ** 2 for n in counts.values()) if total else None
    current_unique = len(groups)
    # Form a shared identity graph for overlap. A previous alias can connect two
    # current metadata records, so independently counted denominators can exceed1.
    all_groups = audit_unique(items + previous)
    current_keys = set().union(*(work_keys(i) for i in items)) if items else set()
    common_unique = sum(bool(g & current_keys) and bool(g & previous_keys) for g in all_groups)
    union_count = len(all_groups)
    return {"n_items": len(items), "identity_observed_count": len(identity_items), "identity_missing_count": len(items) - len(identity_items),
            "unique_work_count": current_unique, "previous_supplied": previous_supplied,
            "previous_identity_observed_count": sum(bool(work_keys(i)) for i in previous),
            "repeat_count": repeated if previous_supplied else None,
            "repeat_fraction": repeated / len(identity_items) if previous_supplied and identity_items else None,
            "work_jaccard_with_previous": common_unique / union_count if previous_supplied and union_count else None,
            "creator_observed_count": creator_observed, "creator_missing_count": len(items) - creator_observed,
            "creator_counts": dict(sorted(creators.items())), "creator_hhi": hhi(creators),
            "topic_observed_items": topic_observed, "topic_missing_count": len(items) - topic_observed,
            "topic_coverage_count": len(topics), "topic_counts": dict(sorted(topics.items())), "topic_hhi": hhi(topics),
            "definitions": {"creator_hhi": "Sum of squared creator shares among items with creator metadata.",
                            "topic_hhi": "Sum of squared topic-label shares; multi-topic works contribute multiple label assignments.",
                            "repeat_fraction": "Share of identity-observed current items matching at least one previous work."},
            "limits": list(LIMITS)}


def audit_unique(items):
    groups = []
    for item in items:
        keys = work_keys(item)
        if not keys:
            continue
        overlap = [g for g in groups if g & keys]
        groups = [g for g in groups if g not in overlap] + [set(keys).union(*overlap)]
    return groups


def _load(path, items=False):
    text = Path(path).expanduser().read_text(encoding="utf-8")
    if not text.strip():
        return [] if items else {}
    if Path(path).suffix == ".jsonl":
        value = [json.loads(line) for line in text.splitlines() if line.strip()]
    else:
        value = json.loads(text)
    if items and isinstance(value, dict):
        for key in ("items", "candidates", "selected"):
            if key in value:
                return value[key]
    return value


def _maintenance_gate(plan, root):
    """Require the current receipt for plans emitted by the active workflow."""
    if root is None:
        if plan.get("hypothesis_maintenance_required"):
            raise ValueError("this plan requires hypothesis maintenance; pass --root <curation-root>")
        return None
    state = _hypotheses_api()["maintenance_check"](root, plan=plan)
    if state["eligible"] and not state["completed"]:
        raise ValueError("hypothesis maintenance is due (" + ", ".join(state["triggers"]) +
                         "); run hypotheses maintenance-plan and record its outcome before proceeding")
    return state


def _same_model_file(root, path, name):
    if Path(path).expanduser().resolve() != (Path(root).expanduser() / "model" / name).resolve():
        raise ValueError("maintenance and curation must use the same model/" + name)


def _graph_update_gate(plan, root, research, batch_id):
    if root is None or not batch_id:
        if plan.get("graph_update_required"):
            raise ValueError("this plan requires a graph update record; pass --root and --batch-id")
        return None
    helper = runpy.run_path(str(Path(__file__).resolve().with_name("graph_updates.py")))
    result = helper["check_update"](root, research, batch_id)
    if not result["completed"]:
        raise ValueError("graph update is pending; run graph-update with --batch-id for this research and batch")
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    discovery = sub.add_parser("explore", help="create briefs; rooted runs synchronize graph anchor representation")
    discovery.add_argument("--plan", required=True)
    discovery.add_argument("--profile", required=True)
    discovery.add_argument("--root", help="curation root for the required hypothesis-maintenance check")
    discovery.add_argument("--history")
    discovery.add_argument("--feedback", help="feedback JSONL; defaults to the profile's sibling ledger")
    discovery.add_argument("--graph", help="content graph JSON; defaults to the root's synchronized graph when --root is supplied")
    discovery.add_argument("--seed", type=int)
    discovery.add_argument("--count", type=int, default=5)
    selection = sub.add_parser("select", help="select from host-verified, constraint-checked candidates")
    selection.add_argument("--plan", required=True)
    selection.add_argument("--root", help="curation root for the required hypothesis-maintenance check")
    selection.add_argument("--batch-id", help="delivery batch identifier for the post-research graph update check")
    selection.add_argument("--candidates", required=True)
    selection.add_argument("--history")
    selection.add_argument("--seed", type=int)
    selection.add_argument("--count", type=int, help="total picks; defaults to the number of requested categories")
    selection.add_argument("--category", action="append", choices=EDITION_CATEGORIES,
                           help="request one pick in this category; repeat for each desired category")
    selection.add_argument("--min-score", type=float, default=2.5)
    selection.add_argument("--allow-creator-repeat", action="store_true")
    audit = sub.add_parser("audit", help="describe observed work/creator/topic coverage")
    audit.add_argument("--items", required=True)
    audit.add_argument("--previous")
    args = parser.parse_args(argv)
    if args.command == "select" and args.count is None and not args.category:
        selection.error("--count is required unless --category is supplied")
    try:
        plan = _load(args.plan) if args.command in {"explore", "select"} else None
        maintenance = _maintenance_gate(plan, args.root) if plan is not None else None
        if args.command == "explore":
            profile_path = Path(args.profile).expanduser()
            if args.root:
                _same_model_file(args.root, profile_path, "profile.json")
                if args.history:
                    _same_model_file(args.root, args.history, "recommendations.jsonl")
                if args.feedback:
                    _same_model_file(args.root, args.feedback, "feedback.jsonl")
            profile = _load(profile_path)
            feedback_path = Path(args.feedback).expanduser() if args.feedback else profile_path.with_name("feedback.jsonl")
            history_path = Path(args.history).expanduser() if args.history else profile_path.with_name("recommendations.jsonl")
            history = _load(history_path, True) if args.history else None
            if (args.root or profile.get("taste_hypotheses")) and history is None:
                history = _load(history_path, True) if history_path.exists() else []
            feedback = _load(feedback_path, True) if args.feedback else []
            if not args.feedback and feedback_path.exists():
                feedback = _load(feedback_path, True)
            graph_path = Path(args.graph).expanduser() if args.graph else None
            anchor_mappings, anchor_sync = None, None
            if args.root:
                default_graph = Path(args.root).expanduser() / "model/graph.json"
                if graph_path is None or graph_path.resolve() == default_graph.resolve():
                    helper = runpy.run_path(str(Path(__file__).resolve().with_name("graph_anchors.py")))
                    anchor_sync = helper["sync_anchors"](args.root)
                    anchor_mappings = helper["read_mappings"](args.root)
                    graph_path = default_graph if default_graph.exists() else None
            result = explore(plan, profile, history,
                             args.seed, args.count, graph=_load(graph_path) if graph_path else None,
                             feedback=feedback, maintenance=maintenance, anchor_mappings=anchor_mappings)
            if anchor_sync is not None:
                result["graph_anchors"] = anchor_sync
        elif args.command == "select":
            candidates = _load(args.candidates, True)
            graph_update = _graph_update_gate(plan, args.root, candidates, args.batch_id)
            history_path = Path(args.history).expanduser() if args.history else None
            if args.root:
                if history_path:
                    _same_model_file(args.root, history_path, "recommendations.jsonl")
                else:
                    default_history = Path(args.root).expanduser() / "model/recommendations.jsonl"
                    history_path = default_history if default_history.exists() else None
            result = select_slate(plan, candidates, args.count,
                                  _load(history_path, True) if history_path else None, args.seed, args.min_score,
                                  args.allow_creator_repeat, categories=args.category)
            if maintenance is not None:
                result["hypothesis_maintenance"] = maintenance
            if graph_update is not None:
                result["graph_update"] = graph_update
        else:
            result = audit_items(_load(args.items, True), _load(args.previous, True) if args.previous else None)
        print(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False))
        return 0
    except (OSError, ValueError, TypeError, KeyError) as error:
        parser.exit(2, "trurl diversity: " + str(error) + "\n")


if __name__ == "__main__":
    sys.exit(main())
