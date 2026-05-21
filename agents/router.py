# =============================================================================
# agents/router.py
# Agent 1 — Ticker Router: Resolver · Sector Detector · KPI Mapper
# =============================================================================
#
# WHAT DOES THIS AGENT DO? (Plain English for a PM)
# --------------------------------------------------
# When a user types "HDFC Bank" or "hdfc bank" or even "hdfcbank", this agent:
#
#   STEP 1 — TICKER RESOLUTION
#       Converts the fuzzy company name → official NSE ticker symbol
#       e.g.  "hdfc bank"  →  "HDFCBANK.NS"
#       The ".NS" suffix is required by yfinance to pull data from NSE.
#       Falls back to a live yfinance search if not found in our static map.
#
#   STEP 2 — TICKER VALIDATION
#       Confirms the resolved ticker actually has live data on Yahoo Finance.
#       If not, it tries BSE (".BO" suffix) as a secondary exchange.
#       If both fail, it logs a clean error and stops gracefully.
#
#   STEP 3 — SECTOR DETECTION
#       Maps the validated ticker → one of 8 standard Indian market sectors.
#       Falls back to yfinance's own sector metadata if our map doesn't cover it.
#
#   STEP 4 — KPI INJECTION
#       Uses the detected sector → looks up the 2 sector-specific KPIs
#       from a hardcoded mapping → writes them into state.sector_kpis.
#
# INPUT  : state.company_name  (the raw string the user typed)
# OUTPUTS: state.ticker        (e.g. "HDFCBANK.NS")
#          state.sector        (e.g. "Banks/NBFCs")
#          state.sector_kpis   (list of 2 SectorKPI objects, value=None for now)
#
# WHY value=None IN sector_kpis?
#   This agent only *declares* which KPIs are relevant.
#   The actual numeric values (e.g. NIM = 4.1%) are fetched later by the
#   Data Fetcher Agent (Agent 3), which knows how to pull sector-specific data.
#
# ERROR PHILOSOPHY:
#   - Every external call is wrapped in try/except.
#   - On failure, the agent writes a message to state.errors["router"]
#     and returns the state as-is (partially populated).
#   - The orchestrator decides whether to abort or continue.
#   - We NEVER raise unhandled exceptions that crash the pipeline.
#
# =============================================================================

from __future__ import annotations

import re
import sys
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple

# ---------------------------------------------------------------------------
# PATH SETUP
# Adds the project root to sys.path so we can import state.py regardless of
# where this script is run from. Assumes project layout:
#   project_root/
#     state.py
#     agents/
#       router.py
# ---------------------------------------------------------------------------
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

import yfinance as yf
from loguru import logger

from state import AppState, SectorKPI

# =============================================================================
# SECTION 1: STATIC KNOWLEDGE BASES
# These are curated, hardcoded maps that give the agent instant, reliable
# answers for the most common Indian stocks — no API call needed.
# yfinance is only called when a company is NOT in these maps.
# =============================================================================

# -----------------------------------------------------------------------------
# 1A. COMPANY → NSE TICKER MAP
# -----------------------------------------------------------------------------
# KEY   : lowercase, stripped company name / common alias / abbreviation
# VALUE : official NSE ticker symbol WITHOUT the ".NS" suffix
#         (the suffix is appended programmatically in the resolver function)
#
# COVERAGE PHILOSOPHY:
#   We map the top ~5 companies per sector + common aliases + misspellings.
#   For anything outside this map, we fall back to yfinance's search API.
#
# HOW TO EXTEND:
#   Add a new row: "company alias": "TICKER_SYMBOL"
#   The alias should be lowercase and stripped of "ltd", "limited", "inc" etc.
# -----------------------------------------------------------------------------

COMPANY_TO_NSE_TICKER: Dict[str, str] = {

    # ── BANKS & NBFCs ──────────────────────────────────────────────────────
    "hdfc bank":             "HDFCBANK",
    "hdfcbank":              "HDFCBANK",
    "hdfc":                  "HDFCBANK",     # common shorthand
    "icici bank":            "ICICIBANK",
    "icicib ank":            "ICICIBANK",    # typo variant
    "icici":                 "ICICIBANK",
    "state bank of india":   "SBIN",
    "sbi":                   "SBIN",
    "kotak mahindra bank":   "KOTAKBANK",
    "kotak bank":            "KOTAKBANK",
    "kotak":                 "KOTAKBANK",
    "axis bank":             "AXISBANK",
    "axis":                  "AXISBANK",
    "indusind bank":         "INDUSINDBK",
    "indusind":              "INDUSINDBK",
    "yes bank":              "YESBANK",
    "punjab national bank":  "PNB",
    "pnb":                   "PNB",
    "bank of baroda":        "BANKBARODA",
    "bob":                   "BANKBARODA",
    "canara bank":           "CANBK",
    "union bank":            "UNIONBANK",
    "federal bank":          "FEDERALBNK",
    "idfc first bank":       "IDFCFIRSTB",
    "idfc":                  "IDFCFIRSTB",
    "bandhan bank":          "BANDHANBNK",
    "bajaj finance":         "BAJFINANCE",
    "bajaj fin":             "BAJFINANCE",
    "shriram finance":       "SHRIRAMFIN",
    "muthoot finance":       "MUTHOOTFIN",
    "cholafin":              "CHOLAFIN",
    "chola":                 "CHOLAFIN",
    "piramal enterprises":   "PEL",
    "piramal":               "PEL",
    "manappuram finance":    "MANAPPURAM",
    "l&t finance":           "LTF",
    "ltf":                   "LTF",

    # ── ASSET MANAGEMENT ──────────────────────────────────────────────────
    "hdfc amc":              "HDFCAMC",
    "nippon india amc":      "NAM-INDIA",
    "nippon amc":            "NAM-INDIA",
    "nippon":                "NAM-INDIA",
    "aditya birla sun life amc": "ABSLAMC",
    "absl amc":              "ABSLAMC",
    "uti amc":               "UTIAMC",
    "uti":                   "UTIAMC",
    "mirae asset":           "MIRAEASSET",
    "360 one wam":           "360ONE",
    "360one":                "360ONE",

    # ── IT SERVICES ───────────────────────────────────────────────────────
    "tata consultancy services": "TCS",
    "tcs":                   "TCS",
    "infosys":               "INFY",
    "infy":                  "INFY",
    "wipro":                 "WIPRO",
    "hcl technologies":      "HCLTECH",
    "hcl tech":              "HCLTECH",
    "hcltech":               "HCLTECH",
    "tech mahindra":         "TECHM",
    "techm":                 "TECHM",
    "ltimindtree":           "LTIM",
    "lti mindtree":          "LTIM",
    "mphasis":               "MPHASIS",
    "persistent systems":    "PERSISTENT",
    "persistent":            "PERSISTENT",
    "coforge":               "COFORGE",
    "hexaware":              "HEXAWARE",
    "l&t technology services": "LTTS",
    "ltts":                  "LTTS",
    "kpit technologies":     "KPITTECH",
    "kpit":                  "KPITTECH",
    "oracle financial":      "OFSS",
    "ofss":                  "OFSS",

    # ── FMCG / CONSUMER ───────────────────────────────────────────────────
    "hindustan unilever":    "HINDUNILVR",
    "hul":                   "HINDUNILVR",
    "itc":                   "ITC",
    "nestle india":          "NESTLEIND",
    "nestle":                "NESTLEIND",
    "britannia":             "BRITANNIA",
    "britannia industries":  "BRITANNIA",
    "dabur":                 "DABUR",
    "dabur india":           "DABUR",
    "marico":                "MARICO",
    "godrej consumer":       "GODREJCP",
    "godrej cp":             "GODREJCP",
    "emami":                 "EMAMILTD",
    "colgate":               "COLPAL",
    "colgate palmolive":     "COLPAL",
    "varun beverages":       "VBL",
    "vbl":                   "VBL",
    "tata consumer":         "TATACONSUM",
    "tata consumer products":"TATACONSUM",
    "united spirits":        "MCDOWELL-N",
    "mcdowell":              "MCDOWELL-N",
    "united breweries":      "UBL",
    "pidilite":              "PIDILITIND",
    "asian paints":          "ASIANPAINT",

    # ── PHARMA ────────────────────────────────────────────────────────────
    "sun pharmaceutical":    "SUNPHARMA",
    "sun pharma":            "SUNPHARMA",
    "sunpharma":             "SUNPHARMA",
    "dr reddys":             "DRREDDY",
    "dr reddy":              "DRREDDY",
    "dr. reddy's laboratories": "DRREDDY",
    "cipla":                 "CIPLA",
    "divi's laboratories":   "DIVISLAB",
    "divis":                 "DIVISLAB",
    "divi":                  "DIVISLAB",
    "lupin":                 "LUPIN",
    "aurobindo pharma":      "AUROPHARMA",
    "aurobindo":             "AUROPHARMA",
    "torrent pharma":        "TORNTPHARM",
    "torrent pharmaceuticals": "TORNTPHARM",
    "alkem laboratories":    "ALKEM",
    "alkem":                 "ALKEM",
    "zydus lifesciences":    "ZYDUSLIFE",
    "zydus":                 "ZYDUSLIFE",
    "abbott india":          "ABBOTINDIA",
    "ipca":                  "IPCALAB",
    "mankind pharma":        "MANKIND",
    "gland pharma":          "GLAND",

    # ── INDUSTRIALS / INFRA ───────────────────────────────────────────────
    "larsen and toubro":     "LT",
    "l&t":                   "LT",
    "larsen & toubro":       "LT",
    "siemens india":         "SIEMENS",
    "siemens":               "SIEMENS",
    "abb india":             "ABB",
    "abb":                   "ABB",
    "bharat electronics":    "BEL",
    "bel":                   "BEL",
    "bhel":                  "BHEL",
    "bharat heavy electricals": "BHEL",
    "adani ports":           "ADANIPORTS",
    "adani green":           "ADANIGREEN",
    "adani enterprises":     "ADANIENT",
    "adani":                 "ADANIENT",
    "power grid":            "POWERGRID",
    "power grid corporation":"POWERGRID",
    "ntpc":                  "NTPC",
    "irfc":                  "IRFC",
    "rvnl":                  "RVNL",
    "rail vikas nigam":      "RVNL",
    "kalpataru":             "KPIL",
    "kec international":     "KEC",
    "itd cementation":       "ITDCEM",
    "cg power":              "CGPOWER",

    # ── AUTOMOBILES ───────────────────────────────────────────────────────
    "tata motors":           "TATAMOTORS",
    "maruti suzuki":         "MARUTI",
    "maruti":                "MARUTI",
    "mahindra and mahindra": "M&M",
    "m&m":                   "M&M",
    "mahindra":              "M&M",
    "bajaj auto":            "BAJAJ-AUTO",
    "bajaj":                 "BAJAJ-AUTO",
    "hero motocorp":         "HEROMOTOCO",
    "hero":                  "HEROMOTOCO",
    "eicher motors":         "EICHERMOT",
    "eicher":                "EICHERMOT",
    "royal enfield":         "EICHERMOT",
    "tvs motor":             "TVSMOTOR",
    "tvs":                   "TVSMOTOR",
    "ashok leyland":         "ASHOKLEY",
    "mrf":                   "MRF",
    "ola electric":          "OLAELEC",
    "samvardhana motherson": "MOTHERSON",
    "motherson":             "MOTHERSON",
    "bosch india":           "BOSCHLTD",
    "bosch":                 "BOSCHLTD",
    "exide industries":      "EXIDEIND",

    # ── INSURANCE ─────────────────────────────────────────────────────────
    "hdfc life":             "HDFCLIFE",
    "hdfc life insurance":   "HDFCLIFE",
    "sbi life":              "SBILIFE",
    "sbi life insurance":    "SBILIFE",
    "icici prudential life": "ICICIPRULI",
    "icici pru life":        "ICICIPRULI",
    "max financial":         "MFSL",
    "max life":              "MFSL",
    "bajaj allianz life":    "BAJAJFINSV",  # listed via Bajaj Finserv
    "star health":           "STARHEALTH",
    "icici lombard":         "ICICIGI",
    "new india assurance":   "NIACL",
    "general insurance":     "GICRE",
    "lic":                   "LICI",
    "life insurance corporation": "LICI",
}


# -----------------------------------------------------------------------------
# 1B. NSE TICKER → SECTOR MAP
# -----------------------------------------------------------------------------
# Once we have the NSE ticker, we look it up here to get the sector.
# This is faster and more reliable than relying on yfinance's sector string,
# which is often generic (e.g., "Financial Services" covers banks + AMCs + insurance).
#
# SECTOR LABELS are standardised to the 8 categories used in KPI_MAP below.
# -----------------------------------------------------------------------------

TICKER_TO_SECTOR: Dict[str, str] = {

    # Banks & NBFCs
    "HDFCBANK":    "Banks/NBFCs",
    "ICICIBANK":   "Banks/NBFCs",
    "SBIN":        "Banks/NBFCs",
    "KOTAKBANK":   "Banks/NBFCs",
    "AXISBANK":    "Banks/NBFCs",
    "INDUSINDBK":  "Banks/NBFCs",
    "YESBANK":     "Banks/NBFCs",
    "PNB":         "Banks/NBFCs",
    "BANKBARODA":  "Banks/NBFCs",
    "CANBK":       "Banks/NBFCs",
    "UNIONBANK":   "Banks/NBFCs",
    "FEDERALBNK":  "Banks/NBFCs",
    "IDFCFIRSTB":  "Banks/NBFCs",
    "BANDHANBNK":  "Banks/NBFCs",
    "BAJFINANCE":  "Banks/NBFCs",
    "SHRIRAMFIN":  "Banks/NBFCs",
    "MUTHOOTFIN":  "Banks/NBFCs",
    "CHOLAFIN":    "Banks/NBFCs",
    "PEL":         "Banks/NBFCs",
    "MANAPPURAM":  "Banks/NBFCs",
    "LTF":         "Banks/NBFCs",

    # Asset Management
    "HDFCAMC":     "Asset Management",
    "NAM-INDIA":   "Asset Management",
    "ABSLAMC":     "Asset Management",
    "UTIAMC":      "Asset Management",
    "MIRAEASSET":  "Asset Management",
    "360ONE":      "Asset Management",

    # IT Services
    "TCS":         "IT Services",
    "INFY":        "IT Services",
    "WIPRO":       "IT Services",
    "HCLTECH":     "IT Services",
    "TECHM":       "IT Services",
    "LTIM":        "IT Services",
    "MPHASIS":     "IT Services",
    "PERSISTENT":  "IT Services",
    "COFORGE":     "IT Services",
    "HEXAWARE":    "IT Services",
    "LTTS":        "IT Services",
    "KPITTECH":    "IT Services",
    "OFSS":        "IT Services",

    # FMCG / Consumer
    "HINDUNILVR":  "FMCG/Consumer",
    "ITC":         "FMCG/Consumer",
    "NESTLEIND":   "FMCG/Consumer",
    "BRITANNIA":   "FMCG/Consumer",
    "DABUR":       "FMCG/Consumer",
    "MARICO":      "FMCG/Consumer",
    "GODREJCP":    "FMCG/Consumer",
    "EMAMILTD":    "FMCG/Consumer",
    "COLPAL":      "FMCG/Consumer",
    "VBL":         "FMCG/Consumer",
    "TATACONSUM":  "FMCG/Consumer",
    "MCDOWELL-N":  "FMCG/Consumer",
    "UBL":         "FMCG/Consumer",
    "PIDILITIND":  "FMCG/Consumer",
    "ASIANPAINT":  "FMCG/Consumer",

    # Pharma
    "SUNPHARMA":   "Pharma",
    "DRREDDY":     "Pharma",
    "CIPLA":       "Pharma",
    "DIVISLAB":    "Pharma",
    "LUPIN":       "Pharma",
    "AUROPHARMA":  "Pharma",
    "TORNTPHARM":  "Pharma",
    "ALKEM":       "Pharma",
    "ZYDUSLIFE":   "Pharma",
    "ABBOTINDIA":  "Pharma",
    "IPCALAB":     "Pharma",
    "MANKIND":     "Pharma",
    "GLAND":       "Pharma",

    # Industrials / Infra
    "LT":          "Industrials/Infra",
    "SIEMENS":     "Industrials/Infra",
    "ABB":         "Industrials/Infra",
    "BEL":         "Industrials/Infra",
    "BHEL":        "Industrials/Infra",
    "ADANIPORTS":  "Industrials/Infra",
    "ADANIGREEN":  "Industrials/Infra",
    "ADANIENT":    "Industrials/Infra",
    "POWERGRID":   "Industrials/Infra",
    "NTPC":        "Industrials/Infra",
    "IRFC":        "Industrials/Infra",
    "RVNL":        "Industrials/Infra",
    "KPIL":        "Industrials/Infra",
    "KEC":         "Industrials/Infra",
    "ITDCEM":      "Industrials/Infra",
    "CGPOWER":     "Industrials/Infra",

    # Automobiles
    "TATAMOTORS":  "Automobiles",
    "MARUTI":      "Automobiles",
    "M&M":         "Automobiles",
    "BAJAJ-AUTO":  "Automobiles",
    "HEROMOTOCO":  "Automobiles",
    "EICHERMOT":   "Automobiles",
    "TVSMOTOR":    "Automobiles",
    "ASHOKLEY":    "Automobiles",
    "MRF":         "Automobiles",
    "OLAELEC":     "Automobiles",
    "MOTHERSON":   "Automobiles",
    "BOSCHLTD":    "Automobiles",
    "EXIDEIND":    "Automobiles",

    # Insurance
    "HDFCLIFE":    "Insurance",
    "SBILIFE":     "Insurance",
    "ICICIPRULI":  "Insurance",
    "MFSL":        "Insurance",
    "BAJAJFINSV":  "Insurance",
    "STARHEALTH":  "Insurance",
    "ICICIGI":     "Insurance",
    "NIACL":       "Insurance",
    "GICRE":       "Insurance",
    "LICI":        "Insurance",
}


# -----------------------------------------------------------------------------
# 1C. SECTOR → yfinance KEYWORD MAP (for fallback sector inference)
# -----------------------------------------------------------------------------
# When a ticker is NOT in TICKER_TO_SECTOR, we ask yfinance for the sector/
# industry string and scan it for keywords to classify into our 8 buckets.
# Each sector has a list of keyword fragments to match against (case-insensitive).
# -----------------------------------------------------------------------------

YFINANCE_SECTOR_KEYWORDS: Dict[str, List[str]] = {
    "Banks/NBFCs": [
        "bank", "nbfc", "financial services", "credit", "lending",
        "microfinance", "housing finance", "mortgage",
    ],
    "Asset Management": [
        "asset management", "mutual fund", "wealth management",
        "investment management", "amc",
    ],
    "IT Services": [
        "information technology", "software", "it services", "technology",
        "data processing", "computer services", "consulting",
    ],
    "FMCG/Consumer": [
        "consumer", "fmcg", "food", "beverage", "personal care",
        "household", "tobacco", "retail", "packaged goods",
    ],
    "Pharma": [
        "pharmaceutical", "pharma", "drug", "healthcare", "biotech",
        "life science", "medical", "diagnostics",
    ],
    "Industrials/Infra": [
        "industrial", "infrastructure", "engineering", "construction",
        "power", "energy", "utilities", "capital goods", "defence",
        "aerospace", "rail", "port", "telecom",
    ],
    "Automobiles": [
        "automobile", "automotive", "vehicle", "two-wheeler", "car",
        "truck", "tyre", "auto component", "electric vehicle",
    ],
    "Insurance": [
        "insurance", "life insurance", "general insurance", "reinsurance",
        "assurance",
    ],
}


# -----------------------------------------------------------------------------
# 1D. SECTOR → KPI DEFINITIONS MAP
# -----------------------------------------------------------------------------
# The single authoritative source for all sector KPI metadata.
# Any change to KPI names/descriptions happens ONLY here.
#
# STRUCTURE per sector: list of exactly 2 dicts, each with:
#   name        : display label (matches FactorScore.display_name convention)
#   unit        : the measurement unit
#   description : one-sentence plain-English explanation for the HTML report
# -----------------------------------------------------------------------------

KPI_MAP: Dict[str, List[Dict[str, str]]] = {

    "Banks/NBFCs": [
        {
            "name": "Net Interest Margin (NIM)",
            "unit": "%",
            "description": (
                "Spread between what the bank earns on loans and pays on deposits. "
                "Higher NIM = stronger core lending profitability."
            ),
        },
        {
            "name": "Gross NPA Ratio (GNPA%)",
            "unit": "%",
            "description": (
                "Percentage of total loans that have turned bad (non-performing). "
                "Lower is better; >3% is a yellow flag for Indian banks."
            ),
        },
    ],

    "Asset Management": [
        {
            "name": "Assets Under Management (AUM)",
            "unit": "₹ Cr",
            "description": (
                "Total market value of all funds managed by the AMC. "
                "Larger AUM = greater scale and fee-income stability."
            ),
        },
        {
            "name": "Equity AUM Mix",
            "unit": "%",
            "description": (
                "Proportion of total AUM held in equity (vs debt/liquid) funds. "
                "Higher equity mix = higher management fees and margin potential."
            ),
        },
    ],

    "IT Services": [
        {
            "name": "Revenue Growth (Constant Currency)",
            "unit": "%",
            "description": (
                "Year-on-year revenue growth adjusted for currency fluctuations. "
                "The true measure of organic business momentum."
            ),
        },
        {
            "name": "EBIT Margin",
            "unit": "%",
            "description": (
                "Earnings before interest and taxes as a % of revenue. "
                "Measures operational efficiency; >20% is healthy for large-cap IT."
            ),
        },
    ],

    "FMCG/Consumer": [
        {
            "name": "Volume Growth",
            "unit": "%",
            "description": (
                "Growth in units sold (stripping out price/mix effects). "
                "Signals real demand expansion vs. price-driven revenue growth."
            ),
        },
        {
            "name": "EBITDA Margin",
            "unit": "%",
            "description": (
                "Operating profit as a % of net sales. "
                "Key profitability metric; expansion signals improving brand pricing power."
            ),
        },
    ],

    "Pharma": [
        {
            "name": "US Revenue Contribution",
            "unit": "%",
            "description": (
                "Share of total revenue from the US generics market. "
                "High exposure = high opportunity but also high FDA/regulatory risk."
            ),
        },
        {
            "name": "FDA Observations (Form 483 Count)",
            "unit": "count",
            "description": (
                "Number of unresolved FDA observations across manufacturing sites. "
                "Any observation can trigger import alerts; 0 is ideal."
            ),
        },
    ],

    "Industrials/Infra": [
        {
            "name": "Order Book",
            "unit": "₹ Cr",
            "description": (
                "Total value of confirmed, unexecuted contracts in the pipeline. "
                "Large order book = strong near-term revenue visibility."
            ),
        },
        {
            "name": "Debt-to-Equity Ratio (D/E)",
            "unit": "x",
            "description": (
                "Total debt divided by shareholders' equity. "
                "High D/E in a capex-intensive sector signals balance sheet risk."
            ),
        },
    ],

    "Automobiles": [
        {
            "name": "Domestic Volume Growth",
            "unit": "%",
            "description": (
                "Year-on-year growth in total units sold in India. "
                "Leading indicator of market share gains and demand cycles."
            ),
        },
        {
            "name": "EV Mix",
            "unit": "%",
            "description": (
                "Electric vehicles as a percentage of total domestic volumes. "
                "Rising EV mix signals future-readiness and margin profile shift."
            ),
        },
    ],

    "Insurance": [
        {
            "name": "Solvency Ratio",
            "unit": "x",
            "description": (
                "Available capital vs. required capital per IRDAI norms. "
                "Must be >1.5x; lower ratios signal capital adequacy risk."
            ),
        },
        {
            "name": "Value of New Business (VNB) Margin",
            "unit": "%",
            "description": (
                "Profitability of new policies written in the period. "
                "Higher VNB margin = more profitable growth from new business."
            ),
        },
    ],
}


# =============================================================================
# SECTION 2: HELPER FUNCTIONS
# Small, single-purpose functions. Easy to test and debug independently.
# =============================================================================

def _normalise_company_name(raw_name: str) -> str:
    """
    Cleans a raw user-input company name to a canonical lowercase key
    suitable for lookup in COMPANY_TO_NSE_TICKER.

    TRANSFORMATIONS APPLIED:
    1. Strip leading/trailing whitespace
    2. Convert to lowercase
    3. Remove common legal suffixes (ltd, limited, inc, corp, pvt, etc.)
    4. Collapse multiple spaces into one
    5. Strip punctuation except '&' and '-' (relevant for names like "L&T")

    Examples:
        "HDFC Bank Ltd."  → "hdfc bank"
        "Infosys Limited" → "infosys"
        "Dr. Reddy's Laboratories" → "dr reddys laboratories"
        "L&T"             → "l&t"
    """
    name = raw_name.strip().lower()

    # Remove common legal entity suffixes (word-boundary anchored)
    legal_suffixes = r"\b(ltd|limited|inc|corp|corporation|pvt|private|plc|llp|co)\b\.?"
    name = re.sub(legal_suffixes, "", name)

    # Remove standalone punctuation (apostrophes, dots) but keep & and -
    name = re.sub(r"['.]+", "", name)

    # Collapse multiple whitespace characters into a single space
    name = re.sub(r"\s+", " ", name).strip()

    return name


def _resolve_ticker_from_map(normalised_name: str) -> Optional[str]:
    """
    Attempts to find the NSE ticker from our static COMPANY_TO_NSE_TICKER map.

    Returns the raw ticker symbol (without .NS suffix) if found, else None.

    WHY STATIC MAP FIRST?
    - Instant: zero network calls
    - Reliable: no rate limits, no Yahoo Finance downtime
    - Handles common aliases and abbreviations
    """
    return COMPANY_TO_NSE_TICKER.get(normalised_name)


def _resolve_ticker_from_yfinance_search(company_name: str) -> Optional[str]:
    """
    Fallback: queries yfinance's search API to find a matching Indian ticker.

    HOW IT WORKS:
    yfinance.Search returns a ranked list of matching securities.
    We iterate through results and pick the first one that:
      (a) has an exchange of "NSI" (NSE) or "BSI" (BSE), AND
      (b) is a common stock (not an ETF, index, or mutual fund)

    Returns the raw symbol (without exchange suffix) if found, else None.

    RATE LIMITING:
    We add a 0.5s sleep to avoid hammering Yahoo's API if called in a batch.
    """
    try:
        logger.debug(f"[Router] yfinance search fallback for: '{company_name}'")
        time.sleep(0.5)  # polite delay

        search_result = yf.Search(
            query=company_name,
            news_count=0,        # we only want quotes, not news
            max_results=10,
        )
        quotes = search_result.quotes  # list of dicts

        if not quotes:
            logger.warning(f"[Router] yfinance search returned no results for '{company_name}'")
            return None

        # Prefer NSE results; fall back to BSE
        for exchange_code in ("NSI", "BSI"):
            for quote in quotes:
                exch = quote.get("exchange", "")
                qtype = quote.get("quoteType", "")
                symbol = quote.get("symbol", "")

                if exch == exchange_code and qtype == "EQUITY" and symbol:
                    # Strip exchange suffixes if present (e.g., "RELIANCE.NS" → "RELIANCE")
                    clean_symbol = symbol.replace(".NS", "").replace(".BO", "")
                    logger.info(
                        f"[Router] yfinance matched '{company_name}' → '{clean_symbol}' "
                        f"(exchange: {exchange_code})"
                    )
                    return clean_symbol

        logger.warning(f"[Router] No Indian equity found via yfinance search for '{company_name}'")
        return None

    except Exception as exc:
        logger.error(f"[Router] yfinance search error for '{company_name}': {exc}")
        return None


def _validate_ticker_on_yfinance(ticker_symbol: str) -> Tuple[bool, str]:
    """
    Validates that a ticker symbol actually has live data on Yahoo Finance.

    STRATEGY:
    1. Try NSE first: append ".NS", fetch 5 days of history
    2. If NSE has no data, try BSE: replace ".NS" with ".BO"
    3. Return the working full ticker string + a boolean

    Returns:
        (True,  "HDFCBANK.NS")  — NSE ticker is live
        (True,  "500180.BO")    — only BSE ticker works
        (False, "")             — neither exchange has data

    WHY VALIDATE?
    A ticker can exist in our map but be delisted, suspended, or have a
    changed symbol. Validation catches these edge cases before downstream
    agents try to pull 4 quarters of financial data and crash.
    """
    nse_ticker = f"{ticker_symbol}.NS"
    bse_ticker  = f"{ticker_symbol}.BO"

    for full_ticker in (nse_ticker, bse_ticker):
        try:
            logger.debug(f"[Router] Validating ticker: {full_ticker}")
            time.sleep(0.3)  # polite delay between calls

            stock = yf.Ticker(full_ticker)
            hist  = stock.history(period="5d")  # lightweight call

            if not hist.empty:
                logger.info(f"[Router] ✅ Ticker validated: {full_ticker}")
                return True, full_ticker

        except Exception as exc:
            logger.debug(f"[Router] Validation error for {full_ticker}: {exc}")
            continue

    logger.warning(f"[Router] ❌ Could not validate ticker '{ticker_symbol}' on NSE or BSE")
    return False, ""


def _detect_sector_from_map(ticker_symbol: str) -> Optional[str]:
    """
    Looks up the sector from our static TICKER_TO_SECTOR map.
    Returns the sector string if found, else None.

    The ticker_symbol passed here is the raw symbol WITHOUT exchange suffix
    (e.g., "HDFCBANK" not "HDFCBANK.NS").
    """
    return TICKER_TO_SECTOR.get(ticker_symbol.upper())


def _detect_sector_from_yfinance(full_ticker: str) -> Optional[str]:
    """
    Fallback: fetches yfinance's own sector/industry strings and maps them
    to one of our 8 standardised sector labels using keyword matching.

    yfinance returns fields like:
        info["sector"]   = "Financial Services"
        info["industry"] = "Banks—Regional"

    We concatenate both, lowercase, and scan against YFINANCE_SECTOR_KEYWORDS.

    Returns a sector string if matched, else None.
    """
    try:
        logger.debug(f"[Router] Fetching yfinance sector metadata for {full_ticker}")
        time.sleep(0.3)

        stock = yf.Ticker(full_ticker)
        info  = stock.info or {}

        # Build a combined string for keyword matching
        combined = " ".join([
            info.get("sector", ""),
            info.get("industry", ""),
            info.get("longBusinessSummary", "")[:200],  # first 200 chars of description
        ]).lower()

        if not combined.strip():
            logger.warning(f"[Router] yfinance returned empty sector info for {full_ticker}")
            return None

        # Score each sector by counting keyword matches
        best_sector: Optional[str] = None
        best_score  = 0

        for sector, keywords in YFINANCE_SECTOR_KEYWORDS.items():
            score = sum(1 for kw in keywords if kw in combined)
            if score > best_score:
                best_score  = score
                best_sector = sector

        if best_sector and best_score > 0:
            logger.info(
                f"[Router] yfinance sector inference: '{full_ticker}' → "
                f"'{best_sector}' (keyword score: {best_score})"
            )
            return best_sector

        logger.warning(f"[Router] No sector keyword match for {full_ticker}. Raw: '{combined[:100]}'")
        return None

    except Exception as exc:
        logger.error(f"[Router] yfinance sector fetch error for {full_ticker}: {exc}")
        return None


def _build_sector_kpis(sector: str) -> List[SectorKPI]:
    """
    Constructs the list of 2 SectorKPI objects for a given sector.

    Looks up KPI_MAP using the sector string.
    Returns a list of 2 SectorKPI objects with value=None (to be filled
    by the Data Fetcher Agent later).

    If the sector is not in KPI_MAP (e.g., an unexpected sector string),
    returns an empty list so the pipeline can continue without crashing.
    """
    kpi_definitions = KPI_MAP.get(sector, [])

    if not kpi_definitions:
        logger.warning(f"[Router] No KPI definitions found for sector '{sector}'")
        return []

    kpis = []
    for kpi_def in kpi_definitions:
        kpi = SectorKPI(
            name=kpi_def["name"],
            value=None,         # ← populated later by Data Fetcher Agent
            unit=kpi_def["unit"],
            description=kpi_def["description"],
        )
        kpis.append(kpi)

    logger.info(
        f"[Router] KPIs injected for '{sector}': "
        + " | ".join(k.name for k in kpis)
    )
    return kpis


# =============================================================================
# SECTION 3: THE MAIN AGENT FUNCTION
# This is the single public entry point called by the orchestrator.
# =============================================================================

def run(state: AppState) -> AppState:
    """
    =========================================================================
    Agent 1 — Router: Ticker Resolution · Sector Detection · KPI Mapping
    =========================================================================

    ENTRY POINT called by the orchestrator:
        from agents.router import run
        state = run(state)

    WHAT IT DOES (in order):
        1. Normalises state.company_name (strips legal suffixes, lowercase)
        2. Resolves the NSE/BSE ticker via static map → yfinance fallback
        3. Validates the ticker has live data on Yahoo Finance
        4. Detects the sector via static map → yfinance fallback
        5. Injects 2 sector KPIs (with value=None) into state.sector_kpis
        6. Marks itself complete in state.completed_agents

    IDEMPOTENCY:
        If the agent has already run (checked via state.is_agent_complete),
        it logs a message and returns the state immediately without re-running.
        This supports the orchestrator's checkpoint/resume logic.

    PARTIAL SUCCESS:
        If ticker resolution succeeds but sector detection fails, the agent
        still marks itself complete and logs a warning. Downstream agents
        are expected to handle sector=None gracefully.

    ERROR HANDLING:
        All errors are caught, logged, and written to state.errors["router"].
        The function NEVER raises an exception to the caller.

    Args:
        state (AppState): The shared application state object. Must have
                          state.company_name populated.

    Returns:
        AppState: The same state object, mutated in-place with:
                  - state.ticker       (str, e.g. "HDFCBANK.NS")
                  - state.sector       (str, e.g. "Banks/NBFCs")
                  - state.sector_kpis  (List[SectorKPI], 2 items, value=None)
                  OR state.errors["router"] if something went wrong.
    """

    agent_name = "router"

    # ─── IDEMPOTENCY CHECK ────────────────────────────────────────────────
    # If the orchestrator is replaying this step after a partial failure,
    # don't re-run work that already succeeded.
    if state.is_agent_complete(agent_name):
        logger.info(f"[Router] Already complete for '{state.company_name}'. Skipping.")
        return state

    logger.info(f"[Router] ▶ Starting for company: '{state.company_name}'")

    try:
        # ═══════════════════════════════════════════════════════════════════
        # STEP 1 — NORMALISE COMPANY NAME
        # ═══════════════════════════════════════════════════════════════════
        normalised = _normalise_company_name(state.company_name)
        logger.debug(f"[Router] Normalised name: '{state.company_name}' → '{normalised}'")

        # ═══════════════════════════════════════════════════════════════════
        # STEP 2 — RESOLVE TICKER SYMBOL
        # ═══════════════════════════════════════════════════════════════════

        raw_ticker: Optional[str] = None

        # 2a. Try static map first (fastest path)
        raw_ticker = _resolve_ticker_from_map(normalised)

        if raw_ticker:
            logger.info(f"[Router] Static map hit: '{normalised}' → '{raw_ticker}'")
        else:
            # 2b. Static map missed; try yfinance search
            logger.info(f"[Router] Static map miss for '{normalised}'. Trying yfinance search…")
            raw_ticker = _resolve_ticker_from_yfinance_search(state.company_name)

        if not raw_ticker:
            # Total failure: cannot resolve ticker
            err_msg = (
                f"Could not resolve a ticker for '{state.company_name}'. "
                "Try using the exact company name (e.g. 'Infosys', 'HDFC Bank', 'TCS')."
            )
            logger.error(f"[Router] ❌ {err_msg}")
            state.log_error(agent_name, err_msg)
            # Return without marking complete — orchestrator may prompt user to correct name
            return state

        # ═══════════════════════════════════════════════════════════════════
        # STEP 3 — VALIDATE TICKER ON YAHOO FINANCE
        # ═══════════════════════════════════════════════════════════════════

        is_valid, full_ticker = _validate_ticker_on_yfinance(raw_ticker)

        if not is_valid:
            err_msg = (
                f"Ticker '{raw_ticker}' resolved from '{state.company_name}' "
                "has no live data on NSE or BSE via Yahoo Finance. "
                "The stock may be delisted, suspended, or the symbol may have changed."
            )
            logger.error(f"[Router] ❌ {err_msg}")
            state.log_error(agent_name, err_msg)
            return state

        # ✅ Ticker confirmed — write to state
        state.ticker = full_ticker
        logger.info(f"[Router] ✅ Ticker confirmed: {state.ticker}")

        # ═══════════════════════════════════════════════════════════════════
        # STEP 4 — DETECT SECTOR
        # ═══════════════════════════════════════════════════════════════════

        sector: Optional[str] = None

        # 4a. Try static TICKER_TO_SECTOR map (uses raw ticker without suffix)
        sector = _detect_sector_from_map(raw_ticker)

        if sector:
            logger.info(f"[Router] Static sector map hit: '{raw_ticker}' → '{sector}'")
        else:
            # 4b. Fallback to yfinance metadata + keyword matching
            logger.info(
                f"[Router] No static sector for '{raw_ticker}'. "
                "Falling back to yfinance keyword inference…"
            )
            sector = _detect_sector_from_yfinance(full_ticker)

        if not sector:
            # Non-fatal: sector unknown but pipeline can continue
            warn_msg = (
                f"Could not auto-detect sector for '{state.company_name}' ({full_ticker}). "
                "Sector-specific KPIs will not be available. "
                "Consider manually setting state.sector before running downstream agents."
            )
            logger.warning(f"[Router] ⚠ {warn_msg}")
            state.log_error(agent_name, warn_msg)
            # Still mark complete — ticker resolution succeeded
            state.mark_agent_complete(agent_name)
            return state

        # ✅ Sector confirmed — write to state
        state.sector = sector
        logger.info(f"[Router] ✅ Sector detected: {state.sector}")

        # ═══════════════════════════════════════════════════════════════════
        # STEP 5 — INJECT SECTOR KPIs
        # ═══════════════════════════════════════════════════════════════════

        kpis = _build_sector_kpis(sector)

        if not kpis:
            warn_msg = (
                f"Sector '{sector}' is recognised but has no KPI definitions in KPI_MAP. "
                "This is a configuration gap — please update KPI_MAP in router.py."
            )
            logger.warning(f"[Router] ⚠ {warn_msg}")
            state.log_error(agent_name, warn_msg)
        else:
            state.sector_kpis = kpis
            logger.info(
                f"[Router] ✅ {len(kpis)} KPIs injected: "
                + " | ".join(k.name for k in kpis)
            )

        # ═══════════════════════════════════════════════════════════════════
        # STEP 6 — MARK COMPLETE
        # ═══════════════════════════════════════════════════════════════════

        state.mark_agent_complete(agent_name)
        logger.info(
            f"[Router] ✅ Complete. Summary: "
            f"Ticker={state.ticker} | Sector={state.sector} | "
            f"KPIs={[k.name for k in state.sector_kpis]}"
        )

    except Exception as exc:
        # Catch-all: something unexpected happened (e.g., network failure,
        # yfinance API change, Pydantic validation error in an edge case).
        # Log it clearly and do NOT re-raise — the pipeline must not crash.
        err_msg = f"Unexpected error in Router agent: {type(exc).__name__}: {exc}"
        logger.exception(f"[Router] 💥 {err_msg}")
        state.log_error(agent_name, err_msg)

    return state


# =============================================================================
# SECTION 4: STANDALONE TEST HARNESS
# Run this file directly: $ python agents/router.py
# Tests a variety of inputs: clean names, aliases, typos, unknown companies.
# =============================================================================

if __name__ == "__main__":
    from loguru import logger as _logger

    # Configure loguru for readable test output
    _logger.remove()
    _logger.add(
        sink=sys.stderr,
        level="DEBUG",
        format=(
            "<green>{time:HH:mm:ss}</green> | "
            "<level>{level: <8}</level> | "
            "<cyan>{message}</cyan>"
        ),
        colorize=True,
    )

    TEST_CASES = [
        # (input_name, expected_ticker_contains, expected_sector)
        ("HDFC Bank",                 "HDFCBANK",  "Banks/NBFCs"),
        ("hdfc bank ltd.",            "HDFCBANK",  "Banks/NBFCs"),
        ("Infosys",                   "INFY",      "IT Services"),
        ("TCS",                       "TCS",       "IT Services"),
        ("tata consultancy services", "TCS",       "IT Services"),
        ("Sun Pharma",                "SUNPHARMA", "Pharma"),
        ("Dr Reddy's Laboratories",   "DRREDDY",   "Pharma"),
        ("Reliance",                  None,        None),          # not in static map; yfinance fallback
        ("UNKNOWN XYZ COMPANY 99999", None,        None),          # expected failure
    ]

    print("\n" + "=" * 72)
    print("  AGENT 1 — ROUTER : TEST HARNESS")
    print("=" * 72)

    passed = 0
    failed = 0

    for company_name, expected_ticker_fragment, expected_sector in TEST_CASES:
        print(f"\n{'─'*72}")
        print(f"  INPUT : '{company_name}'")

        # Create a fresh state for each test
        test_state = AppState(company_name=company_name)
        result_state = run(test_state)

        ticker = result_state.ticker or "NOT RESOLVED"
        sector = result_state.sector or "NOT DETECTED"
        kpis   = [k.name for k in result_state.sector_kpis]
        errors = result_state.errors

        print(f"  TICKER: {ticker}")
        print(f"  SECTOR: {sector}")
        print(f"  KPIs  : {kpis}")
        if errors:
            print(f"  ERRORS: {errors}")

        # Assertion
        if expected_ticker_fragment is None:
            # We expect failure or fallback — just show outcome
            status = "⚪ EXPECTED FALLBACK"
        elif (
            expected_ticker_fragment in ticker
            and result_state.sector == expected_sector
            and len(result_state.sector_kpis) == 2
        ):
            status = "✅ PASS"
            passed += 1
        else:
            status = "❌ FAIL"
            failed += 1

        print(f"  STATUS: {status}")

    print(f"\n{'═'*72}")
    print(f"  RESULTS: {passed} passed | {failed} failed out of {passed + failed} assertions")
    print(f"{'═'*72}\n")