# =============================================================================
# state.py
# Centralized State Object — Multi-Agent Financial Risk Scorecard
# Indian Stocks (NSE / BSE)
# =============================================================================
#
# WHAT IS THIS FILE?
# ------------------
# Think of this file as the "shared whiteboard" for all our AI agents.
# Every agent in the system — whether it fetches stock prices, scrapes news,
# calculates risk scores, or generates the final HTML report — reads from
# and writes to ONE single object defined here: AppState.
#
# WHY ONE CENTRAL STATE OBJECT?
# ------------------------------
# In a multi-agent system, agents run sequentially (or in parallel).
# Without a single shared state:
#   - Agent A might store revenue data in a "revenue" key.
#   - Agent B might look for it under "revenues" — and crash.
# By enforcing a strict schema here with Pydantic, every agent speaks
# the same language. Data shape mismatches are caught INSTANTLY with a
# clear error message, not silently corrupted.
#
# HOW PYDANTIC HELPS (non-technical summary):
# --------------------------------------------
# Pydantic is like a "data bouncer". You define the rules once (e.g.,
# "ticker must be a string", "roe must be a float or None").
# Every time data is written into AppState, Pydantic checks it against
# the rules. Wrong type? It either converts it automatically or raises
# a descriptive error. This prevents a whole class of subtle bugs.
#
# =============================================================================

from __future__ import annotations  # Allows forward references in type hints

from datetime import datetime
from typing import Any, Dict, List, Optional

import pytz
from pydantic import BaseModel, Field, field_validator

# Indian Standard Time — used for all timestamps in this system
IST = pytz.timezone("Asia/Kolkata")


# =============================================================================
# SECTION 1: SUB-MODELS
# Small, focused data containers that compose into the main AppState.
# Keeping them separate makes each piece independently understandable.
# =============================================================================


class QuarterlyFinancials(BaseModel):
    """
    Stores the key financial figures for ONE fiscal quarter.

    WHY 4 QUARTERS?
    Indian listed companies report results quarterly. To spot trends
    (e.g., "revenue is declining for 3 quarters in a row"), we need at
    least 4 data points. This covers one full fiscal year.

    FIELD NAMING CONVENTION:
    All monetary values are in Indian Rupees (INR), specifically in
    Crores (1 Crore = 10 Million). EPS is in INR per share.

    Example usage:
        q = QuarterlyFinancials(
            quarter_label="Q4 FY2025",
            revenue_cr=45230.5,
            pat_cr=8912.3,
            ebitda_cr=12400.0,
            eps=23.45
        )
    """

    # Human-readable label for the quarter, e.g. "Q1 FY2024", "Q2 FY2024"
    quarter_label: str = Field(
        ...,
        description="Human-readable quarter identifier, e.g. 'Q4 FY2025'.",
    )

    # Revenue = Total income from operations (top line of the P&L statement)
    # Stored in Crores (₹ Cr). None if data is unavailable.
    revenue_cr: Optional[float] = Field(
        default=None,
        description="Total Revenue / Net Sales for this quarter, in INR Crores.",
    )

    # PAT = Profit After Tax (the "bottom line" — what the company actually earned)
    # A negative PAT means the company made a loss that quarter.
    pat_cr: Optional[float] = Field(
        default=None,
        description="Profit After Tax (net profit) for this quarter, in INR Crores.",
    )

    # EBITDA = Earnings Before Interest, Taxes, Depreciation & Amortisation
    # A measure of core operational profitability, before financing costs.
    ebitda_cr: Optional[float] = Field(
        default=None,
        description=(
            "EBITDA for this quarter in INR Crores. "
            "Proxy for operational cash generation ability."
        ),
    )

    # EPS = Earnings Per Share (PAT divided by total shares outstanding)
    # This is what each shareholder "earned" per share they hold.
    eps: Optional[float] = Field(
        default=None,
        description="Earnings Per Share for this quarter, in INR per share.",
    )


class SectorKPI(BaseModel):
    """
    Represents ONE sector-specific Key Performance Indicator.

    WHY SECTOR KPIs?
    A software company and a bank have completely different risk drivers.
    For a bank, Net Interest Margin (NIM) matters enormously.
    For a software company, Revenue Per Employee does.
    Comparing them on the same metrics would be misleading.

    Each sector gets exactly 2 unique KPIs that our sector-detection
    agent identifies and populates. This keeps the scorecard contextually
    relevant without being overwhelming.

    Example:
        kpi = SectorKPI(
            name="Net Interest Margin (NIM)",
            value=3.42,
            unit="%",
            description="Measures bank profitability on its lending vs. borrowing rates."
        )
    """

    # Short, human-readable name for the KPI
    name: str = Field(
        ...,
        description="Short display name of the KPI, e.g. 'Net Interest Margin (NIM)'.",
    )

    # The actual numeric value fetched or calculated by the data agent
    value: Optional[float] = Field(
        default=None,
        description="The numeric value of the KPI. None if data could not be fetched.",
    )

    # The unit makes the number meaningful ("%" vs "x" vs "₹" are very different!)
    unit: Optional[str] = Field(
        default=None,
        description="Unit of the KPI value, e.g. '%', 'x', '₹ Cr', 'days'.",
    )

    # Plain-English explanation of what this KPI tells us about risk
    description: Optional[str] = Field(
        default=None,
        description="One-sentence explanation of why this KPI matters for this sector.",
    )


class FactorScore(BaseModel):
    """
    Stores the risk assessment for ONE of the 7 scoring factors.

    HOW SCORING WORKS:
    Each factor gets a score from 1 (very high risk) to 10 (very low risk).
    The 7 factors together build up to the final verdict.

    Think of this like a doctor's assessment: each vital sign gets a rating,
    a note on what it means, and flags for anything unusual.

    The 7 factors are defined in AppState.analytical_insights below.
    """

    # Factor identifier, e.g. "valuation", "earnings_quality", "promoter_pledging"
    factor_name: str = Field(
        ...,
        description="Machine-readable identifier for this risk factor.",
    )

    # Human-readable display name, e.g. "Valuation Risk", "Earnings Quality"
    display_name: str = Field(
        ...,
        description="Display label shown in the final HTML report.",
    )

    # The score: 1 = Extreme Risk, 10 = Very Safe. We use 1–10 (not 0–100)
    # to keep it human-interpretable at a glance.
    score: Optional[int] = Field(
        default=None,
        ge=1,    # ge = greater than or equal to 1
        le=10,   # le = less than or equal to 10
        description=(
            "Risk score for this factor. "
            "1 = Extreme Risk / Red Flag, 10 = Very Safe / Green Flag."
        ),
    )

    # The "why" behind the score — written in plain English by the LLM agent
    rationale: Optional[str] = Field(
        default=None,
        description=(
            "Plain-English explanation of why this score was assigned. "
            "Should be 2–4 sentences, non-jargon where possible."
        ),
    )

    # Non-obvious insight that a typical retail investor would miss
    hidden_insight: Optional[str] = Field(
        default=None,
        description=(
            "A subtle or non-obvious finding for this factor that goes beyond "
            "the headline number. E.g., 'P/E looks cheap vs peers but EPS includes "
            "a one-time asset sale gain.'"
        ),
    )

    # Things that could IMPROVE this factor's score in the near future
    catalysts: Optional[List[str]] = Field(
        default=None,
        description=(
            "Upcoming events or trends that could IMPROVE the risk score for "
            "this factor. E.g., ['New product launch in Q2', 'Debt repayment due']."
        ),
    )

    # Things that could WORSEN this factor's score
    risks: Optional[List[str]] = Field(
        default=None,
        description=(
            "Specific threats that could WORSEN the risk score for this factor. "
            "E.g., ['Rising raw material costs', 'Regulatory scrutiny']."
        ),
    )

    @field_validator("score", mode="before")
    @classmethod
    def clamp_score(cls, v: Any) -> Optional[int]:
        """
        Safety net: if an agent accidentally returns a score of 11 or 0,
        clamp it to the valid 1–10 range instead of crashing.
        """
        if v is None:
            return None
        v = int(v)
        return max(1, min(10, v))


# =============================================================================
# SECTION 2: RAW FINANCIAL DATA CONTAINER
# Everything an agent needs to *fetch* before analysis can begin.
# =============================================================================


class RawFinancialData(BaseModel):
    """
    The "raw data locker" — all financial data points fetched from external
    sources (Yahoo Finance, NSE website, news scrapers) BEFORE any analysis.

    DATA FLOW:
        Data Fetching Agents → populate RawFinancialData
        Analytical Agents   → read RawFinancialData to generate FactorScores

    WHY SEPARATE RAW FROM ANALYTICAL?
    Keeping raw data separate from insights means:
    1. We can re-run ONLY the analysis agents if we want to change scoring logic,
       without re-fetching all the data (which is slow and hits rate limits).
    2. It's easy to audit: "what data did the agent actually see?"
    3. Debugging is simpler — if a score looks wrong, check raw data first.
    """

    # -------------------------------------------------------------------------
    # MARKET DATA (Point-in-time snapshot from Yahoo Finance / NSE)
    # -------------------------------------------------------------------------

    # CMP = Current Market Price (the live or last-traded price of the stock)
    cmp: Optional[float] = Field(
        default=None,
        description="Current Market Price of the stock in INR. Fetched from yfinance.",
    )

    # The highest price the stock touched in the last 52 weeks
    week_52_high: Optional[float] = Field(
        default=None,
        description="52-week high price in INR. Used to gauge how far stock is from peak.",
    )

    # The lowest price the stock touched in the last 52 weeks
    week_52_low: Optional[float] = Field(
        default=None,
        description="52-week low price in INR. Used to gauge downside already absorbed.",
    )

    # -------------------------------------------------------------------------
    # VALUATION RATIOS (How expensive/cheap is the stock vs earnings/book value?)
    # -------------------------------------------------------------------------

    # P/E Ratio = Price ÷ Earnings Per Share
    # High P/E = market expects high future growth (or stock is overpriced)
    # Low P/E  = market expects low growth (or stock is undervalued)
    # Always compare P/E vs the sector average, NOT in isolation.
    pe_ratio: Optional[float] = Field(
        default=None,
        description=(
            "Price-to-Earnings ratio (TTM). "
            "High = expensive or high-growth expectations. "
            "Compare vs sector median, not in isolation."
        ),
    )

    # P/B Ratio = Price ÷ Book Value Per Share
    # Book value = what shareholders would theoretically get if the company
    # liquidated all assets and paid all debts today.
    # Banks and asset-heavy companies are best evaluated on P/B.
    pb_ratio: Optional[float] = Field(
        default=None,
        description=(
            "Price-to-Book ratio. "
            "Particularly relevant for asset-heavy sectors like Banking, Metals, Infra."
        ),
    )

    # -------------------------------------------------------------------------
    # PROFITABILITY & RETURNS
    # -------------------------------------------------------------------------

    # ROE = Return on Equity = Net Profit ÷ Shareholders' Equity
    # Tells us how efficiently the company uses shareholder money to generate profit.
    # An ROE above 15% is generally considered healthy in the Indian market.
    roe: Optional[float] = Field(
        default=None,
        description=(
            "Return on Equity in %. "
            "Measures how efficiently management generates profit from shareholders' funds. "
            "Benchmark: >15% is generally healthy for Indian large-caps."
        ),
    )

    # Dividend Yield = Annual Dividend Per Share ÷ CMP × 100
    # A steady dividend signals financial health and management confidence.
    # Very high yield (>8%) can sometimes signal the stock price has crashed.
    dividend_yield: Optional[float] = Field(
        default=None,
        description=(
            "Trailing twelve-month dividend yield in %. "
            "A consistent dividend is a positive sign; an unusually high yield may "
            "signal a price crash."
        ),
    )

    # -------------------------------------------------------------------------
    # QUARTERLY FINANCIALS (Last 4 quarters for trend analysis)
    # -------------------------------------------------------------------------
    # Ordered from MOST RECENT to OLDEST: [Q4, Q3, Q2, Q1]
    # Having 4 quarters lets us detect trends: improving, declining, or volatile.
    quarterly_financials: List[QuarterlyFinancials] = Field(
        default_factory=list,
        max_length=4,
        description=(
            "List of the last 4 quarters of financial data, most recent first. "
            "Each entry has Revenue, PAT, EBITDA, and EPS. "
            "Used for trend detection in the earnings quality and growth risk factors."
        ),
    )

    # -------------------------------------------------------------------------
    # GOVERNANCE & RISK SIGNALS
    # -------------------------------------------------------------------------

    # Promoter Pledge % = what percentage of promoters' shareholding is pledged
    # as collateral for loans. HIGH pledge % is a RED FLAG because:
    # - If the stock price falls, lenders may sell pledged shares → price crash
    # - It suggests promoters needed cash urgently (financial stress signal)
    # - Threshold: >30% is generally considered high-risk in Indian markets
    promoter_pledge_pct: Optional[float] = Field(
        default=None,
        description=(
            "Percentage of promoter shareholding that is pledged as loan collateral. "
            "Source: BSE/NSE shareholding pattern disclosures. "
            "Risk threshold: >10% warrants attention, >30% is a serious red flag."
        ),
    )

    # -------------------------------------------------------------------------
    # NEWS & SENTIMENT DATA
    # -------------------------------------------------------------------------

    # Last 60 days of news headlines about this company.
    # Each item in the list is a dict with keys: "date", "headline", "source", "url"
    # The sentiment/news analysis agent will parse these to score reputational risk.
    news_headlines: List[Dict[str, str]] = Field(
        default_factory=list,
        description=(
            "List of news headline dicts from the last 60 days. "
            "Each dict has keys: 'date' (YYYY-MM-DD), 'headline' (str), "
            "'source' (str, e.g. 'Economic Times'), 'url' (str). "
            "Used by the sentiment agent to score reputational and event risk."
        ),
    )

    # Any additional raw data a specialized agent fetches that doesn't fit
    # the above fields (e.g., order book data, credit ratings, FII/DII flows).
    # Using Dict[str, Any] gives us flexibility without breaking the schema.
    extra_data: Dict[str, Any] = Field(
        default_factory=dict,
        description=(
            "Catch-all dictionary for any supplementary raw data fetched by agents "
            "that doesn't have a dedicated field above. "
            "E.g., {'credit_rating': 'AA+', 'fii_holding_pct': 18.3}."
        ),
    )


# =============================================================================
# SECTION 3: ANALYTICAL INSIGHTS CONTAINER
# Everything an agent needs to *produce* after analysing the raw data.
# =============================================================================


class AnalyticalInsights(BaseModel):
    """
    The "intelligence layer" — all scored, interpreted, and synthesised outputs
    produced by the analytical agents AFTER reading RawFinancialData.

    THE 7 RISK FACTORS:
    -------------------
    1. valuation         → Is the stock overpriced or fairly valued?
    2. earnings_quality  → Is profit growth real, consistent, and sustainable?
    3. promoter_pledging → Are insiders financially stressed (governance risk)?
    4. momentum          → Is the stock in a technical uptrend or downtrend?
    5. sentiment         → What is the news/media saying about the company?
    6. sector_kpi        → How does the company score on its sector's unique metrics?
    7. macro_sensitivity → How exposed is the company to RBI rates, INR, global cycles?

    FINAL VERDICT:
    --------------
    A weighted average of all 7 scores, translated into a plain-English
    investment risk summary (not a buy/sell recommendation — just risk framing).
    """

    # -------------------------------------------------------------------------
    # THE 7 FACTOR SCORES
    # Each is a FactorScore object (score + rationale + hidden insight + catalysts/risks)
    # -------------------------------------------------------------------------

    # Factor 1: VALUATION RISK
    # Is the stock overpriced relative to its earnings, book value, and peers?
    valuation: Optional[FactorScore] = Field(
        default=None,
        description=(
            "FACTOR 1 — Valuation Risk. "
            "Scores how expensive or cheap the stock is relative to fundamentals "
            "and sector peers. Uses P/E, P/B, and 52W price position. "
            "Score 1 = dangerously overvalued, Score 10 = attractively undervalued."
        ),
    )

    # Factor 2: EARNINGS QUALITY
    # Is PAT growth driven by real operations or accounting tricks/one-offs?
    earnings_quality: Optional[FactorScore] = Field(
        default=None,
        description=(
            "FACTOR 2 — Earnings Quality Risk. "
            "Assesses whether revenue and profit growth is consistent across 4 quarters, "
            "and flags one-time items (asset sales, write-backs) inflating PAT. "
            "Score 1 = erratic/suspicious earnings, Score 10 = consistent real growth."
        ),
    )

    # Factor 3: PROMOTER PLEDGING
    # High pledge % means promoters may be financially stressed — a governance red flag.
    promoter_pledging: Optional[FactorScore] = Field(
        default=None,
        description=(
            "FACTOR 3 — Promoter Pledging Risk. "
            "Evaluates the % of promoter shares pledged as collateral. "
            "High pledging creates forced-selling risk if the stock price falls. "
            "Score 1 = >50% pledged (extreme risk), Score 10 = 0% pledged (no risk)."
        ),
    )

    # Factor 4: PRICE MOMENTUM
    # Technical analysis: is the stock trending up or down relative to its 52W range?
    momentum: Optional[FactorScore] = Field(
        default=None,
        description=(
            "FACTOR 4 — Price Momentum Risk. "
            "Uses CMP position within the 52-week high/low range to assess "
            "whether the stock is in a bullish or bearish trend. "
            "Score 1 = near 52W high + falling trend (distribution phase), "
            "Score 10 = recovering from 52W lows with improving fundamentals."
        ),
    )

    # Factor 5: NEWS SENTIMENT
    # Reputational and event-driven risk based on 60-day news headline analysis.
    sentiment: Optional[FactorScore] = Field(
        default=None,
        description=(
            "FACTOR 5 — News Sentiment Risk. "
            "Analyses the last 60 days of news headlines for positive/negative tone, "
            "regulatory actions, litigation, management changes, and macro events. "
            "Score 1 = strongly negative news flow, Score 10 = very positive/quiet news."
        ),
    )

    # Factor 6: SECTOR KPI PERFORMANCE
    # How does the company score on the 2 unique KPIs identified for its sector?
    sector_kpi_score: Optional[FactorScore] = Field(
        default=None,
        description=(
            "FACTOR 6 — Sector-Specific KPI Risk. "
            "Scores the company against the 2 sector KPIs in state.sector_kpis. "
            "Example for Banking: NIM and Gross NPA %. "
            "Score 1 = KPIs significantly below sector benchmarks, "
            "Score 10 = KPIs best-in-class."
        ),
    )

    # Factor 7: MACRO SENSITIVITY
    # How much will this company be hurt if RBI raises rates, INR depreciates,
    # or global commodity prices spike?
    macro_sensitivity: Optional[FactorScore] = Field(
        default=None,
        description=(
            "FACTOR 7 — Macro Sensitivity Risk. "
            "Assesses how exposed the business model is to: "
            "RBI interest rate changes, INR/USD movements, global commodity cycles, "
            "and FII flow reversals. "
            "Score 1 = extremely sensitive (e.g., high-debt, import-dependent), "
            "Score 10 = largely insulated (e.g., domestic consumption, zero debt)."
        ),
    )

    # -------------------------------------------------------------------------
    # COMPOSITE SCORE & FINAL VERDICT
    # -------------------------------------------------------------------------

    # Simple weighted average of all 7 factor scores (weights defined in scoring agent)
    # Range: 1.0 (Extreme Risk) to 10.0 (Very Low Risk)
    composite_score: Optional[float] = Field(
        default=None,
        ge=1.0,
        le=10.0,
        description=(
            "Weighted average of all 7 factor scores. "
            "1.0–3.9 = High Risk, 4.0–6.9 = Moderate Risk, 7.0–10.0 = Low Risk."
        ),
    )

    # The risk band converts the composite score into an easy category label
    # Values: "HIGH RISK", "MODERATE RISK", "LOW RISK"
    risk_band: Optional[str] = Field(
        default=None,
        description=(
            "Human-readable risk band derived from composite_score. "
            "One of: 'HIGH RISK', 'MODERATE RISK', 'LOW RISK'."
        ),
    )

    # A 3–5 paragraph plain-English verdict written by the LLM agent.
    # This is the "so what" summary that a PM or non-finance stakeholder can read.
    # IMPORTANT: This is a RISK ASSESSMENT, not a buy/sell recommendation.
    final_verdict_text: Optional[str] = Field(
        default=None,
        description=(
            "Plain-English final verdict narrative generated by the LLM agent. "
            "Covers: overall risk posture, 2–3 key risks, 1–2 key catalysts, "
            "and a contextual framing for an Indian retail investor. "
            "NOT a buy/sell recommendation."
        ),
    )

    # Timestamp of when the analysis was completed (IST)
    analysis_timestamp: Optional[datetime] = Field(
        default=None,
        description="UTC datetime when the analysis was completed. Stored in IST context.",
    )


# =============================================================================
# SECTION 4: THE MAIN APP STATE (Single Source of Truth)
# =============================================================================


class AppState(BaseModel):
    """
    =========================================================================
    AppState — The Central "Shared Whiteboard" for All Agents
    =========================================================================

    LIFECYCLE OF AN AppState OBJECT:
    ---------------------------------
    1. CREATED: User inputs a company name → AppState is instantiated with
               only company_name filled in. Everything else is None.

    2. AGENT 1 (Ticker Resolver):
               Reads  → company_name
               Writes → ticker, sector

    3. AGENT 2 (Sector KPI Selector):
               Reads  → sector
               Writes → sector_kpis

    4. AGENT 3 (Data Fetcher):
               Reads  → ticker, sector
               Writes → raw_financial_data

    5. AGENT 4–10 (Risk Scorers, one per factor):
               Reads  → raw_financial_data, sector_kpis
               Writes → analytical_insights.valuation, .earnings_quality, etc.

    6. AGENT 11 (Verdict Writer):
               Reads  → analytical_insights (all 7 scores)
               Writes → analytical_insights.composite_score, .risk_band,
                        .final_verdict_text

    7. AGENT 12 (Report Generator):
               Reads  → ALL fields in AppState
               Writes → html_report

    SERIALISATION:
    --------------
    The full AppState can be serialised to JSON at any point:
        state_dict = app_state.model_dump()   # Python dict
        state_json = app_state.model_dump_json(indent=2)  # JSON string

    This lets you save intermediate progress, resume after a crash,
    or log the full state for debugging.

    EXAMPLE INSTANTIATION (Agent Orchestrator):
        state = AppState(company_name="Reliance Industries")
        # ... agents run and populate fields ...
        print(state.analytical_insights.composite_score)
    =========================================================================
    """

    # -------------------------------------------------------------------------
    # INPUT (Provided by the user / orchestrator)
    # -------------------------------------------------------------------------

    # The raw company name as typed by the user. Can be messy:
    # "reliance", "Reliance Industries Ltd", "RIL" — the ticker resolver agent
    # figures out the correct NSE/BSE symbol from this.
    company_name: str = Field(
        ...,
        min_length=1,
        description=(
            "Raw company name input by the user. "
            "The Ticker Resolver Agent will normalise this to find the correct ticker. "
            "Examples: 'Reliance', 'HDFC Bank', 'Infosys Ltd', 'TCS'."
        ),
    )

    # -------------------------------------------------------------------------
    # RESOLVED METADATA (Populated by Ticker Resolver + Sector Detection Agents)
    # -------------------------------------------------------------------------

    # The exchange-specific ticker symbol.
    # NSE tickers end in ".NS" (e.g., "RELIANCE.NS")
    # BSE tickers end in ".BO" (e.g., "500325.BO")
    # yfinance uses these suffixes to route to the correct exchange.
    ticker: Optional[str] = Field(
        default=None,
        description=(
            "Resolved NSE or BSE ticker symbol as used by yfinance. "
            "NSE format: 'SYMBOL.NS' (e.g., 'RELIANCE.NS'). "
            "BSE format: 'SCRIPCODE.BO' (e.g., '500325.BO'). "
            "Populated by the Ticker Resolver Agent."
        ),
    )

    # The GICS/NSE sector the company belongs to.
    # Examples: "Banking & Financial Services", "Information Technology",
    #           "Pharmaceuticals", "FMCG", "Oil & Gas", "Metals & Mining"
    # This drives which 2 KPIs are selected in sector_kpis.
    sector: Optional[str] = Field(
        default=None,
        description=(
            "Auto-detected sector for the company. "
            "Used to select the appropriate sector_kpis and contextualise scoring. "
            "Examples: 'Banking', 'IT Services', 'FMCG', 'Pharmaceuticals', "
            "'Metals & Mining', 'Oil & Gas', 'Real Estate', 'Automobiles'."
        ),
    )

    # -------------------------------------------------------------------------
    # SECTOR KPIs (Populated by Sector KPI Selector Agent)
    # -------------------------------------------------------------------------

    # Exactly 2 SectorKPI objects, specific to this company's sector.
    # The Sector KPI Selector Agent picks the 2 most relevant KPIs from a
    # predefined library of sector-specific metrics.
    sector_kpis: List[SectorKPI] = Field(
        default_factory=list,
        max_length=2,
        description=(
            "List of exactly 2 sector-specific KPIs selected for this company's sector. "
            "Examples for Banking: [NIM %, Gross NPA %]. "
            "Examples for IT: [Revenue per Employee, EBIT Margin %]. "
            "Examples for FMCG: [Volume Growth %, Distribution Reach]. "
            "Populated by the Sector KPI Selector Agent."
        ),
    )

    # -------------------------------------------------------------------------
    # RAW FINANCIAL DATA (Populated by Data Fetcher Agent)
    # -------------------------------------------------------------------------

    # All raw data points fetched from external sources.
    # See the RawFinancialData class above for full field documentation.
    raw_financial_data: RawFinancialData = Field(
        default_factory=RawFinancialData,
        description=(
            "All raw financial data points fetched from Yahoo Finance, NSE, "
            "and news scrapers. Populated by the Data Fetcher Agent BEFORE analysis. "
            "Contains: CMP, 52W range, P/E, P/B, ROE, Dividend Yield, "
            "4 quarters of financials, promoter pledge %, and news headlines."
        ),
    )

    # -------------------------------------------------------------------------
    # ANALYTICAL INSIGHTS (Populated by Risk Scoring + Verdict Agents)
    # -------------------------------------------------------------------------

    # All scored outputs from the analytical agents.
    # See the AnalyticalInsights class above for full field documentation.
    analytical_insights: AnalyticalInsights = Field(
        default_factory=AnalyticalInsights,
        description=(
            "All analytical outputs generated by the risk scoring agents. "
            "Contains: 7 factor scores (each with rationale, hidden insight, "
            "catalysts, risks), composite score, risk band, and final verdict text. "
            "Populated by the Scoring Agents and Verdict Writer Agent."
        ),
    )

    # -------------------------------------------------------------------------
    # FINAL OUTPUT (Populated by Report Generator Agent)
    # -------------------------------------------------------------------------

    # The complete HTML string of the final report, ready to be saved as .html
    # and opened in a browser. Includes all charts, tables, and narrative text.
    html_report: Optional[str] = Field(
        default=None,
        description=(
            "The complete, self-contained HTML string of the final risk scorecard report. "
            "Generated by the Report Generator Agent using a Jinja2 template. "
            "Can be written directly to a .html file and opened in any browser. "
            "Includes: company summary, all 7 factor score cards, quarterly trend charts, "
            "news sentiment summary, sector KPI performance, and the final verdict."
        ),
    )

    # -------------------------------------------------------------------------
    # SYSTEM METADATA (Auto-managed by the orchestrator)
    # -------------------------------------------------------------------------

    # ISO 8601 timestamp of when this state object was created (in IST)
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(IST),
        description="Timestamp (IST) when this AppState object was first created.",
    )

    # Tracks which agents have successfully completed their work.
    # Used by the orchestrator to resume from a checkpoint after a crash.
    # Example: ["ticker_resolver", "data_fetcher", "valuation_scorer"]
    completed_agents: List[str] = Field(
        default_factory=list,
        description=(
            "List of agent names that have successfully completed execution. "
            "Used for checkpoint/resume logic. "
            "Example agent names: 'ticker_resolver', 'sector_kpi_selector', "
            "'data_fetcher', 'valuation_scorer', 'verdict_writer', 'report_generator'."
        ),
    )

    # Stores any error messages from agents that failed, keyed by agent name.
    # Example: {"data_fetcher": "yfinance timeout after 30s"}
    errors: Dict[str, str] = Field(
        default_factory=dict,
        description=(
            "Dict of agent_name → error_message for any agents that failed. "
            "The orchestrator checks this to decide whether to retry or skip. "
            "Example: {'data_fetcher': 'yfinance: No data found for ticker XYZ.NS'}."
        ),
    )

    # -------------------------------------------------------------------------
    # PYDANTIC CONFIG
    # -------------------------------------------------------------------------

    model_config = {
        # Allow extra fields to be stored without raising validation errors.
        # Useful during development when new agents add experimental fields.
        "extra": "allow",

        # Allow population by field name AND alias (future-proofing for API integration)
        "populate_by_name": True,

        # When serialising to dict/JSON, use None for unset Optional fields
        # rather than omitting them entirely (makes debugging easier).
        "use_enum_values": True,
    }

    # =========================================================================
    # HELPER METHODS
    # Convenience functions that agents and the orchestrator can call on state.
    # =========================================================================

    def mark_agent_complete(self, agent_name: str) -> None:
        """
        Called by an agent when it finishes successfully.
        Adds the agent's name to completed_agents if not already present.

        Usage:
            state.mark_agent_complete("data_fetcher")
        """
        if agent_name not in self.completed_agents:
            self.completed_agents.append(agent_name)

    def log_error(self, agent_name: str, error_message: str) -> None:
        """
        Called by an agent when it encounters a non-fatal error.
        Stores the error so the orchestrator can decide to retry or skip.

        Usage:
            state.log_error("data_fetcher", "yfinance timeout: no data for ADANI.NS")
        """
        self.errors[agent_name] = error_message

    def is_agent_complete(self, agent_name: str) -> bool:
        """
        Returns True if a given agent has already run successfully.
        The orchestrator uses this for checkpoint/resume logic.

        Usage:
            if not state.is_agent_complete("data_fetcher"):
                await data_fetcher_agent.run(state)
        """
        return agent_name in self.completed_agents

    def to_json(self, indent: int = 2) -> str:
        """
        Serialises the entire AppState to a pretty-printed JSON string.
        Useful for logging, debugging, or saving intermediate state to disk.

        Usage:
            with open("state_snapshot.json", "w") as f:
                f.write(state.to_json())
        """
        return self.model_dump_json(indent=indent)

    def get_composite_score_label(self) -> str:
        """
        Returns a human-readable risk label based on the composite score.

        Returns:
            "🔴 HIGH RISK"      for scores 1.0 – 3.9
            "🟡 MODERATE RISK"  for scores 4.0 – 6.9
            "🟢 LOW RISK"       for scores 7.0 – 10.0
            "⚪ NOT SCORED YET" if composite_score is None
        """
        score = self.analytical_insights.composite_score
        if score is None:
            return "⚪ NOT SCORED YET"
        if score < 4.0:
            return "🔴 HIGH RISK"
        if score < 7.0:
            return "🟡 MODERATE RISK"
        return "🟢 LOW RISK"

    def summary(self) -> str:
        """
        Returns a one-line debug-friendly summary of the current state.
        Useful for logging progress in the orchestrator.

        Example output:
            [AppState] Reliance Industries | RELIANCE.NS | Oil & Gas |
            Score: 6.8 (🟡 MODERATE RISK) | Agents done: 5 | Errors: 0
        """
        score = self.analytical_insights.composite_score
        score_str = f"{score:.1f}" if score is not None else "N/A"
        return (
            f"[AppState] {self.company_name} | "
            f"Ticker: {self.ticker or 'unresolved'} | "
            f"Sector: {self.sector or 'undetected'} | "
            f"Score: {score_str} ({self.get_composite_score_label()}) | "
            f"Agents done: {len(self.completed_agents)} | "
            f"Errors: {len(self.errors)}"
        )


# =============================================================================
# QUICK USAGE EXAMPLE (for developers)
# Run this file directly: $ python state.py
# =============================================================================

if __name__ == "__main__":
    import json

    print("=" * 70)
    print("AppState — Demo Instantiation")
    print("=" * 70)

    # Step 1: Create a fresh state with just the company name (as the user would)
    state = AppState(company_name="HDFC Bank")

    # Step 2: Simulate the Ticker Resolver Agent populating ticker + sector
    state.ticker = "HDFCBANK.NS"
    state.sector = "Banking & Financial Services"
    state.mark_agent_complete("ticker_resolver")

    # Step 3: Simulate the Sector KPI Selector Agent
    state.sector_kpis = [
        SectorKPI(
            name="Net Interest Margin (NIM)",
            value=4.1,
            unit="%",
            description="Measures bank profitability: spread between lending and borrowing rates.",
        ),
        SectorKPI(
            name="Gross NPA Ratio",
            value=1.26,
            unit="%",
            description="Non-Performing Asset ratio — lower is better; indicates loan quality.",
        ),
    ]
    state.mark_agent_complete("sector_kpi_selector")

    # Step 4: Simulate the Data Fetcher Agent
    state.raw_financial_data.cmp = 1723.45
    state.raw_financial_data.week_52_high = 1880.00
    state.raw_financial_data.week_52_low = 1363.55
    state.raw_financial_data.pe_ratio = 19.8
    state.raw_financial_data.pb_ratio = 2.9
    state.raw_financial_data.roe = 17.2
    state.raw_financial_data.dividend_yield = 1.1
    state.raw_financial_data.promoter_pledge_pct = 0.0
    state.raw_financial_data.quarterly_financials = [
        QuarterlyFinancials(
            quarter_label="Q4 FY2025",
            revenue_cr=89450.0,
            pat_cr=17622.0,
            ebitda_cr=None,  # Banks report NII instead of EBITDA
            eps=22.98,
        ),
        QuarterlyFinancials(
            quarter_label="Q3 FY2025",
            revenue_cr=85200.0,
            pat_cr=16736.0,
            ebitda_cr=None,
            eps=21.83,
        ),
    ]
    state.mark_agent_complete("data_fetcher")

    # Step 5: Simulate a partial scoring result
    state.analytical_insights.valuation = FactorScore(
        factor_name="valuation",
        display_name="Valuation Risk",
        score=6,
        rationale=(
            "HDFC Bank trades at a P/E of ~19.8x, which is at a slight premium "
            "to the private banking sector median of ~17x but is justified by "
            "its superior asset quality and consistent earnings delivery."
        ),
        hidden_insight=(
            "The P/B of 2.9x looks expensive in isolation, but HDFC Bank's "
            "ROE of 17.2% comfortably exceeds its cost of equity (~13%), "
            "meaning it creates value above its book price."
        ),
        catalysts=["RBI rate cut cycle could expand NIM", "Credit card portfolio growth"],
        risks=["Elevated valuations leave little margin of safety", "Merger integration costs"],
    )
    state.analytical_insights.composite_score = 6.8
    state.analytical_insights.risk_band = "MODERATE RISK"

    # Step 6: Print the summary and a JSON snippet
    print(state.summary())
    print("\n--- JSON Snapshot (first 1200 chars) ---")
    json_output = state.to_json()
    print(json_output[:1200] + "\n... [truncated for display] ...")
    print("\n--- Risk Label ---")
    print(state.get_composite_score_label())
    print("\n✅ AppState schema is working correctly.")