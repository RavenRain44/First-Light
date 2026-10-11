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

The backend calls Akamai's OpenAI-compatible JSON protocol directly; OpenAI is not an inference provider here.
Strands Agents provides the secondary path through Amazon Bedrock; the application does not call Bedrock directly.

Copy `.env.example` to ignored `.env` if needed, and enter `AKAMAI_API_KEY` securely. Keep `MODEL_PROVIDER=akamai`.
`STRANDS_FALLBACK_ENABLED=true` enables the default secondary path and uses the normal AWS credential chain.
Set it to `false` for an Akamai-only demo. No key is shipped in the repository or browser bundle.
Allow HTTPS egress to `ws.akamai-workshops.com`. Live weather additionally requires `api.weather.gov` and
`mesonet.agron.iastate.edu`.

From the repository root:

```bash
npm run setup
DEMO_MODE=true npm run dev
```

`DEMO_MODE=true` uses cached weather, but AI still calls Akamai. To run entirely offline, also set
`MODEL_PROVIDER=none`. Live Check always calls NWS, including in weather demo mode.
Use **Re-evaluate now** for a new live decision brief. Replay playback reuses recorded backtest data and starts
a brief automatically when the selected report loads.
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

The single-column dashboard leads with **Suggested Action**: “Due to [one to three reasons], [action].” Akamai
rewrites short evidence phrases tied to computed supporting rule IDs; the action always comes from the recorded
posture. Manager authority, immediate safety guidance, decide-by time and confidence stay visible.
**Relevant Metrics** shows two charts chosen from the supporting rules and active hazard, highlighting threshold
crossings, peaks and recorded hazard windows. Chart thresholds come from the immutable snapshot, not current
policy. Captions distinguish alert context from numeric threshold evidence; missing measurements remain gaps.
The wind chart preserves hourly-report wind and the distinct observed peak gust used by the corrected rules.
The visible **Regenerate** control rewrites the same evidence and retains the previous accepted brief while
the new append-only interpretation is pending, or if it fails validation.
**More information** starts collapsed and reveals the manager form, full explanation, alerts, watch items, all
weather metrics, roads, analogs, history and raw sources. The full rationale can be copied into the decision record.

Five read-only snapshot views are supplied together instead of a multi-call agent loop. Only roster counts are
included, never employee names or contact details. The model receives the computed posture, confidence, triggered
rules, alerts, roads, analogs and watch items. Source text is treated as data, not instructions. All generated text
fields are checked for unsupported numbers; citations must reference triggered rules and existing alerts.
Reason phrases must cite distinct computed supporting rules and cannot contain operating instructions. The
rationale must name the computed posture and the manager's decision authority. These checks reduce hallucinations;
they do not prove every natural-language claim is correct. Managers can inspect the underlying source evidence.
Deterministic counterfactuals and safety watch items are preserved. Historical analogs are simulated by rules,
not actual historical USDA decisions.

Failures use a clearly labeled template grounded in the same snapshot. When Akamai is unavailable or rejected,
`STRANDS_FALLBACK_ENABLED=true` runs a Strands agent with `STRANDS_MODEL_ID` through Amazon Bedrock. The normal AWS
credential chain, regional model access, and `AWS_REGION` apply. Strands output is explicitly labeled and audited;
it is never presented as Akamai inference. Missing both providers does not prevent the manager from reviewing
evidence or recording a decision.

## Usage bounds

Each new or previously stored report immediately returns its template and starts a background brief when configured.
The brief sends one chat request, with at most one repair for rejected or malformed output.
SDK retries are disabled. Each attempt allows 700 output tokens, at most 48,000 input-context characters,
and a 60-second deadline. Strands gets at most one additional attempt after Akamai. Per-request token counts,
provider identity, validation outcomes and fallback reasons are stored in a separate append-only interpretation
record. The original snapshot and its hash stay unchanged. Expanding dashboard details or changing chart focus
makes no inference request.
Network/auth failures stop that provider immediately. Offline history builds use `use_ai=false`; loading any report
in the application requests a brief once and stores the append-only result. Avoid leaving replay playback or
background refresh running during a demo if you do not want those one-time requests.

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
npm --prefix frontend test
npm --prefix frontend run build
```

Tests cover workshop URL/auth/alias/JSON-schema wiring for briefs and notification wording, evidence validation,
bounded repair, missing keys, rate limiting, network failure, Strands fallback, preserved safety watch items,
immutable records, manager overrides and approval-only notification drafting.
Mock transport tests do not establish live endpoint availability. A real successful brief must have
`model_id=akamai:hackathon-chat`, `ai.validation.ok=true` and Akamai token usage in `ai.inference.requests`.

The derecho replay at `2020-08-10T16:00:00Z` was validated against the live workshop service: one accepted request,
3,167 input tokens and 823 output tokens, preserving `EARLY_DISMISSAL` and a valid immutable snapshot hash.
Initial live tests exercised headline/citation rejection and timeouts before the schema and grounding corrections.
The local production container also passed dashboard/API, seven-event history and replay checks. The previous direct
AWS fallback was tested only with SDK stubs; the current Strands path still requires configured AWS access. No Linode or other billable cloud resource
was provisioned. These results establish the tested operations, not future shared-service availability or a billing balance.

After the branch integration, the same replay with the 270-person roster passed again on the live service:
one accepted brief request (3,554 input + 871 output tokens) and one accepted notification request
(66 input + 33 output tokens), totaling 4,524 tokens. Both used `hackathon-chat` on Akamai with no repair or
fallback. The integration suite covered 114 tests, including notification failure handling and the manager's
override flowing into an unapproved draft.

The dashboard reason schema passed one live workshop request with 3,691 input and 389 output tokens
(4,080 total), two cited reasons, successful validation and no repair or fallback. The updated backend suite
has 119 tests and 15 frontend tests cover graph relevance, recorded windows, inclusive/strict thresholds, missing
measurements and legacy briefs. Sixteen browser scenarios cover desktop/mobile, light/dark, keyboard expansion,
manager overrides, chart failures, source tooltips, graph focus and background Akamai updates using intercepted
local test responses. The accepted live Akamai brief was also rendered without an additional inference request.
Checks after syncing integration also cover corrected hourly weather and successful/failed regeneration,
including retention of the previous brief and unfinished manager input.
