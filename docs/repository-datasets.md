# Repository-backed testing data

The frozen 7,470-day Ames baseline is stored in `backend/data/backtesting/` as compressed yearly evaluation bundles and source caches, with SHA-256 release catalogs. No cloud account is required. Personal contacts, credentials, camera captures, operational notification history and the complete local SQLite database are excluded.

After cloning and installing dependencies:

```sh
npm run dataset:repo -- restore
# Or restore just one year:
npm run dataset:repo -- restore --year 2024
```

SQLite remains the local query cache. Restore verifies checksums and rejects conflicting local evaluations/files. Use a fresh `DATABASE_PATH` directory when your local cohort differs. A partial restore does not install the full cohort manifest. Local data is preserved; this is a copy to versioned storage, not deletion of the only working copy.

Maintainers can regenerate a release from the frozen local cohort using `npm run dataset:repo -- export`. Unchanged objects reuse the same content hashes. Review every new release before committing; repeated releases grow Git history. Do not commit `backend/var/` or `.env`.

Readable retained results are in `backend/data/backtesting/metrics/`. They preserve accuracy, balanced accuracy, recall, confusion counts and cost-sensitive comparisons. The cohort labels represent observed weather disruptions; they are not thousands of confirmed facility closure decisions. Candidate thresholds are selected using validation data, and held-out test metrics are reported without picking the best test-set result.

The optional Akamai commands remain available separately, but Git-backed restore never requires Object Storage credentials or connects to Akamai.

## Akamai Object Storage copy

The same release is published to the shared bucket folder `datasets/` (top level, ignoring `OBJ_PREFIX`, so every
laptop and the server read one copy). With `OBJ_*` set, the app loads it automatically on startup when the machine
doesn't have it yet (about 30 seconds for all 7,470 evaluations; set `DATASET_AUTO_RESTORE=false` to skip). A
deployed server therefore gets the full baseline without Git LFS or a manual restore.

Upload the repository release to the bucket (idempotent; every object is checksum-verified and the `latest.json`
pointer is written last):

```sh
cd backend && .venv/Scripts/python -m scripts.dataset_repo upload   # Windows; use .venv/bin/python on Linux/macOS
```

`.gitattributes` marks `backend/data/backtesting/**` as binary so Windows checkouts never convert line endings in
the checksummed files.

## Forecast dataset (default since 2026-10-11)

`ames-forecast-v1` replaces the observation-only cohort in the bucket: 1,884 graded days from 2019 to 2026, each
evaluated at 04:00 with the archived NBM/NBS forecast that was already published (1,777 days; 107 days had no
archived run), the station observations, the current thresholds and the corrected labels
(`AMW-local-disruption-v2`). Roads, RWIS and SPC archives are not included. The app loads `DATASET_VERSION`
(default `ames-forecast-v1`) on startup.

```sh
cd backend
.venv/Scripts/python -m scripts.dataset_cloud publish-forecast            # from a database holding the archive evaluations
.venv/Scripts/python -m scripts.dataset_cloud retire --version ames-7470-v1           # dry run: lists what would go
.venv/Scripts/python -m scripts.dataset_cloud retire --version ames-7470-v1 --delete  # permanent
```

`retire` keeps every content object the configured dataset still uses. The Git copy of `ames-7470-v1` is unaffected.
