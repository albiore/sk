import streamlit as st
import pandas as pd
import io
from cleaner import clean_dataframe, CLEANING_STEPS
from sheets import push_to_sheets, push_to_performance_overview, get_sheets_client_status

# ── Page config ──────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="SecondKind · Sales Cleaner",
    page_icon="🧬",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# ── Custom CSS ────────────────────────────────────────────────────────────────
st.markdown("""
<style>
  @import url('https://fonts.googleapis.com/css2?family=DM+Mono:wght@400;500&family=Syne:wght@400;600;700;800&display=swap');

  html, body, [class*="css"] { font-family: 'Syne', sans-serif; }

  .stApp { background-color: #0d0d0d; color: #f0ede6; }

  /* Header */
  .sk-header {
    display: flex; align-items: center; gap: 16px;
    padding: 2rem 0 1.5rem 0; border-bottom: 1px solid #2a2a2a;
    margin-bottom: 2rem;
  }
  .sk-logo { font-size: 2rem; font-weight: 800; letter-spacing: -0.04em; color: #f0ede6; }
  .sk-logo span { color: #c8f04a; }
  .sk-subtitle { font-family: 'DM Mono', monospace; font-size: 0.75rem;
    color: #666; letter-spacing: 0.08em; text-transform: uppercase; margin-top: 4px; }

  /* Stat cards */
  .stat-grid { display: grid; grid-template-columns: repeat(4, 1fr); gap: 12px; margin: 1.5rem 0; }
  .stat-card {
    background: #161616; border: 1px solid #242424;
    border-radius: 8px; padding: 1.25rem 1.5rem;
  }
  .stat-label { font-family: 'DM Mono', monospace; font-size: 0.7rem;
    color: #555; text-transform: uppercase; letter-spacing: 0.1em; margin-bottom: 6px; }
  .stat-value { font-size: 1.8rem; font-weight: 700; color: #f0ede6; line-height: 1; }
  .stat-delta { font-family: 'DM Mono', monospace; font-size: 0.75rem; margin-top: 6px; }
  .delta-neg { color: #ff6b6b; }
  .delta-pos { color: #c8f04a; }

  /* Step pills */
  .step-row { display: flex; flex-wrap: wrap; gap: 8px; margin: 1rem 0 1.5rem 0; }
  .step-pill {
    font-family: 'DM Mono', monospace; font-size: 0.7rem;
    background: #1a1a1a; border: 1px solid #2d2d2d;
    border-radius: 20px; padding: 4px 12px; color: #888;
  }
  .step-pill.active { background: #1e2a0a; border-color: #c8f04a; color: #c8f04a; }

  /* Section labels */
  .section-label {
    font-family: 'DM Mono', monospace; font-size: 0.7rem;
    color: #555; text-transform: uppercase; letter-spacing: 0.12em;
    margin-bottom: 0.75rem; margin-top: 1.5rem;
  }

  /* Table override */
  .dataframe { font-family: 'DM Mono', monospace !important; font-size: 0.78rem !important; }

  /* Buttons */
  .stButton > button {
    background: #c8f04a; color: #0d0d0d; font-family: 'Syne', sans-serif;
    font-weight: 700; border: none; border-radius: 6px;
    padding: 0.6rem 1.5rem; font-size: 0.85rem; letter-spacing: 0.02em;
    transition: background 0.15s;
  }
  .stButton > button:hover { background: #d8ff5a; color: #0d0d0d; }

  /* Upload zone */
  .uploadedFile { background: #161616 !important; border-color: #2a2a2a !important; }
  [data-testid="stFileUploader"] {
    background: #111; border: 1px dashed #2a2a2a;
    border-radius: 8px; padding: 1rem;
  }

  /* Divider */
  hr { border-color: #1e1e1e !important; }

  /* Success / info */
  .stSuccess { background: #1a2810 !important; border-color: #c8f04a !important; }
  .stInfo { background: #111827 !important; }
</style>
""", unsafe_allow_html=True)

# ── Header ───────────────────────────────────────────────────────────────────
st.markdown("""
<div class="sk-header">
  <div>
    <div class="sk-logo">Second<span>Kind</span></div>
    <div class="sk-subtitle">Sales Data Cleaner · Internal Tool</div>
  </div>
</div>
""", unsafe_allow_html=True)

# ── Upload ───────────────────────────────────────────────────────────────────
st.markdown('<div class="section-label">01 — Upload Raw Export</div>', unsafe_allow_html=True)
st.caption("Export from Shopify Analytics › Sales › Group by Month, Order, Product. Download as CSV.")

uploaded = st.file_uploader(
    "Drop your Shopify CSV here",
    type=["csv"],
    label_visibility="collapsed"
)

if not uploaded:
    st.markdown("""
    <div style="margin-top:3rem; text-align:center; color:#333; font-family:'DM Mono',monospace; font-size:0.8rem;">
      Waiting for CSV upload…
    </div>
    """, unsafe_allow_html=True)
    st.stop()

# ── Load raw ─────────────────────────────────────────────────────────────────
raw_df = pd.read_csv(uploaded)
n_raw = len(raw_df)
n_raw_orders = raw_df["Order name"].nunique() if "Order name" in raw_df.columns else 0

# ── Clean ─────────────────────────────────────────────────────────────────────
cleaned_df, log = clean_dataframe(raw_df.copy())
n_clean = len(cleaned_df)
n_clean_orders = cleaned_df["Order name"].nunique() if "Order name" in cleaned_df.columns else 0

# ── Stats ─────────────────────────────────────────────────────────────────────
st.markdown('<div class="section-label">02 — Cleaning Summary</div>', unsafe_allow_html=True)

# Cleaning steps pills
pills_html = '<div class="step-row">'
for step in CLEANING_STEPS:
    removed = log.get(step["key"], 0)
    active_class = "active" if removed > 0 else ""
    pills_html += f'<div class="step-pill {active_class}">{"✓" if removed > 0 else "○"} {step["label"]} ({removed} rows)</div>'
pills_html += '</div>'
st.markdown(pills_html, unsafe_allow_html=True)

# Revenue stats
total_gross = cleaned_df["Gross sales"].sum() if "Gross sales" in cleaned_df.columns else 0
total_net = cleaned_df["Total sales"].sum() if "Total sales" in cleaned_df.columns else 0
total_discount = cleaned_df["Discounts"].sum() if "Discounts" in cleaned_df.columns else 0

rows_removed = n_raw - n_clean
pct_removed = round((rows_removed / n_raw) * 100, 1) if n_raw > 0 else 0

st.markdown(f"""
<div class="stat-grid">
  <div class="stat-card">
    <div class="stat-label">Clean Orders</div>
    <div class="stat-value">{n_clean_orders}</div>
    <div class="stat-delta delta-neg">from {n_raw_orders} raw</div>
  </div>
  <div class="stat-card">
    <div class="stat-label">Gross Revenue</div>
    <div class="stat-value">${total_gross:,.0f}</div>
    <div class="stat-delta delta-neg">before discounts</div>
  </div>
  <div class="stat-card">
    <div class="stat-label">Net Revenue</div>
    <div class="stat-value">${total_net:,.0f}</div>
    <div class="stat-delta delta-pos">after discounts</div>
  </div>
  <div class="stat-card">
    <div class="stat-label">Total Discounts</div>
    <div class="stat-value">${abs(total_discount):,.0f}</div>
    <div class="stat-delta delta-neg">{rows_removed} rows removed ({pct_removed}%)</div>
  </div>
</div>
""", unsafe_allow_html=True)

# ── Product breakdown ─────────────────────────────────────────────────────────
st.markdown('<div class="section-label">03 — Revenue by Product</div>', unsafe_allow_html=True)
if "Product title" in cleaned_df.columns and "Total sales" in cleaned_df.columns:
    product_summary = (
        cleaned_df[cleaned_df["Product title"] != "Shipping"]
        .groupby("Product title")
        .agg(
            Orders=("Order name", "nunique"),
            Gross=("Gross sales", "sum"),
            Net=("Total sales", "sum"),
            Discounts=("Discounts", "sum"),
            Units=("Quantity ordered", "sum"),
        )
        .sort_values("Net", ascending=False)
        .reset_index()
    )
    product_summary["Gross"] = product_summary["Gross"].map("${:,.2f}".format)
    product_summary["Net"] = product_summary["Net"].map("${:,.2f}".format)
    product_summary["Discounts"] = product_summary["Discounts"].map("${:,.2f}".format)
    st.dataframe(product_summary, use_container_width=True, hide_index=True)

# ── Monthly breakdown ─────────────────────────────────────────────────────────
st.markdown('<div class="section-label">04 — Monthly Revenue Trend</div>', unsafe_allow_html=True)
if "Month" in cleaned_df.columns:
    monthly = (
        cleaned_df.groupby("Month")
        .agg(
            Orders=("Order name", "nunique"),
            Gross=("Gross sales", "sum"),
            Net=("Total sales", "sum"),
            Discounts=("Discounts", "sum"),
        )
        .reset_index()
        .sort_values("Month")
    )
    st.bar_chart(monthly.set_index("Month")["Net"], use_container_width=True)
    monthly["Gross"] = monthly["Gross"].map("${:,.2f}".format)
    monthly["Net"] = monthly["Net"].map("${:,.2f}".format)
    monthly["Discounts"] = monthly["Discounts"].map("${:,.2f}".format)
    st.dataframe(monthly, use_container_width=True, hide_index=True)

# ── Data preview ─────────────────────────────────────────────────────────────
st.markdown('<div class="section-label">05 — Cleaned Data Preview</div>', unsafe_allow_html=True)
st.caption(f"{n_clean} rows · {n_clean_orders} orders · scroll to explore")
st.dataframe(cleaned_df, use_container_width=True, hide_index=True, height=320)

# ── Export ────────────────────────────────────────────────────────────────────
st.markdown('<div class="section-label">06 — Export</div>', unsafe_allow_html=True)
col1, col2 = st.columns([1, 2])

with col1:
    csv_bytes = cleaned_df.to_csv(index=False).encode("utf-8")
    st.download_button(
        label="⬇ Download Cleaned CSV",
        data=csv_bytes,
        file_name="secondkind_sales_cleaned.csv",
        mime="text/csv",
    )

with col2:
    sheets_status = get_sheets_client_status()
    if sheets_status == "ready":
        sheet_url = st.text_input(
            "Google Sheet URL",
            placeholder="https://docs.google.com/spreadsheets/d/…",
            key="sheet_url_raw",
        )
        col2a, col2b = st.columns(2)
        with col2a:
            if st.button("Push raw dump → Cleaned Data tab"):
                if sheet_url:
                    with st.spinner("Writing to Sheets…"):
                        result = push_to_sheets(cleaned_df, sheet_url)
                    if result["ok"]:
                        st.success(f"✓ {result['rows']} rows → '{result['sheet']}'")
                    else:
                        st.error(f"Error: {result['error']}")
                else:
                    st.warning("Paste a Sheet URL first.")
        with col2b:
            if st.button("Push actuals → Performance Ov"):
                if sheet_url:
                    with st.spinner("Writing to Performance Ov…"):
                        result = push_to_performance_overview(cleaned_df, sheet_url)
                    if result["ok"]:
                        st.success(f"✓ {result['cells']} cells updated in 'Performance Ov'")
                    else:
                        st.error(f"Error: {result['error']}")
                else:
                    st.warning("Paste a Sheet URL first.")
    else:
        st.info(f"Google Sheets: {sheets_status}. Add credentials.json to enable.")
