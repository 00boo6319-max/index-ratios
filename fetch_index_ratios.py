#!/usr/bin/env python3
"""
Fetches current TIPS Index Ratios from TreasuryDirect for a fixed list of
CUSIPs and writes them to index_ratios.json.

Run manually with: python3 fetch_index_ratios.py
Run automatically by .github/workflows/update-ratios.yml on a daily schedule.
"""
import json
import urllib.request
from datetime import datetime, timezone

# Edit this list if your holdings change.
CUSIPS = [
    "91282CGW5",  # Apr-2028
    "91282CKL4",  # Apr-2029
    "912828Z37",  # Jan-2030
    "91282CNB3",  # Apr-2030
    "91282CBF7",  # Jan-2031
    "91282CCM1",  # Jul-2031
    "91282CDX6",  # Jan-2032
    "91282CEZ0",  # Jul-2032
    "91282CGK1",  # Jan-2033
    "91282CHP9",  # Jul-2033
    "91282CJY8",  # Jan-2034
    "91282CLE9",  # Jul-2034
    "91282CML2",  # Jan-2035
]

TA_WS_URL = (
    "https://www.treasurydirect.gov/TA_WS/secindex/search"
    "?cusip={cusip}&format=json&filterscount=0&groupscount=0"
    "&sortdatafield=indexDate&sortorder=desc"
)


def fetch_ratio(cusip):
    url = TA_WS_URL.format(cusip=cusip)
    req = urllib.request.Request(
        url,
        headers={
            "Accept": "application/json",
            "User-Agent": "tips-ladder-updater/1.0 (github actions)",
        },
    )
    with urllib.request.urlopen(req, timeout=20) as resp:
        data = json.loads(resp.read().decode())

    if not data:
        raise ValueError(f"No data returned for {cusip}")

    entries = [d for d in data if d.get("cusip") == cusip] or data

    # TreasuryDirect publishes Index Ratios roughly a month into the future
    # (Reference CPI is interpolated from known CPI-U releases, which allows
    # forward calculation). Sorting desc and taking the first entry grabs the
    # furthest-future date, not today's. We want the most recent entry whose
    # date is today or earlier.
    today_str = datetime.now(timezone.utc).date().isoformat()
    past_or_today = [d for d in entries if (d.get("indexDate") or "")[:10] <= today_str]
    match = max(past_or_today, key=lambda d: d.get("indexDate", "")) if past_or_today \
        else min(entries, key=lambda d: d.get("indexDate", ""))

    return {
        "cusip": cusip,
        "indexRatio": float(match["dailyIndex"]),
        "indexDate": (match.get("indexDate") or "").split("T")[0],
    }


def main():
    print("Fetching TIPS index ratios from TreasuryDirect...")
    results = {}
    failures = []

    for cusip in CUSIPS:
        try:
            r = fetch_ratio(cusip)
            results[cusip] = r
            print(f"  {cusip}: {r['indexRatio']:.5f}  (as of {r['indexDate']})")
        except Exception as exc:
            failures.append(cusip)
            print(f"  {cusip}: FAILED - {exc}")

    output = {
        "generatedAt": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "ratios": results,
    }

    with open("index_ratios.json", "w") as f:
        json.dump(output, f, indent=2)
        f.write("\n")

    print(f"\nUpdated {len(results)} of {len(CUSIPS)} CUSIPs.")
    if failures:
        print(f"Failed: {', '.join(failures)}")
        raise SystemExit(1)


if __name__ == "__main__":
    main()
