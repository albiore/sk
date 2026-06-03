import streamlit as st
import pandas as pd
import os
import io
from cleaner import clean_dataframe, CLEANING_STEPS
from sheets import (
    push_to_sheets, push_to_performance_overview, get_sheets_client_status,
    read_model_scenario_mix, read_model_ot_retention,
)
from brand import BRAND_CSS

# ── Constants ─────────────────────────────────────────────────────────────────
STORE_FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "shopify_data.csv")

# ── Page config ──────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="SecondKind · Shopify",
    page_icon="🧬",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── Brand CSS ─────────────────────────────────────────────────────────────────
st.markdown(BRAND_CSS, unsafe_allow_html=True)

# ── Header ───────────────────────────────────────────────────────────────────
st.markdown("""
<div class="sk-header">
  <div>
    <div class="sk-logo">Second<span>Kind</span></div>
    <div class="sk-subtitle">Sales Data Cleaner · Internal Tool</div>
  </div>
</div>
""", unsafe_allow_html=True)


# ── Persistence helpers ───────────────────────────────────────────────────────
def load_stored():
    if os.path.exists(STORE_FILE):
        return pd.read_csv(STORE_FILE)
    return None


def merge_data(new_df: pd.DataFrame, stored) -> pd.DataFrame:
    """Month-level override: new file fully replaces any months it covers."""
    if stored is None or stored.empty:
        return new_df
    new_months  = set(new_df["Month"].unique())
    kept        = stored[~stored["Month"].isin(new_months)].copy()
    combined    = pd.concat([kept, new_df], ignore_index=True)
    return combined.sort_values("Month").reset_index(drop=True)


# ── Upload ───────────────────────────────────────────────────────────────────
st.markdown('<div class="section-label">01 — Upload Raw Export</div>', unsafe_allow_html=True)
st.caption("Export from Shopify Analytics › Sales › Group by Month, Order, Product. Download as CSV.")

uploaded = st.file_uploader(
    "Drop your Shopify CSV here",
    type=["csv"],
    label_visibility="collapsed"
)

# ── Load stored data ──────────────────────────────────────────────────────────
stored_df = load_stored()
if stored_df is not None:
    months_stored = sorted(stored_df["Month"].unique())
    month_labels  = pd.to_datetime(months_stored).strftime("%b-%Y").tolist()
    st.info(f"📦 Stored: **{len(stored_df)} rows** across **{', '.join(month_labels)}**  —  "
            f"upload a new file to add or update months.")

if not uploaded:
    if stored_df is None:
        st.markdown("""
        <div style="margin-top:3rem; text-align:center; color:#9C9590;
          font-family:'DM Mono',monospace; font-size:0.8rem;">
          Waiting for CSV upload…
        </div>
        """, unsafe_allow_html=True)
        st.stop()
    else:
        cleaned_df = stored_df
        log        = {}
        n_raw = n_raw_orders = 0
        n_clean = len(cleaned_df)
        n_clean_orders = cleaned_df["Order name"].nunique() if "Order name" in cleaned_df.columns else 0
else:
    # ── Clean new upload ──────────────────────────────────────────────────────
    raw_df        = pd.read_csv(uploaded)
    n_raw         = len(raw_df)
    n_raw_orders  = raw_df["Order name"].nunique() if "Order name" in raw_df.columns else 0
    new_df, log   = clean_dataframe(raw_df.copy())
    cleaned_df    = merge_data(new_df, stored_df)
    n_clean       = len(new_df)
    n_clean_orders= new_df["Order name"].nunique() if "Order name" in new_df.columns else 0

    # Save merged dataset
    cleaned_df.to_csv(STORE_FILE, index=False)
    if stored_df is not None:
        new_month_labels = sorted(
            pd.to_datetime(new_df["Month"].unique()).strftime("%b-%Y").tolist()
        )
        all_month_labels = sorted(
            pd.to_datetime(cleaned_df["Month"].unique()).strftime("%b-%Y").tolist()
        )
        st.success(
            f"✓ Months replaced: **{', '.join(new_month_labels)}** · "
            f"Total stored: **{len(cleaned_df)} rows** across **{', '.join(all_month_labels)}**"
        )
    else:
        st.success(f"✓ {n_clean} rows stored ({n_clean_orders} orders)")

# ── Stats ─────────────────────────────────────────────────────────────────────
st.markdown('<div class="section-label">02 — Cleaning Summary</div>', unsafe_allow_html=True)

if log:
    pills_html = '<div class="step-row">'
    for step in CLEANING_STEPS:
        removed = log.get(step["key"], 0)
        active_class = "active" if removed > 0 else ""
        pills_html += f'<div class="step-pill {active_class}">{"✓" if removed > 0 else "○"} {step["label"]} ({removed} rows)</div>'
    pills_html += '</div>'
    st.markdown(pills_html, unsafe_allow_html=True)

total_gross    = cleaned_df["Gross sales"].sum()    if "Gross sales" in cleaned_df.columns else 0
total_net      = cleaned_df["Total sales"].sum()    if "Total sales" in cleaned_df.columns else 0
total_discount = cleaned_df["Discounts"].sum()      if "Discounts"   in cleaned_df.columns else 0
rows_removed   = n_raw - n_clean
pct_removed    = round((rows_removed / n_raw) * 100, 1) if n_raw > 0 else 0

st.markdown(f"""
<div class="stat-grid">
  <div class="stat-card">
    <div class="stat-label">Clean Orders</div>
    <div class="stat-value">{n_clean_orders}</div>
    <div class="stat-delta delta-neg">{"from " + str(n_raw_orders) + " raw" if n_raw_orders else "stored"}</div>
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

# ── Performance by month by product ───────────────────────────────────────────
st.markdown('<div class="section-label">03 — Performance by Month by Product</div>', unsafe_allow_html=True)
st.caption("Net revenue per month — the same figures pushed to the Performance Ov revenue rows (Gut 13, Mood 14, Shipping 15). Net includes refunds.")
if {"Month", "Product title", "Total sales"}.issubset(cleaned_df.columns):
    _perf_df = cleaned_df.copy()
    _perf_df["_m"] = pd.to_datetime(_perf_df["Month"])
    perf_rows = []
    for _m, _g in _perf_df.groupby("_m"):
        _gut  = _g.loc[_g["Product title"] == "Gut Balance",  "Total sales"].sum()
        _mood = _g.loc[_g["Product title"] == "Mood Balance", "Total sales"].sum()
        _ship = _g.loc[_g["Product title"] == "Shipping",     "Total sales"].sum()
        perf_rows.append({
            "Month - Year":             _m.strftime("%b-%Y"),
            "Gut Balance Net Revenue":  _gut,
            "Mood Balance Net Revenue": _mood,
            "Shipping Revenue":         _ship,
            "Total Revenue":            _gut + _mood + _ship,
        })
    perf_month = pd.DataFrame(perf_rows)
    for _c in ["Gut Balance Net Revenue", "Mood Balance Net Revenue", "Shipping Revenue", "Total Revenue"]:
        perf_month[_c] = perf_month[_c].map("${:,.2f}".format)
    st.dataframe(perf_month, width="stretch", hide_index=True)

# ── Product breakdown ─────────────────────────────────────────────────────────
st.markdown('<div class="section-label">04 — Revenue by Product</div>', unsafe_allow_html=True)
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
    st.dataframe(product_summary, width="stretch", hide_index=True)

# ── Shipping revenue ──────────────────────────────────────────────────────────
st.markdown('<div class="section-label">05 — Shipping Revenue</div>', unsafe_allow_html=True)
st.caption("Shipping charged to customers — tracked separately and pushed to its own row in Performance Ov.")
if "Product title" in cleaned_df.columns and "Total sales" in cleaned_df.columns:
    shipping_df = cleaned_df[cleaned_df["Product title"] == "Shipping"]
    ship_net    = shipping_df["Total sales"].sum()
    ship_gross  = shipping_df["Gross sales"].sum() if "Gross sales" in shipping_df.columns else 0
    ship_orders = shipping_df["Order name"].nunique()

    st.markdown(f"""
    <div class="stat-grid">
      <div class="stat-card">
        <div class="stat-label">Shipping Net</div>
        <div class="stat-value">${ship_net:,.2f}</div>
        <div class="stat-delta delta-pos">after discounts</div>
      </div>
      <div class="stat-card">
        <div class="stat-label">Shipping Gross</div>
        <div class="stat-value">${ship_gross:,.2f}</div>
        <div class="stat-delta delta-neg">before discounts</div>
      </div>
      <div class="stat-card">
        <div class="stat-label">Orders w/ Shipping</div>
        <div class="stat-value">{ship_orders}</div>
        <div class="stat-delta delta-neg">charged shipping</div>
      </div>
    </div>
    """, unsafe_allow_html=True)

    if "Month" in shipping_df.columns and not shipping_df.empty:
        ship_monthly = (
            shipping_df.groupby("Month")
            .agg(Orders=("Order name", "nunique"),
                 Gross=("Gross sales", "sum"),
                 Net=("Total sales", "sum"))
            .reset_index()
            .sort_values("Month")
        )
        ship_monthly["Gross"] = ship_monthly["Gross"].map("${:,.2f}".format)
        ship_monthly["Net"]   = ship_monthly["Net"].map("${:,.2f}".format)
        st.dataframe(ship_monthly, width="stretch", hide_index=True)

# ── Monthly breakdown ─────────────────────────────────────────────────────────
st.markdown('<div class="section-label">06 — Monthly Revenue Trend</div>', unsafe_allow_html=True)
st.caption("Total monthly revenue across all SKUs — **includes** shipping revenue (broken out separately in section 04).")
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
    st.bar_chart(monthly.set_index("Month")["Net"], width="stretch")
    monthly["Gross"] = monthly["Gross"].map("${:,.2f}".format)
    monthly["Net"] = monthly["Net"].map("${:,.2f}".format)
    monthly["Discounts"] = monthly["Discounts"].map("${:,.2f}".format)
    st.dataframe(monthly, width="stretch", hide_index=True)

# ── Data preview ─────────────────────────────────────────────────────────────
st.markdown('<div class="section-label">07 — Cleaned Data Preview</div>', unsafe_allow_html=True)
st.caption(f"{n_clean} rows · {n_clean_orders} orders · scroll to explore")
st.dataframe(cleaned_df, width="stretch", hide_index=True, height=320)

# ── Export ────────────────────────────────────────────────────────────────────
st.markdown('<div class="section-label">08 — Export</div>', unsafe_allow_html=True)
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

# ── Column-set detection (shared by sections 07 and 08) ──────────────────────
# Newer Shopify exports use "Order tag" + "Customer name" + "Products bought together"
# instead of "Subscription or one-time" + "Customer ID" + "Is bundle"
_has_sub_col = "Subscription or one-time" in cleaned_df.columns
_has_tag_col = "Order tag"                in cleaned_df.columns
_cust_col    = "Customer ID"   if "Customer ID"   in cleaned_df.columns else "Customer name"
_bundle_col  = "Is bundle"     if "Is bundle"     in cleaned_df.columns else "Products bought together"


def _is_subscription(row):
    """Return True if the order row is a subscription purchase."""
    if _has_sub_col:
        return str(row.get("Subscription or one-time", "")).strip().lower().replace("-", "_") == "subscription"
    if _has_tag_col:
        return "subscription" in str(row.get("Order tag", "")).lower()
    return False  # can't tell → treat as one-time


# ── Scenario Mix ──────────────────────────────────────────────────────────────
st.markdown('<div class="section-label">09 — Scenario Mix · Model vs Actual</div>', unsafe_allow_html=True)
st.caption("% of D2C product lines by purchase type. Bundles are folded into '1 bottle one-time'.")

_SCENARIO_ORDER = [
    "1 bottle one-time", "3-pack one-time", "6-pack one-time",
    "1 bottle subscription", "3-pack subscription", "6-pack subscription",
]


def _classify_scenario(row):
    # Bundle: "Is bundle" (True/1) or "Products bought together" (non-empty string)
    raw_bundle = str(row.get(_bundle_col, "")).strip().lower()
    is_bundle  = raw_bundle in ("true", "1", "yes") or (
        _bundle_col == "Products bought together" and raw_bundle not in ("", "nan", "none")
    )
    is_sub     = _is_subscription(row)
    try:
        qty = int(float(row.get("Quantity ordered", 1) or 1))
    except (ValueError, TypeError):
        qty = 1
    if is_sub and not is_bundle:
        if qty >= 6:
            return "6-pack subscription"
        elif qty >= 3:
            return "3-pack subscription"
        else:
            return "1 bottle subscription"
    else:  # one-time or bundle → fold into OT
        if not is_bundle and qty >= 6:
            return "6-pack one-time"
        elif not is_bundle and qty >= 3:
            return "3-pack one-time"
        else:
            return "1 bottle one-time"


_sheets_ok = get_sheets_client_status() == "ready"

d2c_df = cleaned_df[cleaned_df["Product title"].isin(["Gut Balance", "Mood Balance"])].copy()

if not d2c_df.empty:
    d2c_df["scenario"]     = d2c_df.apply(_classify_scenario, axis=1)
    d2c_df["_month_label"] = pd.to_datetime(d2c_df["Month"]).dt.strftime("%b-%Y")

    # Count product lines per scenario/month → actual %
    sc_counts = (
        d2c_df.groupby(["_month_label", "scenario"])
        .size().reset_index(name="cnt")
    )
    sc_counts["actual_pct"] = (
        sc_counts["cnt"]
        / sc_counts.groupby("_month_label")["cnt"].transform("sum")
        * 100
    ).round(1)

    months_in_data = sorted(
        d2c_df["_month_label"].unique(),
        key=lambda m: pd.to_datetime(m, format="%b-%Y"),
    )

    # Attempt to load model mix
    model_mix  = {}
    if _sheets_ok:
        with st.spinner("Reading model scenario mix…"):
            _mix = read_model_scenario_mix()
        if _mix["ok"]:
            model_mix = _mix["data"]
        else:
            st.warning(f"Could not read model scenario mix: {_mix['error']}")

    # Build comparison table
    table_rows = []
    for scenario in _SCENARIO_ORDER:
        row = {"Scenario": scenario}
        for month in months_in_data:
            sub = sc_counts[
                (sc_counts["_month_label"] == month) &
                (sc_counts["scenario"] == scenario)
            ]
            actual_pct = sub["actual_pct"].values[0] if len(sub) else 0.0
            model_pct  = model_mix.get(scenario, {}).get(month, None)
            if model_pct is not None:
                row[month] = f"{actual_pct:.0f}%  (mod {model_pct*100:.0f}%)"
            else:
                row[month] = f"{actual_pct:.0f}%"
        table_rows.append(row)

    st.dataframe(pd.DataFrame(table_rows), width="stretch", hide_index=True)
else:
    st.info("No Gut Balance / Mood Balance rows found in cleaned data.")

# ── OT Retention ──────────────────────────────────────────────────────────────
st.markdown('<div class="section-label">10 — OT Retention · Model vs Actual</div>', unsafe_allow_html=True)
st.caption(
    "One-time customers only (subscriptions excluded). "
    "% of Customer IDs who placed ≥1 / ≥2 / ≥3 repeat one-time orders."
)

_d2c_mask = cleaned_df["Product title"].isin(["Gut Balance", "Mood Balance"])
_sub_flag  = cleaned_df.apply(_is_subscription, axis=1)
ot_df      = cleaned_df[_d2c_mask & ~_sub_flag].copy()


def _retention_stats(sub, label):
    if sub.empty or _cust_col not in sub.columns:
        return None
    cust_orders = sub.groupby(_cust_col)["Order name"].nunique()
    n = len(cust_orders)
    if n == 0:
        return None
    return {
        "Product":      label,
        "OT Customers": n,
        "≥1 Repeat — actual":  f"{(cust_orders >= 2).sum() / n * 100:.1f}%",
        "≥2 Repeats — actual": f"{(cust_orders >= 3).sum() / n * 100:.1f}%",
        "≥3 Repeats — actual": f"{(cust_orders >= 4).sum() / n * 100:.1f}%",
    }


# Load model retention assumptions
model_ret = {}
if _sheets_ok:
    with st.spinner("Reading model OT retention…"):
        _ret = read_model_ot_retention()
    if _ret["ok"]:
        model_ret = _ret["data"]
    else:
        st.warning(f"Could not read OT retention model: {_ret['error']}")

ret_rows = []
for product in ["Gut Balance", "Mood Balance", "Combined"]:
    sub = ot_df if product == "Combined" else (
        ot_df[ot_df["Product title"] == product] if not ot_df.empty else pd.DataFrame()
    )
    stats = _retention_stats(sub, product)
    if stats is None:
        continue

    m = model_ret.get(product, {})
    ret_rows.append({
        "Product":            stats["Product"],
        "OT Customers":       stats["OT Customers"],
        "≥1 Repeat — model":  f"{m.get('% >= 1 repeat',  0) * 100:.0f}%" if m else "—",
        "≥1 Repeat — actual": stats["≥1 Repeat — actual"],
        "≥2 Repeats — model": f"{m.get('% >= 2 repeats', 0) * 100:.0f}%" if m else "—",
        "≥2 Repeats — actual":stats["≥2 Repeats — actual"],
        "≥3 Repeats — model": f"{m.get('% >= 3 repeats', 0) * 100:.0f}%" if m else "—",
        "≥3 Repeats — actual":stats["≥3 Repeats — actual"],
    })

if ret_rows:
    st.dataframe(pd.DataFrame(ret_rows), width="stretch", hide_index=True)
else:
    st.info("No one-time D2C orders found — upload a Shopify CSV to see retention data.")
