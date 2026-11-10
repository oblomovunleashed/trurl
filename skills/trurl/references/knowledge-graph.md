# Sourced connections and open exploration

Read this reference when using a graph for discovery, adding an interest, or learning from reactions. The graph helps retrieve possible connections; the person supplies the evidence about their taste and familiarity. See the bundled [state contract](state-contract.md) for the authoritative JSON fields. Resolve `model/` beneath the person's curation root, independently of this skill's installation directory.

## Keep three kinds of information separate

| Information | Home and meaning |
| --- | --- |
| World relationships | Optional private `model/graph.json`: sourced relationships among works, topics, creators, and qualities. A relationship does not describe the person. |
| Personal preference evidence | `profile.interests`, profile provenance, and the feedback ledger: what the person stated, a bounded current goal, or an explicitly tentative observation from an authorized source. |
| Familiarity | `knowledge_level` and `knowledge_evidence`, plus item feedback: what the person actually reports knowing. Interest, graph proximity, recommendations, clicks, or sophisticated questions do not establish knowledge. |

The graph cannot contain user `likes`, `knows`, or `viewed` edges. Do not put personal evidence into a reusable public graph or example. Keep the entire live `model/` private even if individual graph facts are public.

Use [taste hypotheses](taste-hypotheses.md) to explore what a person's stated interests might imply. Keep proposed preferences in `profile.taste_hypotheses`, each linked to original user evidence. The content graph supplies relationships to verify, while feedback can strengthen or correct the proposed taste inference.

## Add interests directly

Accept an independently stated interest without requiring a bridge to earlier interests. Preserve its actual words, provenance, and scope. A new lasting interest becomes its own discovery anchor; a temporary curiosity stays with the current request. Do not distort a new interest to fit the existing graph.

Rooted `explore`, `graph-update`, `graph-update-plan` and Atlas export synchronise persistent, evidenced interests automatically. The helper reuses an explicit `graph_node_id`, a current reviewed binding, or a unique exact normalized topic label/alias. Otherwise it creates an isolated topic with the interest's literal scope. Every eligible interest can be represented before a connection has been researched. No edges, likes, familiarity or new interests are inferred.

Private `model/graph-anchors.json` binds interest IDs and evidence fingerprints to node IDs without editing the profile. An interest correction invalidates its old binding. For a reviewed creator or work identity, use `curation.py graph-sync --root <curation-root> --bindings <bindings.json>` with an array of `{"anchor_id": "interest-id", "node_id": "existing-node-id"}`. This is an identity mapping, not a sourced relationship. Preserve narrow scope; do not match a podcast to its host's entire career or tea preparation to all tea history.

Research missing routes directly and retain coverage gaps in the private trace. Do not use fuzzy resemblance as evidence of fit or aliases to force a broader subject to match. Unchanged syncs perform no writes; the helper returns compact counts. The graph and mappings stay on disk, with no extra model call or background job.

Illustrative examples, quoted third-party preferences, assistant suggestions, and hypothetical profiles are not the person's preferences. Preserve `reference_only` meaning where appropriate; do not promote a mentioned work into an enjoyed work. Authorized memory summaries remain provisional unless underlying or current user evidence confirms them. Memory and past-chat permissions remain separate.

## Use the graph as a bounded research aid

The schema has `sources`, `nodes`, and `edges`. Nodes are `topic`, `work`, `creator`, or `quality`. The supported directed relations are `about`, `in_genre`, `created_by`, `has_quality`, `broader_than`, and `related_to`; see the state contract for signatures and required provenance. An edge records its status, confidence, assertion method, and source IDs. A dated source is required for a verified edge. Clearly fictional public fixtures use `synthetic_fixture` sources.

Only verified, sourced edges with confidence at least 0.5 are traversed. This threshold is an engineering heuristic, not a calibrated truth probability. Validation checks structure and provenance requirements; it cannot establish semantic truth or check a source remotely.

Use the default two-hop bound, or a requested bound from one to three, with bounded neighbors. Respect an immediate correction to the requested hop limit; persist a discovery default only when its lasting scope is stated. Retain the returned node/edge IDs, direction, anchor evidence, minimum edge confidence, and limitations. Reverse traversal is a retrieval operation, not an assertion that the relation reverses.

Review the actual route before claiming a useful connection. Several weak analogies do not become a strong personal bridge. Do not assert transitive `related_to`, infer an interest in every neighbor, or claim that the graph proves a causal explanation for enjoyment. The minimum edge confidence is a path annotation, not an enjoyment estimate. Cycles, repeated destinations, and high-degree hubs must not crowd out other anchors.

The frontier can attach one compact `converging_route` from a different anchor/node to at most two selected destinations. It retains anchor, node and edge IDs, traversal directions and that path's minimum edge confidence. Read the alternate anchor from the profile and its sources from the graph. A separate seeded search uses the same hop/neighbor bounds and at most 64 node expansions; `convergence_search.truncated` reports incomplete search. Primary destinations, ordering and open draws stay unchanged. Shared sources or broad hubs are not independent corroboration, and convergence adds no preference-confidence or relevance bonus.

The read-only `frontier` helper performs no networking, source verification, graph writes, or preference learning. Its output is a research frontier, not a verified recommendation list. The separate update workflow below saves relationships after the host has researched them. Research proposed works and enforce the retained plan's normal source, fit, count, duration, language, and exclusion checks before delivery.

## Save verified relationships after research

Complete this step after researching candidates and before selecting the batch. Hypothesis maintenance happens before research; graph maintenance uses the content evidence found during it. An empty or missing graph is a starting point, not a reason to skip the update.

Keep the candidate research in a private JSON array or JSONL file. Retain each work’s identity and `verification.urls` and `verification.checked_at` from sources actually read. Use the batch ID from `start`, or choose one once.

When the research supports relationships, inspect only relevant existing records and prepare a small delta with `schema_version=1` and `sources`, `nodes` and `edges` arrays. Each update accepts at most **8 sources, 24 nodes and 24 edges**; exceeding a bound fails rather than silently truncating it. Prefer useful relationships from the current research over filling a quota.

Sources need an HTTP(S) `locator` present in the current candidates’ `verification.urls` and a dated `checked_at`. New or changed verified edges need valid `source_provenance` and a concise `support_note` of at most 500 characters explaining what the cited source establishes. A work’s relationship must cite sources verified for that same work. Use the schema’s content relations, such as a work being about a subject or created by a person. Do not copy a candidate’s personal rationale or tentative taste hypothesis into the graph. A work about tea production is not automatically about gongfu brewing; a shared broad label does not verify a relation.

```sh
python3 <skill-directory>/scripts/curation.py graph-update --root <curation-root> --research <candidates.json> --batch-id <batch-id> --delta <private-delta.json> --reason "Saved the supported relationships from this research."
```

This one call takes the review and completes it. A current completion for unchanged research and graph state is reused. To see what is due without completing it, `graph-update-plan` with the same `--batch-id` returns fingerprints and counts rather than the full graph or candidate prose; its saved output can be passed as `--review` in place of `--batch-id`.

The helper merges supported changes into `model/graph.json`, preserving unrelated records and deduplicating canonical source/work URLs, matching node identities and matching edges. Reuse stable IDs. Conflicting identities require review; do not retarget an old ID or reactivate a retracted claim through a fresh alias. The helper validates supplied evidence and structure but does not browse or prove the host’s interpretation.

It records `saved` only when the graph changed. If no supported change is warranted, omit `--delta` and give a concrete reason; the outcome is `no_supported_changes`. Both outcomes create a private completion record in `model/graph-maintenance.json`, bound to the batch, research and graph fingerprints. Changed input or a damaged completion record requires a fresh review. The graph is saved before its completion record, so an interrupted write cannot claim unfinished work succeeded.

```sh
python3 <skill-directory>/scripts/curation.py graph-update-check --root <curation-root> --research <candidates.json> --batch-id <batch-id>
```

The check exits nonzero while completion is missing or stale. Newly generated request plans require this check at `select`, which takes `--root` and the same `--batch-id` and uses the actual candidate input. Rooted `explore` synchronises anchor representation and may run before sourced-relationship maintenance; its pure discovery API remains read-only. Retain the compact checked result in the batch; keep the research and delta privately for inspection. Facts from unselected researched works may be retained, but those works do not enter recommendation history.

This step reuses current research, requires no separate model call or background job, and changes no taste, familiarity, source permissions or delivery settings. If the helper or storage is unavailable, record a pending update and the actual limitation before using an honest manual fallback. Keep an invalid graph out of retrieval rather than replacing it with an empty one. On a forgetting request, remove affected graph evidence, completion data, temporary drafts and dependent trace copies.

## Choose the exploration permission correctly

“Surprise me” and “outside my usual interests” retain connected surprise: use evidenced anchors and concrete bridges. Neither statement alone authorizes unrelated exploration. Missing graph coverage does not authorize an unrelated fallback.

An explicit request to try a new area or explore an unfamiliar field uses `open` mode. A recorded standing opt-in in `discovery.open_exploration.enabled` can also authorize the open lane. `open` and `wildcard` are never selected by automatic rotation or fallback. Fixed-weight instructions take precedence; retain the planner's resulting policy.

For explicit open mode, keep the learned weights unchanged and use the retained 50/25/25 familiar/adjacent/distant research mix. The open allowance is at most one per four requested items, rounded down with one allowed for small collections; the adjacent allowance is separately capped. A broad explicit `open` request reserves one qualified open item, including for a one-item request. This keeps familiar candidates from crowding exploration out during ranking. If none qualifies, leave that slot unfilled and report the open shortfall. Standing permission alone permits but does not require an open item. Focused requests and a current opt-out suppress the reservation. Research allocations for other lanes remain opportunities, not guaranteed delivered counts.

An independently drawn open route has `personal_fit_status="unknown"`. Record its concrete value rationale in the private selection trace and share it on explicit request. Only an authorized distant open candidate may use null relevance; the selector records its scoring basis using the other five weights. Verification, value rationale, constraints, and credibility still apply. Report a shortfall instead of manufacturing fit or padding the slate.

With a sparse profile, explicit open exploration may provide an honestly labelled starter from the registry. Connected-only retrieval may honestly return no routes. Registry draws are seeded and stratified by category then field; they do not sample uniformly from all human knowledge. Preserve the eligible pool, strata, seed, and any reroll explanation.

## Run and retain the frontier

### Inspect connections in the Taste Atlas

On request, `atlas.py --root <curation-root>` exports a private, offline Connections view alongside the interest map and activity history. Choose a work to inspect its current sourced paths from personal anchors and the sources supporting each edge. Anchor matching follows the discovery rules above. Coverage separately reports represented interests and interests with a verified route to a work within the displayed bounds. An isolated interest stays visible with its missing route identified; recorded reasons do not count as sourced coverage. Recorded recommendation reasons and active taste hypotheses appear separately from sourced graph paths. A proposed Lem/first-contact taste connection must not become a factual edge to a book merely to make the diagram connect.

The view distinguishes recommended works from researched graph works that were never delivered. Its bounded paths describe current graph state, not a reconstruction of the graph or reasoning used for an earlier batch. Missing or invalid graph data is reported without replacing or repairing it. Export synchronises isolated anchor nodes and private mappings before writing the HTML. It changes no personal evidence, preferences or ledgers; neither the visualisation nor its layout supplies recommendation evidence.

### Retrieve a research frontier

From this skill's directory, validate and inspect a frontier using the actual curation-root paths:

```sh
python3 scripts/curation.py graph-check --graph /path/to/model/graph.json
python3 scripts/curation.py frontier --graph /path/to/model/graph.json --profile /path/to/model/profile.json --seed 42 --count 5 --max-hops 2 --max-neighbors 12
```

Add `--allow-open --open-count 1` only when open exploration is authorized; supplying the flag does not itself create consent. `frontier` optionally accepts `--history`. The exploration helper accepts `--graph` to attach a frontier to the plan-driven briefs; follow [diverse discovery](diverse-discovery.md) for that workflow.

Keep `connected` and `open` routes distinct. Preserve `unmatched_anchor_ids`, warnings, limits, and the returned unchanged-state flags. The pure frontier accepts an explicit graph without writing it. Rooted discovery can initialise a missing graph with isolated anchors, then continue normal anchored research. An invalid graph should be reported and excluded; do not silently repair facts, erase a profile, initialize over existing state, or broaden permissions.

## Learn from the person, with scope and corrections

1. Record feedback against its actual target first, including user words, source, scope, and date. Keep completion or “already knew this” separate from enjoyment.
2. Change a creator, topic, quality, or global baseline only when the evidence supports that scope. One liked work does not establish all its qualities as preferences. One disliked introduction does not reject the subject or establish general expertise.
3. Keep uncertain interpretations tentative with supporting and contradicting evidence. Do not count a copied memory summary, a source message, and the assistant's restatement as three independent observations.
4. Let the latest explicit correction govern the relevant scope. Retain the older observation and the feedback event's before/after/reason/provenance; do not rewrite it as if the corrected belief had always been explicit.
5. Distinguish a session change from a durable change. A temporary mood, research assignment, hop limit, or open experiment does not silently become a baseline preference or standing permission.
6. Learn from volunteered feedback. Ask for feedback within a workflow the person explicitly requests or enables, following the [delivery rules](../SKILL.md#present-the-picks).

Graph paths, generated candidates, delivered recommendations, clicks, silence, and completion alone supply no taste update. Preserve an exposure trail in the recommendation/batch ledgers without treating repeated exposure as independent preference evidence. The helper never writes back a destination as a new interest or a source-confidence score as user confidence.

These controls are intended to make learning inspectable and correctable. They are not a trained knowledge-graph recommender, a contextual bandit, or a demonstrated improvement in enjoyment. [PGPR](https://arxiv.org/abs/1906.05237) motivates retaining inspectable paths; [algorithmic-confounding simulations](https://arxiv.org/abs/1710.11214) motivate keeping exposure separate from evidence. Neither study validates these local heuristics. Evaluate the whole agent's attribution, scope, corrections, and permission handling as well as the helper's runtime behavior.
