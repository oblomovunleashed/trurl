#!/usr/bin/env python3
"""Trurl planning, discovery, and local installation. Python 3.9+, no dependencies.

This is a planner, not a recommendation search backend or scheduler. Intent
classification is deliberately small; an agent can pass a resolved --mode.
"""
import argparse
import fnmatch
import hashlib
import json
import math
import os
from pathlib import Path
import random
import runpy
import re
import secrets
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from urllib.parse import unquote, urlsplit
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

AXES = ("depth", "novelty", "relevance", "surprise", "perspective_change", "entertainment")
MODES = ("personal", "surprise", "deep", "playful", "perspective", "open", "wildcard")
PRESETS = {
    "surprise": dict(zip(AXES, (0.15, 0.20, 0.25, 0.25, 0.05, 0.10))),
    "deep": dict(zip(AXES, (0.45, 0.15, 0.15, 0.05, 0.15, 0.05))),
    "playful": dict(zip(AXES, (0.05, 0.15, 0.10, 0.15, 0.05, 0.50))),
    "perspective": dict(zip(AXES, (0.15, 0.15, 0.10, 0.15, 0.40, 0.05))),
    "wildcard": dict(zip(AXES, (0.10, 0.25, 0.05, 0.40, 0.15, 0.05))),
}
ROTATION_MODES = tuple(mode for mode in PRESETS if mode != "wildcard")
CONNECTED_SURPRISE_POLICY = {
    "kind": "connected_surprise_v1",
    "min_relevance_score": 3.0,
    "require_personal_connection": True,
    "max_exploratory_fraction": 0.25,
    "allow_distant": False,
}
OPEN_EXPLORATION_POLICY = {
    "kind": "open_exploration_v1",
    "min_relevance_score": 3.0,
    "require_personal_connection": True,
    "max_open_fraction": 0.25,
    "max_exploratory_fraction": 0.25,
    "allow_distant": True,
}
LANES = {
    "personal": {"familiar": 0.75, "adjacent": 0.25, "distant": 0.0},
    "surprise": {"familiar": 0.75, "adjacent": 0.25, "distant": 0.0},
    "deep": {"familiar": 0.70, "adjacent": 0.30, "distant": 0.0},
    "playful": {"familiar": 0.65, "adjacent": 0.35, "distant": 0.0},
    "perspective": {"familiar": 0.55, "adjacent": 0.45, "distant": 0.0},
    "open": {"familiar": 0.50, "adjacent": 0.25, "distant": 0.25},
    "wildcard": {"familiar": 0.05, "adjacent": 0.25, "distant": 0.70},
}
INSTALL_EXCLUSIONS = (
    "__pycache__", "*.pyc", "*.pyo", ".DS_Store", ".git", ".env", ".env.*",
    "model", "profile.json", "graph.json", "recommendations.jsonl", "feedback.jsonl", "batches.jsonl", "curators-brief.json",
    "graph-maintenance.json", "graph-anchors.json", "hypothesis-maintenance.json",
)
INSTALL_AGENTS = ("codex", "claude-code", "pi")
AGENT_HOME_VARIABLES = {"codex": "CODEX_HOME", "claude-code": "CLAUDE_CONFIG_DIR", "pi": "PI_CODING_AGENT_DIR"}
AGENT_COMMANDS = {"codex": "codex", "claude-code": "claude", "pi": "pi"}
FIXED_PATTERNS = (
    r"\b(?:do not|don't|dont|never)\s+(?:surprise|randomi[sz]e)\b",
    r"\b(?:do not|don't|dont|never)\s+(?:change|vary)\s+(?:my |the |these )?(?:weights|weighting)\b",
    r"\bnot\s+surprise\s+me\b",
    r"\bno\s+(?:surprises|randomness|randomization|randomisation|variation)\b",
    r"\bnot\s+(?:looking|asking)\s+for\s+surprises\b",
    r"\b(?:use|keep|stick (?:to|with))\s+(?:(?:my|the)\s+)?(?:normal|usual|fixed|baseline|standard|same|unchanged)\s+(?:weights|weighting|mix|priorities)\b",
    r"\b(?:fixed|same|unchanged)\s+(?:weights|weighting|mix|priorities)\b",
    r"\b(?:keep|leave)\s+(?:(?:my|the)\s+)?(?:weights|weighting|mix|priorities)\s+(?:the\s+)?(?:same|unchanged)\b",
)
INTENTS = (
    ("open", r"\btry (?:a |an )?new area\b|\bexplore (?:an? )?unfamiliar field\b|\bopen exploration\b"),
    ("wildcard", r"\bcompletely random\b|\bunrelated wildcards?\b|\b(?:take|push|send) me completely outside (?:my |the )?interests\b|\b(?:ignore|disregard) my interests\b"),
    ("surprise", r"\bsurprise me\b|\b(?:outside|beyond) (?:my |the )?comfort zone\b|\b(?:outside|beyond) (?:my |the )?(?:usual |normal )?interests\b|\bcomplete(?:ly)? surprise\b|\bbroaden my (?:world|horizons)\b"),
    ("deep", r"\b(?:go deep(?:er)?|deep dive|more advanced|advanced material|intellectually challenging|rigorous)\b"),
    ("playful", r"\b(?:make me laugh|entertain me|something funny|something fun|playful|lighthearted|light-hearted)\b"),
    ("perspective", r"\b(?:change my perspective|challenge my thinking|challenge my assumptions)\b"),
)
OPEN_NEGATIONS = (
    r"\b(?:no|not)\s+(?:open|distant|unrelated|independent)\s+(?:exploration|discoveries|draws|picks|items)\b",
    r"\b(?:do not|don't|dont|never)\s+(?:try (?:a |an )?new area|explore (?:an? )?unfamiliar field|(?:use|enable|include|add|give me) (?:open|distant|unrelated|independent) (?:exploration|discoveries|draws|picks|items))\b",
    r"\b(?:skip|avoid|exclude|disable)\s+(?:all\s+)?(?:open|distant|unrelated|independent)\s+(?:exploration|discoveries|draws|picks|items)\b",
    r"\b(?:stay|keep(?: it| this| the selection| the recommendations)?)\s+(?:close|near)\s+to\s+(?:my |the )?(?:(?:existing|current|usual|known|established)\s+)?interests\b",
    r"\b(?:stick|keep|stay)\s+(?:to|with|within)\s+(?:my |the )?(?:(?:existing|current|usual|known|established)\s+)?interests\b",
)
WILDCARD_NEGATIONS = (
    r"\b(?:not|never)\s+(?:an?\s+)?(?:something\s+)?completely random\b",
    r"\b(?:no|not)\s+(?:an?\s+)?unrelated wildcards?\b",
    r"\b(?:do not|don't|dont|never)\s+(?:ignore|disregard)\s+(?:my|the)\s+interests\b",
    r"\b(?:do not|don't|dont|never)\s+(?:take|push|send) me completely outside (?:my |the )?interests\b",
    r"\b(?:do not|don't|dont|never)\s+(?:give|show|choose)\s+(?:me\s+)?(?:something\s+)?completely random\b",
    r"\b(?:do not|don't|dont|never)\s+(?:give|show|choose)\s+(?:me\s+)?(?:an?\s+)?unrelated wildcards?\b",
)


def normalize_weights(values):
    """Validate a complete nonnegative finite six-axis mapping and normalize it."""
    if not isinstance(values, dict) or set(values) != set(AXES):
        raise ValueError("weights must contain exactly: " + ", ".join(AXES))
    result = {}
    for axis in AXES:
        value = values[axis]
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError("weight for %s must be a finite number" % axis)
        if not math.isfinite(value) or value < 0:
            raise ValueError("weight for %s must be finite and nonnegative" % axis)
        result[axis] = float(value)
    total = math.fsum(result.values())
    if not math.isfinite(total) or total <= 0:
        raise ValueError("weights must have a finite positive sum")
    return {axis: result[axis] / total for axis in AXES}


def distance(left, right):
    return math.fsum(abs(left[a] - right[a]) for a in AXES)


def _text(request):
    return " ".join(request.lower().replace("\u2019", "'").split())


def _wildcard_intent_text(text):
    """A fit-preserving negation blocks wildcard inference, not surprise."""
    return "" if any(re.search(pattern, text) for pattern in WILDCARD_NEGATIONS) else text


def _open_intent_text(text):
    return "" if any(re.search(pattern, text) for pattern in OPEN_NEGATIONS) else text


def _closes_open(request):
    """A current explicit opt-out overrides standing permission for one batch."""
    text = _text(request)
    return any(re.search(pattern, text) for pattern in OPEN_NEGATIONS)


def _factual_request(text):
    # Conservative guard, not full natural-language understanding. Resolved agent
    # modes and --fixed are the reliable controls for more complex instructions.
    return bool(re.search(
        r"\b(?:fact[- ]?check|verify|calculate|summari[sz]e|explain|what is|what are|how does|research question)\b",
        text,
    ))


def _resolve_scope(request, context, requested_scope):
    """Conservative lexical fallback; an agent can supply semantic scope.

    Unrecognized language is focused. A small known broad vocabulary prevents a
    generic phrase followed by an unrecognized named subject from rotating.
    """
    if requested_scope != "auto":
        return requested_scope
    text = _text(request)
    if not text:
        return "broad" if context == "weekly" else "focused"
    if _factual_request(text) or re.search(
        r"\b(?:about|on|regarding|specifically|only|exactly|under|within|less than|at most)\b|\b\d+\s*(?:minutes?|mins?|hours?|hrs?)\b",
        text,
    ):
        return "focused"
    if re.fullmatch(r"(?:please\s+|can you\s+|could you\s+)?(?:surprise me|something outside my (?:usual|normal) interests)[.!]?", text):
        return "broad"
    if any(intent == "wildcard" and re.search(pattern, _wildcard_intent_text(text))
           for intent, pattern in INTENTS):
        return "broad"
    if any(intent == "open" and re.search(pattern, _open_intent_text(text))
           for intent, pattern in INTENTS):
        return "broad"
    broad_signal = re.search(
        r"\b(?:recommendations|selection|curation|ideas|discoveries|idea stimulation|things worth (?:my |the )?time|something interesting)\b|\b(?:a few|some|several) (?:videos|books|papers|films)\b",
        text,
    )
    vocabulary = set((
        "a an few some several recommendations recommendation selection curation ideas idea discoveries "
        "stimulation things worth my the time something interesting new worthwhile personal weekly sunday "
        "week this weeks for me please give show pick prepare make suggest recommend curate can could you "
        "i want would like to see explore discover anything broad mix different topics fields across "
        "disciplines of and videos books papers films"
    ).split())
    words = set(re.findall(r"[a-z]+", text))
    return "broad" if broad_signal and words <= vocabulary else "focused"


def _requested_mode(request, requested_mode, fixed, allow_intent=True):
    text = _text(request)
    if fixed:
        return "personal", "fixed_flag", False
    if requested_mode != "auto":
        if requested_mode in {"open", "wildcard"} and _closes_open(request):
            return "personal", "current_request_closes_open", False
        return requested_mode, "explicit_mode", False
    if any(re.search(pattern, text) for pattern in FIXED_PATTERNS):
        return "personal", "fixed_request", False
    if _factual_request(text):
        return "personal", "constrained_factual_request", False
    if allow_intent:
        for intent, pattern in INTENTS:
            if intent in {"open", "wildcard"} and _closes_open(request):
                continue
            candidate_text = (_wildcard_intent_text(text) if intent == "wildcard" else
                              _open_intent_text(text) if intent == "open" else text)
            if re.search(pattern, candidate_text):
                return intent, "request_intent:" + intent, False
    if _closes_open(request):
        return "personal", "current_request_closes_open", False
    return "personal", "personal_default", True


def _vary(target, rng, mode):
    # A convex mixture gives predictable floors while gamma draws supply real
    # variability. We do not call subjective quality a probability distribution.
    samples = {a: rng.gammavariate(max(target[a] * 36.0, 0.1), 1.0) for a in AXES}
    samples = normalize_weights(samples)
    result = {a: 0.8 * target[a] + 0.2 * samples[a] for a in AXES}
    if mode == "wildcard" and result["relevance"] > 0.08:
        old = result["relevance"]
        result["relevance"] = 0.08
        factor = (1.0 - 0.08) / (1.0 - old)
        for axis in AXES:
            if axis != "relevance":
                result[axis] *= factor
    return normalize_weights(result)


def make_plan(profile, request="", context="on_demand", mode="auto", seed=None,
              fixed=False, repeat_count=0, scope="auto"):
    """Return a replayable batch plan; never modify profile or any file.

    repeat_count counts prior consecutive broad on-demand requests. A host agent
    derives it from the batch ledger. At two prior broad requests, rotate.
    """
    if context not in ("on_demand", "weekly"):
        raise ValueError("context must be on_demand or weekly")
    if mode not in ("auto",) + MODES:
        raise ValueError("unknown mode: %s" % mode)
    if scope not in ("auto", "broad", "focused"):
        raise ValueError("scope must be auto, broad, or focused")
    if isinstance(repeat_count, bool) or not isinstance(repeat_count, int) or repeat_count < 0:
        raise ValueError("repeat_count must be a nonnegative integer")
    if not isinstance(request, str):
        raise ValueError("request must be text")
    if seed is not None and (isinstance(seed, bool) or not isinstance(seed, int)):
        raise ValueError("seed must be an integer")
    try:
        baseline = normalize_weights(profile["taste"]["axes_weights"])
    except (KeyError, TypeError) as exc:
        raise ValueError("profile needs taste.axes_weights") from exc

    policy = profile.get("taste", {}).get("weighting_policy", {})
    chosen, trigger, eligible = _requested_mode(
        request, mode, fixed, policy.get("request_intent_overrides", True)
    )
    resolved_scope = _resolve_scope(request, context, scope)
    if chosen == "open" and scope == "auto" and not request.strip():
        resolved_scope = "broad"
    allowed_contexts = policy.get("variation_contexts", ["weekly_broad", "repeated_broad_on_demand"])
    rotation = eligible and resolved_scope == "broad" and (
        (context == "weekly" and "weekly_broad" in allowed_contexts)
        or (context == "on_demand" and repeat_count >= 2 and "repeated_broad_on_demand" in allowed_contexts)
    )
    if policy.get("mode") == "fixed" and trigger == "personal_default":
        rotation = False
        trigger = "profile_fixed_policy"
    rng = None
    actual_seed = None
    if chosen not in {"personal", "open"} or rotation:
        actual_seed = secrets.randbits(64) if seed is None else seed
        rng = random.Random(actual_seed)
    if rotation:
        candidates = [m for m in ROTATION_MODES if distance(baseline, PRESETS[m]) >= 0.35]
        chosen = rng.choice(candidates or list(ROTATION_MODES))
        trigger = "weekly_broad_rotation" if context == "weekly" else "repeated_broad_rotation"
    target = dict(baseline if chosen in {"personal", "open"} else PRESETS[chosen])
    effective = dict(baseline) if chosen in {"personal", "open"} else _vary(target, rng, chosen)
    if rotation and distance(baseline, effective) < 0.15:
        # Rare close draws must not turn eligible rotation into cosmetic jitter.
        chosen = max(ROTATION_MODES, key=lambda m: distance(baseline, PRESETS[m]))
        target = dict(PRESETS[chosen])
        effective = _vary(target, rng, chosen)
    lane_mix = dict(LANES[chosen])
    warnings = []
    request_closes_open = _closes_open(request)
    standing_open = profile.get("discovery", {}).get("open_exploration", {}).get("enabled") is True and not request_closes_open
    if request_closes_open:
        warnings.append("This request keeps independent exploration disabled for this batch; any stored open-exploration permission is unchanged.")
    if chosen == "personal":
        supplied = profile.get("discovery", {}).get("lane_mix")
        if supplied is not None:
            if (not isinstance(supplied, dict) or set(supplied) != {"familiar", "adjacent", "distant"}
                    or any(isinstance(v, bool) or not isinstance(v, (int, float))
                           or not math.isfinite(v) or v < 0 for v in supplied.values())
                    or not math.isclose(math.fsum(supplied.values()), 1.0)):
                raise ValueError("discovery.lane_mix must be three nonnegative finite values summing to 1")
            lane_mix = dict(supplied)
            if lane_mix["distant"] and not standing_open:
                connected_total = lane_mix["familiar"] + lane_mix["adjacent"]
                lane_mix = ({"familiar": lane_mix["familiar"] / connected_total,
                             "adjacent": lane_mix["adjacent"] / connected_total, "distant": 0.0}
                            if connected_total else dict(LANES["personal"]))
                warnings.append("Stored distant research allocation requires explicit open-exploration opt-in; this batch reallocates it across connected lanes without changing the profile.")
    applied = chosen not in {"personal", "open"}
    open_selection = chosen == "open" or (chosen == "personal" and standing_open and lane_mix["distant"] > 0)
    return {
        "schema_version": 1,
        "policy_version": ("connected_surprise_v1" if chosen == "surprise" else
                           "open_exploration_v1" if open_selection else
                           "explicit_wildcard_v1" if chosen == "wildcard" else "standard_v1"),
        "mode_requested": mode,
        "mode": chosen,
        "trigger": trigger,
        "context": context,
        "scope_requested": scope,
        "scope": resolved_scope,
        "hypothesis_maintenance_required": resolved_scope == "broad" and chosen != "wildcard",
        "graph_update_required": True,
        "seed": actual_seed,
        "baseline_weights": baseline,
        "target_weights": target,
        "effective_weights": effective,
        "lane_mix": lane_mix,
        "selection_policy": (dict(CONNECTED_SURPRISE_POLICY) if chosen == "surprise" else
                             dict(OPEN_EXPLORATION_POLICY) if open_selection else None),
        "variation_applied": applied,
        "baseline_changed": False,
        "rotation_distance_l1": distance(baseline, effective),
        "constraints": {
            "request": request,
            "credibility_gate": True,
            "preserve_explicit_constraints": True,
            "open_exploration_enabled": standing_open,
            "open_exploration_disabled_for_request": request_closes_open,
            "graph_max_hops": profile.get("discovery", {}).get("graph_max_hops", 2),
            "weekly_delivery_enabled": bool(profile.get("delivery", {}).get("weekly", {}).get("enabled", False)),
        },
        "randomness": {
            "applied": applied,
            "seed": actual_seed,
            "method": ("80% mode target + 20% gamma-normalized draw; connected surprise retains relevance and surprise at least 20%, novelty at least 16%"
                       if chosen == "surprise" else
                       "80% mode target + 20% gamma-normalized draw; explicit wildcard relevance capped at 8%"
                       if chosen == "wildcard" else
                       "80% mode target + 20% gamma-normalized draw" if applied else "none"),
            "strength": 0.2 if applied else 0.0,
        },
        "warnings": warnings,
        "uncertainty": [
            "Weights are selection priorities, not measured probabilities or guarantees of enjoyment.",
            "Intent parsing is heuristic; the host agent must preserve medium, time, safety, and other explicit constraints.",
            "Planning does not research recommendations, update preferences, or authorize scheduled delivery.",
        ] + warnings,
    }


def generic_profile(name="You", local_timezone=None):
    if local_timezone is not None:
        try:
            ZoneInfo(local_timezone)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise ValueError("timezone must be a valid IANA timezone") from exc
    return {
        "schema_version": 1,
        "person": {"id": "local-user", "display_name": name},
        "updated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "provenance": [],
        "coverage": {"scope": "No past conversations reviewed; new provisional profile."},
        "onboarding": {
            "status": "not_started",
            "categories": [],
            "anchors": [],
            "context_sources": {
                source: {"permission": "not_asked", "scope": None,
                         "availability": "unknown", "source_provenance": []}
                for source in ("agent_memory", "past_chats")
            },
        },
        "interests": [],
        "taste": {
            "axes_weights": {a: 1.0 / len(AXES) for a in AXES},
            "weights_status": "provisional_equal_weight_default",
            "weighting_policy": {
                "mode": "adaptive",
                "request_intent_overrides": True,
                "variation_contexts": ["weekly_broad", "repeated_broad_on_demand"],
                "preserve_baseline": True,
            },
            "quality_gate": {"credibility_required": True},
            "pure_entertainment_allowed": True,
            "presentation": {"default": "author_title_link_table", "kind": "design_default"},
            "constraints": [],
        },
        "discovery": {"lane_mix": dict(LANES["personal"]), "kind": "design_default_not_user_preference",
                      "graph_max_hops": 2, "open_exploration": {"enabled": False}},
        "media": {"enabled": ["youtube_video", "book", "scientific_paper", "film", "podcast", "lecture"], "music_enabled": False},
        "delivery": {"default_mode": "on_demand", "weekly": {
            "enabled": False, "onboarding_default_pending": True, "day": "sunday", "time": "20:00",
            "time_confirmed": False, "timezone": local_timezone,
            "requires_timezone": local_timezone is None,
        }},
        "controls": {"silence_is_feedback": False, "knowledge_default": "unknown", "feedback_prompt": "optional", "cross_user_isolation": True},
    }


def initialize(root, name="You", local_timezone=None):
    destination = Path(root).expanduser() / "model"
    paths = [destination / "profile.json", destination / "graph.json"] + [destination / (n + ".jsonl") for n in ("recommendations", "feedback", "batches")]
    if any(p.exists() for p in paths):
        raise ValueError("refusing to overwrite an existing model file")
    profile = generic_profile(name, local_timezone)
    destination.mkdir(parents=True, exist_ok=True)
    created = []
    try:
        for path in paths:
            with path.open("x", encoding="utf-8") as handle:
                created.append(path)
                if path.name == "profile.json":
                    json.dump(profile, handle, ensure_ascii=False, indent=2, allow_nan=False)
                    handle.write("\n")
                elif path.name == "graph.json":
                    json.dump({"schema_version": 1, "sources": [], "nodes": [], "edges": []}, handle, indent=2)
                    handle.write("\n")
    except BaseException:
        for path in created:
            path.unlink(missing_ok=True)
        raise
    return {"initialized": str(destination.resolve()), "weekly_enabled": False, "files": [p.name for p in paths]}


def _install_path(value, user_home, environ):
    raw = os.fspath(value)
    if raw == "~" or raw.startswith("~/"):
        raw = str(user_home) + raw[1:]
    raw = re.sub(r"\$(\w+)|\$\{([^}]+)\}", lambda match: environ.get(match.group(1) or match.group(2), match.group(0)), raw)
    return Path(os.path.abspath(raw))


def resolve_install_targets(agent="codex", home=None, destination=None, environ=None):
    """Resolve targets without I/O or mutation.

    Explicit home selects isolated defaults and ignores ambient agent-home
    variables. An explicit environ mapping can test or select native overrides.
    CODEX_HOME/skills remains an explicit legacy override; the normal Codex
    user-scope default is ~/.agents/skills. PI_CODING_AGENT_DIR selects the
    agent directory itself (normally ~/.pi/agent), not its parent.
    """
    if agent not in INSTALL_AGENTS + ("all",):
        raise ValueError("unknown agent: %s" % agent)
    if destination is not None and agent == "all":
        raise ValueError("--destination is ambiguous for --agent all; select one agent")
    env = dict(os.environ if environ is None else environ)
    user_home = (Path(home).expanduser() if home is not None else
                 Path(env["HOME"]).expanduser() if environ is not None and env.get("HOME") else Path.home())
    user_home = Path(os.path.abspath(user_home))
    native_env = {} if home is not None and environ is None else env
    defaults = {"codex": user_home / ".agents", "claude-code": user_home / ".claude",
                "pi": user_home / ".pi" / "agent"}
    targets = []
    for host in INSTALL_AGENTS if agent == "all" else (agent,):
        variable = AGENT_HOME_VARIABLES[host]
        override = native_env.get(variable)
        if destination is not None:
            path, path_source = _install_path(destination, user_home, env), "destination"
        else:
            # Pi's native override expands a leading tilde, not literal $VAR
            # text. Preserve its path exactly; other hosts keep their existing
            # installer expansion behavior.
            base = _install_path(override, user_home, {} if host == "pi" else env) if override else defaults[host]
            path = base / "skills" / "trurl"
            path_source = variable + (" (legacy)" if host == "codex" else "") if override else "user_default"
        targets.append({"agent": host, "path": str(path), "path_source": path_source})
    return targets


def _install_source(source):
    source = Path(source or Path(__file__).resolve().parents[1]).expanduser()
    if source.is_symlink():
        raise ValueError("refusing to install from a symlink source")
    source = source.resolve()
    if not (source / "SKILL.md").is_file():
        raise ValueError("skill source needs SKILL.md")
    for path in source.rglob("*"):
        relative = path.relative_to(source)
        excluded = any(fnmatch.fnmatch(part, pattern) for part in relative.parts for pattern in INSTALL_EXCLUSIONS)
        if path.is_symlink() and not excluded:
            raise ValueError("refusing to install a symlink payload: " + str(relative))
    return source


def _fingerprint(folder):
    """Hash a skill folder's installable files; private state and caches are ignored."""
    digest = hashlib.sha256()
    for path in sorted(folder.rglob("*")):
        relative = path.relative_to(folder)
        if any(fnmatch.fnmatch(part, pattern) for part in relative.parts for pattern in INSTALL_EXCLUSIONS):
            continue
        if path.is_file() and not path.is_symlink():
            digest.update(relative.as_posix().encode("utf-8") + b"\0" + hashlib.sha256(path.read_bytes()).digest())
    return digest.hexdigest()


def _replaceable(target):
    """Only a plain Trurl skill folder without private files may be replaced by an update."""
    if not target.is_dir():
        raise ValueError("cannot update: the existing path is not a folder: " + str(target))
    files = list(target.rglob("*"))
    if any(path.is_symlink() for path in files):
        raise ValueError("cannot update: the existing installation contains a symlink: " + str(target))
    try:
        front = (target / "SKILL.md").read_text(encoding="utf-8").split("---", 2)[1]
    except (OSError, UnicodeError, IndexError):
        front = ""
    if not re.search(r"^name:\s*['\"]?trurl['\"]?\s*$", front, re.MULTILINE):
        raise ValueError("cannot update: the existing folder is not a Trurl skill: " + str(target))
    private = sorted(str(path.relative_to(target)) for path in files if path.is_file() and any(
        fnmatch.fnmatch(part, pattern) for part in path.relative_to(target).parts
        for pattern in INSTALL_EXCLUSIONS if pattern not in ("__pycache__", "*.pyc", "*.pyo", ".DS_Store")))
    if private:
        raise ValueError("cannot update: move private files out of the installed skill first: " + ", ".join(private[:5]))


def install_skill(destination=None, source=None, agent="codex", home=None, environ=None, update=False):
    """Install reviewed copies after preflighting every target; replace an existing copy only when asked."""
    source = _install_source(source)
    targets = resolve_install_targets(agent, home, destination, environ)
    prepared = []
    for record in targets:
        target = Path(record["path"])
        if target.is_symlink():
            raise ValueError("refusing to install through a symlink destination")
        target = target.resolve()
        if target == source or source in target.parents:
            raise ValueError("installation destination must be outside the source skill")
        action = "installed"
        if target.exists():
            if not update:
                raise FileExistsError("installation already exists; review the changes, then rerun with --update "
                                      "to replace it: " + str(target))
            _replaceable(target)
            action = "current" if _fingerprint(target) == _fingerprint(source) else "updated"
        for parent in target.parents:
            if parent.exists() and not parent.is_dir():
                raise ValueError("installation parent is not a directory: " + str(parent))
        if any(target == other or target in other.parents or other in target.parents for _, other in prepared):
            raise ValueError("agent installation targets must be distinct and must not overlap")
        prepared.append((dict(record, action=action), target))
    created, parents, replaced = [], [], []
    try:
        for record, target in prepared:
            if record["action"] == "current":
                continue
            if record["action"] == "updated":
                # Stage beside the target, then swap. The previous copy leaves the
                # skills folder so a host never sees two skills named trurl.
                staged = Path(tempfile.mkdtemp(prefix=".trurl-update-", dir=str(target.parent)))
                try:
                    shutil.copytree(source, staged / "trurl", ignore=shutil.ignore_patterns(*INSTALL_EXCLUSIONS))
                    backup = Path(tempfile.mkdtemp(prefix="trurl-previous-")) / "trurl"
                    shutil.move(str(target), str(backup))
                    replaced.append((target, backup))
                    os.replace(str(staged / "trurl"), str(target))
                finally:
                    shutil.rmtree(staged, ignore_errors=True)
                record["previous_copy"] = str(backup)
                continue
            missing = []
            parent = target.parent
            while not parent.exists():
                missing.append(parent)
                parent = parent.parent
            target.parent.mkdir(parents=True, exist_ok=True)
            parents.extend(reversed(missing))
            target.mkdir()  # Atomic refusal if another process created it after preflight.
            created.append(target)
            shutil.copytree(source, target, dirs_exist_ok=True, ignore=shutil.ignore_patterns(*INSTALL_EXCLUSIONS))
    except BaseException:
        for target in reversed(created):
            shutil.rmtree(target)
        for target, backup in reversed(replaced):
            if target.exists():
                shutil.rmtree(target)
            shutil.move(str(backup), str(target))
        for parent in reversed(parents):
            try:
                parent.rmdir()
            except OSError:
                pass
        raise
    installations = [dict(record, installed=str(target), path=str(target), personal_model_copied=False)
                     for record, target in prepared]
    if agent != "all":
        return dict(installations[0], skill="trurl")
    return {"skill": "trurl", "agent": "all", "installations": installations, "personal_model_copied": False}


def _bundle_checks(folder):
    checks = {"folder": folder.is_dir() and not folder.is_symlink(), "manifest": False,
              "bundled_references": False, "runtime_files": False, "private_state_absent": False,
              "python": sys.version_info >= (3, 9), "runtime_smoke": False}
    errors = []
    if not checks["folder"]:
        return checks, ["Skill folder is missing or is a symlink."]
    files = list(folder.rglob("*"))
    if any(path.is_symlink() for path in files):
        return checks, ["Installed bundle contains a symlink; no bundled files were executed."]
    private_names = {"model", "profile.json", "graph.json", "recommendations.jsonl", "feedback.jsonl", "batches.jsonl",
                     "curators-brief.json", "taste-atlas.html", "graph-maintenance.json", "graph-anchors.json", "hypothesis-maintenance.json"}
    checks["private_state_absent"] = not any(path.name in private_names or path.name == ".env" or path.name.startswith(".env.") for path in files)
    if not checks["private_state_absent"]:
        errors.append("Private-state files are present inside the installed skill.")
    manifest = folder / "SKILL.md"
    try:
        text = manifest.read_text(encoding="utf-8")
        parts = text.split("---", 2)
        front = parts[1] if text.startswith("---\n") and len(parts) == 3 else ""
        name = re.search(r"^name:\s*['\"]?trurl['\"]?\s*$", front, re.MULTILINE)
        description = re.search(r"^description:\s*\S.+$", front, re.MULTILINE)
        checks["manifest"] = bool(name and description)
    except (OSError, UnicodeError):
        pass
    if not checks["manifest"]:
        errors.append("SKILL.md needs trurl name and a nonempty description in frontmatter.")
    missing = []
    for markdown in [path for path in files if path.is_file() and path.suffix == ".md"]:
        try:
            for value in re.findall(r"\[[^\]]*\]\(([^)]+)\)", markdown.read_text(encoding="utf-8")):
                value = value.strip().strip("<>")
                parsed = urlsplit(value)
                if parsed.scheme or parsed.netloc or value.startswith("#"):
                    continue
                linked = (markdown.parent / unquote(parsed.path)).resolve()
                if folder.resolve() not in linked.parents or not linked.is_file():
                    missing.append(str(markdown.relative_to(folder)) + ": " + value)
        except (OSError, UnicodeError, ValueError) as exc:
            missing.append(str(markdown.relative_to(folder)) + ": " + str(exc))
    checks["bundled_references"] = not missing
    errors.extend("Missing or external bundled reference " + value for value in missing)
    runtime_files = ("scripts/curation.py", "scripts/diversity.py", "scripts/graph.py", "scripts/graph_updates.py", "scripts/graph_anchors.py", "scripts/brief.py", "scripts/hypotheses.py", "scripts/location.py",
                     "scripts/sunday.py", "scripts/atlas.py", "scripts/context.py", "scripts/workflow.py", "references/domains.json")
    try:
        for relative in runtime_files:
            path = folder / relative
            data = path.read_bytes()
            if path.suffix == ".py":
                compile(data, str(path), "exec")
            else:
                registry = json.loads(data)
                if not isinstance(registry, dict) or not isinstance(registry.get("domains"), list) or not registry["domains"]:
                    raise ValueError("domains.json needs a nonempty domains array")
        atlas_template = (folder / "assets" / "taste-atlas-template.html").read_text(encoding="utf-8")
        if atlas_template.count("__TRURL_ATLAS_DATA__") != 1:
            raise ValueError("taste-atlas-template.html needs one atlas data placeholder")
        checks["runtime_files"] = True
    except (OSError, ValueError, SyntaxError, TypeError) as exc:
        errors.append("Bundled runtime check failed: " + str(exc))
    if all(checks[key] for key in ("manifest", "bundled_references", "runtime_files", "private_state_absent", "python")):
        try:
            result = subprocess.run([sys.executable, str(folder / "scripts/curation.py"), "demo", "--fixed"],
                                    cwd=str(folder), capture_output=True, text=True, timeout=15,
                                    env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1"))
            output = json.loads(result.stdout) if result.returncode == 0 else {}
            checks["runtime_smoke"] = result.returncode == 0 and output.get("baseline_changed") is False and output.get("mode") == "personal"
        except (OSError, ValueError, subprocess.TimeoutExpired):
            pass
        if not checks["runtime_smoke"]:
            errors.append("Installed Python demo failed; no agent CLI or model was invoked.")
    return checks, errors


def doctor(agent="all", home=None, root=None, destination=None, environ=None):
    """Read-only bundle/runtime diagnostics; CLI presence is not a host test."""
    hosts = []
    source = Path(__file__).resolve().parents[1]
    source_print = _fingerprint(source)
    for target in resolve_install_targets(agent, home, destination, environ):
        folder = Path(target["path"])
        checks, errors = _bundle_checks(folder)
        command = AGENT_COMMANDS[target["agent"]]
        executable = shutil.which(command, path=(environ or {}).get("PATH"))
        installed_print = _fingerprint(folder) if checks["folder"] else None
        # An installed copy cannot be compared with itself; run doctor from the
        # downloaded repository to learn whether an installation is behind it.
        current = None if installed_print is None or folder.resolve() == source else installed_print == source_print
        hosts.append(dict(target, ok=all(checks.values()), checks=checks, errors=errors,
                          cli={"command": command, "available": executable is not None, "path": executable},
                          bundle_sha256=installed_print,
                          update={"compared_with": str(source), "current": current},
                          full_host_tested=False))
    # An explicit root must hold a model. Otherwise report the location a session
    # would resolve, which may not have a model before first use.
    explicit = root is not None and str(root) != ""
    if explicit:
        location, origin = Path(root).expanduser().resolve(), "explicit"
    else:
        resolver = runpy.run_path(str(Path(__file__).resolve().with_name("location.py")))
        resolved = resolver["resolve_root"](None, environ=environ, home=home)
        location, origin = Path(resolved["root"]), resolved["source"]
    root_check = {"path": str(location), "source": origin, "exists": location.is_dir(),
                  "profile_present": (location / "model/profile.json").is_file(),
                  "graph_present": (location / "model/graph.json").is_file(),
                  "ledgers_present": {name: (location / "model" / (name + ".jsonl")).is_file()
                                      for name in ("recommendations", "feedback", "batches")},
                  "contents_read": False, "changed": False}
    return {"schema_version": 1, "command": "doctor", "agent_requested": agent,
            "ok": all(host["ok"] for host in hosts) and (not explicit or root_check["profile_present"]),
            "python": {"executable": sys.executable, "version": sys.version.split()[0], "supported": sys.version_info >= (3, 9)},
            "hosts": hosts, "root": root_check, "changed": False,
            "limits": ["Local bundle and Python smoke checks do not establish agent discovery, authentication, tool access, or full host behavior.",
                       "CLI availability only reports an executable on PATH; no host CLI or model was launched."]}


def format_demo_table(plan):
    """Show the actual seeded demo plan without exposing implementation JSON."""
    labels = {
        "depth": "Intellectual depth", "novelty": "Novelty and discovery",
        "relevance": "Personal relevance", "surprise": "Surprise and connections",
        "perspective_change": "Perspective change", "entertainment": "Entertainment",
    }
    lines = [
        "Trurl - synthetic planner demo",
        "Mode: {mode} | Scope: {scope} | Seed: {seed}".format(**plan),
        "",
        "{:<27} {:>9} {:>13}".format("Selection priority", "Baseline", "This request"),
        "-" * 51,
    ]
    for axis in AXES:
        lines.append("{:<27} {:>8.1f}% {:>12.1f}%".format(
            labels[axis], 100 * plan["baseline_weights"][axis], 100 * plan["effective_weights"][axis]))
    lines.extend([
        "",
        "Discovery mix: " + ", ".join("{} {:.0f}%".format(lane, 100 * value) for lane, value in plan["lane_mix"].items()),
        "Learned baseline: unchanged.",
        "Weights are subjective priorities. A host agent researches the recommendations.",
    ])
    return "\n".join(lines)


def _profile_path(args):
    if args.profile:
        return Path(args.profile).expanduser()
    helper = runpy.run_path(str(Path(__file__).resolve().with_name("location.py")))
    return Path(helper["resolve_root"](args.root)["profile_path"])


def _common(parser):
    parser.add_argument("--request", default="")
    parser.add_argument("--context", choices=("on_demand", "weekly"), default="on_demand")
    parser.add_argument("--mode", choices=("auto",) + MODES, default="auto")
    parser.add_argument("--scope", choices=("auto", "broad", "focused"), default="auto", help="semantic request scope; auto only rotates clearly broad requests")
    parser.add_argument("--seed", type=int)
    parser.add_argument("--fixed", action="store_true", help="use supplied profile baseline unchanged; no preset or randomness")
    parser.add_argument("--repeat-count", type=int, default=0, help="prior consecutive broad on-demand requests")


def main(argv=None):
    argv = sys.argv[1:] if argv is None else list(argv)
    if argv and argv[0] in {"root", "use"}:
        helper = runpy.run_path(str(Path(__file__).resolve().with_name("location.py")))
        return helper["main"](argv)
    if argv and argv[0] in {"start", "record", "feedback"}:
        helper = runpy.run_path(str(Path(__file__).resolve().with_name("workflow.py")))
        return helper["main"](argv)
    if argv and argv[0] in {"explore", "select", "audit"}:
        helper = runpy.run_path(str(Path(__file__).resolve().with_name("diversity.py")))
        return helper["main"](argv)
    if argv and argv[0] in {"graph-check", "frontier"}:
        helper = runpy.run_path(str(Path(__file__).resolve().with_name("graph.py")))
        return helper["main"](argv)
    if argv and argv[0] == "graph-sync":
        helper = runpy.run_path(str(Path(__file__).resolve().with_name("graph_anchors.py")))
        return helper["main"](argv[1:])
    if argv and argv[0] in {"graph-update-plan", "graph-update", "graph-update-check"}:
        helper = runpy.run_path(str(Path(__file__).resolve().with_name("graph_updates.py")))
        return helper["main"](argv)
    if argv and argv[0] == "sunday":
        helper = runpy.run_path(str(Path(__file__).resolve().with_name("sunday.py")))
        return helper["main"](argv[1:])
    if argv and argv[0] == "atlas":
        helper = runpy.run_path(str(Path(__file__).resolve().with_name("atlas.py")))
        return helper["main"](argv[1:])
    if argv and argv[0] == "hypotheses":
        helper = runpy.run_path(str(Path(__file__).resolve().with_name("hypotheses.py")))
        return helper["main"](argv[1:])
    parser = argparse.ArgumentParser(
        prog="trurl",
        description=__doc__,
        epilog="Request loop: start, graph-update, select, record, feedback. Model location: root, use. Discovery tools: explore, select, audit. Graph tools: graph-sync, graph-check, frontier, graph-update-plan, graph-update, graph-update-check. Taste learning: hypotheses. Sunday edition: sunday render. Private taste map: atlas. Run each command with --help for inputs.",
    )
    commands = parser.add_subparsers(dest="command", required=True)
    weights = commands.add_parser("weights", help="print a read-only request-specific weight plan")
    source = weights.add_mutually_exclusive_group()
    source.add_argument("--root")
    source.add_argument("--profile")
    _common(weights)
    init = commands.add_parser("init", help="create a generic private model; refuses to overwrite")
    init.add_argument("--root", help="private curation root; defaults to the resolved location or ~/Trurl")
    init.add_argument("--name", default="You")
    init.add_argument("--timezone", help="IANA timezone for a future Sunday schedule")
    install = commands.add_parser("install", help="install for one or all supported agents; replaces an existing copy only with --update")
    install.add_argument("--agent", choices=INSTALL_AGENTS + ("all",), default="codex")
    install.add_argument("--home", help="use isolated user defaults beneath this directory; ignore ambient agent-home overrides")
    install.add_argument("--destination", help="exact skill directory for one agent; incompatible with --agent all")
    install.add_argument("--update", action="store_true",
                         help="replace an existing installation with this version; the previous copy moves to a temporary backup")
    diagnostic = commands.add_parser("doctor", help="read-only installed bundle/Python checks; CLI presence is reported separately")
    diagnostic.add_argument("--agent", choices=INSTALL_AGENTS + ("all",), default="all")
    diagnostic.add_argument("--home", help="use isolated user defaults beneath this directory; ignore ambient agent-home overrides")
    diagnostic.add_argument("--destination", help="exact installed skill directory for one agent")
    diagnostic.add_argument("--root", help="curation root that must hold a model; defaults to reporting the resolved location. Presence only: personal contents are not read")
    demo = commands.add_parser("demo", help="plan with a synthetic profile; never read private files")
    _common(demo)
    demo.add_argument("--format", choices=("json", "table"), default="json", help="show the raw plan or a concise priority comparison")
    demo.set_defaults(request="surprise me")
    args = parser.parse_args(argv)
    try:
        if args.command == "init":
            helper = runpy.run_path(str(Path(__file__).resolve().with_name("location.py")))
            location = helper["resolve_root"](args.root)
            if location["source"] == "registered" and not location["profile_exists"]:
                raise ValueError("the remembered model is unavailable at " + location["profile_path"]
                                 + "; restore access or pass --root explicitly to create a different model")
            output = initialize(location["root"], args.name, args.timezone)
        elif args.command == "install":
            output = install_skill(args.destination, agent=args.agent, home=args.home, update=args.update)
        elif args.command == "doctor":
            output = doctor(args.agent, args.home, args.root, args.destination)
        else:
            if args.command == "demo":
                profile = generic_profile("Demo reader")
                # Fictional illustrative baseline shared by public demo assets.
                profile["taste"]["axes_weights"] = dict(zip(AXES, (0.20, 0.20, 0.15, 0.20, 0.10, 0.15)))
            else:
                path = _profile_path(args)
                if not path.is_file():
                    raise ValueError("no taste model at {}; create one with `init`, or pass --root or --profile".format(path))
                with path.open(encoding="utf-8") as handle:
                    profile = json.load(handle)
            output = make_plan(profile, args.request, args.context, args.mode, args.seed, args.fixed, args.repeat_count, args.scope)
        if args.command == "demo" and args.format == "table":
            print(format_demo_table(output))
        else:
            print(json.dumps(output, ensure_ascii=False, indent=2, allow_nan=False))
        return 1 if args.command == "doctor" and not output["ok"] else 0
    except (ValueError, OSError, TypeError) as exc:
        parser.exit(2, "trurl: %s\n" % exc)


if __name__ == "__main__":
    sys.exit(main())
