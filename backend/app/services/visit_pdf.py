"""One-page printable doctor visit summary, built only from recorded data.

It states what was recorded and by whom; it draws no medical conclusions. Lists are
capped so the summary always fits on one A4 page (tested with maximum-length inputs).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

from fpdf import FPDF

ASSETS = Path(__file__).resolve().parent.parent / "assets"
NAVY = (16, 42, 67)
TEAL = (11, 92, 88)
INK = (29, 43, 54)
MUTED = (82, 97, 107)
RULE = (214, 221, 218)


@dataclass(frozen=True)
class Limits:
    meds: int
    history: int
    appts: int
    questions: int
    allergies: int
    bullet_chars: int
    cell_chars: int


# Tried in order until the summary fits on one page. Typical records fit at the first level;
# the later levels only engage for unusually long or numerous entries.
LEVELS = (
    Limits(10, 6, 3, 6, 6, 150, 90),
    Limits(8, 4, 3, 4, 4, 110, 60),
    Limits(6, 3, 2, 3, 3, 80, 40),
    Limits(4, 2, 1, 2, 2, 60, 24),
)


@dataclass
class MedLine:
    name: str
    strength: str
    dose: str
    schedule: str
    instructions: str


@dataclass
class VisitData:
    patient_name: str
    date_of_birth: date | None
    phone: str
    primary_doctor: str
    allergies: list[str]
    history: list[str]
    medications: list[MedLine]
    adherence_line: str
    adherence_basis: str
    appointments: list[str]
    questions: list[str]
    generated_at: datetime
    generated_by: str


def _clip(text: str, limit: int) -> str:
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def _age(dob: date, today: date) -> int:
    return today.year - dob.year - ((today.month, today.day) < (dob.month, dob.day))


class _Doc(FPDF):
    def footer(self) -> None:
        self.set_y(-14)
        self.set_font("Atkinson", "", 7.5)
        self.set_text_color(*MUTED)
        self.multi_cell(
            0,
            3.6,
            "Prepared from information recorded in ElderCare by the patient "
            "and their care circle. It is not a clinical record and contains no "
            "diagnosis or treatment advice. Please verify medicines with the "
            "patient and pharmacy.",
            align="C",
        )


def _section(pdf: FPDF, title: str) -> None:
    pdf.ln(2.5)
    pdf.set_font("Atkinson", "B", 10.5)
    pdf.set_text_color(*TEAL)
    pdf.cell(0, 6, title.upper(), new_x="LMARGIN", new_y="NEXT")
    pdf.set_draw_color(*RULE)
    pdf.line(pdf.l_margin, pdf.get_y(), pdf.w - pdf.r_margin, pdf.get_y())
    pdf.ln(1.2)
    pdf.set_text_color(*INK)


def _bullets(
    pdf: FPDF, items: list[str], empty: str, cap: int, more_hint: str, chars: int = 150
) -> None:
    pdf.set_font("Atkinson", "", 9.5)
    if not items:
        pdf.set_text_color(*MUTED)
        pdf.cell(0, 5, empty, new_x="LMARGIN", new_y="NEXT")
        pdf.set_text_color(*INK)
        return
    for item in items[:cap]:
        pdf.multi_cell(0, 4.8, f"•  {_clip(item, chars)}", new_x="LMARGIN", new_y="NEXT")
    if len(items) > cap:
        pdf.set_text_color(*MUTED)
        pdf.cell(
            0,
            4.8,
            f"+ {len(items) - cap} more {more_hint} in ElderCare",
            new_x="LMARGIN",
            new_y="NEXT",
        )
        pdf.set_text_color(*INK)


def _render(data: VisitData, lim: Limits) -> FPDF:
    pdf = _Doc(format="A4")
    pdf.set_margins(16, 14, 16)
    pdf.set_auto_page_break(True, margin=18)
    pdf.add_font("Atkinson", "", str(ASSETS / "AtkinsonHyperlegible-Regular.ttf"))
    pdf.add_font("Atkinson", "B", str(ASSETS / "AtkinsonHyperlegible-Bold.ttf"))
    pdf.set_title(f"Visit summary - {data.patient_name}")
    pdf.set_author("ElderCare")
    pdf.add_page()

    # Header
    pdf.set_fill_color(*NAVY)
    pdf.rect(0, 0, pdf.w, 26, style="F")
    pdf.set_xy(16, 7)
    pdf.set_text_color(255, 255, 255)
    pdf.set_font("Atkinson", "B", 16)
    pdf.cell(110, 8, "Doctor visit summary")
    pdf.set_font("Atkinson", "", 9)
    pdf.cell(
        0,
        8,
        f"Prepared {data.generated_at:%d %b %Y, %H:%M}",
        align="R",
        new_x="LMARGIN",
        new_y="NEXT",
    )
    pdf.set_x(16)
    pdf.cell(
        0,
        5,
        f"By {_clip(data.generated_by, 60)} via ElderCare",
        align="R",
        new_x="LMARGIN",
        new_y="NEXT",
    )
    pdf.set_y(31)

    # Patient block
    pdf.set_text_color(*INK)
    pdf.set_font("Atkinson", "B", 14)
    pdf.cell(0, 7, _clip(data.patient_name, 70), new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Atkinson", "", 9.5)
    facts = []
    if data.date_of_birth:
        facts.append(
            f"Born {data.date_of_birth:%d %b %Y} (age "
            f"{_age(data.date_of_birth, data.generated_at.date())})"
        )
    if data.phone:
        facts.append(f"Phone {data.phone}")
    if data.primary_doctor:
        facts.append(f"Primary doctor: {data.primary_doctor}")
    pdf.set_text_color(*MUTED)
    pdf.multi_cell(
        0,
        4.8,
        _clip("   |   ".join(facts) or "No personal details recorded", 220),
        new_x="LMARGIN",
        new_y="NEXT",
    )
    pdf.set_text_color(*INK)

    _section(pdf, "Allergies")
    _bullets(
        pdf, data.allergies, "No allergies recorded.", lim.allergies, "allergies", lim.bullet_chars
    )

    _section(pdf, "Current medicines (as recorded)")
    if data.medications:
        pdf.set_font("Atkinson", "", 8.8)
        with pdf.table(
            col_widths=(34, 20, 22, 40, 62),
            line_height=4.6,
            text_align="LEFT",
            borders_layout="HORIZONTAL_LINES",
            first_row_as_headings=False,
        ) as table:
            head = table.row()
            pdf.set_font("Atkinson", "B", 8.8)
            for h in ("Medicine", "Strength", "Dose", "Schedule", "Instructions"):
                head.cell(h)
            pdf.set_font("Atkinson", "", 8.8)
            for m in data.medications[: lim.meds]:
                row = table.row()
                row.cell(_clip(m.name, min(40, lim.cell_chars)))
                row.cell(_clip(m.strength, min(18, lim.cell_chars)))
                row.cell(_clip(m.dose, min(22, lim.cell_chars)))
                row.cell(_clip(m.schedule, min(48, lim.cell_chars)))
                row.cell(_clip(m.instructions, lim.cell_chars))
        if len(data.medications) > lim.meds:
            pdf.set_text_color(*MUTED)
            pdf.cell(
                0,
                4.8,
                f"+ {len(data.medications) - lim.meds} more medicines in ElderCare",
                new_x="LMARGIN",
                new_y="NEXT",
            )
            pdf.set_text_color(*INK)
    else:
        _bullets(pdf, [], "No current medicines recorded.", 0, "")

    _section(pdf, "Medicine-taking record (last 30 days)")
    pdf.set_font("Atkinson", "B", 9.5)
    pdf.multi_cell(
        0, 4.8, _clip(data.adherence_line, 2 * lim.bullet_chars), new_x="LMARGIN", new_y="NEXT"
    )
    pdf.set_font("Atkinson", "", 8.5)
    pdf.set_text_color(*MUTED)
    pdf.multi_cell(
        0, 4.2, _clip(data.adherence_basis, 2 * lim.bullet_chars), new_x="LMARGIN", new_y="NEXT"
    )
    pdf.set_text_color(*INK)

    _section(pdf, "Medical history")
    _bullets(pdf, data.history, "No history recorded.", lim.history, "entries", lim.bullet_chars)

    _section(pdf, "Upcoming appointments")
    _bullets(
        pdf,
        data.appointments,
        "No upcoming appointments.",
        lim.appts,
        "appointments",
        lim.bullet_chars,
    )

    _section(pdf, "Questions and notes for the doctor")
    _bullets(
        pdf, data.questions, "No questions prepared.", lim.questions, "questions", lim.bullet_chars
    )

    return pdf


def render(data: VisitData) -> bytes:
    pdf = _render(data, LEVELS[0])
    for lim in LEVELS[1:]:
        if pdf.page_no() == 1:
            break
        pdf = _render(data, lim)
    return bytes(pdf.output())
