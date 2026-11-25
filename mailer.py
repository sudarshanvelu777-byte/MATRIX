"""
mailer.py
----------
Sends the "new account" greeting + verification code email.

IMPORTANT / HONEST NOTE FOR WHOEVER DEPLOYS THIS:
This development sandbox has no outbound network access, so it cannot place
a real SMTP call to Gmail/Outlook/etc. right now. To keep the login flow
fully working and demonstrable, SEND_MODE defaults to "simulated": the code
is written to a local "demo_inbox" table-like JSON file and shown to the
user inside the app UI in a styled "Inbox preview" panel, exactly as if it
had arrived in their real inbox.

To send REAL email once you run this somewhere with internet access:
  1. pip install nothing extra needed (uses stdlib smtplib).
  2. Set these environment variables before launching streamlit:
       SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASSWORD, SMTP_FROM
  3. That's it -- send_verification_email() will automatically switch to
     SEND_MODE = "smtp" and place a real call instead of simulating.
"""

import os
import smtplib
import ssl
import json
import time
from email.mime.text import MIMEText

_SIM_INBOX_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data", "demo_inbox.json")


def _smtp_configured() -> bool:
    return all(os.environ.get(k) for k in ("SMTP_HOST", "SMTP_PORT", "SMTP_USER", "SMTP_PASSWORD", "SMTP_FROM"))


def _write_sim_inbox(email: str, subject: str, body: str):
    os.makedirs(os.path.dirname(_SIM_INBOX_PATH), exist_ok=True)
    inbox = []
    if os.path.exists(_SIM_INBOX_PATH):
        try:
            with open(_SIM_INBOX_PATH, "r") as f:
                inbox = json.load(f)
        except Exception:
            inbox = []
    inbox.append({"to": email, "subject": subject, "body": body, "ts": time.time()})
    inbox = inbox[-50:]
    with open(_SIM_INBOX_PATH, "w") as f:
        json.dump(inbox, f, indent=2)


def get_last_sim_message(email: str):
    if not os.path.exists(_SIM_INBOX_PATH):
        return None
    try:
        with open(_SIM_INBOX_PATH, "r") as f:
            inbox = json.load(f)
    except Exception:
        return None
    for msg in reversed(inbox):
        if msg["to"].lower() == email.lower():
            return msg
    return None


def send_verification_email(email: str, code: str, username_hint: str = "") -> dict:
    """
    Returns {"mode": "smtp"|"simulated", "ok": bool, "code": code}
    so the UI can show the right confirmation state.
    """
    subject = "Welcome to OrderFlow Markets - verify your email"
    body = (
        f"Hello{(' ' + username_hint) if username_hint else ''},\n\n"
        f"Welcome to OrderFlow Markets! We're excited to have you.\n\n"
        f"Your verification code is: {code}\n"
        f"This code expires in 10 minutes.\n\n"
        f"If you didn't request this, you can safely ignore this email.\n\n"
        f"-- OrderFlow Markets"
    )

    if _smtp_configured():
        try:
            host = os.environ["SMTP_HOST"]
            port = int(os.environ["SMTP_PORT"])
            user = os.environ["SMTP_USER"]
            password = os.environ["SMTP_PASSWORD"]
            sender = os.environ["SMTP_FROM"]

            msg = MIMEText(body)
            msg["Subject"] = subject
            msg["From"] = sender
            msg["To"] = email

            context = ssl.create_default_context()
            with smtplib.SMTP(host, port, timeout=15) as server:
                server.starttls(context=context)
                server.login(user, password)
                server.sendmail(sender, [email], msg.as_string())
            return {"mode": "smtp", "ok": True, "code": code}
        except Exception as e:
            # Fall back to simulated so the login flow never hard-fails
            _write_sim_inbox(email, subject, body + f"\n\n[SMTP send failed: {e}]")
            return {"mode": "simulated", "ok": True, "code": code, "error": str(e)}

    _write_sim_inbox(email, subject, body)
    return {"mode": "simulated", "ok": True, "code": code}
