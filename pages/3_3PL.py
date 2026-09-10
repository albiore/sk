import streamlit as st
import pandas as pd
import io
from freepl import (
    parse_invoice, summarise, merge_invoices, load_invoices, save_invoices,
    save_source_pdf, push_3pl_to_expenses, BUCKETS, BUCKET_LABELS, STORE_FILE, PDF_DIR,
)
from sheets import get_sheets_client_status
from brand import BRAND_CSS

# ── Page config ───────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="SecondKind · 3PL",
    page_icon="🧬",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown(BRAND_CSS, unsafe_allow_html=True)

# ── Header ────────────────────────────────────────────────────────────────────
st.markdown("""
<div class="sk-header">
  <div>
    <div class="sk-logo">Second<span>Kind</span> · 3PL</div>
    <div class="sk-subtitle">3PL Invoices · Logystico Cost Buckets</div>
  </div>
</div>
""", unsafe_allow_html=True)

# ── Upload ────────────────────────────────────────────────────────────────────
st.markdown('<div class="section-label">01 — Upload Monthly Invoices</div>', unsafe_allow_html=True)
st.caption("Drop one or more Logystico invoice PDFs (one per month). Each is parsed and costs are split into buckets. All invoices are stored in the cloud — historic months stay loaded across sessions and re-uploading a month replaces it.")

# Load history from the on-disk store first.
stored = load_invoices()

files = st.file_uploader(
    "Drop invoice PDFs here",
    type=["pdf"],
    accept_multiple_files=True,
    label_visibility="collapsed",
)

# Parse any new uploads and merge them into the stored history.
if files:
    new_ok, failed = [], []
    for f in files:
        data = f.getvalue()
        inv = parse_invoice(io.BytesIO(data), f.name)
        if inv["error"]:
            failed.append(inv)
        else:
            inv["pdf_path"] = save_source_pdf(inv, data)  # keep the source PDF
            new_ok.append(inv)

    for inv in failed:
        st.error(f"Could not parse {inv['filename']}: {inv['error']}")

    if new_ok:
        stored = merge_invoices(stored, new_ok)
        save_invoices(stored)
        st.success(
            f"Stored {len(new_ok)} invoice(s) (duplicates by invoice # are skipped). "
            f"{len(stored)} invoice(s) now saved."
        )

ok = stored

if not ok:
    st.markdown("""<div style="margin-top:3rem; text-align:center; color:#9C9590;
      font-family:'DM Mono',monospace; font-size:0.8rem;">Waiting for invoice PDFs…
      <br>No history stored yet — upload a PDF to get started.</div>""",
      unsafe_allow_html=True)
    st.stop()

# Stored-data controls.
import os as _os
_n_pdfs = len([f for f in _os.listdir(PDF_DIR)]) if _os.path.isdir(PDF_DIR) else 0
_n_months = len({inv["period_key"] for inv in ok})
_meta = st.columns([3, 1])
_meta[0].caption(
    f"📦 {len(ok)} invoice(s) across {_n_months} month(s) in storage · "
    f"{_n_pdfs} source PDF(s) kept · data: `{STORE_FILE}`"
)
if _meta[1].button("Clear stored data", use_container_width=True):
    save_invoices([])
    st.rerun()

# ── Overview ──────────────────────────────────────────────────────────────────
st.markdown('<div class="section-label">02 — Overview</div>', unsafe_allow_html=True)

total_spend = sum(inv["parsed_total"] for inv in ok)
months = len({inv["period_key"] for inv in ok})
latest = max(ok, key=lambda i: i["period_key"])
mismatches = sum(
    1 for inv in ok
    if inv["printed_total"] is not None
    and abs(inv["parsed_total"] - inv["printed_total"]) > 0.01
)

st.markdown(f"""
<div class="stat-grid">
  <div class="stat-card">
    <div class="stat-label">Months Loaded</div>
    <div class="stat-value">{months}</div>
    <div class="stat-sub">{len(ok)} invoices</div>
  </div>
  <div class="stat-card">
    <div class="stat-label">Total 3PL Spend</div>
    <div class="stat-value">${total_spend:,.0f}</div>
    <div class="stat-sub">across all months</div>
  </div>
  <div class="stat-card">
    <div class="stat-label">Latest Month</div>
    <div class="stat-value" style="font-size:1.3rem;">{latest['period_label']}</div>
    <div class="stat-sub">${latest['parsed_total']:,.0f}</div>
  </div>
  <div class="stat-card">
    <div class="stat-label">Parse Check</div>
    <div class="stat-value">{'✓' if mismatches == 0 else str(mismatches)}</div>
    <div class="stat-delta {'delta-pos' if mismatches == 0 else 'delta-neg'}">
      {'all totals reconcile' if mismatches == 0 else 'total mismatches'}</div>
  </div>
</div>
""", unsafe_allow_html=True)

# ── Cost by bucket per month ──────────────────────────────────────────────────
summary_df = pd.DataFrame(summarise(ok))
bucket_cols = [BUCKET_LABELS[b] for b in BUCKETS]

st.markdown('<div class="section-label">03 — Cost by Bucket per Month</div>', unsafe_allow_html=True)
st.bar_chart(summary_df.set_index("Period")[bucket_cols], width="stretch")

display_df = summary_df.copy()
for col in bucket_cols + ["Total"]:
    display_df[col] = display_df[col].map("${:,.2f}".format)
st.dataframe(display_df, width="stretch", hide_index=True)

# ── Per-invoice detail ────────────────────────────────────────────────────────
st.markdown('<div class="section-label">04 — Invoice Detail</div>', unsafe_allow_html=True)
for inv in sorted(ok, key=lambda i: i["period_key"]):
    printed = inv["printed_total"]
    check = "✓ reconciles" if printed is not None and abs(inv["parsed_total"] - printed) <= 0.01 else "⚠ check"
    with st.expander(f"{inv['period_label']} · Invoice #{inv['invoice_no']} · ${inv['parsed_total']:,.2f}  ({check})"):
        lines_df = pd.DataFrame(inv["line_items"])
        if not lines_df.empty:
            lines_df["bucket"] = lines_df["bucket"].map(BUCKET_LABELS)
            lines_df["amount"] = lines_df["amount"].map("${:,.2f}".format)
            lines_df = lines_df.rename(columns={"description": "Description", "bucket": "Bucket", "amount": "Amount"})
            st.dataframe(lines_df, width="stretch", hide_index=True)
        printed_str = f"${printed:,.2f}" if printed is not None else "—"
        st.caption(f"Invoice date {inv['invoice_date']} · printed total {printed_str} · parsed total ${inv['parsed_total']:,.2f}")

# ── Push to Google Sheet ──────────────────────────────────────────────────────
st.markdown('<div class="section-label">05 — Push to Business Tracker</div>', unsafe_allow_html=True)
st.caption("Writes monthly bucket costs to the 'Expenses Actuals_new' tab, rows 35-42 (Platform→Everything Else), by month. Multiple invoices in a month are summed.")

if get_sheets_client_status() != "ready":
    st.warning("No Google credentials found — add credentials.json to enable pushing.")
else:
    exp_url = st.text_input(
        "Expenses Sheet URL",
        value="https://docs.google.com/spreadsheets/d/1I4QpO9pYQYQpPOSaEQIHeP91N2xJ0nLWT8bcoFEy1Ts/edit",
        key="expenses_sheet_url",
    )
    if st.button("Push 3PL costs → Expenses Actuals_new"):
        if exp_url:
            with st.spinner("Writing to Expenses Actuals_new…"):
                result = push_3pl_to_expenses(ok, exp_url)
            if result["ok"]:
                st.success(f"✓ {result['cells']} cells updated across {result['months']} month(s) in 'Expenses Actuals_new'")
                if result.get("skipped"):
                    st.warning(f"Skipped (before Jul-2025 or unrecognised period): {', '.join(result['skipped'])}")
            else:
                st.error(f"Error: {result['error']}")
                if result.get("skipped"):
                    st.warning(f"Skipped (before Jul-2025 or unrecognised period): {', '.join(result['skipped'])}")
        else:
            st.warning("Paste the Sheet URL first.")
