import streamlit as st
import pandas as pd
import os
from sheets import get_sheets_client_status
from brand import BRAND_CSS
import storage

_ROOT = os.path.dirname(os.path.abspath(__file__))
SHOPIFY_FILE = os.path.join(_ROOT, "shopify_data.csv")
AMAZON_FILE  = os.path.join(_ROOT, "amazon_data.csv")

st.set_page_config(
    page_title="SecondKind · Data Hub",
    page_icon="🧬",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown(BRAND_CSS, unsafe_allow_html=True)

# ── Header ────────────────────────────────────────────────────────────────────
st.markdown("""
<div class="sk-header">
  <div class="sk-logo">Second<span>Kind</span> · Data Hub</div>
  <div class="sk-subtitle">Internal Analytics · Sales &amp; Operations</div>
</div>
""", unsafe_allow_html=True)

# ── Status checks ─────────────────────────────────────────────────────────────
sheets_ok     = get_sheets_client_status() == "ready"
shopify_store = os.path.exists(SHOPIFY_FILE)
amazon_store  = os.path.exists(AMAZON_FILE)

sheets_pill  = '<span class="pill pill-ok">● Sheets connected</span>'  if sheets_ok    else '<span class="pill pill-off">○ Sheets offline</span>'
shopify_pill = '<span class="pill pill-ok">● Data stored</span>'       if shopify_store else '<span class="pill pill-off">○ No data yet</span>'
amazon_pill  = '<span class="pill pill-ok">● Data stored</span>'       if amazon_store  else '<span class="pill pill-off">○ No data yet</span>'

# ── Nav cards ─────────────────────────────────────────────────────────────────
st.markdown(f"""
<div class="nav-grid">
  <div class="nav-card">
    <div class="nav-card-title">Second<span>Kind</span> · Shopify</div>
    <div class="nav-card-desc">
      Upload Shopify Analytics CSV exports. Clean D2C sales data, track revenue by product,
      compare actuals vs model scenario mix and OT retention. Push to Google Sheets.
    </div>
    <div>{sheets_pill}{shopify_pill}</div>
  </div>
  <div class="nav-card">
    <div class="nav-card-title">Second<span>Kind</span> · Amazon</div>
    <div class="nav-card-desc">
      Upload Amazon Orders XLSX reports. Clean shipped orders, track revenue · units ·
      Subscribe &amp; Save rate by product and month. Push actuals to Google Sheets.
    </div>
    <div>{sheets_pill}{amazon_pill}</div>
  </div>
  <div class="nav-card">
    <div class="nav-card-title">Second<span>Kind</span> · freepl</div>
    <div class="nav-card-desc">
      Upload monthly Logystico 3PL invoice PDFs. Split costs into buckets — platform,
      storage, receiving, pick &amp; pack, packaging, B2B, shipping &amp; more. Read-only.
    </div>
    <div><span class="pill pill-off">○ Read-only · no push</span></div>
  </div>
</div>
""", unsafe_allow_html=True)

st.markdown("<br>", unsafe_allow_html=True)
st.caption("Use the sidebar ← to navigate between sections.")

# ── Combined dashboard ────────────────────────────────────────────────────────
st.markdown("<hr>", unsafe_allow_html=True)

if not shopify_store and not amazon_store:
    st.info("No data yet — upload files in the Shopify and Amazon sections to see combined totals here.")
else:
    # ── Load Shopify ──────────────────────────────────────────────────────────
    if shopify_store:
        sk = pd.read_csv(SHOPIFY_FILE)
        # All cleaned Shopify revenue — includes Shipping, excludes B2B/brochures (already removed by cleaner)
        # Note: the Performance Ov sheet push only counts Gut Balance + Mood Balance product revenue,
        # so the Home total will be slightly higher due to Shipping revenue.
        # Revenue includes refunds naturally (negative Total sales reduces sum)
        sk_rev = sk.groupby("Month")["Total sales"].sum().reset_index(name="sk_revenue")
        # Orders and units exclude refund rows (Total sales ≤ 0)
        sk_pos = sk[sk["Total sales"] > 0]
        sk_ord = sk_pos.groupby("Month")["Order name"].nunique().reset_index(name="sk_orders")
        sk_uni = sk_pos.groupby("Month")["Quantity ordered"].sum().reset_index(name="sk_units")
        sk_monthly = sk_rev.merge(sk_ord, on="Month", how="outer").merge(sk_uni, on="Month", how="outer").fillna(0)
    else:
        sk_monthly = pd.DataFrame(columns=["Month", "sk_revenue", "sk_orders", "sk_units"])

    # ── Load Amazon ───────────────────────────────────────────────────────────
    if amazon_store:
        amz = pd.read_csv(AMAZON_FILE)
        if "is_free" in amz.columns:
            amz["is_free"] = amz["is_free"].astype(bool)
            amz_paying = amz[~amz["is_free"]]
        else:
            amz_paying = amz
        # Use _month_key (YYYY-MM-01) to align with Shopify's Month column
        amz_rev = amz_paying.groupby("_month_key")["revenue"].sum().reset_index()
        amz_rev.columns = ["Month", "amz_revenue"]
        amz_ord = amz_paying.groupby("_month_key")["Order ID"].nunique().reset_index()
        amz_ord.columns = ["Month", "amz_orders"]
        amz_uni = amz_paying.groupby("_month_key")["units"].sum().reset_index()
        amz_uni.columns = ["Month", "amz_units"]
        amz_monthly = amz_rev.merge(amz_ord, on="Month", how="outer").merge(amz_uni, on="Month", how="outer").fillna(0)
    else:
        amz_monthly = pd.DataFrame(columns=["Month", "amz_revenue", "amz_orders", "amz_units"])

    # ── Merge & compute combined ──────────────────────────────────────────────
    combined = sk_monthly.merge(amz_monthly, on="Month", how="outer").fillna(0)
    combined["total_revenue"] = combined["sk_revenue"] + combined["amz_revenue"]
    combined["total_orders"]  = combined["sk_orders"]  + combined["amz_orders"]
    combined["total_units"]   = combined["sk_units"]   + combined["amz_units"]
    combined = combined.sort_values("Month").reset_index(drop=True)
    combined["Month_label"] = pd.to_datetime(combined["Month"]).dt.strftime("%b-%Y")

    # ── Overall KPI cards ─────────────────────────────────────────────────────
    st.markdown('<div class="section-label">Combined Totals — All Months</div>', unsafe_allow_html=True)

    tot_rev = combined["total_revenue"].sum()
    sk_rev_tot  = combined["sk_revenue"].sum()
    amz_rev_tot = combined["amz_revenue"].sum()
    tot_ord = int(combined["total_orders"].sum())
    tot_uni = int(combined["total_units"].sum())

    st.markdown(f"""
    <div class="stat-grid">
      <div class="stat-card">
        <div class="stat-label">Total Revenue</div>
        <div class="stat-value">${tot_rev:,.0f}</div>
        <div class="stat-sub">SK ${sk_rev_tot:,.0f} · AMZ ${amz_rev_tot:,.0f}</div>
      </div>
      <div class="stat-card">
        <div class="stat-label">Shopify Revenue</div>
        <div class="stat-value">${sk_rev_tot:,.0f}</div>
        <div class="stat-sub">{sk_rev_tot/tot_rev*100:.0f}% of total</div>
      </div>
      <div class="stat-card">
        <div class="stat-label">Amazon Revenue</div>
        <div class="stat-value">${amz_rev_tot:,.0f}</div>
        <div class="stat-sub">{amz_rev_tot/tot_rev*100:.0f}% of total</div>
      </div>
      <div class="stat-card">
        <div class="stat-label">Total Orders · Units</div>
        <div class="stat-value">{tot_ord:,}</div>
        <div class="stat-sub">{tot_uni:,} units shipped</div>
      </div>
    </div>
    """, unsafe_allow_html=True)

    # ── Monthly breakdown table ───────────────────────────────────────────────
    st.markdown('<div class="section-label">Monthly Breakdown — Shopify · Amazon · Combined</div>', unsafe_allow_html=True)

    display = combined[["Month_label",
                         "sk_revenue",  "amz_revenue",  "total_revenue",
                         "sk_orders",   "amz_orders",   "total_orders",
                         "sk_units",    "amz_units",    "total_units"]].copy()

    display.columns = [
        "Month",
        "Revenue SK", "Revenue AMZ", "Revenue Total",
        "Orders SK",  "Orders AMZ",  "Orders Total",
        "Units SK",   "Units AMZ",   "Units Total",
    ]

    for col in ["Revenue SK", "Revenue AMZ", "Revenue Total"]:
        display[col] = display[col].apply(lambda x: f"${x:,.0f}")
    for col in ["Orders SK", "Orders AMZ", "Orders Total", "Units SK", "Units AMZ", "Units Total"]:
        display[col] = display[col].apply(lambda x: f"{int(x):,}")

    st.dataframe(display, width="stretch", hide_index=True)

    # ── Revenue chart ─────────────────────────────────────────────────────────
    st.markdown('<div class="section-label">Revenue by Month</div>', unsafe_allow_html=True)
    chart = combined.set_index("Month_label")[["sk_revenue", "amz_revenue"]].rename(
        columns={"sk_revenue": "Shopify", "amz_revenue": "Amazon"}
    )
    st.bar_chart(chart, width="stretch")

# ── Revenue & Units Overview ──────────────────────────────────────────────────
st.markdown("<hr>", unsafe_allow_html=True)
st.markdown('<div class="section-label">Revenue &amp; Units Overview</div>', unsafe_allow_html=True)
st.caption(
    "Shopify consumer (Net Revenue) vs. consumer + B2B doctors orders (Master Carton or qty ≥ 7), "
    "free partner units, gross sales at list price ($44.99/unit), and Amazon paid units."
)

_FULL_PRICE = 44.99

_ov_cons = storage.download_df("shopify_data.csv")
_ov_b2b  = storage.download_df("shopify_b2b_data.csv")
_ov_fu   = storage.download_df("shopify_free_units.csv")
_ov_amz  = storage.download_df("amazon_data.csv")

if _ov_cons is not None and not _ov_cons.empty:
    _ov_cons["_mdt"]   = pd.to_datetime(_ov_cons["Month"])
    _ov_cons["_total"] = pd.to_numeric(_ov_cons["Total sales"],      errors="coerce").fillna(0)
    _ov_cons["_qty"]   = pd.to_numeric(_ov_cons["Quantity ordered"], errors="coerce").fillna(0)
    _prod_rows  = _ov_cons["Product title"] != "Shipping"
    _cons_net   = _ov_cons.groupby("_mdt")["_total"].sum()
    _cons_units = _ov_cons[_prod_rows].groupby("_mdt")["_qty"].sum()

    _b2b_rev = pd.Series(dtype=float)
    if _ov_b2b is not None and not _ov_b2b.empty:
        _b2b_g = _ov_b2b.copy()
        _b2b_g["_mdt"]   = pd.to_datetime(_b2b_g["Month"])
        _b2b_g["_total"] = pd.to_numeric(_b2b_g["Total sales"], errors="coerce").fillna(0)
        _b2b_rev = _b2b_g.groupby("_mdt")["_total"].sum()

    _fu_units = pd.Series(dtype=float)
    if _ov_fu is not None and not _ov_fu.empty:
        _fu_g = _ov_fu.copy()
        _fu_g["_mdt"] = pd.to_datetime(_fu_g["Month"])
        _fu_g["_qty"] = pd.to_numeric(_fu_g["Quantity ordered"], errors="coerce").fillna(0)
        _fu_units = _fu_g.groupby("_mdt")["_qty"].sum()

    _amz_units = pd.Series(dtype=float)
    if _ov_amz is not None and not _ov_amz.empty:
        _amz_g = _ov_amz[_ov_amz["is_free"] == False].copy()
        _amz_g["_mdt"] = pd.to_datetime(_amz_g["_month_key"])
        _amz_units = _amz_g.groupby("_mdt")["units"].sum()

    _ov_rows = []
    _tot_net = _tot_b2b_net = _tot_fu = _tot_cu = _tot_gross_c = _tot_b2b_gs = _tot_amz_u = _tot_ec = 0.0
    for _m in sorted(_ov_cons["_mdt"].unique()):
        _net     = _cons_net.get(_m, 0.0)
        _b2b_r   = _b2b_rev.get(_m, 0.0)
        _fu_u    = int(_fu_units.get(_m, 0))
        _cu      = int(_cons_units.get(_m, 0))
        _gross_c = _cu * _FULL_PRICE
        _amz_u   = int(_amz_units.get(_m, 0))
        _ec      = _gross_c + _b2b_r + _amz_u * _FULL_PRICE
        _ov_rows.append({
            "Month":                      pd.Timestamp(_m).strftime("%B %Y"),
            "Net Revenue":                f"${_net:,.0f}",
            "eCom + B2B Net Revenue":     f"${_net + _b2b_r:,.0f}",
            "Free Units":                 _fu_u or "—",
            "Total Units Consumer":       _cu,
            "Gross Sales Consumers":      f"${_gross_c:,.0f}",
            "eCom + B2B Gross Sales":     f"${_gross_c + _b2b_r:,.0f}",
            "Amazon Units":               _amz_u or "—",
            "Total Gross Sales eCom+AMZ": f"${_ec:,.0f}",
        })
        _tot_net    += _net;  _tot_b2b_net += _net + _b2b_r
        _tot_fu     += _fu_u; _tot_cu      += _cu
        _tot_gross_c += _gross_c; _tot_b2b_gs += _gross_c + _b2b_r
        _tot_amz_u  += _amz_u;   _tot_ec     += _ec

    _ov_rows.append({
        "Month":                      "TOTAL",
        "Net Revenue":                f"${_tot_net:,.0f}",
        "eCom + B2B Net Revenue":     f"${_tot_b2b_net:,.0f}",
        "Free Units":                 int(_tot_fu) or "—",
        "Total Units Consumer":       int(_tot_cu),
        "Gross Sales Consumers":      f"${_tot_gross_c:,.0f}",
        "eCom + B2B Gross Sales":     f"${_tot_b2b_gs:,.0f}",
        "Amazon Units":               int(_tot_amz_u) or "—",
        "Total Gross Sales eCom+AMZ": f"${_tot_ec:,.0f}",
    })
    st.dataframe(pd.DataFrame(_ov_rows), use_container_width=True, hide_index=True)
    if _ov_b2b is None or _ov_b2b.empty:
        st.caption(
            "⚠ B2B/doctor order data not yet stored — upload a new Shopify CSV to populate it. "
            "Until then, eCom + B2B columns equal the consumer-only figures."
        )
else:
    st.info("No Shopify data stored yet — upload a CSV in the Shopify section.")

# ── System status ─────────────────────────────────────────────────────────────
st.markdown("<hr>", unsafe_allow_html=True)
st.markdown('<div class="section-label">System Status</div>', unsafe_allow_html=True)

col1, col2, col3 = st.columns(3)
with col1:
    if sheets_ok:
        st.success("Google Sheets — connected")
    else:
        st.warning("Google Sheets — no credentials.json")
with col2:
    if shopify_store:
        df = pd.read_csv(SHOPIFY_FILE)
        months = pd.to_datetime(df["Month"]).dt.strftime("%b-%Y").unique() if "Month" in df.columns else []
        st.info(f"Shopify — {len(df)} rows · {len(months)} months stored")
    else:
        st.info("Shopify — no data stored yet")
with col3:
    if amazon_store:
        df = pd.read_csv(AMAZON_FILE)
        months = df["Month"].unique() if "Month" in df.columns else []
        st.info(f"Amazon — {len(df)} orders · {len(months)} months stored")
    else:
        st.info("Amazon — no data stored yet")
