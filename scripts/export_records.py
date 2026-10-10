#!/usr/bin/env python3
import sys
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.app.config import ROOT, get_settings
from backend.app.db import Repository, build_session_factory


def main() -> None:
    settings = get_settings()
    records = Repository(build_session_factory(settings.database_url)).records()
    export_dir = ROOT / "data" / "exports"
    export_dir.mkdir(parents=True, exist_ok=True)
    path = export_dir / f"decision-chain-{datetime.now(UTC):%Y%m%d}.jsonl"
    path.write_text(
        "".join(record.model_dump_json() + "\n" for record in records), encoding="utf-8"
    )
    print(f"Exported {len(records)} records to {path}")


if __name__ == "__main__":
    main()
