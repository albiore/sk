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

CREDENTIALS_FILE = "credentials.json"


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
