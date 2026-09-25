# RepurposeAI — prototype

Agentic multi-agent research assistant for drug-repurposing hypotheses.
Orchestrator → Biology agent → Drug-discovery agent → Literature agent →
Clinical agent → Safety agent → Critic agent → Synthesis agent.

Every scientific claim is grounded in a **real, free, no-API-key** public
data source:

| Agent | Data source |
|---|---|
| Biology | Open Targets Platform GraphQL API |
| Disease overview | MedlinePlus Web Service (plain-language topic summary), with Open Targets associations as research context |
| Drug discovery | ChEMBL REST API |
| Literature | NCBI PubMed E-utilities |
| Clinical | ClinicalTrials.gov API v2 |
| Safety | openFDA drug label API |

Only the LLM reasoning steps (orchestration, summarization, critique,
synthesis) require an API key — everything else is free public data.

## Setup

```bash
cd backend
python3 -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt

export GROQ_API_KEY=gsk_...      # FREE - see below, no credit card needed

uvicorn main:app --reload --port 8000
```

### Getting a free LLM key (no credit card)

The app auto-detects which provider to use based on which key is set:

- **Groq (recommended, free)**: go to https://console.groq.com/keys, sign up,
  create an API key (`gsk_...`). Free tier: 30 requests/min, 14,400/day,
  fast enough for a live demo. `export GROQ_API_KEY=gsk_...`
- **Anthropic (paid)**: if you have Anthropic credits, `export
  ANTHROPIC_API_KEY=sk-ant-...` instead and it'll use Claude automatically.
- Override the model with `REPURPOSEAI_MODEL=...` or force a provider with
  `REPURPOSEAI_PROVIDER=groq|anthropic` if you somehow have both keys set.

Then open **http://localhost:8000** — the FastAPI app serves the frontend
directly, no separate dev server needed.

## Streamlit Community Cloud

The repository is configured to run its FastAPI application through Streamlit's
ASGI app discovery. In Streamlit Community Cloud, select branch `main` and set
the main file path to `repurposeai/backend/main.py`. The dependency file is
alongside that entrypoint, and the Streamlit config belongs at the repository
root (`.streamlit/config.toml`).

The public-data explorers do not require a key. To enable AI agent synthesis,
add a provider key in **App settings → Secrets** (never commit it):

```toml
GROQ_API_KEY = "your-groq-key"
```

`ANTHROPIC_API_KEY` is also supported. If both keys are configured, Groq is used
by default; set `REPURPOSEAI_PROVIDER = "anthropic"` to choose Anthropic.

## What to demo

1. Enter a disease (e.g. "Alzheimer's Disease") → **Start Investigation**.
2. Watch the pipeline panel light up step by step and the agent log stream
   real tool calls (Open Targets, ChEMBL, PubMed, ClinicalTrials.gov, FDA).
3. Candidate cards appear with target/pathway, confidence, and
   supporting/contradictory evidence counts.
4. Click **View Evidence** on a candidate → see the individual evidence
   items each tagged with type, stance, confidence, and a clickable source
   link (real PubMed/ClinicalTrials.gov/FDA links) plus the critic agent's
   knowledge-gap findings.
5. Scroll down to the **Research Brief** — the synthesis agent's final
   report with an explicit "requires further validation" caveat.
6. Use **Accept / Need more evidence / Reject** on a candidate card to show
   the human-in-the-loop review step.

## Known limitations (good material for the "challenges" section)

- Literature/clinical agents reason over **titles and trial metadata only**,
  not full text — intentionally conservative, and the UI/prompts say so.
- Some diseases won't resolve cleanly in Open Targets' free-text search;
  the biology agent will log the failure and the pipeline degrades
  gracefully (empty target list → LLM says so explicitly, no invented data).
- ChEMBL target search picks the first fuzzy match — fine for a demo, not
  production-grade entity resolution.
- Sequential agent execution (not parallelized) for simplicity — noted in
  the doc as a latency/cost trade-off with parallelization as a next step.
- In-memory + SQLite storage, single-process — fine for a demo, would move
  to Postgres + a task queue (Celery/RQ) for production.

## Suggested next iterations

- Parallelize literature/clinical/safety calls per candidate (asyncio).
- Add an evaluation harness: 10 fixed disease queries, manually score
  citation accuracy / hallucination rate / completeness.
- Swap sequential Python orchestration for LangGraph if you want explicit
  graph visualization of agent state transitions.

## Intelligence workspaces

The interface now includes:

- **Disease Explorer** — MedlinePlus disease overview, Open Targets disease-associated targets, and an action to start drug discovery. When an LLM key is configured, it rewrites the retrieved material into a short, plain-language overview; otherwise the source summary and target context are shown directly.
- **Drug Explorer** — ChEMBL molecule, indication, and mechanism records, plus ClinicalTrials.gov, PubMed, and FDA label lookups.
- **Knowledge Graph** — interactive disease → gene → target links with source and relationship explanations; drug links appear when the retrieved target records can be matched.
- **Literature Intelligence** — up to 100 retrieved PubMed records, title-based study categories, a publication-year timeline, and an optional LLM summary grounded only in titles/metadata.
- **Hypothesis Lab** — submits the stated hypothesis into the existing multi-agent run; the run's agent log is shown in the Research Room.
- **Research Room** — live status cards for the orchestrator and specialist agents.

API routes: GET /api/disease?query=..., GET /api/drug?query=...,
GET /api/graph?disease=...&drug=..., GET /api/literature?query=...,
and POST /api/hypotheses.

The connected sources do not currently provide
protein accessions, pathway/biomarker annotations, or structured drug-drug
interactions through these workflows. Those fields are shown as gaps. Literature categories are
heuristic title-level labels; the result count is the retrieved sample (capped
at 100), not the total number of matching publications. Candidate and
hypothesis outputs are research leads and require expert validation.
