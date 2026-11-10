# Trurl workspace

For personal recommendations, idea stimulation, taste-model updates, or curation feedback, read `skills/trurl/SKILL.md` and use this workspace as the curation root.

The persistent Personal Intellectual & Taste Model is `model/profile.json`. Recommendation history and feedback are separate JSONL ledgers in `model/`. Preserve their provenance and the difference between an explicit preference and a tentative observation.

Use `model/curators-brief.json` as a derived working summary, checking it with the bundled brief helper before reading its prose. Refresh stale or missing briefs from authorized evidence; keep the full profile's interest inventory and raw feedback authoritative. The reusable taste brief is separate from each request's weights, seeds, constraints and research directions.

Start a request with `skills/trurl/scripts/curation.py start --request "<request>"`. One call resolves the root, checks freshness, makes the retained plan and returns the complete interest index, current settings and research briefs without dumping ledgers; `context.py prepare --root <curation-root>` returns the context alone. After delivery, `curation.py record` appends the delivered items and batch trace, and `curation.py feedback` appends a reaction in the person's words. Fetch original records selectively when interpreting evidence; local discovery helpers still check full history.

Use the taste-hypothesis workflow for plausible new preferences. Store proposals separately in the profile, retain original anchors and scoped feedback, and reconcile evidence with the bundled helper before reading the brief. The Taste Atlas visualises these records and never supplies recommendation evidence.

For a new profile, use category-and-anchor onboarding from the skill. Let the person provide as much context as they want. Offer relevant agent memory separately from past-chat review, honor existing source choices, and record actual availability without assuming access.

Use the bundled planner for request-specific scoring weights. Intent such as “surprise me” can change effective weights substantially; broad weekly or repeated open-ended requests can use seeded variation. Keep the learned baseline separate from each batch plan, and honor fixed-weight requests.

Broaden candidates before ranking them. Use the diversity helper for external exploration draws, eligible slate selection, and descriptive coverage audits when appropriate. Keep model-reported generation likelihood separate from user preference and factual confidence. Preserve unusual explicit interests without inferring sensitive identity traits.

For graph-based discovery, read the skill's knowledge-graph reference. Keep sourced content relationships separate from personal preference and familiarity evidence; graph reachability and illustrative examples never establish user taste. New explicit interests can become independent anchors. Open exploration needs an explicit request or standing opt-in; a skill update alone does not enable it for this person's model.

On-demand curation works independently. New onboarding defaults to weekly Sunday delivery on a supported host after disclosing the schedule and how to skip it. Preserve existing profiles' delivery choices. Inspect the profile and native automation before changing its status, and record activation only after the native scheduler confirms it.

Keep `model/` private. Build a publishable copy with `python3 scripts/package_release.py`; its public-file manifest excludes personal state. Verify changes with `python3 -m unittest discover -s tests -v`.
