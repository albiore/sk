import streamlit as st
import pandas as pd
import io
from freepl import parse_invoice, summarise, BUCKETS, BUCKET_LABELS
from brand import BRAND_CSS

# ── Page config ───────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="SecondKind · freepl",
    page_icon="🧬",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown(BRAND_CSS, unsafe_allow_html=True)

# ── Header ────────────────────────────────────────────────────────────────────
st.markdown("""
<div class="sk-header">
  <div>
    <div class="sk-logo">Second<span>Kind</span> · freepl</div>
    <div class="sk-subtitle">3PL Invoices · Logystico Cost Buckets</div>
  </div>
</div>
""", unsafe_allow_html=True)

# ── Upload ────────────────────────────────────────────────────────────────────
st.markdown('<div class="section-label">01 — Upload Monthly Invoices</div>', unsafe_allow_html=True)
st.caption("Drop one or more Logystico invoice PDFs (one per month). Each is parsed and costs are split into buckets. Read-only — nothing is pushed anywhere.")

files = st.file_uploader(
    "Drop invoice PDFs here",
    type=["pdf"],
    accept_multiple_files=True,
    label_visibility="collapsed",
)

if not files:
    st.markdown("""<div style="margin-top:3rem; text-align:center; color:#9C9590;
      font-family:'DM Mono',monospace; font-size:0.8rem;">Waiting for invoice PDFs…</div>""",
      unsafe_allow_html=True)
    st.stop()

invoices = [parse_invoice(io.BytesIO(f.getvalue()), f.name) for f in files]
ok = [inv for inv in invoices if not inv["error"]]
failed = [inv for inv in invoices if inv["error"]]

for inv in failed:
    st.error(f"Could not parse {inv['filename']}: {inv['error']}")

if not ok:
    st.stop()

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
