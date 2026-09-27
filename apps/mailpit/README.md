# Secure MOM local Mailpit environment

This folder runs Mailpit as the Secure MOM demonstration's local email
environment. It is an SMTP capture server: it accepts the two application
emails below and displays them in a browser inbox on the same Mac. It does not
relay or forward email to the internet.

1. **Draft ready for review** — sent to the submitting author after a MoM draft
   reaches `AWAITING_REVIEW`.
2. **Approved MoM** — sent from the submitting author's authorized address to
   the recipients selected in the review portal.

The Python pipeline is wired to Mailpit-compatible SMTP for both the generic
draft-ready notification and approved-MoM delivery. Live Mailpit inspection is
still pending because Docker is not installed in the current environment.

## Local-only design

```text
Secure MOM pipeline on macOS
    └── SMTP 127.0.0.1:1025
            └── Mailpit Docker container
                    └── browser inbox at http://127.0.0.1:8025
```

Both published ports are bound to `127.0.0.1`; they are not reachable from the
hospital LAN or the public internet. Mailpit is configured to accept only the
test recipient domain from `.env` and to disable reverse-DNS lookup and version
checking, so routine operation has no external network dependency.

The `runtime/` directory holds Mailpit's local SQLite database, including
captured email bodies and attachments. It is ignored by Git and must be treated
as confidential meeting-derived data.

## Contents

- `compose.yaml` — pinned, loopback-only Mailpit container.
- `.env.example` — the permitted test-recipient domain.
- `.gitignore` — keeps local Mailpit content and machine configuration out of
  source control.
- `Makefile` and `scripts/` — repeatable startup, verification, and a
  non-sensitive SMTP smoke test. These do not modify or invoke the pipeline.

## One-time setup on a development or demonstration Mac

Complete these steps **while the machine has internet access**. Docker Desktop
and the Mailpit image must be installed before the offline demonstration.

1. Install and start Docker Desktop for macOS. Confirm it is running:

   ```bash
   docker version
   docker compose version
   ```

2. From this folder, create the local Compose environment:

   ```bash
   cp .env.example .env
   ```

   Keep `@medpark\.test$` unless the team deliberately chooses another
   non-routable test domain. The backslash is required because this is a regular
   expression.

3. Validate the configuration and preload the pinned image:

   ```bash
   docker compose config
   docker compose pull
   docker image inspect axllent/mailpit:v1.31.2
   ```

4. Start Mailpit:

   ```bash
   docker compose up -d --pull never
   docker compose ps
   ```

5. Confirm the local service is healthy, then open the inbox in a browser:

   ```bash
   curl --fail http://127.0.0.1:8025/readyz
   ```

   Open <http://127.0.0.1:8025>. Do not expose this interface using a LAN IP,
   `0.0.0.0`, a reverse proxy, SMTP forwarding, or SMTP relaying.

## Offline demonstration check

Before the event, disconnect the Mac from the network and verify that Docker
Desktop is already running. Then, from this folder:

```bash
docker compose up -d --pull never
curl --fail http://127.0.0.1:8025/readyz
```

The inbox must remain reachable at <http://127.0.0.1:8025>. If Docker reports
that `axllent/mailpit:v1.31.2` is missing, reconnect only long enough to run
`docker compose pull`, then repeat this check offline.

## Pipeline integration contract

The pipeline sends approved-MoM mail through standard SMTP using these values:

```text
PIPELINE_MAIL_HOST=127.0.0.1
PIPELINE_MAIL_PORT=1025
PIPELINE_MAIL_USE_STARTTLS=false
PIPELINE_MAIL_ALLOWED_RECIPIENT_DOMAINS=medpark.test
PIPELINE_NOTIFICATION_SENDER=secure-mom@medpark.test
PIPELINE_NOTIFICATION_MAX_ATTEMPTS=2
```

The implementation uses a replaceable local mail adapter and Python's SMTP
client rather than Mailpit's HTTP API. It has no external relay or forwarding
configuration.

For draft-ready notification, the pipeline:

- uses the configured system address as `From` and the persisted submitting
  author as the sole recipient;
- includes only the job ID and stable loopback review link;
- persists intent and result metadata and does not automatically resend an
  acceptance-uncertain submission; and
- leaves the job at `AWAITING_REVIEW / review_ready` for every notification
  outcome.

For approved-MoM delivery, the pipeline:

- uses the server-side submitting-author address as `From` only after local
  authorization validates it;
- softly skips malformed or non-permitted-domain recipients and delivers only to
  the accepted `@medpark.test` list;
- uses a stable, notification-distinct `Message-ID` and persists a metadata-only
  delivery record;
- moves the job to `COMPLETED` only after local SMTP accepts the approved-MoM
  delivery request.

During live verification, inspect or search the Mailpit UI by the persisted
`Message-ID`. An `unknown` notification result requires operator inspection;
do not trigger an automatic resend because SMTP acceptance may already have
occurred.

Mailpit accepts messages for local inspection; it does not prove that an
external or production mailbox received them.

## Routine commands

```bash
# View all commands.
make help

# Validate the configuration, then preload the image while online.
make config
make preload

# Start the local mail environment without pulling images.
make up

# Start and check Mailpit while offline.
make verify

# Send a non-sensitive email through local SMTP and inspect it in Mailpit.
make smoke

# Show container state and recent logs.
make status
make logs

# Stop Mailpit while preserving captured mail in runtime/.
make down
```

The smoke-test recipient defaults to `demo.recipient@medpark.test`. It is only
an email header in Mailpit's shared local inbox; Mailpit does not create a real
user account or send the message outside the Mac. The current recipient picker
uses the pipeline's server-owned local demo directory; institutional directory
integration remains later work.

Do not commit `.env`, `runtime/`, Mailpit databases, captured email files, or
attachments. Do not change the image tag during the demo without running the
online preload and offline verification steps again.
