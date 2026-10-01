"""Deterministic PDF rendering of an approved MoM for local email delivery.

The layout mirrors the portal's print view: masthead, subject, facts,
participants, then only the non-empty MoM sections. Rendering is pure Python
(fpdf2) with local TrueType fonts, so it works offline.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path

from fpdf import FPDF, FontFace, XPos, YPos
from fpdf.errors import FPDFException

from .models import DocumentLanguage, MomDocument

Rgb = tuple[int, int, int]

TEAL: Rgb = (0, 130, 134)
INK: Rgb = (23, 50, 53)
MUTED: Rgb = (83, 103, 106)
RULE: Rgb = (214, 227, 228)
TINT: Rgb = (241, 247, 247)
FAMILY = "MomSans"


class PdfRenderError(RuntimeError):
    """The PDF could not be produced, e.g. because a configured font is missing."""


@dataclass(frozen=True, slots=True)
class PdfFonts:
    """Unicode TTF files covering Romanian diacritics and Cyrillic."""

    regular: Path
    bold: Path


@dataclass(frozen=True, slots=True)
class Labels:
    """Fixed document wording per portal language; MoM content is never translated."""

    confidential: str
    generated_locally: str
    approved: str
    meeting_type: str
    date: str
    duration: str
    participants: str
    summary: str
    topics: str
    findings: str
    decisions: str
    actions: str
    action: str
    owner: str
    due: str
    unassigned: str
    not_stated: str
    risks: str
    questions: str
    statuses: dict[str, str]
    types: dict[str, str]
    file_stem: str
    # Formatted with `subject` and `date`.
    email_body: str


LABELS: dict[DocumentLanguage, Labels] = {
    "ro": Labels(
        confidential="Proces-verbal confidențial",
        generated_locally="Generat local",
        approved="Proces-verbal aprobat",
        meeting_type="Tip",
        date="Data",
        duration="Durată",
        participants="Participanți",
        summary="Rezumat",
        topics="Subiecte-cheie discutate",
        findings="Dovezi și constatări analizate",
        decisions="Soluții adoptate",
        actions="Acțiuni următoare",
        action="Acțiune",
        owner="Responsabil",
        due="Termen",
        unassigned="Nestabilit",
        not_stated="Nespecificat",
        risks="Riscuri și preocupări",
        questions="Întrebări deschise",
        statuses={"decided": "decisă", "proposed": "doar propusă", "revoked": "revocată"},
        types={
            "medical": "Medical",
            "patient_case": "Caz clinic",
            "financial": "Financiar",
            "administrative": "Administrativ",
            "executive": "Executiv",
            "operational": "Operațional",
            "crisis": "Răspuns la criză",
            "other": "Altul",
        },
        file_stem="proces-verbal",
        email_body=(
            "Bună ziua,\n\n"
            "În atașament găsiți procesul-verbal aprobat al ședinței „{subject}” "
            "({date}), în format PDF.\n\n"
            "Documentul a fost generat local de Secure MOM și conține informații "
            "confidențiale. Nu îl redirecționați în afara instituției.\n"
        ),
    ),
    "ru": Labels(
        confidential="Конфиденциальный протокол",
        generated_locally="Создано локально",
        approved="Утверждённый протокол",
        meeting_type="Тип",
        date="Дата",
        duration="Длительность",
        participants="Участники",
        summary="Резюме",
        topics="Ключевые обсуждённые темы",
        findings="Рассмотренные данные и выводы",
        decisions="Принятые решения",
        actions="Следующие шаги",
        action="Действие",
        owner="Ответственный",
        due="Срок",
        unassigned="Не назначен",
        not_stated="Не указан",
        risks="Риски и замечания",
        questions="Открытые вопросы",
        statuses={"decided": "принято", "proposed": "только предложено", "revoked": "отменено"},
        types={
            "medical": "Медицинское",
            "patient_case": "Клинический случай",
            "financial": "Финансовое",
            "administrative": "Административное",
            "executive": "Руководство",
            "operational": "Операционное",
            "crisis": "Кризисное реагирование",
            "other": "Другое",
        },
        file_stem="protokol",
        email_body=(
            "Здравствуйте,\n\n"
            "Во вложении — утверждённый протокол совещания «{subject}» ({date}) "
            "в формате PDF.\n\n"
            "Документ создан локально системой Secure MOM и содержит "
            "конфиденциальную информацию. Не пересылайте его за пределы учреждения.\n"
        ),
    ),
    "en": Labels(
        confidential="Confidential meeting record",
        generated_locally="Generated locally",
        approved="Approved minutes",
        meeting_type="Type",
        date="Date",
        duration="Duration",
        participants="Participants",
        summary="Summary",
        topics="Key topics discussed",
        findings="Evidence and findings reviewed",
        decisions="Decisions",
        actions="Next actions",
        action="Action",
        owner="Owner",
        due="Due",
        unassigned="Not assigned",
        not_stated="Not stated",
        risks="Risks and concerns",
        questions="Open questions",
        statuses={"decided": "decided", "proposed": "only proposed", "revoked": "revoked"},
        types={
            "medical": "Medical",
            "patient_case": "Clinical case",
            "financial": "Financial",
            "administrative": "Administrative",
            "executive": "Executive",
            "operational": "Operational",
            "crisis": "Crisis response",
            "other": "Other",
        },
        file_stem="minutes",
        email_body=(
            "Hello,\n\n"
            "The approved minutes of the meeting \"{subject}\" ({date}) are attached "
            "as a PDF.\n\n"
            "This document was generated locally by Secure MOM and contains "
            "confidential information. Do not forward it outside the institution.\n"
        ),
    ),
}


def format_date(value: date) -> str:
    return value.strftime("%d.%m.%Y")


def pdf_filename(document: MomDocument, language: DocumentLanguage) -> str:
    return f"{LABELS[language].file_stem}-{document.header.date.isoformat()}.pdf"


class _MomPdf(FPDF):
    def __init__(self, labels: Labels, fonts: PdfFonts) -> None:
        super().__init__(format="A4")
        self.labels = labels
        self.add_font(FAMILY, "", str(fonts.regular))
        self.add_font(FAMILY, "B", str(fonts.bold))
        self.set_margins(left=15, top=16, right=15)
        self.set_auto_page_break(auto=True, margin=18)

    def footer(self) -> None:
        self.set_y(-12)
        self.set_font(FAMILY, "", 7.5)
        self.set_text_color(*MUTED)
        labels = self.labels
        self.cell(
            0,
            4,
            f"{labels.confidential} · {labels.generated_locally} · {labels.approved}",
        )
        self.set_x(self.l_margin)
        self.cell(0, 4, f"{self.page_no()} / {{nb}}", align="R")

    def masthead(self) -> None:
        self.set_font(FAMILY, "B", 7.8)
        self.set_text_color(*MUTED)
        self.cell(0, 5, self.labels.confidential.upper())
        self.set_x(self.l_margin)
        self.set_text_color(*TEAL)
        self.cell(0, 5, self.labels.generated_locally.upper(), align="R")
        self.ln(7)
        self.set_draw_color(*TEAL)
        self.set_line_width(0.5)
        self.line(self.l_margin, self.get_y(), self.w - self.r_margin, self.get_y())
        self.ln(7)

    def paragraph(self, text: str, *, size: float = 10.5, color: Rgb = INK, bold: bool = False) -> None:
        self.set_font(FAMILY, "B" if bold else "", size)
        self.set_text_color(*color)
        self.multi_cell(0, size * 0.5, text, align="L", new_x=XPos.LMARGIN, new_y=YPos.NEXT)

    def heading(self, title: str, *, keep_with_next: float = 22) -> None:
        # Keep a heading together with at least the first lines (mm) of its section.
        if self.will_page_break(keep_with_next):
            self.add_page()
        self.set_font(FAMILY, "B", 8.5)
        self.set_text_color(*TEAL)
        self.cell(0, 5, title.upper(), new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        self.set_draw_color(*RULE)
        self.set_line_width(0.2)
        self.line(self.l_margin, self.get_y() + 0.5, self.w - self.r_margin, self.get_y() + 0.5)
        self.ln(3)

    def bullets(self, items: list[str]) -> None:
        self.set_font(FAMILY, "", 10.5)
        for item in items:
            self.set_text_color(*TEAL)
            self.cell(4, 5.25, "•")
            self.set_text_color(*INK)
            self.multi_cell(0, 5.25, item, align="L", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
            self.ln(1.2)

    def end_section(self) -> None:
        self.ln(4)


def render_mom_pdf(document: MomDocument, language: DocumentLanguage, fonts: PdfFonts) -> bytes:
    """Render only facts already present in the approved document."""

    try:
        return _render(document, language, fonts)
    except (OSError, FPDFException) as exc:
        raise PdfRenderError("The MoM PDF could not be rendered.") from exc


def _render(document: MomDocument, language: DocumentLanguage, fonts: PdfFonts) -> bytes:
    labels = LABELS[language]
    header = document.header
    pdf = _MomPdf(labels, fonts)
    pdf.set_title(header.subject)
    pdf.set_creator("Secure MOM (local)")
    pdf.add_page()
    pdf.masthead()

    pdf.paragraph(header.subject, size=20, bold=True)
    pdf.ln(2)
    facts = [
        f"{labels.meeting_type}: {labels.types.get(header.meeting_type, header.meeting_type)}",
        f"{labels.date}: {format_date(header.date)}",
    ]
    if header.duration_min:
        facts.append(f"{labels.duration}: {header.duration_min} min")
    pdf.paragraph("   •   ".join(facts), size=9, color=MUTED)
    pdf.ln(4)

    participants = [
        f"{participant.name} — {participant.role}" if participant.role else participant.name
        for participant in header.participants_mentioned or []
    ]
    if participants:
        pdf.set_fill_color(*TINT)
        pdf.set_font(FAMILY, "", 9)
        pdf.set_text_color(*INK)
        pdf.multi_cell(
            0,
            4.8,
            f"{labels.participants}: {', '.join(participants)}",
            fill=True,
            align="L",
            padding=(3, 4),
            new_x=XPos.LMARGIN,
            new_y=YPos.NEXT,
        )
        pdf.ln(6)

    pdf.heading(labels.summary)
    pdf.paragraph(document.summary)
    pdf.end_section()

    if document.topics:
        pdf.heading(labels.topics)
        for topic in document.topics:
            pdf.paragraph(topic.title, bold=True)
            pdf.paragraph(topic.text, color=MUTED)
            pdf.ln(2)
        pdf.end_section()

    if document.findings:
        pdf.heading(labels.findings)
        pdf.bullets([finding.text for finding in document.findings])
        pdf.end_section()

    if document.decisions:
        pdf.heading(labels.decisions)
        for decision in document.decisions:
            status = labels.statuses.get(decision.status, decision.status)
            pdf.paragraph(f"{decision.id} · {status.upper()}", size=8, color=TEAL, bold=True)
            pdf.paragraph(decision.text)
            pdf.ln(2)
        pdf.end_section()

    if document.actions:
        # The table's header row plus its first row must follow the heading.
        pdf.heading(labels.actions, keep_with_next=40)
        pdf.set_font(FAMILY, "", 9.5)
        pdf.set_text_color(*INK)
        pdf.set_draw_color(*RULE)
        with pdf.table(
            col_widths=(56, 22, 22),
            line_height=5,
            padding=2,
            borders_layout="HORIZONTAL_LINES",
            headings_style=FontFace(emphasis="BOLD", color=(255, 255, 255), fill_color=INK),
        ) as table:
            heading = table.row()
            for title in (labels.action, labels.owner, labels.due):
                heading.cell(title.upper())
            for action in document.actions:
                deadline = action.deadline
                due = (
                    format_date(deadline.resolved)
                    if deadline.resolved
                    else deadline.spoken or labels.not_stated
                )
                row = table.row()
                row.cell(action.text)
                row.cell(action.owner or labels.unassigned)
                row.cell(due)
        pdf.end_section()

    if document.risks:
        pdf.heading(labels.risks)
        pdf.bullets([risk.text for risk in document.risks])
        pdf.end_section()

    if document.open_questions:
        pdf.heading(labels.questions)
        pdf.bullets([question.text for question in document.open_questions])
        pdf.end_section()

    return bytes(pdf.output())
