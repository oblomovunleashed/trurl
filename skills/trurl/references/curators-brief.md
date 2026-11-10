# The curator's brief

Maintain a short, editable working understanding of the person in private `model/curators-brief.json`. The host writes the summary; the bundled Python helper records sources, checks freshness and saves it atomically. It requires no memory service, model training, additional account or background job.

## Three different kinds of brief

| Artifact | Question it answers | Lifetime |
| --- | --- | --- |
| Curator's brief | What do we currently understand about this person's taste, and what is uncertain? | Reusable until relevant source evidence changes |
| Request plan | What are we selecting now, with which constraints, priorities and exploration policy? | One request or batch |
| Research briefs | Which distinct questions, approaches and sources should we investigate before selecting works? | One candidate-generation run |

The taste profile and raw feedback remain authoritative. The brief supplies a coherent reading aid, while the request plan applies current intent. A film request can use the same taste brief with film-specific constraints. It does not require fresh random weights: focused requests suppress unrequested mode rotation, fixed weights remain fixed, and deliberate surprise can change the objective. External seeds vary eligible discovery directions or selection ties separately. Follow the existing adaptive-weight and diverse-discovery references for those decisions.

Use the brief privately to inform recommendations. Follow the [skill's delivery rules](../SKILL.md#present-the-picks) for the reply. A person's explicit layout or length preference belongs in `taste.presentation`.

Reconcile [taste hypotheses](taste-hypotheses.md) before checking or refreshing the brief. Summarise supported patterns with their inferred status and keep useful unresolved possibilities clearly tentative. Cite the original user and feedback evidence behind them. Hypothesis reasoning, the brief and the Atlas each represent interpretations of those sources.

## Contents and evidence

Keep the summary at most 350 words. Useful contents are confirmed priorities and constraints; explicitly tentative interests; source-scoped work or creator anchors; relevant familiarity and feedback; and important unknowns. Do not fabricate a rich personality for a sparse profile. A starter model can have an honestly sparse brief and continue category-and-anchor onboarding.

Keep claim references to the underlying records with their actual kind and scope. A positive willingness-to-try rating remains first-impression willingness; it does not establish consumption, enjoyment, expertise, a genre preference or an axis-weight update. A previous recommendation and an assistant's rationale do not establish liking. Do not count an event again through its summary or experiment copy.

When authorized feedback refers to an earlier experimental selection, consult its linked work/exposure records for identity and repeat avoidance. Keep those original records separate unless import was requested. The brief is not a complete recommendation ledger, and a prior exposure is not consumption.

Distinguish lessons about selection from beliefs about the person. A complaint that a batch concentrated on one field can inform how the curator distributes attention; it does not automatically establish dislike of that field. New explicit interests can start independently. Examples, third-party statements, project branding and sensitive-identity guesses do not become tastes.

The helper retains `profile_interest_ids` from the source profile. This inventory is not semantic proof that the prose covered everything. `context.py prepare --root <curation-root>` returns every interest's ID, topic, kind, scope and pointer alongside settings and a checked fresh brief, without full ledgers. Use that complete inventory when allocating discovery so quiet, unusual explicit interests receive opportunities too. Fetch originals by ID with `context.py records` before interpreting selected anchors, source provenance or uncertain scope. Do not use compressed prose as the entire candidate universe.

Temporary instructions such as a current mood, a tighter duration, or a request to venture farther belong in the request plan and its trace. Apply a new correction immediately within its stated scope, even before a persisted brief is refreshed. A temporary request must not become a standing curiosity, open-exploration permission, new weight baseline or weekly subscription.

## Check, draft and save

Resolve the helper relative to the installed skill and pass the actual private workspace explicitly. Initialize a new model before building its first brief.

1. `curation.py start` includes this check in its `context`. Otherwise run `python3 <skill-directory>/scripts/context.py prepare --root <curation-root>` before reading the cached summary. This reconciles existing hypothesis evidence, then returns prose only if the brief is `fresh`. `brief.py check` is also available after explicit hypothesis reconciliation. Missing, stale, invalid or invalidated results require source review, not use of the old prose. Timestamps alone do not establish freshness.
2. Run `python3 <skill-directory>/scripts/brief.py snapshot --root <curation-root>` **before drafting**. It captures the profile and feedback fingerprints plus the current cache digest. Add repeated `--source model/path/to/source.json` only for other authorized evidence actually used. Declare a recommendation ledger when joining feedback to work identities. Avoid declaring unrelated files or batch logs that would cause unnecessary refreshes.
3. Preserve that captured snapshot in a private draft JSON, adding `summary`, `source_refs` and `limits`. Each source reference has `path`, `locator` and an optional `note`. Use a JSON Pointer such as `#/interests/0` or `#`, or a one-based JSONL/text locator such as `line:1`. Cite every nonempty source used. Keep missing feedback and uninspected history explicitly unknown. A helper can validate references, not the truth or permission behind a claim.
4. Save with `python3 <skill-directory>/scripts/brief.py save --root <curation-root> --draft <private-draft.json>`. A changed source or intervening cache edit rejects the draft. Review the new evidence and take a new snapshot before retrying; do not merely attach new hashes to unreviewed old prose.
5. Check the saved brief, then remove temporary drafts. Use its version and file digest in the delivered batch's trace, without copying the whole prose into history.

`check` exits zero only for a fresh brief. The helper validates paths inside the private model, source formats and locators; its hashes establish byte currency, not semantic accuracy. A missing or empty feedback ledger is represented truthfully. Sources are explicitly declared: the helper does not search chats, agent memory, accounts or every experiment folder. New authorized evidence outside the declared files must be reviewed and added when used; a fresh fingerprint cannot prove that all possible feedback was inspected.

The active cache is replaced rather than archived as old prose. Source fingerprints and the previous cache digest retain version lineage. Source files are rechecked before atomic replacement, and a lock serializes cooperating brief writers. Coordinate other state writers through the workspace's normal serialized-update discipline; a raw-state change after the final check is caught by the next freshness check.

## Corrections, editing and forgetting

Show the readable summary when asked and take edits as scoped feedback with provenance. Correct the underlying observation when appropriate, review affected claims and refresh the brief. A user's latest explicit correction takes priority over an older interpretation. If only this request changes, preserve the enduring summary and use an explicit request overlay.

Use `python3 <skill-directory>/scripts/brief.py invalidate --root <curation-root> --reason source_corrected` when cached prose must stop being usable before a replacement is ready. For forgotten evidence, use `source_forgotten`, remove the requested private evidence and dependent copies, and rebuild only from remaining authorized sources. Invalidation writes a content-free tombstone; it does not itself erase the raw sources, an old experiment snapshot or a temporary draft. Locate and remove affected derived copies when fulfilling a forgetting request. Preserve only minimal content-free change metadata where needed.

If the helper or write access is unavailable, work from current raw evidence, record the brief fallback and continue. A missing cache must not trigger broader source access, repeat useful onboarding, invent preferences, relax credibility, or block a small useful selection.

## Evidence for this design

The brief adds source-linked synthesis and freshness checks to the existing evidence and request-planning workflow. It does not change scoring formulas, imply a recommendation-quality multiplier, or require a particular host or memory product. Evaluate appeal, worthwhile variety, unknown familiarity and reaction to corrections separately; first impressions are not experienced enjoyment. A preferred set in a small pilot motivates further use rather than a claim of general superiority.
