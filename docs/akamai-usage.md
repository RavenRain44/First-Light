# Closure Call on Akamai

Closure Call helps a facility manager decide when dangerous weather warrants delayed arrival, early dismissal,
telework or closure. Akamai summarizes the recorded evidence, explains the rules' recommendation, highlights
uncertainty, summarizes alerts, and identifies what to watch. The manager accepts or overrides the recommendation
with a reason. Neither the model nor this integration makes or records a human decision automatically.

## Inference setup

Follow the [Hack Midwest workshop inference reference](https://github.com/akamai-developers/akamai-workshop-hackmidwest/blob/main/docs/inference.md).
The service is OpenAI-compatible, hosted on Akamai Cloud, and uses these exact workshop values:

- Base URL: `https://ws.akamai-workshops.com/v1`
- Chat endpoint: `POST /v1/chat/completions`
- Model alias: `hackathon-chat` (the workshop controls the backing model)
- Authentication: backend-only `Authorization: Bearer <team key>`
- Structured output: `response_format.type=json_schema`, validated with Pydantic

The OpenAI SDK here is a protocol client to Akamai, not an OpenAI inference provider. The old Anthropic,
OpenAI-provider and direct Bedrock-provider switches have been removed.

Copy `.env.example` to ignored `.env` if needed, and enter `AKAMAI_API_KEY` securely. Keep `MODEL_PROVIDER=akamai`
and `AWS_FALLBACK_ENABLED=false` for judging. No key is shipped in the repository or browser bundle.
Allow HTTPS egress to `ws.akamai-workshops.com`. Live weather additionally requires `api.weather.gov` and
`mesonet.agron.iastate.edu`.

From the repository root:

```bash
npm run setup
DEMO_MODE=true npm run dev
```

`DEMO_MODE=true` uses cached weather, but AI still calls Akamai. To run entirely offline, also set
`MODEL_PROVIDER=none`. Live Check always calls NWS, including in weather demo mode.
Use **Re-evaluate now** for a new live decision brief. Replay playback reuses recorded backtest data without
model calls; pause at an hour and click **Generate Akamai brief** for a fresh, recorded Akamai interpretation.
Existing immutable snapshots keep their original provider and are never relabeled as Akamai output.

After recording a decision, **Send notifications** creates an editable draft. Akamai supplies only a short
weather sentence from the snapshot's hazard names and severity levels. Employee names, contacts, recipient
selection and reporting instructions stay outside inference. The recorded manager decision determines the
notification status, including overrides of the AI brief. Each group requires manager review and approval
before dispatch. The default delivery provider is simulation; generating a draft transmits no messages.
Notification drafts show **Powered by Akamai** only after validation and retain `draft_inference` provider,
token usage and safe failure details in the package and creation audit. Reopening an existing draft makes no
additional inference call. Existing packages remain readable without this new audit field.

## Decision brief and grounding

The brief leads with operating status and the manager's final authority, immediate safety guidance, the decide-by
time, confidence and its weakest factor. A short summary explains why the posture applies to the work or commute
window. Up to three cited rules show observed values, thresholds, timestamps and source links. Missing sources and
unverified policy thresholds remain visible. The full rationale can be copied into the decision record.

Five read-only snapshot views are supplied together instead of a multi-call agent loop. Only roster counts are
included, never employee names or contact details. The model receives the computed posture, confidence, triggered
rules, alerts, roads, analogs and watch items. Source text is treated as data, not instructions. All generated text
fields are checked for unsupported numbers; citations must reference triggered rules and existing alerts. The
rationale must name the computed posture and the manager's decision authority. These checks reduce hallucinations;
they do not prove every natural-language claim is correct. Managers can inspect the underlying source evidence.
Deterministic counterfactuals and safety watch items are preserved. Historical analogs are simulated by rules,
not actual historical USDA decisions.

Failures use a clearly labeled template grounded in the same snapshot. An optional AWS Bedrock fallback is available
only when `AWS_FALLBACK_ENABLED=true`, `AWS_BEDROCK_MODEL_ID` is set, the normal AWS credential chain is configured,
and model access is enabled in `AWS_REGION`. The model must support Bedrock Converse. AWS output is explicitly labeled
**AWS fallback** and audited in the snapshot; it is never presented as Akamai inference. For competition use, leave
this off. Missing both providers does not prevent the manager from reviewing evidence or recording a decision.

## Usage bounds

Each evaluation sends one Akamai chat request, with at most one repair for rejected or malformed output.
SDK retries are disabled. Each attempt allows 2,000 output tokens, at most 48,000 input-context characters,
and a 60-second deadline. Optional Bedrock gets at most one additional request. Per-request token counts,
provider identity, validation outcomes and fallback reasons are stored with the immutable snapshot.
Network/auth failures stop that provider immediately. History builds, replay playback and existing snapshot reads
make no inference requests. Avoid leaving repeated evaluation or background refresh running during a demo.

Creating a new notification package makes at most one additional Akamai request with 200 output tokens,
4,000 input-context characters and a 30-second deadline, with no repair or SDK retry. Truncated responses,
malformed JSON, extra fields, empty wording, multiple sentences, numbers and operational guidance are rejected.
Failures preserve template weather wording and the manager's recorded instructions. Notification wording
uses the template on failure even when optional AWS brief fallback is enabled. Test contacts and credentials
are excluded from Git, inference context and the production image.

The workshop documents shared team limits of 60 requests/minute and 100,000 chat tokens/minute (confirm with the
organizers). On rate limiting, the application uses the template; it does not keep retrying. Team activity in other
apps still shares the quota. Request caps are not a dollar budget or a billing meter.

The workshop's $300 promotion is **Akamai Cloud credit**, while shared inference uses the event's team quota.
Do not assume an inference token price or charge this credit as though it were a provider balance. Check Cloud
Manager's Billing page for credit, expiry and resource charges before provisioning. This integration creates no
cloud resources automatically.

## Optional Akamai Cloud runtime

A production container and Compose configuration are provided in `deploy/`. This is an optional Linode deployment
path, not evidence that a VM has already been created. The app serves the dashboard and API from the same origin,
uses a persistent SQLite volume, and runs as a non-root user. Historical data is built offline into the image.
For builds behind an HTTPS inspection proxy, supply the trusted CA bundle with
`docker build --secret id=build_ca,src=/path/to/trusted-ca-bundle.pem -f deploy/Dockerfile .`.
The optional build secret preserves TLS verification and is not retained in the image.

1. In Akamai Cloud Manager, verify the promotional credit and select a small Linux Linode with enough memory for
   Docker builds (2 GB RAM is a reasonable starting point; check current pricing).
2. Install Docker Engine and Compose using the official instructions for that OS. Clone this branch and create
   an owner-readable `.env` containing the team key. Keep it out of Git and screenshots.
3. From the checkout root, run:

   ```bash
   docker compose -f deploy/compose.prod.yaml up -d --build
   curl --fail http://127.0.0.1:8000/api/health
   ```

4. The app binds to loopback on port 8000. Configure a TLS reverse proxy such as Caddy or nginx for your domain,
   forwarding to that port. Allow only HTTPS/HTTP and restricted SSH through the Linode Cloud Firewall. Do not
   expose an unauthenticated decision-recording app broadly; use demo access controls at the reverse proxy.
5. Verify the dashboard, generate one brief and record a synthetic manager decision. Show the Linode in Cloud
   Manager and the successful Akamai provider badge to judges. `/api/health` only reports configuration; it does
   not establish live inference access.
6. Export the SQLite volume before deleting resources. Remove the Linode and any extra resources after judging;
   powering off the VM does not stop all billing. Review the workshop's costs/cleanup guide before deletion.

## Verification

```bash
DEMO_MODE=true MODEL_PROVIDER=none npm test
npm --prefix frontend run build
```

Tests cover workshop URL/auth/alias/JSON-schema wiring for briefs and notification wording, evidence validation,
bounded repair, missing keys, rate limiting, network failure, opt-in AWS fallback, preserved safety watch items,
immutable records, manager overrides and approval-only notification drafting.
Mock transport tests do not establish live endpoint availability. A real successful brief must have
`model_id=akamai:hackathon-chat`, `ai.validation.ok=true` and Akamai token usage in `ai.inference.requests`.

The derecho replay at `2020-08-10T16:00:00Z` was validated against the live workshop service: one accepted request,
3,167 input tokens and 823 output tokens, preserving `EARLY_DISMISSAL` and a valid immutable snapshot hash.
Initial live tests exercised headline/citation rejection and timeouts before the schema and grounding corrections.
The local production container also passed dashboard/API, seven-event history and replay checks. AWS fallback was
tested with SDK stubs; it was not activated against a paid AWS endpoint. No Linode or other billable cloud resource
was provisioned. These results establish the tested operations, not future shared-service availability or a billing balance.

After the branch integration, the same replay with the 270-person roster passed again on the live service:
one accepted brief request (3,554 input + 871 output tokens) and one accepted notification request
(66 input + 33 output tokens), totaling 4,524 tokens. Both used `hackathon-chat` on Akamai with no repair or
fallback. The integration suite covers 114 tests, including notification failure handling and the manager's
override flowing into an unapproved draft.
