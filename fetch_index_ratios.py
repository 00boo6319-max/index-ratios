#!/usr/bin/env python3
"""
Updates TIPS Index Ratios for a fixed list of CUSIPs and writes them to
index_ratios.json.

How it works
------------
An Index Ratio is simply:

    Reference CPI on a given date / Reference CPI on the bond's dated date

The Reference CPI for any day is set by Treasury rule from published CPI-U
(not seasonally adjusted) figures: for day d of month M it is the CPI for
month M-3 plus (d-1)/(days in M) of the change to month M-2. So once those
monthly CPI numbers are known, today's Index Ratio can be calculated exactly,
the same way TreasuryDirect does.

This script:
  1. Downloads monthly CPI-U (FRED first, BLS as backup), plus the market's
     inflation forecast (5- and 10-year Treasury breakeven rates from FRED).
  2. Gets each bond's base Reference CPI (saved in index_ratios.json after the
     first run; otherwise from TreasuryDirect, otherwise derived from the
     last good Index Ratio already in index_ratios.json).
  3. Calculates today's Index Ratio for each bond.
  4. If CPI can't be downloaded, falls back to TreasuryDirect's own figures,
     skipping any blank entries, and finally to the last good values.

Run manually with: python3 fetch_index_ratios.py
Run automatically by .github/workflows/update-ratios.yml on a daily schedule.
"""
import calendar
import csv
import io
import json
import time
import urllib.request
from datetime import date, datetime, timedelta, timezone

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

OUTPUT = "index_ratios.json"
UA = "tips-ladder-updater/2.0 (github actions)"

FRED_URL = "https://fred.stlouisfed.org/graph/fredgraph.csv?id=CPIAUCNS"
FRED_SERIES_URL = "https://fred.stlouisfed.org/graph/fredgraph.csv?id={series}"
BLS_URL = "https://api.bls.gov/publicAPI/v2/timeseries/data/CUUR0000SA0"
TD_SECURITY_URL = "https://www.treasurydirect.gov/TA_WS/securities/search?cusip={cusip}&format=json"
TD_INDEX_URL = (
    "https://www.treasurydirect.gov/TA_WS/secindex/search"
    "?cusip={cusip}&format=json&filterscount=0&groupscount=0"
    "&sortdatafield=indexDate&sortorder=desc"
)

# A one-day move bigger than this means something is wrong with the data.
MAX_DAILY_CHANGE = 0.02


# ---------------------------------------------------------------- helpers --

def http_get(url, accept="application/json", attempts=2):
    """GET with one retry, for network hiccups only."""
    last = None
    for n in range(attempts):
        try:
            req = urllib.request.Request(url, headers={"Accept": accept, "User-Agent": UA})
            with urllib.request.urlopen(req, timeout=20) as resp:
                return resp.read().decode("utf-8", "replace")
        except Exception as exc:
            last = exc
            if n < attempts - 1:
                time.sleep(3)
    raise last


def to_float(v):
    """Return a float, or None for blanks / junk."""
    try:
        f = float(str(v).strip())
        return f if f > 0 else None
    except (TypeError, ValueError):
        return None


def load_previous():
    try:
        with open(OUTPUT) as f:
            return json.load(f).get("ratios", {})
    except Exception:
        return {}


# -------------------------------------------------------------- CPI data --

def cpi_from_fred():
    text = http_get(FRED_URL, accept="text/csv")
    rows = list(csv.reader(io.StringIO(text)))
    cpi = {}
    for row in rows[1:]:
        if len(row) < 2:
            continue
        val = to_float(row[1])
        try:
            d = date.fromisoformat(row[0].strip())
        except ValueError:
            continue
        if val:
            cpi[(d.year, d.month)] = val
    return cpi


def cpi_from_bls():
    data = json.loads(http_get(BLS_URL))
    cpi = {}
    for series in data.get("Results", {}).get("series", []):
        for item in series.get("data", []):
            period = item.get("period", "")
            if not period.startswith("M") or period == "M13":
                continue
            val = to_float(item.get("value"))
            if val:
                cpi[(int(item["year"]), int(period[1:]))] = val
    return cpi


def load_cpi():
    for name, fn in (("FRED", cpi_from_fred), ("BLS", cpi_from_bls)):
        try:
            cpi = fn()
            if len(cpi) >= 6:
                latest = max(cpi)
                print(f"CPI-U loaded from {name}; latest month {latest[0]}-{latest[1]:02d} = {cpi[latest]}")
                return cpi
            print(f"CPI-U from {name} looked incomplete ({len(cpi)} months)")
        except Exception as exc:
            print(f"CPI-U from {name} failed: {exc}")
    return {}


def month_back(y, m, k):
    idx = y * 12 + (m - 1) - k
    return idx // 12, idx % 12 + 1


def ref_cpi(d, cpi):
    """Treasury Reference CPI for date d, or None if the CPI isn't out yet."""
    c3 = cpi.get(month_back(d.year, d.month, 3))
    c2 = cpi.get(month_back(d.year, d.month, 2))
    if c3 is None or c2 is None:
        return None
    days = calendar.monthrange(d.year, d.month)[1]
    return round(c3 + (d.day - 1) / days * (c2 - c3), 5)


def latest_ref_cpi(today, cpi):
    """Reference CPI for today, or the latest earlier day that can be computed."""
    d = today
    for _ in range(70):
        r = ref_cpi(d, cpi)
        if r is not None:
            return d, r
        d -= timedelta(days=1)
    return None, None


# ------------------------------------------- market inflation forecast --

def latest_fred_value(series):
    """Most recent non-blank daily value of a FRED series, as (date, value)."""
    text = http_get(FRED_SERIES_URL.format(series=series), accept="text/csv")
    last = None
    for row in list(csv.reader(io.StringIO(text)))[1:]:
        if len(row) >= 2:
            try:
                v = float(row[1])
            except ValueError:
                continue
            last = (row[0].strip(), v)
    if not last:
        raise ValueError(f"no values in {series}")
    return last


def load_breakevens():
    """Market-implied inflation (Treasury breakeven rates), or None."""
    try:
        d5, be5 = latest_fred_value("T5YIE")
        d10, be10 = latest_fred_value("T10YIE")
    except Exception as exc:
        print(f"Breakeven inflation unavailable: {exc}")
        return None
    if not (-2 < be5 < 15 and -2 < be10 < 15):
        print(f"Breakeven inflation looked wrong ({be5}, {be10}); skipped")
        return None
    print(f"Breakeven inflation: 5-yr {be5:.2f}% ({d5}), 10-yr {be10:.2f}% ({d10})")
    return {"breakeven5y": be5, "breakeven10y": be10, "asOf": max(d5, d10),
            "source": "FRED T5YIE / T10YIE"}


# ------------------------------------------------------- TreasuryDirect --

def base_cpi_from_td(cusip):
    try:
        data = json.loads(http_get(TD_SECURITY_URL.format(cusip=cusip)))
    except Exception as exc:
        print(f"  {cusip}: TreasuryDirect base-CPI lookup failed ({exc})")
        return None
    for sec in data if isinstance(data, list) else [data]:
        for key in ("refCpiOnDatedDate", "refCpiOnIssueDate"):
            v = to_float(sec.get(key))
            if v:
                return v
    return None


def ratio_from_td(cusip, today_str):
    """TreasuryDirect's published ratio, ignoring blank entries."""
    data = json.loads(http_get(TD_INDEX_URL.format(cusip=cusip)))
    entries = [e for e in data if e.get("cusip") == cusip] or data
    good = []
    for e in entries:
        d = (e.get("indexDate") or "")[:10]
        r = to_float(e.get("dailyIndex")) or to_float(e.get("indexRatio"))
        if d and d <= today_str and r:
            good.append((d, r))
    if not good:
        sample = entries[0] if entries else {}
        raise ValueError(f"no usable entries (sample entry: {json.dumps(sample)[:300]})")
    d, r = max(good)
    return {"cusip": cusip, "indexRatio": r, "indexDate": d, "source": "TreasuryDirect"}


# ------------------------------------------------------------------ main --

def main():
    today = datetime.now(timezone.utc).date()
    today_str = today.isoformat()
    previous = load_previous()
    cpi = load_cpi()
    inflation = load_breakevens()
    calc_date, calc_ref = latest_ref_cpi(today, cpi) if cpi else (None, None)
    if calc_date:
        print(f"Reference CPI for {calc_date} = {calc_ref}\n")

    results, problems = {}, []

    for cusip in CUSIPS:
        prev = previous.get(cusip, {})
        prev_ratio = to_float(prev.get("indexRatio"))
        result = None

        # 1) Calculate from CPI.
        if calc_ref:
            base = to_float(prev.get("baseCpi")) or base_cpi_from_td(cusip)
            if not base and prev_ratio and prev.get("indexDate"):
                prev_ref = ref_cpi(date.fromisoformat(prev["indexDate"]), cpi)
                if prev_ref:
                    base = round(prev_ref / prev_ratio, 5)
            if base:
                ratio = round(calc_ref / base, 5)
                result = {"cusip": cusip, "indexRatio": ratio,
                          "indexDate": calc_date.isoformat(),
                          "baseCpi": base, "source": "calculated from CPI-U"}
            else:
                print(f"  {cusip}: no base CPI available, trying TreasuryDirect")

        # 2) Fall back to TreasuryDirect's own number.
        if result is None:
            try:
                result = ratio_from_td(cusip, today_str)
                if prev.get("baseCpi"):
                    result["baseCpi"] = prev["baseCpi"]
            except Exception as exc:
                print(f"  {cusip}: TreasuryDirect fallback failed ({exc})")

        # 3) Sanity check against yesterday's value.
        if result and prev_ratio:
            change = abs(result["indexRatio"] / prev_ratio - 1)
            days = max(1, (date.fromisoformat(result["indexDate"]) -
                           date.fromisoformat(prev.get("indexDate", result["indexDate"]))).days)
            if change > MAX_DAILY_CHANGE * days ** 0.5 + 0.005:
                print(f"  {cusip}: rejected {result['indexRatio']:.5f} "
                      f"(too far from previous {prev_ratio:.5f})")
                result = None

        if result:
            results[cusip] = result
            print(f"  {cusip}: {result['indexRatio']:.5f}  (as of {result['indexDate']}, {result['source']})")
        else:
            problems.append(cusip)
            if prev:
                results[cusip] = prev
            print(f"  {cusip}: FAILED - kept previous value {prev.get('indexRatio')} ({prev.get('indexDate')})")

    out = {"generatedAt": datetime.now(timezone.utc).isoformat(timespec="seconds"),
           "ratios": results}
    if inflation is None:
        # Keep yesterday's forecast rather than dropping it.
        try:
            with open(OUTPUT) as f:
                inflation = json.load(f).get("inflation")
        except Exception:
            inflation = None
    if inflation:
        out["inflation"] = inflation

    with open(OUTPUT, "w") as f:
        json.dump(out, f, indent=2)
        f.write("\n")

    print(f"\nUpdated {len(CUSIPS) - len(problems)} of {len(CUSIPS)} CUSIPs.")
    if problems:
        print(f"Kept previous value for: {', '.join(problems)}")
    if len(problems) == len(CUSIPS):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
