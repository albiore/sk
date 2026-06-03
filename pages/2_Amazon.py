import streamlit as st
import pandas as pd
import os
from sheets import push_amazon_to_performance_overview, get_sheets_client_status
from brand import BRAND_CSS

# ── Constants ─────────────────────────────────────────────────────────────────
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STORE_FILE         = os.path.join(_ROOT, "amazon_data.csv")
STORE_REFUNDS_FILE = os.path.join(_ROOT, "amazon_refunds.csv")

# ASIN → product name mapping
ASIN_MAP = {
    "B0G1PTSQTS": "Gut Balance",
    "B0G1NL6TQC": "Mood Balance",
}

# ── Page config ───────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="SecondKind · Amazon",
    page_icon="🧬",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── Brand CSS ─────────────────────────────────────────────────────────────────
st.markdown(BRAND_CSS, unsafe_allow_html=True)

# ── Header ────────────────────────────────────────────────────────────────────
st.markdown("""
<div class="sk-header">
  <div>
    <div class="sk-logo">Second<span>Kind</span> · Amazon</div>
    <div class="sk-subtitle">Amazon Orders Cleaner · Internal Tool</div>
  </div>
</div>
""", unsafe_allow_html=True)


# ── Helper: categorise an order row ──────────────────────────────────────────
def _categorize(is_free: bool, coupon: str) -> str:
    if is_free:
        return "Vine"
    c = str(coupon).lower()
    if "subscribe and save" in c or "fba subscribe & save" in c:
        return "Subscribe & Save"
    if coupon and coupon != "nan":
        return "Other discount"
    return "Real client"


# ── Helper: clean a raw Amazon Orders XLSX ───────────────────────────────────
def clean_amazon_file(raw: pd.DataFrame):
    log = {}
    df  = raw.copy()
    df.columns = df.columns.str.strip()
    log["total_in"] = len(df)

    # Dropped-status buckets — for visibility only, NOT pushed to the model.
    _status = df["OrderStatus"].value_counts()
    log["cancelled"] = int(_status.get("Cancelled", 0))
    log["unshipped"] = int(_status.get("Unshipped", 0))
    log["returned"]  = int(_status.get("Return", 0))

    # Refunds = returned D2C orders for our ASINs. Seller Board books these as a
    # separate refund line while still counting the original sale; we surface them
    # here but keep them OUT of active_df so pushed actuals stay shipped-paying net.
    _ret = df[(df["OrderStatus"] == "Return") & (df["IsBusinessOrder"] == False)].copy()
    _ret["product_group"] = _ret["Products"].map(ASIN_MAP)
    _ret = _ret[_ret["product_group"].notna()].copy()
    _ret["Order date"]   = pd.to_datetime(_ret["PurchaseDate(UTC)"], dayfirst=True, errors="coerce")
    _ret = _ret[_ret["Order date"].notna()].copy()
    _ret["_month_key"]   = _ret["Order date"].dt.strftime("%Y-%m-01")
    _ret["Month"]        = _ret["Order date"].dt.strftime("%b-%Y")
    _ret["units"]        = pd.to_numeric(_ret["NumberOfItems"], errors="coerce").fillna(0).astype(int)
    _ret["refund_value"] = pd.to_numeric(_ret["OrderTotalAmount"], errors="coerce").fillna(0)
    log["returns_units"] = int(_ret["units"].sum())
    log["returns_value"] = round(float(_ret["refund_value"].sum()), 2)

    # Keep only Shipped orders
    df = df[df["OrderStatus"] == "Shipped"].copy()
    log["non_shipped"] = log["total_in"] - len(df)

    # Drop B2B
    df = df[df["IsBusinessOrder"] == False].copy()
    log["b2b"] = log["total_in"] - log["non_shipped"] - len(df)

    # Parse date (format: DD/MM/YYYY HH:MM:SS)
    df["Order date"] = pd.to_datetime(df["PurchaseDate(UTC)"], dayfirst=True, errors="coerce")
    bad_dates = int(df["Order date"].isna().sum())
    if bad_dates:
        log["bad_dates"] = bad_dates
    df = df[df["Order date"].notna()].copy()

    # Month keys
    df["_month_key"] = df["Order date"].dt.strftime("%Y-%m-01")
    df["Month"]      = df["Order date"].dt.strftime("%b-%Y")

    # Numeric fields
    df["OrderTotalAmount"] = pd.to_numeric(df["OrderTotalAmount"], errors="coerce").fillna(0)
    df["Item promotion"]   = pd.to_numeric(df["Item promotion"],   errors="coerce").fillna(0)
    df["units"]            = pd.to_numeric(df["NumberOfItems"],    errors="coerce").fillna(0).astype(int)

    # Revenue = list price + promotions (promos are negative)
    df["revenue"] = df["OrderTotalAmount"] + df["Item promotion"]

    # Free units: full-price promo (Vine) → revenue ≤ 0
    df["is_free"] = (df["revenue"] <= 0) & (df["OrderTotalAmount"] > 0)

    # Product group via ASIN
    df["product_group"] = df["Products"].map(ASIN_MAP)
    unclassified = int(df["product_group"].isna().sum())
    log["unclassified"] = unclassified
    df = df[df["product_group"].notna()].copy()

    # Normalise coupon: strip NaN
    df["coupon_clean"] = df["Coupons"].fillna("").astype(str).str.strip()

    # Category
    df["category"] = df.apply(
        lambda r: _categorize(r["is_free"], r["coupon_clean"]), axis=1
    )

    # Rename order ID to match sheets.py expectation
    df = df.rename(columns={"AmazonOrderId": "Order ID"})

    log["total_out"]  = len(df)
    log["vine_units"] = int(df["is_free"].sum())
    log["sns_orders"] = int((df["category"] == "Subscribe & Save").sum())

    # Per-month/product refund aggregate — persisted separately, never pushed.
    refunds_df = (
        _ret.rename(columns={"AmazonOrderId": "Order ID"})
            .groupby(["_month_key", "Month", "product_group"])
            .agg(Returned_Orders=("Order ID", "nunique"),
                 Returned_Units=("units", "sum"),
                 Refund_Value=("refund_value", "sum"))
            .reset_index()
    )

    keep_cols = [
        "Order ID", "Order date", "_month_key", "Month",
        "Products", "product_group", "category",
        "OrderTotalAmount", "revenue", "units", "is_free", "coupon_clean",
    ]
    return df[keep_cols].reset_index(drop=True), log, refunds_df


# ── Helper: load stored data ──────────────────────────────────────────────────
def load_stored():
    if os.path.exists(STORE_FILE):
        df = pd.read_csv(STORE_FILE, parse_dates=["Order date"])
        # Restore bool column
        if "is_free" in df.columns:
            df["is_free"] = df["is_free"].astype(bool)
        return df
    return None


# ── Helper: merge new + stored with month-level override ─────────────────────
def merge_data(new: pd.DataFrame, stored) -> pd.DataFrame:
    if stored is None or stored.empty:
        return new
    # Drop any stored rows whose month is covered by the new file,
    # then append the new file's data for those months.
    new_months   = set(new["_month_key"].unique())
    stored_kept  = stored[~stored["_month_key"].isin(new_months)].copy()
    combined     = pd.concat([stored_kept, new], ignore_index=True)
    combined     = combined.sort_values("Order date").reset_index(drop=True)
    return combined


# ── Helper: load / merge refunds (display-only, never pushed) ─────────────────
def load_refunds():
    if os.path.exists(STORE_REFUNDS_FILE):
        return pd.read_csv(STORE_REFUNDS_FILE)
    return None


def merge_refunds(new: pd.DataFrame, stored) -> pd.DataFrame:
    if stored is None or stored.empty:
        return new
    new_months  = set(new["_month_key"].unique())
    stored_kept = stored[~stored["_month_key"].isin(new_months)].copy()
    return (pd.concat([stored_kept, new], ignore_index=True)
            .sort_values("_month_key").reset_index(drop=True))


# ── Upload section ────────────────────────────────────────────────────────────
st.markdown('<div class="section-label">01 — Upload Amazon Orders Report</div>', unsafe_allow_html=True)
st.caption("Amazon Seller Central → Reports → Orders → Download as XLSX (all statuses, full date range)")

uploaded = st.file_uploader(
    "Drop your Amazon Orders XLSX here",
    type=["xlsx"],
    label_visibility="collapsed",
)

# ── Show stored data status ───────────────────────────────────────────────────
stored_df = load_stored()
if stored_df is not None:
    months_stored = sorted(stored_df["_month_key"].unique())
    month_labels  = pd.to_datetime(months_stored).strftime("%b-%Y").tolist()
    st.info(f"📦 Stored: **{len(stored_df)} orders** across **{', '.join(month_labels)}**  —  "
            f"upload a new file to add data, or push as-is below.")

if not uploaded:
    if stored_df is None:
        st.markdown("""<div style="margin-top:3rem; text-align:center; color:#9C9590;
          font-family:'DM Mono',monospace; font-size:0.8rem;">Waiting for XLSX upload…</div>""",
          unsafe_allow_html=True)
        st.stop()
    else:
        active_df      = stored_df
        active_refunds = load_refunds()
        log            = {}
else:
    raw_df                   = pd.read_excel(uploaded)
    new_df, log, new_refunds = clean_amazon_file(raw_df)
    active_df                = merge_data(new_df, stored_df)
    active_refunds           = merge_refunds(new_refunds, load_refunds())

    # Save merged data (refunds persisted separately — never part of the push)
    active_df.to_csv(STORE_FILE, index=False)
    active_refunds.to_csv(STORE_REFUNDS_FILE, index=False)
    if stored_df is not None:
        new_months_labels = sorted(
            pd.to_datetime(new_df["_month_key"].unique()).strftime("%b-%Y").tolist()
        )
        all_months_labels = sorted(
            pd.to_datetime(active_df["_month_key"].unique()).strftime("%b-%Y").tolist()
        )
        st.success(
            f"✓ Months replaced: **{', '.join(new_months_labels)}** · "
            f"Total stored: **{len(active_df)} orders** across **{', '.join(all_months_labels)}**"
        )
    else:
        st.success(f"✓ {log['total_out']} orders stored")

# ── Cleaning summary ──────────────────────────────────────────────────────────
st.markdown('<div class="section-label">02 — Cleaning Summary</div>', unsafe_allow_html=True)

if log:
    steps = [
        ("Raw rows in file",           log["total_in"]),
        ("Non-shipped removed",        log["non_shipped"]),
        ("B2B removed",                log.get("b2b", 0)),
        ("Unclassified ASINs removed", log.get("unclassified", 0)),
        ("Kept (Shipped, D2C)",        log["total_out"]),
        ("of which Vine (free units)", log.get("vine_units", 0)),
        ("of which Subscribe & Save",  log.get("sns_orders", 0)),
        ("Cancelled (dropped)",        log.get("cancelled", 0)),
        ("Unshipped (dropped)",        log.get("unshipped", 0)),
        ("Returned (dropped)",         log.get("returned", 0)),
    ]
    pills_html = '<div class="step-row">'
    for label, count in steps:
        active = "active" if count > 0 else ""
        pills_html += f'<div class="step-pill {active}">◎ {label}: {count}</div>'
    pills_html += "</div>"
    st.markdown(pills_html, unsafe_allow_html=True)

# Refunds (computed from returned orders; persisted separately; NEVER pushed).
if active_refunds is not None and not active_refunds.empty:
    r_orders = int(active_refunds["Returned_Orders"].sum())
    r_units  = int(active_refunds["Returned_Units"].sum())
    r_value  = float(active_refunds["Refund_Value"].sum())
    st.caption(
        f"↩︎ Refunds (computed, **not** pushed): {r_orders} returned orders · "
        f"{r_units} units · ${r_value:,.2f}. Seller Board books these as a separate "
        "refund line; the model push sends shipped-paying net revenue only."
    )

# ── KPI cards ─────────────────────────────────────────────────────────────────
st.markdown('<div class="section-label">03 — Overview</div>', unsafe_allow_html=True)

paying      = active_df[~active_df["is_free"]]
total_rev   = paying["revenue"].sum()
gut_rev     = paying[paying["product_group"] == "Gut Balance"]["revenue"].sum()
mood_rev    = paying[paying["product_group"] == "Mood Balance"]["revenue"].sum()
total_orders= paying["Order ID"].nunique()
total_units = paying["units"].sum()
free_units  = int(active_df[active_df["is_free"]]["units"].sum())
sns_orders  = int((active_df["category"] == "Subscribe & Save").sum())

st.markdown(f"""
<div class="stat-grid">
  <div class="stat-card">
    <div class="stat-label">Net Revenue (paying)</div>
    <div class="stat-value">${total_rev:,.0f}</div>
    <div class="stat-sub">Vine excluded</div>
  </div>
  <div class="stat-card">
    <div class="stat-label">Gut Balance</div>
    <div class="stat-value">${gut_rev:,.0f}</div>
    <div class="stat-sub">net revenue</div>
  </div>
  <div class="stat-card">
    <div class="stat-label">Mood Balance</div>
    <div class="stat-value">${mood_rev:,.0f}</div>
    <div class="stat-sub">net revenue</div>
  </div>
  <div class="stat-card">
    <div class="stat-label">Paying Orders</div>
    <div class="stat-value">{total_orders}</div>
    <div class="stat-sub">{int(total_units)} units</div>
  </div>
</div>
<div class="stat-grid" style="grid-template-columns: repeat(2,1fr); margin-top:0;">
  <div class="stat-card">
    <div class="stat-label">Free Units (Vine)</div>
    <div class="stat-value">{free_units}</div>
    <div class="stat-sub">$0 net revenue · excluded from totals above</div>
  </div>
  <div class="stat-card">
    <div class="stat-label">Subscribe &amp; Save Orders</div>
    <div class="stat-value">{sns_orders}</div>
    <div class="stat-sub">of {total_orders} paying orders</div>
  </div>
</div>
""", unsafe_allow_html=True)

# ── Category breakdown ────────────────────────────────────────────────────────
st.markdown('<div class="section-label">04 — Breakdown by Category</div>', unsafe_allow_html=True)
st.caption("Real client · Subscribe & Save · Vine · Other discount — by product and month.")

breakdown = (
    active_df.groupby(["Month", "_month_key", "product_group", "category"])
    .agg(Orders=("Order ID", "nunique"), Units=("units", "sum"), Revenue=("revenue", "sum"))
    .reset_index()
    .sort_values(["_month_key", "product_group", "category"])
    .drop(columns="_month_key")
)
breakdown["Revenue"] = breakdown["Revenue"].map("${:,.2f}".format)
st.dataframe(breakdown, width="stretch", hide_index=True)

# ── Monthly summary ────────────────────────────────────────────────────────────
st.markdown('<div class="section-label">05 — Monthly Summary · Paying Orders Only</div>', unsafe_allow_html=True)

monthly = (
    paying.groupby(["_month_key", "Month", "product_group"])
    .agg(Revenue=("revenue", "sum"), Orders=("Order ID", "nunique"), Units=("units", "sum"))
    .reset_index()
    .sort_values(["_month_key", "product_group"])
)
pivot = monthly.pivot_table(
    index=["_month_key", "Month"], columns="product_group",
    values=["Revenue", "Orders", "Units"], aggfunc="sum"
).round(2)
pivot.columns = [f"{m} — {p}" for m, p in pivot.columns]
pivot = pivot.reset_index().drop(columns="_month_key")
for col in pivot.columns:
    if col.startswith("Revenue"):
        pivot[col] = pivot[col].apply(lambda x: f"${x:,.2f}" if pd.notna(x) else "—")
st.dataframe(pivot, width="stretch", hide_index=True)

# Bar chart
chart_data = (
    paying.groupby(["_month_key", "product_group"])["revenue"]
    .sum().unstack(fill_value=0).sort_index()
)
if not chart_data.empty:
    st.bar_chart(chart_data, width="stretch")

# ── Units breakdown ────────────────────────────────────────────────────────────
st.markdown('<div class="section-label">06 — Units · Paying vs Free (Vine)</div>', unsafe_allow_html=True)

units_summary = (
    active_df.groupby(["Month", "_month_key", "product_group"])
    .apply(lambda g: pd.Series({
        "Paying Units":  int(g[~g["is_free"]]["units"].sum()),
        "Free Units":    int(g[g["is_free"]]["units"].sum()),
        "Total Shipped": int(g["units"].sum()),
    }), include_groups=False)
    .reset_index()
    .sort_values(["_month_key", "product_group"])
    .drop(columns="_month_key")
)
st.dataframe(units_summary, width="stretch", hide_index=True)

# ── Subscribe & Save attachment rate ─────────────────────────────────────────
st.markdown('<div class="section-label">06b — Subscribe & Save Rate · by Product by Month</div>', unsafe_allow_html=True)
st.caption("S&S orders as % of total paying orders (Vine excluded).")

if not paying.empty:
    sns_rate = (
        paying.groupby(["_month_key", "Month", "product_group"])
        .apply(lambda g: pd.Series({
            "Total Orders": int(g["Order ID"].nunique()),
            "S&S Orders":   int((g["category"] == "Subscribe & Save").sum()),
            "One-time":     int((g["category"] != "Subscribe & Save").sum()),
        }), include_groups=False)
        .reset_index()
        .sort_values(["_month_key", "product_group"])
        .drop(columns="_month_key")
    )
    sns_rate["S&S %"] = (
        sns_rate["S&S Orders"] / sns_rate["Total Orders"] * 100
    ).round(1).astype(str) + "%"
    st.dataframe(sns_rate, width="stretch", hide_index=True)

# ── Data preview ──────────────────────────────────────────────────────────────
st.markdown('<div class="section-label">07 — Full Data Preview</div>', unsafe_allow_html=True)
st.caption(f"{len(active_df)} orders · scroll to explore")
st.dataframe(active_df, width="stretch", hide_index=True, height=320)

# ── Push to Google Sheets ─────────────────────────────────────────────────────
st.markdown('<div class="section-label">08 — Push to Google Sheets</div>', unsafe_allow_html=True)

sheets_status = get_sheets_client_status()
if sheets_status == "ready":
    sheet_url = st.text_input(
        "Google Sheet URL",
        placeholder="https://docs.google.com/spreadsheets/d/…",
        key="amz_sheet_url",
    )
    if st.button("Push actuals → Performance Ov (Amazon revenue 67/68 · orders 84/85 · units 101/102)"):
        if sheet_url:
            with st.spinner("Writing to Performance Ov…"):
                result = push_amazon_to_performance_overview(active_df, sheet_url)
            if result["ok"]:
                st.success(f"✓ {result['cells']} cells updated in 'Performance Ov'")
            else:
                st.error(f"Error: {result['error']}")
        else:
            st.warning("Paste a Sheet URL first.")

    st.markdown("---")
    if st.button("🗑 Clear stored data (reset)", type="secondary"):
        if os.path.exists(STORE_FILE):
            os.remove(STORE_FILE)
            st.success("Stored data cleared. Refresh the page.")
else:
    st.info(f"Google Sheets: {sheets_status}. Add credentials.json to enable.")
