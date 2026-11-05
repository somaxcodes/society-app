# Decisions Log

## 2026-11-03
- **Stack**: FastAPI + Jinja2 + SQLite + SQLAlchemy. Reason: lightweight, no separate DB server needed, easy to deploy on Render.
- **Auth**: Email/password with hashed passwords + signed session cookie. Reason: brief asked for OTP but email/password is simpler and secure enough for a demo.
- **CSS**: Pico.css + custom CSS. Reason: mobile-friendly out of the box, no build step needed.
- **AI**: Groq API for complaint classification. Reason: brief specified it.
- **Deploy**: Render free tier. Reason: simple Git-based deploy, free.

## 2026-11-04
- Login shows the same error for "no such email" and "wrong password" — prevents attackers from discovering which emails are registered residents.

## 2026-11-04 (deploy)
- Deployed to Render: https://society-app-4t15.onrender.com
- Known limitation: free tier has no persistent disk, so SQLite resets on restart/inactivity. Fixed by auto-seeding on startup if the database is empty (see main.py).

## 2026-11-05
- Removed DB-level unique constraint on BankPayment.reference to allow storing an audit row for every CSV row, including detected duplicates. Duplicate prevention is enforced in application code (checking existing references before matching), not at the database level.

## 2026-11-05 (assumption)
- Safety-word detection (fire, gas, lift stuck, shock) is a simple, literal keyword match with no context understanding — e.g. "fire exit door is squeaky" would be flagged just like a real fire. This is intentional, for these reasons:
  - The brief requires these words to always escalate regardless of what the AI concludes ("whatever the AI says"), meaning the rule is meant to override smarter reasoning, not defer to it.
  - False positive cost is low: a staff member reads a wrongly-flagged complaint and dismisses it in seconds.
  - False negative cost is high: missing a genuinely dangerous complaint (a real gas leak, a real fire) could cause real harm.
  - Given that asymmetry, over-triggering on purpose is safer than trying to be clever and risking a miss.
- A separate visible "Safety Flagged" banner distinguishes these from ordinary High-urgency complaints, rather than relying on urgency alone.
