# State contract

Use UTF-8 JSON for the profile and one JSON object per line for the append-only ledgers. Unknown is `null`, `unknown`, or an empty evidence list as appropriate, not an invented estimate. Optional fields may be absent in imported history. Source IDs refer to records in `profile.provenance` or are fully described in the event itself.

Resolve the curation root with `curation.py root` before accessing these files. New local profiles use `~/Trurl/model` by default. `curation.py use --root <existing-root>` can remember another persistent root in the user's `~/.config/trurl/config.json` or absolute `XDG_CONFIG_HOME`. This registry stores the root path. It is separate from the model and the installed skill.

## Profile: `model/profile.json`

The top-level fields are:

| Field | Purpose |
| --- | --- |
| `schema_version` | Integer format version. |
| `person` | Minimal identity/display information distinguishing whose profile this is. |
| `updated_at` | ISO 8601 timestamp, with timezone. |
| `provenance` | Sources actually read, with ID, kind, title, locator/thread ID, inspected range, and captured date. |
| `interests` | Topic observations: `id`, `topic`, `kind` (`explicit`/`inferred`), `confidence` [0,1], `knowledge_level` (default `unknown`), `knowledge_evidence`, `source_provenance`, scope, and any supporting words. |
| `taste_hypotheses` | Optional proposed topics, styles or qualities linked to original user anchors. The [hypothesis workflow](taste-hypotheses.md) defines evidence references, lifecycle and managed interests. |
| `taste` | Persistent baseline `axes_weights`, `presentation`, and evidenced taste constraints. Batch-specific effective weights belong in the batch ledger. |
| `discovery` | `lane_mix` (`familiar`, `adjacent`, `distant`), preferably summing to 1; identify provisional defaults. |
| `media` | Enabled and disabled media, with reasons when uncertain. |
| `onboarding` | Category and anchor inputs, readiness, and separate decisions about agent memory and past chats. Optional in existing profiles. |
| `delivery` | `weekly`: `enabled`, `day`, `time`, `timezone`, `time_confirmed`, optional native automation ID, and optional `onboarding_default_pending`. |
| `controls` | Feedback-prompt preferences, evidence/learning controls, and user exclusions. |
| `coverage`, `pending_questions` | Optional inspected-history coverage and unresolved preferences; keep unknowns visible. |

The `taste.axes_weights` keys are `depth`, `novelty`, `relevance`, `surprise`, `perspective_change`, and `entertainment`, with nonnegative values summing to 1. Preserve explicit user baseline values. Effective weights can change radically for the current request without modifying these fields. A generic equal-weight fallback, if needed, must be labeled provisional. `taste.presentation` records the person's requested output shape, such as an author/title/link table, without imposing it on incompatible requests.

New generic profiles start with `delivery.weekly.enabled=false` and `onboarding_default_pending=true`. The pending flag applies only to first profile setup after notice and an opportunity to opt out. A missing flag preserves the existing profile's schedule and means automatic enrollment is unavailable. Set `enabled=true` only when the host confirms the native job is active. Clear the pending flag once first-time enrollment is resolved. Keep `time_confirmed=false` for a proposed time that the person has yet to confirm. Record the host's identifier for the confirmed job as `delivery.weekly.job_id`.

## Onboarding and context sources

The initializer creates `onboarding.status="not_started"`, empty `categories` and `anchors`, and separate `context_sources.agent_memory` and `context_sources.past_chats` records. Each source starts with `permission="not_asked"`, `scope=null`, `availability="unknown"`, and an empty `source_provenance` list. These fields record the curation workspace's source choices; they do not enable a platform feature or establish that a source was accessed.

| Field | Values and interpretation |
| --- | --- |
| `status` | `not_started`, `starter` (only format or incomplete context), or `ready` (a usable anchor is available). Readiness is not a claim of a complete or validated taste model. |
| `categories` | User-selected medium IDs: `book`, `podcast`, `film`, `youtube_video`, `lecture`, `scientific_paper`. A mix is multiple selections. Empty means no choice yet; generic enabled media are provisional defaults. |
| `anchors` | Any number of supplied anchor records with `id`, `kind`, `value`, `signal`, `scope`, and `source_provenance`. |
| Anchor `kind` | `topic`, `current_goal`, `work`, `creator`, `link`, or `constraint`. |
| Anchor `signal` | `interested`, `enjoyed`, `avoid`, `reference_only`, or `unknown`. Mentioning a title alone does not establish enjoyment. |
| Anchor `scope` | `current_request`, `persistent`, or `source_unspecified`. A current curiosity need not become a durable interest. |
| Source `permission` | `not_asked`, `allowed`, or `declined`. Preserve explicit limits and the source of the person's choice. Silence is not permission. |
| Source `scope` | Bounded text identifying permitted interests, projects, chats, dates, exclusions, and purpose, as applicable. |
| Source `availability` | `unknown`, `available`, `partial`, or `unavailable`, based on actual host capabilities or returned context. Permission does not imply availability. |
| Source `source_provenance` | IDs for the person's source choice and the memory or chat evidence actually inspected. Retain access gaps. |
| Source `offered_at` | Optional ISO 8601 timestamp for an offer actually made. An unanswered offer remains `not_asked` for permission and must not be repeatedly prompted. |

Use `media.enabled` for the person's selected recurring formats when that is their stated scope; keep a one-off format request in its batch. New generic profiles make all six categories available without treating any as a learned preference. A lecture also available on YouTube remains one canonical work, not two recommendations.

`onboarding.anchors` retains inputs and their meaning; use the existing `interests` and `taste` fields for supported lasting observations, and the current batch request for temporary goals. The discovery helper reads those interests and its retained request, not onboarding metadata alone. Preserve the actual anchor in those inputs so a ready profile can support later discovery without fabricated fit.

For memory-only evidence, record a provenance source such as `agent_memory_summary`, its available locator and inspected portion, capture time, and the limitation that underlying messages were not inspected. Keep the resulting observation inferred unless direct user evidence or a current confirmation supports an explicit preference. Preserve unknown original dates rather than inventing them. Do not count a memory and its underlying chat as independent corroboration of the same statement. Current explicit corrections govern.

Existing profiles remain valid without `onboarding`. Do not discard their observations, reset weights, force repeat onboarding, or treat missing permission fields as a new grant. Honor an earlier explicit authorization already present in the session or evidence. Record decisions when the workflow actually obtains them; updating the reusable skill must not change a real person's source settings.

## Derived curator's brief: `model/curators-brief.json`

The [brief workflow](curators-brief.md) defines a reusable, at-most-350-word summary of current authorized taste evidence. It is a private derived cache, never a second preference store or independent source. The host supplies `summary`, `source_refs` and `limits` using the helper's pre-draft snapshot. The helper stamps an independent version, current source fingerprints, cache lineage and a machine-derived `profile_interest_ids` inventory. Source references use private workspace-relative paths and JSON Pointers or one-based line locators. A missing or empty ledger stays explicit rather than implying a known preference.

Check freshness before using the summary. Profile/feedback corrections and changed or missing declared sources invalidate affected cached understanding. Current instructions and raw evidence govern; a request-only override belongs in its batch, not this enduring cache. Do not migrate an experimental brief's item quotas, frozen exclusions or temporary exploration request into a production brief. Preserve originals' explicit/tentative status and feedback scope.

Cache saves do not modify the profile, ledgers, request weights, seeds, source choices or scheduling. Retain only the active prose and content-free version/hash lineage by default. Invalidation makes the active summary unusable; forgetting additionally requires removal of affected evidence and dependent copies. Hash freshness and validated locators do not establish semantic accuracy, complete history coverage or permission to access a source.

## Hypothesis maintenance: optional `model/hypothesis-maintenance.json`

The [hypothesis workflow](taste-hypotheses.md) maintains one private completion record for the latest reviewed evidence. It records an outcome (`saved`, `reviewed` or `no_proposal`), a short reason, relevant hypothesis IDs, completion time and helper-derived evidence fingerprints. It is a workflow receipt, never preference evidence or a second profile. The helper compares current original anchors and their sources, meaningful feedback and its referenced works, the hypothesis pool, and used opportunities when that pool is low. Delivery affects opportunity tracking only; it supplies no enjoyment, confirmation or rejection.

Use the maintenance planner's returned review when completing work. A `saved` receipt requires an actual new or revised persisted hypothesis; a prompt to create one is insufficient. Preserve current or pending status honestly. A current receipt can be reused across unchanged requests, including an unchanged sparse pool or a no-proposal outcome. New broad, non-wildcard request plans carry `hypothesis_maintenance_required=true`. The `explore` and `select` CLIs require `--root` for those plans and reject a missing or stale completion record for an eligible profile. Their low-level read-only APIs and historical plans remain usable; bypassing maintenance there does not establish a completed workflow. Focused, wildcard and unanchored requests do not require this maintenance step.

The helper writes this file atomically under the profile lock and checks concurrent relevant evidence changes. Recording completion does not modify profile preferences, ledgers, weights, source permissions or scheduling, and does not itself invalidate the curator's brief. Keep only the latest receipt here; retain the compact checked result actually used in each delivered batch. When forgetting underlying personal evidence, remove affected receipt data, temporary review files and dependent copies in batch traces; retain only minimal content-free change metadata where needed.

## Content graph: optional `model/graph.json`

New models also contain an empty content graph. Existing models can continue without one. This file contains relationships among content and concepts; the personal profile and feedback remain the evidence about the person. A graph is private alongside the profile even when some of its sources are public. Use the [post-research graph update](knowledge-graph.md#save-verified-relationships-after-research) to merge supported changes and record completion. `graph-check` remains a read-only validator. Validation checks structure and supplied provenance, not the truth of a statement or permission to access a source.

The graph has `schema_version=1`, and `sources`, `nodes`, and `edges` arrays:

| Record | Fields |
| --- | --- |
| Source | Unique `id`, `kind`, `locator`, `checked_at`; optional title and limits. Unknown dates remain null. Verified edges need dated source evidence. Public fixtures use the explicit `synthetic_fixture` kind. |
| Node | Unique `id`, `type` (`topic`, `work`, `creator`, `quality`), `label`; optional `aliases` and `canonical_url`. |
| Edge | Unique `id`, `source`, `relation`, `target`, `status` (`verified`, `hypothesis`, `retracted`), finite `confidence` in [0,1], `source_provenance` source IDs, and `assertion_method`; optional creation/review dates. Graph updates require a concise `support_note` for new or changed verified edges. |

Relations and permitted endpoints are `about` and `in_genre` (work → topic), `created_by` (work → creator), `has_quality` (work → quality), and `broader_than` or `related_to` (topic → topic). Use `in_genre` for classification, such as a novel being science fiction, and `about` for subject matter. Personal liking, familiarity, exposure, consumption, and expertise are not world-graph edges. `related_to` is not transitive. Reverse traversal is a retrieval step, not an inverse assertion; a multi-step path must not be stored as a direct fact merely because it exists.

Only verified, sourced edges meeting the helper's factual-confidence threshold enter default retrieval. Keep hypotheses available for checking without using them as established routes. The threshold, two-hop default and neighbor bound are engineering heuristics. Graph degree describes this stored graph's coverage, not general popularity or preference strength. When retracting an assertion, exclude its paths; a request to forget private evidence requires removing its contents and dependent caches, with only a minimal content-free change record if needed.

An interest may carry `graph_node_id` to identify its evidenced anchor. Otherwise the helper matches its exact normalized topic label or alias. Inferred anchors need supporting source evidence; preserve their kind, scope and unknown knowledge. A creator, work, or quality anchor can use an explicit node mapping without inferring enjoyment of its neighbors. Keep an observation's evidence in the profile or feedback, not duplicated as a world fact. A direct new user interest does not need a path back to the old profile.

Retain each graph route's `anchor_id`, `anchor_evidence`, `destination`, `node_ids`, `edge_ids`, directed traversal `steps`, `hops`, and `evidence_confidence_min`. The latter describes asserted relationship support, not predicted enjoyment. Cache only what the batch needs and retain graph/edge versions or hashes for replay; regenerating routes after changing their sources does not reproduce the original run.

A route may additionally have one `converging_route` with `anchor_id`, `node_ids`, `edge_ids`, aligned `traversed_reverse` booleans and `evidence_confidence_min`. This compact alternate refers to the original profile and graph; it duplicates neither the destination nor personal evidence. At most two alternates appear per frontier. Optional `convergence_search` records output/work caps, expansion count and truncation. These are discovery annotations, not profile updates or scoring inputs.

`discovery.graph_max_hops` defaults to 2. `discovery.open_exploration.enabled` defaults to false. Enable standing open exploration only from an explicit scoped user choice, with its provenance, and honor a current request to stay close. A missing setting is not an opt-in. In ordinary personal plans an old provisional distant allocation is redistributed over familiar and adjacent research when no open permission exists; record that adjustment in the plan, not as a mutation of `taste.axes_weights` or the stored profile.

## Interest mappings: `model/graph-anchors.json`

This private derived file maps eligible persistent interest IDs to content node IDs, with an anchor fingerprint and a mapping method. Rooted exploration, graph-update planning and Atlas export synchronise it automatically. A changed or removed interest cannot reuse a stale binding. Explicit profile mappings remain supported; reviewed sidecar bindings allow creator/work identities without changing profile evidence or hypothesis fingerprints.

An unmatched interest receives an isolated topic node retaining its literal scope. Node presence records coverage, not a sourced relationship. The helper never creates edges, preferences or familiarity. It preserves existing graph facts and keeps corrected or ambiguous identities from silently acquiring old routes. Repeated unchanged syncs do not write files. Invalid graphs fail closed; the Atlas reports a sync limitation rather than inventing successful coverage.

Representation and sourced connectivity are separate metrics. The Atlas lists all eligible interests and shows which have verified routes to works within its hop and display limits. Recommendation reasoning and taste hypotheses remain separate from sourced routes.

## Graph completion: `model/graph-maintenance.json`

The graph update helper keeps the latest completion record separately from the graph and personal profile. It records the batch ID, research and graph fingerprints, an outcome (`saved` or `no_supported_changes`), bounded change counts/IDs, a short reason and completion time. These are workflow facts, never preference evidence. New request plans carry `graph_update_required=true`; the `select` CLI requires `--root`, `--batch-id` and a current record matching its candidate research. Discovery can run before this post-research step.

The update uses `model/.graph.lock`, checks concurrent changes, and saves the graph atomically before its receipt. A missing, stale or damaged completion cannot establish success; obtain a fresh review and complete it. Unchanged research and graph state reuse the current completion without another write. Keep the checked `graph_update` result in each delivered batch rather than duplicating the full graph there. The helper does not modify the taste profile, feedback, recommendation history, weights, permissions or scheduling. When forgetting evidence, remove affected sources, relationships, completion data and dependent copies, including temporary review/delta files.

## Batches: `model/batches.jsonl`

A `hypothesis_maintenance` record retains the compact result of the maintenance check for this batch, including its current completion receipt, inapplicable status, or an explicit pending/manual-fallback reason. Never turn a missing review into a successful completion. Its fingerprints support inspection; the original profile and feedback establish taste.

A `graph_update` record retains the compact checked post-research completion for the actual batch and candidate pool, or an explicit pending/manual-fallback reason. Keep it separate from the graph frontier used before research: later graph additions do not retroactively become that run’s retrieval evidence.

An optional `curators_brief` record identifies the working brief actually used: `version`, `file_sha256` and `status="fresh"`. With no usable cache, use `status="raw_model_fallback"` and a concrete `reason`. Retain version/hash metadata rather than an obsolete copy of the summary prose. The request plan below separately records the effective scoring and discovery policy; the brief does not generate or replace that plan.

Record the plan actually used for a delivered batch. Each record has `id` (matching recommendation `batch_id`), `created_at`, `context` (`on_demand`/`weekly`), `request`, `weight_plan` (the complete read-only planner output), and `recommendation_ids`. Preserve the planner's `baseline_weights`, `target_weights`, `effective_weights`, `mode_requested`, `mode`, `scope_requested`, `scope`, `trigger`, `variation_applied`, `seed`, `randomness`, and `constraints` without reconstructing them after scoring. The resolved `scope` is `broad` or `focused`; record the host's semantic decision rather than assuming the CLI understood every topic or constraint. `baseline_changed=false` confirms that planning alone did not mutate learned taste; `rotation_distance_l1` measures effective-weight departure from the baseline. Keep `uncertainty` and the plan's `schema_version` as returned. The constraints include the original request, the credibility gate, preservation of explicit constraints, and `weekly_delivery_enabled`; these are trace information, not a replacement for the scheduled-run guard.

Retain `policy_version` and `selection_policy` when present. `connected_surprise_v1` requires a minimum relevance score of 3/5, structured personal-connection evidence, no distant items, and an exploratory cap of floor(requested count × 0.25), with a minimum allowance of one for small collections. These are experimental design defaults. A historical `surprise` plan cannot bypass the current connected-surprise checks merely by omitting the new fields; exact historical reproduction requires the corresponding implementation revision.

`open_exploration_v1` retains the supplied personal baseline weights and permits a bounded independent component only under explicit open intent or standing authorization. For a broad four-item request, at most one distant open item and at most one adjacent item can be selected; the remaining items satisfy connected-fit rules. Explicit broad `mode="open"` reserves one qualified independent item, including for a one-item request without a prior anchor. A missing qualified open candidate leaves that slot unfilled. Selection output records `required_open_items`, `selected_open_items`, and `open_shortfall`; the overall `shortfall` includes any unfilled slot. Standing permission alone does not require an open item. Focused requests and current opt-outs suppress unrelated fields and the reservation. Record the actual selection channel and eligible pool; neither an LLM likelihood nor a subjective fit score is a randomized exposure probability.

Add `discovery_draw` with the distant-field seed, eligible fields, selected field, and any reroll reason, when used. Its seed is separate from weight variation. Store the exact eligible field list for replay. A manually supplied numeric-weight plan should identify its request-based origin and retain the same baseline/effective separation; do not claim the CLI parsed numbers it did not parse.

When the diversity helpers are used, also retain `discovery_plan` (the exact `explore` output), `selection_plan` (the exact `select` output), and `diversity_audit` for delivered items. Keep candidate IDs and their source/verification provenance in `candidate_pool`, separately from `recommendation_ids`. Record `generation_protocol` such as `direct`, `list_five`, `vs_style`, or `varied_briefs` so comparisons are possible. Model-reported generation likelihood may be preserved as an explicitly uncalibrated experimental annotation; it must never be read as user enjoyment, factual confidence, or a learned preference.

The weights planner does not create this record, send a brief, update a profile, or activate weekly delivery. The curation workflow appends a batch record when it delivers the selected recommendations. `curation.py record` appends it together with the delivered items, taking the plan, `select` output, checked receipts and brief status from the request's working folder; it records `generation_protocol="unspecified"` when none is given. Weekly scheduling has its own onboarding or explicit-request workflow. Imported historical items may reference an import batch without a reconstructable scoring plan; do not invent one.

## Recommendations: `model/recommendations.jsonl`

Each delivered item records:

| Field | Purpose |
| --- | --- |
| `id` | Stable unique recommendation ID. |
| `canonical_url` | Direct work/video/paper page; normalize tracking parameters and equivalent video URLs. |
| `title`, `creator`, `medium` | Work identity; medium normally `youtube_video`, `book`, `scientific_paper`, `film`, `podcast`, or `lecture`. |
| `status` | `recommended`, `seen`, `completed`, or `skipped`; change only with evidence. |
| `engagement`, `imported_at` | Optional explicit engagement state (default `unknown`) and historical-import date. |
| `batch_id`, `recommended_at` | Delivery group and timestamp; unknown original timestamps stay null. |
| `lane`, `topics` | Familiar/adjacent/distant placement and topic labels. |
| `rationale`, `relation_to_profile` | Why it was selected and what evidence connects it to the person. |
| `personal_connection` | Required for connected surprise: `basis`, actual `anchor`, and concrete `explanation`. Allowed bases: `explicit_interest`, `tentative_interest`, `current_request`, `first_impression_feedback`. Preserve uncertainty; do not infer a creator/topic preference from one item. |
| `graph_path`, `selection_channel` | Optional exact frontier route and channel (`established`, `connected`, `open`). A route explains retrieval, not a personal preference. |
| `personal_fit_status`, `value_rationale` | An independent open item uses `personal_fit_status="unknown"` and a concrete reason it is worth investigating. It needs no invented personal bridge. |
| `source_provenance` | Source IDs or explicit source locators showing where the recommendation appeared. |
| `scores`, `weighted_total` | Optional six-axis judgment and weighted sum, with missing values left null. |
| `release_date`, `duration_minutes` | Verified values, or null. |
| `verification` | `checked_at`, supporting `urls`, and `limitations`. |
| `source_family`, `discovery_domain` | Optional discovery provenance; do not invent labels to inflate coverage. |
| `random_seed` | For distant selections: integer seed, eligible field list, selected field, and any reroll reason. |

`curation.py record` writes these records from the `select` output for the items actually delivered. It assigns `id` as `<batch-id>.<candidate-id>`, keeps the original `candidate_id` and sets `weighted_total` only for six-axis scores.

Score anchors: 0 = absent or poor fit on that axis; 1 = low; 2 = modest; 3 = good; 4 = strong; 5 = exceptional. `novelty` measures evidence of newness to this person, not only a recent release. If familiarity is unknown, mark novelty uncertainty. Credibility is a separate gate, not another weighted axis. Compute `weighted_total = sum(effective_weight[axis] * score[axis])` only when all six scores are supplied; the result remains a subjective aid. Use the effective weights from this item's recorded batch plan, not a subsequently updated profile.

The broad-open selector permits `scores.relevance=null` only for its distant open candidates. It always renormalizes the other five effective weights for those items, ignoring any numeric relevance supplied by a legacy caller, and labels the item's `scoring_basis` as an open value score. This avoids making up a personal-relevance measurement; it does not establish enjoyment probability. If the remaining weight mass is zero, no value score can be supplied. All ordinary candidates still need complete subjective scores, and connected candidates retain the relevance floor and personal-connection record. A standing-authorized personal plan with a distant allocation retains this same open selection policy rather than bypassing its gates.

Recommended status is not an endorsement or a claim of consumption. Keep original delivery events append-only; derive current engagement status from subsequent feedback rather than rewriting what was delivered. A canonical work may have multiple delivery events for justified revisits; de-duplicate by work identity when selecting.

Selection-helper candidate inputs additionally use explicit `constraints_passed` and `credibility_passed` flags, verification metadata, and complete subjective scores. These flags are supplied by the researching host; the helper does not remotely verify them. Excluded or unselected candidates stay outside this delivered ledger. Diversity metrics need consistent creator/topic labels and missing-data counts; they do not establish preservation or loss of psychological distinctiveness.

## Feedback: `model/feedback.jsonl`

Each event has `id`, `recommendation_id` (nullable for general preferences), `recorded_at`, `signal`, `user_words`, `source_provenance`, and `profile_changes`.

Useful `signal` values include `useful`, `not_for_me`, `already_knew`, `want_more`, `want_less`, `completed`, and `skipped`. Retain more precise user wording rather than forcing ambiguous feedback into a like/dislike label. A completion signal alone should not change taste weights.

Hypothesis learning additionally recognises experienced enjoyment signals and the broader `confirmed_interest` and `rejected_interest` signals. Use the latter only when the actual words address that interest. Retain `hypothesis_id` on a delivered probe so later item feedback can be traced to its proposal.

Also preserve whether a signal is curiosity, first-impression willingness, experienced enjoyment, familiarity, or a temporary request. Record the exposure/batch and selection channel when available. One enjoyed work updates that work first; a broader topic/creator/quality preference needs direct wording or independent support. Repeated summaries of the same event are one source, not additional evidence. Illustrative, hypothetical, third-party, and assistant-generated statements never become explicit user preferences. Corrections may supersede interpretations without rewriting the historical delivery event.

`profile_changes` is an array of changes with `path`, `before`, `after`, `reason`, and `source_provenance`; use an empty array when no durable learning is justified. Preference scope may be an item, creator, topic, medium, presentation, or global axis. Record which scope the person's words support. `source_provenance` consistently accepts profile source IDs or full source locator objects, including thread/message IDs when importing past chats.

## Write discipline

Read the current state before modifying it. Preserve unrelated fields and unknown imported-history values. Validate JSON and weight ranges/sums, then replace the profile atomically using a temporary file in the same directory. Append recommendation and feedback events with unique IDs; do not duplicate an event during a retry. `curation.py record` and `curation.py feedback` do this under `model/.profile.lock`, and repeating either after an interrupted run adds nothing twice. When multiple sessions might write, use the workspace's existing locking mechanism or serialize updates rather than overwriting a newer profile. Do not rewrite evidence to make a hypothesis appear explicit.

The hypothesis helper uses `model/.profile.lock` while updating the profile and checks the profile and both ledgers against its snapshot. Other profile writers should cooperate with that lock. A changed source requires a fresh review and snapshot.
