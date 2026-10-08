"""
cleaner.py — SecondKind Sales CSV cleaning pipeline.

Rules applied in order:
  1. Drop aggregate rows (no Order name)
  2. Label empty Product title → "Shipping"
  3. Collapse order_tag row explosion (combine tags, de-dup line items)
  4. Remove brochure line items
  5. Remove B2B / wholesale (Master Carton titles OR qty >= 12)
  6. Remove non-clients (Gross > 0 AND Total sales = 0)
  7. Remove zero-net-revenue rows
  8. Add order_line_number + is_first_line helper cols
"""

import pandas as pd
from typing import Tuple

# ── Cleaning step registry (used by UI for pills display) ────────────────────
CLEANING_STEPS = [
    {"key": "no_order",     "label": "No order rows"},
    {"key": "tag_dupes",    "label": "Order-tag duplicate lines"},
    {"key": "brochures",    "label": "Brochures"},
    {"key": "b2b",          "label": "B2B / wholesale (carton or qty≥7)"},
    {"key": "non_clients",  "label": "Non-clients (free units)"},
    {"key": "zero_net",     "label": "Zero net revenue"},
]

# Wholesale threshold: a single line at or above this qty is treated as B2B/bulk
B2B_QTY_THRESHOLD = 7


def clean_dataframe(df: pd.DataFrame) -> Tuple[pd.DataFrame, dict]:
    """
    Apply all cleaning rules to raw Shopify export.
    Returns (cleaned_df, log) where log is {step_key: rows_removed}.
    """
    log = {}
    before = len(df)

    # ── 1. Drop rows with no Order name (monthly aggregate / totals rows) ───
    mask = df["Order name"].isna()
    log["no_order"] = int(mask.sum())
    df = df[~mask].copy()

    # ── 2. Label empty Product title as "Shipping" ───────────────────────────
    df["Product title"] = df["Product title"].fillna("Shipping")

    # ── 3. Collapse order_tag row explosion ──────────────────────────────────
    #    The ShopifyQL query GROUPs BY order_tag, so a line item belonging to an
    #    order with N tags is emitted as N identical rows (same revenue & units).
    #    Summing would multiply revenue/units by the tag count. Combine every
    #    tag for a line into one field and keep a single row per physical line.
    if "Order tag" in df.columns:
        non_tag = [c for c in df.columns if c != "Order tag"]
        before_dd = len(df)
        df["Order tag"] = (
            df.groupby(non_tag, dropna=False)["Order tag"]
              .transform(lambda s: ", ".join(sorted({
                  str(x).strip() for x in s if pd.notna(x) and str(x).strip()
              })))
        )
        df = df.drop_duplicates(subset=non_tag).copy()
        log["tag_dupes"] = before_dd - len(df)
    else:
        log["tag_dupes"] = 0

    # ── 4. Remove brochures ───────────────────────────────────────────────────
    brochure_mask = df["Product title"].str.contains("Brochure", case=False, na=False)
    log["brochures"] = int(brochure_mask.sum())
    df = df[~brochure_mask].copy()

    # ── 4. Remove B2B / wholesale orders ─────────────────────────────────────
    #    Master Carton SKUs (by name) OR any single line at/above the qty threshold
    carton_mask = df["Product title"].str.contains("Master Carton", case=False, na=False)
    qty_mask    = pd.to_numeric(df["Quantity ordered"], errors="coerce").fillna(0) >= B2B_QTY_THRESHOLD
    b2b_mask    = carton_mask | qty_mask
    log["b2b"]  = int(b2b_mask.sum())
    df = df[~b2b_mask].copy()

    # ── 6. Remove non-clients (free units to influencers / partners) ─────────
    #    Condition: Gross Sales > 0 AND Total sales = 0
    non_client_mask = (df["Gross sales"] > 0) & (df["Total sales"] == 0)
    log["non_clients"] = int(non_client_mask.sum())
    df = df[~non_client_mask].copy()

    # ── 7. Remove zero net revenue rows ──────────────────────────────────────
    zero_mask = df["Total sales"] == 0
    log["zero_net"] = int(zero_mask.sum())
    df = df[~zero_mask].copy()

    # ── 8. Add helper columns ─────────────────────────────────────────────────
    df["order_line_number"] = df.groupby("Order name").cumcount() + 1
    df["is_first_line"] = df["order_line_number"] == 1

    df = df.reset_index(drop=True)
    return df, log
