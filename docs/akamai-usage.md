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

The deployment runs **live** weather (re-evaluated every 10 minutes) behind a **Caddy front door** with automatic
HTTPS. Anyone with the address can view the dashboard. Setup asks whether recording decisions, notifications and
storage actions should require a manager login (HTTP basic auth at Caddy); without it, anyone with the address can
use them. To change it later, delete `deploy/manager-auth` and rerun the setup script.

1. In Akamai Cloud Manager, check the promotional credit and current pricing, then **Create → Linode**:
   Ubuntu 24.04 LTS, region **Chicago (us-ord)** (same as the bucket), a shared-CPU plan with 2-4 GB RAM, a root
   password and your SSH key. Under **Firewall**, create one that allows inbound TCP 80 and 443 from anywhere and
   TCP 22 from your own IP only.
2. SSH in and run:

   ```bash
   git clone -b integration https://github.com/RavenRain44/hack-midwest-2026.git
   cd hack-midwest-2026
   sudo bash deploy/scripts/setup-linode.sh
   ```

   The script installs Docker (and a swap file on small plans), writes `.env` (live weather, Akamai key, Object
   Storage keys with no `OBJ_PREFIX`), asks whether to require a manager login (a bcrypt hash in
   `deploy/manager-auth`), builds, starts and prints the address.
3. **Address.** With no argument the site uses the Linode's free reverse-DNS hostname (shown on the Linode's
   **Network** tab, like `203-0-113-5.ip.linodeusercontent.com`), or `203-0-113-5.sslip.io` as a fallback. For a
   friendlier name, buy a domain from any registrar, add it in **Cloud Manager → Domains** (free DNS) with an
   **A record** pointing to the Linode's IPv4 address, set the registrar's nameservers to `ns1.linode.com` …
   `ns5.linode.com`, wait for DNS, then run `sudo bash deploy/scripts/setup-linode.sh your-domain.org`.
   Caddy obtains the HTTPS certificate on the first visit.
4. Verify from a phone: the dashboard loads, the Akamai brief appears, recording a decision works (and asks for the
   manager login if you set one), and **Technical details → Cloud copy** shows the log and camera frames. In Cloud Manager, the Linode's
   **Analytics** tab shows CPU and traffic, and **Object Storage → Buckets** lists the mirrored files (top level,
   not `dev/`).
5. Update to the latest code: `git pull && sudo docker compose -f deploy/compose.prod.yaml up -d --build`.
   Logs: `sudo docker compose -f deploy/compose.prod.yaml logs -f app`.
6. After the event: confirm `backups/closurecall-latest.db` in the bucket, then delete the Linode (powering it off
   does not stop billing), the domain record and the bucket's objects, and revoke the Object Storage key.

## Object storage

Optional. Mirrors the decision log, chart data, decision camera stills and daily database backups to a private
Akamai Object Storage bucket (S3-compatible, through `boto3`). See the README's "Cloud storage" section for the
bucket layout.

1. In Akamai Cloud Manager, open **Object Storage → Create Bucket**. Choose the **Chicago (us-ord)** region (closest
   to Iowa), name it (for example `closurecall-<team>`), and keep it private. Check current pricing first.
2. Open **Object Storage → Access Keys → Create Access Key**. Turn on **Limited access** and give it **Read/Write**
   on this bucket only. Copy the secret now; it is shown once.
3. Add to the server's `.env` (and your local `.env` to test):

   ```bash
   OBJ_ENDPOINT=https://us-ord-1.linodeobjects.com
   OBJ_REGION=us-ord-1
   OBJ_BUCKET=closurecall-<team>
   OBJ_ACCESS_KEY=...
   OBJ_SECRET_KEY=...
   ```

   If Cloud Manager shows a different endpoint hostname for the bucket, use that one. On laptops also set
   `OBJ_PREFIX=dev` so local test data lands in `dev/` and never mixes with (or restores onto) the server's.
4. Restart the app. `GET /api/storage/status` should report `enabled: true`; `POST /api/storage/sync` copies
   everything immediately (normally it runs within seconds of each write). Open **Technical details → Cloud copy**
   on the dashboard to see links to the snapshot log, chart data and camera stills.
5. Before deleting the Linode, confirm a recent `backups/closurecall-latest.db`. A new server with an empty volume
   restores it automatically. Delete the bucket's objects and the bucket after the event to stop billing, and
   revoke the access key.

The bucket never becomes public: the dashboard receives signed links that expire after one hour.

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
