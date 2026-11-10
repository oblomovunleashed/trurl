# Comfortable first use

Start with categories and whatever context the person wants to share. Give value quickly; do not require introspection, ratings, a quiz, account imports, or a fixed number of examples.
An existing useful profile is enough to begin. Missing `onboarding` fields do not justify restarting onboarding or asking again about a recorded source choice.

## Choose a lasting home

Resolve the root with `python3 <skill-directory>/scripts/curation.py root` before setup. Use an explicitly chosen location or an existing accessible model. Otherwise use the local default `~/Trurl`, with the profile and ledgers in its `model/` folder. Create it with `python3 <skill-directory>/scripts/curation.py init --root <resolved-root>`. For a custom location the person wants to reuse, run `python3 <skill-directory>/scripts/curation.py use --root <existing-root>` after initialization. This remembers its path for later sessions that share the same user configuration.

Confirm that the location is on persistent storage available to this host. App-created session directories, temporary containers and disposable worktrees need a durable alternative. On a sandboxed or remote host, use a shared folder that survives the session and report its actual path. If access requires a folder selection or permission, obtain that access before claiming the profile has been saved durably. A local folder is reusable by other sessions and agents that can access the same filesystem.

If a remembered model is missing or inaccessible, resolve its location or access before starting another model. A changed working directory or a fresh session alone is no reason to restart.

For an existing model in a session directory, identify its exact root and a durable destination. Copy the complete `model/` and any referenced local evidence, verify the copy, then remember the destination and use it for subsequent requests. Preserve relative source paths and refresh derived records if references change. Coordinate the transfer with active writers, and update any existing scheduled job's root through the host scheduler. Deletion of the original is a separate user choice.

Deletion instructions must name the actual data folder and distinguish it from the installed skill and the host's chat history. Describe session deletion effects only after checking the host and storage location.

## One compact invitation

If the person has already told you what they want, use it. Otherwise start with a short invitation and one example request. Skip the preamble about whether a profile file exists.

> Let’s build your taste profile so I can draw on what you like each time you ask for picks. Start with one thing, like “Books and podcasts about how cities change,” or dictate whatever comes to mind. You can see and correct the profile as we go.
>
> I’ll keep it in `~/Trurl/model` so you can use it across sessions.
>
> I’ll also set up a Sunday edition at 8 pm local time. Each one runs as an ordinary request on your plan. Say “one-off only” to skip weekly delivery.

Replace the location with the actual selected path, using a readable home-relative form when appropriate. Include the storage line once during setup, after confirming that the host can use that persistent location.

Use the Sunday line only for eligible new onboarding on a host with a native scheduler. Use the person's stated time if they give one. If their local timezone is still unknown, leave out the exact time and resolve it before scheduling. If scheduling is unavailable, say they can ask for an edition any time.

If the person gives you a full brain dump before seeing the weekly notice, give them their first selection and include the notice in that reply. Apply the default only after they have had a chance to respond. Keep a one-off request in the format and count they asked for.

Treat a voice transcript or rough notes as ordinary user input. Accept multiple categories or anchors without a cap. A brain dump with usable interests can be enough to start. If no format is chosen, use a provisional mix for the first selection and keep the saved format choice open. Ask one question about format only if the current request needs it.
Record distinct interests as separate anchors, with their wording, scope, and current-message provenance. Keep work or personal context separate from stated preferences. Preserve ambiguity in dictated names unless resolving it matters to the selection.
Names and links may be references, research assignments, dislikes, or enjoyed works: retain what the person actually says rather than converting every mention into a like.
Do not open every supplied link just to finish onboarding. Read relevant supplied evidence when needed and record what was actually inspected.
Current-request limits remain temporary unless the person makes them lasting preferences. Category choices establish preferred formats, not subjects, personality, or expertise; unchosen categories are not dislikes.
Apply substantive lasting interests and preferences to the existing `interests` and `taste` fields with their evidence and scope; `onboarding.anchors` is the input record, not a second taste model. Preserve temporary goals in the current batch request. The discovery helper reads `interests` and the retained request, so include the usable current anchor there rather than relying only on onboarding metadata. Constraints and avoid/reference-only examples do not supply positive fit by themselves.

Offer agent memory separately after the first result when it would help and the choice is still open:

> Would you like me to use relevant things this agent remembers about you? You can tell me what to include.

An affirmative answer is required before using agent memory for onboarding. A decline or unanswered option leaves the current-data/starter route open; do not keep prompting.
When the person asks to use only what they share here, honour that choice for both agent memory and past chats and skip the offer. Apply narrower source limits to the sources they cover.
Reuse a previously decided permission within its recorded scope. Ask again only when the person changes that choice or the proposed source scope genuinely exceeds it.
These are choices about sources for this workspace's curation profile, not platform permission toggles. Never enable host memory, rewrite the host's memory store, or imply a platform setting changed.

## Distinguish sources

**Current input:** use the person's supplied categories, anchors, corrections, and limits directly, preserving their scope and words.

**Agent memory:** an allowed choice covers only relevant memory actually exposed by the host, within the agreed scope. It does not authorize past-chat discovery, account connections, Google searches, or reading unrelated files.
If access is unavailable or partial, say so briefly and continue with current input. Do not fabricate a memory lookup or claim that a missing memory proves no preference exists.
Treat memory summaries as provisional observations, not verbatim user statements. Retain source locators, actual access date, inspected scope, and unknown original dates as unknown; do not invent an original chat or timestamp.

**Past chats:** this is a separate optional source. Read only specifically authorized chats or bounded portions; memory permission does not authorize searching all chats.
A person may name a chat and authorize that source directly. Otherwise obtain a bounded affirmative choice before discovery or reading, reuse that choice within scope, and record actual coverage and gaps.
An accessible chat fixture or connector is not consent. Do not search connected accounts as a substitute for an unavailable source.

Do not assume professional research is a leisure interest, sophisticated questions establish expertise, or a mentioned title was enjoyed; require direct evidence for each.
Preserve contradictions, context, uncertainty, and source provenance. The latest explicit user correction governs; retain earlier observations as historical evidence rather than silently rewriting them.
When translating a memory hypothesis into the existing `interests` model, keep `kind=inferred`, knowledge `unknown`, and justified confidence/provenance. Do not promote it because onboarding has finished.

## Start, summarize, and continue

Give a short, editable summary and the first picks in the same reply when you have enough context. For example, “I’ll start with films about city design and keep tonight’s picks under 20 minutes.” Keep tentative observations distinguishable from what the person confirmed.
Invite corrections without requiring approval of the summary before giving a useful selection. Do not label an explicit correction as uncertain merely because an older memory disagrees.
Category-only or skipped context yields a clearly labelled starter selection, not a claim of personal fit. Feedback is optional and may supply a later anchor.
Connected “surprise me” still requires a substantive interest, enjoyed example, current goal, or concrete request subject. Format, duration, and randomness instructions alone are not sufficient; obtain one anchor rather than fabricating a connection.
Do not infer consumption, enjoyment, or preference from delivery, silence, a click, or a title alone. Follow the [weekly delivery rules](weekly-delivery.md) for the separate scheduling decision.

## Private onboarding state

Use `profile.onboarding` alongside the existing profile model; preserve unrelated fields. Generic initialization uses:

```json
{
  "status": "not_started",
  "categories": [],
  "anchors": [],
  "context_sources": {
    "agent_memory": {
      "permission": "not_asked",
      "scope": null,
      "availability": "unknown",
      "source_provenance": []
    },
    "past_chats": {
      "permission": "not_asked",
      "scope": null,
      "availability": "unknown",
      "source_provenance": []
    }
  }
}
```

`status` is `not_started`, `starter` (usable format/limits but no fit anchor), or `ready` (a usable substantive anchor). It is not a required approval stage.
`categories` uses canonical media IDs: `book`, `podcast`, `film`, `youtube_video`, `lecture`, and `scientific_paper`. Expand a chosen mix into its multiple selected IDs, not a literal `mix` value. Preserve other requested formats through a documented extension, rather than inventing additional root IDs or inferring exclusion.
Each `anchors` record has `id`, `kind` (`topic`/`current_goal`/`work`/`creator`/`link`/`constraint`), `value`, `signal` (`interested`/`enjoyed`/`avoid`/`reference_only`/`unknown`), `scope` (`current_request`/`persistent`/`source_unspecified`), and `source_provenance`.
Avoid/constraint/reference records can be useful without supplying a positive personal-fit anchor. Preserve multiple records when signals conflict or have different scope.
Each source has `permission` (`not_asked`/`allowed`/`declined`), a null or bounded-text `scope`, `availability` (`unknown`/`available`/`partial`/`unavailable`), and `source_provenance` for the actual decision and inspected evidence.
Unanswered means no affirmative permission; do not persist it as a decline or use availability as a substitute. An optional source `offered_at` records when the offer was actually made so an unanswered offer need not be repeated. Prior visible conversation also establishes that it was offered.
Keep this state private with the rest of `model/`; do not add personal onboarding answers to public examples or this reference.
