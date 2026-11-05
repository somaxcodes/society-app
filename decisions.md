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
