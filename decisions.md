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

## 2026-11-06 (check_safety_flag)
- **What it does**: `app/safety_check.py`'s `check_safety_flag(text)` takes a complaint's raw text and returns `True`/`False` for whether it should be flagged as a safety emergency, using plain keyword matching — no AI call, no external dependency.
- **Why it exists**: it's a deterministic safety net that runs independently of the AI classification call. The brief's own wording is "fire, gas, lift stuck, shock... whatever the AI says" — meaning these specific danger signals are meant to escalate regardless of what the AI concludes, and critically, regardless of whether the AI call even succeeds. If the Groq API is down, rate-limited, or returns something unexpected, this function still runs and still catches the obvious cases.
- **How it works**:
  - **Standalone words vs. paired words**: most danger words — fire, shock, smoke, weapon, assault, intruder, unconscious, bleeding, flooding, collapse, trapped, electrocuted — are dangerous on their own, so a single hit returns `True` immediately. A few concepts are only dangerous in combination: "lift" alone (a lift that works fine) or "stuck" alone (stuck in traffic) aren't emergencies, but "lift" + "stuck" together is; same for "gas" + "leak"/"smell", and "wire" + "spark".
  - **Why "live" specifically needed pair logic, not standalone**: "live" is a real false-positive risk — "I **live** in flat T07-1203, my tap is leaking" is an ordinary complaint that happens to contain the word "live". Standalone matching on "live" would wrongly flag every resident who uses that word to describe where they live. Pairing it with "wire"/"wires"/"wyre" (a live wire being the actual hazard) means "live" only counts when something electrical is also mentioned.
  - **Misspelling variants**: each danger word has a short list of common misspellings/typos (e.g. "shock" also matches "shok", "shocked", "shoked") so a rushed or non-native-English complaint still gets caught.
  - **Squished-text check**: in addition to the normal lowercased text, a second version strips out spaces and common punctuation (`. - , _ ! ? ; :`). This catches words broken up by spacing or punctuation — "g.as le-ak" or "f,i,r,e" — that wouldn't otherwise appear as a clean substring.
  - **Manual stemming for word tenses**: a few entries use a hand-picked "bare stem" instead of (or in addition to) the full word, so one list entry covers multiple tenses — "collaps" catches "collapse", "collapsed", AND "collapsing"; "trap" catches "trap", "trapped", AND "trapping"; "electrocut" catches "electrocuted" AND "electrocuting". Irregular forms that no stem trick covers (like "bled", the past tense of "bleed") are just added as their own explicit variant.
  - **Why a stemming library was deliberately avoided**: a real stemmer (e.g. Porter/Snowball) operates on the whole vocabulary with generic suffix-stripping rules, which can produce unpredictable collisions on words we never intended to match — the classic example being "universe" and "university" stemming to the same root. For this function's small, fixed list of maybe a dozen danger words, hand-picking a safe stem for each one is easy to verify, easy to extend, and has zero risk of an unrelated word accidentally matching.

## 2026-11-06 (complaint categories and duplicate linking)
- **Why the category list was expanded**: the original six categories (plumbing, electrical, lift, security, cleaning, other) had nowhere good to put a lot of real complaints — a gas leak complaint in particular had no honest home among them and would have been forced into "other," burying a genuinely dangerous report under a catch-all label a staff member has no reason to prioritize checking. Added `safety`, `structural`, `parking`, and `noise` so these common, distinct complaint types get their own routing lane instead of collapsing into "other."
- **Why one category per complaint, not multiple**: real support/ticketing systems (Zendesk, Jira Service Desk) face the same situation constantly — a single ticket describing more than one issue — and the standard answer isn't to tag it with every category that applies. It gets filed under one category for routing purposes, the full original text stays visible to whoever picks it up, and it only gets manually split into separate tickets if that's genuinely necessary for tracking two unrelated pieces of work. We're following that same pattern: `classify_complaint` picks a single category, and the prompt tells the model to prefer whichever issue is more safety-critical or urgent when a complaint mixes more than one.
  - Critically, category is just a routing label, not a safety mechanism. Urgency and the safety-word check (`check_safety_flag`) both run against the complaint's full text independently of whatever category got picked, so a second, more dangerous issue mentioned in the same complaint is never silently downgraded just because the category field only has room for one value — the urgency and safety flag still reflect the worst thing actually described.
- **How duplicate linking works**: `find_duplicate` runs a cheap structural pre-filter first — same category, same tower (parsed from the flat number, e.g. "T07" from "T07-1203"), still "Open" or "In Progress," and reported within the last 7 days — to narrow a potentially large complaints table down to a handful of plausible candidates without spending an API call on any of it. Only then does it spend one Groq call per remaining candidate (oldest first), asking specifically whether the two complaints describe the same underlying problem — because two complaints can share a category and tower by pure coincidence (two different plumbing issues in the same building in the same week), and only a real comparison of the two descriptions can tell those apart from an actual duplicate.
- **Why linking points to the oldest matching open complaint, not the most recent**: this keeps the data shape a star, not a chain — every duplicate's `linked_to_id` points straight back to the one original report, instead of each new duplicate linking to whichever one came right before it. That means "show me everything tied to this issue" is one simple query (`WHERE linked_to_id = X OR id = X`), instead of having to walk a chain of links one hop at a time to find them all.

## 2026-11-07
- There's no separate committee role in this build — the "committee dashboard" is the same staff dashboard page. The Core build brief only specifies resident and help-desk staff roles, so a third role wasn't built.
