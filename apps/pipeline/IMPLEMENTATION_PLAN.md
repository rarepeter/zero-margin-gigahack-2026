# Pipeline baseline implementation plan

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
