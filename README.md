# Society App

A resident society management web app. Residents view and pay maintenance bills and raise complaints, which are classified by AI. Staff match bank statement payments to flats and manage complaints.

## Links

- GitHub: https://github.com/somaxcodes/society-app
- Live (Render): https://society-app-4t15.onrender.com
- Technical design: [TDD.md](TDD.md)
- Running and deploying: [deployment.md](deployment.md)

## Quick start

```bash
git clone https://github.com/somaxcodes/society-app.git
cd society-app
python3 -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

Create a `.env` file in the project root with these two variables (add your own values):

```
SECRET_KEY=
GROQ_API_KEY=
```

Then start the server:

```bash
uvicorn app.main:app --reload
```

See [deployment.md](deployment.md) for full details.

## Demo logins

| Role | Email | Password |
|---|---|---|
| Staff | `staff@society.com` | `staff123` |
| Resident (flat T07-1203) | `neeraj@test.com` | `resident123` |
| Resident (flat T12-0408) | `swati@test.com` | `resident123` |

## Try the bank matching

`sample_bank_statement.csv` in the project root is ready to upload from the Bank Upload page (log in as staff). [deployment.md](deployment.md) has the full walkthrough.

## Tests

There are 259 passing pytest tests. Run them with `python -m pytest` (install `requirements-dev.txt` first).
