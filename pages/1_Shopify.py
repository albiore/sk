import streamlit as st
import pandas as pd
import os
import io
from datetime import datetime
from cleaner import clean_dataframe, CLEANING_STEPS
from sheets import (
    push_to_performance_overview, get_sheets_client_status,
    read_model_scenario_mix, read_model_ot_retention,
)
from brand import BRAND_CSS
import storage

# ── Page config ──────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="SecondKind · Shopify",
    page_icon="🧬",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown(BRAND_CSS, unsafe_allow_html=True)

st.markdown("""
<div class="sk-header">
  <div>
    <div class="sk-logo">Second<span>Kind</span></div>
    <div class="sk-subtitle">Shopify Sales · Internal Analytics</div>
  </div>
</div>
""", unsafe_allow_html=True)


# ── Persistence helpers ───────────────────────────────────────────────────────
def load_stored():
    return storage.download_df("shopify_data.csv")


def load_meta():
    return storage.download_text("shopify_data_meta.txt")


def save_meta():
    ts = datetime.now().strftime("%d/%m/%Y %H:%M")
    storage.upload_text("shopify_data_meta.txt", ts)
    return ts


def merge_data(new_df: pd.DataFrame, stored) -> pd.DataFrame:
    """Month-level override: new file fully replaces any months it covers."""
    if stored is None or stored.empty:
        return new_df
    new_months = set(new_df["Month"].unique())
    kept       = stored[~stored["Month"].isin(new_months)].copy()
    combined   = pd.concat([kept, new_df], ignore_index=True)
    return combined.sort_values("Month").reset_index(drop=True)


def load_free_units():
    return storage.download_df("shopify_free_units.csv")


def load_b2b_data():
    return storage.download_df("shopify_b2b_data.csv")


# ── 01 — Upload ───────────────────────────────────────────────────────────────
st.markdown('<div class="section-label">01 — Upload Raw Export</div>', unsafe_allow_html=True)
st.caption("Export from Shopify Analytics › Sales › Group by Month, Order, Product. Download as CSV.")

uploaded = st.file_uploader(
    "Drop your Shopify CSV here",
    type=["csv"],
    label_visibility="collapsed"
)

stored_df  = load_stored()
last_upload = load_meta()

if stored_df is not None:
    months_stored = sorted(stored_df["Month"].unique())
    month_labels  = pd.to_datetime(months_stored).strftime("%b-%Y").tolist()
    meta_line     = f"  ·  Last uploaded {last_upload}" if last_upload else ""
    st.info(f"📦 Stored: **{len(stored_df)} rows** across **{', '.join(month_labels)}**{meta_line}  —  "
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
        cleaned_df     = stored_df
        log            = {}
        n_raw          = n_raw_orders = 0
        n_clean        = len(cleaned_df)
        n_clean_orders = cleaned_df["Order name"].nunique() if "Order name" in cleaned_df.columns else 0
else:
    raw_df         = pd.read_csv(uploaded)
    n_raw          = len(raw_df)
    n_raw_orders   = raw_df["Order name"].nunique() if "Order name" in raw_df.columns else 0
    new_df, log    = clean_dataframe(raw_df.copy())
    cleaned_df     = merge_data(new_df, stored_df)
    n_clean        = len(new_df)
    n_clean_orders = new_df["Order name"].nunique() if "Order name" in new_df.columns else 0

    storage.upload_df("shopify_data.csv", cleaned_df)

    # ── Extract and persist B2B (doctor) orders ──────────────────────────────
    _raw2 = raw_df.copy()
    _raw2["_qty2"]   = pd.to_numeric(_raw2.get("Quantity ordered", 0), errors="coerce").fillna(0)
    _raw2["_total2"] = pd.to_numeric(_raw2.get("Total sales",       0), errors="coerce").fillna(0)
    _b2b_mask = (
        _raw2["Order name"].notna() &
        (
            _raw2["Product title"].str.contains("Master Carton", case=False, na=False) |
            (_raw2["_qty2"] >= 12)
        ) &
        (_raw2["_total2"] > 0)
    )
    b2b_new = (
        _raw2[_b2b_mask][["Month", "Order name", "Product title", "Quantity ordered", "Total sales"]]
        .drop_duplicates()
        .copy()
    )
    storage.upload_df("shopify_b2b_data.csv", merge_data(b2b_new, load_b2b_data()))

    # ── Extract and persist free units ───────────────────────────────────────
    _raw2["_gross2"] = pd.to_numeric(_raw2.get("Gross sales", 0), errors="coerce").fillna(0)
    _fu_mask = (
        _raw2["Order name"].notna() &
        (_raw2["_gross2"] > 0) &
        (_raw2["_total2"] == 0)
    )
    fu_new = (
        _raw2[_fu_mask][["Month", "Order name", "Product title", "Quantity ordered"]]
        .drop_duplicates()
        .copy()
    )
    storage.upload_df("shopify_free_units.csv", merge_data(fu_new, load_free_units()))

    ts = save_meta()

    new_month_labels = sorted(
        pd.to_datetime(new_df["Month"].unique()).strftime("%b-%Y").tolist()
    )
    all_month_labels = sorted(
        pd.to_datetime(cleaned_df["Month"].unique()).strftime("%b-%Y").tolist()
    )
    if stored_df is not None:
        st.success(
            f"✓ Uploaded {ts}  ·  Months replaced: **{', '.join(new_month_labels)}**  ·  "
            f"Total stored: **{len(cleaned_df)} rows** across **{', '.join(all_month_labels)}**"
        )
    else:
        st.success(f"✓ Uploaded {ts}  ·  {n_clean} rows stored ({n_clean_orders} orders)")


# ── 02 — Export ───────────────────────────────────────────────────────────────
st.markdown('<div class="section-label">02 — Export & Push to Sheets</div>', unsafe_allow_html=True)

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
        st.caption("Writes Gut / Mood / Shipping revenue + orders + units to the hardcoded ACTUALS rows.")
    else:
        st.info(f"Google Sheets: {sheets_status}. Add credentials.json to enable.")


# ── 03 — Cleaning Summary ─────────────────────────────────────────────────────
st.markdown('<div class="section-label">03 — Cleaning Summary</div>', unsafe_allow_html=True)

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


# ── 04 — Performance by Month by Product ──────────────────────────────────────
st.markdown('<div class="section-label">04 — Performance by Month by Product</div>', unsafe_allow_html=True)
st.caption("Net revenue per month — the same figures pushed to the Performance Ov ACTUALS rows (Gut 13, Mood 14, Shipping 15).")
if {"Month", "Product title", "Total sales"}.issubset(cleaned_df.columns):
    _perf_df = cleaned_df.copy()
    _perf_df["_m"] = pd.to_datetime(_perf_df["Month"])
    perf_rows = []
    for _m, _g in _perf_df.groupby("_m"):
        _gut  = _g.loc[_g["Product title"] == "Gut Balance",  "Total sales"].sum()
        _mood = _g.loc[_g["Product title"] == "Mood Balance", "Total sales"].sum()
        _ship = _g.loc[_g["Product title"] == "Shipping",     "Total sales"].sum()
        perf_rows.append({
            "Month":                    _m.strftime("%b-%Y"),
            "Gut Balance":              _gut,
            "Mood Balance":             _mood,
            "Shipping":                 _ship,
            "Total":                    _gut + _mood + _ship,
        })
    perf_month = pd.DataFrame(perf_rows)
    for _c in ["Gut Balance", "Mood Balance", "Shipping", "Total"]:
        perf_month[_c] = perf_month[_c].map("${:,.2f}".format)
    st.dataframe(perf_month, width="stretch", hide_index=True)


# ── 05 — Revenue by Product ───────────────────────────────────────────────────
st.markdown('<div class="section-label">05 — Revenue by Product</div>', unsafe_allow_html=True)
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
    product_summary["Gross"]     = product_summary["Gross"].map("${:,.2f}".format)
    product_summary["Net"]       = product_summary["Net"].map("${:,.2f}".format)
    product_summary["Discounts"] = product_summary["Discounts"].map("${:,.2f}".format)
    st.dataframe(product_summary, width="stretch", hide_index=True)


# ── 06 — Shipping Revenue ─────────────────────────────────────────────────────
st.markdown('<div class="section-label">06 — Shipping Revenue</div>', unsafe_allow_html=True)
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
            .reset_index().sort_values("Month")
        )
        ship_monthly["Gross"] = ship_monthly["Gross"].map("${:,.2f}".format)
        ship_monthly["Net"]   = ship_monthly["Net"].map("${:,.2f}".format)
        st.dataframe(ship_monthly, width="stretch", hide_index=True)


# ── 07 — Monthly Revenue Trend ────────────────────────────────────────────────
st.markdown('<div class="section-label">07 — Monthly Revenue Trend</div>', unsafe_allow_html=True)
st.caption("Total monthly revenue across all SKUs — includes shipping revenue.")
if "Month" in cleaned_df.columns:
    monthly = (
        cleaned_df.groupby("Month")
        .agg(Orders=("Order name", "nunique"),
             Gross=("Gross sales", "sum"),
             Net=("Total sales", "sum"),
             Discounts=("Discounts", "sum"))
        .reset_index().sort_values("Month")
    )
    st.bar_chart(monthly.set_index("Month")["Net"], width="stretch")
    monthly["Gross"]     = monthly["Gross"].map("${:,.2f}".format)
    monthly["Net"]       = monthly["Net"].map("${:,.2f}".format)
    monthly["Discounts"] = monthly["Discounts"].map("${:,.2f}".format)
    st.dataframe(monthly, width="stretch", hide_index=True)


# ── 08 — Cleaned Data Preview ─────────────────────────────────────────────────
st.markdown('<div class="section-label">08 — Cleaned Data Preview</div>', unsafe_allow_html=True)
st.caption(f"{n_clean} rows · {n_clean_orders} orders · scroll to explore")
st.dataframe(cleaned_df, width="stretch", hide_index=True, height=320)


# ── Column-set detection (shared by sections 09, 10, 11) ─────────────────────
# Newer Shopify exports use "Order tag" + "Customer name" + "Products bought together"
# instead of "Subscription or one-time" + "Customer ID" + "Is bundle"
_has_sub_col = "Subscription or one-time" in cleaned_df.columns
_has_tag_col = "Order tag"                in cleaned_df.columns
_cust_col    = "Customer ID"   if "Customer ID"   in cleaned_df.columns else "Customer name"
_bundle_col  = "Is bundle"     if "Is bundle"     in cleaned_df.columns else "Products bought together"
_acq_col     = "New or returning customer" if "New or returning customer" in cleaned_df.columns else None

# Subscription orders carry multiple tags:
#   "Subscription, Subscription First Order"     → acquisition (first) order
#   "Subscription, Subscription Recurring Order" → retention (recurring) order
_SUB_FIRST_TAG = "subscription first order"


def _is_subscription(row):
    """True for ANY subscription order (first or recurring) — used to exclude subs."""
    if _has_sub_col:
        val = str(row.get("Subscription or one-time", "")).strip().lower().replace("-", "_")
        return val == "subscription"
    if _has_tag_col:
        return "subscription" in str(row.get("Order tag", "")).lower()
    return False


def _is_subscription_first_order(row):
    """True only for a subscription's acquisition (first) order."""
    if _has_sub_col:
        # Old export has no first/recurring split — treat all subs as first
        return _is_subscription(row)
    if _has_tag_col:
        return _SUB_FIRST_TAG in str(row.get("Order tag", "")).lower()
    return False


# ── 09 — Scenario Mix ─────────────────────────────────────────────────────────
st.markdown('<div class="section-label">09 — Scenario Mix · Model vs Actual</div>', unsafe_allow_html=True)
st.caption(
    "% of **acquisition** D2C orders by purchase type. Subscriptions tagged via "
    "'Subscription First Order'; pack size from units (6 → 6-pack, 3 → 3-pack, else 1 bottle)."
)

_SCENARIO_ORDER = [
    "1 bottle one-time", "3-pack one-time", "6-pack one-time",
    "1 bottle subscription", "3-pack subscription", "6-pack subscription",
]


def _classify_scenario(row):
    is_sub = _is_subscription_first_order(row)
    try:
        qty = int(float(row.get("Quantity ordered", 1) or 1))
    except (ValueError, TypeError):
        qty = 1
    # Pack size from units: 6 → 6-pack, 3 → 3-pack, everything else → 1 bottle
    if qty == 6:   pack = "6-pack"
    elif qty == 3: pack = "3-pack"
    else:          pack = "1 bottle"
    return f"{pack} {'subscription' if is_sub else 'one-time'}"


_sheets_ok = get_sheets_client_status() == "ready"

d2c_df = cleaned_df[cleaned_df["Product title"].isin(["Gut Balance", "Mood Balance"])].copy()
# Scenario mix considers acquisition orders only (new customers)
if _acq_col is not None:
    d2c_df = d2c_df[d2c_df[_acq_col].astype(str).str.strip().str.lower() == "new"].copy()

if not d2c_df.empty:
    d2c_df["scenario"]     = d2c_df.apply(_classify_scenario, axis=1)
    d2c_df["_month_label"] = pd.to_datetime(d2c_df["Month"]).dt.strftime("%b-%Y")

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

    model_mix = {}
    if _sheets_ok:
        with st.spinner("Reading model scenario mix…"):
            _mix = read_model_scenario_mix()
        if _mix["ok"]:
            model_mix = _mix["data"]
        else:
            st.warning(f"Could not read model scenario mix: {_mix['error']}")

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


# ── 10 — OT Retention ─────────────────────────────────────────────────────────
st.markdown('<div class="section-label">10 — OT Retention · Model vs Actual</div>', unsafe_allow_html=True)
st.caption(
    "One-time customers only (subscriptions excluded). "
    "% of customers who placed ≥1 / ≥2 / ≥3 repeat one-time orders."
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
        "Product":       label,
        "OT Customers":  n,
        "≥1 Repeat":     f"{(cust_orders >= 2).sum() / n * 100:.1f}%",
        "≥2 Repeats":    f"{(cust_orders >= 3).sum() / n * 100:.1f}%",
        "≥3 Repeats":    f"{(cust_orders >= 4).sum() / n * 100:.1f}%",
    }


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
        "≥1 Repeat — actual": stats["≥1 Repeat"],
        "≥2 Repeats — model": f"{m.get('% >= 2 repeats', 0) * 100:.0f}%" if m else "—",
        "≥2 Repeats — actual":stats["≥2 Repeats"],
        "≥3 Repeats — model": f"{m.get('% >= 3 repeats', 0) * 100:.0f}%" if m else "—",
        "≥3 Repeats — actual":stats["≥3 Repeats"],
    })

if ret_rows:
    st.dataframe(pd.DataFrame(ret_rows), width="stretch", hide_index=True)
else:
    st.info("No one-time D2C orders found — upload a Shopify CSV to see retention data.")


# ── 11 — Acquisition & Retention ─────────────────────────────────────────────
st.markdown('<div class="section-label">11 — Deals per Product · Acquisition vs Retention</div>', unsafe_allow_html=True)
st.caption(
    "Number of deals (orders) per product, per month, split by new (acquisition) vs "
    "returning (retention) customers. Acquisition deals feed CAC; retention deals feed CPRU."
)

if _acq_col is None:
    st.info("Column 'New or returning customer' not found in the CSV — cannot split acquisition vs retention.")
else:
    acq_df = cleaned_df[cleaned_df["Product title"].isin(["Gut Balance", "Mood Balance"])].copy()
    acq_df = acq_df[acq_df["Total sales"] > 0]  # exclude refund rows

    if acq_df.empty:
        st.info("No D2C order rows found.")
    else:
        acq_df["_month_label"] = pd.to_datetime(acq_df["Month"]).dt.strftime("%b-%Y")
        acq_df["_sort"]        = pd.to_datetime(acq_df["Month"])
        acq_df["_is_new"]      = acq_df[_acq_col].astype(str).str.strip().str.lower() == "new"

        # One table per product: rows = month, cols = Acquisition / Retention / Total deals
        for product in ["Gut Balance", "Mood Balance"]:
            p_df = acq_df[acq_df["Product title"] == product]
            if p_df.empty:
                continue
            st.markdown(f'<div class="section-label" style="margin-top:1rem;">{product}</div>', unsafe_allow_html=True)
            rows = []
            for _sort, m_df in p_df.groupby("_sort"):
                acq_deals = m_df[m_df["_is_new"]]["Order name"].nunique()
                ret_deals = m_df[~m_df["_is_new"]]["Order name"].nunique()
                total     = acq_deals + ret_deals
                rows.append({
                    "Month":             pd.Timestamp(_sort).strftime("%b-%Y"),
                    "Acquisition Deals": acq_deals,
                    "Retention Deals":   ret_deals,
                    "Total Deals":       total,
                    "Acq %":             f"{acq_deals / total * 100:.0f}%" if total else "—",
                    "Ret %":             f"{ret_deals / total * 100:.0f}%" if total else "—",
                })
            # All-time total row for this product
            acq_all = p_df[p_df["_is_new"]]["Order name"].nunique()
            ret_all = p_df[~p_df["_is_new"]]["Order name"].nunique()
            tot_all = acq_all + ret_all
            rows.append({
                "Month":             "TOTAL",
                "Acquisition Deals": acq_all,
                "Retention Deals":   ret_all,
                "Total Deals":       tot_all,
                "Acq %":             f"{acq_all / tot_all * 100:.0f}%" if tot_all else "—",
                "Ret %":             f"{ret_all / tot_all * 100:.0f}%" if tot_all else "—",
            })
            st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True)


# ── 12 — Cross-sell Rates ─────────────────────────────────────────────────────
st.markdown('<div class="section-label">12 — Cross-sell Rates</div>', unsafe_allow_html=True)
st.caption(
    "Same-order cross-sell: among orders containing product A, % that also contain product B."
)

_XSELL_PRODUCTS = ["Gut Balance", "Mood Balance"]
xs_df = cleaned_df[cleaned_df["Product title"].isin(_XSELL_PRODUCTS)].copy()

if xs_df.empty:
    st.info("No D2C product rows found.")
else:
    xs_df["_month_dt"] = pd.to_datetime(xs_df["Month"])

    # Per-order product quantities (for same-product upsell detection)
    xs_df["_qty"] = pd.to_numeric(xs_df["Quantity ordered"], errors="coerce").fillna(0)
    order_qty = (
        xs_df.groupby(["Order name", "Product title"])
        .agg(_qty=("_qty", "sum"))
        .reset_index()
    )

    def _xsell_rates(oq):
        """Return {(from_p, to_p): rate} for a given order_qty slice."""
        rates = {}
        for from_p in _XSELL_PRODUCTS:
            from_orders = set(oq[oq["Product title"] == from_p]["Order name"])
            n = len(from_orders)
            for to_p in _XSELL_PRODUCTS:
                if n == 0:
                    rates[(from_p, to_p)] = None
                elif from_p == to_p:
                    # Same-product upsell: exactly 2 units (3 = 3-pack, 6 = 6-pack)
                    multi = oq[
                        (oq["Product title"] == from_p) &
                        (oq["_qty"] == 2) &
                        (oq["Order name"].isin(from_orders))
                    ]
                    rates[(from_p, to_p)] = len(multi) / n
                else:
                    to_orders = set(oq[oq["Product title"] == to_p]["Order name"])
                    rates[(from_p, to_p)] = len(from_orders & to_orders) / n
        return rates

    # ── All-time matrix ───────────────────────────────────────────────────────
    all_rates   = _xsell_rates(order_qty)
    matrix_rows = []
    for from_p in _XSELL_PRODUCTS:
        from_orders = set(order_qty[order_qty["Product title"] == from_p]["Order name"])
        row = {"Product (From →)": from_p, "Orders": len(from_orders)}
        for to_p in _XSELL_PRODUCTS:
            r = all_rates[(from_p, to_p)]
            row[f"→ {to_p}"] = f"{r * 100:.1f}%" if r is not None else "—"
        matrix_rows.append(row)

    st.dataframe(pd.DataFrame(matrix_rows), width="stretch", hide_index=True)

    # ── Monthly breakdown ─────────────────────────────────────────────────────
    st.caption("Same metric broken down by month.")
    all_months   = sorted(xs_df["_month_dt"].unique())
    _pair_labels = [f"{a} → {b}" for a in _XSELL_PRODUCTS for b in _XSELL_PRODUCTS]
    trend = {p: {} for p in _pair_labels}

    for m in all_months:
        m_label  = pd.Timestamp(m).strftime("%b-%Y")
        m_oq     = order_qty[order_qty["Order name"].isin(
            xs_df[xs_df["_month_dt"] == m]["Order name"]
        )]
        m_rates  = _xsell_rates(m_oq)
        for from_p in _XSELL_PRODUCTS:
            for to_p in _XSELL_PRODUCTS:
                pair = f"{from_p} → {to_p}"
                r    = m_rates[(from_p, to_p)]
                trend[pair][m_label] = f"{r * 100:.1f}%" if r is not None else "—"

    month_labels = [pd.Timestamp(m).strftime("%b-%Y") for m in all_months]
    trend_rows   = [{"Pair": pair, **{m: trend[pair].get(m, "—") for m in month_labels}}
                    for pair in _pair_labels]
    st.dataframe(pd.DataFrame(trend_rows), width="stretch", hide_index=True)


# ── 13 — OT Retention Detail by Scenario ─────────────────────────────────────
st.markdown('<div class="section-label">13 — OT Retention · Detail by Scenario</div>', unsafe_allow_html=True)
st.caption(
    "One-time customers only. For each product × scenario: repeat rates, timing of first "
    "repeat purchase (distribution across Month+1 … Month+6+), and average reorder price & units."
)

_OT_SCENARIOS = ["1 bottle one-time", "3-pack one-time", "6-pack one-time"]
_TIMING_BUCKETS = ["Month+1", "Month+2", "Month+3", "Month+4", "Month+5", "Month+6+"]

ot13_df = cleaned_df[
    cleaned_df["Product title"].isin(["Gut Balance", "Mood Balance"])
].copy()
_sub13 = ot13_df.apply(_is_subscription, axis=1)
ot13_df = ot13_df[~_sub13].copy()

if ot13_df.empty or _cust_col not in ot13_df.columns:
    st.info("No one-time D2C orders found.")
else:
    ot13_df["scenario"]  = ot13_df.apply(_classify_scenario, axis=1)
    ot13_df["_month_dt"] = pd.to_datetime(ot13_df["Month"])
    ot13_df["_qty"]      = pd.to_numeric(ot13_df["Quantity ordered"], errors="coerce").fillna(1)

    # Deduplicate to one row per order (revenue/units are at order-product level)
    orders_dedup = ot13_df.drop_duplicates(subset=["Order name", "Product title"])

    for product in ["Gut Balance", "Mood Balance"]:
        prod_df = orders_dedup[orders_dedup["Product title"] == product].copy()
        if prod_df.empty:
            continue

        st.markdown(f'<div class="section-label" style="margin-top:1rem;">{product}</div>', unsafe_allow_html=True)

        # First order per customer for this product
        first = (
            prod_df.sort_values("_month_dt")
            .groupby(_cust_col, sort=False)
            .agg(
                first_scenario=("scenario", "first"),
                first_date=("_month_dt", "min"),
                first_order=("Order name", "first"),
            )
            .reset_index()
        )

        rate_rows   = []
        timing_rows = []

        for scenario in _OT_SCENARIOS:
            sc_custs = first[first["first_scenario"] == scenario]
            n = len(sc_custs)
            if n == 0:
                continue

            # All orders by these customers for this product (including first)
            cust_set   = set(sc_custs[_cust_col])
            cust_orders = prod_df[prod_df[_cust_col].isin(cust_set)].copy()

            # Repeat order counts per customer (total orders minus first)
            order_ct = cust_orders.groupby(_cust_col)["Order name"].nunique()
            pct1 = (order_ct >= 2).sum() / n
            pct2 = (order_ct >= 3).sum() / n
            pct3 = (order_ct >= 4).sum() / n

            # Repeat orders only (exclude first order per customer)
            first_map = sc_custs.set_index(_cust_col)["first_order"]
            repeat_orders = cust_orders[
                cust_orders.apply(
                    lambda r: r["Order name"] != first_map.get(r[_cust_col]), axis=1
                )
            ]

            avg_price = repeat_orders["Total sales"].mean() if not repeat_orders.empty else 0
            avg_units = repeat_orders["_qty"].mean()         if not repeat_orders.empty else 0

            rate_rows.append({
                "Scenario":         scenario,
                "OT Customers":     n,
                "≥1 Repeat":        f"{pct1 * 100:.1f}%",
                "≥2 Repeats":       f"{pct2 * 100:.1f}%",
                "≥3 Repeats":       f"{pct3 * 100:.1f}%",
                "Avg Reorder $":    f"${avg_price:.2f}" if avg_price else "—",
                "Avg Reorder Units":f"{avg_units:.1f}"  if avg_units else "—",
            })

            # Timing: first repeat purchase — how many months after first order?
            first_repeats = (
                repeat_orders.sort_values("_month_dt")
                .groupby(_cust_col)
                .first()
                .reset_index()
            )
            first_repeats = first_repeats.merge(
                sc_custs[[_cust_col, "first_date"]], on=_cust_col
            )
            first_repeats["months_later"] = (
                (first_repeats["_month_dt"] - first_repeats["first_date"])
                / pd.Timedelta(days=30.44)
            ).round().astype(int).clip(lower=1)

            total_repeaters = len(first_repeats)
            t_row = {"Scenario": scenario}
            weight_sum = 0.0
            for i in range(1, 6):
                w = (first_repeats["months_later"] == i).sum() / total_repeaters if total_repeaters else 0
                t_row[f"Month+{i}"] = f"{w:.0%}"
                weight_sum += w
            w6 = (first_repeats["months_later"] >= 6).sum() / total_repeaters if total_repeaters else 0
            t_row["Month+6+"] = f"{w6:.0%}"
            weight_sum += w6
            t_row["Sum"] = f"{weight_sum:.0%}" if total_repeaters else "—"
            timing_rows.append(t_row)

        if rate_rows:
            st.dataframe(pd.DataFrame(rate_rows), width="stretch", hide_index=True)
        if timing_rows:
            st.caption("Timing of first repeat purchase (distribution across months after first order)")
            st.dataframe(pd.DataFrame(timing_rows), width="stretch", hide_index=True)


# ── 14 — Revenue & Units Overview ─────────────────────────────────────────────
st.markdown('<div class="section-label">14 — Revenue &amp; Units Overview</div>', unsafe_allow_html=True)
st.caption(
    "Monthly snapshot: Shopify consumer revenue, B2B (doctor) orders (qty ≥ 12), "
    "free units sent to partners, and Amazon paid units. "
    "Gross Sales use full list price of $44.99/unit."
)

_FULL_PRICE = 44.99

_ov_b2b = load_b2b_data()
_ov_fu  = load_free_units()
_ov_amz = storage.download_df("amazon_data.csv")

# Consumer aggregates
_ov_cons = cleaned_df.copy()
_ov_cons["_mdt"]   = pd.to_datetime(_ov_cons["Month"])
_ov_cons["_total"] = pd.to_numeric(_ov_cons["Total sales"],       errors="coerce").fillna(0)
_ov_cons["_qty"]   = pd.to_numeric(_ov_cons["Quantity ordered"],  errors="coerce").fillna(0)
_prod_rows = _ov_cons["Product title"] != "Shipping"
_cons_net  = _ov_cons.groupby("_mdt")["_total"].sum()
_cons_units = _ov_cons[_prod_rows].groupby("_mdt")["_qty"].sum()

# B2B aggregates
if _ov_b2b is not None and not _ov_b2b.empty:
    _b2b_g = _ov_b2b.copy()
    _b2b_g["_mdt"]   = pd.to_datetime(_b2b_g["Month"])
    _b2b_g["_total"] = pd.to_numeric(_b2b_g["Total sales"], errors="coerce").fillna(0)
    _b2b_rev = _b2b_g.groupby("_mdt")["_total"].sum()
else:
    _b2b_rev = pd.Series(dtype=float)

# Free unit aggregates
if _ov_fu is not None and not _ov_fu.empty:
    _fu_g = _ov_fu.copy()
    _fu_g["_mdt"] = pd.to_datetime(_fu_g["Month"])
    _fu_g["_qty"] = pd.to_numeric(_fu_g["Quantity ordered"], errors="coerce").fillna(0)
    _fu_units = _fu_g.groupby("_mdt")["_qty"].sum()
else:
    _fu_units = pd.Series(dtype=float)

# Amazon paid unit aggregates
if _ov_amz is not None and not _ov_amz.empty:
    _amz_g = _ov_amz[_ov_amz["is_free"] == False].copy()
    _amz_g["_mdt"] = pd.to_datetime(_amz_g["_month_key"])
    _amz_units = _amz_g.groupby("_mdt")["units"].sum()
else:
    _amz_units = pd.Series(dtype=float)

_ov_months = sorted(_ov_cons["_mdt"].unique())
_ov_rows = []
for _m in _ov_months:
    _net      = _cons_net.get(_m, 0.0)
    _b2b_r    = _b2b_rev.get(_m, 0.0)
    _total_r  = _net + _b2b_r
    _fu_u     = int(_fu_units.get(_m, 0))
    _cu       = int(_cons_units.get(_m, 0))
    _gross_c  = _cu * _FULL_PRICE
    _tot_gs   = _gross_c + _b2b_r
    _amz_u    = int(_amz_units.get(_m, 0))
    _tot_ec   = _tot_gs + _amz_u * _FULL_PRICE

    _ov_rows.append({
        "Month":                        pd.Timestamp(_m).strftime("%B %Y"),
        "Net Revenue":                  f"${_net:,.0f}",
        "eCom + B2B Net Revenue":       f"${_total_r:,.0f}",
        "Free Units":                   _fu_u or "—",
        "Total Units Consumer":         _cu,
        "Gross Sales Consumers":        f"${_gross_c:,.0f}",
        "eCom + B2B Gross Sales":       f"${_tot_gs:,.0f}",
        "Amazon Units":                 _amz_u or "—",
        "Total Gross Sales eCom+AMZ":   f"${_tot_ec:,.0f}",
    })

if _ov_rows:
    st.dataframe(pd.DataFrame(_ov_rows), use_container_width=True, hide_index=True)
    if _ov_b2b is None or _ov_b2b.empty:
        st.caption(
            "⚠ B2B/doctor order data not yet stored — upload a new Shopify CSV to populate it. "
            "Until then, eCom + B2B Net Revenue = Net Revenue and eCom + B2B Gross Sales = Gross Sales Consumers."
        )
