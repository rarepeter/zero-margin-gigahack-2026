# Baseline discovery TODOs

Status: open; the current implementation must not be treated as a final contract

The baseline uses placeholders only where a runnable skeleton needs a concrete
value. Every such decision remains replaceable through configuration or a small
boundary module.

## Public API

- `TODO(discovery, TD-025)`: confirm the API prefix, routes, methods, statuses,
  request fields, response fields, and error behavior.
- `TODO(discovery, TD-031)`: confirm or replace the provisional common-format
  allowlist and 300 MiB upload limit implemented for the first real slice.
- `TODO(discovery, TD-027)`: decide whether and by whom `COMPLETED` is emitted.

## Filesystem and artifacts

- `TODO(discovery)`: choose final runtime roots. The implemented job layout uses
  `transcript/source.json`, `transcript/transcript.txt`, and
  `review/context.json` provisionally.
- `TODO(discovery, TD-024)`: define the detailed MoM `document` schema. The
  surrounding `mom.v1alpha1` envelope and confidence field are agreed.
- `TODO(discovery)`: define persistence, atomic replacement, queueing, and
  recovery when those features enter implementation scope.

## ML services

- `TODO(discovery, TD-026)`: confirm both callback routes/headers and the
  text-service multipart field, acknowledgement, status values, and errors with
  their owners.
- Validate whether the ML services can later provide reliable word-level
  recommendations or ambiguity annotations. They are not part of the current
  contracts.
- Replace the current mock audio pickup adapter only after the audio-service
  contract is agreed.
- `TODO(discovery, TD-032)`: choose polling intervals, timeouts, and the error
  taxonomy after observing the actual services.

## Runtime and operations

- `TODO(discovery)`: select the API bind address, port, and launch policy.
- `TODO(discovery)`: select machine-specific storage and log locations.
- `TODO(discovery, TD-029)`: decide log format, rotation, retention, and strict
  content policy. The baseline logs only safe event names and mock states.
- `TODO(discovery)`: replace both development mocks with the real ML adapters
  while retaining the persisted callback checkpoints.
