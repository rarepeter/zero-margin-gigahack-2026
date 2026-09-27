# OpenAPI status

The transport remains provisional, while the versioned data shapes described
below are agreed for the current integration increment.

- `pipeline.openapi.json` is generated from the FastAPI application and includes
  the structured transcription callback, versioned MoM callback, separate
  transcript/MoM reads, and compact review-context read.
- `audio-processing.openapi.json` fixes the schema-version-1 transcription result
  structure, including transcript confidence.
- `text-processing.openapi.json` describes the local MoM service: the multipart
  submission, the schema-version-1 MoM callback, and the failure callback. The
  detailed `document` object is defined by `MomResult` in the pipeline document.

Health details and service transport choices that still carry discovery markers
are not finalized by these data-shape decisions.
