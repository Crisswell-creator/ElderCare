"""ElderCare assistant: permission-aware context, safety gates and provider abstraction.

Safety is layered so it does not depend on the model behaving:
  1. Urgent-symptom messages get fixed urgent-care guidance; no model call is made.
  2. Requests to start, stop or change a medicine get a fixed referral to the prescriber,
     plus the instructions exactly as recorded; no model call is made.
  3. Everything else goes to the provider with a system prompt that forbids diagnosis and
     prescribing, and with ONLY the record sections the asking user may view.
Prompts and answers are never logged; only provider, latency and token counts are.
"""

from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any, Protocol
from zoneinfo import ZoneInfo

import requests
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import utcnow
from app.deps import PatientAccess
from app.domain import AppointmentStatus, DoseStatus, MedicationStatus, Permission
from app.logging_setup import log_event
from app.models import (
    Allergy,
    Appointment,
    Doctor,
    DoseEvent,
    HistoryEntry,
    Medication,
    VisitQuestion,
)
from app.services import adherence
from app.services.doses import slots_of
from app.services.schedule import daily_use, stock_estimate

logger = logging.getLogger("eldercare.assistant")

DISCLAIMER = (
    "ElderCare's assistant explains what is recorded and general health terms. It cannot "
    "diagnose, prescribe or change treatment. Ask a doctor, nurse or pharmacist about "
    "anything clinical."
)

URGENT = re.compile(
    r"chest pain|can'?t breathe|cannot breathe|difficulty breathing|short(ness)? of breath|"
    r"stroke|face (is )?droop|slurred speech|unconscious|not breathing|passed out|faint(ed)?|"
    r"severe bleeding|bleeding heavily|overdose|took too many|swallowed too many|suicid|"
    r"kill (my|him|her)self|seizure|fit(ting)?\b|severe allergic|anaphyla|throat (is )?swelling",
    re.IGNORECASE,
)
CLINICAL = re.compile(
    r"\b(should|can|could|may) (i|she|he|they|we|mum|mom|dad)\b.{0,40}\b(stop|quit|skip|double|"
    r"increase|decrease|reduce|halve|change|swap|add|start)\b|"
    r"\b(stop|quit|double|increase|decrease|reduce|halve|change|swap)\b.{0,30}\b(dose|dosage|"
    r"medicine|medication|tablets?|pills?)\b|\bdiagnos|what('?s| is) wrong with|"
    r"\b(prescribe|recommend) (me|a|some)\b",
    re.IGNORECASE,
)

URGENT_REPLY = (
    "This could be urgent. If someone has chest pain, trouble breathing, signs of a stroke "
    "(face drooping, arm weakness, slurred speech), heavy bleeding, a seizure, a severe "
    "allergic reaction, has taken too much medicine, or is unresponsive: call your local "
    "emergency number now (999 in the UK, 112 in the EU, 911 in the US).\n\n"
    "ElderCare has not contacted anyone. You can call your emergency contacts from the "
    "Emergency screen, and ask your care circle for help from there."
)

GLOSSARY = {
    "adherence": "Adherence means taking medicines as they were prescribed. ElderCare shows the "
    "share of recorded doses that were taken.",
    "as needed": "“As needed” (sometimes written PRN) means a medicine is taken only "
    "when required, not on a fixed schedule.",
    "prn": "PRN is Latin shorthand for “as needed”: taken only when required.",
    "refill": "A refill is a new supply of a medicine from the pharmacy, often on a repeat "
    "prescription.",
    "dosage": "Dosage is how much of a medicine is taken and how often, as set by the prescriber.",
    "side effect": "A side effect is an unwanted effect of a medicine. Report new or worrying "
    "effects to a doctor or pharmacist.",
    "grace period": "In ElderCare, the grace period is how long after a scheduled time a dose "
    "can be recorded before carers are asked to check in.",
    "unconfirmed": "An unconfirmed dose is one nobody has recorded yet. It is not assumed to "
    "be missed.",
    "blood pressure": "Blood pressure is the force of blood against artery walls, written as "
    "two numbers (for example 120/80 mmHg).",
    "type 2 diabetes": "Type 2 diabetes is a long-term condition where the body does not use "
    "insulin well, so blood sugar runs high.",
}

SYSTEM_PROMPT = """You are the ElderCare assistant, helping an older person and the family or
carers they authorised. You can see ONLY the record extract below, which the current user is
allowed to view.

Rules you must always follow:
- Never diagnose, prescribe, or suggest starting, stopping, skipping or changing any medicine
  or dose. For anything clinical, say to ask their doctor, nurse or pharmacist.
- Use only facts present in the record extract. If something is not in it, say it is not
  recorded. Never invent history, results or medicines.
- Clearly separate "In the records:" facts from general information.
- Never claim to have contacted anyone or any emergency service.
- If symptoms might be urgent, tell them to call their local emergency number.
- Be brief, warm and plain-spoken. Short sentences. No markdown tables.

Record extract (current as of {today}):
{context}
"""


@dataclass
class Context:
    text: str
    sources: list[str]
    sections: dict[str, str] = field(default_factory=dict)


def build_context(db: Session, access: PatientAccess, today: date) -> Context:
    """Collects only the sections this user may view. Never includes other members' contact
    details, document contents or access-control data."""
    p = access.patient
    pid = p.id
    sections: dict[str, str] = {}
    name = p.preferred_name or p.full_name.split(" ")[0]
    if access.can(Permission.VIEW_PROFILE):
        lines = [f"Name: {p.full_name} (called {name})"]
        if p.date_of_birth:
            age = (
                today.year
                - p.date_of_birth.year
                - ((today.month, today.day) < (p.date_of_birth.month, p.date_of_birth.day))
            )
            lines.append(f"Age: {age}")
        allergies = db.scalars(select(Allergy).where(Allergy.patient_id == pid)).all()
        lines.append(
            "Allergies: "
            + (
                "; ".join(
                    f"{a.substance}" + (f" ({a.reaction})" if a.reaction else "") for a in allergies
                )
                or "none recorded"
            )
        )
        hist = db.scalars(select(HistoryEntry).where(HistoryEntry.patient_id == pid)).all()
        lines.append(
            "Medical history: "
            + ("; ".join(f"{h.title} [{h.kind}, {h.status}]" for h in hist) or "none recorded")
        )
        docs = db.scalars(select(Doctor).where(Doctor.patient_id == pid)).all()
        if docs:
            lines.append(
                "Doctors: "
                + "; ".join(
                    f"{d.name}" + (f" ({d.specialty})" if d.specialty else "") for d in docs
                )
            )
        sections["profile"] = "\n".join(lines)
    if access.can(Permission.VIEW_MEDICATIONS):
        meds = db.scalars(
            select(Medication)
            .where(
                Medication.patient_id == pid,
                Medication.archived_at.is_(None),
                Medication.status != MedicationStatus.DISCONTINUED,
            )
            .order_by(Medication.name)
        ).all()
        lines = []
        stock_lines = []
        for m in meds:
            when = (
                "as needed"
                if m.schedule_type == "as_needed"
                else ", ".join(t.local_time.strftime("%H:%M") for t in m.times)
            )
            lines.append(
                f"- {m.name} {m.strength}: {float(m.dose_amount):g} {m.dose_unit} at {when}"
                + (f"; instructions as recorded: {m.instructions}" if m.instructions else "")
                + (f"; status {m.status}" if m.status != "active" else "")
            )
            days, run_out = stock_estimate(
                m.quantity_on_hand, daily_use(slots_of(m), m.dose_amount), today
            )
            if m.quantity_on_hand is not None:
                stock_lines.append(
                    f"- {m.name}: {float(m.quantity_on_hand):g} {m.dose_unit}(s) recorded"
                    + (
                        f", estimated to last about {int(days)} days (until about {run_out:%d %b})"
                        if days is not None and run_out
                        else ""
                    )
                )
        sections["medications"] = "\n".join(lines) or "No current medicines recorded."
        sections["stock"] = "\n".join(stock_lines) or "No stock counts recorded."
        doses = db.scalars(
            select(DoseEvent)
            .where(
                DoseEvent.patient_id == pid,
                DoseEvent.local_date == today,
                DoseEvent.status != DoseStatus.CANCELLED,
            )
            .order_by(DoseEvent.scheduled_at)
        ).all()
        sections["today"] = (
            "\n".join(f"- {d.local_time:%H:%M} {d.medication.name}: {d.status}" for d in doses)
            or "No doses scheduled today."
        )
    if access.can(Permission.VIEW_ADHERENCE):
        rep = adherence.build(db, pid, today - timedelta(days=29), today, "day")
        t = rep.totals
        lines = [
            f"Last 30 days: {t.taken} taken, {t.skipped} skipped, {t.missed} missed, "
            f"{t.unconfirmed} not confirmed"
            + (f"; {t.adherence:.0f}% of recorded doses taken" if t.adherence is not None else "")
        ]
        lines += [f"Pattern: {i['text']} ({i['basis']})" for i in adherence.insights(rep)]
        sections["adherence"] = "\n".join(lines)
    if access.can(Permission.VIEW_APPOINTMENTS):
        appts = db.scalars(
            select(Appointment)
            .where(
                Appointment.patient_id == pid,
                Appointment.status == AppointmentStatus.SCHEDULED,
                Appointment.starts_at >= utcnow(),
            )
            .order_by(Appointment.starts_at)
            .limit(5)
        ).all()
        tz = ZoneInfo(p.timezone)
        sections["appointments"] = (
            "\n".join(
                f"- {a.starts_at.astimezone(tz):%a %d %b at %H:%M} with {a.doctor_name}"
                + (f" ({a.specialty})" if a.specialty else "")
                + (f" for {a.purpose}" if a.purpose else "")
                + (f" at {a.location}" if a.location else "")
                for a in appts
            )
            or "No upcoming appointments."
        )
        qs = db.scalars(
            select(VisitQuestion).where(
                VisitQuestion.patient_id == pid, VisitQuestion.resolved_at.is_(None)
            )
        ).all()
        sections["questions"] = "\n".join(f"- {q.text}" for q in qs) or "None prepared."
    titles = {
        "profile": "Health profile",
        "medications": "Current medicines",
        "stock": "Medicine stock",
        "today": "Today's doses",
        "adherence": "Adherence",
        "appointments": "Upcoming appointments",
        "questions": "Questions for the doctor",
    }
    text = "\n\n".join(f"## {titles[k]}\n{v}" for k, v in sections.items())
    return Context(
        text=text or "No records are visible to this user.",
        sources=[titles[k] for k in sections],
        sections=sections,
    )


# ---- providers --------------------------------------------------------------------------


class Provider(Protocol):
    name: str

    def answer(self, system: str, history: list[dict[str, str]], message: str) -> str: ...


class ProviderError(Exception):
    pass


class OfflineProvider:
    """Deterministic record lookup used when no AI provider is configured or reachable.
    It only repeats recorded facts and glossary definitions; it never generates advice."""

    name = "offline"

    def __init__(self, ctx: Context) -> None:
        self.ctx = ctx

    def answer(self, system: str, history: list[dict[str, str]], message: str) -> str:
        q = message.lower()
        s = self.ctx.sections
        for term, text in GLOSSARY.items():
            if (
                f"what is {term}" in q
                or f"what does {term}" in q
                or f"meaning of {term}" in q
                or f"explain {term}" in q
            ):
                return f"General information: {text}"
        picks: list[tuple[str, str]] = []
        if re.search(r"refill|stock|run out|running out|how many (tablets|pills) left", q):
            picks.append(("Medicine stock", s.get("stock", "")))
        if re.search(r"today|now|next dose|due", q):
            picks.append(("Today's doses", s.get("today", "")))
        if re.search(r"medic|tablet|pill|dose|schedule|take", q) and not picks:
            picks.append(("Current medicines", s.get("medications", "")))
        if re.search(r"appointment|visit|doctor|clinic", q):
            picks.append(("Upcoming appointments", s.get("appointments", "")))
        if re.search(r"question", q):
            picks.append(("Questions already prepared", s.get("questions", "")))
            picks.append(("Things you might ask about", self._suggest_questions()))
        if re.search(r"adherence|missed|taken|how (is|are) .* going|doing", q):
            picks.append(("Adherence", s.get("adherence", "")))
        if re.search(r"allerg|history|condition|diagnos", q):
            picks.append(("Health profile", s.get("profile", "")))
        picks = [(t, v) for t, v in picks if v]
        if not picks:
            picks = [
                (t, v)
                for t, v in (
                    ("Current medicines", s.get("medications", "")),
                    ("Upcoming appointments", s.get("appointments", "")),
                )
                if v
            ]
        if not picks:
            return (
                "I can only see records you're allowed to view, and none match that "
                "question. Try asking about medicines, today's doses or appointments."
            )
        body = "\n\n".join(f"{t}:\n{v}" for t, v in picks)
        return f"In the records:\n\n{body}"

    def _suggest_questions(self) -> str:
        s = self.ctx.sections
        out = []
        if "Pattern:" in s.get("adherence", ""):
            out.append(
                "- The records show a pattern in missed doses. Is there a better time to "
                "take those medicines?"
            )
        if "estimated to last" in s.get("stock", ""):
            out.append("- Can repeat prescriptions be arranged before supplies run low?")
        if s.get("medications"):
            out.append(
                "- Are all current medicines still needed, and are there side effects to watch for?"
            )
        return "\n".join(out) or "- No suggestions from the records yet."


def _gemini_body(system: str, history: list[dict[str, str]], message: str) -> dict[str, Any]:
    settings = get_settings()
    contents = [
        {"role": "model" if h["role"] == "assistant" else "user", "parts": [{"text": h["content"]}]}
        for h in history
    ]
    contents.append({"role": "user", "parts": [{"text": message}]})
    return {
        "systemInstruction": {"parts": [{"text": system}]},
        "contents": contents,
        "generationConfig": {"temperature": 0.2, "maxOutputTokens": settings.ai_max_output_tokens},
    }


def _parse_gemini(data: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    try:
        parts = data["candidates"][0]["content"]["parts"]
    except (KeyError, IndexError) as exc:
        raise ProviderError("empty or blocked response") from exc
    text = "".join(p.get("text", "") for p in parts).strip()
    if not text:
        raise ProviderError("empty response")
    return text, data.get("usageMetadata", {})


class GeminiProvider:
    """Google Gemini via the Gemini API (generativelanguage.googleapis.com) with an API key
    held only on the server."""

    name = "gemini"

    def answer(self, system: str, history: list[dict[str, str]], message: str) -> str:
        s = get_settings()
        url = (
            f"https://generativelanguage.googleapis.com/v1beta/models/{s.ai_model}:generateContent"
        )
        return self._post(url, {"x-goog-api-key": s.gemini_api_key}, system, history, message)

    def _post(
        self,
        url: str,
        headers: dict[str, str],
        system: str,
        history: list[dict[str, str]],
        message: str,
    ) -> str:
        started = time.perf_counter()
        try:
            res = requests.post(
                url,
                json=_gemini_body(system, history, message),
                headers=headers,
                timeout=get_settings().ai_timeout_seconds,
            )
        except requests.RequestException as exc:
            raise ProviderError(type(exc).__name__) from exc
        if res.status_code != 200:
            raise ProviderError(f"HTTP {res.status_code}")
        text, usage = _parse_gemini(res.json())
        log_event(
            logger,
            logging.INFO,
            "assistant provider call",
            provider=self.name,
            latency_ms=round((time.perf_counter() - started) * 1000),
            prompt_tokens=usage.get("promptTokenCount"),
            output_tokens=usage.get("candidatesTokenCount"),
        )
        return text


class VertexProvider(GeminiProvider):
    """Gemini on Vertex AI, authenticated with the Cloud Run service account through
    Application Default Credentials, so no API key exists anywhere."""

    name = "vertex"

    def answer(self, system: str, history: list[dict[str, str]], message: str) -> str:
        from google.auth.exceptions import GoogleAuthError

        s = get_settings()
        try:
            creds, project = self._credentials()
        except GoogleAuthError as exc:
            raise ProviderError(type(exc).__name__) from exc
        project = s.vertex_project or project
        url = (
            f"https://{s.vertex_location}-aiplatform.googleapis.com/v1/projects/{project}"
            f"/locations/{s.vertex_location}/publishers/google/models/{s.ai_model}"
            ":generateContent"
        )
        return self._post(url, {"Authorization": f"Bearer {creds.token}"}, system, history, message)

    @staticmethod
    def _credentials() -> tuple[Any, str]:
        import google.auth
        from google.auth.transport.requests import Request

        creds, project = google.auth.default(
            scopes=["https://www.googleapis.com/auth/cloud-platform"]
        )
        creds.refresh(Request())  # type: ignore[no-untyped-call]
        return creds, str(project or "")


def provider_for(ctx: Context) -> Provider:
    s = get_settings()
    if s.ai_provider == "gemini" and s.gemini_api_key:
        return GeminiProvider()
    if s.ai_provider == "vertex":
        return VertexProvider()
    return OfflineProvider(ctx)


@dataclass
class Reply:
    answer: str
    provider: str
    sources: list[str]
    safety: str | None
    notice: str = ""


def _refers_back(message: str) -> bool:
    return bool(
        re.search(
            r"\b(it|that|this|them|so|then|should i|can i|ok|okay|yes)\b", message, re.IGNORECASE
        )
    )


def respond(
    ctx: Context,
    history: list[dict[str, str]],
    message: str,
    today: date,
    provider: Provider | None = None,
) -> Reply:
    # Earlier user turns are checked too: a clinical request split across messages, or placed
    # in client-supplied history, still gets the fixed referral.
    user_text = " ".join([message, *(h["content"] for h in history[-4:] if h["role"] == "user")])
    if URGENT.search(message):
        return Reply(URGENT_REPLY, "safety", [], "urgent")
    if CLINICAL.search(message) or (CLINICAL.search(user_text) and _refers_back(message)):
        meds = ctx.sections.get("medications")
        recorded = f"\n\nWhat's recorded for the current medicines:\n{meds}" if meds else ""
        return Reply(
            "I can't advise on starting, stopping, skipping or changing a medicine or dose, "
            "or say what might be wrong. Please ask the doctor, nurse or pharmacist who "
            "manages the prescription. If it might be urgent, call your local emergency "
            "number." + recorded,
            "safety",
            ["Current medicines"] if meds else [],
            "clinical",
        )
    chosen = provider or provider_for(ctx)
    system = SYSTEM_PROMPT.format(today=today.isoformat(), context=ctx.text)
    try:
        return Reply(chosen.answer(system, history, message), chosen.name, ctx.sources, None)
    except ProviderError as exc:
        log_event(
            logger,
            logging.WARNING,
            "assistant provider failed",
            provider=chosen.name,
            error=str(exc),
        )
        fallback = OfflineProvider(ctx)
        return Reply(
            fallback.answer(system, history, message),
            fallback.name,
            ctx.sources,
            None,
            notice="The AI service didn't respond, so this answer is a direct "
            "lookup of the records instead.",
        )
