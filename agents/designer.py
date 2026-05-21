# =============================================================================
# agents/designer.py
# Agent 4 — HTML Report Designer
# =============================================================================
#
# ROLE: Frontend UI/UX Architect
# --------------------------------
# This agent does ZERO financial calculations and ZERO data fetching.
# Its single responsibility: read the fully-populated AppState and render
# a polished, self-contained, single-file HTML report string.
#
# DESIGN PHILOSOPHY:
# ------------------
# The report targets a sophisticated finance professional audience.
# Aesthetic direction: "Premium Indian equity research note" —
# editorial precision meets institutional gravitas.
#
# Think Bloomberg terminal meets a Goldman Sachs pitch deck:
#   - Clean white canvas (#ffffff) with card-surface warmth (#f7f7f8)
#   - Gold (#b8922e) accents that signal "premium research"
#   - Monospaced numbers for scannable data density
#   - Two-page structure mirroring how a real equity note is consumed:
#       Page 1 → Quick Verdict + Risk Gauge + Key Metrics
#       Page 2 → Deep Dive (Quarterly Trends, Catalysts, Risks, Insights)
#
# FONTS:
#   DM Serif Display — editorial headings (authoritative, classic serif)
#   DM Sans          — body copy (clean, modern, highly readable)
#   IBM Plex Mono    — all numbers, tickers, percentages (terminal/data feel)
#
# OUTPUT:
#   state.html_report ← complete, self-contained HTML string
#   (no external dependencies except Google Fonts CDN — works offline if fonts cached)
#
# INPUT CONTRACT:
#   Reads from state: company_name, ticker, sector, sector_kpis,
#                     raw_financial_data, analytical_insights
#   All missing values handled gracefully with "N/A" fallbacks.
#   The agent must NEVER crash due to missing data.
#
# =============================================================================

from __future__ import annotations

import math
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import pytz

# ---------------------------------------------------------------------------
# PATH SETUP
# ---------------------------------------------------------------------------
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from state import AppState

IST = pytz.timezone("Asia/Kolkata")

# =============================================================================
# SECTION 1: DESIGN TOKENS
# Single source of truth for all visual constants.
# =============================================================================

COLORS = {
    "page_bg":      "#ffffff",
    "card_bg":      "#f7f7f8",
    "border":       "#e4e4e7",
    "dark_surface": "#111118",
    "gold":         "#b8922e",
    "gold_light":   "#d4a843",
    "gold_faint":   "#fdf6e9",
    "text_primary": "#111118",
    "text_secondary":"#52525b",
    "text_muted":   "#a1a1aa",
    "green":        "#15803d",
    "green_bg":     "#f0fdf4",
    "amber":        "#b45309",
    "amber_bg":     "#fffbeb",
    "red":          "#b91c1c",
    "red_bg":       "#fef2f2",
    "blue":         "#1d4ed8",
    "blue_bg":      "#eff6ff",
}

# Verdict → color mapping
VERDICT_STYLES = {
    "Strong Buy":  {"bg": "#f0fdf4", "border": "#15803d", "text": "#14532d", "badge": "#15803d"},
    "Buy":         {"bg": "#f0fdf4", "border": "#16a34a", "text": "#15803d", "badge": "#16a34a"},
    "Hold":        {"bg": "#fffbeb", "border": "#d97706", "text": "#92400e", "badge": "#d97706"},
    "Sell":        {"bg": "#fef2f2", "border": "#dc2626", "text": "#7f1d1d", "badge": "#dc2626"},
    "Strong Sell": {"bg": "#fef2f2", "border": "#991b1b", "text": "#450a0a", "badge": "#991b1b"},
}

# Factor score → color band
def _score_color(score_10: Optional[int]) -> str:
    """Maps a 1–10 factor score to a display color."""
    if score_10 is None:
        return COLORS["text_muted"]
    if score_10 >= 7:
        return COLORS["green"]
    if score_10 >= 4:
        return COLORS["amber"]
    return COLORS["red"]

def _score_bg(score_10: Optional[int]) -> str:
    if score_10 is None:
        return COLORS["card_bg"]
    if score_10 >= 7:
        return COLORS["green_bg"]
    if score_10 >= 4:
        return COLORS["amber_bg"]
    return COLORS["red_bg"]

def _score_label(score_10: Optional[int]) -> str:
    if score_10 is None:
        return "N/A"
    if score_10 >= 7:
        return "LOW RISK"
    if score_10 >= 4:
        return "MODERATE"
    return "HIGH RISK"

# =============================================================================
# SECTION 2: DATA EXTRACTION HELPERS
# Safe accessors — NEVER raise, always return a display-ready string or value.
# =============================================================================

NA = "N/A"

def _s(value: Any, fmt: str = "", suffix: str = "", prefix: str = "") -> str:
    """
    Safely formats a numeric value for display.
    Returns NA if value is None, "Not Available", or NaN.
    """
    if value is None or value == "Not Available" or value == "":
        return NA
    try:
        f = float(value)
        if math.isnan(f) or math.isinf(f):
            return NA
        if fmt:
            formatted = format(f, fmt)
        else:
            formatted = f"{f:,.2f}"
        return f"{prefix}{formatted}{suffix}"
    except (TypeError, ValueError):
        return str(value) if value else NA


def _pct(value: Any, decimals: int = 1) -> str:
    return _s(value, f".{decimals}f", suffix="%")

def _cr(value: Any) -> str:
    return _s(value, ",.0f", prefix="₹", suffix=" Cr")

def _price(value: Any) -> str:
    return _s(value, ",.2f", prefix="₹")

def _ratio(value: Any) -> str:
    return _s(value, ".1f", suffix="x")

def _inr(value: Any) -> str:
    return _s(value, ",.2f", prefix="₹")

def _qoq_change(current: Any, prior: Any) -> str:
    """Computes QoQ % change and returns a colored badge string."""
    try:
        c, p = float(current), float(prior)
        if p == 0:
            return ""
        chg = (c - p) / abs(p) * 100
        sign = "+" if chg >= 0 else ""
        color = COLORS["green"] if chg >= 0 else COLORS["red"]
        arrow = "▲" if chg >= 0 else "▼"
        return (
            f'<span style="color:{color};font-size:0.7rem;font-family:\'IBM Plex Mono\',monospace;">'
            f'{arrow} {sign}{chg:.1f}%</span>'
        )
    except (TypeError, ValueError):
        return ""

def _factor_score_row(label: str, score_obj: Any, icon: str = "") -> str:
    """Renders one row of the 7-factor scoring table."""
    score_val = getattr(score_obj, "score", None) if score_obj else None
    rationale = getattr(score_obj, "rationale", "") or ""
    color     = _score_color(score_val)
    bg        = _score_bg(score_val)
    band      = _score_label(score_val)
    bar_pct   = (score_val or 0) * 10  # 1–10 → 0–100%
    score_display = str(score_val) if score_val is not None else "—"

    # Truncate rationale for the table view
    rat_short = rationale[:160] + "…" if len(rationale) > 160 else rationale

    return f"""
        <tr>
          <td style="padding:14px 16px;border-bottom:1px solid {COLORS['border']};width:200px;">
            <div style="display:flex;align-items:center;gap:8px;">
              <span style="font-size:1.1rem;">{icon}</span>
              <span style="font-family:'DM Sans',sans-serif;font-weight:600;
                           font-size:0.85rem;color:{COLORS['text_primary']};">{label}</span>
            </div>
          </td>
          <td style="padding:14px 16px;border-bottom:1px solid {COLORS['border']};width:80px;text-align:center;">
            <div style="display:inline-flex;align-items:center;justify-content:center;
                        width:42px;height:42px;border-radius:50%;
                        background:{bg};border:2px solid {color};">
              <span style="font-family:'IBM Plex Mono',monospace;font-weight:700;
                           font-size:1.1rem;color:{color};">{score_display}</span>
            </div>
          </td>
          <td style="padding:14px 16px;border-bottom:1px solid {COLORS['border']};width:120px;">
            <div style="background:{COLORS['border']};border-radius:4px;height:8px;overflow:hidden;">
              <div style="background:{color};height:100%;width:{bar_pct}%;
                          border-radius:4px;transition:width 0.3s;"></div>
            </div>
            <div style="margin-top:4px;font-family:'IBM Plex Mono',monospace;
                        font-size:0.65rem;color:{color};text-align:right;">{band}</div>
          </td>
          <td style="padding:14px 16px;border-bottom:1px solid {COLORS['border']};
                     font-family:'DM Sans',sans-serif;font-size:0.8rem;
                     color:{COLORS['text_secondary']};line-height:1.5;">
            {rat_short or "Rationale not available."}
          </td>
        </tr>"""


# =============================================================================
# SECTION 3: SVG GAUGE RENDERER
# Trigonometric needle calculation as specified in the brief.
# =============================================================================

def _render_gauge_svg(composite_score_100: float) -> str:
    """
    Renders a semicircular SVG risk gauge with a computed needle position.

    GEOMETRY:
        The gauge arc spans 180° (π radians), left (high risk) to right (low risk).
        Score 0   → needle points hard left  (HIGH RISK)
        Score 50  → needle points straight up (MODERATE)
        Score 100 → needle points hard right  (LOW RISK)

    NEEDLE COORDINATES (as specified in the brief):
        angle_rad = (composite_score / 100) * π
        cx, cy, r = 160, 155, 115        ← gauge center and radius
        tx = cx + r × cos(π - angle_rad) ← needle tip X
        ty = cy − r × sin(π - angle_rad) ← needle tip Y

    The needle is rendered as a thin polygon (rotated triangle) from the
    gauge center to (tx, ty), with a circular hub at the center.
    """
    score = max(0.0, min(100.0, float(composite_score_100 or 50.0)))

    # ── Prescribed needle trigonometry ───────────────────────────────────
    PI        = math.pi
    angle_rad = (score / 100.0) * PI
    cx, cy, r = 160, 155, 115

    tx = cx + r * math.cos(PI - angle_rad)   # needle tip X
    ty = cy - r * math.sin(PI - angle_rad)   # needle tip Y

    # Needle base: two points flanking the center, perpendicular to the needle
    needle_width = 5
    perp_angle   = (PI - angle_rad) + PI / 2
    bx1 = cx + needle_width * math.cos(perp_angle)
    by1 = cy + needle_width * math.sin(perp_angle)
    bx2 = cx - needle_width * math.cos(perp_angle)
    by2 = cy - needle_width * math.sin(perp_angle)

    # Color the needle based on score zone
    if score >= 66:
        needle_color = COLORS["green"]
        zone_label   = "LOW RISK"
        zone_color   = COLORS["green"]
    elif score >= 40:
        needle_color = COLORS["amber"]
        zone_label   = "MODERATE RISK"
        zone_color   = COLORS["amber"]
    else:
        needle_color = COLORS["red"]
        zone_label   = "HIGH RISK"
        zone_color   = COLORS["red"]

    score_display = f"{score:.1f}"

    # ── Tick marks at 0, 25, 50, 75, 100 (mapped to angles) ─────────────
    tick_marks = ""
    tick_positions = [0, 25, 50, 75, 100]
    for tp in tick_positions:
        ta  = (tp / 100.0) * PI
        t_inner_r = r - 10
        t_outer_r = r + 4
        tick_x1 = cx + t_inner_r * math.cos(PI - ta)
        tick_y1 = cy - t_inner_r * math.sin(PI - ta)
        tick_x2 = cx + t_outer_r * math.cos(PI - ta)
        tick_y2 = cy - t_outer_r * math.sin(PI - ta)
        tick_marks += (
            f'<line x1="{tick_x1:.1f}" y1="{tick_y1:.1f}" '
            f'x2="{tick_x2:.1f}" y2="{tick_y2:.1f}" '
            f'stroke="{COLORS["border"]}" stroke-width="2"/>\n'
        )

    # ── Gauge arc: 3 color zones (red / amber / green) ───────────────────
    # We draw the arc in 3 segments using SVG arc commands.
    def arc_path(start_score: float, end_score: float, color: str, stroke_w: int = 18) -> str:
        a1 = (start_score / 100.0) * PI
        a2 = (end_score   / 100.0) * PI
        x1 = cx + r * math.cos(PI - a1)
        y1 = cy - r * math.sin(PI - a1)
        x2 = cx + r * math.cos(PI - a2)
        y2 = cy - r * math.sin(PI - a2)
        return (
            f'<path d="M {x1:.2f} {y1:.2f} A {r} {r} 0 0 1 {x2:.2f} {y2:.2f}" '
            f'fill="none" stroke="{color}" stroke-width="{stroke_w}" '
            f'stroke-linecap="round" opacity="0.85"/>'
        )

    arcs = (
        arc_path(0,  33,  COLORS["red"],   18) + "\n"
        + arc_path(33, 66,  COLORS["amber"], 18) + "\n"
        + arc_path(66, 100, COLORS["green"], 18)
    )

    return f"""
<svg viewBox="0 0 320 175" xmlns="http://www.w3.org/2000/svg"
     style="width:100%;max-width:320px;display:block;margin:0 auto;overflow:visible;">

  <!-- Background track arc -->
  <path d="M {cx - r} {cy} A {r} {r} 0 0 1 {cx + r} {cy}"
        fill="none" stroke="{COLORS['border']}" stroke-width="20" stroke-linecap="round"/>

  <!-- Colored zone arcs -->
  {arcs}

  <!-- Tick marks -->
  {tick_marks}

  <!-- Zone labels -->
  <text x="{cx - r - 6}" y="{cy + 22}" font-family="'IBM Plex Mono',monospace"
        font-size="9" fill="{COLORS['red']}" text-anchor="middle">HIGH</text>
  <text x="{cx}" y="{cy - r - 12}" font-family="'IBM Plex Mono',monospace"
        font-size="9" fill="{COLORS['amber']}" text-anchor="middle">MID</text>
  <text x="{cx + r + 6}" y="{cy + 22}" font-family="'IBM Plex Mono',monospace"
        font-size="9" fill="{COLORS['green']}" text-anchor="middle">LOW</text>

  <!-- Needle shadow -->
  <polygon points="{tx:.2f},{ty:.2f} {bx1:.2f},{by1:.2f} {bx2:.2f},{by2:.2f}"
           fill="rgba(0,0,0,0.12)" transform="translate(2,2)"/>

  <!-- Needle -->
  <polygon points="{tx:.2f},{ty:.2f} {bx1:.2f},{by1:.2f} {bx2:.2f},{by2:.2f}"
           fill="{needle_color}" opacity="0.95"/>

  <!-- Hub circle -->
  <circle cx="{cx}" cy="{cy}" r="10" fill="{COLORS['dark_surface']}" stroke="white" stroke-width="2"/>
  <circle cx="{cx}" cy="{cy}" r="4"  fill="{needle_color}"/>

  <!-- Score display -->
  <text x="{cx}" y="{cy + 42}" font-family="'IBM Plex Mono',monospace"
        font-weight="700" font-size="28" fill="{zone_color}" text-anchor="middle">{score_display}</text>
  <text x="{cx}" y="{cy + 58}" font-family="'DM Sans',sans-serif"
        font-size="10" fill="{COLORS['text_muted']}" text-anchor="middle">out of 100</text>

  <!-- Zone badge -->
  <rect x="{cx - 50}" y="{cy + 66}" width="100" height="20" rx="10"
        fill="{zone_color}" opacity="0.12"/>
  <text x="{cx}" y="{cy + 80}" font-family="'IBM Plex Mono',monospace"
        font-weight="700" font-size="9" fill="{zone_color}" text-anchor="middle">{zone_label}</text>
</svg>"""


# =============================================================================
# SECTION 4: COMPONENT BUILDERS
# Each function returns an HTML fragment for one section of the report.
# =============================================================================

def _build_header(state: AppState, generated_at: str) -> str:
    """Page-spanning header with company identity and report metadata."""
    verdict_raw = (state.raw_financial_data.extra_data or {}).get("verdict", "Hold")
    vstyle = VERDICT_STYLES.get(verdict_raw, VERDICT_STYLES["Hold"])
    composite_100 = (state.raw_financial_data.extra_data or {}).get("composite_score_100", 50.0)
    ticker_display = (state.ticker or "").replace(".NS", "").replace(".BO", "")

    return f"""
  <!-- ═══════════════ HEADER ═══════════════ -->
  <div style="background:{COLORS['dark_surface']};padding:36px 48px 32px;
              border-bottom:3px solid {COLORS['gold']};">
    <div style="display:flex;justify-content:space-between;align-items:flex-start;flex-wrap:wrap;gap:16px;">

      <!-- Left: Branding + Company Name -->
      <div>
        <div style="display:flex;align-items:center;gap:10px;margin-bottom:12px;">
          <div style="width:32px;height:32px;background:{COLORS['gold']};border-radius:6px;
                      display:flex;align-items:center;justify-content:center;">
            <span style="color:{COLORS['dark_surface']};font-weight:900;font-size:1rem;
                         font-family:'IBM Plex Mono',monospace;">₹</span>
          </div>
          <span style="font-family:'IBM Plex Mono',monospace;font-size:0.7rem;
                       letter-spacing:0.15em;color:{COLORS['gold']};text-transform:uppercase;">
            NSE · BSE Risk Scorecard
          </span>
        </div>
        <h1 style="font-family:'DM Serif Display',serif;font-size:2.4rem;font-weight:400;
                   color:#ffffff;margin:0 0 6px;line-height:1.1;letter-spacing:-0.02em;">
          {state.company_name}
        </h1>
        <div style="display:flex;align-items:center;gap:12px;flex-wrap:wrap;">
          <span style="font-family:'IBM Plex Mono',monospace;font-size:0.85rem;
                       color:{COLORS['gold']};letter-spacing:0.05em;">{ticker_display}</span>
          <span style="color:#3f3f46;">|</span>
          <span style="font-family:'DM Sans',sans-serif;font-size:0.85rem;color:#a1a1aa;">
            {state.sector or "Unknown Sector"}
          </span>
        </div>
      </div>

      <!-- Right: Verdict Badge -->
      <div style="text-align:right;">
        <div style="display:inline-block;padding:10px 22px;border-radius:8px;
                    background:{vstyle['badge']};margin-bottom:8px;">
          <span style="font-family:'IBM Plex Mono',monospace;font-weight:700;
                       font-size:1.1rem;color:#ffffff;letter-spacing:0.05em;">
            {verdict_raw.upper()}
          </span>
        </div>
        <div style="font-family:'IBM Plex Mono',monospace;font-size:0.7rem;
                    color:#71717a;margin-top:8px;">
          Generated: {generated_at}
        </div>
        <div style="font-family:'IBM Plex Mono',monospace;font-size:0.7rem;color:#52525b;margin-top:2px;">
          Composite Score: <span style="color:{COLORS['gold']};">{composite_100:.1f}/100</span>
        </div>
      </div>
    </div>
  </div>"""


def _build_metrics_strip(state: AppState) -> str:
    """Top KPI strip: CMP, 52W range, P/E, P/B, ROE, Div Yield."""
    rfd = state.raw_financial_data
    market_cap = rfd.extra_data.get("market_cap_cr", NA)

    metrics = [
        ("CMP",           _price(rfd.cmp),           "Current Market Price"),
        ("Market Cap",    _cr(market_cap),            "₹ Crore"),
        ("52W High",      _price(rfd.week_52_high),   "Trailing 52 Weeks"),
        ("52W Low",       _price(rfd.week_52_low),    "Trailing 52 Weeks"),
        ("P/E (TTM)",     _ratio(rfd.pe_ratio),       "Price-to-Earnings"),
        ("P/B",           _ratio(rfd.pb_ratio),       "Price-to-Book"),
        ("ROE",           _pct(rfd.roe),              "Return on Equity"),
        ("Div. Yield",    _pct(rfd.dividend_yield),   "Trailing 12M"),
    ]

    cells = ""
    for i, (label, value, subtitle) in enumerate(metrics):
        border_right = f"border-right:1px solid {COLORS['border']};" if i < len(metrics) - 1 else ""
        cells += f"""
        <td style="padding:18px 20px;text-align:center;{border_right}vertical-align:middle;">
          <div style="font-family:'DM Sans',sans-serif;font-size:0.68rem;
                      color:{COLORS['text_muted']};text-transform:uppercase;
                      letter-spacing:0.08em;margin-bottom:6px;">{label}</div>
          <div style="font-family:'IBM Plex Mono',monospace;font-weight:700;
                      font-size:1.05rem;color:{COLORS['text_primary']};">{value}</div>
          <div style="font-family:'DM Sans',sans-serif;font-size:0.65rem;
                      color:{COLORS['text_muted']};margin-top:3px;">{subtitle}</div>
        </td>"""

    return f"""
  <!-- ═══════════════ METRICS STRIP ═══════════════ -->
  <div style="background:{COLORS['card_bg']};border-bottom:1px solid {COLORS['border']};">
    <table style="width:100%;border-collapse:collapse;">
      <tr>{cells}</tr>
    </table>
  </div>"""


def _build_gauge_and_factors(state: AppState) -> str:
    """Left: SVG gauge with composite score. Right: 7-factor scoring table."""
    ai  = state.analytical_insights
    rfd = state.raw_financial_data
    composite_100 = rfd.extra_data.get("composite_score_100", 50.0)

    gauge_svg = _render_gauge_svg(composite_100)

    # Factor rows
    factors = [
        ("Valuation Risk",          getattr(ai, "valuation",         None), "📊"),
        ("Earnings Quality",        getattr(ai, "earnings_quality",   None), "📈"),
        ("Balance Sheet",           getattr(ai, "macro_sensitivity",  None), "🏦"),
        ("Growth Momentum",         getattr(ai, "momentum",           None), "🚀"),
        ("Mgmt & Governance",       getattr(ai, "promoter_pledging",  None), "🛡️"),
        ("Sector Risk",             getattr(ai, "sector_kpi_score",   None), "🏭"),
        ("Technical & Sentiment",   getattr(ai, "sentiment",          None), "📰"),
    ]

    rows = "".join(_factor_score_row(label, obj, icon) for label, obj, icon in factors)

    # Promoter data pill
    pledge      = rfd.promoter_pledge_pct
    holding_raw = rfd.extra_data.get("promoter_holding_pct", NA)
    pledge_str  = _pct(pledge) if pledge is not None else NA
    pledge_color = COLORS["red"] if (pledge or 0) > 10 else COLORS["green"]

    return f"""
  <!-- ═══════════════ GAUGE + FACTOR GRID ═══════════════ -->
  <div style="display:grid;grid-template-columns:300px 1fr;gap:0;
              border-bottom:1px solid {COLORS['border']};">

    <!-- Gauge Panel -->
    <div style="padding:32px 24px;border-right:1px solid {COLORS['border']};
                background:{COLORS['card_bg']};display:flex;flex-direction:column;
                align-items:center;justify-content:center;gap:20px;">
      <div style="font-family:'DM Serif Display',serif;font-size:1rem;font-weight:400;
                  color:{COLORS['text_secondary']};text-align:center;letter-spacing:0.03em;">
        Composite Risk Score
      </div>
      {gauge_svg}

      <!-- Shareholding Pills -->
      <div style="width:100%;background:{COLORS['page_bg']};border:1px solid {COLORS['border']};
                  border-radius:10px;padding:14px 16px;margin-top:4px;">
        <div style="font-family:'DM Sans',sans-serif;font-size:0.7rem;font-weight:600;
                    color:{COLORS['text_muted']};text-transform:uppercase;
                    letter-spacing:0.08em;margin-bottom:10px;">Shareholding</div>
        <div style="display:flex;justify-content:space-between;margin-bottom:8px;">
          <span style="font-family:'DM Sans',sans-serif;font-size:0.78rem;
                       color:{COLORS['text_secondary']};">Promoter Holding</span>
          <span style="font-family:'IBM Plex Mono',monospace;font-size:0.78rem;
                       font-weight:600;color:{COLORS['text_primary']};">
            {_pct(holding_raw) if holding_raw not in (NA, None, "Not Available") else NA}
          </span>
        </div>
        <div style="display:flex;justify-content:space-between;">
          <span style="font-family:'DM Sans',sans-serif;font-size:0.78rem;
                       color:{COLORS['text_secondary']};">Promoter Pledge</span>
          <span style="font-family:'IBM Plex Mono',monospace;font-size:0.78rem;
                       font-weight:700;color:{pledge_color};">{pledge_str}</span>
        </div>
      </div>
    </div>

    <!-- Factor Table -->
    <div style="overflow-x:auto;">
      <table style="width:100%;border-collapse:collapse;">
        <thead>
          <tr style="background:{COLORS['dark_surface']};">
            <th style="padding:12px 16px;text-align:left;font-family:'DM Sans',sans-serif;
                       font-size:0.72rem;font-weight:600;color:{COLORS['gold']};
                       text-transform:uppercase;letter-spacing:0.08em;">Risk Factor</th>
            <th style="padding:12px 16px;text-align:center;font-family:'DM Sans',sans-serif;
                       font-size:0.72rem;font-weight:600;color:{COLORS['gold']};
                       text-transform:uppercase;letter-spacing:0.08em;">Score /10</th>
            <th style="padding:12px 16px;text-align:left;font-family:'DM Sans',sans-serif;
                       font-size:0.72rem;font-weight:600;color:{COLORS['gold']};
                       text-transform:uppercase;letter-spacing:0.08em;">Band</th>
            <th style="padding:12px 16px;text-align:left;font-family:'DM Sans',sans-serif;
                       font-size:0.72rem;font-weight:600;color:{COLORS['gold']};
                       text-transform:uppercase;letter-spacing:0.08em;">Analytical Rationale</th>
          </tr>
        </thead>
        <tbody style="background:{COLORS['page_bg']};">{rows}</tbody>
      </table>
    </div>
  </div>"""


def _build_quarterly_table(state: AppState) -> str:
    """4-quarter financials table with QoQ change badges."""
    quarters = state.raw_financial_data.quarterly_financials

    if not quarters:
        return f"""
  <div style="padding:32px 48px;">
    <h2 style="font-family:'DM Serif Display',serif;font-size:1.3rem;color:{COLORS['text_primary']};
               margin:0 0 16px;">Quarterly Financials</h2>
    <p style="font-family:'DM Sans',sans-serif;color:{COLORS['text_muted']};font-style:italic;">
      No quarterly data available.</p>
  </div>"""

    # Header row — quarter labels
    header_cells = '<th style="padding:12px 16px;text-align:left;font-family:\'DM Sans\',sans-serif;font-size:0.72rem;font-weight:600;color:{gold};text-transform:uppercase;letter-spacing:0.08em;">Metric (₹ Cr)</th>'.format(gold=COLORS['gold'])
    for q in quarters:
        header_cells += f'<th style="padding:12px 16px;text-align:right;font-family:\'IBM Plex Mono\',monospace;font-size:0.8rem;font-weight:700;color:{COLORS["gold"]};letter-spacing:0.03em;">{q.quarter_label}</th>'

    def metric_row(metric_name: str, values: list, formatter) -> str:
        cells = f'<td style="padding:12px 16px;font-family:\'DM Sans\',sans-serif;font-size:0.82rem;font-weight:600;color:{COLORS["text_primary"]};border-bottom:1px solid {COLORS["border"]};">{metric_name}</td>'
        for i, val in enumerate(values):
            qoq = ""
            if i < len(values) - 1 and val is not None and values[i+1] is not None:
                qoq = _qoq_change(val, values[i+1])
            display = formatter(val) if val is not None else f'<span style="color:{COLORS["text_muted"]};">N/A</span>'
            cells += f'<td style="padding:12px 16px;text-align:right;font-family:\'IBM Plex Mono\',monospace;font-size:0.82rem;color:{COLORS["text_primary"]};border-bottom:1px solid {COLORS["border"]};vertical-align:middle;">{display}<br>{qoq}</td>'
        return f'<tr>{cells}</tr>'

    rev_vals    = [q.revenue_cr for q in quarters]
    pat_vals    = [q.pat_cr     for q in quarters]
    ebitda_vals = [q.ebitda_cr  for q in quarters]
    eps_vals    = [q.eps        for q in quarters]

    rows = (
        metric_row("Revenue",    rev_vals,    lambda v: f"₹{v:,.0f}")
        + metric_row("PAT (Net Profit)", pat_vals,  lambda v: f"₹{v:,.0f}")
        + metric_row("EBITDA / Op. Inc.", ebitda_vals, lambda v: f"₹{v:,.0f}")
        + metric_row("EPS (₹/share)", eps_vals, lambda v: f"{v:.2f}")
    )

    return f"""
  <!-- ═══════════════ QUARTERLY TABLE ═══════════════ -->
  <div style="padding:32px 48px 0;">
    <div style="display:flex;align-items:center;gap:10px;margin-bottom:20px;">
      <div style="width:3px;height:22px;background:{COLORS['gold']};border-radius:2px;"></div>
      <h2 style="font-family:'DM Serif Display',serif;font-size:1.4rem;font-weight:400;
                 color:{COLORS['text_primary']};margin:0;">Quarterly Financial Trend</h2>
      <span style="font-family:'IBM Plex Mono',monospace;font-size:0.68rem;
                   color:{COLORS['text_muted']};background:{COLORS['card_bg']};
                   padding:3px 8px;border-radius:4px;border:1px solid {COLORS['border']};">
        Most recent → oldest
      </span>
    </div>
    <div style="border:1px solid {COLORS['border']};border-radius:12px;overflow:hidden;">
      <table style="width:100%;border-collapse:collapse;">
        <thead style="background:{COLORS['dark_surface']};">
          <tr>{header_cells}</tr>
        </thead>
        <tbody style="background:{COLORS['page_bg']};">{rows}</tbody>
      </table>
    </div>
  </div>"""


def _build_sector_kpis(state: AppState) -> str:
    """Sector KPI cards — 2 KPIs rendered side by side."""
    kpis = state.sector_kpis or []
    if not kpis:
        return ""

    cards = ""
    for kpi in kpis:
        val_str = NA
        if kpi.value is not None:
            val_str = f"{kpi.value:.2f}{kpi.unit or ''}"

        cards += f"""
      <div style="flex:1;min-width:200px;background:{COLORS['gold_faint']};
                  border:1px solid #e6c97a;border-radius:12px;padding:20px 22px;">
        <div style="font-family:'IBM Plex Mono',monospace;font-size:0.68rem;
                    color:{COLORS['gold']};text-transform:uppercase;
                    letter-spacing:0.1em;margin-bottom:8px;">Sector KPI</div>
        <div style="font-family:'DM Serif Display',serif;font-size:1.15rem;
                    color:{COLORS['text_primary']};margin-bottom:10px;line-height:1.3;">
          {kpi.name}
        </div>
        <div style="font-family:'IBM Plex Mono',monospace;font-size:1.6rem;
                    font-weight:700;color:{COLORS['gold']};margin-bottom:8px;">{val_str}</div>
        <div style="font-family:'DM Sans',sans-serif;font-size:0.78rem;
                    color:{COLORS['text_secondary']};line-height:1.5;">
          {kpi.description or ""}
        </div>
      </div>"""

    return f"""
  <!-- ═══════════════ SECTOR KPIs ═══════════════ -->
  <div style="padding:28px 48px 0;">
    <div style="display:flex;align-items:center;gap:10px;margin-bottom:16px;">
      <div style="width:3px;height:22px;background:{COLORS['gold']};border-radius:2px;"></div>
      <h2 style="font-family:'DM Serif Display',serif;font-size:1.4rem;font-weight:400;
                 color:{COLORS['text_primary']};margin:0;">
        {state.sector or "Sector"} — Key Performance Indicators
      </h2>
    </div>
    <div style="display:flex;gap:16px;flex-wrap:wrap;">{cards}</div>
  </div>"""


def _build_hidden_insights(state: AppState) -> str:
    """4-panel hidden insights grid."""
    insights = (state.raw_financial_data.extra_data or {}).get("hidden_insights", [])
    if not insights:
        return ""

    panels = ""
    icons  = ["🔍", "⚡", "📉", "🌐"]
    titles = [
        "Earnings Quality Signal",
        "Promoter Pledge Dynamics",
        "Valuation–Growth Alignment",
        "Macro Sector Exposure",
    ]

    for i, insight in enumerate(insights[:4]):
        icon  = icons[i] if i < len(icons) else "💡"
        title = titles[i] if i < len(titles) else f"Insight {i+1}"
        panels += f"""
      <div style="background:{COLORS['card_bg']};border:1px solid {COLORS['border']};
                  border-radius:12px;padding:22px 24px;
                  border-left:4px solid {COLORS['gold']};">
        <div style="display:flex;align-items:center;gap:8px;margin-bottom:12px;">
          <span style="font-size:1.2rem;">{icon}</span>
          <span style="font-family:'IBM Plex Mono',monospace;font-size:0.72rem;
                       font-weight:700;color:{COLORS['gold']};text-transform:uppercase;
                       letter-spacing:0.08em;">{title}</span>
        </div>
        <p style="font-family:'DM Sans',sans-serif;font-size:0.82rem;
                  color:{COLORS['text_secondary']};line-height:1.65;margin:0;">
          {insight}
        </p>
      </div>"""

    return f"""
  <!-- ═══════════════ HIDDEN INSIGHTS ═══════════════ -->
  <div style="padding:32px 48px 0;">
    <div style="display:flex;align-items:center;gap:10px;margin-bottom:20px;">
      <div style="width:3px;height:22px;background:{COLORS['gold']};border-radius:2px;"></div>
      <h2 style="font-family:'DM Serif Display',serif;font-size:1.4rem;font-weight:400;
                 color:{COLORS['text_primary']};margin:0;">Hidden Insights</h2>
      <span style="font-family:'DM Sans',sans-serif;font-size:0.75rem;
                   color:{COLORS['text_muted']};font-style:italic;">
        Non-obvious signals that move markets
      </span>
    </div>
    <div style="display:grid;grid-template-columns:repeat(2, 1fr);gap:16px;">{panels}</div>
  </div>"""


def _build_catalysts_and_risks(state: AppState) -> str:
    """Side-by-side Catalysts (green) and Risks (red) columns."""
    extra      = state.raw_financial_data.extra_data or {}
    catalysts  = extra.get("all_catalysts", [])
    risks      = extra.get("all_risks", [])

    def item_list(items: list, color: str, bullet: str) -> str:
        if not items:
            return f'<p style="font-family:\'DM Sans\',sans-serif;font-size:0.82rem;color:{COLORS["text_muted"]};font-style:italic;">No data available.</p>'
        li_items = ""
        for i, item in enumerate(items, 1):
            li_items += f"""
          <div style="display:flex;gap:12px;padding:12px 0;
                      border-bottom:1px solid {COLORS['border']};">
            <div style="flex-shrink:0;width:22px;height:22px;border-radius:50%;
                        background:{color};display:flex;align-items:center;
                        justify-content:center;margin-top:1px;">
              <span style="font-family:'IBM Plex Mono',monospace;font-size:0.65rem;
                           font-weight:700;color:#ffffff;">{i}</span>
            </div>
            <p style="font-family:'DM Sans',sans-serif;font-size:0.8rem;
                      color:{COLORS['text_secondary']};line-height:1.6;margin:0;">{item}</p>
          </div>"""
        return li_items

    return f"""
  <!-- ═══════════════ CATALYSTS & RISKS ═══════════════ -->
  <div style="padding:32px 48px 0;">
    <div style="display:flex;align-items:center;gap:10px;margin-bottom:20px;">
      <div style="width:3px;height:22px;background:{COLORS['gold']};border-radius:2px;"></div>
      <h2 style="font-family:'DM Serif Display',serif;font-size:1.4rem;font-weight:400;
                 color:{COLORS['text_primary']};margin:0;">Catalysts &amp; Risks</h2>
    </div>

    <div style="display:grid;grid-template-columns:1fr 1fr;gap:20px;">

      <!-- Catalysts -->
      <div style="background:{COLORS['green_bg']};border:1px solid #bbf7d0;border-radius:12px;
                  padding:22px 24px;">
        <div style="display:flex;align-items:center;gap:8px;margin-bottom:16px;
                    padding-bottom:12px;border-bottom:1px solid #bbf7d0;">
          <span style="font-size:1.1rem;">🚀</span>
          <span style="font-family:'IBM Plex Mono',monospace;font-weight:700;font-size:0.78rem;
                       color:{COLORS['green']};text-transform:uppercase;letter-spacing:0.08em;">
            8 Key Catalysts
          </span>
        </div>
        {item_list(catalysts, COLORS['green'], "✓")}
      </div>

      <!-- Risks -->
      <div style="background:{COLORS['red_bg']};border:1px solid #fecaca;border-radius:12px;
                  padding:22px 24px;">
        <div style="display:flex;align-items:center;gap:8px;margin-bottom:16px;
                    padding-bottom:12px;border-bottom:1px solid #fecaca;">
          <span style="font-size:1.1rem;">⚠️</span>
          <span style="font-family:'IBM Plex Mono',monospace;font-weight:700;font-size:0.78rem;
                       color:{COLORS['red']};text-transform:uppercase;letter-spacing:0.08em;">
            8 Key Risks
          </span>
        </div>
        {item_list(risks, COLORS['red'], "✗")}
      </div>
    </div>
  </div>"""


def _build_news_breakdown(state: AppState) -> str:
    """News sentiment breakdown with headline list."""
    headlines = state.raw_financial_data.news_headlines or []

    if not headlines:
        return f"""
  <div style="padding:32px 48px 0;">
    <div style="display:flex;align-items:center;gap:10px;margin-bottom:16px;">
      <div style="width:3px;height:22px;background:{COLORS['gold']};border-radius:2px;"></div>
      <h2 style="font-family:'DM Serif Display',serif;font-size:1.4rem;font-weight:400;
                 color:{COLORS['text_primary']};margin:0;">News &amp; Sentiment (60 Days)</h2>
    </div>
    <p style="font-family:'DM Sans',sans-serif;color:{COLORS['text_muted']};font-style:italic;
               padding:20px;">No news headlines available for this period.</p>
  </div>"""

    # Count sentiment signals using simple keyword scan
    NEG_KW = ["fraud","probe","loss","decline","default","downgrade","penalty","fine","ban","recall","layoff","resign"]
    POS_KW = ["record profit","upgrade","beats","buyback","dividend","order win","approval","expansion","buy"]

    pos_count, neg_count, neu_count = 0, 0, 0
    for h in headlines:
        text = h.get("headline", "").lower()
        is_pos = any(kw in text for kw in POS_KW)
        is_neg = any(kw in text for kw in NEG_KW)
        if is_pos and not is_neg:
            pos_count += 1
        elif is_neg:
            neg_count += 1
        else:
            neu_count += 1

    total = len(headlines)
    pos_pct = pos_count / total * 100 if total else 0
    neg_pct = neg_count / total * 100 if total else 0
    neu_pct = neu_count / total * 100 if total else 0

    # Sentiment bar
    sentiment_bar = f"""
      <div style="background:{COLORS['border']};border-radius:6px;height:12px;
                  overflow:hidden;margin:12px 0;display:flex;">
        <div style="background:{COLORS['green']};width:{pos_pct:.0f}%;height:100%;"></div>
        <div style="background:{COLORS['text_muted']};width:{neu_pct:.0f}%;height:100%;"></div>
        <div style="background:{COLORS['red']};width:{neg_pct:.0f}%;height:100%;"></div>
      </div>
      <div style="display:flex;gap:16px;font-family:'IBM Plex Mono',monospace;font-size:0.68rem;">
        <span style="color:{COLORS['green']};">● Positive: {pos_count} ({pos_pct:.0f}%)</span>
        <span style="color:{COLORS['text_muted']};">● Neutral: {neu_count} ({neu_pct:.0f}%)</span>
        <span style="color:{COLORS['red']};">● Negative: {neg_count} ({neg_pct:.0f}%)</span>
      </div>"""

    # Show up to 8 most recent headlines
    news_rows = ""
    for h in headlines[:8]:
        date     = h.get("date", "")
        headline = h.get("headline", "")
        source   = h.get("source", "")
        url      = h.get("url", "#")

        text_lower = headline.lower()
        is_pos = any(kw in text_lower for kw in POS_KW)
        is_neg = any(kw in text_lower for kw in NEG_KW)
        dot_color = COLORS['green'] if is_pos and not is_neg else (COLORS['red'] if is_neg else COLORS['text_muted'])

        news_rows += f"""
        <tr>
          <td style="padding:10px 16px;border-bottom:1px solid {COLORS['border']};width:24px;">
            <div style="width:8px;height:8px;border-radius:50%;background:{dot_color};"></div>
          </td>
          <td style="padding:10px 8px;border-bottom:1px solid {COLORS['border']};
                     font-family:'IBM Plex Mono',monospace;font-size:0.72rem;
                     color:{COLORS['text_muted']};white-space:nowrap;">{date}</td>
          <td style="padding:10px 12px;border-bottom:1px solid {COLORS['border']};
                     font-family:'DM Sans',sans-serif;font-size:0.8rem;
                     color:{COLORS['text_primary']};line-height:1.4;">
            <a href="{url}" style="color:inherit;text-decoration:none;"
               target="_blank">{headline}</a>
          </td>
          <td style="padding:10px 16px;border-bottom:1px solid {COLORS['border']};
                     font-family:'IBM Plex Mono',monospace;font-size:0.68rem;
                     color:{COLORS['gold']};white-space:nowrap;">{source}</td>
        </tr>"""

    remaining = total - 8
    more_row = ""
    if remaining > 0:
        more_row = f"""<tr><td colspan="4" style="padding:10px 16px;font-family:'DM Sans',sans-serif;
                       font-size:0.75rem;color:{COLORS['text_muted']};font-style:italic;text-align:center;">
                       + {remaining} more headlines in the 60-day window</td></tr>"""

    return f"""
  <!-- ═══════════════ NEWS BREAKDOWN ═══════════════ -->
  <div style="padding:32px 48px 0;">
    <div style="display:flex;align-items:center;gap:10px;margin-bottom:16px;">
      <div style="width:3px;height:22px;background:{COLORS['gold']};border-radius:2px;"></div>
      <h2 style="font-family:'DM Serif Display',serif;font-size:1.4rem;font-weight:400;
                 color:{COLORS['text_primary']};margin:0;">News &amp; Sentiment (60 Days)</h2>
      <span style="font-family:'IBM Plex Mono',monospace;font-size:0.68rem;
                   color:{COLORS['text_muted']};background:{COLORS['card_bg']};
                   padding:3px 8px;border-radius:4px;border:1px solid {COLORS['border']};">
        {total} articles
      </span>
    </div>

    <!-- Sentiment Summary Bar -->
    <div style="background:{COLORS['card_bg']};border:1px solid {COLORS['border']};
                border-radius:12px;padding:18px 22px;margin-bottom:20px;">
      <div style="font-family:'DM Sans',sans-serif;font-size:0.78rem;font-weight:600;
                  color:{COLORS['text_secondary']};margin-bottom:4px;">
        Sentiment Distribution
      </div>
      {sentiment_bar}
    </div>

    <!-- Headlines Table -->
    <div style="border:1px solid {COLORS['border']};border-radius:12px;overflow:hidden;">
      <table style="width:100%;border-collapse:collapse;background:{COLORS['page_bg']};">
        <thead style="background:{COLORS['dark_surface']};">
          <tr>
            <th style="padding:10px 16px;width:24px;"></th>
            <th style="padding:10px 8px;text-align:left;font-family:'IBM Plex Mono',monospace;
                       font-size:0.68rem;color:{COLORS['gold']};text-transform:uppercase;letter-spacing:0.08em;">Date</th>
            <th style="padding:10px 12px;text-align:left;font-family:'IBM Plex Mono',monospace;
                       font-size:0.68rem;color:{COLORS['gold']};text-transform:uppercase;letter-spacing:0.08em;">Headline</th>
            <th style="padding:10px 16px;text-align:left;font-family:'IBM Plex Mono',monospace;
                       font-size:0.68rem;color:{COLORS['gold']};text-transform:uppercase;letter-spacing:0.08em;">Source</th>
          </tr>
        </thead>
        <tbody>{news_rows}{more_row}</tbody>
      </table>
    </div>
  </div>"""


def _build_verdict_panel(state: AppState) -> str:
    """Full-width bottom-line verdict with upgrade/downgrade conditions."""
    ai          = state.analytical_insights
    verdict_raw = (state.raw_financial_data.extra_data or {}).get("verdict", "Hold")
    vstyle      = VERDICT_STYLES.get(verdict_raw, VERDICT_STYLES["Hold"])
    verdict_text = (ai.final_verdict_text or "").strip()

    if not verdict_text:
        return ""

    # Split verdict_text into display sections
    # The text from analyst.py uses ━━━ separators and section labels
    lines      = verdict_text.split("\n")
    body_lines = []
    in_body    = False
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("━"):
            continue
        if stripped.startswith("BOTTOM-LINE VERDICT") or stripped.startswith("Composite"):
            continue
        body_lines.append(stripped)

    formatted = " ".join(l for l in body_lines if l).strip()

    # Replace section headers with styled spans
    sections_html = ""
    raw_sections  = verdict_text.split("\n\n")
    for section in raw_sections:
        s = section.strip()
        if not s or s.startswith("━") or "BOTTOM-LINE VERDICT" in s:
            continue
        if s.startswith("ASSESSMENT SUMMARY"):
            parts = s.split("\n", 1)
            heading = parts[0].strip()
            content = parts[1].strip() if len(parts) > 1 else ""
            sections_html += f"""
        <div style="margin-bottom:18px;">
          <div style="font-family:'IBM Plex Mono',monospace;font-size:0.7rem;font-weight:700;
                      color:{COLORS['gold']};text-transform:uppercase;letter-spacing:0.1em;
                      margin-bottom:8px;">{heading}</div>
          <p style="font-family:'DM Sans',sans-serif;font-size:0.85rem;
                    color:{COLORS['text_secondary']};line-height:1.7;margin:0;">{content}</p>
        </div>"""
        elif any(s.startswith(h) for h in ["STRENGTHS:", "WEAKNESSES:", "UPGRADE CONDITIONS", "DOWNGRADE CONDITIONS", "DISCLAIMER"]):
            lines_in = s.split("\n")
            heading  = lines_in[0].strip().rstrip(":")
            items    = [l.strip() for l in lines_in[1:] if l.strip()]
            color = COLORS['green'] if "UPGRADE" in heading or "STRENGTH" in heading else \
                    (COLORS['red'] if "DOWNGRADE" in heading or "WEAKNESS" in heading or "DISCLAIMER" in heading else COLORS['text_muted'])
            items_html = "".join(
                f'<div style="font-family:\'DM Sans\',sans-serif;font-size:0.8rem;'
                f'color:{COLORS["text_secondary"]};line-height:1.6;padding:4px 0;">{item}</div>'
                for item in items
            )
            sections_html += f"""
        <div style="margin-bottom:18px;">
          <div style="font-family:'IBM Plex Mono',monospace;font-size:0.68rem;font-weight:700;
                      color:{color};text-transform:uppercase;letter-spacing:0.1em;
                      margin-bottom:8px;padding-bottom:6px;border-bottom:1px solid {COLORS['border']};">
            {heading}
          </div>
          {items_html}
        </div>"""

    return f"""
  <!-- ═══════════════ VERDICT PANEL ═══════════════ -->
  <div style="padding:32px 48px 0;">
    <div style="display:flex;align-items:center;gap:10px;margin-bottom:20px;">
      <div style="width:3px;height:22px;background:{COLORS['gold']};border-radius:2px;"></div>
      <h2 style="font-family:'DM Serif Display',serif;font-size:1.4rem;font-weight:400;
                 color:{COLORS['text_primary']};margin:0;">Bottom-Line Verdict</h2>
      <div style="padding:5px 16px;border-radius:20px;background:{vstyle['badge']};">
        <span style="font-family:'IBM Plex Mono',monospace;font-weight:700;font-size:0.8rem;
                     color:#ffffff;letter-spacing:0.05em;">{verdict_raw.upper()}</span>
      </div>
    </div>
    <div style="background:{vstyle['bg']};border:1px solid {vstyle['border']};
                border-radius:12px;padding:28px 32px;border-left:5px solid {vstyle['border']};">
      {sections_html if sections_html else f'<p style="font-family:\'DM Sans\',sans-serif;font-size:0.85rem;color:{vstyle["text"]};line-height:1.7;">{formatted}</p>'}
    </div>
  </div>"""


def _build_footer(state: AppState, generated_at: str) -> str:
    return f"""
  <!-- ═══════════════ FOOTER ═══════════════ -->
  <div style="padding:32px 48px;margin-top:48px;border-top:1px solid {COLORS['border']};
              background:{COLORS['card_bg']};">
    <div style="display:flex;justify-content:space-between;align-items:flex-start;
                flex-wrap:wrap;gap:16px;">
      <div>
        <div style="font-family:'DM Serif Display',serif;font-size:1rem;
                    color:{COLORS['gold']};margin-bottom:6px;">
          NSE · BSE Risk Scorecard
        </div>
        <p style="font-family:'DM Sans',sans-serif;font-size:0.72rem;
                  color:{COLORS['text_muted']};line-height:1.6;max-width:500px;margin:0;">
          This report is generated by an automated multi-agent financial analysis system.
          It is for informational purposes only and does not constitute investment advice.
          Past performance does not guarantee future results. All data sourced from publicly
          available exchanges and financial data providers. Consult a SEBI-registered
          investment adviser before making any investment decision.
        </p>
      </div>
      <div style="text-align:right;">
        <div style="font-family:'IBM Plex Mono',monospace;font-size:0.72rem;
                    color:{COLORS['text_muted']};">Report generated</div>
        <div style="font-family:'IBM Plex Mono',monospace;font-size:0.78rem;
                    color:{COLORS['text_primary']};font-weight:600;">{generated_at} IST</div>
        <div style="font-family:'IBM Plex Mono',monospace;font-size:0.68rem;
                    color:{COLORS['text_muted']};margin-top:4px;">
          {state.company_name} · {(state.ticker or '').replace('.NS','').replace('.BO','')}
        </div>
      </div>
    </div>
  </div>"""


# =============================================================================
# SECTION 5: PAGE BREAK DIVIDER
# Visible "Page 2" marker for print / PDF rendering.
# =============================================================================

def _page_break_divider() -> str:
    return f"""
  <!-- ═══════════════ PAGE BREAK ═══════════════ -->
  <div style="margin:40px 48px 0;padding:16px 24px;
              background:{COLORS['dark_surface']};border-radius:10px;
              display:flex;align-items:center;gap:12px;">
    <div style="width:2px;height:20px;background:{COLORS['gold']};border-radius:1px;"></div>
    <span style="font-family:'IBM Plex Mono',monospace;font-size:0.72rem;
                 font-weight:700;color:{COLORS['gold']};text-transform:uppercase;
                 letter-spacing:0.15em;">PAGE 2 — DEEP DIVE ANALYSIS</span>
    <div style="flex:1;height:1px;background:#2d2d3a;"></div>
  </div>"""


# =============================================================================
# SECTION 6: FULL HTML ASSEMBLER
# Composes all components into a single self-contained HTML string.
# =============================================================================

def _assemble_html(state: AppState) -> str:
    """
    Assembles the complete HTML report string.

    STRUCTURE:
    ┌────────────────────────────────────────┐
    │  <head> — Fonts, CSS variables, print  │
    ├────────────────────────────────────────┤
    │  PAGE 1                                │
    │    Header (company, ticker, verdict)   │
    │    Metrics Strip (8 KPIs)              │
    │    Gauge + 7-Factor Table              │
    │    Quarterly Financials Table          │
    │    Sector KPI Cards                    │
    ├────────────────────────────────────────┤
    │  PAGE BREAK DIVIDER                    │
    ├────────────────────────────────────────┤
    │  PAGE 2                                │
    │    Hidden Insights (2×2 grid)          │
    │    Catalysts & Risks (2-col)           │
    │    News Breakdown Table                │
    │    Bottom-Line Verdict                 │
    │  Footer                                │
    └────────────────────────────────────────┘
    """
    generated_at = datetime.now(IST).strftime("%d %b %Y, %I:%M %p")

    head = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8"/>
  <meta name="viewport" content="width=device-width, initial-scale=1.0"/>
  <title>{state.company_name} — Risk Scorecard</title>

  <!-- Google Fonts -->
  <link rel="preconnect" href="https://fonts.googleapis.com"/>
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin/>
  <link href="https://fonts.googleapis.com/css2?family=DM+Serif+Display:ital@0;1&family=DM+Sans:ital,opsz,wght@0,9..40,300;0,9..40,400;0,9..40,500;0,9..40,600;0,9..40,700;1,9..40,400&family=IBM+Plex+Mono:ital,wght@0,400;0,500;0,600;0,700;1,400&display=swap" rel="stylesheet"/>

  <style>
    /* ── Reset ── */
    *, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}

    /* ── Design Tokens ── */
    :root {{
      --page-bg:      {COLORS['page_bg']};
      --card-bg:      {COLORS['card_bg']};
      --border:       {COLORS['border']};
      --dark-surface: {COLORS['dark_surface']};
      --gold:         {COLORS['gold']};
      --gold-light:   {COLORS['gold_light']};
      --text-primary: {COLORS['text_primary']};
      --text-secondary:{COLORS['text_secondary']};
      --text-muted:   {COLORS['text_muted']};
      --green:        {COLORS['green']};
      --amber:        {COLORS['amber']};
      --red:          {COLORS['red']};
    }}

    /* ── Base ── */
    html, body {{
      background: #d4d4d8;
      font-family: 'DM Sans', sans-serif;
      color: var(--text-primary);
      min-height: 100vh;
      padding: 32px 16px;
    }}

    /* ── Report Container ── */
    .report-container {{
      max-width: 1200px;
      margin: 0 auto;
      background: var(--page-bg);
      border-radius: 16px;
      overflow: hidden;
      box-shadow: 0 8px 40px rgba(0,0,0,0.18), 0 2px 8px rgba(0,0,0,0.1);
    }}

    /* ── Print ── */
    @media print {{
      body {{ background: white; padding: 0; }}
      .report-container {{
        box-shadow: none;
        border-radius: 0;
        max-width: 100%;
      }}
    }}

    /* ── Responsive ── */
    @media (max-width: 768px) {{
      .report-container {{ border-radius: 8px; }}
    }}

    /* ── Scrollbar Styling ── */
    ::-webkit-scrollbar {{ width: 6px; height: 6px; }}
    ::-webkit-scrollbar-track {{ background: var(--card-bg); }}
    ::-webkit-scrollbar-thumb {{ background: var(--border); border-radius: 3px; }}

    /* ── Link Styling ── */
    a {{ color: var(--gold); }}
    a:hover {{ text-decoration: underline; }}
  </style>
</head>
<body>
<div class="report-container">"""

    body = (
        _build_header(state, generated_at)
        + _build_metrics_strip(state)
        + _build_gauge_and_factors(state)
        + _build_quarterly_table(state)
        + _build_sector_kpis(state)
        + _page_break_divider()
        + _build_hidden_insights(state)
        + _build_catalysts_and_risks(state)
        + _build_news_breakdown(state)
        + _build_verdict_panel(state)
        + _build_footer(state, generated_at)
    )

    tail = "\n</div>\n</body>\n</html>"

    return head + body + tail


# =============================================================================
# SECTION 7: THE MAIN AGENT FUNCTION
# =============================================================================

def run(state: AppState) -> AppState:
    """
    =========================================================================
    Agent 4 — Designer: HTML Report Renderer
    =========================================================================

    ENTRY POINT called by the orchestrator:
        from agents.designer import run
        state = run(state)

    PREREQUISITES:
        Agent 3 (analyst) must have run successfully.
        state.analytical_insights must be populated.

    WHAT IT DOES:
        1. Validates prerequisites
        2. Assembles all HTML components
        3. Writes the complete HTML string to state.html_report
        4. Marks itself complete

    Does ZERO calculations. Reads state, writes HTML. Nothing else.

    Args:
        state (AppState): Fully populated application state.

    Returns:
        AppState: Same state with state.html_report populated.
    """
    agent_name = "designer"

    if state.is_agent_complete(agent_name):
        print(f"\n[Designer] Already complete for '{state.company_name}'. Skipping.")
        return state

    print(f"\n{'='*68}")
    print(f"  AGENT 4 — DESIGNER: {state.company_name} ({state.ticker})")
    print(f"{'='*68}")

    # ── Prerequisite check ────────────────────────────────────────────────
    if not state.is_agent_complete("analyst"):
        err = "Agent 3 (analyst) has not completed. Analytical insights unavailable."
        print(f"[Designer] ❌ {err}")
        state.log_error(agent_name, err)
        return state

    print(f"\n  [Designer] 🎨 Assembling report components...")

    try:
        # ── Compute needle coordinates (logged for transparency) ──────────
        composite_100 = (state.raw_financial_data.extra_data or {}).get("composite_score_100", 50.0)
        PI        = math.pi
        angle_rad = (composite_100 / 100.0) * PI
        cx, cy, r = 160, 155, 115
        tx = cx + r * math.cos(PI - angle_rad)
        ty = cy - r * math.sin(PI - angle_rad)
        print(f"  [Designer] 📐 Gauge needle: score={composite_100:.1f}, "
              f"angle={math.degrees(angle_rad):.1f}°, tip=({tx:.1f},{ty:.1f})")

        # ── Build components ──────────────────────────────────────────────
        print(f"  [Designer] Building: Header...")
        print(f"  [Designer] Building: Metrics Strip...")
        print(f"  [Designer] Building: SVG Risk Gauge...")
        print(f"  [Designer] Building: 7-Factor Table...")
        print(f"  [Designer] Building: Quarterly Financials Table...")
        print(f"  [Designer] Building: Sector KPI Cards...")
        print(f"  [Designer] Building: Hidden Insights Grid...")
        print(f"  [Designer] Building: Catalysts & Risks columns...")
        print(f"  [Designer] Building: News Breakdown Table...")
        print(f"  [Designer] Building: Bottom-Line Verdict Panel...")
        print(f"  [Designer] Building: Footer...")

        html = _assemble_html(state)

        print(f"  [Designer] ✅ HTML assembled: {len(html):,} characters")

    except Exception as exc:
        err = f"HTML assembly failed: {type(exc).__name__}: {exc}"
        print(f"  [Designer] ❌ {err}")
        state.log_error(agent_name, err)
        import traceback; traceback.print_exc()
        return state

    # ── Write to state ────────────────────────────────────────────────────
    state.html_report = html
    state.mark_agent_complete(agent_name)

    print(f"\n{'='*68}")
    print(f"  DESIGNER COMPLETE")
    print(f"{'='*68}")
    print(f"  Company     : {state.company_name}")
    print(f"  Verdict     : {(state.raw_financial_data.extra_data or {}).get('verdict', 'N/A')}")
    print(f"  Score       : {composite_100:.1f}/100")
    print(f"  HTML length : {len(html):,} chars")
    print(f"  All agents  : {state.completed_agents}")
    print(f"{'='*68}\n")

    return state


# =============================================================================
# SECTION 8: STANDALONE TEST HARNESS + FILE SAVER
# Run directly: $ python agents/designer.py
# Saves the generated HTML to: output_report.html
# =============================================================================

if __name__ == "__main__":
    from state import (AppState, AnalyticalInsights, FactorScore,
                       QuarterlyFinancials, RawFinancialData, SectorKPI)

    print("\n" + "=" * 68)
    print("  AGENT 4 — DESIGNER : STANDALONE TEST")
    print("=" * 68)

    # ── Simulate a fully-populated state ─────────────────────────────────
    s = AppState(company_name="HDFC Bank")
    s.ticker = "HDFCBANK.NS"
    s.sector = "Banks/NBFCs"
    s.sector_kpis = [
        SectorKPI(name="Net Interest Margin (NIM)", value=4.1, unit="%",
                  description="Spread between lending and borrowing rates."),
        SectorKPI(name="Gross NPA Ratio", value=1.26, unit="%",
                  description="Percentage of non-performing loans. Lower is better."),
    ]
    s.mark_agent_complete("router")

    rfd = s.raw_financial_data
    rfd.cmp            = 1723.45
    rfd.week_52_high   = 1880.00
    rfd.week_52_low    = 1363.55
    rfd.pe_ratio       = 19.8
    rfd.pb_ratio       = 2.9
    rfd.roe            = 17.2
    rfd.dividend_yield = 1.1
    rfd.promoter_pledge_pct = 0.0
    rfd.quarterly_financials = [
        QuarterlyFinancials(quarter_label="Q4 FY2025", revenue_cr=89450.0, pat_cr=17622.0, ebitda_cr=None, eps=22.98),
        QuarterlyFinancials(quarter_label="Q3 FY2025", revenue_cr=85200.0, pat_cr=16736.0, ebitda_cr=None, eps=21.83),
        QuarterlyFinancials(quarter_label="Q2 FY2025", revenue_cr=80100.0, pat_cr=15976.0, ebitda_cr=None, eps=20.85),
        QuarterlyFinancials(quarter_label="Q1 FY2025", revenue_cr=76300.0, pat_cr=11951.0, ebitda_cr=None, eps=15.60),
    ]
    rfd.extra_data = {
        "market_cap_cr":        "1319200",
        "promoter_holding_pct": "26.2",
        "composite_score_100":  67.4,
        "verdict":              "Buy",
        "factor_scores_100": {
            "valuation":    58.0, "earnings": 72.0, "balance_sheet": 68.0,
            "growth":       75.0, "governance": 100.0, "sector": 42.0, "technical": 55.0,
        },
        "all_catalysts": [
            "P/E compression to 15x sector fair-value driven by 2 consecutive earnings beats could unlock 20% price appreciation.",
            "Revenue reaccelerating above 15% QoQ — crossing ₹102,867Cr next quarter — would confirm demand inflection.",
            "Promoter stake increase via open-market purchases would send a strong conviction signal.",
            "RBI rate cut of 25–50bps would expand NIM by 8–15bps, adding directly to net interest income.",
            "A sustained close above ₹1,917 (2% above 52W high) would trigger momentum-based buying.",
            "ROE expansion from 17.2% to 22% through asset sweating implies ₹258–₹430/share of additional value.",
            "Dividend increase of ₹34–₹86/share would attract yield-seeking institutional investors.",
            "Regulatory clarity on credit card regulations would unlock the 15–20% sentiment discount vs sector peers.",
        ],
        "all_risks": [
            "P/E mean-reversion to 15x sector fair-value could cause a 24% price decline to ₹1,309 on a single earnings miss.",
            "A 15% PAT decline to ₹14,978Cr would push trailing P/E above 25x, triggering institutional sell mandates.",
            "Zero pledge is ideal; any future promoter borrowing disclosure would immediately impact sentiment.",
            "A gross NPA spike of 50–100bps above current 1.26% would trigger provisioning that could halve PAT.",
            "A decisive close below ₹1,322 (3% below 52W low) would trigger stop-loss cascade selling.",
            "RBI holding rates elevated above 6.5% through CY2026 would compress NIM by 10–20bps.",
            "High promoter concentration creates liquidity risk; block deal by FII could move price 3–5% intraday.",
            "10% downward EPS revision implies a fair value of ₹1,291 — representing ₹432 downside from current levels.",
        ],
        "hidden_insights": [
            "HDFC Bank's Q1 FY2025 PAT of ₹11,951Cr was significantly depressed by merger integration provisioning — the apparent 47% QoQ jump to Q2 FY2025 (₹15,976Cr) is a base-effect recovery, not a structural earnings acceleration. The Coefficient of Variation of 16.3% sits just above the 15% comfort threshold.",
            "Zero promoter pledge is a genuine governance premium. Institutionally-managed governance screens (MSCI ESG, Nifty Quality 30) over-weight zero-pledge companies, providing a systematic demand floor. Any future pledge disclosure would trigger automatic deletion from these indices — an event-driven risk that is not priced in.",
            "HDFC Bank's PEG ratio of 0.85x (P/E 19.8x ÷ YoY revenue growth 17.2%) sits in the attractive band below 1.0x. The market is modestly under-pricing the compounding quality of this growth — a classic condition seen before institutional re-rating events.",
            "At 59% of its 52-week range with the Banks/NBFCs sector carrying a structural risk baseline of 42/100, HDFC Bank's primary macro trigger is an RBI rate cut cycle. A 50bps cut compresses NIM by approximately 12bps but re-rates P/B by 0.3–0.5x — the market historically prices the re-rating before the NIM pressure is visible in results.",
        ],
    }
    rfd.news_headlines = [
        {"date": "2025-05-10", "headline": "HDFC Bank posts record quarterly profit beating estimates", "source": "Economic Times", "url": ""},
        {"date": "2025-05-08", "headline": "HDFC Bank credit rating upgrade from CRISIL for long-term debt", "source": "Mint", "url": ""},
        {"date": "2025-04-28", "headline": "HDFC Bank announces ₹19.50 dividend for FY2025", "source": "Business Standard", "url": ""},
        {"date": "2025-04-22", "headline": "HDFC Bank net NPA falls to multi-year low of 0.33%", "source": "NDTV Profit", "url": ""},
        {"date": "2025-04-15", "headline": "RBI regulatory probe into HDFC Bank credit card practices", "source": "Moneycontrol", "url": ""},
    ]
    s.mark_agent_complete("extractor")

    ai = s.analytical_insights
    def _fs(name, dname, sc, rat):
        return FactorScore(factor_name=name, display_name=dname, score=sc, rationale=rat,
                           catalysts=[], risks=[])

    ai.valuation        = _fs("valuation",  "Valuation Risk",        6, "P/E of 19.8x trades at a slight premium to the 15x sector fair-value for Banks/NBFCs; composite valuation score 58/100 = (PE 54×60%) + (PB 63×40%).")
    ai.earnings_quality = _fs("earnings",   "Earnings Quality",      7, "PAT CV of 16.3% across 4 quarters — just above the 15% comfort threshold; EPS positive in 3/3 QoQ transitions; score 72/100.")
    ai.macro_sensitivity= _fs("bs",         "Balance Sheet",         7, "ROE of 17.2% in the healthy 15–25% band; dividend yield 1.1% signals FCF; implied P/B analysis suggests moderate leverage; score 68/100.")
    ai.momentum         = _fs("growth",     "Growth Momentum",       8, "Revenue QoQ +5.0% with PAT QoQ +5.3%; YoY revenue growth +17.2%; positive operating leverage signal; score 75/100.")
    ai.promoter_pledging= _fs("governance", "Mgmt & Governance",    10, "Zero promoter pledge (score 100/100); promoter holding of 26.2% in moderate range; governance premium well-deserved.")
    ai.sector_kpi_score = _fs("sector",     "Sector Risk",           4, "Banks/NBFCs structural risk score 42/100; key risks: credit cycle, NPA formation, RBI rate sensitivity.")
    ai.sentiment        = _fs("technical",  "Technical & Sentiment", 6, "CMP ₹1,723 is 59% through 52W range; 3 positive vs 1 negative news signals; composite technical score 55/100.")
    ai.composite_score  = 6.7
    ai.risk_band        = "MODERATE RISK"
    ai.final_verdict_text = """━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
BOTTOM-LINE VERDICT: BUY
Composite Risk Score: 67.4/100 | Risk Band: MODERATE RISK
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

ASSESSMENT SUMMARY — HDFC Bank (Banks/NBFCs)

HDFC Bank receives a composite risk score of 67.4/100, translating to a 'Buy' rating. The score reflects a weighted assessment across 7 financial risk dimensions calibrated to Banks/NBFCs sector norms.

STRENGTHS:
  ✓ Management & Governance: Scored 100/100 — primary analytical support for the rating.
  ✓ Growth Momentum: Scored 75/100 — secondary support factor.

WEAKNESSES:
  ✗ Sector Risk: Scored 42/100 — primary risk factor limiting the rating.
  ✗ Valuation: Scored 58/100 — secondary drag on the assessment.

UPGRADE CONDITIONS (rating improves if ALL met):
  1. P/E contracts below 15x (current: 19.8x) due to earnings growth outpacing price.
  2. Stock price sustains above ₹1,880 (52W high) for 10+ consecutive trading sessions.
  3. A positive sector macro event (RBI rate cut) that upgrades sector risk score above 65/100.

DOWNGRADE CONDITIONS (rating worsens if ANY triggered):
  1. Any single quarter where PAT declines >20% QoQ on an operational basis.
  2. Stock price closing below ₹1,295 (5% below 52W low) on above-average volume.
  3. Promoter pledge exceeding 30% or any SEBI/ED regulatory action.

─────────────────────────────────────────────────────────
DISCLAIMER: This is a quantitative risk assessment model output, not personalised investment advice."""
    s.mark_agent_complete("analyst")

    # ── Run designer ──────────────────────────────────────────────────────
    result = run(s)

    # ── Save HTML ─────────────────────────────────────────────────────────
    output_path = _PROJECT_ROOT / "output_report.html"
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(result.html_report)

    print(f"\n✅ Report saved to: {output_path}")
    print(f"   Open in browser: file://{output_path}")