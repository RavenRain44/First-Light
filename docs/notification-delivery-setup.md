# SMTP email bot setup

Closure Call keeps employee delivery simulated. The separate **Send a real test**
control sends only to contacts in ignored `backend/notification-contacts.local.json`.
Every real test starts with TEST ONLY. Recording a decision never sends real messages.

## Email

Use an email sending account or service supporting authenticated SMTP. Obtain its
SMTP hostname, port, username and password (often an app password).
Put these in the repository's ignored `.env`:

```
SMTP_HOST=smtp.your-provider.example
SMTP_PORT=587
SMTP_USERNAME=your-sending-account
SMTP_PASSWORD=your-app-password
SMTP_FROM=your-verified-sender@example.com
```

Port 587 uses STARTTLS; port 465 uses implicit TLS. Certificate checks remain enabled.
Use a sender authorized by your provider. No passwords belong in commits or chat.

## Delivery policy

The SMTP service sends personalized messages only after the manager reviews and explicitly
approves the test. Select multiple local email contacts to send the group draft to
all of them. SMS can be routed through an email-to-SMS gateway account as described below.
A sending email account with SMTP credentials is required for actual delivery.

## Email-to-SMS gateway

Obtain an account with a service that accepts SMTP email and delivers SMS. Follow
its sender authorization and recipient setup, and use the destination email address
it supplies for your test phone number. This app does not create or purchase a gateway
account, and Gmail alone cannot convert email into SMS.

In ignored `backend/notification-contacts.local.json`, add `gateway_address` to the
existing SMS contact, for example:

```json
{"name": "Phone test", "channel": "sms", "address": "+15555550100", "gateway_address": "recipient-id@your-gateway.example"}
```

The example is a placeholder, not a working gateway. Never guess a carrier domain.
Use your existing Gmail SMTP sender only if the gateway accepts and authorizes it;
otherwise configure SMTP credentials required by that service. The real-test UI
shows configured gateway contacts and their route. It sends the group's short SMS
draft with a TEST ONLY prefix via email to the gateway. SMTP acceptance confirms only
email submission, not SMS delivery. Historical audit records preserve the chosen route.
Without a gateway address, phone contacts remain available only in simulation.

## Try it

1. Restart `npm run dev` after updating `.env`.
2. Record a decision and continue to **Review alerts**.
3. Expand **Send real test emails / gateway texts**.
4. Choose a group message and the test contacts to receive it.
5. Review the message and click **Approve and send real test**.

Email and explicitly configured gateway contacts appear in the real-test selector.
Use **Verify SMTP login** to test credentials without sending a message.
The main **Approve and alert people** button continues to simulate the employee
roster. Real test delivery is separate, explicit and immediate; it ignores the demo
clock and never automatically retries a network failure. Duplicate requests reuse
persisted results. Provider acceptance is shown as acceptance, not confirmed inbox
delivery. An unknown outcome requires checking provider logs before
starting a new test.

## Three-box message review and saved decisions

The top of the notification tab contains one expanded message composer: a shared
Location box, a shared Decision box, and a Personal instructions section with
separate editable instructions for each group. One collapsed recipient list
combines all groups and supports searching and selecting everyone. Location and Decision
are shared across groups; reporting instructions can be overridden per group,
including essential personnel. Edits invalidate approval and are audited. A Use
template text button restores deterministic wording. Akamai supplies a bounded
weather explanation informed by the recorded manager posture; unavailable or
rejected inference uses labeled template wording. AI receives no contact details.
The three reviewed boxes form the delivered message for both email and SMS; the
real-test channel additionally labels it TEST ONLY.

The notification decision log opens saved human decisions and their immutable
weather snapshots. Historical dashboard review pauses live weather refresh until
Return to live weather is selected. Editing notification wording does not alter
the recorded decision or weather snapshot.

## Saved camera evidence

New human decisions start a background capture of the facility's camera set
(the same nearest 20 cameras used by the dashboard). One newest available frame
at or before the decision time is saved per angle at each camera location, including its source timestamp
and URL. Replay decisions capture against the replay snapshot time. Image bytes
and camera metadata persist in SQLite independently of the live camera cache.
Completed archives cannot be replaced or deleted through normal database writes.
Historical decision review serves only these saved bytes, never live replacements.
Camera stills may be several minutes older than the decision; they are not exact
instantaneous photos. Unavailable frames are recorded as unavailable. A server
restart during capture marks the archive interrupted rather than capturing later
images. Existing decisions have no archive unless one was captured when recorded.
