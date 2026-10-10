"""Authenticated SMTP service. No public relay or automatic sending."""
import os
import smtplib
import ssl
from email.message import EmailMessage


def configured():
    return all(os.getenv(k) for k in ("SMTP_HOST", "SMTP_USERNAME", "SMTP_PASSWORD", "SMTP_FROM"))


def check_connection():
    """Authenticate without submitting a message; never return credential values."""
    if not configured():
        return {"status": "not_configured", "detail": "Add SMTP credentials to local .env and restart the API."}
    stage = "connecting"
    try:
        port = int(os.getenv("SMTP_PORT", "587"))
        cls = smtplib.SMTP_SSL if port == 465 else smtplib.SMTP
        kwargs = {"context": ssl.create_default_context()} if port == 465 else {}
        with cls(os.environ["SMTP_HOST"], port, timeout=20, **kwargs) as smtp:
            if port != 465:
                stage = "starting TLS"
                smtp.starttls(context=ssl.create_default_context())
            stage = "authenticating"
            smtp.login(os.environ["SMTP_USERNAME"], os.environ["SMTP_PASSWORD"])
        return {"status": "authenticated", "detail": "SMTP login verified. No email sent."}
    except smtplib.SMTPAuthenticationError:
        return {"status": "authentication_failed", "detail": "SMTP login rejected. For Gmail, use an app password for the sender account."}
    except Exception:
        return {"status": "connection_failed", "detail": f"SMTP connection failed while {stage}. No email sent."}


def send_email(address, body):
    message = EmailMessage()
    message["From"] = os.environ["SMTP_FROM"]
    message["To"] = address
    message["Subject"] = "TEST ONLY — Closure Call notification exercise"
    message.set_content(body)
    port = int(os.getenv("SMTP_PORT", "587"))
    cls = smtplib.SMTP_SSL if port == 465 else smtplib.SMTP
    kwargs = {"context": ssl.create_default_context()} if port == 465 else {}
    with cls(os.environ["SMTP_HOST"], port, timeout=20, **kwargs) as smtp:
        if port != 465:
            smtp.starttls(context=ssl.create_default_context())
        try:
            smtp.login(os.environ["SMTP_USERNAME"], os.environ["SMTP_PASSWORD"])
        except smtplib.SMTPAuthenticationError:
            return {"status": "provider_rejected", "detail": "SMTP login rejected. For Gmail, use an app password created for the sending account, not its Google account password. No email was submitted."}
        except smtplib.SMTPServerDisconnected:
            return {"status": "provider_rejected", "detail": "SMTP disconnected during login, before any email was submitted. Check the sending account and app password."}
        refused = smtp.send_message(message)
        if refused:
            return {"status": "provider_rejected", "detail": "Email provider refused recipient."}
    return {"status": "provider_accepted", "detail": "Email accepted by SMTP server; inbox delivery is not confirmed."}
