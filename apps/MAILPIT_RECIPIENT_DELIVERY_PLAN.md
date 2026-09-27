# Recipient delivery plan

Status: implemented direction, 27 September 2026.

## One approval endpoint

The portal always calls:

```text
POST /api/v1/jobs/{jobId}/approve
```

with the reviewed `document` and an email `recipients` list. The backend
chooses the continuation from that list:

```text
recipients empty after filtering
  -> persist immutable approved MoM
  -> no SMTP call
  -> COMPLETED / approved

one or more recipients after filtering
  -> persist immutable approved MoM and recipient results
  -> compose email from approved content
  -> submit to local SMTP
  -> COMPLETED / delivered only after SMTP acceptance
```

No `/approve-and-deliver` or separate delivery action exists.

## Recipient policy

The backend normalizes and deduplicates addresses. Addresses outside the
configured allowed domains, malformed addresses, and unsupported addresses are
softly skipped: approval continues, skipped values are returned in
`skippedRecipients`, and only accepted addresses enter SMTP. Demo and mock
addresses use `@medpark.test`, matching Mailpit.

The browser picker helps users choose compatible addresses, but backend
filtering remains authoritative.

## Approval and delivery persistence

`mom/approved.json` is a new-contract-only immutable artifact containing the
approved document, accepted `recipients`, and `skippedRecipients`. Compatibility
with older approved artifacts is intentionally not maintained while the product
is pre-live.

`delivery/result.json` stores only delivery metadata: status, stable
Message-ID, attempt time, recipient count, and a safe error code. It contains no
MoM body or credentials.

An identical replay is idempotent. If local SMTP failed, the same `/approve`
request retries the same document, recipients, sender, and Message-ID. A changed
document or recipient result after approval returns `APPROVAL_CONFLICT`.

## Sender and message

The browser never supplies `From`. The backend uses the submitting-author email
already stored in job state only when its user ID and email match the configured
demo identity.

The message is a deterministic text representation of the approved subject,
date, summary, participants mentioned, topics, findings, decisions, actions,
risks, and open questions. Empty sections are omitted and no missing metadata
is invented.

The current PDF is produced by browser print and is not attached. Attachment
support begins only after a server-readable PDF/DOCX artifact contract exists.

## Portal behavior

The existing recipient picker is displayed in the Review bottom bar. The same
store action and API method handle both branches:

- no selected recipients: **Approve and download**;
- one or more selected recipients: **Approve and send**.

The Done screen says **No email sent** for the first branch and **Approved and
sent** with the locally accepted recipient count for the second. If SMTP fails,
the approved review becomes read-only, its recipients remain selected, and the
same action retries `/approve`.
