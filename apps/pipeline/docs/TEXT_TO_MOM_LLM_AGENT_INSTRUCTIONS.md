# Agent task: integrate the local text-to-MoM LLM service

> **Status (27 September 2026): implemented** in `src/secure_mom_llm` with Muse
> Glimmer 30B Q4_K_M on llama.cpp. Both contract gaps below were closed with
> the recommended sidecar: the submission carries the structured transcription
> and `uploadedAt`. See [the README](../README.md#the-local-mom-service) and
> TD-037 and TD-045 to TD-047 in the [decision log](technical-decisions.md).

You are implementing the local text-to-MoM module for Secure MOM. Read
[`TEXT_TO_MOM_LLM_HANDOFF.md`](TEXT_TO_MOM_LLM_HANDOFF.md) first, then the
pipeline contributor rules in [`../AGENTS.md`](../AGENTS.md). This task is a
48-hour offline prototype, not a production hospital platform.

## Outcome

Replace the deterministic development text-service mock with an independently
started local LLM service that accepts a multilingual transcript asynchronously
and posts a validated schema-version-1 draft MoM to the pipeline. Keep the
existing pipeline state machine intact:

```text
pipeline text dispatch -> 202 accepted -> local inference -> correlated MoM callback
```

The pipeline must reach `AWAITING_REVIEW / review_ready` with the generated
draft. All runtime inference and data handling remain local and work with the
network disconnected.

## Non-negotiable constraints

- Do not use OpenAI, another hosted LLM API, cloud inference, external storage,
  telemetry, analytics, external SMTP, a CDN, or runtime model downloads.
- Do not expose transcript or MoM content in logs unless the project has an
  explicit, reviewed content-logging policy.
- Do not put model weights, runtime jobs, caches, recordings, transcripts, or
  generated MoMs in Git.
- Do not change the public MoM schema casually. The source of truth is
  `apps/pipeline/src/secure_mom_pipeline/models.py`, with the generated
  `apps/pipeline/docs/openapi/pipeline.openapi.json` as a consumable contract.
- Do not manufacture evidence IDs, dates, owners, deadlines, participants,
  clinical facts, or decisions to make the JSON look complete.
- Keep the LLM service independent of the audio service. The pipeline remains
  responsible for orchestration, validation, and artifact persistence.

## First: close or explicitly stage the input-contract gap

The current submission gives the service only `transcript.txt`; it does not
provide segment IDs or header date metadata. Yet the callback contract requires
segment IDs for every decision/action/finding and a non-null header date.

Before implementing generation, choose one of these paths with the pipeline
owner and document the choice:

1. **Recommended: add a local structured sidecar.** Extend the pipeline’s
   multipart text submission with a JSON part containing the persisted
   schema-version-1 transcription source and explicit upload-date context. Keep
   the existing `transcript` text part unchanged for compatibility. Parse the
   sidecar in the service and use its `transcript.segments[].id` values exactly.
   Update the text transport OpenAPI, adapter tests, and handoff documentation
   together.
2. **Temporary limitation: do not claim full evidence support.** Keep the mock
   as the only producer of schema-valid evidence-backed documents and make the
   real LLM service an explicitly separate, non-integrated experiment until the
   sidecar contract is approved. Do not bypass pipeline validation or invent
   segment IDs.

Do not choose an undocumented third workaround such as downloading the
transcript from a guessed pipeline endpoint, assigning IDs by line number, or
using the machine date as meeting date.

## Implement the service boundary

1. Create a separately runnable local service with a health endpoint and a
   `POST /jobs` endpoint. Keep its source/dependencies isolated from the
   pipeline mock where practical.
2. Validate multipart input before acknowledging it:
   - field name `transcript`, filename `transcript.txt`;
   - UTF-8 `text/plain; charset=utf-8` data;
   - non-empty `X-Pipeline-Job-Id` and `Idempotency-Key` headers;
   - if adopted, a valid structured sidecar correlated with that job.
3. Implement idempotent acceptance: a repeated idempotency key must return the
   same `modelJobId` without scheduling duplicate inference.
4. Return HTTP `202` immediately with
   `{"modelJobId":"…","status":"accepted"}`. Execute inference in a
   local background worker, not in the request thread.
5. Construct the callback URL from an explicitly configured local base URL and
   the supplied pipeline job ID. POST `application/json` to
   `/api/v1/integrations/text/jobs/{job_id}/mom` with the original model job ID
   in `X-Text-Model-Job-Id`.
6. Persist or retain the exact callback bytes until the callback succeeds. A
   `202` is success; a `200` idempotent replay is also success. Retry only
   transient local transport failures according to bounded configured policy;
   surface other rejections safely for diagnosis.

Use configuration for listen address/port, callback base URL, model path,
model/runtime settings, target MoM language, concurrency, and storage paths.
The pipeline already expects a local service URL through
`PIPELINE_TEXT_SERVICE_URL` and defaults to port `8102`.

## Implement the LLM transformation

Use a locally available model and a deterministic, testable generation pipeline
(for example: structured extraction, draft composition, then transcript-grounded
validation). The exact model, prompt, and runtime are your choice, but they must
be local and recorded in the README.

Require JSON output and validate it against the pipeline contract before
callback. Repair only mechanical JSON-format failures. Never “repair” an
unsupported factual statement by guessing what the transcript meant.

Generate this envelope exactly:

```json
{
  "schemaVersion": 1,
  "quality": {"momConfidence": null, "confidenceScale": "ZERO_TO_ONE"},
  "document": {
    "header": {
      "subject": "…",
      "meeting_type": "other",
      "meeting_type_confidence": "low",
      "date": "YYYY-MM-DD",
      "date_source": "recording"
    },
    "summary": "…",
    "decisions": [],
    "actions": [],
    "findings": [],
    "topics": [],
    "risks": [],
    "open_questions": []
  }
}
```

Then populate only supported fields. Follow these rules:

- Decisions have unique sequential IDs `D1`, `D2`, …, a status of `decided`,
  `proposed`, or `revoked`, an exact or near-exact evidence quote, an existing
  `segment_id`, and `flags` (possibly empty).
- Actions have IDs `A1`, `A2`, …, evidence, flags, and a `deadline` object even
  when both fields are null. Set `owner` to `null` if it was not assigned.
- Findings also require evidence. Risks and open questions may carry evidence.
- Use a `term`, `number`, `decision_status`, `owner`, or `deadline` flag when
  uncertainty is material. Do not add a flag merely because model confidence
  is low without a transcript-specific reason.
- Preserve Romanian, Russian, English, mixed-language terms, units, numbers,
  negation, and uncertainty. Produce MoM wording in the configured target
  language; retain critical source terminology where translation would risk a
  clinical or operational meaning change.
- Never convert discussion into a decision or an unassigned task into an owned
  action. Empty arrays are better than unsupported content.
- Until confidence is evaluated against a reference set, emit
  `momConfidence: null` rather than an arbitrary score.

For full field definitions, inspect `MomHeader`, `MomEvidence`, `MomFlag`,
`MomDecision`, `MomAction`, `MomFinding`, `MomRisk`, `MomOpenQuestion`, and
`MomPatient` in `models.py`. Use the enriched mock object in
`text_service.py` only as a JSON-shape fixture, never as generated content.

## Verification required before handoff

Add automated tests for:

1. multipart submission validation and 202 acknowledgement;
2. idempotent resubmission returning the same model job ID;
3. callback headers, route, and byte-identical callback replay;
4. a valid multilingual (Romanian/Russian/English) result accepted by the real
   pipeline callback;
5. rejection before callback of invalid schema, unknown segment ID, and bad
   date/evidence mapping;
6. an action with unassigned owner and no deadline remaining null and flagged;
7. a proposal remaining `proposed`, rather than being upgraded to `decided`;
8. no external network dependency in the test/inference path.

Run the pipeline test suite and the service test suite. Then run an offline
end-to-end smoke test: start the API, worker, and local LLM service; submit a
representative recording; verify the final state, retrieve `/mom`, and inspect
evidence against `/transcript`. Measure and report elapsed processing time and
hardware/model configuration.

## Deliverables

- Runnable local service and concise setup/run README.
- Pinned, locally installable dependencies and documented model acquisition
  before demo day.
- Configuration template with no secrets or machine-specific paths committed.
- Tests and an offline end-to-end verification note.
- If the sidecar contract is adopted: corresponding pipeline adapter, schema,
  generated OpenAPI, and contract-test updates in the same change.
- A short limitations section: model, target-language default, terminology
  coverage, date-resolution policy, uncertainty behavior, and known failure
  modes.
