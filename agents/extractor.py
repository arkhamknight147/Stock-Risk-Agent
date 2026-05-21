# =============================================================================
# agents/extractor.py
# Agent 2 — Financial Data Extractor
# =============================================================================
#
# WHAT DOES THIS AGENT DO? (Plain English for a PM)
# --------------------------------------------------
# This agent is the system's "data collection engine." It takes the ticker
# symbol resolved by Agent 1 (router.py) and goes out to fetch ALL the
# real financial numbers needed for the risk scorecard.
#
# It is responsible for populating the entire `raw_financial_data` block
# in the central AppState. Think of it as a meticulous research analyst who
# opens multiple browser tabs, pulls numbers from each one, and fills in
# a structured data sheet — but does it in seconds, automatically.
#
# DATA SOURCES USED:
# ------------------
#   1. yfinance (Yahoo Finance API)
#      → CMP, 52W High/Low, P/E, P/B, ROE, Dividend Yield, Market Cap
#      → Last 4 quarters: Revenue, Net Income (PAT), Operating Income (EBITDA), EPS
#      → Major holders data (for promoter holding %)
#
#   2. Screener.in (web scraping via requests + BeautifulSoup)
#      → Promoter holding % and Promoter pledge % (more reliable than yfinance
#        for Indian-specific shareholding disclosures)
#
#   3. Google News RSS Feed (web scraping via requests + BeautifulSoup)
#      → Last 60 days of news headlines with date, source, and URL
#      → Targeted by company name + ticker for precision
#
# STRICT "NOT AVAILABLE" POLICY:
# --------------------------------
# If any data point cannot be fetched (API down, scraping blocked, field
# missing), we store the string "Not Available" in extra_data OR leave the
# typed field as None. We NEVER guess, interpolate, or hallucinate numbers.
# Every fetch is wrapped in try/except to enforce this.
#
# INPUT  : state.ticker      (e.g. "HDFCBANK.NS")
#          state.sector      (e.g. "Banks/NBFCs")
#          state.sector_kpis (list of 2 SectorKPI objects)
#          state.company_name (e.g. "HDFC Bank")
#
# OUTPUT : state.raw_financial_data (fully populated RawFinancialData object)
#
# =============================================================================

from __future__ import annotations

import re
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import quote_plus

import pandas as pd
import requests
import yfinance as yf
from bs4 import BeautifulSoup

# ---------------------------------------------------------------------------
# PATH SETUP — ensures we can import state.py from the project root
# ---------------------------------------------------------------------------
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from state import AppState, QuarterlyFinancials, SectorKPI

# ---------------------------------------------------------------------------
# CONSTANTS
# ---------------------------------------------------------------------------

# Standard browser-like headers to avoid being blocked by news sites.
# Many sites return 403 if they see Python's default "python-requests/x.x" UA.
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

# How long (in seconds) to wait for an HTTP response before giving up
REQUEST_TIMEOUT = 15

# INR conversion: yfinance returns financials in native currency units (usually INR).
# Yahoo Finance for Indian stocks reports financials in actual INR (not thousands/millions).
# We divide by 1 Crore (10,000,000) to get ₹ Crore values for display.
INR_TO_CRORE = 1_00_00_000  # 10 million = 1 Crore

# Not Available sentinel string — used consistently across all "missing" fields
NA = "Not Available"

# Number of news days to look back
NEWS_LOOKBACK_DAYS = 60


# =============================================================================
# SECTION 1: YFINANCE DATA FETCHERS
# Each function fetches ONE logical group of data and is independently
# wrapped in try/except so one failure doesn't cascade to others.
# =============================================================================

def _fetch_market_snapshot(ticker: yf.Ticker, full_ticker_str: str) -> Dict[str, Any]:
    """
    Fetches the point-in-time market data snapshot for a stock.

    DATA POINTS FETCHED:
    - CMP (Current Market Price)
    - Market Capitalisation
    - 52-Week High and Low
    - P/E Ratio (TTM — Trailing Twelve Months)
    - P/B Ratio (Price-to-Book)
    - ROE (Return on Equity, as %)
    - Dividend Yield (as %)

    SOURCE: yfinance `ticker.info` dictionary.
    NOTE: `ticker.info` is a single API call that returns ~100+ fields.
    We extract only what we need and discard the rest.

    Returns a dict with string keys mapping to float values or NA strings.
    """
    print(f"\n  [Extractor] 📊 Fetching market snapshot for {full_ticker_str}...")

    result: Dict[str, Any] = {
        "cmp":            NA,
        "market_cap_cr":  NA,
        "week_52_high":   NA,
        "week_52_low":    NA,
        "pe_ratio":       NA,
        "pb_ratio":       NA,
        "roe":            NA,
        "dividend_yield": NA,
    }

    try:
        info = ticker.info

        if not info or len(info) < 5:
            # yfinance returns a nearly-empty dict for invalid/delisted tickers
            print(f"  [Extractor] ⚠  ticker.info returned insufficient data for {full_ticker_str}")
            return result

        # ── CMP: try currentPrice first, then regularMarketPrice, then previousClose
        cmp_raw = (
            info.get("currentPrice")
            or info.get("regularMarketPrice")
            or info.get("previousClose")
        )
        if cmp_raw is not None:
            result["cmp"] = round(float(cmp_raw), 2)
            print(f"  [Extractor]   ✓ CMP              : ₹{result['cmp']}")
        else:
            print(f"  [Extractor]   ✗ CMP              : {NA}")

        # ── Market Cap (converted from INR to ₹ Crore)
        mcap_raw = info.get("marketCap")
        if mcap_raw is not None:
            result["market_cap_cr"] = round(float(mcap_raw) / INR_TO_CRORE, 2)
            print(f"  [Extractor]   ✓ Market Cap       : ₹{result['market_cap_cr']:,.0f} Cr")
        else:
            print(f"  [Extractor]   ✗ Market Cap       : {NA}")

        # ── 52-Week High
        high_52 = info.get("fiftyTwoWeekHigh")
        if high_52 is not None:
            result["week_52_high"] = round(float(high_52), 2)
            print(f"  [Extractor]   ✓ 52W High         : ₹{result['week_52_high']}")
        else:
            print(f"  [Extractor]   ✗ 52W High         : {NA}")

        # ── 52-Week Low
        low_52 = info.get("fiftyTwoWeekLow")
        if low_52 is not None:
            result["week_52_low"] = round(float(low_52), 2)
            print(f"  [Extractor]   ✓ 52W Low          : ₹{result['week_52_low']}")
        else:
            print(f"  [Extractor]   ✗ 52W Low          : {NA}")

        # ── P/E Ratio (TTM)
        pe_raw = info.get("trailingPE") or info.get("forwardPE")
        if pe_raw is not None:
            result["pe_ratio"] = round(float(pe_raw), 2)
            print(f"  [Extractor]   ✓ P/E (TTM)        : {result['pe_ratio']}x")
        else:
            print(f"  [Extractor]   ✗ P/E (TTM)        : {NA}")

        # ── P/B Ratio
        pb_raw = info.get("priceToBook")
        if pb_raw is not None:
            result["pb_ratio"] = round(float(pb_raw), 2)
            print(f"  [Extractor]   ✓ P/B Ratio        : {result['pb_ratio']}x")
        else:
            print(f"  [Extractor]   ✗ P/B Ratio        : {NA}")

        # ── ROE (yfinance returns as decimal, e.g. 0.172 for 17.2% — we convert to %)
        roe_raw = info.get("returnOnEquity")
        if roe_raw is not None:
            result["roe"] = round(float(roe_raw) * 100, 2)
            print(f"  [Extractor]   ✓ ROE              : {result['roe']}%")
        else:
            print(f"  [Extractor]   ✗ ROE              : {NA}")

        # ── Dividend Yield (yfinance returns as decimal, e.g. 0.011 for 1.1%)
        dy_raw = info.get("dividendYield") or info.get("trailingAnnualDividendYield")
        if dy_raw is not None:
            result["dividend_yield"] = round(float(dy_raw) * 100, 2)
            print(f"  [Extractor]   ✓ Dividend Yield   : {result['dividend_yield']}%")
        else:
            print(f"  [Extractor]   ✗ Dividend Yield   : {NA}")

    except Exception as exc:
        print(f"  [Extractor] ❌ Market snapshot fetch failed: {type(exc).__name__}: {exc}")

    return result


def _fetch_quarterly_financials(
    ticker: yf.Ticker, full_ticker_str: str
) -> List[QuarterlyFinancials]:
    """
    Fetches the last 4 quarters of financial results.

    DATA POINTS FETCHED PER QUARTER:
    - Revenue (Total Revenue)
    - PAT     (Net Income = Profit After Tax)
    - EBITDA  (Operating Income as proxy — closest available in yfinance)
    - EPS     (Basic EPS per share)

    SOURCE: yfinance quarterly financial statements:
        ticker.quarterly_financials   → P&L line items indexed by quarter date
        ticker.quarterly_earnings     → EPS per quarter (backup)

    CONVERSION: All monetary values divided by INR_TO_CRORE to get ₹ Crore.

    ORDERING: Most recent quarter first (index 0 = latest).

    FALLBACK: If a specific line item is missing for a quarter (e.g., EBITDA
    not reported for a bank), that field is stored as None — never as 0 or NA.
    None is the honest representation of "we don't have this number."
    """
    print(f"\n  [Extractor] 📋 Fetching quarterly financials for {full_ticker_str}...")

    quarters: List[QuarterlyFinancials] = []

    try:
        # yfinance returns a DataFrame where:
        #   - Columns are quarter-end dates (most recent first)
        #   - Rows are financial line items (e.g., "Total Revenue", "Net Income")
        fin_df = ticker.quarterly_financials  # P&L statement

        if fin_df is None or fin_df.empty:
            print(f"  [Extractor] ⚠  No quarterly financials available for {full_ticker_str}")
            return quarters

        # Normalise row index labels to lowercase for robust matching
        # (yfinance sometimes changes label capitalisation between versions)
        fin_df.index = [str(i).strip().lower() for i in fin_df.index]

        # Take only the 4 most-recent columns (quarters)
        cols = fin_df.columns[:4]

        # Helper: safely pull a float value from a DataFrame cell
        def _safe_get(df: pd.DataFrame, row_fragment: str, col) -> Optional[float]:
            """
            Finds a row whose label CONTAINS `row_fragment` (case-insensitive)
            and returns the float value at `col`. Returns None if missing/NaN.
            """
            matching = [r for r in df.index if row_fragment in r]
            if not matching:
                return None
            val = df.loc[matching[0], col]
            if pd.isna(val):
                return None
            return float(val)

        for i, col in enumerate(cols):
            # Convert pandas Timestamp column to a human-readable quarter label
            # e.g. 2024-12-31 → "Q3 FY2025" (Indian fiscal year: Apr–Mar)
            quarter_label = _date_to_indian_quarter(col)

            # ── Revenue
            revenue_raw = (
                _safe_get(fin_df, "total revenue", col)
                or _safe_get(fin_df, "operating revenue", col)
            )
            revenue_cr = round(revenue_raw / INR_TO_CRORE, 2) if revenue_raw else None

            # ── PAT (Net Income)
            pat_raw = (
                _safe_get(fin_df, "net income", col)
                or _safe_get(fin_df, "net profit", col)
            )
            pat_cr = round(pat_raw / INR_TO_CRORE, 2) if pat_raw else None

            # ── EBITDA (yfinance reports Operating Income as closest proxy)
            ebitda_raw = (
                _safe_get(fin_df, "operating income", col)
                or _safe_get(fin_df, "ebitda", col)
                or _safe_get(fin_df, "gross profit", col)  # last resort
            )
            ebitda_cr = round(ebitda_raw / INR_TO_CRORE, 2) if ebitda_raw else None

            # ── EPS — try quarterly_earnings first, then calculate from PAT
            eps = _fetch_eps_for_quarter(ticker, col, pat_raw)

            q = QuarterlyFinancials(
                quarter_label=quarter_label,
                revenue_cr=revenue_cr,
                pat_cr=pat_cr,
                ebitda_cr=ebitda_cr,
                eps=eps,
            )
            quarters.append(q)

            status_parts = [
                f"Rev=₹{revenue_cr:,.0f}Cr" if revenue_cr else "Rev=N/A",
                f"PAT=₹{pat_cr:,.0f}Cr"    if pat_cr    else "PAT=N/A",
                f"EBITDA=₹{ebitda_cr:,.0f}Cr" if ebitda_cr else "EBITDA=N/A",
                f"EPS=₹{eps}"               if eps       else "EPS=N/A",
            ]
            print(f"  [Extractor]   ✓ {quarter_label:12s} | {' | '.join(status_parts)}")

    except Exception as exc:
        print(f"  [Extractor] ❌ Quarterly financials fetch failed: {type(exc).__name__}: {exc}")

    if not quarters:
        print(f"  [Extractor] ⚠  No quarterly data extracted for {full_ticker_str}")

    return quarters


def _fetch_eps_for_quarter(
    ticker: yf.Ticker, col_date: Any, pat_raw: Optional[float]
) -> Optional[float]:
    """
    Attempts to retrieve EPS for a specific quarter using two methods:

    Method 1: ticker.quarterly_earnings DataFrame
        This DataFrame has "Earnings" (= EPS) and "Revenue" indexed by quarter date.
        We find the row whose date is within 5 days of `col_date`.

    Method 2: Divide PAT by shares outstanding
        Used if Method 1 fails. EPS = PAT / shares_outstanding.
        This is an approximation (uses diluted shares, not basic).

    Returns None if both methods fail.
    """
    try:
        earnings_df = ticker.quarterly_earnings
        if earnings_df is not None and not earnings_df.empty:
            # earnings_df index is quarter-end dates — find closest match
            for idx in earnings_df.index:
                if abs((pd.Timestamp(idx) - pd.Timestamp(col_date)).days) <= 95:
                    val = earnings_df.loc[idx, "Earnings"]
                    if not pd.isna(val):
                        return round(float(val), 2)
    except Exception:
        pass

    # Method 2: calculate from PAT ÷ shares outstanding
    try:
        if pat_raw:
            info = ticker.info or {}
            shares = info.get("sharesOutstanding") or info.get("impliedSharesOutstanding")
            if shares and shares > 0:
                eps = pat_raw / float(shares)
                return round(eps, 2)
    except Exception:
        pass

    return None


def _fetch_shareholding_from_yfinance(
    ticker: yf.Ticker, full_ticker_str: str
) -> Dict[str, Any]:
    """
    Attempts to extract promoter holding data from yfinance's
    `major_holders` and `institutional_holders` DataFrames.

    IMPORTANT CAVEAT:
    yfinance's holder data for Indian stocks is often incomplete because:
    - Yahoo Finance doesn't parse BSE/NSE shareholding pattern filings
    - It only shows broad categories like "Insiders" and "Institutions"

    We use this as a FIRST ATTEMPT. The Screener.in scraper below is the
    more reliable source for Indian promoter + pledge data.

    Returns a dict with:
        "promoter_holding_pct" : float or NA
        "promoter_pledge_pct"  : float or NA   ← almost always NA from yfinance
    """
    print(f"\n  [Extractor] 🏦 Fetching shareholding data (yfinance) for {full_ticker_str}...")

    result = {
        "promoter_holding_pct": NA,
        "promoter_pledge_pct": NA,
    }

    try:
        major = ticker.major_holders
        if major is not None and not major.empty:
            # major_holders is a 2-column DataFrame: [value, description]
            # We look for "% of Shares Held by Insiders" row
            for _, row in major.iterrows():
                desc = str(row.iloc[1]).lower()
                val  = str(row.iloc[0]).replace("%", "").strip()
                if "insider" in desc:
                    try:
                        result["promoter_holding_pct"] = round(float(val), 2)
                        print(f"  [Extractor]   ✓ Insider (Promoter) Holding : {result['promoter_holding_pct']}%")
                    except ValueError:
                        pass
        else:
            print(f"  [Extractor]   ✗ major_holders not available")

    except Exception as exc:
        print(f"  [Extractor]   ✗ yfinance shareholding error: {type(exc).__name__}: {exc}")

    return result


# =============================================================================
# SECTION 2: SCREENER.IN SCRAPER
# Screener.in is the most reliable public source for Indian stock
# shareholding patterns including promoter pledge data.
# =============================================================================

def _scrape_screener_shareholding(company_name: str, ticker_symbol: str) -> Dict[str, Any]:
    """
    Scrapes Screener.in for Indian-specific shareholding pattern data.

    WHY SCREENER.IN?
    Screener.in aggregates BSE/NSE quarterly shareholding pattern filings
    and presents them in clean HTML tables. It is the go-to site for
    Indian retail investors and research analysts.

    WHAT WE EXTRACT:
    - Promoter holding %  (from "Shareholding Pattern" section)
    - Promoter pledge %   (from pledged shares disclosure)

    URL STRATEGY:
    Screener.in uses the NSE symbol directly in its URL:
        https://www.screener.in/company/HDFCBANK/consolidated/

    FALLBACK:
    If the direct URL fails, we try the search endpoint:
        https://www.screener.in/api/company/search/?q=HDFCBANK

    Returns a dict with "promoter_holding_pct" and "promoter_pledge_pct".
    Both default to NA if scraping fails.
    """
    print(f"\n  [Extractor] 🔍 Scraping Screener.in for shareholding data...")

    result = {
        "promoter_holding_pct": NA,
        "promoter_pledge_pct":  NA,
    }

    # Strip exchange suffix to get the bare symbol
    bare_symbol = ticker_symbol.replace(".NS", "").replace(".BO", "").upper()

    urls_to_try = [
        f"https://www.screener.in/company/{bare_symbol}/consolidated/",
        f"https://www.screener.in/company/{bare_symbol}/",
    ]

    soup: Optional[BeautifulSoup] = None

    for url in urls_to_try:
        try:
            print(f"  [Extractor]   → Trying: {url}")
            resp = requests.get(url, headers=HEADERS, timeout=REQUEST_TIMEOUT)

            if resp.status_code == 200:
                soup = BeautifulSoup(resp.text, "lxml")
                print(f"  [Extractor]   ✓ Screener.in page loaded (HTTP 200)")
                break
            elif resp.status_code == 404:
                print(f"  [Extractor]   ✗ 404 Not Found: {url}")
            else:
                print(f"  [Extractor]   ✗ HTTP {resp.status_code}: {url}")

        except requests.exceptions.Timeout:
            print(f"  [Extractor]   ✗ Timeout on {url}")
        except requests.exceptions.ConnectionError:
            print(f"  [Extractor]   ✗ Connection error on {url}")
        except Exception as exc:
            print(f"  [Extractor]   ✗ Unexpected error on {url}: {exc}")

    if soup is None:
        print(f"  [Extractor]   ✗ Screener.in scraping failed for {bare_symbol}")
        return result

    # ── Parse shareholding pattern table ──────────────────────────────────
    try:
        # Screener.in renders a "Shareholding Pattern" section with a table
        # The promoter row is the first data row and is labelled "Promoters"

        # Strategy 1: Look for a <section> with id="shareholding"
        section = soup.find("section", id="shareholding")

        if not section:
            # Strategy 2: Search all tables for one containing "Promoters"
            section = soup

        tables = section.find_all("table") if section else []

        for table in tables:
            rows = table.find_all("tr")
            for row in rows:
                cells = row.find_all(["td", "th"])
                if not cells:
                    continue

                row_label = cells[0].get_text(strip=True).lower()

                # ── Promoter holding %
                if "promoter" in row_label and "pledg" not in row_label:
                    # The most recent quarter value is usually in cells[1] or cells[-1]
                    # Screener shows quarters left-to-right: oldest → newest
                    # We take cells[-1] for the latest value
                    for cell in reversed(cells[1:]):
                        val_text = cell.get_text(strip=True).replace("%", "").strip()
                        try:
                            pct = float(val_text)
                            if 0 < pct <= 100:
                                result["promoter_holding_pct"] = round(pct, 2)
                                print(f"  [Extractor]   ✓ Promoter Holding : {pct}%")
                                break
                        except ValueError:
                            continue

                # ── Promoter pledge %
                if "pledg" in row_label:
                    for cell in reversed(cells[1:]):
                        val_text = cell.get_text(strip=True).replace("%", "").strip()
                        try:
                            pct = float(val_text)
                            if 0 <= pct <= 100:
                                result["promoter_pledge_pct"] = round(pct, 2)
                                print(f"  [Extractor]   ✓ Promoter Pledge  : {pct}%")
                                break
                        except ValueError:
                            continue

    except Exception as exc:
        print(f"  [Extractor]   ✗ Screener.in parse error: {type(exc).__name__}: {exc}")

    # Report NA fields
    if result["promoter_holding_pct"] == NA:
        print(f"  [Extractor]   ✗ Promoter Holding : {NA}")
    if result["promoter_pledge_pct"] == NA:
        print(f"  [Extractor]   ✗ Promoter Pledge  : {NA}")

    return result


# =============================================================================
# SECTION 3: NEWS SCRAPER
# Fetches 60-day news headlines using Google News RSS feed.
# =============================================================================

def _scrape_news_headlines(company_name: str, ticker_symbol: str) -> List[Dict[str, str]]:
    """
    Scrapes the last 60 days of news headlines for the target company
    using the Google News RSS feed.

    WHY GOOGLE NEWS RSS?
    - Publicly accessible without authentication or API keys
    - Aggregates content from Economic Times, Moneycontrol, Business Standard,
      LiveMint, NDTV Profit, and other Indian financial media
    - Returns structured XML (RSS format) that BeautifulSoup can parse cleanly
    - No JavaScript rendering required (unlike scraping dynamic news sites)

    RSS URL FORMAT:
        https://news.google.com/rss/search?q={query}&hl=en-IN&gl=IN&ceid=IN:en

    QUERY STRATEGY:
    We build two queries and merge results to maximise coverage:
        1. Company name + "NSE" (e.g., "HDFC Bank NSE stock")
        2. Bare ticker symbol   (e.g., "HDFCBANK stock India")

    DEDUPLICATION:
    Headlines already seen (by URL) are skipped in the second query pass.

    DATE FILTERING:
    RSS items include a <pubDate> field. We parse it and discard anything
    older than NEWS_LOOKBACK_DAYS (60 days).

    Returns a list of dicts, each with keys:
        "date"     : "YYYY-MM-DD"
        "headline" : str
        "source"   : str (e.g., "The Economic Times")
        "url"      : str
    """
    print(f"\n  [Extractor] 📰 Fetching news headlines (last {NEWS_LOOKBACK_DAYS} days)...")

    headlines: List[Dict[str, str]] = []
    seen_urls: set = set()

    bare_symbol = ticker_symbol.replace(".NS", "").replace(".BO", "").upper()
    cutoff_date = datetime.utcnow() - timedelta(days=NEWS_LOOKBACK_DAYS)

    # Build search queries — two different angles for broader coverage
    queries = [
        f'"{company_name}" stock NSE India',
        f"{bare_symbol} NSE share price India",
    ]

    rss_base = "https://news.google.com/rss/search"

    for query_idx, query in enumerate(queries, start=1):
        encoded_query = quote_plus(query)
        url = f"{rss_base}?q={encoded_query}&hl=en-IN&gl=IN&ceid=IN:en"

        print(f"  [Extractor]   → Query {query_idx}: '{query}'")

        try:
            time.sleep(1.0)  # polite delay between RSS requests
            resp = requests.get(url, headers=HEADERS, timeout=REQUEST_TIMEOUT)

            if resp.status_code != 200:
                print(f"  [Extractor]   ✗ Google News RSS returned HTTP {resp.status_code}")
                continue

            # Parse RSS XML with BeautifulSoup using the "xml" parser
            # Fall back to "lxml" if the xml parser isn't installed
            try:
                rss_soup = BeautifulSoup(resp.content, "xml")
            except Exception:
                rss_soup = BeautifulSoup(resp.content, "lxml")

            items = rss_soup.find_all("item")

            if not items:
                print(f"  [Extractor]   ✗ No RSS items found for query {query_idx}")
                continue

            for item in items:
                # ── Parse pub date ──
                pub_date_str = _get_tag_text(item, "pubDate") or ""
                pub_date     = _parse_rss_date(pub_date_str)

                if pub_date is None or pub_date < cutoff_date:
                    continue  # Skip items older than our lookback window

                # ── Parse URL ──
                raw_url = (
                    _get_tag_text(item, "link")
                    or _get_tag_text(item, "guid")
                    or ""
                )
                # Google News wraps URLs — extract the actual destination
                article_url = _extract_google_news_url(raw_url)

                if article_url in seen_urls:
                    continue  # Deduplicate
                seen_urls.add(article_url)

                # ── Parse headline ──
                headline = _get_tag_text(item, "title") or ""
                headline = _clean_headline(headline)

                if not headline:
                    continue

                # ── Parse source (Google News puts source in <source> tag) ──
                source_tag  = item.find("source")
                source_name = source_tag.get_text(strip=True) if source_tag else "Unknown Source"

                headlines.append({
                    "date":     pub_date.strftime("%Y-%m-%d"),
                    "headline": headline,
                    "source":   source_name,
                    "url":      article_url,
                })

        except requests.exceptions.Timeout:
            print(f"  [Extractor]   ✗ Timeout fetching news for query {query_idx}")
        except requests.exceptions.ConnectionError:
            print(f"  [Extractor]   ✗ Connection error fetching news for query {query_idx}")
        except Exception as exc:
            print(f"  [Extractor]   ✗ News fetch error for query {query_idx}: {type(exc).__name__}: {exc}")

    # Sort by date descending (most recent first)
    headlines.sort(key=lambda x: x["date"], reverse=True)

    print(f"  [Extractor]   ✓ Total headlines fetched: {len(headlines)}")

    if not headlines:
        print(f"  [Extractor]   ⚠  No news headlines found. Storing empty list.")

    return headlines


# =============================================================================
# SECTION 4: UTILITY FUNCTIONS
# Small helpers used by the fetch/scrape functions above.
# =============================================================================

def _date_to_indian_quarter(date_val: Any) -> str:
    """
    Converts a pandas Timestamp (quarter-end date) to an Indian fiscal
    quarter label like "Q3 FY2025".

    Indian Fiscal Year (FY) runs April 1 → March 31:
        Q1: April   – June      (month 4–6)
        Q2: July    – September (month 7–9)
        Q3: October – December  (month 10–12)
        Q4: January – March     (month 1–3)

    Note: A date of December 31, 2024 falls in Q3 FY2025 because FY2025
    spans April 2024 to March 2025.

    Args:
        date_val: A pandas Timestamp or datetime-like object.

    Returns:
        A string like "Q3 FY2025". Returns "Unknown Quarter" on parse failure.
    """
    try:
        ts = pd.Timestamp(date_val)
        month = ts.month
        year  = ts.year

        if month in (4, 5, 6):
            q, fy = 1, year + 1
        elif month in (7, 8, 9):
            q, fy = 2, year + 1
        elif month in (10, 11, 12):
            q, fy = 3, year + 1
        else:  # Jan, Feb, Mar
            q, fy = 4, year

        return f"Q{q} FY{fy}"

    except Exception:
        return "Unknown Quarter"


def _parse_rss_date(date_str: str) -> Optional[datetime]:
    """
    Parses an RSS <pubDate> string into a Python datetime object.

    RSS dates follow RFC 2822 format:
        "Mon, 15 Apr 2024 10:30:00 GMT"
        "Mon, 15 Apr 2024 10:30:00 +0530"

    We try multiple format strings to handle variations across RSS feeds.

    Returns None if parsing fails.
    """
    formats = [
        "%a, %d %b %Y %H:%M:%S %Z",    # e.g. "Mon, 15 Apr 2024 10:30:00 GMT"
        "%a, %d %b %Y %H:%M:%S %z",    # e.g. "Mon, 15 Apr 2024 10:30:00 +0530"
        "%Y-%m-%dT%H:%M:%SZ",          # ISO 8601 with Z
        "%Y-%m-%dT%H:%M:%S%z",         # ISO 8601 with offset
    ]
    for fmt in formats:
        try:
            return datetime.strptime(date_str.strip(), fmt).replace(tzinfo=None)
        except (ValueError, AttributeError):
            continue
    return None


def _get_tag_text(element: Any, tag_name: str) -> Optional[str]:
    """
    Safely extracts text content from a BeautifulSoup tag.
    Returns None if the tag doesn't exist or has no text.
    """
    tag = element.find(tag_name)
    if tag is None:
        return None
    text = tag.get_text(strip=True)
    return text if text else None


def _extract_google_news_url(raw_url: str) -> str:
    """
    Google News RSS items sometimes contain a Google redirect URL
    (https://news.google.com/rss/articles/...) instead of the actual
    article URL. We return the raw URL as-is; following redirects would
    require additional HTTP calls. The Sentiment Agent (downstream) can
    optionally resolve these when needed.
    """
    return raw_url.strip() if raw_url else ""


def _clean_headline(text: str) -> str:
    """
    Cleans a raw RSS headline:
    - Strips leading/trailing whitespace
    - Removes HTML entities (e.g., "&amp;" → "&", "&#39;" → "'")
    - Collapses multiple spaces
    - Strips source attribution appended by Google News
      (e.g., "HDFC Bank Q4 results — Economic Times" → "HDFC Bank Q4 results")
    """
    if not text:
        return ""

    # Decode common HTML entities
    text = text.replace("&amp;", "&").replace("&#39;", "'").replace("&quot;", '"').replace("&lt;", "<").replace("&gt;", ">")

    # Remove source suffix appended by some RSS feeds (" - Source Name" at end)
    text = re.sub(r"\s*[-–—]\s*[^-–—]{3,50}$", "", text).strip()

    # Collapse multiple whitespace
    text = re.sub(r"\s+", " ", text).strip()

    return text


def _safe_float(value: Any) -> Optional[float]:
    """
    Attempts to cast any value to float.
    Returns None on failure — never raises an exception.
    Used as a safety net throughout the agent.
    """
    if value is None:
        return None
    try:
        f = float(value)
        # Reject NaN and Infinity — not useful for financial data
        if pd.isna(f) or f == float("inf") or f == float("-inf"):
            return None
        return f
    except (ValueError, TypeError):
        return None


# =============================================================================
# SECTION 5: STATE WRITER
# Applies all fetched data into the AppState object in one controlled place.
# All writes go through this function to keep state mutation auditable.
# =============================================================================

def _write_to_state(
    state: AppState,
    snapshot: Dict[str, Any],
    quarters: List[QuarterlyFinancials],
    shareholding: Dict[str, Any],
    news: List[Dict[str, str]],
) -> None:
    """
    Writes all fetched data into state.raw_financial_data.

    WHY A SEPARATE WRITE FUNCTION?
    Keeping all state mutations in one place means:
    1. Easy to audit exactly what gets written (no scattered state.x = y)
    2. NA-handling logic is centralised — one place to update if schema changes
    3. Easier to unit-test the write logic independently of the fetch logic

    NA POLICY:
    - For Optional[float] fields: write None if value is NA string or None
    - For extra_data dict: write the NA string so it's visible in the report
    """
    rfd = state.raw_financial_data

    # ── Market Snapshot Fields ────────────────────────────────────────────
    rfd.cmp            = _safe_float(snapshot.get("cmp"))
    rfd.week_52_high   = _safe_float(snapshot.get("week_52_high"))
    rfd.week_52_low    = _safe_float(snapshot.get("week_52_low"))
    rfd.pe_ratio       = _safe_float(snapshot.get("pe_ratio"))
    rfd.pb_ratio       = _safe_float(snapshot.get("pb_ratio"))
    rfd.roe            = _safe_float(snapshot.get("roe"))
    rfd.dividend_yield = _safe_float(snapshot.get("dividend_yield"))

    # Market cap goes into extra_data (no dedicated field in schema)
    rfd.extra_data["market_cap_cr"] = snapshot.get("market_cap_cr", NA)

    # ── Quarterly Financials ─────────────────────────────────────────────
    rfd.quarterly_financials = quarters[:4]  # enforce max 4

    # ── Shareholding ──────────────────────────────────────────────────────
    pledge_val = shareholding.get("promoter_pledge_pct", NA)
    rfd.promoter_pledge_pct = _safe_float(pledge_val) if pledge_val != NA else None

    # Promoter holding % goes into extra_data (no dedicated typed field in schema)
    rfd.extra_data["promoter_holding_pct"] = shareholding.get("promoter_holding_pct", NA)

    # ── News Headlines ────────────────────────────────────────────────────
    rfd.news_headlines = news

    # ── Metadata ─────────────────────────────────────────────────────────
    rfd.extra_data["data_fetch_timestamp"] = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
    rfd.extra_data["data_source_primary"]  = "Yahoo Finance (yfinance)"
    rfd.extra_data["data_source_holdings"] = "Screener.in"
    rfd.extra_data["data_source_news"]     = "Google News RSS"


# =============================================================================
# SECTION 6: THE MAIN AGENT FUNCTION
# Single public entry point called by the orchestrator.
# =============================================================================

def run(state: AppState) -> AppState:
    """
    =========================================================================
    Agent 2 — Extractor: Financial Data Extraction Engine
    =========================================================================

    ENTRY POINT called by the orchestrator:
        from agents.extractor import run
        state = run(state)

    PREREQUISITES:
        Agent 1 (router) must have already run successfully.
        state.ticker must be set (e.g. "HDFCBANK.NS").

    WHAT IT DOES:
        1. Validates prerequisites (ticker must be present)
        2. Initialises a yfinance Ticker object (single reusable connection)
        3. Fetches market snapshot (CMP, 52W, P/E, P/B, ROE, Div Yield)
        4. Fetches 4 quarters of financials (Revenue, PAT, EBITDA, EPS)
        5. Fetches shareholding via yfinance (promoter holding, first attempt)
        6. Scrapes Screener.in for promoter pledge % (more reliable for India)
        7. Scrapes Google News RSS for 60-day headlines
        8. Writes all data into state.raw_financial_data
        9. Marks itself complete in state.completed_agents

    IDEMPOTENCY:
        If already marked complete, returns immediately without re-fetching.

    PARTIAL FAILURE HANDLING:
        Each data source is fetched independently. If one fails (e.g., news
        scraper is blocked), the others still write their data successfully.
        The agent marks itself complete even with partial data — downstream
        scoring agents handle None/NA values gracefully.

    Args:
        state (AppState): Shared application state. Must have state.ticker set.

    Returns:
        AppState: Same state object with state.raw_financial_data populated.
    """

    agent_name = "extractor"

    # ─── IDEMPOTENCY CHECK ────────────────────────────────────────────────
    if state.is_agent_complete(agent_name):
        print(f"\n[Extractor] Already complete for '{state.company_name}'. Skipping.")
        return state

    print(f"\n{'='*68}")
    print(f"  AGENT 2 — EXTRACTOR: {state.company_name} ({state.ticker})")
    print(f"{'='*68}")

    # ─── PREREQUISITE VALIDATION ──────────────────────────────────────────
    if not state.ticker:
        err = "state.ticker is not set. Run Agent 1 (router) first."
        print(f"\n[Extractor] ❌ {err}")
        state.log_error(agent_name, err)
        return state

    full_ticker = state.ticker  # e.g. "HDFCBANK.NS"

    # ─── INITIALISE YFINANCE TICKER ───────────────────────────────────────
    # We create ONE Ticker object and reuse it for all yfinance calls.
    # This is more efficient than creating a new Ticker per call.
    try:
        print(f"\n[Extractor] 🔗 Initialising yfinance Ticker: {full_ticker}")
        yf_ticker = yf.Ticker(full_ticker)
        print(f"[Extractor] ✅ yfinance Ticker ready")
    except Exception as exc:
        err = f"Failed to initialise yfinance Ticker for {full_ticker}: {exc}"
        print(f"[Extractor] ❌ {err}")
        state.log_error(agent_name, err)
        return state

    # ─── STEP 1: MARKET SNAPSHOT ──────────────────────────────────────────
    snapshot: Dict[str, Any] = {}
    try:
        snapshot = _fetch_market_snapshot(yf_ticker, full_ticker)
    except Exception as exc:
        print(f"\n[Extractor] ❌ Market snapshot fetch crashed: {exc}")
        state.log_error(agent_name, f"market_snapshot: {exc}")

    # ─── STEP 2: QUARTERLY FINANCIALS ────────────────────────────────────
    quarters: List[QuarterlyFinancials] = []
    try:
        quarters = _fetch_quarterly_financials(yf_ticker, full_ticker)
    except Exception as exc:
        print(f"\n[Extractor] ❌ Quarterly financials fetch crashed: {exc}")
        state.log_error(agent_name, f"quarterly_financials: {exc}")

    # ─── STEP 3: SHAREHOLDING (yfinance — first attempt) ─────────────────
    shareholding: Dict[str, Any] = {
        "promoter_holding_pct": NA,
        "promoter_pledge_pct":  NA,
    }
    try:
        shareholding = _fetch_shareholding_from_yfinance(yf_ticker, full_ticker)
    except Exception as exc:
        print(f"\n[Extractor] ❌ yfinance shareholding fetch crashed: {exc}")

    # ─── STEP 4: SHAREHOLDING + PLEDGE (Screener.in — more reliable) ─────
    # Overwrite the yfinance result with Screener data where available
    # (Screener is more accurate for Indian promoter disclosures)
    try:
        screener_data = _scrape_screener_shareholding(state.company_name, full_ticker)

        # Only overwrite if Screener returned actual data (not NA)
        if screener_data.get("promoter_holding_pct") != NA:
            shareholding["promoter_holding_pct"] = screener_data["promoter_holding_pct"]
            print(f"  [Extractor]   ✅ Screener overrode promoter holding: {shareholding['promoter_holding_pct']}%")

        if screener_data.get("promoter_pledge_pct") != NA:
            shareholding["promoter_pledge_pct"] = screener_data["promoter_pledge_pct"]
            print(f"  [Extractor]   ✅ Screener overrode promoter pledge: {shareholding['promoter_pledge_pct']}%")

    except Exception as exc:
        print(f"\n[Extractor] ❌ Screener.in scraper crashed: {exc}")
        state.log_error(agent_name, f"screener_scraping: {exc}")

    # ─── STEP 5: NEWS HEADLINES ───────────────────────────────────────────
    news: List[Dict[str, str]] = []
    try:
        news = _scrape_news_headlines(state.company_name, full_ticker)
    except Exception as exc:
        print(f"\n[Extractor] ❌ News scraper crashed: {exc}")
        state.log_error(agent_name, f"news_scraping: {exc}")

    # ─── STEP 6: WRITE ALL DATA TO STATE ─────────────────────────────────
    print(f"\n  [Extractor] 💾 Writing all fetched data to AppState...")
    try:
        _write_to_state(state, snapshot, quarters, shareholding, news)
        print(f"  [Extractor]   ✓ State updated successfully")
    except Exception as exc:
        err = f"State write failed: {type(exc).__name__}: {exc}"
        print(f"  [Extractor]   ❌ {err}")
        state.log_error(agent_name, err)
        return state

    # ─── STEP 7: MARK COMPLETE + PRINT SUMMARY ───────────────────────────
    state.mark_agent_complete(agent_name)

    rfd = state.raw_financial_data
    print(f"\n{'='*68}")
    print(f"  EXTRACTOR COMPLETE — DATA SUMMARY")
    print(f"{'='*68}")
    print(f"  Ticker          : {full_ticker}")
    print(f"  CMP             : ₹{rfd.cmp or NA}")
    print(f"  52W High / Low  : ₹{rfd.week_52_high or NA} / ₹{rfd.week_52_low or NA}")
    print(f"  P/E             : {rfd.pe_ratio or NA}x")
    print(f"  P/B             : {rfd.pb_ratio or NA}x")
    print(f"  ROE             : {rfd.roe or NA}%")
    print(f"  Dividend Yield  : {rfd.dividend_yield or NA}%")
    print(f"  Market Cap      : ₹{rfd.extra_data.get('market_cap_cr', NA)} Cr")
    print(f"  Quarters Loaded : {len(rfd.quarterly_financials)}")
    print(f"  Promoter Hold % : {rfd.extra_data.get('promoter_holding_pct', NA)}")
    print(f"  Promoter Pledge%: {rfd.promoter_pledge_pct if rfd.promoter_pledge_pct is not None else NA}")
    print(f"  News Headlines  : {len(rfd.news_headlines)} articles (last {NEWS_LOOKBACK_DAYS} days)")
    print(f"  Errors Logged   : {list(state.errors.keys())}")
    print(f"{'='*68}\n")

    return state


# =============================================================================
# SECTION 7: STANDALONE TEST HARNESS
# Run this file directly: $ python agents/extractor.py
# Tests the full pipeline with a well-known Indian stock.
# =============================================================================

if __name__ == "__main__":
    # We need state.py on the path — handled by PATH SETUP at the top
    from state import AppState, SectorKPI

    print("\n" + "=" * 68)
    print("  AGENT 2 — EXTRACTOR : STANDALONE TEST")
    print("=" * 68)

    # ── Simulate what Agent 1 (router) would have produced ──
    test_state = AppState(company_name="HDFC Bank")
    test_state.ticker = "HDFCBANK.NS"
    test_state.sector = "Banks/NBFCs"
    test_state.sector_kpis = [
        SectorKPI(
            name="Net Interest Margin (NIM)",
            unit="%",
            description="Spread between lending and borrowing rates.",
        ),
        SectorKPI(
            name="Gross NPA Ratio (GNPA%)",
            unit="%",
            description="Percentage of bad loans in total loan book.",
        ),
    ]
    test_state.mark_agent_complete("router")

    # ── Run this agent ──
    result_state = run(test_state)

    # ── Print the resulting state as JSON ──
    print("\n── Raw Financial Data (JSON) ──")
    import json
    rfd_dict = result_state.raw_financial_data.model_dump()
    # Truncate news list for readability
    if rfd_dict.get("news_headlines"):
        rfd_dict["news_headlines"] = rfd_dict["news_headlines"][:3]
        rfd_dict["news_headlines"].append({"note": f"... and {len(result_state.raw_financial_data.news_headlines) - 3} more"})
    print(json.dumps(rfd_dict, indent=2, default=str))