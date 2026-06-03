"""
brand.py — Shared SecondKind brand CSS injected into every page.

Palette extracted from secondkind.com:
  Cream background   #F8F4EE
  White surface      #FFFFFF
  Dark text          #1A1A17
  Secondary text     #6B6560
  Muted text         #9C9590
  Brand green        #52A96A   (CTA button approx.)
  Green hover        #449059
  Green tint         #EBF6EF
  Warm border        #E4DDD3
"""

BRAND_CSS = """
<style>
  @import url('https://fonts.googleapis.com/css2?family=Cormorant+Garamond:wght@400;500;600&family=DM+Sans:wght@300;400;500;600;700&family=DM+Mono:wght@400;500&display=swap');

  /* ── Reset & base ──────────────────────────────────────────── */
  html, body, [class*="css"] {
    font-family: 'DM Sans', sans-serif;
    color: #1A1A17;
  }
  .stApp {
    background-color: #F8F4EE;
  }

  /* ── Sidebar ───────────────────────────────────────────────── */
  [data-testid="stSidebar"] {
    background-color: #FFFFFF;
    border-right: 1px solid #E4DDD3;
  }
  [data-testid="stSidebar"] * {
    color: #1A1A17 !important;
  }

  /* ── Header ─────────────────────────────────────────────────── */
  .sk-header {
    padding: 2rem 0 1.75rem 0;
    border-bottom: 1px solid #E4DDD3;
    margin-bottom: 2rem;
  }
  .sk-logo {
    font-family: 'Cormorant Garamond', serif;
    font-size: 2rem;
    font-weight: 600;
    letter-spacing: 0.01em;
    color: #1A1A17;
  }
  .sk-logo span { color: #52A96A; }
  .sk-subtitle {
    font-family: 'DM Mono', monospace;
    font-size: 0.7rem;
    color: #9C9590;
    letter-spacing: 0.1em;
    text-transform: uppercase;
    margin-top: 4px;
  }

  /* ── Section labels ──────────────────────────────────────────── */
  .section-label {
    font-family: 'DM Mono', monospace;
    font-size: 0.68rem;
    color: #9C9590;
    text-transform: uppercase;
    letter-spacing: 0.14em;
    margin-bottom: 0.75rem;
    margin-top: 2rem;
  }

  /* ── Stat cards ──────────────────────────────────────────────── */
  .stat-grid {
    display: grid;
    grid-template-columns: repeat(4, 1fr);
    gap: 12px;
    margin: 1.5rem 0;
  }
  .stat-card {
    background: #FFFFFF;
    border: 1px solid #E4DDD3;
    border-radius: 10px;
    padding: 1.25rem 1.5rem;
  }
  .stat-label {
    font-family: 'DM Mono', monospace;
    font-size: 0.68rem;
    color: #9C9590;
    text-transform: uppercase;
    letter-spacing: 0.1em;
    margin-bottom: 8px;
  }
  .stat-value {
    font-size: 1.9rem;
    font-weight: 700;
    color: #1A1A17;
    line-height: 1;
    font-family: 'DM Sans', sans-serif;
  }
  .stat-sub {
    font-family: 'DM Mono', monospace;
    font-size: 0.72rem;
    margin-top: 6px;
    color: #9C9590;
  }
  .stat-delta      { font-family: 'DM Mono', monospace; font-size: 0.72rem; margin-top: 6px; }
  .delta-neg       { color: #C0392B; }
  .delta-pos       { color: #52A96A; }

  /* ── Step pills ──────────────────────────────────────────────── */
  .step-row { display: flex; flex-wrap: wrap; gap: 8px; margin: 1rem 0 1.5rem 0; }
  .step-pill {
    font-family: 'DM Mono', monospace;
    font-size: 0.68rem;
    background: #FFFFFF;
    border: 1px solid #E4DDD3;
    border-radius: 20px;
    padding: 4px 12px;
    color: #9C9590;
  }
  .step-pill.active {
    background: #EBF6EF;
    border-color: #52A96A;
    color: #2E7D4F;
  }

  /* ── Nav cards (landing page) ────────────────────────────────── */
  .nav-grid { display: grid; grid-template-columns: repeat(2,1fr); gap: 16px; margin-top: 1.5rem; }
  .nav-card {
    background: #FFFFFF;
    border: 1px solid #E4DDD3;
    border-radius: 12px;
    padding: 2rem;
    transition: border-color 0.15s, box-shadow 0.15s;
  }
  .nav-card:hover { border-color: #52A96A; box-shadow: 0 2px 16px rgba(82,169,106,0.08); }
  .nav-card-title {
    font-family: 'Cormorant Garamond', serif;
    font-size: 1.4rem;
    font-weight: 600;
    color: #1A1A17;
    margin-bottom: 10px;
  }
  .nav-card-title span { color: #52A96A; }
  .nav-card-desc {
    font-family: 'DM Sans', sans-serif;
    font-size: 0.82rem;
    color: #6B6560;
    line-height: 1.65;
    margin-bottom: 1.25rem;
  }
  .pill {
    display: inline-block;
    font-family: 'DM Mono', monospace;
    font-size: 0.65rem;
    border-radius: 20px;
    padding: 3px 10px;
    margin-right: 6px;
  }
  .pill-ok  { background: #EBF6EF; border: 1px solid #52A96A; color: #2E7D4F; }
  .pill-off { background: #F5F1EB; border: 1px solid #E4DDD3; color: #9C9590; }

  /* ── Buttons ─────────────────────────────────────────────────── */
  .stButton > button {
    background: #52A96A;
    color: #FFFFFF;
    font-family: 'DM Sans', sans-serif;
    font-weight: 600;
    border: none;
    border-radius: 8px;
    padding: 0.6rem 1.5rem;
    font-size: 0.85rem;
    letter-spacing: 0.01em;
    transition: background 0.15s;
  }
  .stButton > button:hover { background: #449059; color: #FFFFFF; }

  /* ── Tables / dataframes ─────────────────────────────────────── */
  .dataframe {
    font-family: 'DM Mono', monospace !important;
    font-size: 0.78rem !important;
  }
  [data-testid="stDataFrame"] {
    border: 1px solid #E4DDD3 !important;
    border-radius: 8px;
  }

  /* ── File uploader ───────────────────────────────────────────── */
  [data-testid="stFileUploader"] {
    background: #FFFFFF;
    border: 1px dashed #C8C0B5;
    border-radius: 10px;
    padding: 1rem;
  }

  /* ── Text inputs ─────────────────────────────────────────────── */
  [data-testid="stTextInput"] input {
    background: #FFFFFF;
    border: 1px solid #E4DDD3;
    border-radius: 8px;
    color: #1A1A17;
    font-family: 'DM Mono', monospace;
    font-size: 0.82rem;
  }

  /* ── Info / success / warning banners ───────────────────────── */
  [data-testid="stAlert"] { border-radius: 8px; }

  /* ── Divider ─────────────────────────────────────────────────── */
  hr { border-color: #E4DDD3 !important; }

  /* ── Captions ────────────────────────────────────────────────── */
  .stCaption, [data-testid="stCaptionContainer"] p {
    font-family: 'DM Mono', monospace !important;
    font-size: 0.72rem !important;
    color: #9C9590 !important;
  }
</style>
"""
