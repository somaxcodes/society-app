# Society App: Running and Deploying

Live site: https://society-app-4t15.onrender.com
Code: https://github.com/somaxcodes/society-app

## 1. Run locally

Developed on Python 3.14. You need Python 3 and git installed.

**1. Clone the repo**

```bash
git clone https://github.com/somaxcodes/society-app.git
cd society-app
```

**2. Create the virtual environment**

```bash
python3 -m venv .venv
```

**3. Activate the virtual environment. Do this before installing anything or running the server.**

```bash
# macOS, Linux, WSL
source .venv/bin/activate

# Windows (Command Prompt or PowerShell)
.venv\Scripts\activate
```

Your prompt should now start with `(.venv)`. If it doesn't, the next steps will install into your system Python instead. Every new terminal needs this step again.

**4. Install dependencies**

```bash
pip install -r requirements.txt
```

To run the tests as well, install the test dependencies too:

```bash
pip install -r requirements.txt -r requirements-dev.txt
```

**5. Create a `.env` file in the project root**

The app reads two variables. Create the file and add these names with your own values:

```
SECRET_KEY=
GROQ_API_KEY=
```

- `SECRET_KEY` is required. The app refuses to start without it. Any long random string works.
- `GROQ_API_KEY` is optional for a first look. Without a valid key, complaints are still filed with category "other" and urgency "Medium", and the keyword safety check still works. Add a key to see real AI classification and duplicate linking.
- `.env` is in `.gitignore`. Never commit it.

**6. Start the server**

```bash
uvicorn app.main:app --reload
```

Open http://127.0.0.1:8000. On the first start, the app creates `society.db` and fills it with sample data (see section 3).

**7. Run the tests (optional)**

```bash
python -m pytest
```

The tests use their own in-memory database and fake the AI calls. They do not touch `society.db` and do not need a Groq key.

## 2. How it is deployed, and environment variables

**Hosting:** a Render web service connected to the GitHub repo.

**Render settings:**
- Build command: `pip install -r requirements.txt`
- Start command: `uvicorn app.main:app --host 0.0.0.0 --port $PORT`

**Environment variables** (set in the Render dashboard under Environment; names only):

| Name | Required | Used for |
|---|---|---|
| `SECRET_KEY` | Yes | Signing the session cookie. The app will not start without it. |
| `GROQ_API_KEY` | No, but needed for AI | Complaint classification and duplicate-complaint checks. |

No other environment variables are read.

**Auto-seed on startup.** Every time the app starts, it checks whether the database has any flats. If it is empty, it fills it with sample flats, bills, users and complaints. This is in `app/main.py` and `app/seed.py`. The seeding does not call the AI, so startup stays fast.

**No persistent disk, by design.** Render's free tier has no persistent disk, so SQLite resets on every restart or period of inactivity. This is a known constraint and not an oversight. The auto-seed above is the mitigation: the live site always shows a working, populated state instead of an empty one. The tradeoff is that anything entered live (a new complaint, a bank upload) only lasts until the next restart. That is fine for a demo review, but a production deployment would need a persistent database.

## 3. Demo logins and the sample bank statement

### Logins

Staff and resident accounts are created by the seed script.

| Role | Email | Password |
|---|---|---|
| Staff | `staff@society.com` | `staff123` |
| Resident (flat T07-1203) | `neeraj@test.com` | `resident123` |

Log in from the homepage with "Resident Login" or "Staff Login".

### Try the bank statement matching

`sample_bank_statement.csv` is in the project root. It has 15 rows written against the seeded flats. To see matching, the review queue and duplicate detection work on realistic data:

1. Log in as staff.
2. Open **Bank Upload** in the nav.
3. Choose `sample_bank_statement.csv` and click **Upload and Process**.
4. Read the result page. On a freshly seeded database you should see **6 matched, 8 needs review, 1 duplicate**.
5. Open **Review Queue** to see the 8 rows that need a person, each with the reason it wasn't matched. They include two overpayments, one payment to an already-paid flat, and five with no matching flat.
6. Open **Processed Transactions** to see the 6 matched rows and the 1 duplicate.
7. Open **Staff Dashboard** to see the collections and overdue figures change.

Upload the file only once per fresh database. A second upload marks every row as a duplicate, because duplicate detection compares reference text against everything already imported. The counts above also assume nothing else has been uploaded first.

### Optional: test the upload again from a clean slate

To run the upload again from the start, stop the server, delete `society.db`, and start the server again:

```bash
rm society.db
uvicorn app.main:app --reload
```

The app sees an empty database and reseeds it automatically. On Windows, delete `society.db` in File Explorer or with `del society.db`.
