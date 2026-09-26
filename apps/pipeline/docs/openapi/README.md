# OpenAPI status

The transport remains provisional, while the versioned data shapes described
below are agreed for the current integration increment.

- `pipeline.openapi.json` is generated from the FastAPI application and includes
  the structured transcription callback, versioned MoM callback, separate
  transcript/MoM reads, and compact review-context read.
- `audio-processing.openapi.json` fixes the `transcription.v1alpha1` result
  structure, including transcript confidence.
- `text-processing.openapi.json` fixes the `mom.v1alpha1` envelope and MoM
  confidence while leaving the detailed `document` object open.

Health details and service transport choices that still carry discovery markers
are not finalized by these data-shape decisions.
