"""Email carrying an approved MoM as a PDF attachment."""

from __future__ import annotations

from .mail_adapter import LocalMailMessage, MailAttachment
from .models import DocumentLanguage, MomDocument
from .mom_pdf import LABELS, PdfFonts, format_date, pdf_filename, render_mom_pdf


def compose_approved_mom_email(
    document: MomDocument,
    *,
    recipients: list[str],
    sender: str,
    message_id: str,
    language: DocumentLanguage,
    fonts: PdfFonts,
) -> LocalMailMessage:
    """The body is a short localized note; the minutes travel only in the PDF."""

    subject = " ".join(document.header.subject.splitlines()).strip()
    body = LABELS[language].email_body.format(
        subject=subject,
        date=format_date(document.header.date),
    )
    return LocalMailMessage(
        sender=sender,
        recipients=tuple(recipients),
        subject=f"Secure MOM — {subject}",
        text_body=body,
        message_id=message_id,
        attachments=(
            MailAttachment(
                filename=pdf_filename(document, language),
                content=render_mom_pdf(document, language, fonts),
            ),
        ),
    )
