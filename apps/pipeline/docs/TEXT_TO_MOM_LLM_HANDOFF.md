# Text-to-MoM LLM integration handoff

> **Status (27 September 2026): implemented** in `src/secure_mom_llm` with Muse
> Glimmer 30B Q4_K_M on llama.cpp. Both contract gaps below were closed with
> the recommended sidecar: the submission carries the structured transcription
> and `uploadedAt`. See [the README](../README.md#the-local-mom-service) and
> TD-037 and TD-045 to TD-047 in the [decision log](technical-decisions.md).

## What we need

Please replace the development text-service mock with a real **local**
transcript-to-Minutes-of-Meeting (MoM) service. Its job is to turn the
multilingual transcript produced by the audio service into a conservative,
structured draft for human review.

This is not a generic summarizer. The useful outcome is a concise MoM that
separates confirmed decisions from proposals, identifies follow-up actions,
preserves clinical and operational detail, and never fills gaps with plausible
guesses. It must work with Romanian, Russian, and English, including switching
within a sentence. The draft is reviewed by a person before it is approved or
distributed.

The service is part of an offline hospital demonstration. At runtime it must
run entirely on the presentation MacBook: no hosted model, external API,
telemetry, cloud storage, external SMTP, model download, or CDN request. The
model and all dependencies must be available before the demonstration starts.

## Where it fits

The pipeline owns job state and artifacts. The LLM service is an independently
started local process and communicates only with the pipeline over local HTTP.
It does not call the audio service.

```text
audio service
  -> pipeline persists transcription JSON
  -> pipeline derives UTF-8 transcript.txt
  -> text-to-MoM service accepts the transcript asynchronously
  -> text-to-MoM service posts draft MoM JSON to pipeline
  -> pipeline validates, persists, and exposes the review draft
```

At present the pipeline submits `POST {PIPELINE_TEXT_SERVICE_URL}/jobs` as
multipart form data. The field is `transcript`, with filename `transcript.txt`
and media type `text/plain; charset=utf-8`. It also sends these headers:

| Header | Purpose |
| --- | --- |
| `X-Pipeline-Job-Id` | Pipeline job ID; preserve it for the completion callback. |
| `Idempotency-Key` | Stable per attempt key, currently `<job-id>:mom-generation:<attempt>`. |

The service must respond promptly with HTTP `202` and:

```json
{"modelJobId":"local-text-…","status":"accepted"}
```

Inference must happen after the acknowledgement. On completion, post the JSON
result to the configured local callback URL:

```text
POST /api/v1/integrations/text/jobs/{pipeline-job-id}/mom
Content-Type: application/json
X-Text-Model-Job-Id: <the modelJobId returned at acceptance>
```

The pipeline initially responds with `202`. A retry carrying byte-identical
JSON may receive `200` with `replayed: true`, which is success. Keep the exact
completion bytes and resend those on a transient local callback failure; do not
regenerate a different document for the same model job.

Local endpoint addresses, callback base URL, model path, target MoM language,
and concurrency must be configuration—not hard-coded paths or remote URLs.

## Required output

The completion body is the schema-version-1 `MomResult` object, validated by
the pipeline and consumed directly by the portal. The generated source of truth
is [the pipeline OpenAPI schema](openapi/pipeline.openapi.json), especially
`MomResult` and the `Mom*` definitions. The separate
`text-processing.openapi.json` is still a provisional transport document and
currently describes `document` too loosely; do not treat it as permission to
return arbitrary document fields.

At a high level the output is:

```json
{
  "schemaVersion": 1,
  "quality": {
    "momConfidence": null,
    "confidenceScale": "ZERO_TO_ONE"
  },
  "document": {
    "header": {},
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

All listed document arrays are required, even if empty. The header is required:
`subject` (maximum 120 characters), `meeting_type`,
`meeting_type_confidence`, `date`, and `date_source`. Valid meeting types are
`medical`, `patient_case`, `financial`, `administrative`, `executive`,
`operational`, `crisis`, and `other`.

Use the specific schema rules rather than guessing names or casing. Important
ones are:

- Decision IDs are `D1`, `D2`, … and action IDs are `A1`, `A2`, ….
- A decision has `status` of `decided`, `proposed`, or `revoked`, plus evidence
  and a `flags` array.
- Every decision, action, and finding needs evidence. Optional evidence on a
  risk or open question is strongly preferred when there is supporting speech.
- Evidence contains a verbatim or very close source `quote`, `lang` (`ro`,
  `ru`, `en`, or `mixed`), and an existing `segment_id`. `speaker` and `t` are
  optional display aids; `segment` is only a legacy fallback.
- An action always has a `deadline` object. Use
  `{"spoken": null, "resolved": null}` when no deadline was stated. Leave
  `owner` as `null` when none was explicitly assigned.
- `decision_ids` may link an action to supported decisions, but should be
  omitted or `null` when there is no justified link.
- Flags use only `number`, `decision_status`, `owner`, `deadline`, or `term`.
  Each flag needs a reviewer-facing reason and `blocking` boolean. Add
  candidates only when they are real alternatives from the transcript.
- `patients` is optional. Do not create patient records or personally
  identifying detail merely because this is a hospital product.

The mock in
[`src/secure_mom_pipeline/text_service.py`](../src/secure_mom_pipeline/text_service.py)
is a useful shape example only. Its conclusions and segment IDs are fixture
data; they must never be copied into real results.

## Content rules for the LLM

- Treat the transcript as the only meeting-content source. Do not infer names,
  roles, facts, decisions, owners, deadlines, dates, clinical conclusions,
  measurements, units, costs, or risks.
- Preserve negation, uncertainty, medical terminology, numbers, dates, units,
  and terminology in the language actually spoken. When a term is unclear or
  clinically ambiguous, retain the best supported wording and flag it; do not
  silently normalize it into a different medical fact.
- A proposal, wish, or question is not a decision. Mark it `proposed` or place
  it in open questions as appropriate. A later reversal is `revoked`, not
  `decided`.
- An action needs an actual follow-up. A named speaker is not automatically its
  owner. A relative date must keep the spoken wording and be flagged unless its
  resolution is supplied by a defined, auditable rule.
- Omit unsupported or empty ideas rather than adding filler. Empty arrays are
  valid; fabricated completeness is not.
- Infer a meeting type only conservatively. Use `other` with low confidence
  where the transcript does not support a category.
- The output language must be an explicit local setting or input contract, not
  an assumption based on the majority language. The current pipeline has no
  user-selected language field, so agree a demo default before implementation.

`momConfidence` may be `null` until the team defines and evaluates a real
calibration method. Do not expose an invented numeric confidence as a model
measurement.

## Two contract gaps to resolve before a real integration

These are current constraints, not issues for the LLM to work around by
inventing data.

1. **Evidence mapping:** the existing text submission contains only
   `transcript.txt`, while valid decisions, actions, and findings must cite real
   `segment_id` values. Plain text does not contain them. The recommended small
   change is for the pipeline to submit a second JSON part (for example
   `transcription`) containing the existing schema-version-1 transcription
   source, or an equivalent segment sidecar with IDs, text, languages, speaker
   IDs, and timing. The LLM service should use these IDs exactly. Do not derive
   IDs from line positions or manufacture `segment-…` values.
2. **Required date:** the MoM header requires `date` and `date_source`, but
   the text submission does not include recording time or upload time. Pass
   recording metadata plus an explicit pipeline upload date in the sidecar.
   Use recording date only when the audio service supplied it; otherwise use
   the explicit upload date with `date_source: "upload"`. If the product team
   wants a truly unknown date instead, the pipeline/portal schema must be
   changed together—an LLM must not use its runtime date.

The proposed sidecar is deliberately local and small: it preserves the current
plain-text contract while allowing traceability and truthful header metadata.
Until it exists, a real result with supported decision/action/finding evidence
cannot be produced reliably under the current validation rules.

## Definition of done

The handoff is complete when the service can be started locally with a locally
available model, accept the pipeline’s asynchronous submission, and complete a
full offline test recording through `AWAITING_REVIEW / review_ready`.

Please demonstrate at least these cases:

1. Romanian/Russian/English switching with preserved clinical terms.
2. A confirmed decision, a proposal, a revoked or unresolved outcome, and an
   action whose owner/deadline are absent or ambiguous.
3. Accurate evidence quotes and IDs that are accepted by the pipeline.
4. A retry of the same callback that is treated as an idempotent replay.
5. No network traffic beyond local loopback/LAN while processing.
6. Malformed output, unknown segment IDs, and callback-correlation mismatch
   are rejected safely without corrupting the existing job checkpoint.

Record model name/version, quantization, runtime, configured output language,
hardware, offline startup steps, and measured time for a representative
recording. This is a hackathon prototype: demonstrate a narrow, trustworthy
path rather than adding unrelated workflow features.
