"""Explicit real tests to locally allowlisted contacts. Never called by the scheduler."""
import json
import os
from uuid import uuid4

from fastapi import HTTPException

from app import notifications as n, smtp_service


def readiness():
    return {"email": smtp_service.configured(),
            "sms": smtp_service.configured() and any(c["channel"] == "sms" and valid_gateway(c.get("gateway_address", "")) for c in n.contacts())}


def valid_gateway(address):
    return isinstance(address, str) and address.count("@") == 1 and all(address.split("@")) and not any(ch.isspace() for ch in address) and not any(ch in address for ch in "<>,;")


def deliver(contact, body):
    if contact["channel"] == "email":
        return smtp_service.send_email(contact["address"], body)
    if contact["channel"] == "sms" and valid_gateway(contact.get("gateway_address", "")):
        result = smtp_service.send_email(contact["gateway_address"], body)
        if result["status"] == "provider_accepted":
            result["detail"] = "Email accepted by SMTP for the SMS gateway; text delivery to the phone is not confirmed."
        return result
    raise HTTPException(422, "SMS requires a configured gateway email address from your gateway account.")


def send_tests(pid, req):
    with n.transaction() as s:
        row, p = n.require_package(s, pid)
        previous = next((b for b in p.get("real_tests", []) if b["request_id"] == req.request_id), None)
        if previous:
            return previous  # Never retransmit on duplicate requests, timeout or browser retry.
        if p["version"] != req.version:
            raise HTTPException(409, "Draft changed; review again before real testing")
        g = next((g for g in p["groups"] if g["id"] == req.group_id), None)
        if not g or not g["approved"] or p["status"] == "superseded":
            raise HTTPException(422, "Review and approve the selected draft first")
        contact_map = {c["id"]: c for c in n.contacts()}
        if not req.contact_ids or not set(req.contact_ids).issubset(contact_map):
            raise HTTPException(422, "Select configured test contacts")
        selected = [contact_map[cid] for cid in dict.fromkeys(req.contact_ids)]
        if any(c["channel"] == "sms" and not valid_gateway(c.get("gateway_address", "")) for c in selected):
            raise HTTPException(422, "SMS requires a configured gateway email address from your gateway account.")
        ready = readiness()
        if any(not ready[c["channel"]] for c in selected):
            raise HTTPException(422, "Real delivery is not configured for these channels. Add SMTP settings to .env and restart the API.")
        batch = {"id": uuid4().hex, "request_id": req.request_id, "actor": req.actor,
                 "messages": [{"contact_id": c["id"], "channel": c["channel"], "address": c["address"],
                               "gateway_address": c.get("gateway_address", ""),
                               "body": "TEST ONLY — NOT AN ACTUAL CLOSURE.\n" + n.message_text(p, g, c["channel"], c["name"]),
                               "status": "sending"} for c in selected]}
        p.setdefault("real_tests", []).append(batch)
        p["version"] += 1
        n.audit(s, p, "real_test_authorized", req.actor, batch)
        n.store(s, row, p)
    # Network calls happen outside the database transaction. No automatic retries.
    for message, contact in zip(batch["messages"], selected):
        try:
            outcome = deliver(contact, message["body"])
        except Exception:
            outcome = {"status": "delivery_unknown", "detail": "Provider connection failed. Check provider logs before a new test; automatic retry is disabled."}
        with n.transaction() as s:
            row, p = n.require_package(s, pid)
            saved = next(b for b in p["real_tests"] if b["request_id"] == req.request_id)
            m = next(m for m in saved["messages"] if m["contact_id"] == contact["id"])
            m.update(outcome)
            p["version"] += 1
            n.audit(s, p, "real_test_attempt", req.actor, m)
            n.store(s, row, p)
        message.update(outcome)
    return batch
