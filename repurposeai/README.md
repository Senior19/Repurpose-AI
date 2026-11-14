# RepurposeAI application

See the [repository README](../README.md) for the project overview, architecture, data sources, limitations, and setup instructions.

## Quick start

From this directory:

```bash
cd backend
python -m venv .venv
# Windows: .venv\\Scripts\\Activate.ps1
# macOS/Linux: source .venv/bin/activate
python -m pip install -r requirements.txt
python -m uvicorn main:app --reload --port 8000
```

Open http://localhost:8000.

Configure either `GROQ_API_KEY` or `ANTHROPIC_API_KEY` and select the provider using `REPURPOSEAI_PROVIDER`. Keep credentials out of Git.
