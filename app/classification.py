import json
import os
from datetime import datetime, timedelta

from groq import Groq

from app.models import Complaint, Flat
from app.safety_check import check_safety_flag
from dotenv import load_dotenv
load_dotenv()

SYSTEM_PROMPT = """You are classifying complaints for a residential society management app. Respond with ONLY a JSON object in this exact format, and nothing else — no explanation, no extra text:
{"category": "...", "urgency": "..."}
category must be exactly one of: plumbing, electrical, lift, security, cleaning, safety, structural, parking, noise, other
urgency must be exactly one of: Low, Medium, High
If the complaint describes more than one issue, pick whichever is more safety-critical or urgent as the single category."""

# llama-3.1-8b-instant (the model originally asked for) was retired by Groq;
# openai/gpt-oss-20b is Groq's own recommended replacement and is their
# fastest small production text model, so it's the closest equivalent.
MODEL = "openai/gpt-oss-20b"


# Classifies a complaint via the Groq API, but falls back to category="other"/
# urgency="Medium" on any failure (bad key, timeout, bad JSON, retired model,
# etc.) so a down or misbehaving API never blocks a complaint from being
# filed — and the safety override always has the final say on urgency,
# regardless of what Groq or the fallback decided.
def classify_complaint(text: str) -> dict:
    is_safety_flagged = check_safety_flag(text)

    try:
        client = Groq(api_key=os.getenv("GROQ_API_KEY"))
        response = client.chat.completions.create(
            model=MODEL,
            temperature=0,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": text},
            ],
        )
        parsed = json.loads(response.choices[0].message.content)
        category = parsed["category"]
        urgency = parsed["urgency"]
    except Exception:
        category = "other"
        urgency = "Medium"

    if is_safety_flagged:
        urgency = "High"

    return {
        "category": category,
        "urgency": urgency,
        "is_safety_flagged": is_safety_flagged,
    }


DUPLICATE_SYSTEM_PROMPT = (
    'You are checking whether two complaints to a residential society management '
    'app describe the same underlying problem. Answer with ONLY "yes" or "no", '
    "and nothing else — no explanation, no extra text."
)


# Finds the oldest still-open complaint (if any) that's probably the same
# underlying issue as the one being described in `text`: first a cheap structural
# pre-filter (same category, same tower, still open, within the last 7 days)
# narrows candidates, then one Groq call per candidate (oldest first) confirms
# it's genuinely the same issue rather than just a same-category coincidence.
# Defaults to None on any failure (API error, timeout, unexpected response) so
# a broken duplicate check never blocks a complaint from being filed.
def find_duplicate(db_session, flat, category, text, exclude_id=None):
    try:
        # "T07-1203" -> "T07" — complaints from the same tower are the ones
        # worth comparing; a lift outage in a different tower isn't the same
        # issue just because the category matches.
        tower = flat.flat_number.split("-")[0]

        cutoff = datetime.utcnow() - timedelta(days=7)

        query = (
            db_session.query(Complaint)
            .join(Flat, Complaint.flat_id == Flat.id)
            .filter(
                Complaint.category == category,
                Complaint.status.in_(["Open", "In Progress"]),
                Complaint.created_at >= cutoff,
                Flat.flat_number.like(f"{tower}-%"),
            )
        )
        if exclude_id is not None:
            query = query.filter(Complaint.id != exclude_id)

        candidates = query.order_by(Complaint.created_at.asc()).all()

        client = Groq(api_key=os.getenv("GROQ_API_KEY"))

        for candidate in candidates:
            response = client.chat.completions.create(
                model=MODEL,
                temperature=0,
                messages=[
                    {"role": "system", "content": DUPLICATE_SYSTEM_PROMPT},
                    {
                        "role": "user",
                        "content": f"Complaint A: {candidate.description}\nComplaint B: {text}",
                    },
                ],
            )
            answer = response.choices[0].message.content.strip().lower()
            if answer == "yes":
                return candidate.id

        return None
    except Exception:
        return None
