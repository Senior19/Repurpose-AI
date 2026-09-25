# RepurposeAI

Life-sciences research intelligence for exploring disease biology, drug profiles,
scientific literature, repurposing hypotheses, and evidence trails. The browser UI
is served by the FastAPI application in `repurposeai/backend/main.py`.

## Deploy on Streamlit Community Cloud

This repository uses Streamlit's ASGI app discovery to run its FastAPI `app`.
In Streamlit Community Cloud, choose:

- **Repository:** `Senior19/Repurpose-AI`
- **Branch:** `main`
- **Main file path:** `repurposeai/backend/main.py`
- **Python version:** 3.14 (the current deployed runtime)

The app's `requirements.txt` is next to its entrypoint at
`repurposeai/backend/requirements.txt`. The Streamlit configuration is at the
repository root in `.streamlit/config.toml`.

Evidence explorers use public sources and work without an AI key. Multi-agent
synthesis needs an LLM key. In Community Cloud, open the app's **Settings →
Secrets** and add a key there; do not commit secrets to GitHub:

```toml
GROQ_API_KEY = "your-groq-key"
# Optional: REPURPOSEAI_PROVIDER = "groq"
# Optional: REPURPOSEAI_MODEL = "model-id"
```

The app also accepts `ANTHROPIC_API_KEY`; if both provider keys are present,
Groq is selected by default. Set `REPURPOSEAI_PROVIDER = "anthropic"` to use
Anthropic.

## Run locally on Windows

```powershell
cd repurposeai/backend
./run.ps1
```

Or install dependencies and start the server manually:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m uvicorn main:app --reload --port 8000
```

Open `http://localhost:8000`. Set `GROQ_API_KEY` or `ANTHROPIC_API_KEY` in
your environment to enable LLM-backed agent synthesis.

## Data and limitations

The app retrieves evidence from Open Targets, MedlinePlus, ChEMBL, PubMed,
ClinicalTrials.gov, and openFDA. Some graph relationships and study categories
are limited by the fields available from these sources. Research leads require
expert review; the app is not a diagnostic or treatment tool.
