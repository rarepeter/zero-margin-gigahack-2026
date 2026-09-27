from __future__ import annotations

from email.message import EmailMessage

import pytest

from secure_mom_pipeline.mail_adapter import (
    LocalMailMessage,
    MailAdapterError,
    SmtpMailAdapter,
)


class FakeSmtp:
    def __init__(self, refused: dict[str, object] | None = None) -> None:
        self.refused = refused or {}
        self.ehlo_calls = 0
        self.starttls_calls = 0
        self.sent: tuple[EmailMessage, str, list[str]] | None = None

    def __enter__(self) -> FakeSmtp:
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        return None

    def ehlo(self) -> None:
        self.ehlo_calls += 1

    def starttls(self, *, context: object) -> None:
        assert context is not None
        self.starttls_calls += 1

    def send_message(
        self,
        message: EmailMessage,
        from_addr: str,
        to_addrs: list[str],
    ) -> dict[str, object]:
        self.sent = (message, from_addr, to_addrs)
        return self.refused


class FakeSmtpFactory:
    def __init__(self, client: FakeSmtp) -> None:
        self.client = client
        self.calls: list[tuple[str, int, float]] = []

    def __call__(self, host: str, port: int, timeout: float) -> FakeSmtp:
        self.calls.append((host, port, timeout))
        return self.client


def test_mailpit_adapter_uses_configured_loopback_smtp_without_starttls() -> None:
    client = FakeSmtp()
    factory = FakeSmtpFactory(client)
    adapter = SmtpMailAdapter(
        host="127.0.0.1",
        port=1025,
        timeout_seconds=5.0,
        use_starttls=False,
        smtp_factory=factory,
    )

    receipt = adapter.send(
        LocalMailMessage(
            sender="demo@medpark.test",
            recipients=("reviewer@medpark.test",),
            subject="Secure MOM draft ready",
            text_body="Review the local draft.",
            html_body="<p>Review the local draft.</p>",
            message_id="<job-123@secure-mom.local>",
        )
    )

    assert factory.calls == [("127.0.0.1", 1025, 5.0)]
    assert client.ehlo_calls == 1
    assert client.starttls_calls == 0
    assert client.sent is not None
    message, sender, recipients = client.sent
    assert sender == "demo@medpark.test"
    assert recipients == ["reviewer@medpark.test"]
    assert message["Message-ID"] == "<job-123@secure-mom.local>"
    assert message.get_body(preferencelist=("plain",)).get_content().strip() == "Review the local draft."
    assert receipt.message_id == "<job-123@secure-mom.local>"
    assert receipt.recipient_count == 1


def test_adapter_can_enable_starttls_when_configured_for_a_future_local_server() -> None:
    client = FakeSmtp()
    adapter = SmtpMailAdapter(
        host="127.0.0.1",
        port=1025,
        timeout_seconds=5.0,
        use_starttls=True,
        smtp_factory=FakeSmtpFactory(client),
    )

    adapter.send(
        LocalMailMessage(
            sender="demo@medpark.test",
            recipients=("reviewer@medpark.test",),
            subject="Local test",
            text_body="Safe test content.",
        )
    )

    assert client.starttls_calls == 1
    assert client.ehlo_calls == 2


def test_adapter_rejects_refused_recipients_without_claiming_delivery() -> None:
    adapter = SmtpMailAdapter(
        host="127.0.0.1",
        port=1025,
        timeout_seconds=5.0,
        use_starttls=False,
        smtp_factory=FakeSmtpFactory(FakeSmtp({"reviewer@medpark.test": object()})),
    )

    with pytest.raises(MailAdapterError) as error:
        adapter.send(
            LocalMailMessage(
                sender="demo@medpark.test",
                recipients=("reviewer@medpark.test",),
                subject="Local test",
                text_body="Safe test content.",
            )
        )

    assert error.value.retryable is False


@pytest.mark.parametrize(
    "message",
    [
        LocalMailMessage("sender@medpark.test", (), "Subject", "Body"),
        LocalMailMessage("sender@medpark.test", ("recipient@medpark.test",), "Bad\nSubject", "Body"),
    ],
)
def test_adapter_rejects_invalid_local_message_before_opening_smtp(
    message: LocalMailMessage,
) -> None:
    factory = FakeSmtpFactory(FakeSmtp())
    adapter = SmtpMailAdapter(
        host="127.0.0.1",
        port=1025,
        timeout_seconds=5.0,
        use_starttls=False,
        smtp_factory=factory,
    )

    with pytest.raises(ValueError):
        adapter.send(message)

    assert factory.calls == []
