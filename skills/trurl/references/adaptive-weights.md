# Adaptive scoring weights

Separate a person's learned taste from what they want on this occasion. `taste.axes_weights` is the persistent baseline. Each batch gets its own effective scoring plan, and all candidate scores in that batch use that plan.

## Generate the plan

`curation.py start` makes this plan as part of its one call and saves it as `plan.json`. To make it alone, use the bundled runtime with the profile path and the actual request:

```sh
python3 scripts/curation.py weights --profile /path/to/model/profile.json --request "surprise me" --context on_demand --mode surprise --scope broad
```

Create exactly one plan before candidate research. Use its `lane_mix` to allocate familiar, adjacent, and distant search effort, then reuse its `effective_weights` to score the resulting candidates. Retain and log this original output; generating another random plan at scoring time would break the connection between search and selection.

Run this from the skill directory or resolve the script relative to `SKILL.md`, using an absolute profile path. The command is read-only. Modes are `auto`, `personal`, `surprise`, `deep`, `playful`, `perspective`, and explicitly requested `open` or `wildcard`; scope is `auto`, `broad`, or `focused`. Keep the complete plan for replay. Repeat-triggered variation can start after two prior comparable broad requests. `--fixed` preserves the supplied baseline, disabling preset changes and variation; `--mode personal` also uses the baseline. Check that weekly delivery is active before a scheduled run. For an edition requested in chat, use `on_demand`.

## Let intent change the objective

The host agent should interpret intent from the current request, then pass the intended mode and scope. A person should not need to know the internal mode names or weight keys. The runtime's lexical `auto` classifier recognizes common phrases, but it cannot replace the host's understanding of subjects, negation, or constraints. For example:

| Request | Effective objective |
| --- | --- |
| “Surprise me” / “Something outside my usual interests” | Seek an unexpected connection with a clear reason it fits this person. |
| “Try a new area” / “Explore an unfamiliar field” | Use a bounded independent exploration component with personal fit unknown; preserve baseline weights. |
| “Give me a completely unrelated wildcard” | Use distant exploration explicitly, preserving credibility and requested constraints. |
| “Go deep” / “Something rigorous” | Increase intellectual depth while preserving credible evidence. |
| “Something fun” / “Just entertain me” | Increase entertainment; no educational justification is required. |
| “Challenge my thinking” / “Change my perspective” | Increase perspective change and unexpected connections. |
| “Use my usual mix” | Use the personal baseline. |

Classify scope separately from intent. A request for papers about a named subject, a specific topic, or a tightly bounded duration is focused: pass `--scope focused` to suppress unrequested exploration-mode rotation. A general invitation to find interesting material across fields is broad. `--scope auto` is conservative and treats unrecognized or constrained wording as focused. Explicit `--scope broad` should reflect the person's actual invitation to explore, not be used merely to trigger variation.

An explicit mode overrides automatic inference, except that `--fixed` always preserves the supplied baseline. The CLI does not parse custom numeric weights from prose. When the person supplies exact weights, construct and log a temporary request plan with those values after valid normalization, or invoke the planner on an ephemeral profile containing them with `--fixed`. Preserve the real learned baseline separately and do not save the supplied values there unless persistence was requested. Do not randomize explicit numbers. A narrow subject, requested medium, language, duration, or exclusion remains a constraint in every mode. “Surprise me with a short film” does not authorize a book, an hour-long video, or an irrelevant low-quality recommendation.

The connected-surprise target retains personal relevance:

| Axis | Weight |
| --- | ---: |
| Depth | 0.15 |
| Novelty | 0.20 |
| Relevance | 0.25 |
| Surprise | 0.25 |
| Perspective change | 0.05 |
| Entertainment | 0.10 |

This is an experimental request preset, not learned taste or a validated optimum. Its 75/25/0 search mix favors established-interest directions with a limited adjacent component. Each selected item still needs relevance at least 3/5 and a concrete personal bridge; high novelty cannot compensate for failing that check. For four items, at most one can be adjacent. A single-item request may return one connected adjacent work. `wildcard` retains the separate distant-exploration objective and requires explicit invocation.

`open` is a different request policy: its target and effective weights equal the supplied baseline, with a 50/25/25 familiar/adjacent/distant research mix. For a broad four-item selection it reserves one qualified independent open item and permits at most one adjacent item. If no open candidate qualifies, report its unfilled slot; standing permission alone does not reserve a slot. The open item's unknown relevance is excluded from its value score, with the other five weights renormalized; connected items retain the personal-fit floor. A focused request or current opt-out suppresses unrelated draws and the reservation. These are engineering defaults, not paper-derived optima. A fixed instruction still takes precedence over mode intent.

Ordinary personal defaults use 75/25/0. Other ordinary modes also omit distant draws by default. An old provisional personal mix with distant mass does not itself authorize open exploration: absent an explicit standing `discovery.open_exploration.enabled` choice, the planner reallocates that mass across familiar/adjacent directions and records the adjustment in its output without changing stored weights or profile fields. An explicit standing choice is scoped and correctable; it is not a subscription.

## Vary eligible broad batches

In `auto` with broad scope, active Sunday delivery and repeated broad on-demand requests can vary their emphasis. Automatic selection excludes `open` and `wildcard`, including fallback paths. Explicit non-baseline presets can use bounded variation while preserving their selection policy; open mode preserves the baseline and varies discovery through a separate seed. Randomness may change priorities and research approaches, never waive personal-fit, credibility, or request constraints.

Suppress unrequested mode rotation for factual research and focused requests. Explicitly fixed weights are never randomized. A deliberate “surprise me with a short film” request can still use the surprise target and bounded variation while preserving the film and time constraints. Credibility and explicit constraints never become random variables. A selected intent such as surprise should still dominate after any permitted variation; randomization must not accidentally turn it into a standard relevance-led selection.

Record the actual seed, baseline and effective weights, target, mode, scope, trigger, randomness, `policy_version`, and `selection_policy` in the batch. Connected-surprise variation retains relevance and surprise at least 0.20 and novelty at least 0.16. Candidate relevance scores and connection evidence are separate from these weight floors. Replay requires the same inputs and implementation, not just a seed. Historical plans retain their original meaning and code revision; current `surprise` semantics should not be represented as an unchanged replay of the earlier distant-exploration policy.

## Learn independently

The planner never learns from its own mode choice. A surprise request is temporary unless the person says it should become their default. Feedback can update the persistent baseline using the evidence and scope rules in `SKILL.md`, independently of the last batch's effective plan. Keep before/after values and source evidence so a later change can be explained or corrected.
