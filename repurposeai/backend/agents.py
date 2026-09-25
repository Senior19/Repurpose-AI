"""
The agent layer.

Design principle (this is the anti-hallucination guardrail described in the
project doc): agents are NOT allowed to invent facts. Every agent that makes
a scientific claim is given real retrieved data (from tools.py) and is
instructed to reason ONLY over that data, tagging every claim with a source.
The LLM's job is synthesis/summarization/prioritization, not recall.

If a tool call fails or returns nothing, the agent explicitly records a
knowledge gap instead of letting the LLM fill it in from parametric memory.
"""
import json
import os
import time
import requests

import tools
from schemas import Candidate, EvidenceItem, AgentLog, new_id

def _setting(name: str, fallback: str = "") -> str:
    """Read deployment secrets from env vars or Streamlit Cloud secrets."""
    value = os.environ.get(name)
    if value:
        return value
    try:
        import streamlit as st
        value = st.secrets.get(name, "")
    except Exception:
        # Streamlit is optional for local FastAPI development, and secrets.toml
        # is optional when using the evidence-only explorers.
        value = ""
    return str(value or fallback)


ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "")

# Auto-pick a provider: prefer Groq if its key is set (it's free, no card
# required - see README), otherwise fall back to Anthropic. Override with
# REPURPOSEAI_PROVIDER=groq|anthropic if you have both keys set.
PROVIDER = os.environ.get("REPURPOSEAI_PROVIDER", "").lower()

DEFAULT_MODELS = {"groq": "llama-3.3-70b-versatile", "anthropic": "claude-sonnet-5"}
MODEL = os.environ.get("REPURPOSEAI_MODEL", "")


_resolved_groq_model = None  # cached after first successful auto-discovery

def _discover_groq_model(api_key: str) -> str:
    """Ask Groq itself which chat models are currently available on this
    account and pick a sensible one. This avoids hardcoding a model name
    that Groq may have renamed/retired since this code was written."""
    resp = requests.get(
        "https://api.groq.com/openai/v1/models",
        headers={"Authorization": f"Bearer {api_key}"},
        timeout=30,
    )
    resp.raise_for_status()
    ids = [m["id"] for m in resp.json().get("data", [])]
    if not ids:
        raise RuntimeError("Groq returned no available models for this API key.")

    # Skip audio/moderation/guard models - we want a general chat model.
    excluded = ("whisper", "tts", "guard", "prompt-guard")
    chat_ids = [m for m in ids if not any(x in m.lower() for x in excluded)]
    candidates = chat_ids or ids

    # Prefer a well-known versatile/instant llama model if present, else
    # just take the first available chat model.
    for preferred in ("versatile", "instant", "llama"):
        match = next((m for m in candidates if preferred in m.lower()), None)
        if match:
            return match
    return candidates[0]


def call_llm(system: str, user: str, max_tokens: int = 1200) -> str:
    """Thin wrapper that calls either Groq (OpenAI-compatible, free) or
    Anthropic, depending on which key is configured. Returns plain text."""

    groq_api_key = _setting("GROQ_API_KEY", GROQ_API_KEY)
    anthropic_api_key = _setting("ANTHROPIC_API_KEY", ANTHROPIC_API_KEY)
    configured_provider = _setting("REPURPOSEAI_PROVIDER", PROVIDER).lower()
    provider = configured_provider if configured_provider in {"groq", "anthropic"} else ""
    if not provider:
        provider = "groq" if groq_api_key else "anthropic" if anthropic_api_key else "groq"
    model = _setting("REPURPOSEAI_MODEL", MODEL) or DEFAULT_MODELS[provider]

    if provider == "groq":
        global _resolved_groq_model
        if not groq_api_key:
            raise RuntimeError("GROQ_API_KEY is missing. Add it to Streamlit Cloud app Secrets or set it as an environment variable.")

        model_to_use = _resolved_groq_model or model

        def _post(model_name):
            return requests.post(
                "https://api.groq.com/openai/v1/chat/completions",
                headers={"Authorization": f"Bearer {groq_api_key}", "Content-Type": "application/json"},
                json={
                    "model": model_name,
                    "max_tokens": max_tokens,
                    "messages": [
                        {"role": "system", "content": system},
                        {"role": "user", "content": user},
                    ],
                },
                timeout=60,
            )

        resp = _post(model_to_use)

        # If the configured model no longer exists, auto-discover a working
        # one from Groq's own /models endpoint and retry once.
        if resp.status_code == 404 and "model_not_found" in resp.text:
            _resolved_groq_model = _discover_groq_model(groq_api_key)
            resp = _post(_resolved_groq_model)

        if not resp.ok:
            raise RuntimeError(f"Groq API error {resp.status_code}: {resp.text}")
        data = resp.json()
        return data["choices"][0]["message"]["content"]

    # --- Anthropic path ---
    if not anthropic_api_key:
        raise RuntimeError(
            "ANTHROPIC_API_KEY is missing. Add it to Streamlit Cloud app Secrets or set it as an environment variable."
        )
    resp = requests.post(
        "https://api.anthropic.com/v1/messages",
        headers={
            "x-api-key": anthropic_api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        },
        json={
            "model": model,
            "max_tokens": max_tokens,
            "system": system,
            "messages": [{"role": "user", "content": user}],
        },
        timeout=60,
    )
    if not resp.ok:
        # Surface Anthropic's actual error body instead of a bare "400 Bad Request",
        # which is the only way to know *why* the request was rejected.
        raise RuntimeError(f"Anthropic API error {resp.status_code}: {resp.text}")
    data = resp.json()
    return "".join(b.get("text", "") for b in data.get("content", []) if b.get("type") == "text")


def call_llm_json(system: str, user: str, max_tokens: int = 1500) -> dict:
    """Same as call_llm but strips markdown fences and parses JSON, with a
    single repair retry if parsing fails."""
    text = call_llm(system + "\n\nRespond with ONLY valid JSON. No markdown, no preamble.", user, max_tokens)
    cleaned = text.strip().strip("`")
    if cleaned.lower().startswith("json"):
        cleaned = cleaned[4:]
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        repaired = call_llm(
            "You output ONLY valid JSON, nothing else.",
            f"This is not valid JSON, fix it and return ONLY the corrected JSON:\n\n{text}",
            max_tokens,
        )
        return json.loads(repaired.strip().strip("`"))


def _log(run, agent, action, status, summary):
    entry = AgentLog(id=new_id("log"), run_id=run.id, agent=agent, action=action,
                      status=status, result_summary=summary, timestamp=time.time())
    run.logs.append(entry)
    import db
    db.log_agent_step(entry)
    db.save_run(run)


# ---------------------------------------------------------------------------
# Orchestrator: decomposes the research question into a task plan
# ---------------------------------------------------------------------------
def orchestrator_plan(run):
    _log(run, "orchestrator", "decompose_question", "running", f"Planning investigation for {run.disease}")
    plan = call_llm_json(
        system=(
            "You are the orchestrator agent in a drug-repurposing research system. "
            "Break the research question into a short, concrete task plan for downstream "
            "specialist agents (biology, drug discovery, literature, clinical, safety). "
            "Do not answer the question yourself."
        ),
        user=(
            f'Disease: "{run.disease}"\n'
            f'Hypothesis: "{getattr(run, "hypothesis", None) or "No explicit user hypothesis"}"\n'
            'Return JSON: {"sub_questions": ["...", "..."], "notes": "1-2 sentence framing"}'
        ),
    )
    _log(run, "orchestrator", "decompose_question", "done", plan.get("notes", "Plan created"))
    return plan


# ---------------------------------------------------------------------------
# Biology agent
# ---------------------------------------------------------------------------
def biology_agent(run):
    _log(run, "biology", "query_open_targets", "running", f"Querying Open Targets for {run.disease}")
    targets, err = tools.search_disease_targets(run.disease)
    if err:
        _log(run, "biology", "query_open_targets", "error", err)
    else:
        _log(run, "biology", "query_open_targets", "done", f"Found {len(targets)} associated targets")

    summary = call_llm(
        system=(
            "You are a disease-biology research agent. You are given REAL target-association "
            "data retrieved from Open Targets. Summarize, in 3-4 sentences, what these targets "
            "suggest about the disease's underlying biology and pathways. Only reason over the "
            "data given; if the data is empty, say explicitly that no target data was retrieved."
        ),
        user=f"Disease: {run.disease}\nTarget association data:\n{json.dumps(targets, indent=2)}",
    )
    _log(run, "biology", "summarize_biology", "done", summary[:200])
    return targets, summary


# ---------------------------------------------------------------------------
# Drug discovery agent
# ---------------------------------------------------------------------------
def drug_agent(run, targets):
    candidates = {}
    for t in targets[:4]:
        symbol = t["symbol"]
        _log(run, "drug_discovery", "query_chembl", "running", f"Looking up drugs acting on {symbol}")
        drugs, err = tools.search_drugs_for_target(symbol)
        if err:
            _log(run, "drug_discovery", "query_chembl", "error", f"{symbol}: {err}")
            continue
        for d in drugs:
            name = get_cached_drug_name(d["molecule_chembl_id"])
            key = name
            if key not in candidates:
                candidates[key] = Candidate(
                    drug=name,
                    target=symbol,
                    pathway=None,
                    mechanism_hypothesis=d.get("mechanism_of_action") or "",
                )
        _log(run, "drug_discovery", "query_chembl", "done", f"{symbol}: {len(drugs)} known drugs")

    result = list(candidates.values())[:4]  # cap for demo speed/cost
    _log(run, "drug_discovery", "shortlist", "done", f"Shortlisted {len(result)} candidate drugs")
    return result


_drug_name_cache = {}

def get_cached_drug_name(chembl_id):
    if chembl_id not in _drug_name_cache:
        _drug_name_cache[chembl_id] = tools.get_drug_name(chembl_id)
    return _drug_name_cache[chembl_id]


# ---------------------------------------------------------------------------
# Literature agent
# ---------------------------------------------------------------------------
def literature_agent(run, candidate: Candidate):
    query = f"{candidate.drug} {run.disease} {getattr(run, 'hypothesis', None) or ''}".strip()
    _log(run, "literature", "search_pubmed", "running", f"Searching PubMed: {query}")
    articles, err = tools.search_pubmed(query)
    if err:
        _log(run, "literature", "search_pubmed", "error", err)
    else:
        _log(run, "literature", "search_pubmed", "done", f"{candidate.drug}: {len(articles)} articles found")

    if not articles:
        candidate.knowledge_gaps.append(f"No PubMed literature found directly linking {candidate.drug} to {run.disease}.")
        return

    analysis = call_llm_json(
        system=(
            "You are a literature-evidence agent. You are given REAL PubMed article titles "
            "(not full text). Based ONLY on titles/metadata, classify each as likely supporting, "
            "contradictory, or neutral/inconclusive toward the hypothesis that the drug could help "
            "the disease. Be conservative - titles alone are weak evidence, say so."
        ),
        user=(
            f"Drug: {candidate.drug}\nDisease: {run.disease}\nUser hypothesis: {getattr(run, 'hypothesis', None) or 'Not specified'}\n"
            f"Articles:\n{json.dumps(articles, indent=2)}\n\n"
            'Return JSON: {"items": [{"pmid": "...", "stance": "supporting|contradictory|neutral", '
            '"claim": "short claim", "confidence": "low|moderate|high"}]}'
        ),
    )
    for item in analysis.get("items", []):
        article = next((a for a in articles if a["pmid"] == item.get("pmid")), None)
        candidate.evidence.append(EvidenceItem(
            claim=item.get("claim", ""),
            evidence_type="literature",
            stance=item.get("stance", "neutral"),
            source=article["title"] if article else "PubMed article",
            url=article["url"] if article else None,
            confidence=item.get("confidence", "low"),
        ))


# ---------------------------------------------------------------------------
# Clinical evidence agent
# ---------------------------------------------------------------------------
def clinical_agent(run, candidate: Candidate):
    query = f"{candidate.drug} {run.disease}"
    _log(run, "clinical", "search_clinicaltrials", "running", f"Searching ClinicalTrials.gov: {query}")
    trials, err = tools.search_clinical_trials(query)
    if err:
        _log(run, "clinical", "search_clinicaltrials", "error", err)
        candidate.knowledge_gaps.append("Clinical trial data could not be retrieved (API error).")
        return
    _log(run, "clinical", "search_clinicaltrials", "done", f"{candidate.drug}: {len(trials)} trials found")
    candidate.clinical_trials = trials
    if not trials:
        candidate.knowledge_gaps.append(f"No registered clinical trials found for {candidate.drug} in {run.disease}.")
    else:
        for t in trials:
            candidate.evidence.append(EvidenceItem(
                claim=f'Registered trial: "{t["title"]}" (status: {t["status"]})',
                evidence_type="clinical",
                stance="neutral",
                source="ClinicalTrials.gov",
                url=t["url"],
                confidence="moderate",
            ))


# ---------------------------------------------------------------------------
# Safety agent
# ---------------------------------------------------------------------------
def safety_agent(run, candidate: Candidate):
    _log(run, "safety", "search_openfda", "running", f"Checking FDA label data for {candidate.drug}")
    notes, err = tools.search_drug_safety(candidate.drug)
    if err:
        _log(run, "safety", "search_openfda", "error", err)
        candidate.knowledge_gaps.append("No structured FDA safety label data available for this compound.")
        return
    _log(run, "safety", "search_openfda", "done", f"{candidate.drug}: {len(notes)} safety notes found")
    candidate.safety_notes = notes


# ---------------------------------------------------------------------------
# Critic agent - actively looks for reasons the hypothesis might be wrong
# ---------------------------------------------------------------------------
def critic_agent(run, candidate: Candidate):
    _log(run, "critic", "review_hypothesis", "running", f"Critiquing hypothesis for {candidate.drug}")
    review = call_llm_json(
        system=(
            "You are a skeptical critic agent reviewing a drug-repurposing hypothesis. "
            "Your job is to actively look for weaknesses: contradictory evidence, weak evidence "
            "types (e.g. only title-level literature, no human data), overreach, and missing data. "
            "Do not be reassuring - be rigorous."
        ),
        user=(
            f"Disease: {run.disease}\nUser hypothesis: {getattr(run, 'hypothesis', None) or 'Not specified'}\nCandidate: {json.dumps(candidate.to_dict(), indent=2)}\n\n"
            'Return JSON: {"gaps": ["..."], "overall_confidence": "low|moderate|high", '
            '"critic_summary": "2-3 sentences"}'
        ),
    )
    candidate.knowledge_gaps.extend(review.get("gaps", []))
    candidate.confidence = review.get("overall_confidence", candidate.confidence)
    _log(run, "critic", "review_hypothesis", "done", review.get("critic_summary", ""))


# ---------------------------------------------------------------------------
# Synthesis agent - produces the final research brief
# ---------------------------------------------------------------------------
def synthesis_agent(run):
    _log(run, "synthesis", "generate_report", "running", "Compiling final research brief")
    report = call_llm_json(
        system=(
            "You are the synthesis agent. Produce a research brief for a life-sciences "
            "researcher. This is a DECISION-SUPPORT document, not a treatment recommendation. "
            "Explicitly state that findings require further scientific/clinical validation."
        ),
        user=(
            f"Disease: {run.disease}\n"
            f"User hypothesis: {getattr(run, 'hypothesis', None) or 'Not specified'}\n"
            f"Candidates investigated:\n{json.dumps([c.to_dict() for c in run.candidates], indent=2)}\n\n"
            'Return JSON: {"summary": "...", "top_candidate": "drug name or null", '
            '"recommendation": "...", "next_steps": ["...", "..."]}'
        ),
        max_tokens=2000,
    )
    _log(run, "synthesis", "generate_report", "done", report.get("summary", "")[:200])
    return report
