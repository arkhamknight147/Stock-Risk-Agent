# =============================================================================
# app.py
# Streamlit Visual Entry Point — Investors Way AI Stock Risk Analyzer
# =============================================================================
#
# HOW TO RUN:
#   streamlit run app.py
#
# WHAT THIS FILE DOES:
# ---------------------
# This is the browser-based front-end for the multi-agent pipeline.
# It replaces main.py as the primary user interface.
#
# USER JOURNEY:
#   1. User opens the Streamlit app in their browser
#   2. Types an Indian company name into the search bar
#   3. Clicks "Analyze Stock Risk"
#   4. Watches real-time status updates as each agent runs
#   5. The full 2-page HTML report renders directly on the page
#   6. User can also download the HTML file
#
# ARCHITECTURE NOTES:
# --------------------
# - st.session_state is used to persist the pipeline result across
#   Streamlit reruns (which happen on every UI interaction).
# - The HTML report is rendered via streamlit.components.v1.html()
#   inside an iframe-equivalent — this preserves all custom fonts,
#   SVG gauges, and gold-theme styling from the designer agent.
# - All agent stdout is suppressed from the browser (it goes to the
#   terminal where `streamlit run` was invoked) — the UI shows its
#   own clean status messages via st.status / st.write.
#
# =============================================================================

from __future__ import annotations

import sys
import time
import traceback
from datetime import datetime
from pathlib import Path

import streamlit as st
import streamlit.components.v1 as components

# ---------------------------------------------------------------------------
# PATH SETUP — ensure state.py and agents/ are importable from project root
# ---------------------------------------------------------------------------
_ROOT = Path(__file__).resolve().parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

# Ensure agents/__init__.py exists (first-run safety)
_agents_init = _ROOT / "agents" / "__init__.py"
if not _agents_init.exists():
    try:
        _agents_init.write_text("# agents package\n", encoding="utf-8")
    except OSError:
        pass

# ---------------------------------------------------------------------------
# PROJECT IMPORTS — wrapped in try/except for graceful missing-lib errors
# ---------------------------------------------------------------------------
_import_errors: list[str] = []

try:
    from state import AppState
except ImportError as e:
    _import_errors.append(f"state.py: {e}")
    AppState = None  # type: ignore

try:
    from agents import router, extractor, analyst, designer
except ImportError as e:
    _import_errors.append(f"agents/: {e}")
    router = extractor = analyst = designer = None  # type: ignore


# =============================================================================
# SECTION 1: PAGE CONFIGURATION
# Must be the FIRST Streamlit call in the script — before any st.* usage.
# =============================================================================

st.set_page_config(
    page_title="Investors Way — AI Stock Risk Analyzer",
    page_icon="₹",
    layout="wide",
    initial_sidebar_state="collapsed",
    menu_items={
        "Get Help": None,
        "Report a bug": None,
        "About": (
            "**Investors Way — AI Stock Risk Analyzer**\n\n"
            "A multi-agent equity research pipeline for Indian stocks (NSE/BSE).\n"
            "Generates institutional-grade risk scorecards automatically."
        ),
    },
)


# =============================================================================
# SECTION 2: GLOBAL CUSTOM CSS
# Injects a light, professional theme that complements the HTML report's
# own design language (gold accents, DM Sans body, clean whites).
# =============================================================================

CUSTOM_CSS = """
<style>
  /* ── Google Fonts ── */
  @import url('https://fonts.googleapis.com/css2?family=DM+Serif+Display:ital@0;1&family=DM+Sans:ital,opsz,wght@0,9..40,300;0,9..40,400;0,9..40,500;0,9..40,600;0,9..40,700&family=IBM+Plex+Mono:wght@400;500;600;700&display=swap');

  /* ── Root tokens ── */
  :root {
    --gold:         #b8922e;
    --gold-light:   #d4a843;
    --gold-faint:   #fdf6e9;
    --dark:         #111118;
    --card-bg:      #f7f7f8;
    --border:       #e4e4e7;
    --text:         #111118;
    --text-muted:   #71717a;
    --green:        #15803d;
    --red:          #b91c1c;
    --amber:        #b45309;
  }

  /* ── App-wide font override ── */
  html, body, [class*="css"] {
    font-family: 'DM Sans', sans-serif !important;
    background-color: #f4f4f5 !important;
  }

  /* ── Hide Streamlit chrome decorations ── */
  #MainMenu { visibility: hidden; }
  footer    { visibility: hidden; }
  header    { visibility: hidden; }

  /* ── Main content area ── */
  .main .block-container {
    padding-top: 2rem;
    padding-bottom: 3rem;
    max-width: 1200px;
  }

  /* ── Header card ── */
  .app-header {
    background: linear-gradient(135deg, #111118 0%, #1e1e2e 100%);
    border-radius: 16px;
    padding: 40px 48px 36px;
    margin-bottom: 28px;
    border-bottom: 3px solid var(--gold);
    position: relative;
    overflow: hidden;
  }
  .app-header::before {
    content: '';
    position: absolute;
    top: -60px; right: -60px;
    width: 220px; height: 220px;
    border-radius: 50%;
    background: radial-gradient(circle, rgba(184,146,46,0.12) 0%, transparent 70%);
    pointer-events: none;
  }
  .app-header-eyebrow {
    font-family: 'IBM Plex Mono', monospace;
    font-size: 0.7rem;
    font-weight: 600;
    letter-spacing: 0.18em;
    color: var(--gold);
    text-transform: uppercase;
    margin-bottom: 10px;
  }
  .app-header-title {
    font-family: 'DM Serif Display', serif;
    font-size: 2.6rem;
    font-weight: 400;
    color: #ffffff;
    margin: 0 0 10px;
    line-height: 1.1;
    letter-spacing: -0.02em;
  }
  .app-header-subtitle {
    font-family: 'DM Sans', sans-serif;
    font-size: 0.95rem;
    color: #a1a1aa;
    max-width: 620px;
    line-height: 1.6;
    margin: 0;
  }
  .app-header-badge {
    display: inline-block;
    background: rgba(184,146,46,0.15);
    border: 1px solid rgba(184,146,46,0.35);
    border-radius: 20px;
    padding: 4px 14px;
    font-family: 'IBM Plex Mono', monospace;
    font-size: 0.68rem;
    color: var(--gold);
    margin-top: 14px;
    letter-spacing: 0.06em;
  }

  /* ── Search card ── */
  .search-card {
    background: #ffffff;
    border: 1px solid var(--border);
    border-radius: 14px;
    padding: 28px 32px 24px;
    margin-bottom: 24px;
    box-shadow: 0 1px 4px rgba(0,0,0,0.06);
  }
  .search-label {
    font-family: 'DM Sans', sans-serif;
    font-size: 0.82rem;
    font-weight: 600;
    color: var(--text-muted);
    text-transform: uppercase;
    letter-spacing: 0.08em;
    margin-bottom: 10px;
  }

  /* ── Streamlit text_input override ── */
  div[data-testid="stTextInput"] input {
    font-family: 'DM Sans', sans-serif !important;
    font-size: 1rem !important;
    border: 1.5px solid var(--border) !important;
    border-radius: 10px !important;
    padding: 12px 16px !important;
    background: #fafafa !important;
    color: var(--text) !important;
    transition: border-color 0.2s !important;
  }
  div[data-testid="stTextInput"] input:focus {
    border-color: var(--gold) !important;
    box-shadow: 0 0 0 3px rgba(184,146,46,0.12) !important;
    outline: none !important;
  }

  /* ── Primary action button ── */
  div[data-testid="stButton"] > button[kind="primary"] {
    background: linear-gradient(135deg, var(--gold) 0%, var(--gold-light) 100%) !important;
    color: #111118 !important;
    font-family: 'DM Sans', sans-serif !important;
    font-weight: 700 !important;
    font-size: 0.95rem !important;
    border: none !important;
    border-radius: 10px !important;
    padding: 12px 32px !important;
    letter-spacing: 0.02em !important;
    transition: transform 0.15s, box-shadow 0.15s !important;
    width: 100% !important;
  }
  div[data-testid="stButton"] > button[kind="primary"]:hover {
    transform: translateY(-1px) !important;
    box-shadow: 0 6px 20px rgba(184,146,46,0.35) !important;
  }
  div[data-testid="stButton"] > button[kind="primary"]:active {
    transform: translateY(0) !important;
  }

  /* ── Agent progress steps ── */
  .agent-step {
    display: flex;
    align-items: flex-start;
    gap: 14px;
    padding: 14px 18px;
    border-radius: 10px;
    margin-bottom: 10px;
    border: 1px solid var(--border);
    background: #fafafa;
  }
  .agent-step.running {
    background: #fdf6e9;
    border-color: rgba(184,146,46,0.4);
  }
  .agent-step.done {
    background: #f0fdf4;
    border-color: #bbf7d0;
  }
  .agent-step.failed {
    background: #fef2f2;
    border-color: #fecaca;
  }
  .agent-step.pending {
    background: #fafafa;
    border-color: var(--border);
    opacity: 0.5;
  }
  .step-icon {
    font-size: 1.3rem;
    flex-shrink: 0;
    margin-top: 1px;
  }
  .step-title {
    font-family: 'DM Sans', sans-serif;
    font-weight: 700;
    font-size: 0.9rem;
    color: var(--text);
    margin-bottom: 2px;
  }
  .step-desc {
    font-family: 'DM Sans', sans-serif;
    font-size: 0.78rem;
    color: var(--text-muted);
    line-height: 1.5;
  }
  .step-detail {
    font-family: 'IBM Plex Mono', monospace;
    font-size: 0.7rem;
    color: var(--gold);
    margin-top: 4px;
  }

  /* ── Results summary bar ── */
  .result-bar {
    display: flex;
    align-items: center;
    gap: 14px;
    background: var(--dark);
    border-radius: 12px;
    padding: 18px 24px;
    margin: 20px 0 16px;
    flex-wrap: wrap;
  }
  .result-metric {
    text-align: center;
    flex: 1;
    min-width: 100px;
  }
  .result-metric-label {
    font-family: 'IBM Plex Mono', monospace;
    font-size: 0.62rem;
    letter-spacing: 0.12em;
    text-transform: uppercase;
    color: #71717a;
    margin-bottom: 4px;
  }
  .result-metric-value {
    font-family: 'IBM Plex Mono', monospace;
    font-size: 1.2rem;
    font-weight: 700;
    color: var(--gold);
  }
  .result-divider {
    width: 1px;
    height: 36px;
    background: #2d2d3a;
    flex-shrink: 0;
  }

  /* ── Error box ── */
  .error-box {
    background: #fef2f2;
    border: 1px solid #fecaca;
    border-left: 4px solid var(--red);
    border-radius: 10px;
    padding: 18px 22px;
    margin: 16px 0;
  }
  .error-title {
    font-family: 'DM Sans', sans-serif;
    font-weight: 700;
    font-size: 0.9rem;
    color: var(--red);
    margin-bottom: 6px;
  }
  .error-body {
    font-family: 'DM Sans', sans-serif;
    font-size: 0.82rem;
    color: #7f1d1d;
    line-height: 1.6;
  }

  /* ── Warning box ── */
  .warn-box {
    background: #fffbeb;
    border: 1px solid #fde68a;
    border-left: 4px solid var(--amber);
    border-radius: 10px;
    padding: 14px 18px;
    margin: 10px 0;
    font-family: 'DM Sans', sans-serif;
    font-size: 0.8rem;
    color: #78350f;
    line-height: 1.6;
  }

  /* ── Report section header ── */
  .report-section-header {
    display: flex;
    align-items: center;
    gap: 10px;
    margin: 28px 0 14px;
  }
  .report-section-accent {
    width: 3px;
    height: 22px;
    background: var(--gold);
    border-radius: 2px;
    flex-shrink: 0;
  }
  .report-section-title {
    font-family: 'DM Serif Display', serif;
    font-size: 1.35rem;
    font-weight: 400;
    color: var(--text);
  }

  /* ── Spinner override ── */
  div[data-testid="stSpinner"] > div {
    border-top-color: var(--gold) !important;
  }

  /* ── Download button ── */
  div[data-testid="stDownloadButton"] > button {
    font-family: 'DM Sans', sans-serif !important;
    font-weight: 600 !important;
    border-radius: 8px !important;
    border-color: var(--border) !important;
    color: var(--text) !important;
  }

  /* ── Sidebar (collapsed by default, styled if opened) ── */
  section[data-testid="stSidebar"] {
    background: var(--dark) !important;
  }

  /* ── Scrollbar ── */
  ::-webkit-scrollbar { width: 6px; height: 6px; }
  ::-webkit-scrollbar-track { background: #f4f4f5; }
  ::-webkit-scrollbar-thumb { background: var(--border); border-radius: 3px; }
</style>
"""

st.markdown(CUSTOM_CSS, unsafe_allow_html=True)


# =============================================================================
# SECTION 3: SESSION STATE INITIALISATION
# Streamlit re-runs the entire script on every interaction.
# st.session_state persists values across those reruns.
# =============================================================================

def _init_session_state() -> None:
    """Initialises all session-state keys on first load."""
    defaults = {
        "pipeline_result":   None,   # AppState after successful pipeline run
        "pipeline_error":    None,   # str error message if pipeline failed
        "pipeline_running":  False,  # True while agents are executing
        "last_company":      "",     # last successfully analysed company name
        "agent_statuses":    {},     # dict: agent_key → "pending"|"running"|"done"|"failed"
        "agent_details":     {},     # dict: agent_key → detail string shown under step
    }
    for key, default in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = default


_init_session_state()


# =============================================================================
# SECTION 4: HEADER COMPONENT
# =============================================================================

def _render_header() -> None:
    """Renders the dark branding header with title and subtitle."""
    st.markdown(
        """
        <div class="app-header">
          <div class="app-header-eyebrow">₹ &nbsp;NSE · BSE &nbsp;·&nbsp; Multi-Agent AI Research</div>
          <div class="app-header-title">Investors Way<br>AI Stock Risk Analyzer</div>
          <p class="app-header-subtitle">
            Enter any Indian listed company name and our AI pipeline will automatically
            fetch live market data, run a 7-factor risk analysis, and generate an
            institutional-grade equity research scorecard — in under 60 seconds.
          </p>
          <div class="app-header-badge">
            🤖 &nbsp; 4 Agents &nbsp;·&nbsp; 7 Risk Factors &nbsp;·&nbsp;
            Real-Time NSE/BSE Data &nbsp;·&nbsp; 60-Day News Sentiment
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


# =============================================================================
# SECTION 5: SEARCH BAR COMPONENT
# =============================================================================

def _render_search_bar() -> tuple[str, bool]:
    """
    Renders the company name input and action button.

    Returns:
        (company_name: str, button_clicked: bool)
    """
    st.markdown('<div class="search-card">', unsafe_allow_html=True)
    st.markdown(
        '<div class="search-label">🔍 &nbsp; Company Search</div>',
        unsafe_allow_html=True,
    )

    col_input, col_btn = st.columns([4, 1], gap="medium")

    with col_input:
        company_name = st.text_input(
            label="Company Name",
            placeholder="e.g., Happiest Minds, Tata Motors, HDFC Bank, Infosys, Sun Pharma…",
            label_visibility="collapsed",
            key="company_input",
        )

    with col_btn:
        # Vertical spacer to align button with input
        st.markdown("<div style='height:4px'></div>", unsafe_allow_html=True)
        clicked = st.button(
            "⚡  Analyze Stock Risk",
            type="primary",
            use_container_width=True,
            key="analyze_btn",
        )

    st.markdown(
        "<div style='margin-top:10px;font-family:\"DM Sans\",sans-serif;"
        "font-size:0.76rem;color:#a1a1aa;'>"
        "Supports NSE and BSE listed companies. "
        "Try: <b>Reliance, ITC, L&amp;T, Bajaj Finance, Asian Paints, Wipro, ONGC, SBI</b>"
        "</div>",
        unsafe_allow_html=True,
    )

    st.markdown("</div>", unsafe_allow_html=True)  # close search-card

    return company_name.strip(), clicked


# =============================================================================
# SECTION 6: AGENT PROGRESS TRACKER
# Renders a visual card for each pipeline step showing live status.
# =============================================================================

# Agent metadata: (key, display_number, display_name, description, icon_pending, icon_running, icon_done)
AGENT_STEPS = [
    (
        "router",
        1,
        "Router Agent",
        "Resolving NSE/BSE ticker symbol, auto-detecting sector, mapping 2 sector-specific KPIs",
        "🔍",
    ),
    (
        "extractor",
        2,
        "Extractor Agent",
        "Fetching live CMP, P/E, P/B, ROE, 4 quarters of financials, promoter pledge %, 60-day news",
        "📡",
    ),
    (
        "analyst",
        3,
        "Analyst Agent",
        "Scoring 7 risk factors, computing weighted composite score, generating hidden insights, catalysts & risks",
        "🧠",
    ),
    (
        "designer",
        4,
        "Designer Agent",
        "Rendering 2-page HTML report with SVG risk gauge, quarterly charts, and verdict panel",
        "🎨",
    ),
]

STATUS_ICON = {
    "pending": "⬜",
    "running": "🔄",
    "done":    "✅",
    "failed":  "❌",
}


def _render_agent_progress(statuses: dict, details: dict) -> None:
    """Renders the 4-step progress tracker cards."""
    st.markdown(
        "<div style='margin:4px 0 18px;font-family:\"DM Sans\",sans-serif;"
        "font-size:0.78rem;font-weight:600;color:#52525b;text-transform:uppercase;"
        "letter-spacing:0.08em;'>Pipeline Progress</div>",
        unsafe_allow_html=True,
    )

    for agent_key, step_num, name, description, icon in AGENT_STEPS:
        status  = statuses.get(agent_key, "pending")
        detail  = details.get(agent_key, "")
        s_icon  = STATUS_ICON.get(status, "⬜")
        css_cls = f"agent-step {status}"

        detail_html = (
            f'<div class="step-detail">{detail}</div>' if detail else ""
        )

        st.markdown(
            f"""
            <div class="{css_cls}">
              <div class="step-icon">{s_icon}</div>
              <div>
                <div class="step-title">
                  Step {step_num} &nbsp;·&nbsp; {name}
                </div>
                <div class="step-desc">{description}</div>
                {detail_html}
              </div>
            </div>
            """,
            unsafe_allow_html=True,
        )


# =============================================================================
# SECTION 7: RESULT SUMMARY BAR
# =============================================================================

def _render_result_bar(state: "AppState") -> None:
    """Renders the dark summary strip after a successful pipeline run."""
    extra   = state.raw_financial_data.extra_data or {}
    score   = extra.get("composite_score_100", None)
    verdict = extra.get("verdict", "N/A")
    band    = getattr(state.analytical_insights, "risk_band", None) or "N/A"
    ticker  = (state.ticker or "").replace(".NS", "").replace(".BO", "")
    sector  = state.sector or "N/A"

    score_str = f"{score:.1f}" if score is not None else "N/A"

    verdict_colors = {
        "Strong Buy": "#15803d",
        "Buy":        "#16a34a",
        "Hold":       "#d97706",
        "Sell":       "#dc2626",
        "Strong Sell":"#991b1b",
    }
    v_color = verdict_colors.get(verdict, "#b8922e")

    band_icons = {"LOW RISK": "🟢", "MODERATE RISK": "🟡", "HIGH RISK": "🔴"}
    b_icon = band_icons.get(band, "⚪")

    st.markdown(
        f"""
        <div class="result-bar">
          <div class="result-metric">
            <div class="result-metric-label">Company</div>
            <div class="result-metric-value" style="font-size:0.95rem;color:#e4e4e7;">
              {state.company_name}
            </div>
          </div>
          <div class="result-divider"></div>
          <div class="result-metric">
            <div class="result-metric-label">Ticker</div>
            <div class="result-metric-value">{ticker}</div>
          </div>
          <div class="result-divider"></div>
          <div class="result-metric">
            <div class="result-metric-label">Sector</div>
            <div class="result-metric-value" style="font-size:0.82rem;color:#a1a1aa;">
              {sector}
            </div>
          </div>
          <div class="result-divider"></div>
          <div class="result-metric">
            <div class="result-metric-label">Risk Score</div>
            <div class="result-metric-value">{score_str} / 100</div>
          </div>
          <div class="result-divider"></div>
          <div class="result-metric">
            <div class="result-metric-label">Risk Band</div>
            <div class="result-metric-value" style="font-size:0.85rem;">
              {b_icon} {band}
            </div>
          </div>
          <div class="result-divider"></div>
          <div class="result-metric">
            <div class="result-metric-label">Verdict</div>
            <div class="result-metric-value" style="color:{v_color};">
              {verdict.upper()}
            </div>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


# =============================================================================
# SECTION 8: PIPELINE RUNNER
# Executes all four agents sequentially with live UI updates.
# =============================================================================

def _run_pipeline(company_name: str) -> "AppState | None":
    """
    Runs the full 4-agent pipeline with live progress updates in the UI.

    STRATEGY:
    - We use a placeholder container for the progress cards so they can be
      updated in-place (rather than appended each time).
    - Each agent is wrapped in try/except. Critical failures abort the pipeline.
      Non-critical errors (e.g., news scraper blocked) generate a warning
      but allow continuation.
    - st.session_state tracks statuses so they survive reruns.

    Returns:
        AppState on full or partial success, None on critical failure.
    """

    # ── Reset status tracking ─────────────────────────────────────────────
    statuses: dict = {k: "pending" for k, *_ in AGENT_STEPS}
    details:  dict = {}
    st.session_state["agent_statuses"] = statuses
    st.session_state["agent_details"]  = details

    # ── Placeholder for live progress cards ──────────────────────────────
    progress_placeholder = st.empty()

    def _refresh_progress():
        with progress_placeholder.container():
            _render_agent_progress(
                st.session_state["agent_statuses"],
                st.session_state["agent_details"],
            )

    _refresh_progress()

    # ── Initialise AppState ───────────────────────────────────────────────
    try:
        state = AppState(company_name=company_name)
    except Exception as exc:
        st.session_state["pipeline_error"] = f"Failed to initialise state: {exc}"
        return None

    # ── AGENT 1: ROUTER ───────────────────────────────────────────────────
    statuses["router"] = "running"
    _refresh_progress()

    try:
        state = router.run(state)
    except Exception as exc:
        state.log_error("router", str(exc))

    if state.is_agent_complete("router"):
        ticker = (state.ticker or "N/A")
        sector = state.sector or "N/A"
        kpis   = [k.name for k in (state.sector_kpis or [])]
        statuses["router"] = "done"
        details["router"]  = (
            f"✓ {ticker} · {sector} · KPIs: {', '.join(kpis) if kpis else 'N/A'}"
        )
    else:
        statuses["router"] = "failed"
        err = state.errors.get("router", "Unknown error")
        details["router"]  = f"✖ {err[:120]}"
        _refresh_progress()

        # CRITICAL FAILURE — cannot proceed without a ticker
        st.session_state["pipeline_error"] = (
            f"**Could not resolve a stock ticker for '{company_name}'.**\n\n"
            f"**Reason:** {err}\n\n"
            "**Try these fixes:**\n"
            "- Use the official company name (e.g. *'HDFC Bank'* not *'hdfc'*)\n"
            "- Try the NSE ticker directly (e.g. *'HDFCBANK'*, *'RELIANCE'*, *'INFY'*)\n"
            "- Check spelling — even small differences matter\n"
            "- Ensure the company is listed on NSE or BSE"
        )
        return None

    st.session_state["agent_statuses"] = statuses
    st.session_state["agent_details"]  = details
    _refresh_progress()

    # ── AGENT 2: EXTRACTOR ────────────────────────────────────────────────
    statuses["extractor"] = "running"
    _refresh_progress()

    try:
        state = extractor.run(state)
    except Exception as exc:
        state.log_error("extractor", str(exc))

    if state.is_agent_complete("extractor"):
        rfd      = state.raw_financial_data
        cmp      = rfd.cmp
        q_count  = len(rfd.quarterly_financials or [])
        n_news   = len(rfd.news_headlines or [])
        cmp_str  = f"₹{cmp:,.2f}" if cmp else "CMP N/A"
        statuses["extractor"] = "done"
        details["extractor"]  = (
            f"✓ {cmp_str} · {q_count}/4 quarters · {n_news} news articles"
        )

        # Non-critical warnings — don't block pipeline but inform user
        warnings = []
        if q_count < 4:
            warnings.append(f"Only {q_count}/4 quarters of financial data available.")
        if n_news == 0:
            warnings.append("No news headlines fetched — sentiment score uses neutral defaults.")
        if rfd.promoter_pledge_pct is None:
            warnings.append("Promoter pledge % unavailable — governance score uses conservative defaults.")
        st.session_state["data_warnings"] = warnings
    else:
        statuses["extractor"] = "failed"
        err = state.errors.get("extractor", "Unknown error")
        details["extractor"]  = f"✖ {err[:120]}"
        _refresh_progress()

        st.session_state["pipeline_error"] = (
            f"**Data extraction failed for '{state.ticker}'.**\n\n"
            f"**Reason:** {err}\n\n"
            "**Try these fixes:**\n"
            "- Check your internet connection\n"
            "- Yahoo Finance may be rate-limiting requests — wait 60s and retry\n"
            "- The stock may be newly listed with limited historical data"
        )
        return None

    st.session_state["agent_statuses"] = statuses
    st.session_state["agent_details"]  = details
    _refresh_progress()

    # ── AGENT 3: ANALYST ──────────────────────────────────────────────────
    statuses["analyst"] = "running"
    _refresh_progress()

    try:
        state = analyst.run(state)
    except Exception as exc:
        state.log_error("analyst", str(exc))

    if state.is_agent_complete("analyst"):
        extra   = state.raw_financial_data.extra_data or {}
        score   = extra.get("composite_score_100", None)
        verdict = extra.get("verdict", "N/A")
        band    = getattr(state.analytical_insights, "risk_band", "N/A") or "N/A"
        score_s = f"{score:.1f}/100" if score is not None else "N/A"
        statuses["analyst"] = "done"
        details["analyst"]  = f"✓ Score: {score_s} · {verdict} · {band}"
    else:
        statuses["analyst"] = "failed"
        err = state.errors.get("analyst", "Unknown error")
        details["analyst"]  = f"✖ {err[:120]}"
        _refresh_progress()

        st.session_state["pipeline_error"] = (
            f"**Risk scoring failed.**\n\n"
            f"**Reason:** {err}\n\n"
            "The raw financial data was fetched successfully but the scoring engine "
            "encountered an unexpected error. Please try again."
        )
        return None

    st.session_state["agent_statuses"] = statuses
    st.session_state["agent_details"]  = details
    _refresh_progress()

    # ── AGENT 4: DESIGNER ─────────────────────────────────────────────────
    statuses["designer"] = "running"
    _refresh_progress()

    try:
        state = designer.run(state)
    except Exception as exc:
        state.log_error("designer", str(exc))

    if state.is_agent_complete("designer"):
        html_len = len(state.html_report or "")
        statuses["designer"] = "done"
        details["designer"]  = f"✓ Report generated: {html_len:,} chars ({html_len // 1024} KB)"
    else:
        statuses["designer"] = "failed"
        err = state.errors.get("designer", "Unknown error")
        details["designer"]  = f"✖ {err[:120]}"
        # Non-critical for session — analysis is done even if HTML render failed

    st.session_state["agent_statuses"] = statuses
    st.session_state["agent_details"]  = details
    _refresh_progress()

    return state


# =============================================================================
# SECTION 9: HTML REPORT RENDERER
# Renders the HTML string inside a full-width iframe via components.html().
# Height is set to accommodate the 2-page report structure.
# =============================================================================

# Approximate height (in pixels) for the 2-page report.
# This is calibrated to the designer's layout:
#   - Header + metrics strip:           ~180px
#   - Gauge + 7-factor table:           ~560px
#   - Quarterly financials table:       ~280px
#   - Sector KPIs:                      ~180px
#   - Page-2 hidden insights (2×2):     ~480px
#   - Catalysts & Risks (2-col):        ~820px
#   - News breakdown table:             ~380px
#   - Verdict panel:                    ~520px
#   - Footer:                           ~140px
#   - Padding / margin buffers:         ~260px
#   ─────────────────────────────────────────
#   Total:                            ~3,800px
REPORT_IFRAME_HEIGHT = 3900


def _render_html_report(html: str, company_name: str) -> None:
    """
    Renders the full HTML scorecard embedded directly in the Streamlit page.

    TECHNICAL NOTE:
    streamlit.components.v1.html() renders the HTML string inside a sandboxed
    iframe. This means:
    - All custom fonts, CSS, and SVG from the designer agent render perfectly
    - External Google Fonts CDN links load fine (iframe has internet access)
    - No Streamlit CSS interferes with the report's own styling
    - The height parameter must be generous enough to avoid a nested scrollbar

    We also provide a separate download button so users can save the report.
    """

    # ── Section header ────────────────────────────────────────────────────
    st.markdown(
        """
        <div class="report-section-header">
          <div class="report-section-accent"></div>
          <div class="report-section-title">📄 &nbsp; Full Risk Scorecard Report</div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    # ── Download + open hint row ──────────────────────────────────────────
    dl_col, hint_col = st.columns([1, 3], gap="medium")

    with dl_col:
        st.download_button(
            label="⬇  Download HTML Report",
            data=html.encode("utf-8"),
            file_name=f"{company_name.replace(' ', '_')}_risk_report.html",
            mime="text/html",
            use_container_width=True,
            key="download_report",
        )

    with hint_col:
        st.markdown(
            "<div style='padding-top:8px;font-family:\"DM Sans\",sans-serif;"
            "font-size:0.78rem;color:#71717a;'>"
            "💡 The report is rendered live below. Download it to keep a local copy "
            "or share it as a standalone HTML file — it works without internet "
            "(fonts cached after first load)."
            "</div>",
            unsafe_allow_html=True,
        )

    st.markdown(
        "<div style='height:12px;'></div>",
        unsafe_allow_html=True,
    )

    # ── Inject the full HTML report ───────────────────────────────────────
    # We wrap the designer's HTML in a lightweight outer div that removes
    # the grey page background it was designed for (since here it sits on
    # Streamlit's own white canvas) and resets body padding.
    _report_wrapper = f"""
    <style>
      body {{
        background: transparent !important;
        padding: 0 !important;
        margin: 0 !important;
      }}
      .report-container {{
        border-radius: 12px !important;
        box-shadow: 0 4px 24px rgba(0,0,0,0.10) !important;
        margin: 0 !important;
      }}
    </style>
    {html}
    """

    components.html(
        _report_wrapper,
        height=REPORT_IFRAME_HEIGHT,
        scrolling=True,
    )


# =============================================================================
# SECTION 10: ERROR DISPLAY
# =============================================================================

def _render_error(error_msg: str) -> None:
    """Renders a styled error box with actionable guidance."""
    st.markdown(
        f"""
        <div class="error-box">
          <div class="error-title">⚠️ &nbsp; Analysis Could Not Be Completed</div>
          <div class="error-body">{error_msg.replace(chr(10), '<br>')}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def _render_import_errors(errors: list[str]) -> None:
    """Renders a fatal setup error when project imports fail."""
    st.markdown(
        f"""
        <div class="error-box">
          <div class="error-title">🔧 &nbsp; Setup Error — Missing Dependencies</div>
          <div class="error-body">
            The following imports failed:<br>
            {'<br>'.join(f'• {e}' for e in errors)}<br><br>
            <b>Fix:</b> Run <code>pip install -r requirements.txt</code> in your
            terminal from the project root, then restart Streamlit.
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


# =============================================================================
# SECTION 11: SIDEBAR
# Collapsible info panel for instructions and project context.
# =============================================================================

def _render_sidebar() -> None:
    """Renders the collapsible sidebar with usage instructions."""
    with st.sidebar:
        st.markdown(
            """
            <div style="font-family:'IBM Plex Mono',monospace;font-size:0.7rem;
                        color:#b8922e;letter-spacing:0.12em;text-transform:uppercase;
                        margin-bottom:6px;">
              ₹ &nbsp; Investors Way
            </div>
            <div style="font-family:'DM Serif Display',serif;font-size:1.3rem;
                        color:#ffffff;margin-bottom:16px;">
              AI Risk Analyzer
            </div>
            """,
            unsafe_allow_html=True,
        )

        st.markdown("---")
        st.markdown("### 🚀 How It Works")
        st.markdown(
            """
            1. **Type** any NSE/BSE listed company
            2. **Click** Analyze Stock Risk
            3. **Watch** 4 AI agents run live
            4. **Read** the full risk scorecard
            5. **Download** the HTML report
            """
        )

        st.markdown("---")
        st.markdown("### 🤖 The 4 Agents")
        st.markdown(
            """
            | Agent | Role |
            |-------|------|
            | Router | Ticker + Sector |
            | Extractor | Live Data Fetch |
            | Analyst | 7-Factor Scoring |
            | Designer | HTML Report |
            """
        )

        st.markdown("---")
        st.markdown("### 📊 Risk Factors")
        st.markdown(
            """
            - 📊 Valuation (P/E, P/B)
            - 📈 Earnings Quality
            - 🏦 Balance Sheet
            - 🚀 Growth Momentum
            - 🛡️ Governance (Pledge %)
            - 🏭 Sector Risk
            - 📰 Technical & Sentiment
            """
        )

        st.markdown("---")
        st.markdown("### ⚡ Example Companies")
        examples = [
            "HDFC Bank", "Infosys", "Reliance", "TCS",
            "Sun Pharma", "L&T", "Maruti Suzuki",
            "Bajaj Finance", "ITC", "ONGC",
        ]
        for ex in examples:
            st.markdown(f"`{ex}`", unsafe_allow_html=False)

        st.markdown("---")
        st.caption(
            "⚠️ For informational purposes only. "
            "Not investment advice. "
            "Consult a SEBI-registered adviser."
        )


# =============================================================================
# SECTION 12: MAIN APP LAYOUT
# =============================================================================

def main() -> None:
    """
    Main Streamlit app function.

    LAYOUT STRUCTURE:
    ┌─────────────────────────────────────────────┐
    │  [Sidebar]  Usage guide + examples          │
    ├─────────────────────────────────────────────┤
    │  Header card (dark, gold-accented)          │
    │  Search bar + Analyze button                │
    │                                             │
    │  [If running]  Pipeline progress cards      │
    │  [If error]    Error box                    │
    │  [If done]     Result summary bar           │
    │                Data quality warnings        │
    │                Full HTML report (iframe)    │
    └─────────────────────────────────────────────┘
    """

    # ── Fatal import check ────────────────────────────────────────────────
    if _import_errors:
        _render_header()
        _render_import_errors(_import_errors)
        return

    # ── Sidebar ───────────────────────────────────────────────────────────
    _render_sidebar()

    # ── Header ────────────────────────────────────────────────────────────
    _render_header()

    # ── Search Bar ───────────────────────────────────────────────────────
    company_name, clicked = _render_search_bar()

    # ── Handle button click ───────────────────────────────────────────────
    if clicked:
        # Input validation
        if not company_name:
            st.markdown(
                '<div class="warn-box">'
                '⚠️ &nbsp; Please enter a company name before clicking Analyze.'
                '</div>',
                unsafe_allow_html=True,
            )
            return

        if len(company_name) < 2:
            st.markdown(
                '<div class="warn-box">'
                '⚠️ &nbsp; Company name is too short. Please enter at least 2 characters.'
                '</div>',
                unsafe_allow_html=True,
            )
            return

        if len(company_name) > 80:
            st.markdown(
                '<div class="warn-box">'
                '⚠️ &nbsp; Company name is too long. Please enter the company name only '
                '(without address, description, or other text).'
                '</div>',
                unsafe_allow_html=True,
            )
            return

        # Clear previous results before starting a new run
        st.session_state["pipeline_result"]  = None
        st.session_state["pipeline_error"]   = None
        st.session_state["pipeline_running"] = True
        st.session_state["last_company"]     = company_name
        st.session_state["data_warnings"]    = []

        # Run pipeline inside a spinner (provides the top-of-page loading indicator)
        with st.spinner(f"Running AI analysis for **{company_name}**…"):
            state = _run_pipeline(company_name)

        st.session_state["pipeline_running"] = False

        if state is not None and state.html_report:
            st.session_state["pipeline_result"] = state
        elif st.session_state["pipeline_error"] is None:
            # Pipeline ran but designer produced no HTML (shouldn't happen, but guard it)
            st.session_state["pipeline_error"] = (
                "The analysis completed but the HTML report could not be generated. "
                "This is an internal error. Please try again."
            )

    # ── Show error (if any) ───────────────────────────────────────────────
    if st.session_state["pipeline_error"]:
        _render_error(st.session_state["pipeline_error"])

    # ── Show results (if available) ───────────────────────────────────────
    result_state = st.session_state.get("pipeline_result")

    if result_state is not None:
        # Progress cards (now all done/failed — static final state)
        if st.session_state.get("agent_statuses"):
            _render_agent_progress(
                st.session_state["agent_statuses"],
                st.session_state["agent_details"],
            )

        # Result summary bar
        _render_result_bar(result_state)

        # Data quality warnings
        warnings = st.session_state.get("data_warnings", [])
        if warnings:
            for w in warnings:
                st.markdown(
                    f'<div class="warn-box">⚠️ &nbsp; {w}</div>',
                    unsafe_allow_html=True,
                )

        # Full HTML report
        _render_html_report(
            html=result_state.html_report,
            company_name=st.session_state.get("last_company", "report"),
        )

    elif not clicked and not st.session_state.get("pipeline_error"):
        # ── Landing state — show sample companies prompt ─────────────────
        st.markdown(
            """
            <div style="margin-top:8px;padding:28px 32px;background:#f7f7f8;
                        border:1px solid #e4e4e7;border-radius:14px;text-align:center;">
              <div style="font-size:2rem;margin-bottom:10px;">📊</div>
              <div style="font-family:'DM Serif Display',serif;font-size:1.2rem;
                          color:#111118;margin-bottom:8px;">
                Ready to analyze any Indian listed stock
              </div>
              <div style="font-family:'DM Sans',sans-serif;font-size:0.85rem;
                          color:#71717a;max-width:480px;margin:0 auto;line-height:1.6;">
                Type a company name above and click <b>Analyze Stock Risk</b> to generate
                a comprehensive AI-powered equity risk scorecard in under 60 seconds.
              </div>
              <div style="margin-top:18px;display:flex;gap:10px;justify-content:center;flex-wrap:wrap;">
                <span style="background:#ffffff;border:1px solid #e4e4e7;border-radius:6px;
                             padding:5px 14px;font-family:'IBM Plex Mono',monospace;
                             font-size:0.72rem;color:#b8922e;">HDFC Bank</span>
                <span style="background:#ffffff;border:1px solid #e4e4e7;border-radius:6px;
                             padding:5px 14px;font-family:'IBM Plex Mono',monospace;
                             font-size:0.72rem;color:#b8922e;">Infosys</span>
                <span style="background:#ffffff;border:1px solid #e4e4e7;border-radius:6px;
                             padding:5px 14px;font-family:'IBM Plex Mono',monospace;
                             font-size:0.72rem;color:#b8922e;">Sun Pharma</span>
                <span style="background:#ffffff;border:1px solid #e4e4e7;border-radius:6px;
                             padding:5px 14px;font-family:'IBM Plex Mono',monospace;
                             font-size:0.72rem;color:#b8922e;">L&T</span>
                <span style="background:#ffffff;border:1px solid #e4e4e7;border-radius:6px;
                             padding:5px 14px;font-family:'IBM Plex Mono',monospace;
                             font-size:0.72rem;color:#b8922e;">Tata Motors</span>
              </div>
            </div>
            """,
            unsafe_allow_html=True,
        )


# =============================================================================
# ENTRY POINT
# =============================================================================

if __name__ == "__main__":
    main()