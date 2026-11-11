---
name: trurl
license: MIT
description: Curate personally relevant books, podcasts, films, videos, lectures, and papers using a persistent intellectual and taste model, recommendation history, explicit feedback, and deliberate serendipity. Use for personal recommendations, on-demand idea stimulation, and Sunday editions on request or through weekly delivery.
---

# Trurl

Curate from the person's persistent taste model, verified research and current request. Keep hypotheses tentative and learn from actual reactions. Sunday editions and the private Taste Atlas are optional views of this workflow.

## Start with compact current context

Supports Codex, Claude Code and Pi. Resolve scripts/references relative to this skill directory, independently of the working directory. Helpers use Python 3.9+; the host supplies research, file access, optional memory and scheduling. Read [host capabilities](references/host-compatibility.md) for setup or missing tools.

1. Run `python3 <skill-directory>/scripts/curation.py start --request "<request>"`, explicitly resolving `--mode`/`--scope`, with `--root` for a supplied path. One call resolves the root, reconciles existing hypotheses, checks brief freshness and makes the **one** retained request plan. It returns settings, **every interest**, hypothesis IDs, ledger metadata, a `batch_id` and, when no hypothesis review is due, the research briefs, and saves `plan.json` in a private working folder. Reuse that root, plan, batch ID and folder throughout. It does not dump raw ledgers or author preferences. `no_model` means setup; restore access to a missing remembered model before creating another. The single steps remain: `curation.py root`, `context.py prepare --root <root>`, `curation.py weights` and `explore`.
2. Use only a `fresh` brief. For missing/stale/invalid briefs, read [brief maintenance](references/curators-brief.md) and review current authorized sources before refreshing; never reuse old prose. Fetch originals needed to interpret an anchor, feedback or hypothesis with `context.py records --root <root> --kind interest --id <id>` (also `hypothesis`, `provenance`, `feedback`, `recommendation`, `batch`). Explicit pages use `--offset`/`--limit`; inspect all relevant evidence, without loading entire history by default.

The index preserves quiet interests; it is not evidence by itself. Python discovery/selection reads full ledgers for evidence checks and duplicate avoidance. Current instructions and corrections govern. If helpers/storage are unavailable, use current raw evidence and record concrete fallback limits, never successful maintenance or stale-cache use.

For a new/empty model or requested setup, read [onboarding](references/onboarding.md). Accept one category/anchor or an unrestricted brain dump; offer useful starter picks without inventing personal fit. Keep the model in persistent private storage. Offer memory separately from past-chat review, honor recorded choices, and record permission versus actual availability. A skill installation grants neither source access nor scheduling.

## Review changed profile evidence

After saving original interests during onboarding or a profile update, run `curation.py hypotheses maintenance-plan --root <root> --event onboarding`. After recording meaningful sourced feedback, use `--event feedback`. Consume a due review in the same invocation before the first or next picks, including a single or focused recommendation; do not wait for an interest-count threshold or another user request. Read [hypotheses](references/taste-hypotheses.md), inspect the original anchors and competing explanations, save at most one defensible tentative proposal, and `maintenance-complete` the returned review. A reasoned `reviewed` or `no_proposal` outcome is valid; create no quota-filling hypothesis. The agent authors the interpretation; Python checks the evidence and completion.

If `start` already returned a due review, finish that review. Keep the retained request plan, scope, count and seeds. Profile maintenance does not broaden a focused request or turn an independent wildcard pick into a hypothesis test.

## Evidence rules

- Separate explicit interests, inferred observations, tentative hypotheses, familiarity, consumption and enjoyment. Knowledge defaults to unknown. Suggestions, graph paths, clicks, completion and silence establish no taste.
- Preserve provenance, scope, contradictions and the full interest inventory. New explicit interests can stand independently. Examples, third-party quotations and assistant interpretations are not user statements. Infer no sensitive identity traits.
- Temporary mood, constraints, seeds and effective weights belong to this request. Preserve learned baseline weights, source choices and existing delivery settings.
- `record` and `feedback` write ledger entries. Read [the state contract](references/state-contract.md) before writing/importing other state; keep `model/` private and serialize writes. Only delivered items become recommendations.

## Curate a selection

1. Honor medium, count, time, language, depth, exclusions and presentation. The plan from `start` is the **one** retained request plan. Use [adaptive weights](references/adaptive-weights.md) for intent, fixed weights or variation. Reuse the same seed, mix and effective weights throughout; planning never changes the baseline.
2. When profile evidence or eligible broad discovery needs review, `start` returns `maintenance_due` and a saved review. Finish it before research, then continue with the same retained plan. Recheck context after profile changes. Keep its checked receipt; unchanged evidence reuses current completion. One pick can still be broad: count and subject scope are separate. Delivery is an opportunity used, never enjoyment.
3. Read [diverse discovery](references/diverse-discovery.md) for a new selection. Use the briefs from `start`, or rooted `explore` with the retained plan after a due review, before proposing candidates. Broaden approaches/sources and give quieter evidenced interests opportunities. Read original selected anchors before assessing fit. Connected surprise needs a concrete personal bridge; unrelated `open`/`wildcard` exploration needs explicit request or scoped standing permission. Never force weak material into a variety quota.
4. Research a broader pool than the final slate. Verify exact title, creator, direct URL, medium, availability and current/technical claims through appropriate original sources. Credibility and request constraints are gates; pure entertainment needs no educational excuse. Keep generation likelihood, factual confidence and taste judgments separate.
5. Complete [the post-research graph update](references/knowledge-graph.md#save-verified-relationships-after-research) for the exact candidates and batch ID in one call: `curation.py graph-update --root <root> --research <candidates.json> --batch-id <batch-id> --reason <text>`, adding `--delta` for supported changes; without one it records `no_supported_changes`. A current completion is reused. Graph facts never become preferences. Read the graph reference when inspecting routes or relationships.
6. Score and run rooted `select` using the same plan/batch ID and full local history, saving its output as `selection.json` in the working folder. Require current hypothesis/graph completion where applicable; check identity, constraints, duplicates, fit and useful variety. Report shortfalls rather than weakening gates. After delivering, run `curation.py record --workdir <working-folder>`, with `--deliver <candidate-id>` per item when only some were delivered. It appends the delivered items and a batch trace holding the exact plan, brief version/hash or fallback, candidate provenance and checked receipts, enough to explain the actual run.

## Present the picks

Lead with linked titles, creators, useful verified details and one plain descriptive sentence. Honor the person's requested layout or `taste.presentation`. Keep scores, modes, selection reasons and discarded leads private unless asked. State material shortfalls or method limits; otherwise end after the picks. Read [visual identity](references/visual-identity.md) only for designed exports.

## Feedback, editions and Atlas

For volunteered feedback/corrections/forgetting, read [feedback](references/feedback.md). Append the person's words with `curation.py feedback --signal <signal> --words "<their words>"`, adding `--recommendation-id <id>` for a reaction to one pick; scope changes to what the words support and reconcile hypotheses/briefs. Ask for feedback only within a requested or enabled workflow.

For an on-demand or scheduled issue, read [Sunday editions](references/sunday-edition.md). Select one verified work per chosen category and render the linked edition; report unfilled categories.

For “show my taste atlas”, run `python3 <skill-directory>/scripts/atlas.py --root <root>` and open/link its private HTML. Export synchronizes anchor representation without inventing relationships or taste. Atlas illustrations and current routes never supply recommendation evidence.

## Weekly Sunday delivery

Read [weekly delivery](references/weekly-delivery.md) only during genuine new-profile setup, a scheduling request or a scheduled run. Preserve existing choices; inspect native jobs before changes and record activation only after host confirmation. **Every scheduled run must stop before research or delivery when the current profile has weekly delivery disabled;** `start --context weekly` then returns `weekly_delivery_disabled`.
