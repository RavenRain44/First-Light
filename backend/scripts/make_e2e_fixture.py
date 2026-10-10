"""Regenerate fixtures/derecho_2020-08-10T16Z_inputs.json (used by tests/test_e2e_derecho.py)."""
import asyncio
import json
from datetime import datetime, timezone

from app.facility import load_facility
from engine.evaluate import gather, json_ready

AS_OF = datetime(2020, 8, 10, 16, tzinfo=timezone.utc)


async def main():
    f = load_facility()
    inputs, statuses = await gather(f, AS_OF, "replay")
    out = {"facility_id": f.id, "as_of": AS_OF.isoformat(), "mode": "replay",
           "inputs": json_ready(inputs), "statuses": json_ready(statuses)}
    with open("fixtures/derecho_2020-08-10T16Z_inputs.json", "w", encoding="utf-8") as fh:
        json.dump(out, fh)
    print({s.adapter: s.status for s in statuses})


if __name__ == "__main__":
    asyncio.run(main())
