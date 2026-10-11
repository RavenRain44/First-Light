"""Original NWS Hurricane Local Statements, as supplemental regional context.

NWS's product endpoint supplies original text and its issuance time, but does
not offer a long-term archive. Older replay must not fetch today's statement.
The statement covers the WFO region; point-specific CAP warnings remain the
assessment's official alerts.
"""
from __future__ import annotations

from datetime import datetime, timedelta

from adapters import cache
from adapters.base import Adapter, Facility, NormalizedInput, utc
from adapters.nwps import dt

API = "https://api.weather.gov"


class NWSHurricaneLocalAdapter(Adapter):
    name = "nws_hurricane_local"
    label = "NWS Hurricane Local Statement"
    coverage = "NC"
    supports_historical = False

    def __init__(self, allow_demo_bypass: bool = False):
        self.allow_demo_bypass = allow_demo_bypass

    async def fetch(self, facility: Facility, as_of: datetime) -> list[NormalizedInput]:
        office = facility.nws_office or "ILM"
        if len(office) != 3 or not office.isalpha():
            raise cache.SourceUnavailable("Invalid configured NWS office identifier.")
        index_url = f"{API}/products/types/HLS/locations/{office.upper()}"
        self._urls.append(index_url)
        index = await cache.get_json(index_url, ttl=600, allow_demo_bypass=self.allow_demo_bypass)
        now = utc(as_of)
        candidates = [row for row in index.data.get("@graph", []) if dt(row.get("issuanceTime"))
                      and now-timedelta(hours=24) <= dt(row["issuanceTime"]) <= now]
        if not candidates:
            return []
        candidate = max(candidates, key=lambda row: dt(row["issuanceTime"]))
        product_id = str(candidate.get("id", ""))
        if len(product_id) != 36 or any(c not in "0123456789abcdef-" for c in product_id.lower()):
            raise cache.SourceUnavailable("NWS returned an invalid Hurricane Local Statement product identifier.")
        product_url = f"{API}/products/{product_id}"
        self._urls.append(product_url)
        response = await cache.get_json(product_url, ttl=86400, allow_demo_bypass=self.allow_demo_bypass)
        product = response.data
        issued = dt(product.get("issuanceTime"))
        issuing_office = str(product.get("issuingOffice") or "").upper().removeprefix("K")
        if product.get("productCode") != "HLS" or issuing_office != office.upper() or issued is None or issued > now or not product.get("productText"):
            raise cache.SourceUnavailable("Original Hurricane Local Statement time/type could not be verified.")
        return [NormalizedInput(id=f"nws.hls.{product_id}", kind="report", role="context", metric="hurricane_local_statement",
                value=product.get("productName") or "Hurricane Local Statement",
                data={"product_id": product_id, "text": product["productText"], "issuance_time": issued.isoformat(),
                      "office": office.upper(), "scope": "Regional statement; do not apply every listed impact to this facility."},
                source=f"NWS {office.upper()} original Hurricane Local Statement", source_url=product_url,
                fetched_at=response.fetched_at, source_time=issued,
                note="Original issued text; regional context. Facility alerts remain point-specific.")]
