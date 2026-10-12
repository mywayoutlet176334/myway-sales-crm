# MYWAY SALES CRM

A simple, working CRM for Myway Technology (M) Sdn Bhd. Python Flask serves four responsive pages; SQLite stores records and a private upload folder stores quotation PDFs. No WhatsApp API, background messaging, cloud database or paid service is required.

## What you can do

- **Dashboard:** follow-ups today, overdue tasks, Sent/pending quotation counts and value in RM, and won deals.
- **Customers:** add and edit name, WhatsApp number, product category, installation location, notes and customer status.
- **Quotations:** multiple quotations per customer, exact amounts in sen, Draft/Sent/Won/Lost statuses, date sent, and PDF upload/download (10 MB limit).
- **Follow Ups:** Day 2, 5 and 10 calendar-day reminders from Date Sent, ordered earliest first. Mark Done completes one reminder. Reschedule or Save Reply & Date changes its date; Snooze moves it one day later (tomorrow for an overdue reminder). Stop All ends remaining reminders for that quotation. Won/Lost and Draft statuses stop pending reminders automatically.
- **WhatsApp:** Open WhatsApp opens `wa.me` with a short editable message. You must press Send yourself. Your existing account is never accessed by the CRM. Send quotation PDFs yourself using WhatsApp Web after downloading them from the CRM.

The calendar uses **Asia/Kuala_Lumpur**, including dashboard totals and demo dates. Follow-up reminders appear inside the CRM when you open it; there are no push, email or automatic WhatsApp notifications. Multiple overdue milestones can appear for the same quotation. Reopening a quotation as Sent starts a new Day 2/5/10 schedule and clears its previous reminder rows; activity notes remain. Editing a Sent quotation does not duplicate reminders. Use Reschedule for an existing sent date.

## Run on Windows (PowerShell)

Install Python 3.12 or newer from python.org, then open PowerShell inside this repository folder. Run these commands one line at a time:

```powershell
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m flask --app app create-user owner
```

Choose your own password when prompted (at least 12 characters); there is no default password. Repeating `create-user owner` resets that account's password.

Optional: load fictional samples into an empty database before entering real customers:

```powershell
.\.venv\Scripts\python.exe -m flask --app app seed-demo
```

Start the application:

```powershell
.\.venv\Scripts\waitress-serve.exe --host=127.0.0.1 --port=5000 app:app
```

On your computer, open `http://127.0.0.1:5000` in a browser and sign in as `owner`. Keep the PowerShell window running. Press Ctrl+C to stop. Next time, only run the startup command. Loopback binding keeps this local installation off the public internet.

Demo names are labelled “Demo”; their shared WhatsApp number is fictional and must be replaced before using chat buttons. To start fresh after trying samples: stop the server, rename the entire `instance` folder to `instance-demo-backup`, then create your login again and restart. Never do this blindly to an installation containing real records.

## Run on Linux / cloud

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m flask --app app create-user owner
# Optional, empty database only:
.venv/bin/python -m flask --app app seed-demo
.venv/bin/waitress-serve --host=127.0.0.1 --port=5000 app:app
```

## Daily workflow

1. Add a customer and choose a product category.
2. Add a quotation, its amount and optional PDF.
3. Send the PDF manually using WhatsApp Web.
4. Edit the quotation: set Status to Sent and enter the actual Date Sent.
5. Open the Dashboard each working day. Open a WhatsApp chat, review the message and send it yourself. Record replies or mark reminders done.
6. Set the quotation to Won or Lost when decided; its remaining reminders stop.

## Security and storage

Login is required for every CRM page and PDF download. Passwords use Werkzeug scrypt hashing; forms have CSRF protection; sessions have an eight-hour lifetime; repeated failed logins are limited per username. Do not share account passwords. This version has one shared business workspace: every login can access every customer and quotation; no roles or separate tenants.

`instance/crm.sqlite3`, `instance/uploads/` and `instance/session.key` are created automatically, ignored by Git and must stay private. The application validates the extension and PDF header, but does not scan files for malware: upload trusted quotation PDFs only. Attachments download rather than render inline. Uploaded replacements are retained on disk for recovery; there is no automated cleanup or permanent deletion feature in this version.

To back up, stop the server and copy the entire `instance` directory to secure storage. To restore, stop the server and restore that directory. Keep backups private: SQLite and PDF files contain customer information and are not encrypted by the application. Password/session protection is not a substitute for disk encryption and access controls. No secrets belong in Git.

## Deploy later

Use a Linux host with Python 3.12+, persistent disk and HTTPS. An ephemeral hosting filesystem will lose your records. The application has no managed hosting deployment attached to this repository.

1. Install dependencies using the Linux commands above.
2. Set `CRM_DATA_DIR` to a private persistent directory, outside the public web root. Run `create-user owner` interactively under the service user. Use this same directory for every command and server start.
3. Set `CRM_HTTPS=1` when the public site is served over HTTPS; this makes session cookies HTTPS-only. Do not set it for local HTTP testing.
4. Run Waitress bound to `127.0.0.1:5000` behind an HTTPS reverse proxy (e.g. Caddy). Proxy your CRM domain to that address. Do not expose the HTTP backend directly. Configure the proxy's upload limit to at least 10 MB and add login rate limiting at the proxy for public hosting.
5. Run Waitress as a restartable system service under a dedicated user with access to the data directory. Keep the data directory and backups out of publicly served paths. Schedule private backups and dependency/security updates.
6. Verify HTTPS login, customer saving, PDF upload/download and backup restoration before entering real customer data. Never enable Flask debug mode on a public deployment.

Example service command (substitute the actual repository path):

```sh
CRM_DATA_DIR=/private/persistent/myway CRM_HTTPS=1 /path/to/myway-sales-crm/.venv/bin/waitress-serve --host=127.0.0.1 --port=5000 app:app
```

Live server processes need to restart after a cloud environment is restored. Database and uploads must be retained. This first version suits a small team on one application instance; multiple servers and large-scale reporting are outside its scope.

## Tests

```sh
.venv/bin/python -m unittest discover -s tests -v
```

Windows equivalent: `.\.venv\Scripts\python.exe -m unittest discover -s tests -v`.

Tests use isolated temporary databases and cover authentication/CSRF/login throttling, page rendering, persistence, Malaysian phone normalization, exact amounts, multiple quotations, Day 2/5/10 dates, due/overdue displays, reminder actions, Won/Lost stopping, input validation, protected PDF downloads and manual WhatsApp links. They do not send WhatsApp messages or require your account.

## WhatsApp Sales Assistant upgrade (sample mode)

Your existing CRM is preserved. New **Sales Assistant**, **Approval Queue** and **Daily Summary** pages use fictional conversations only. Load samples from the assistant page, review category/quotation suggestions, then prepare English, Chinese or Bahasa Melayu drafts. Approving a draft does not send it. There is no live WhatsApp connection or connected AI model in this stage.

Read [the integration plan and simple next steps](docs/WHATSAPP_INTEGRATION.md) for Coexistence requirements, Web/Desktop synchronization limits, costs, official onboarding stages and the 5 PM timer. For local automatic summaries, run `.venv/bin/python summary_worker.py` alongside the server (Windows: `.\.venv\Scripts\python.exe summary_worker.py`). Keep both running; an offline computer cannot generate an exact-time summary. No additional dependencies or API keys are required for sample mode.
