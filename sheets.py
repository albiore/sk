"""
sheets.py — Google Sheets push via service account.

Setup (one-time):
  1. Go to console.cloud.google.com
  2. Create a project → Enable Google Sheets API + Google Drive API
  3. Create a Service Account → download JSON key → save as credentials.json
  4. Share your target Google Sheet with the service account email (Editor access)
  5. Drop credentials.json next to this file (or set GOOGLE_CREDENTIALS_JSON env var)

The service account email looks like:
  something@your-project.iam.gserviceaccount.com
"""

import os
import json
import pandas as pd
from typing import Dict, Any

CREDENTIALS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "credentials.json")


def get_sheets_client_status() -> str:
    """Check whether credentials are available."""
    # Check env var first (useful for Railway / cloud deployment)
    if os.environ.get("GOOGLE_CREDENTIALS_JSON"):
        return "ready"
    if os.path.exists(CREDENTIALS_FILE):
        return "ready"
    return "no credentials.json found"


def _get_credentials():
    """Load credentials from file or environment variable."""
    import google.oauth2.service_account as sa

    env_creds = os.environ.get("GOOGLE_CREDENTIALS_JSON")
    if env_creds:
        info = json.loads(env_creds)
    elif os.path.exists(CREDENTIALS_FILE):
        with open(CREDENTIALS_FILE) as f:
            info = json.load(f)
    else:
        raise FileNotFoundError(
            "No Google credentials found. "
            "Add credentials.json or set GOOGLE_CREDENTIALS_JSON env var."
        )

    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive",
    ]
    return sa.Credentials.from_service_account_info(info, scopes=scopes)


def _extract_sheet_id(url: str) -> str:
    """Extract spreadsheet ID from a Google Sheets URL."""
    # Handles: /spreadsheets/d/{ID}/edit  and  /spreadsheets/d/{ID}
    import re
    match = re.search(r"/spreadsheets/d/([a-zA-Z0-9_-]+)", url)
    if not match:
        raise ValueError(f"Could not extract sheet ID from URL: {url}")
    return match.group(1)


# Fiscal year column map: CSV month key → sheet column letter (Jul-2025 to Jun-2026)
_MONTH_TO_COL: Dict[str, str] = {
    "2025-07-01": "B", "2025-08-01": "C", "2025-09-01": "D",
    "2025-10-01": "E", "2025-11-01": "F", "2025-12-01": "G",
    "2026-01-01": "H", "2026-02-01": "I", "2026-03-01": "J",
    "2026-04-01": "K", "2026-05-01": "L", "2026-06-01": "M",
}

# Target rows in "Performance Ov" tab
# (shifted after Shipping Revenue lines were inserted at OKR 9 / ACTUALS 15 / ATTAINMENT 21)
_PERF_ROWS = {
    "revenue_gut":  13, "revenue_mood": 14, "revenue_shipping": 15,
    "orders_gut":   32, "orders_mood":  33,
    "units_gut":    49, "units_mood":   50,
}


def push_to_performance_overview(df: pd.DataFrame, sheet_url: str) -> Dict[str, Any]:
    """
    Write monthly actuals into the 'Performance Ov' tab at hardcoded rows/columns.
    Only D2C SKUs: exact 'Gut Balance' and 'Mood Balance' (excludes Master Carton).
    """
    try:
        import gspread

        creds = _get_credentials()
        client = gspread.authorize(creds)
        sheet_id = _extract_sheet_id(sheet_url)
        worksheet = client.open_by_key(sheet_id).worksheet("Performance Ov")

        df = df.copy()
        df["_month_key"] = pd.to_datetime(df["Month"]).dt.strftime("%Y-%m-01")

        gut_mask  = df["Product title"] == "Gut Balance"
        mood_mask = df["Product title"] == "Mood Balance"
        ship_mask = df["Product title"] == "Shipping"

        updates = []
        for month_key, col in _MONTH_TO_COL.items():
            m = df["_month_key"] == month_key
            for label, mask in [("gut", gut_mask), ("mood", mood_mask)]:
                sub = df[m & mask]
                revenue = round(float(sub["Total sales"].sum()), 2)
                # Exclude refund rows (Total sales < 0) from order count —
                # refunds correctly reduce revenue but should not count as orders.
                orders  = int(sub[sub["Total sales"] > 0]["Order name"].nunique())
                units   = int(sub[sub["Total sales"] > 0]["Quantity ordered"].sum())
                updates += [
                    {"range": f"{col}{_PERF_ROWS[f'revenue_{label}']}", "values": [[revenue]]},
                    {"range": f"{col}{_PERF_ROWS[f'orders_{label}']}", "values": [[orders]]},
                    {"range": f"{col}{_PERF_ROWS[f'units_{label}']}", "values": [[units]]},
                ]
            # Shipping revenue (net Total sales, refunds included) → its own row
            ship_rev = round(float(df[m & ship_mask]["Total sales"].sum()), 2)
            updates.append(
                {"range": f"{col}{_PERF_ROWS['revenue_shipping']}", "values": [[ship_rev]]}
            )

        worksheet.batch_update(updates, value_input_option="USER_ENTERED")
        return {"ok": True, "cells": len(updates), "error": None}

    except Exception as e:
        return {"ok": False, "cells": 0, "error": str(e)}


MODEL_SHEET_ID = "1T2U-9hufaw1Puo3a-HObHxx01-9zDqpvCXitQ6HMbAc"

# Assumptions_Monthly column index → month label (col B=index1 = Jul-2025)
_MODEL_COL_MONTHS = [
    "Jul-2025","Aug-2025","Sep-2025","Oct-2025","Nov-2025","Dec-2025",
    "Jan-2026","Feb-2026","Mar-2026","Apr-2026","May-2026","Jun-2026",
]

_SCENARIO_LABELS = [
    "1 bottle one-time",
    "3-pack one-time",
    "6-pack one-time",
    "1 bottle subscription",
    "3-pack subscription",
    "6-pack subscription",
]


def read_model_scenario_mix() -> dict:
    """
    Read Scenario Mix % from Assumptions_Monthly rows 15-20.
    Returns {scenario_label: {month_label: float}} e.g. {"1 bottle one-time": {"Jan-2026": 0.40}}
    """
    try:
        import gspread
        creds = _get_credentials()
        client = gspread.authorize(creds)
        ws = client.open_by_key(MODEL_SHEET_ID).worksheet("Assumptions_Monthly")
        rows = ws.get("A15:M20")  # 6 scenario rows, columns A-M
        result = {}
        for row, label in zip(rows, _SCENARIO_LABELS):
            monthly = {}
            for i, month in enumerate(_MODEL_COL_MONTHS):
                try:
                    val = row[i + 1]  # skip col A (label)
                    monthly[month] = float(str(val).replace("%", "")) / 100
                except (IndexError, ValueError):
                    monthly[month] = 0.0
            result[label] = monthly
        return {"ok": True, "data": result, "error": None}
    except Exception as e:
        return {"ok": False, "data": {}, "error": str(e)}


def read_model_ot_retention() -> dict:
    """
    Read OT retention rates (% >= 1/2/3 repeats) from Retention_OT_Assumptions.
    Returns {product: {metric: float}} for 1-bottle one-time scenario only.
    Gut Balance: rows 4-6, Mood Balance: rows 46-48.
    Values are constant across months — we take the first month column (D).
    """
    try:
        import gspread
        creds = _get_credentials()
        client = gspread.authorize(creds)
        ws = client.open_by_key(MODEL_SHEET_ID).worksheet("Retention_OT_Assumptions")
        # Gut Balance rows 4-6, Mood Balance rows 46-48
        gut_rows  = ws.get("A4:E6")   # A=Product, B=Scenario, C=Metric, D=Jul-2025 value
        mood_rows = ws.get("A46:E48")
        metrics   = ["% >= 1 repeat", "% >= 2 repeats", "% >= 3 repeats"]
        result = {}
        for product, rows in [("Gut Balance", gut_rows), ("Mood Balance", mood_rows)]:
            result[product] = {}
            for row, metric in zip(rows, metrics):
                try:
                    result[product][metric] = float(row[3])  # col D = first month value
                except (IndexError, ValueError):
                    result[product][metric] = 0.0
        return {"ok": True, "data": result, "error": None}
    except Exception as e:
        return {"ok": False, "data": {}, "error": str(e)}


# Amazon target rows in "Performance Ov" tab
# (shifted +3 after the Shopify Shipping Revenue rows were inserted above this block)
_AMZ_ROWS = {
    "revenue_gut":  67, "revenue_mood": 68,
    "orders_gut":   84, "orders_mood":  85,
    "units_gut":    101, "units_mood":   102,
}


def push_amazon_to_performance_overview(df: pd.DataFrame, sheet_url: str) -> Dict[str, Any]:
    """
    Write monthly Amazon actuals into the 'Performance Ov' tab.
    df must already be cleaned (only Order Payment rows, product_group assigned).
    """
    try:
        import gspread

        creds = _get_credentials()
        client = gspread.authorize(creds)
        worksheet = client.open_by_key(_extract_sheet_id(sheet_url)).worksheet("Performance Ov")

        updates = []
        for month_key, col in _MONTH_TO_COL.items():
            m = df["_month_key"] == month_key
            for label, product in [("gut", "Gut Balance"), ("mood", "Mood Balance")]:
                sub = df[m & (df["product_group"] == product)]
                # Revenue: Vine orders naturally add $0, so sum all
                revenue = round(float(sub["revenue"].sum()), 2)
                # Orders & units: exclude Vine free units (same logic as Shopify refunds)
                paying  = sub[~sub["is_free"]] if "is_free" in sub.columns else sub
                orders  = int(paying["Order ID"].nunique())
                units   = int(paying["units"].sum())
                updates += [
                    {"range": f"{col}{_AMZ_ROWS[f'revenue_{label}']}", "values": [[revenue]]},
                    {"range": f"{col}{_AMZ_ROWS[f'orders_{label}']}", "values": [[orders]]},
                    {"range": f"{col}{_AMZ_ROWS[f'units_{label}']}", "values": [[units]]},
                ]

        worksheet.batch_update(updates, value_input_option="USER_ENTERED")
        return {"ok": True, "cells": len(updates), "error": None}

    except Exception as e:
        return {"ok": False, "cells": 0, "error": str(e)}


def push_to_sheets(df: pd.DataFrame, sheet_url: str, tab_name: str = "Cleaned Data") -> Dict[str, Any]:
    """
    Write cleaned DataFrame to a Google Sheet.
    Clears the target tab and rewrites from row 1.

    Returns dict with keys: ok, rows, sheet, error
    """
    try:
        import gspread

        creds = _get_credentials()
        client = gspread.authorize(creds)

        sheet_id = _extract_sheet_id(sheet_url)
        spreadsheet = client.open_by_key(sheet_id)

        # Get or create the target worksheet
        try:
            worksheet = spreadsheet.worksheet(tab_name)
        except gspread.WorksheetNotFound:
            worksheet = spreadsheet.add_worksheet(title=tab_name, rows=5000, cols=30)

        # Prepare data: replace NaN with empty string for Sheets compatibility
        df_export = df.copy()
        df_export = df_export.fillna("")

        # Convert bool columns to string (Sheets doesn't like Python bools)
        for col in df_export.select_dtypes(include="bool").columns:
            df_export[col] = df_export[col].astype(str)

        headers = df_export.columns.tolist()
        rows = df_export.values.tolist()
        all_data = [headers] + rows

        # Clear and rewrite
        worksheet.clear()
        worksheet.update(all_data, value_input_option="USER_ENTERED")

        return {
            "ok": True,
            "rows": len(rows),
            "sheet": tab_name,
            "error": None,
        }

    except ImportError:
        return {
            "ok": False,
            "rows": 0,
            "sheet": tab_name,
            "error": "gspread not installed. Run: pip install gspread google-auth",
        }
    except Exception as e:
        return {
            "ok": False,
            "rows": 0,
            "sheet": tab_name,
            "error": str(e),
        }
