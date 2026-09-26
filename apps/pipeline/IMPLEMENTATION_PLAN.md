# Pipeline baseline implementation plan

## Iteration completion rule

Every implementation iteration must end by stopping any running pipeline API
and worker processes, starting both again from the current checkout, and
verifying the live API version and changed workflow. An iteration is not
complete merely because its tests pass while stale processes are still running.

Status: approved on 26 September 2026

This checklist tracks the approved mock baseline. An item is marked complete
only after its implementation has been exercised during the final smoke check.

- [x] 1. Bootstrap the Python project.
- [x] 2. Add centralized provisional configuration.
- [x] 3. Add binary and UTF-8 text filesystem services.
- [x] 4. Add dummy pipeline API endpoints.
- [x] 5. Add the generated pipeline OpenAPI document.
- [x] 6. Add provisional OpenAPI documents for both ML services.
- [x] 7. Add a mock worker and state-machine shell.
- [x] 8. Add configurable local server logging.
- [x] 9. Add local operating and discovery documentation.
- [x] 10. Run the baseline smoke verification.

## Verification result

Completed on 26 September 2026 with Python 3.12.14. The API and mock worker
started successfully; all dummy endpoints returned placeholder responses and
wrote safe events to the configured log; byte and multilingual UTF-8 text
round trips succeeded; all three OpenAPI JSON documents parsed successfully;
and the dependency lockfile passed `uv lock --check`.

## Explicit exclusions

This baseline does not implement real job persistence, queueing, atomic
checkpoints, ML calls, artifact validation, finalized schemas, production state
transitions, retries, recovery, or automated tests.

# Upload-to-audio-pickup implementation plan

Status: approved on 26 September 2026

This increment replaces the mock upload path through the point where an audio
service accepts the persisted recording. The ML service contract is still under
discussion, so its pickup is represented by an isolated mock adapter.

- [x] 1. Add versioned job, response, error, event, and mock-submission models.
- [x] 2. Stream common audio formats up to 300 MiB into a staging job directory.
- [x] 3. Atomically publish the audio, initial state, and event log as a queued job.
- [x] 4. Return `202 Accepted` and expose real persisted job status.
- [x] 5. Add atomic state updates and safe job discovery.
- [x] 6. Replace mock worker transitions with single-active-job dispatch.
- [x] 7. Add a replaceable mock audio-service pickup adapter.
- [x] 8. Record ordered Kafka-shaped events in per-job NDJSON files.
- [x] 9. Add API, persistence, event-log, worker, and failure-path tests.
- [x] 10. Update contracts and operating documentation.
- [x] 11. Run the implementation smoke verification.
- [x] 12. Restart the live API and worker and verify the served API version.

## Implemented boundary

```text
audio upload
    -> atomic filesystem-backed queued job
    -> separate worker
    -> mock audio-service acknowledgement
    -> persisted TRANSCRIBING checkpoint
```

Transcript polling, transcript persistence, text processing, and draft MoM
generation remain later increments.

## Verification result

Completed on 26 September 2026 with Python 3.12.14. All 18 automated tests
passed, the dependency lockfile validated, all OpenAPI JSON documents parsed,
and source/test compilation succeeded. A live API and separate worker smoke
test returned `202`, preserved the uploaded bytes, produced ordered event
offsets 0 through 6, persisted the mock model job ID, transitioned the job to
`TRANSCRIBING`, and exposed that checkpoint through the status endpoint.
The stale baseline processes were then stopped; the current API and worker were
started, and localhost reported API version `0.2.0-provisional`.
