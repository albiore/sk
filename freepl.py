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
import re
from typing import List, Dict, Any

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


def summarise(invoices: List[Dict[str, Any]]) -> "list[dict]":
    """One row per month: period + each bucket + total. Sorted by period key."""
    rows = []
    for inv in invoices:
        if inv.get("error"):
            continue
        row = {"Period": inv["period_label"], "_key": inv["period_key"]}
        for b in BUCKETS:
            row[BUCKET_LABELS[b]] = round(inv["buckets"][b], 2)
        row["Total"] = round(inv["parsed_total"], 2)
        rows.append(row)
    rows.sort(key=lambda r: r["_key"])
    for r in rows:
        r.pop("_key", None)
    return rows
