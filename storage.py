"""
storage.py — Supabase Storage helpers for SK Data Hub.

Replaces all disk-based CSV/JSON/PDF persistence so the app works on
Streamlit Community Cloud (ephemeral filesystem) with data surviving restarts.

Credentials are read from st.secrets (local: .streamlit/secrets.toml,
production: Streamlit Cloud secrets UI).
"""

import io
import json
import os

import pandas as pd

BUCKET = "sk-data"

_client = None


_SUPABASE_URL = "https://rhzedijuurlimtcxthdb.supabase.co"


def _get_client():
    global _client
    if _client is not None:
        return _client
    try:
        import streamlit as st
        url = st.secrets.get("SUPABASE_URL", _SUPABASE_URL)
        key = st.secrets["SUPABASE_KEY"]
    except Exception:
        url = os.environ.get("SUPABASE_URL", _SUPABASE_URL)
        key = os.environ.get("SUPABASE_KEY", "")
    from supabase import create_client
    _client = create_client(url, key)
    return _client


def _upload(path: str, data: bytes, mime: str = "application/octet-stream") -> None:
    c = _get_client()
    try:
        c.storage.from_(BUCKET).remove([path])
    except Exception:
        pass
    c.storage.from_(BUCKET).upload(path, data, {"content-type": mime, "upsert": "true"})


def _download(path: str):
    try:
        return _get_client().storage.from_(BUCKET).download(path)
    except Exception:
        return None


def upload_df(path: str, df: pd.DataFrame) -> None:
    _upload(path, df.to_csv(index=False).encode("utf-8"), "text/csv")


def download_df(path: str, **read_kwargs):
    data = _download(path)
    return pd.read_csv(io.BytesIO(data), **read_kwargs) if data else None


def upload_text(path: str, text: str) -> None:
    _upload(path, text.encode("utf-8"), "text/plain")


def download_text(path: str):
    data = _download(path)
    return data.decode("utf-8").strip() if data else None


def upload_json(path: str, obj) -> None:
    _upload(path, json.dumps(obj, indent=2).encode("utf-8"), "application/json")


def download_json(path: str):
    data = _download(path)
    return json.loads(data.decode("utf-8")) if data else None


def upload_bytes(path: str, data: bytes, mime: str = "application/octet-stream") -> None:
    _upload(path, data, mime)
