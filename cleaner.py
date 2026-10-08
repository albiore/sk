"""
cleaner.py — SecondKind Sales CSV cleaning pipeline.

Rules applied in order:
  1. Drop aggregate rows (no Order name)
  2. Label empty Product title → "Shipping"
  3. Remove brochure line items
  4. Remove non-clients (Gross > 0 AND Total sales = 0)
  5. Remove zero-net-revenue rows
  6. Add order_line_number + is_first_line helper cols
"""

import pandas as pd
from typing import Tuple

# ── Cleaning step registry (used by UI for pills display) ────────────────────
# B2B/wholesale orders to exclude from all D2C analysis
B2B_ORDERS = {"#1109", "#1172", "#1286"}

CLEANING_STEPS = [
    {"key": "no_order",     "label": "No order rows"},
    {"key": "brochures",    "label": "Brochures"},
    {"key": "non_clients",  "label": "Non-clients (free units)"},
    {"key": "zero_net",     "label": "Zero net revenue"},
    {"key": "b2b_orders",   "label": "B2B orders"},
]


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

    # ── 3. Remove brochures ───────────────────────────────────────────────────
    brochure_mask = df["Product title"].str.contains("Brochure", case=False, na=False)
    log["brochures"] = int(brochure_mask.sum())
    df = df[~brochure_mask].copy()

    # ── 4. Remove non-clients (free units to influencers / partners) ─────────
    #    Condition: Gross Sales > 0 AND Total sales = 0
    non_client_mask = (df["Gross sales"] > 0) & (df["Total sales"] == 0)
    log["non_clients"] = int(non_client_mask.sum())
    df = df[~non_client_mask].copy()

    # ── 5. Remove zero net revenue rows ──────────────────────────────────────
    zero_mask = df["Total sales"] == 0
    log["zero_net"] = int(zero_mask.sum())
    df = df[~zero_mask].copy()

    # ── 6. Remove B2B / wholesale orders ─────────────────────────────────────
    b2b_mask = df["Order name"].isin(B2B_ORDERS)
    log["b2b_orders"] = int(b2b_mask.sum())
    df = df[~b2b_mask].copy()

    # ── 7. Add helper columns ─────────────────────────────────────────────────
    df["order_line_number"] = df.groupby("Order name").cumcount() + 1
    df["is_first_line"] = df["order_line_number"] == 1

    df = df.reset_index(drop=True)
    return df, log
