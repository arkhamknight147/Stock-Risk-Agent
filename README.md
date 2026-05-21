# 🤖 Multi-Agent Stock Risk Scorecard Engine

An enterprise-grade, agentic financial analysis framework built on **Python 3.13**, **Streamlit**, and **Claude Sonnet** that automatically evaluates risk vector profiles for NSE/BSE listed Indian equities.

---

## 🎯 The Product Problem Statement
Standard Large Language Models (LLMs) suffer from context window truncation and output limits when asked to generate long, dense financial reports. Furthermore, they frequently hallucinate historical stock prices, volatile corporate pledge structures, and current financial metrics. 

### The Solution: An Orchestrated Agentic Pipeline
This system completely separates data collection, numerical computation, and UI rendering into an **Orchestrator-Worker Multi-Agent Workflow**, achieving 100% predictable, data-accurate output without truncation.

---

## 🏗️ System Architecture & Data Flow

[Insert a screenshot of your beautiful Streamlit App Interface here once running]

The application implements a strict state-machine routing pipeline:

1. **Agent 1: Ticker & Sector Router** ➡️ Resolves readable business queries to standard NSE symbols and assigns sector-specific KPIs.
2. **Agent 2: Parallel Data Extractor** ➡️ Fetches live metrics, 4 quarters of historical filings, and recent corporate news without manual interference.
3. **Agent 3: Financial Analyst Risk Engine** ➡️ Evaluates weighted risk layers, processes SVG trigonometric parameters, and surfaces hidden insights.
4. **Agent 4: UI Presentation Compiler** ➡️ Maps verified outputs cleanly into a production-grade HTML/CSS layout.

---

## 🚀 Local Installation & Setup

To run this product locally on a Windows environment:

1. Clone this repository:
   ```bash
   git clone [https://github.com/arkhamknight147/Stock-Risk-Agent.git](https://github.com/arkhamknight147/Stock-Risk-Agent.git)