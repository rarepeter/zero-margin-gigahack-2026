"""Replaceable local SMTP boundary for Secure MOM mail delivery.

This module deliberately uses the standard SMTP protocol only. It does not
call Mailpit's HTTP API and it has no relay, forwarding, or cloud-mail code.
Workflow and state ownership remain outside this module; this boundary only
builds and submits one already-authorized local message.
"""

from __future__ import annotations

import smtplib
import ssl
from dataclasses import dataclass
from email.message import EmailMessage
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from .config import Settings


class MailAdapterError(RuntimeError):
    """SMTP submission failure with a safe retry classification."""

    def __init__(self, message: str, *, retryable: bool) -> None:
        super().__init__(message)
        self.retryable = retryable


@dataclass(frozen=True, slots=True)
class LocalMailMessage:
    """A fully formed message supplied by a notification or delivery flow."""

    sender: str
    recipients: tuple[str, ...]
    subject: str
    text_body: str
    message_id: str | None = None
    html_body: str | None = None


@dataclass(frozen=True, slots=True)
class MailSubmission:
    """Metadata returned after the configured SMTP server accepted a message."""

    message_id: str | None
    recipient_count: int


class LocalMailAdapter(Protocol):
    """Boundary implemented by SMTP and deterministic test adapters."""

    def send(self, message: LocalMailMessage) -> MailSubmission: ...


class SmtpConnection(Protocol):
    def __enter__(self) -> SmtpConnection: ...

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None: ...

    def ehlo(self) -> object: ...

    def starttls(self, *, context: ssl.SSLContext) -> object: ...

    def send_message(
        self,
        message: EmailMessage,
        from_addr: str,
        to_addrs: list[str],
    ) -> dict[str, object]: ...


class SmtpFactory(Protocol):
    def __call__(self, host: str, port: int, timeout: float) -> SmtpConnection: ...


def _validate_header(value: str, name: str) -> str:
    if not value.strip():
        raise ValueError(f"{name} must not be empty")
    if "\r" in value or "\n" in value:
        raise ValueError(f"{name} must not contain a line break")
    return value


def _build_message(message: LocalMailMessage) -> EmailMessage:
    sender = _validate_header(message.sender, "sender")
    subject = _validate_header(message.subject, "subject")
    if not message.recipients:
        raise ValueError("at least one recipient is required")
    recipients = tuple(_validate_header(value, "recipient") for value in message.recipients)
    if not message.text_body:
        raise ValueError("text_body must not be empty")

    email = EmailMessage()
    email["From"] = sender
    email["To"] = ", ".join(recipients)
    email["Subject"] = subject
    if message.message_id is not None:
        email["Message-ID"] = _validate_header(message.message_id, "message_id")
    email.set_content(message.text_body)
    if message.html_body is not None:
        email.add_alternative(message.html_body, subtype="html")
    return email


class SmtpMailAdapter:
    """Submit messages to a configured local SMTP server with bounded I/O."""

    def __init__(
        self,
        *,
        host: str,
        port: int,
        timeout_seconds: float,
        use_starttls: bool,
        smtp_factory: SmtpFactory = smtplib.SMTP,
    ) -> None:
        if not host.strip():
            raise ValueError("mail host must not be empty")
        if not 1 <= port <= 65535:
            raise ValueError("mail port must be between 1 and 65535")
        if not 0 < timeout_seconds <= 60:
            raise ValueError("mail timeout must be greater than zero and no greater than 60")
        self._host = host
        self._port = port
        self._timeout_seconds = timeout_seconds
        self._use_starttls = use_starttls
        self._smtp_factory = smtp_factory

    @classmethod
    def from_settings(cls, settings: Settings) -> SmtpMailAdapter:
        return cls(
            host=settings.mail_host,
            port=settings.mail_port,
            timeout_seconds=settings.mail_timeout_seconds,
            use_starttls=settings.mail_use_starttls,
        )

    def send(self, message: LocalMailMessage) -> MailSubmission:
        email = _build_message(message)
        try:
            with self._smtp_factory(
                self._host,
                self._port,
                self._timeout_seconds,
            ) as client:
                client.ehlo()
                if self._use_starttls:
                    client.starttls(context=ssl.create_default_context())
                    client.ehlo()
                refused = client.send_message(
                    email,
                    from_addr=message.sender,
                    to_addrs=list(message.recipients),
                )
        except smtplib.SMTPRecipientsRefused as exc:
            raise MailAdapterError("The local SMTP server rejected all recipients.", retryable=False) from exc
        except (OSError, TimeoutError, smtplib.SMTPException) as exc:
            raise MailAdapterError("The local SMTP submission failed.", retryable=True) from exc

        if refused:
            raise MailAdapterError("The local SMTP server rejected one or more recipients.", retryable=False)
        return MailSubmission(
            message_id=message.message_id,
            recipient_count=len(message.recipients),
        )


def make_local_mail_adapter(settings: Settings) -> LocalMailAdapter:
    """Create the configured SMTP adapter without coupling the caller to Mailpit."""

    return SmtpMailAdapter.from_settings(settings)
