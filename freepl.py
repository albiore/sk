"""
freepl.py — Logystico 3PL invoice parser + cost bucketing.

Each monthly invoice (PDF) is parsed into line items, then each line is mapped
to one of the cost buckets below. Amounts are summed per bucket per month.

Column layout in the Logystico template (x-coordinates, points):
  Quantity  x < 100
  Description  100 <= x < 450
  Rate  450 <= x < 500
  Amount  x >= 500   (rightmost numeric on the row)
"""

import io
import os
import json
import re
from typing import List, Dict, Any, Optional

# ── Persistent store ──────────────────────────────────────────────────────────
# Parsed invoices are saved here so historic data survives across sessions
# (the page reads this on load instead of requiring a re-upload every time).
STORE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "freepl_invoices.json")
# Original source PDFs are kept here, named by invoice number.
PDF_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "freepl_pdfs")

# ── Cost buckets (display order) ──────────────────────────────────────────────
BUCKETS = [
    "platform",
    "storage",
    "receiving",
    "pick_pack",
    "packaging",
    "b2b",
    "shipping",
    "other",
]

BUCKET_LABELS = {
    "platform": "Platform",
    "storage": "Storage",
    "receiving": "Receiving",
    "pick_pack": "Pick & Pack",
    "packaging": "Packaging Materials",
    "b2b": "B2B",
    "shipping": "Shipping",
    "other": "Everything Else",
}

# Ordered keyword rules — first match wins. Keyword matched against the cleaned,
# lowercased line description.
_BUCKET_RULES = [
    ("platform",  ["software & cloud", "account management"]),
    ("storage",   ["storage fee"]),
    ("receiving", ["receiving of inventory"]),
    ("pick_pack", ["pick & pack"]),
    ("packaging", ["packing materials"]),
    ("b2b",       ["b2b fee"]),
    ("shipping",  ["shipping -", "uniuni", "carrier"]),
]

# ── PDF glyph artifacts (subset embedded in this template's font) ─────────────
_CID_MAP = {
    "(cid:36)": "$",
    "(cid:88)": "X",
    "(cid:122)": "z",
}

_MONTHS = {
    "january": 1, "february": 2, "march": 3, "april": 4, "may": 5, "june": 6,
    "july": 7, "august": 8, "september": 9, "october": 10, "november": 11,
    "december": 12,
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "jun": 6, "jul": 7, "aug": 8,
    "sep": 9, "sept": 9, "oct": 10, "nov": 11, "dec": 12,
}
# Longest names first so "april" wins over "apr", etc.
_MONTH_PATTERN = "|".join(sorted(_MONTHS, key=len, reverse=True))
_PERIOD_RE = re.compile(rf"({_MONTH_PATTERN})\s*(\d{{4}}|\d{{2}})", re.IGNORECASE)


def _clean_cid(text: str) -> str:
    for code, char in _CID_MAP.items():
        text = text.replace(code, char)
    return text


def _to_number(text: str):
    """Parse a money/number token, or return None if it isn't one."""
    cleaned = _clean_cid(text).replace("$", "").replace(",", "").strip()
    if not re.fullmatch(r"-?\d+(\.\d+)?", cleaned):
        return None
    return float(cleaned)


def _bucket_for(description: str) -> str:
    desc = description.lower()
    for bucket, keywords in _BUCKET_RULES:
        if any(kw in desc for kw in keywords):
            return bucket
    return "other"


def _detect_period(text: str) -> Dict[str, Any]:
    """Return {key: 'YYYY-MM', label: 'Month YYYY'} from the first month token."""
    match = _PERIOD_RE.search(_clean_cid(text))
    if not match:
        return {"key": "unknown", "label": "Unknown period"}
    month = _MONTHS[match.group(1).lower()]
    year = int(match.group(2))
    if year < 100:
        year += 2000
    label = f"{match.group(1).capitalize()} {year}"
    # Normalise label month to full name for consistency.
    full = [m for m, n in _MONTHS.items() if n == month and len(m) > 3]
    if full:
        label = f"{full[0].capitalize()} {year}"
    return {"key": f"{year}-{month:02d}", "label": label}


def parse_invoice(file: io.BytesIO, filename: str = "") -> Dict[str, Any]:
    """
    Parse one Logystico invoice PDF into bucketed costs.

    Returns dict:
      filename, invoice_no, invoice_date, period_key, period_label,
      buckets {bucket: amount}, line_items [{description, bucket, amount}],
      parsed_total (sum of lines), printed_total (from the invoice), error
    """
    import pdfplumber

    result: Dict[str, Any] = {
        "filename": filename,
        "invoice_no": None,
        "invoice_date": None,
        "period_key": "unknown",
        "period_label": "Unknown period",
        "buckets": {b: 0.0 for b in BUCKETS},
        "line_items": [],
        "parsed_total": 0.0,
        "printed_total": None,
        "error": None,
    }

    try:
        with pdfplumber.open(file) as pdf:
            full_text = ""
            money_tokens = []  # (top_on_last_page, x0, value) for total detection

            for page in pdf.pages:
                full_text += (page.extract_text() or "") + "\n"
                words = page.extract_words()

                # Cluster words into visual rows by their rounded top coordinate.
                rows: Dict[int, list] = {}
                for w in words:
                    rows.setdefault(round(w["top"]), []).append(w)

                for top in sorted(rows):
                    row = sorted(rows[top], key=lambda x: x["x0"])

                    # A line item has a leading quantity (x < 100, integer) AND an
                    # amount in the rightmost column (x >= 500, numeric).
                    qty_tokens = [w for w in row if w["x0"] < 100 and _to_number(w["text"]) is not None]
                    amount_tokens = [
                        w for w in row if w["x0"] >= 500 and _to_number(w["text"]) is not None
                    ]
                    has_qty = any(float(_to_number(w["text"])).is_integer() for w in qty_tokens)

                    if not (has_qty and amount_tokens):
                        continue

                    amount = _to_number(max(amount_tokens, key=lambda w: w["x0"])["text"])
                    desc_tokens = [w for w in row if 100 <= w["x0"] < 450]
                    description = _clean_cid(" ".join(w["text"] for w in desc_tokens)).strip()
                    if not description:
                        continue

                    bucket = _bucket_for(description)
                    result["buckets"][bucket] += amount
                    result["parsed_total"] += amount
                    result["line_items"].append(
                        {"description": description, "bucket": bucket, "amount": amount}
                    )

            # ── Metadata from full text ──────────────────────────────────────
            text = _clean_cid(full_text)

            inv_no = re.search(r"Invoice\s*#\s*\n?\s*[\d/]*\s*(\d{6,})", text)
            if inv_no:
                result["invoice_no"] = inv_no.group(1)

            inv_date = re.search(r"\b(\d{1,2}/\d{1,2}/\d{4})\b", text)
            if inv_date:
                result["invoice_date"] = inv_date.group(1)

            period = _detect_period(text)
            result["period_key"] = period["key"]
            result["period_label"] = period["label"]

            # Printed total = the largest "$x,xxx.xx" figure (Total / Balance Due).
            totals = [float(t.replace(",", "")) for t in re.findall(r"\$\s*([\d,]+\.\d{2})", text)]
            if totals:
                result["printed_total"] = max(totals)

    except Exception as e:  # noqa: BLE001 — surface parse failures to the UI
        result["error"] = str(e)

    return result


def _store_key(inv: Dict[str, Any]) -> str:
    """Unique key for dedup. Use the invoice number — the true identity — so that
    re-uploaded file copies collapse, but two DIFFERENT invoices in the same
    month are both kept. Fall back to period, then filename."""
    ino = inv.get("invoice_no")
    if ino:
        return f"inv:{ino}"
    pk = inv.get("period_key")
    if pk and pk != "unknown":
        return f"period:{pk}"
    return f"file:{inv.get('filename', '')}"


def save_source_pdf(inv: Dict[str, Any], data: bytes) -> str:
    """Persist the original PDF bytes, named by invoice number. Returns the path."""
    os.makedirs(PDF_DIR, exist_ok=True)
    key = inv.get("invoice_no") or os.path.splitext(inv.get("filename", ""))[0] or "unknown"
    path = os.path.join(PDF_DIR, f"{key}.pdf")
    with open(path, "wb") as f:
        f.write(data)
    return path


def load_invoices() -> List[Dict[str, Any]]:
    """Load previously parsed invoices from the on-disk store (empty if none)."""
    if not os.path.exists(STORE_FILE):
        return []
    try:
        with open(STORE_FILE) as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except (json.JSONDecodeError, OSError):
        return []


def save_invoices(invoices: List[Dict[str, Any]]) -> None:
    """Persist the full invoice list to disk."""
    with open(STORE_FILE, "w") as f:
        json.dump(invoices, f, indent=2)


def merge_invoices(
    existing: List[Dict[str, Any]], new: List[Dict[str, Any]]
) -> List[Dict[str, Any]]:
    """Merge new invoices into existing, keyed by month — a re-uploaded month
    replaces the stored one. Returns the combined list sorted by period."""
    by_key = {_store_key(inv): inv for inv in existing}
    for inv in new:
        by_key[_store_key(inv)] = inv
    return sorted(by_key.values(), key=lambda i: i.get("period_key", ""))


def summarise(invoices: List[Dict[str, Any]]) -> "list[dict]":
    """One row per month: period + each bucket + total, summing all invoices that
    fall in the same month. Sorted by period key."""
    by_period: Dict[str, dict] = {}
    for inv in invoices:
        if inv.get("error"):
            continue
        pk = inv["period_key"]
        if pk not in by_period:
            agg = {"Period": inv["period_label"], "_key": pk}
            for b in BUCKETS:
                agg[BUCKET_LABELS[b]] = 0.0
            agg["Total"] = 0.0
            by_period[pk] = agg
        agg = by_period[pk]
        for b in BUCKETS:
            agg[BUCKET_LABELS[b]] += inv["buckets"][b]
        agg["Total"] += inv["parsed_total"]
    rows = sorted(by_period.values(), key=lambda r: r["_key"])
    for r in rows:
        for b in BUCKETS:
            r[BUCKET_LABELS[b]] = round(r[BUCKET_LABELS[b]], 2)
        r["Total"] = round(r["Total"], 2)
        r.pop("_key", None)
    return rows


# ── Push to Google Sheet: "Expenses Actuals_new" tab ────────────────────────────
# Target: the SAME SK Business Tracker spreadsheet that holds "Performance Ov"
# (where Shopify/Amazon push), just a different tab — so the service account
# already has access. Month columns start at C (Jul-2025) and continue monthly —
# note this tab starts at C, not B. 3PL bucket rows 35-42; row 43 is a formula total.
EXPENSES_TAB = "Expenses Actuals_new"

# First month column: Jul-2025 = column C. Later months are computed relative
# to this instead of a fixed lookup table, so the mapping never runs out.
_3PL_FIRST_PERIOD = (2025, 7)
_3PL_FIRST_COL_INDEX = 3  # column C


def _col_index_to_letter(index: int) -> str:
    """1-based column index -> spreadsheet column letters (1=A, 27=AA, ...)."""
    letters = ""
    while index > 0:
        index, remainder = divmod(index - 1, 26)
        letters = chr(65 + remainder) + letters
    return letters


def _col_for_period(period_key: str) -> Optional[str]:
    """Map a 'YYYY-MM' period key to its sheet column, relative to Jul-2025 = C.
    Returns None for periods before Jul-2025 or malformed keys."""
    try:
        year, month = (int(part) for part in period_key.split("-"))
    except (ValueError, AttributeError):
        return None
    first_year, first_month = _3PL_FIRST_PERIOD
    months_since_first = (year - first_year) * 12 + (month - first_month)
    if months_since_first < 0:
        return None
    return _col_index_to_letter(_3PL_FIRST_COL_INDEX + months_since_first)


# bucket key → sheet row (order matches the sheet's row labels 35-42)
_3PL_BUCKET_ROWS = {
    "platform":  35, "storage":   36, "receiving": 37, "pick_pack": 38,
    "packaging": 39, "b2b":       40, "shipping":  41, "other":     42,
}


def push_3pl_to_expenses(invoices: List[Dict[str, Any]], sheet_url: str) -> Dict[str, Any]:
    """
    Write monthly 3PL bucket costs into the 'Expenses Actuals_new' tab (rows 35-42).
    Aggregates all invoices in the same month (a month can hold several invoices).
    Months before Jul-2025 or with an unrecognised period are skipped and
    reported back in "skipped" rather than silently dropped.
    """
    try:
        import gspread
        from sheets import _get_credentials, _extract_sheet_id

        creds = _get_credentials()
        client = gspread.authorize(creds)
        worksheet = client.open_by_key(_extract_sheet_id(sheet_url)).worksheet(EXPENSES_TAB)

        # Aggregate buckets per month.
        by_month: Dict[str, Dict[str, float]] = {}
        skipped = []
        for inv in invoices:
            if inv.get("error"):
                continue
            pk = inv.get("period_key")
            if _col_for_period(pk) is None:
                skipped.append(pk)
                continue
            agg = by_month.setdefault(pk, {b: 0.0 for b in BUCKETS})
            for b in BUCKETS:
                agg[b] += inv["buckets"].get(b, 0.0)

        if not by_month:
            return {"ok": False, "cells": 0, "months": 0, "skipped": skipped,
                    "error": "No invoices fall on or after Jul-2025."}

        updates = []
        for pk, agg in by_month.items():
            col = _col_for_period(pk)
            for b in BUCKETS:
                updates.append({
                    "range": f"{col}{_3PL_BUCKET_ROWS[b]}",
                    "values": [[round(agg[b], 2)]],
                })

        worksheet.batch_update(updates, value_input_option="USER_ENTERED")
        return {"ok": True, "cells": len(updates), "months": len(by_month),
                "skipped": skipped, "error": None}

    except Exception as e:
        return {"ok": False, "cells": 0, "months": 0, "skipped": [], "error": str(e)}
