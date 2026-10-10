"""IEM VTEC archive (warnings/advisories in effect at a past moment) and SPC
outlooks at a point. These let replay see the alerts that existed *then*."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from adapters import cache
from adapters.base import Adapter, Facility, NormalizedInput, is_historical, iso_z, utc

IEM = "https://mesonet.agron.iastate.edu/api/1"

# VTEC significance -> CAP-like severity/certainty. The archive does not carry
# the CAP fields, so these are inferred and labelled as such in the UI.
SIG_MAP = {
    "W": ("Severe", "Likely", "Expected"),
    "A": ("Moderate", "Possible", "Future"),
    "Y": ("Minor", "Likely", "Expected"),
    "S": ("Minor", "Possible", "Expected"),
}
EXTREME_PH = {"TO", "IS", "BZ", "EC"}  # tornado, ice storm, blizzard, extreme cold warnings


def _dt(s: str | None) -> datetime | None:
    return datetime.fromisoformat(s.replace("Z", "+00:00")).astimezone(timezone.utc) if s else None


def vtec_row_to_alert(row: dict) -> dict:
    sev, cert, urg = SIG_MAP.get(row["significance"], ("Unknown", "Unknown", "Unknown"))
    if row["significance"] == "W" and row["phenomena"] in EXTREME_PH:
        sev = "Extreme"
    ends = row["utc_expire"]
    note = None
    if ends and row["utc_issue"] and ends < row["utc_issue"]:
        # Upgraded or cancelled before it began. The archive keeps the final expire time,
        # which would leak hindsight, so the planned end is treated as unknown.
        ends, note = None, "replaced or cancelled before its start time; planned end unknown in archive"
    aid = f"{row['wfo']}.{row['phenomena']}.{row['significance']}.{row['eventid']:04d}.{row['utc_issue'][:4]}"
    return {
        "id": aid,
        "event": row["event_label"],
        "severity": sev,
        "certainty": cert,
        "urgency": urg,
        "onset": row["utc_issue"],
        "ends": ends,
        "expires": ends,
        "archive_note": note,
        "effective": row.get("utc_product_issue"),
        "sent": row.get("utc_product_issue"),
        "headline": f"{row['event_label']} ({row['ph_sig']}) for {row['ugc']}",
        "description": None,
        "instruction": None,
        "areaDesc": row["ugc"],
        "senderName": f"NWS {row['wfo']}",
        "vtec": [f"{row['ph_sig']} #{row['eventid']}"],
        "ugc": [row["ugc"]],
        "web": f"https://mesonet.agron.iastate.edu/vtec/#{row['utc_issue'][:4]}-O-NEW-K{row['wfo']}-{row['phenomena']}-{row['significance']}-{row['eventid']:04d}",
        "origin": "iem_vtec_archive",
        "inferred_fields": ["severity", "certainty", "urgency"],
    }


def _product_time(product_id: str | None) -> datetime | None:
    """'202302220854-KDMX-...' -> 2023-02-22 08:54 UTC: when the NWS product that created the event was issued."""
    if not product_id or len(product_id) < 12:
        return None
    return datetime.strptime(product_id[:12], "%Y%m%d%H%M").replace(tzinfo=timezone.utc)


def byugc_row_to_alert(row: dict, as_of: datetime) -> dict | None:
    """Map a vtec_events_byugc row to an alert as it was known at ``as_of`` (None if not known/active then)."""
    known = _product_time(row.get("product_id"))
    if known is None or known > as_of:
        return None  # not issued yet: replay must not see it
    issue, expire = _dt(row["issue"]), _dt(row["expire"])
    cancelled_early = expire is not None and issue is not None and expire < issue
    if expire is not None and expire <= as_of:
        return None  # expired (or cancelled/upgraded) by as_of
    sig, ph = row["significance"], row["phenomena"]
    sev, cert, urg = SIG_MAP.get(sig, ("Unknown", "Unknown", "Unknown"))
    if sig == "W" and ph in EXTREME_PH:
        sev = "Extreme"
    year = row["issue"][:4]
    return {
        "id": f"{row['wfo']}.{ph}.{sig}.{row['eventid']:04d}.{year}",
        "event": row["name"], "severity": sev, "certainty": cert, "urgency": urg,
        "onset": row["issue"], "ends": None if cancelled_early else row["expire"],
        "expires": None if cancelled_early else row["expire"],
        "effective": known.isoformat(), "sent": known.isoformat(),
        "headline": f"{row['name']} ({ph}.{sig}) for {row['ugc']}", "description": None, "instruction": None,
        "areaDesc": row["ugc"], "senderName": f"NWS {row['wfo']}", "vtec": [f"{ph}.{sig} #{row['eventid']}"],
        "ugc": [row["ugc"]], "web": f"https://mesonet.agron.iastate.edu{row['url']}" if row.get("url") else None,
        "origin": "iem_vtec_archive", "inferred_fields": ["severity", "certainty", "urgency"],
        "archive_note": "later replaced or cancelled before its start; planned end unknown" if cancelled_early else
                        "end time is the archive's final value (may reflect later extensions)",
    }


class IEMVTECAdapter(Adapter):
    """NWS watches/warnings/advisories for the facility's zone and county as known at ``as_of`` (replay only).

    Uses IEM's VTEC-events-by-UGC service (one cached call per UGC per few-day window), then keeps only events
    whose issuing product existed at ``as_of`` and that had not yet expired.
    """

    name = "iem_vtec"
    label = "NWS warnings archive (IEM VTEC)"
    supports_historical = True
    historical_only = True
    coverage = "IA"
    BYUGC = "https://mesonet.agron.iastate.edu/json/vtec_events_byugc.php"

    def __init__(self, ugcs: list[str]):
        self.ugcs = ugcs

    async def fetch(self, facility: Facility, as_of: datetime) -> list[NormalizedInput]:
        as_of = utc(as_of)
        d0 = (as_of - timedelta(days=3)).date()
        d0 = d0 - timedelta(days=d0.toordinal() % 3)  # align windows so neighbouring hours share a cached call
        d1 = d0 + timedelta(days=6)
        out, seen = [], set()
        for ugc in self.ugcs:
            url = f"{self.BYUGC}?ugc={ugc}&sdate={d0.isoformat()}&edate={d1.isoformat()}"
            self._urls.append(url)
            r = await cache.get_json(url, historical=is_historical(datetime.combine(d1, datetime.min.time(), timezone.utc)))
            for row in r.data.get("events", []):
                a = byugc_row_to_alert(row, as_of)
                if a is None:
                    continue
                key = (row["phenomena"], row["significance"], row["eventid"], row["issue"][:4])
                if key in seen:  # zone and county copies of one event
                    continue
                seen.add(key)
                out.append(NormalizedInput(
                    id=f"alert:{a['id']}", kind="alert", role="alert", metric="nws_alert", value=a["event"], data=a,
                    source="IEM VTEC archive (events by UGC)", source_url=url, fetched_at=r.fetched_at,
                    source_time=_dt(a["sent"]),
                    note="known at as_of from the issuing product time; severity/certainty inferred from VTEC significance",
                ))
        if not out:
            out.append(NormalizedInput(
                id="alert:none", kind="scalar", role="alert", metric="nws_alert_count", value=0.0, unit="count",
                source="IEM VTEC archive (events by UGC)", source_url=self._urls[-1] if self._urls else self.BYUGC,
                fetched_at=datetime.now(timezone.utc),
                note=f"No NWS warnings/watches/advisories known for {', '.join(self.ugcs)} at {iso_z(as_of)}",
            ))
        return out


SPC_ORDER = ["TSTM", "MRGL", "SLGT", "ENH", "MDT", "HIGH"]


class IEMOutlookAdapter(Adapter):
    """SPC convective outlook category at the facility (day 1 and day 2)."""

    name = "iem_outlook"
    label = "SPC convective outlook (IEM)"
    supports_historical = True
    coverage = "US"

    async def fetch(self, facility: Facility, as_of: datetime) -> list[NormalizedInput]:
        hist = is_historical(as_of)
        url = f"{IEM}/nws/outlook_by_point.json?lat={facility.lat:.4f}&lon={facility.lon:.4f}" + (
            f"&valid={iso_z(as_of)}" if hist else "")
        self._urls.append(url)
        r = await cache.get_json(url, historical=hist)
        rows = r.data.get("data", [])
        out = []
        for day in (1, 2):
            cats = [x for x in rows if x.get("day") == day and x.get("category") == "CATEGORICAL"
                    and x.get("outlook_type") == "C" and x.get("threshold") in SPC_ORDER]
            wind = [x for x in rows if x.get("day") == day and x.get("category") == "WIND"]
            if cats:
                best = max(cats, key=lambda x: SPC_ORDER.index(x["threshold"]))
                cat = best["threshold"]
                src_time = _dt(best.get("product_issue"))
            else:
                best, cat, src_time = None, "NONE", None
            out.append(NormalizedInput(
                id=f"spc.day{day}_category", kind="outlook", role="forecast", metric="spc_category",
                unit="category", value=cat,
                data={"rank": SPC_ORDER.index(cat) if cat in SPC_ORDER else -1,
                      "issue": best and best.get("issue"), "expire": best and best.get("expire"),
                      "wind_probability": max((x["threshold"] for x in wind), default=None)},
                source="SPC convective outlook via IEM", source_url=url, fetched_at=r.fetched_at,
                source_time=src_time,
            ))
        return out
