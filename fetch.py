#!/usr/bin/env python3
"""Public power cut feed for Clarity's website ticker.

Reads SSEN's official Power Track live faults, keeps cuts in Clarity's towns, merges
them with the previous feed (so cuts stay listed for 7 days after SSEN takes them off
its map), and writes site/feed.json. Shows postcode district and town only, never a
full postcode (Deon, 19 Nov 2026). Source: SSEN Power Track. Stdlib only.
"""
import datetime as dt
import gzip
import json
import re
import time
import urllib.request
from pathlib import Path

SSEN = "https://ssen-powertrack-api.opcld.com/gridiview/reporter/info/livefaults"
PREVIOUS = "https://deonbryan.github.io/clarity-power-cuts/feed.json"
AREAS = {"SO", "PO", "BH", "SP", "RG", "GU", "RH", "SL", "HP", "TW", "KT", "UB", "CR"}
KEEP_DAYS = 7
TOWNS = json.loads(Path(__file__).with_name("towns.json").read_text())


def get(url):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0", "Accept-Encoding": "gzip"})
    with urllib.request.urlopen(req, timeout=30) as r:
        b = r.read()
    return json.loads(gzip.decompress(b) if b[:2] == b"\x1f\x8b" else b)


def town(d, postcode):
    """Real place name from the free postcodes.io lookup (Ordnance Survey and ONS data):
    the parish, else 'ward, council'. Falls back to our own district list."""
    if d in TOWNS["districts"]:
        return TOWNS["districts"][d]
    try:
        r = get("https://api.postcodes.io/postcodes/" + urllib.request.quote(postcode))["result"]
        parish, ward, council = r.get("parish") or "", r.get("admin_ward") or "", r.get("admin_district") or ""
        if parish and "unparished" not in parish:
            return parish
        if ward and council and ward != council and ward.lower() not in ("town", "central", "town centre"):
            return f"{ward}, {council}"
        return council or ward or d
    except Exception:
        return TOWNS["districts"].get(d) or d


def main():
    now = dt.datetime.now(dt.timezone.utc).replace(microsecond=0)
    # the previous feed carries the 7 day list and the running totals; if it cannot be read,
    # stop (the job fails and GitHub keeps serving the old feed) rather than wipe the history
    for attempt in range(3):
        try:
            old_feed = get(PREVIOUS)
            break
        except Exception:
            if attempt == 2:
                raise
            time.sleep(20)
    prev = {c["ref"]: c for c in old_feed.get("cuts", [])}
    since = old_feed.get("tracking_since") or now.isoformat().replace("+00:00", "Z")
    live = {}
    for f in get(SSEN).get("Faults", []):
        ds = sorted({p.split(" ")[0].upper() for p in f.get("affectedAreas") or []})
        ds = [d for d in ds if re.match(r"[A-Z]+", d) and re.match(r"[A-Z]+", d).group(0) in AREAS]
        if not ds:
            continue
        pc = next(p for p in f["affectedAreas"] if p.upper().startswith(ds[0] + " "))
        old = prev.get(f["reference"])
        live[f["reference"]] = {
            "ref": f["reference"], "district": ds[0], "town": old["town"] if old else town(ds[0], pc),
            "homes": f.get("affectedCustomerCount"), "started": f.get("loggedAt", "").replace("+0000", "Z").replace(".000", ""),
            "expected_back": (f.get("estimatedRestoration") or "").replace("+0000", "Z").replace(".000", ""),
            "back": None,
        }
    new_refs = [r for r in live if r not in prev]
    total_cuts = old_feed.get("total_cuts", len(prev)) + len(new_refs)
    total_homes = old_feed.get("total_homes", sum(c["homes"] or 0 for c in prev.values())) \
        + sum(live[r]["homes"] or 0 for r in new_refs)
    cuts = dict(prev)
    for ref, c in live.items():
        cuts[ref] = c
    for ref, c in cuts.items():
        if ref not in live and not c.get("back"):
            c["back"] = now.isoformat().replace("+00:00", "Z")   # gone from SSEN's map: power is back
    cutoff = now - dt.timedelta(days=KEEP_DAYS)
    keep = [c for c in cuts.values()
            if c["started"] and (not c.get("back")   # a cut still live stays listed, so it is never counted twice
                                 or dt.datetime.fromisoformat(c["started"].replace("Z", "+00:00")) >= cutoff)]
    keep.sort(key=lambda c: c["started"], reverse=True)
    out = {"source": "SSEN Power Track", "updated": now.isoformat().replace("+00:00", "Z"),
           "days": KEEP_DAYS, "tracking_since": since,
           "total_cuts": total_cuts, "total_homes": total_homes, "cuts": keep}
    Path("site").mkdir(exist_ok=True)
    Path("site/feed.json").write_text(json.dumps(out, indent=1))
    print(f"{len(live)} live, {len(keep)} in the last {KEEP_DAYS} days")


if __name__ == "__main__":
    main()
