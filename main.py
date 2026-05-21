#!/usr/bin/env python3
# =============================================================================
# main.py
# Agentic Workflow Orchestrator — Indian Stock Risk Scorecard
# =============================================================================
#
# WHAT IS THIS FILE?
# ------------------
# This is the single entry-point for the entire multi-agent system.
# Run it from your terminal and it does everything automatically:
#
#   $ python main.py
#   Enter Indian Company Name: HDFC Bank
#   ...  (pipeline runs) ...
#   ✅  Report saved → output_risk_report.html
#
# HOW IT WORKS (for a non-technical PM):
# ----------------------------------------
# Think of this file as the "project manager" who:
#   1. Asks you for the company name (your only required input)
#   2. Creates a blank "work-order" (the AppState object)
#   3. Hands it to four specialists IN ORDER:
#
#       ┌─────────────────────────────────────────────────────────┐
#       │  YOU → company name                                     │
#       │                                                         │
#       │  [1] ROUTER AGENT    → finds NSE ticker + sector + KPIs │
#       │  [2] EXTRACTOR AGENT → fetches all financial data       │
#       │  [3] ANALYST AGENT   → scores, rates, and verdicts      │
#       │  [4] DESIGNER AGENT  → renders polished HTML report     │
#       │                                                         │
#       │  OUTPUT → output_risk_report.html (open in browser)     │
#       └─────────────────────────────────────────────────────────┘
#
#   4. After each agent finishes, it prints a clear status update
#   5. If an agent fails, it reports the error and decides whether
#      to stop or try to continue with the remaining agents
#   6. Saves the final HTML report to disk
#
# PIPELINE RESILIENCE:
# ---------------------
# The orchestrator uses a "best-effort" strategy:
#   - Critical failures (Router can't find ticker) → ABORT with clear message
#   - Non-critical failures (news scraper blocked) → WARN and continue
#   - Each agent's errors are captured in state.errors for post-mortem review
#
# HOW TO RUN:
# -----------
#   python main.py                   # interactive mode (prompts for input)
#   python main.py "Infosys"         # pass company name as CLI argument
#   python main.py --company "TCS"   # named argument form
#
# =============================================================================

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import traceback
from datetime import datetime
from pathlib import Path

import pytz

# ---------------------------------------------------------------------------
# ROOT PATH SETUP
# Ensures Python can find state.py and the agents/ package from any
# working directory the user runs main.py from.
# ---------------------------------------------------------------------------
ROOT_DIR = Path(__file__).resolve().parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

# ---------------------------------------------------------------------------
# PROJECT IMPORTS
# We import lazily inside each step so that a missing library in one agent
# doesn't prevent the others from loading. Any ImportError is caught here
# with a helpful install instruction.
# ---------------------------------------------------------------------------
try:
    from state import AppState
except ImportError as e:
    print(f"\n❌  Cannot import 'state.py'. Make sure you are running this script")
    print(f"    from the StockAgent/ project root directory.")
    print(f"    Error: {e}\n")
    sys.exit(1)

try:
    from agents import router, extractor, analyst, designer
except ImportError as e:
    print(f"\n❌  Cannot import agents. Verify the 'agents/' folder exists and")
    print(f"    all four files are present: router.py, extractor.py,")
    print(f"    analyst.py, designer.py")
    print(f"    Error: {e}\n")
    sys.exit(1)

IST = pytz.timezone("Asia/Kolkata")

# =============================================================================
# SECTION 1: CONSOLE DISPLAY HELPERS
# All terminal output is routed through these functions so that:
#   (a) the visual style is consistent throughout the run
#   (b) a PM reading the console always knows what is happening
#   (c) timestamps are attached to every major event
# =============================================================================

# ANSI colour codes — automatically disabled on Windows CMD if not supported
_SUPPORTS_COLOR = (
    sys.stdout.isatty()
    and os.environ.get("TERM", "") != "dumb"
    and sys.platform != "win32"
) or os.environ.get("FORCE_COLOR", "0") == "1"

def _c(text: str, code: str) -> str:
    """Wraps text in an ANSI escape sequence if the terminal supports it."""
    if not _SUPPORTS_COLOR:
        return text
    return f"\033[{code}m{text}\033[0m"

def _gold(t: str)  -> str: return _c(t, "33")      # yellow/gold
def _green(t: str) -> str: return _c(t, "32")      # green
def _red(t: str)   -> str: return _c(t, "31")      # red
def _cyan(t: str)  -> str: return _c(t, "36")      # cyan
def _bold(t: str)  -> str: return _c(t, "1")       # bold
def _dim(t: str)   -> str: return _c(t, "2")       # dim/grey
def _blue(t: str)  -> str: return _c(t, "34")      # blue

def _now() -> str:
    """Returns current IST time as a short string for log prefixes."""
    return datetime.now(IST).strftime("%H:%M:%S")

def _line(char: str = "─", width: int = 68) -> str:
    return char * width

def _header_banner() -> None:
    """Prints the application title banner at startup."""
    print()
    print(_gold(_line("═")))
    print(_bold(_gold("  ₹  NSE · BSE MULTI-AGENT RISK SCORECARD  ₹")))
    print(_dim(  "     Automated Equity Research Pipeline · v1.0"))
    print(_gold(_line("═")))
    print()

def _section_start(step: int, total: int, agent_name: str, description: str) -> None:
    """
    Prints a highly visible banner at the START of each agent's execution.
    Designed so a PM glancing at the terminal immediately knows what's running.

    Example output:
    ────────────────────────────────────────────────────────────────────
      [14:32:01]  STEP 1 / 4  ▶  ROUTER AGENT
                  Resolving ticker symbol, detecting sector, mapping KPIs
    ────────────────────────────────────────────────────────────────────
    """
    print()
    print(_dim(_line()))
    tag   = _bold(_cyan(f"  STEP {step} / {total}"))
    arrow = _gold("  ▶  ")
    name  = _bold(f"{agent_name.upper()} AGENT")
    ts    = _dim(f"[{_now()}]")
    print(f"{ts}{tag}{arrow}{name}")
    print(_dim(f"              {description}"))
    print(_dim(_line()))

def _section_end(
    step: int,
    agent_name: str,
    success: bool,
    elapsed: float,
    detail: str = "",
) -> None:
    """
    Prints a concise result line at the END of each agent's execution.

    Example output (success):
      ✅  [14:32:08]  ROUTER  done in 7.1s  │  HDFCBANK.NS · Banks/NBFCs
    Example output (failure):
      ❌  [14:32:08]  ROUTER  FAILED in 2.1s │  Could not resolve ticker
    """
    icon    = _green("  ✅") if success else _red("  ❌")
    status  = _green("done") if success else _red("FAILED")
    ts      = _dim(f"[{_now()}]")
    elapsed_str = _dim(f"in {elapsed:.1f}s")
    name    = _bold(agent_name.upper())
    sep     = _dim("  │  ")
    detail_str = _dim(detail) if detail else ""
    print(f"{icon}  {ts}  {name}  {status} {elapsed_str}{sep}{detail_str}")

def _info(message: str) -> None:
    print(f"  {_dim('[' + _now() + ']')}  {message}")

def _warn(message: str) -> None:
    print(f"  {_dim('[' + _now() + ']')}  {_gold('⚠  WARNING:')} {message}")

def _error(message: str) -> None:
    print(f"  {_dim('[' + _now() + ']')}  {_red('✖  ERROR:')} {_red(message)}")

def _success(message: str) -> None:
    print(f"  {_dim('[' + _now() + ']')}  {_green('✓  ')} {message}")

def _pipeline_summary(state: AppState, total_elapsed: float, output_path: Path) -> None:
    """
    Prints the final pipeline summary card that a PM would screenshot and share.
    Includes composite score, verdict, timing, and report path.
    """
    rfd         = state.raw_financial_data
    extra       = rfd.extra_data or {}
    composite   = extra.get("composite_score_100", None)
    verdict     = extra.get("verdict", "N/A")
    risk_band   = getattr(state.analytical_insights, "risk_band", None) or "N/A"
    ticker      = (state.ticker or "").replace(".NS", "").replace(".BO", "")
    news_count  = len(rfd.news_headlines or [])
    q_count     = len(rfd.quarterly_financials or [])
    errors_seen = list(state.errors.keys())

    # Verdict color
    verdict_colors = {
        "Strong Buy": _green, "Buy": _green,
        "Hold": _gold,
        "Sell": _red, "Strong Sell": _red,
    }
    verdict_fn = verdict_colors.get(verdict, _dim)

    # Risk band emoji
    risk_icons = {"LOW RISK": "🟢", "MODERATE RISK": "🟡", "HIGH RISK": "🔴"}
    risk_icon  = risk_icons.get(risk_band, "⚪")

    score_str = f"{composite:.1f} / 100" if composite is not None else "N/A"

    print()
    print(_gold(_line("═")))
    print(_bold(_gold("  PIPELINE COMPLETE — FINAL SCORECARD SUMMARY")))
    print(_gold(_line("═")))
    print()
    print(f"  {'Company':<22} {_bold(state.company_name)}")
    print(f"  {'Ticker':<22} {_bold(_cyan(ticker or 'N/A'))}")
    print(f"  {'Sector':<22} {state.sector or 'Not detected'}")
    print()
    print(f"  {'Composite Score':<22} {_bold(score_str)}")
    print(f"  {'Risk Band':<22} {risk_icon}  {_bold(risk_band)}")
    print(f"  {'Verdict':<22} {_bold(verdict_fn(verdict.upper()))}")
    print()
    print(f"  {'Data Quality':<22}")
    print(f"  {'  Quarters loaded':<22} {q_count} / 4")
    print(f"  {'  News headlines':<22} {news_count} articles (last 60 days)")
    print(f"  {'  Agents completed':<22} {len(state.completed_agents)} / 4")
    print(f"  {'  Pipeline errors':<22} {len(errors_seen)}" +
          (f"  {_gold('(see warnings above)')}" if errors_seen else f"  {_green('none')}"))
    print(f"  {'  Total runtime':<22} {total_elapsed:.1f}s")
    print()
    print(_gold(_line()))
    print(f"  {_bold('📄  REPORT SAVED')}")
    print(f"  {_dim('Path  :')} {output_path}")
    print(f"  {_dim('Size  :')} {output_path.stat().st_size / 1024:.1f} KB")
    print(f"  {_dim('Open  :')} double-click the file or run:")
    print(f"  {_dim('       ')} {_cyan('open ' + str(output_path))}  (macOS)")
    print(f"  {_dim('       ')} {_cyan('start ' + str(output_path))}  (Windows)")
    print(_gold(_line("═")))
    print()


# =============================================================================
# SECTION 2: INPUT HANDLING
# Accepts company name from three sources (checked in priority order):
#   1. CLI argument:  python main.py "HDFC Bank"
#   2. Named flag:    python main.py --company "TCS"
#   3. Interactive:   prompted from terminal
# =============================================================================

def _parse_company_name() -> str:
    """
    Resolves the target company name from CLI args or interactive input.

    Returns the cleaned company name string.
    Exits with a user-friendly message if no name is provided.
    """
    parser = argparse.ArgumentParser(
        description="NSE/BSE Multi-Agent Risk Scorecard — Automated Equity Research",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  python main.py                   # interactive prompt\n"
            "  python main.py \"HDFC Bank\"        # positional argument\n"
            "  python main.py --company Infosys  # named argument\n"
            "  python main.py \"Reliance\"         # common abbreviation works\n"
        ),
    )
    parser.add_argument(
        "company",
        nargs="?",                 # optional positional argument
        help="Indian company name to analyse (e.g., 'HDFC Bank', 'TCS', 'Infosys')",
    )
    parser.add_argument(
        "--company", "-c",
        dest="company_flag",
        help="Same as positional argument (named form)",
    )
    parser.add_argument(
        "--output", "-o",
        dest="output_path",
        default="output_risk_report.html",
        help="Output file path (default: output_risk_report.html)",
    )

    args, _ = parser.parse_known_args()

    # Priority: positional → named flag → interactive prompt
    company_name = args.company or args.company_flag or ""

    if not company_name.strip():
        # Interactive mode — used when run with no arguments
        print()
        print(_bold("  Enter the Indian company name you want to analyse."))
        print(_dim("  Examples: HDFC Bank · TCS · Infosys · Sun Pharma · L&T · Maruti"))
        print()
        try:
            raw = input(_gold("  ▶  Company Name: ")).strip()
        except (KeyboardInterrupt, EOFError):
            print("\n\n  Interrupted by user. Exiting.\n")
            sys.exit(0)

        if not raw:
            print(_red("\n  ✖  No company name entered. Please try again.\n"))
            sys.exit(1)
        company_name = raw

    return company_name.strip(), Path(args.output_path)


# =============================================================================
# SECTION 3: PIPELINE STEP RUNNER
# A thin wrapper around each agent's run() call that:
#   - Prints the start/end banners
#   - Measures elapsed time
#   - Catches any unhandled exception that somehow escapes the agent
#   - Returns (state, success_flag)
# =============================================================================

def _run_agent(
    step: int,
    total: int,
    agent_module,
    agent_key: str,
    agent_display_name: str,
    description: str,
    state: AppState,
    abort_if_missing: bool = False,
) -> tuple[AppState, bool]:
    """
    Executes a single agent and handles all logging and error catching.

    Parameters
    ----------
    step               : 1-based step number in the pipeline
    total              : total number of steps (4)
    agent_module       : the imported Python module (router, extractor, etc.)
    agent_key          : the key used in state.completed_agents / state.errors
    agent_display_name : human-readable name for console output
    description        : one-line description of what this agent does
    state              : the shared AppState object (mutated in-place)
    abort_if_missing   : if True, return failure immediately if the agent's
                         prerequisite agents have not completed

    Returns
    -------
    (state, success) — state is always returned even on failure
    """
    _section_start(step, total, agent_display_name, description)
    t0 = time.time()

    try:
        state = agent_module.run(state)
    except Exception as exc:
        # This should never happen — each agent has its own try/except —
        # but we catch it here as an absolute safety net.
        elapsed = time.time() - t0
        err_msg = f"Unhandled exception in {agent_display_name}: {type(exc).__name__}: {exc}"
        state.log_error(agent_key, err_msg)
        _section_end(step, agent_display_name, success=False, elapsed=elapsed, detail=err_msg[:80])
        _error(f"Full traceback:")
        traceback.print_exc()
        return state, False

    elapsed = time.time() - t0
    success = state.is_agent_complete(agent_key)

    # Build a brief detail string for the end-of-step banner
    detail = _build_step_detail(agent_key, state)

    # Log any errors the agent wrote to state.errors
    if agent_key in state.errors:
        _warn(f"{agent_display_name} logged a non-fatal error:")
        _warn(f"  → {state.errors[agent_key][:120]}")

    _section_end(step, agent_display_name, success=success, elapsed=elapsed, detail=detail)

    return state, success


def _build_step_detail(agent_key: str, state: AppState) -> str:
    """
    Builds a one-line status detail string for the end-of-step log,
    specific to each agent's output.
    """
    rfd   = state.raw_financial_data
    extra = rfd.extra_data or {}

    if agent_key == "router":
        ticker  = state.ticker or "unresolved"
        sector  = state.sector or "unknown sector"
        n_kpis  = len(state.sector_kpis or [])
        return f"{ticker} · {sector} · {n_kpis} KPIs mapped"

    if agent_key == "extractor":
        cmp       = rfd.cmp
        q_count   = len(rfd.quarterly_financials or [])
        n_news    = len(rfd.news_headlines or [])
        cmp_str   = f"₹{cmp:,.2f}" if cmp else "CMP N/A"
        return f"{cmp_str} · {q_count} quarters · {n_news} news articles"

    if agent_key == "analyst":
        score   = extra.get("composite_score_100")
        verdict = extra.get("verdict", "N/A")
        band    = getattr(state.analytical_insights, "risk_band", "N/A") or "N/A"
        score_s = f"{score:.1f}/100" if score is not None else "N/A"
        return f"Score: {score_s} · {verdict} · {band}"

    if agent_key == "designer":
        html_len = len(state.html_report or "")
        return f"HTML report: {html_len:,} chars ({html_len / 1024:.0f} KB)"

    return ""


# =============================================================================
# SECTION 4: REPORT SAVER
# Writes the HTML string from state to a local file.
# =============================================================================

def _save_report(state: AppState, output_path: Path) -> bool:
    """
    Saves state.html_report to the specified output file path.

    Returns True on success, False on failure.
    """
    html = state.html_report

    if not html:
        _error("state.html_report is empty — Designer Agent may have failed.")
        return False

    try:
        # Ensure the parent directory exists (handles cases where --output
        # specifies a subdirectory like reports/hdfc_bank.html)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        output_path.write_text(html, encoding="utf-8")
        return True

    except PermissionError:
        _error(f"Permission denied writing to: {output_path}")
        _error("Try running from a directory where you have write access.")
        return False
    except OSError as exc:
        _error(f"File write failed: {exc}")
        return False


# =============================================================================
# SECTION 5: STATE SNAPSHOT SAVER
# Optionally saves the full AppState as a JSON file for debugging.
# Written alongside the HTML report as <name>_state_snapshot.json
# =============================================================================

def _save_state_snapshot(state: AppState, output_path: Path) -> None:
    """
    Saves the entire AppState as a JSON file (debug artifact).
    Named after the output HTML file: output_risk_report_state.json

    This is invaluable when:
    - A score looks wrong and you want to inspect raw data
    - An agent partially failed and you need to see what data was captured
    - You want to re-run only the analyst/designer without re-fetching data

    The file is saved silently; any failure is swallowed.
    """
    try:
        snapshot_path = output_path.parent / (output_path.stem + "_state.json")
        snapshot_path.write_text(state.to_json(indent=2), encoding="utf-8")
        _info(f"State snapshot saved → {snapshot_path.name}")
    except Exception:
        pass  # Non-critical; don't clutter output on failure


# =============================================================================
# SECTION 6: PRE-FLIGHT CHECKS
# Validate the environment before spending time on API calls.
# =============================================================================

def _preflight_checks() -> bool:
    """
    Runs a series of quick sanity checks before starting the pipeline:
      1. Python version ≥ 3.10 (for match/case and type union syntax)
      2. Required third-party libraries are importable
      3. The agents/ package structure is intact

    Returns True if all checks pass, False if any critical check fails.
    Prints a clear actionable message for each failure.
    """
    all_ok = True

    # ── Python version ────────────────────────────────────────────────────
    if sys.version_info < (3, 10):
        _error(f"Python 3.10+ required. Current: {sys.version.split()[0]}")
        _error("Upgrade Python and re-run.")
        all_ok = False

    # ── Required libraries ────────────────────────────────────────────────
    required_libs = {
        "yfinance":       "pip install yfinance",
        "pydantic":       "pip install pydantic",
        "requests":       "pip install requests",
        "bs4":            "pip install beautifulsoup4",
        "pandas":         "pip install pandas",
        "pytz":           "pip install pytz",
        "loguru":         "pip install loguru",
    }

    missing = []
    for lib, install_cmd in required_libs.items():
        try:
            __import__(lib)
        except ImportError:
            missing.append((lib, install_cmd))

    if missing:
        _error("Missing required libraries. Install them with:")
        print()
        print(f"      {_cyan('pip install -r requirements.txt')}")
        print()
        print("  Or install individually:")
        for lib, cmd in missing:
            print(f"      {_cyan(cmd)}")
        all_ok = False

    # ── Agents package structure ──────────────────────────────────────────
    agents_dir = ROOT_DIR / "agents"
    required_agent_files = ["router.py", "extractor.py", "analyst.py", "designer.py"]
    for fname in required_agent_files:
        if not (agents_dir / fname).exists():
            _error(f"Missing agent file: agents/{fname}")
            all_ok = False

    # agents/__init__.py must exist for 'from agents import ...' to work
    init_file = agents_dir / "__init__.py"
    if not init_file.exists():
        # Create it silently if missing — it's a common setup oversight
        try:
            init_file.write_text("# agents package\n", encoding="utf-8")
            _info("Created missing agents/__init__.py")
        except OSError:
            _error("agents/__init__.py missing and could not be created.")
            all_ok = False

    return all_ok


# =============================================================================
# SECTION 7: MAIN PIPELINE ORCHESTRATOR
# =============================================================================

def main() -> int:
    """
    Main pipeline orchestrator. Returns an exit code (0 = success, 1 = failure).

    PIPELINE STAGES:
    ─────────────────────────────────────────────────────────────────────
    Stage 0 │ Pre-flight checks (libraries, file structure)
    Stage 1 │ User input (company name)
    Stage 2 │ State initialisation
    Stage 3 │ Agent 1 — Router (ticker, sector, KPIs)          [CRITICAL]
    Stage 4 │ Agent 2 — Extractor (financial data + news)      [CRITICAL]
    Stage 5 │ Agent 3 — Analyst (scoring + verdict)            [CRITICAL]
    Stage 6 │ Agent 4 — Designer (HTML report generation)      [CRITICAL]
    Stage 7 │ Report save to disk
    Stage 8 │ State snapshot save (debug artifact)
    Stage 9 │ Final summary card
    ─────────────────────────────────────────────────────────────────────

    ABORT POLICY:
    If a CRITICAL agent fails (marked [CRITICAL] above), the pipeline stops
    immediately because downstream agents have no meaningful data to work with.
    Non-critical failures (e.g., news scraper blocked) generate a warning
    but allow the pipeline to continue.
    """

    pipeline_start = time.time()

    # ── STAGE 0: BANNER ──────────────────────────────────────────────────
    _header_banner()

    # ── STAGE 0b: PRE-FLIGHT ─────────────────────────────────────────────
    _info("Running pre-flight environment checks...")
    if not _preflight_checks():
        print()
        _error("Pre-flight checks failed. Fix the issues above and re-run.")
        print()
        return 1
    _success("Environment checks passed.")

    # ── STAGE 1: USER INPUT ──────────────────────────────────────────────
    company_name, output_path = _parse_company_name()

    print()
    print(_gold(_line()))
    print(f"  {_bold('Target Company  :')} {_bold(company_name)}")
    print(f"  {_bold('Report Output   :')} {output_path}")
    print(f"  {_bold('Pipeline Start  :')} {datetime.now(IST).strftime('%d %b %Y, %I:%M:%S %p IST')}")
    print(_gold(_line()))

    # ── STAGE 2: STATE INITIALISATION ───────────────────────────────────
    print()
    _info(f"Initialising AppState for '{company_name}'...")
    try:
        state = AppState(company_name=company_name)
        _success(f"AppState created. Pipeline ID: {id(state)}")
    except Exception as exc:
        _error(f"Failed to create AppState: {exc}")
        return 1

    # ── STAGE 3: AGENT 1 — ROUTER ────────────────────────────────────────
    state, ok = _run_agent(
        step=1,
        total=4,
        agent_module=router,
        agent_key="router",
        agent_display_name="Router",
        description=(
            "Resolving NSE/BSE ticker symbol · Detecting sector "
            "· Mapping 2 sector-specific KPIs"
        ),
        state=state,
    )

    if not ok:
        print()
        _error(
            "Router Agent failed to resolve the company ticker. "
            "The pipeline cannot continue without a valid NSE/BSE symbol."
        )
        _error(
            "Suggestions: Try the official company name "
            "(e.g. 'HDFC Bank' instead of 'hdfc'), "
            "or the NSE ticker directly (e.g. 'HDFCBANK')."
        )
        print()
        return 1

    # Confirm what the router found — reassuring PM-level status
    _info(f"Resolved → Ticker: {_cyan(state.ticker or 'N/A')}  "
          f"Sector: {_gold(state.sector or 'N/A')}  "
          f"KPIs: {[k.name for k in (state.sector_kpis or [])]}")

    # ── STAGE 4: AGENT 2 — EXTRACTOR ─────────────────────────────────────
    _info("This step makes live API calls — expect 15–45 seconds...")
    state, ok = _run_agent(
        step=2,
        total=4,
        agent_module=extractor,
        agent_key="extractor",
        agent_display_name="Extractor",
        description=(
            "Fetching CMP, 52W range, P/E, P/B, ROE · "
            "4 quarters of financials · Promoter shareholding · 60-day news"
        ),
        state=state,
    )

    if not ok:
        print()
        _error(
            "Extractor Agent failed. This usually means the ticker is valid "
            "but Yahoo Finance returned no data (possible market closure, "
            "rate-limit, or network issue)."
        )
        _error(
            "Try again in a few minutes. If the problem persists, "
            "verify your internet connection."
        )
        print()
        return 1

    # Report data sufficiency to the PM
    rfd = state.raw_financial_data
    q_count  = len(rfd.quarterly_financials or [])
    n_news   = len(rfd.news_headlines or [])
    pledge   = rfd.promoter_pledge_pct

    if q_count < 4:
        _warn(f"Only {q_count}/4 quarters of financial data available. "
              "Some trend metrics will be limited.")
    else:
        _success(f"Full 4-quarter financial data loaded.")

    if n_news == 0:
        _warn("No news headlines fetched. Sentiment score will use neutral defaults.")
    else:
        _success(f"{n_news} news headlines fetched for sentiment analysis.")

    if pledge is None:
        _warn("Promoter pledge % not available. Governance score uses conservative default.")

    # ── STAGE 5: AGENT 3 — ANALYST ───────────────────────────────────────
    state, ok = _run_agent(
        step=3,
        total=4,
        agent_module=analyst,
        agent_key="analyst",
        agent_display_name="Analyst",
        description=(
            "Scoring 7 risk factors · Computing weighted composite score "
            "· Generating Hidden Insights, 8 Catalysts, 8 Risks · Drafting verdict"
        ),
        state=state,
    )

    if not ok:
        print()
        _error(
            "Analyst Agent failed. The raw data was fetched successfully "
            "but the scoring engine encountered an unexpected error."
        )
        _error(
            "Check that all libraries (pandas, numpy) are installed. "
            "Review the traceback above for the specific cause."
        )
        print()
        return 1

    # Print the headline numbers immediately — PM wants to know NOW
    extra   = rfd.extra_data or {}
    score   = extra.get("composite_score_100", 0)
    verdict = extra.get("verdict", "N/A")
    band    = getattr(state.analytical_insights, "risk_band", "N/A") or "N/A"

    verdict_fn = {"Strong Buy": _green, "Buy": _green,
                  "Sell": _red, "Strong Sell": _red}.get(verdict, _gold)
    print()
    print(f"  {'─'*64}")
    print(f"  {'  PRELIMINARY RESULT':}")
    print(f"  {'─'*64}")
    print(f"  {'  Composite Risk Score':<26} {_bold(f'{score:.1f} / 100')}")
    print(f"  {'  Risk Band':<26} {_bold(band)}")
    print(f"  {'  Analyst Verdict':<26} {_bold(verdict_fn(verdict.upper()))}")
    print(f"  {'─'*64}")
    print()

    # ── STAGE 6: AGENT 4 — DESIGNER ──────────────────────────────────────
    state, ok = _run_agent(
        step=4,
        total=4,
        agent_module=designer,
        agent_key="designer",
        agent_display_name="Designer",
        description=(
            "Rendering 2-page HTML report · SVG risk gauge · "
            "Quarterly charts · Catalyst/Risk columns · Verdict panel"
        ),
        state=state,
    )

    if not ok:
        print()
        _error("Designer Agent failed to generate the HTML report.")
        _error(
            "The analysis IS complete (see preliminary result above). "
            "You can re-run with only the designer step, or review "
            "the state snapshot JSON for the full data."
        )
        # Still save a state snapshot so the data isn't lost
        _save_state_snapshot(state, output_path)
        print()
        return 1

    # ── STAGE 7: SAVE HTML REPORT ─────────────────────────────────────────
    print()
    _info(f"Saving HTML report to: {output_path}")
    saved = _save_report(state, output_path)

    if not saved:
        _error("Report could not be saved to disk.")
        _error(f"Check permissions for: {output_path.parent}")
        return 1

    # ── STAGE 8: SAVE STATE SNAPSHOT ─────────────────────────────────────
    _save_state_snapshot(state, output_path)

    # ── STAGE 9: FINAL SUMMARY ────────────────────────────────────────────
    total_elapsed = time.time() - pipeline_start
    _pipeline_summary(state, total_elapsed, output_path)

    return 0


# =============================================================================
# SECTION 8: ENTRY POINT
# =============================================================================

if __name__ == "__main__":
    # Ensure the agents/ directory has an __init__.py before imports run.
    # This handles first-time setup where the file may not exist yet.
    _agents_init = ROOT_DIR / "agents" / "__init__.py"
    if not _agents_init.exists():
        try:
            _agents_init.write_text("# agents package\n", encoding="utf-8")
        except OSError:
            pass  # Will be caught in pre-flight with a clear message

    exit_code = main()
    sys.exit(exit_code)