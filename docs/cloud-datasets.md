# Historical datasets in Akamai Object Storage

The frozen `ames-7470-v1` baseline can be published to a private S3-compatible Akamai bucket. SQLite remains the local query cache; it is not opened over the network. Publishing does not delete local files or send notifications.

## Configure the bucket

1. Sign in to https://cloud.linode.com and open Object Storage → Create Bucket.
2. Review the account's displayed charges before enabling Object Storage. Create a private bucket, for example `closure-call-datasets`, in the region used by your app. Keep public access disabled.
3. Create an Object Storage access key limited to this bucket, with read/write permissions for publishing. Use a separate read-only key for machines that only download datasets.
4. Set the following in the ignored local `.env`. Copy the endpoint and region from Cloud Manager rather than guessing them. Never commit keys.

```dotenv
OBJ_ENDPOINT=https://REGION.linodeobjects.com
OBJ_REGION=REGION
OBJ_BUCKET=closure-call-datasets
OBJ_ACCESS_KEY=YOUR_ACCESS_KEY
OBJ_SECRET_KEY=YOUR_SECRET_KEY
OBJ_PREFIX=dev
```

All machines sharing a dataset must use the same bucket and prefix. The existing operational mirror also uses these settings: do not change a production prefix casually. No external credentials are required for local-only operation.

## Publish and restore

```sh
npm run dataset:cloud -- publish
npm run dataset:cloud -- list
npm run dataset:cloud -- restore --full
npm run dataset:cloud -- restore --year 2024
```

Run full restore into a fresh data directory when local files differ. Existing evaluations and files are never silently overwritten. Partial-year restore does not install the full 7,470-day cohort manifest. The replay date search's “Load missing years from Akamai dataset” option downloads a missing year only when explicitly selected.

Publish verifies the frozen evaluation summaries and weather artifact hashes, creates compressed yearly bundles, and uploads allowlisted source caches, cohort manifests, analysis JSON and model artifacts. It excludes `.env`, contacts and human decision records. Operational records and database backups are handled separately by the existing storage mirror.

Objects are addressed by SHA-256. An immutable release catalog is published only after every object is downloaded and checksum-verified; a small `latest.json` pointer selects the complete release. Interrupted uploads can be resumed by rerunning publish. Pin a release with `restore --full --release-sha HASH` to reproduce an older dataset. Files remain private.

Cloud storage is durable storage, not a substitute for versioning or a second backup. This implementation does not delete old releases or automatically evict the local cache. Keep local data until the initial upload and a restore on a fresh machine are verified.

## Validation

Automated tests use an in-memory provider and temporary SQLite databases to verify integrity, repeat publishing, restore idempotency, path validation, release pinning, preservation of conflicting local files and recovery after interrupted publishing. A real cloud round trip requires a bucket and local credentials.
