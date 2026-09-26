# OpenAPI status

All documents in this directory are provisional.

- `pipeline.openapi.json` is generated from the FastAPI application. Job
  creation and status reads are implemented; the remaining operations are
  marked as mocks in their operation metadata.
- `audio-processing.openapi.json` describes only the conceptual asynchronous
  boundary for the independently owned audio service.
- `text-processing.openapi.json` describes only the conceptual asynchronous
  boundary for the independently owned text service.

`TODO(discovery)` descriptions are intentional. They prevent placeholder paths
and open object schemas from being mistaken for finalized integration contracts.
