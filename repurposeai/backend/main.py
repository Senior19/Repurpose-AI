import json
import threading
import traceback
from pathlib import Path

from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

import agents
import db
import tools
from schemas import ResearchRun, new_id

app = FastAPI(title="RepurposeAI")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


class InvestigateRequest(BaseModel):
    disease: str


class HypothesisRequest(BaseModel):
    hypothesis: str
    disease: str


class ReviewRequest(BaseModel):
    drug: str
    decision: str  # "accepted" | "needs_more_evidence" | "rejected"


def run_pipeline(run_id: str):
    run = db.get_run(run_id)
    try:
        run.status = "planning"
        db.save_run(run)
        agents.orchestrator_plan(run)

        run.status = "biology"
        db.save_run(run)
        targets, _bio_summary = agents.biology_agent(run)

        run.status = "drug_discovery"
        db.save_run(run)
        candidates = agents.drug_agent(run, targets)
        run.candidates = candidates
        db.save_run(run)

        for stage, fn in [
            ("literature", agents.literature_agent),
            ("clinical", agents.clinical_agent),
            ("safety", agents.safety_agent),
        ]:
            run.status = stage
            db.save_run(run)
            for c in run.candidates:
                fn(run, c)
            db.save_run(run)

        run.status = "critic"
        db.save_run(run)
        for c in run.candidates:
            agents.critic_agent(run, c)
        db.save_run(run)

        run.status = "synthesis"
        db.save_run(run)
        run.report = agents.synthesis_agent(run)

        run.status = "done"
        db.save_run(run)

    except Exception as e:
        run.status = "error"
        run.error = f"{e}\n{traceback.format_exc()}"
        db.save_run(run)


@app.post("/api/investigate")
def investigate(req: InvestigateRequest, background_tasks: BackgroundTasks):
    if not req.disease or not req.disease.strip():
        raise HTTPException(400, "disease is required")
    run = ResearchRun(id=new_id("run"), disease=req.disease.strip())
    db.save_run(run)
    background_tasks.add_task(run_pipeline, run.id)
    return {"run_id": run.id}


@app.get("/api/disease")
def disease_explorer(query: str):
    if not query.strip():
        raise HTTPException(400, "query is required")
    targets, err = tools.search_disease_targets(query.strip(), limit=12)
    health_topic, health_error = tools.search_disease_health_topic(query.strip())
    disease_record, description_error = tools.search_disease_description(query.strip())
    disease_description = (
        health_topic.get("summary") if health_topic else (disease_record or {}).get("description")
    )
    overview_url = health_topic.get("url") if health_topic else (disease_record or {}).get("url")
    ranked_targets = sorted(targets, key=lambda item: item.get("association_score") or 0, reverse=True)
    target_summary = "; ".join(
        f'{item.get("symbol")} ({item.get("name")}; association score {item.get("association_score")})'
        for item in ranked_targets[:8]
    )
    if disease_description:
        overview = disease_description.strip()
        overview_source = (
            "MedlinePlus / NLM and Open Targets associations"
            if health_topic else "Open Targets disease ontology description and target associations"
        )
        if ranked_targets:
            overview += (
                f"\n\nOpen Targets separately lists {len(targets)} genes associated with this disease. "
                f"Among the highest-ranked records are {target_summary}. The association score ranks evidence "
                "in that database; it is not a measure of disease severity."
            )
            overview += (
                "\n\nThese two sources provide complementary context: MedlinePlus supplies the plain-language "
                "health summary, while Open Targets supplies gene-association records. The records shown here "
                "do not by themselves establish a cause, pathway, biomarker, or treatment effect."
            )
        else:
            overview += (
                "\n\nOpen Targets did not return associated gene records for this query, so this overview is "
                "based on the MedlinePlus health summary alone."
            )
    elif ranked_targets:
        overview = f"Open Targets returned {len(targets)} associated target records for {query.strip()}. The highest-ranked retrieved records are {target_summary}."
        overview_source = "Open Targets target associations"
    else:
        overview = f"No disease description or target associations were retrieved for {query.strip()} from Open Targets."
        overview_source = "Open Targets Platform"
    if ranked_targets or disease_description:
        try:
            overview = agents.call_llm(
                system=(
                    "Write an accessible disease overview for a life-sciences research dashboard. Return 3 "
                    "well-connected paragraphs totalling about 180-230 words. Use the supplied MedlinePlus "
                    "summary as the main source for explaining the disease in plain language. Preserve its meaning, "
                    "briefly explain technical terms using only what the supplied text supports, and do not add "
                    "medical facts from memory. Use Open Targets only for a separate short explanation of the "
                    "retrieved disease-target associations; scores are evidence rankings, not proof of causation or "
                    "treatment effect. Close by naming material gaps in the supplied data. Do not invent symptoms, "
                    "prevalence, mechanisms, biomarkers, pathways, or treatments. If no MedlinePlus text was supplied, "
                    "say so and do not pretend that target associations are a general disease description."
                ),
                user=(
                    f"Disease query: {query.strip()}\n"
                    f"MedlinePlus health topic: {json.dumps(health_topic, ensure_ascii=False)}\n"
                    f"Open Targets disease ontology description: {(disease_record or {}).get('description') or 'Not returned.'}\n"
                    f"Retrieved Open Targets target-association records ({len(targets)}):\n"
                    f"{json.dumps(ranked_targets[:12], ensure_ascii=False, indent=2)}"
                ),
                max_tokens=700,
            )
            overview_source = (
                "AI-written from MedlinePlus and Open Targets records"
                if health_topic else "AI-written from Open Targets records"
            )
        except Exception:
            pass
    return {
        "disease": query.strip(),
        "overview": overview,
        "overview_source": overview_source,
        "overview_url": overview_url,
        "description": disease_description,
        "genes": targets,
        "proteins": [],
        "targets": targets,
        "pathways": [],
        "biomarkers": [],
        "mechanisms": [],
        "gaps": ([err] if err else []) + ([health_error] if health_error else []) + ([description_error] if description_error else []) + [
            gap for gap, unavailable in [
                ("A disease description was not returned by Open Targets.", not disease_description),
                ("Protein accessions, pathways, biomarkers, and disease-mechanism records are not included in this workflow.", True),
            ] if unavailable
        ],
        "source": "Open Targets Platform",
    }


@app.get("/api/explore/disease")
def disease_explorer_ui(q: str):
    return disease_explorer(q)


@app.get("/api/drug")
def drug_explorer(query: str):
    if not query.strip():
        raise HTTPException(400, "query is required")
    profile, err = tools.search_drug_profile(query.strip())
    if err or not profile:
        raise HTTPException(502, err or "Drug profile could not be retrieved")
    safety, safety_error = tools.search_drug_safety(profile["name"])
    trials, trials_error = tools.search_clinical_trials(profile["name"], max_results=10)
    literature = tools.search_literature_landscape(profile["name"], max_results=10)
    profile["safety"] = safety
    profile["clinical_trials"] = trials
    profile["publications"] = literature["articles"]
    profile["gaps"].extend([
        "A structured drug-drug interaction source is not connected; known interactions are unavailable.",
        "Pathway annotations are not currently returned by the connected drug-profile source."
    ])
    if safety_error:
        profile["gaps"].append(f"FDA safety label lookup unavailable: {safety_error}")
    if trials_error:
        profile["gaps"].append(f"ClinicalTrials.gov lookup unavailable: {trials_error}")
    profile["pathways"] = []
    return profile


@app.get("/api/explore/drug")
def drug_explorer_ui(q: str):
    profile = drug_explorer(q)
    profile["trials"] = profile.get("clinical_trials", [])
    profile["papers"] = profile.get("publications", [])
    return profile


@app.get("/api/literature")
def literature_explorer(query: str):
    if not query.strip():
        raise HTTPException(400, "query is required")
    result = tools.search_literature_landscape(query.strip())
    if result.get("articles"):
        try:
            titles = [{"title": a.get("title"), "year": a.get("pubdate"), "url": a.get("url")} for a in result["articles"]]
            result["ai_summary"] = agents.call_llm(
                "You are a scientific literature triage assistant. Summarize only the supplied PubMed titles and metadata. Do not infer study findings from titles. State that this is a title-level landscape, not a systematic review.",
                f"Query: {query.strip()}\nRetrieved records: {len(titles)}\nArticles:\n{json.dumps(titles, ensure_ascii=False)}",
                max_tokens=500,
            )
        except Exception:
            result["ai_summary"] = None
            result["summary_note"] = "AI summary unavailable; the displayed landscape is based on retrieved titles and metadata."
    return result


@app.get("/api/explore/literature")
def literature_explorer_ui(q: str):
    result = literature_explorer(q)
    result["count"] = result.get("total", 0)
    result["note"] = result.get("summary_note") or result.get("summary", "")
    result["papers"] = result.get("articles", [])
    return result


@app.post("/api/hypotheses")
def test_hypothesis(req: HypothesisRequest, background_tasks: BackgroundTasks):
    if not req.hypothesis.strip() or not req.disease.strip():
        raise HTTPException(400, "hypothesis and disease are required")
    run = ResearchRun(id=new_id("run"), disease=req.disease.strip(), hypothesis=req.hypothesis.strip())
    db.save_run(run)
    background_tasks.add_task(run_pipeline, run.id)
    return {"run_id": run.id, "hypothesis": req.hypothesis.strip()}


@app.get("/api/graph")
def knowledge_graph(disease: str, drug: str = ""):
    targets, err = tools.search_disease_targets(disease.strip(), limit=8)
    nodes = [{"id": "disease", "label": disease.strip(), "type": "Disease"}]
    edges = []
    for index, target in enumerate(targets):
        gene_id = f"gene-{index}"
        target_id = f"target-{index}"
        nodes.extend([
            {"id": gene_id, "label": target["symbol"], "type": "Gene", "evidence": target},
            {"id": target_id, "label": target["symbol"], "type": "Target", "evidence": target},
        ])
        edges.extend([
            {"source": "disease", "target": gene_id, "why": f'Open Targets association score: {target.get("association_score", "not reported")}', "source_name": "Open Targets"},
            {"source": gene_id, "target": target_id, "why": "Open Targets reports this gene as the disease-associated target.", "source_name": "Open Targets"},
        ])
    if drug.strip():
        profile, _ = tools.search_drug_profile(drug.strip())
        if profile:
            drug_id = "drug"
            nodes.append({"id": drug_id, "label": profile["name"], "type": "Drug", "evidence": profile})
            for index, mechanism in enumerate(profile.get("mechanisms", [])):
                matching = next((i for i, t in enumerate(targets) if t["symbol"].lower() in (mechanism.get("target") or "").lower()), None)
                if matching is not None:
                    edges.append({"source": drug_id, "target": f"gene-{matching}", "why": mechanism.get("mechanism") or mechanism.get("action") or "ChEMBL target mechanism record.", "source_name": "ChEMBL"})
    return {"nodes": nodes, "edges": edges, "gaps": [err] if err else (["No verified pathway records were retrieved; pathway links are omitted."] if targets else ["No graph associations were retrieved."]), "source": "Open Targets Platform and ChEMBL"}


@app.get("/api/runs/{run_id}")
def get_run(run_id: str):
    run = db.get_run(run_id)
    if not run:
        raise HTTPException(404, "run not found")
    return run.to_dict()


@app.get("/api/runs")
def list_runs():
    return [r.to_dict() for r in db.list_runs()]


@app.post("/api/runs/{run_id}/review")
def review_candidate(run_id: str, req: ReviewRequest):
    run = db.get_run(run_id)
    if not run:
        raise HTTPException(404, "run not found")
    for c in run.candidates:
        if c.drug == req.drug:
            c.review_status = req.decision
            db.save_run(run)
            return {"ok": True}
    raise HTTPException(404, "candidate not found")


@app.get("/api/explore/disease")
def explore_disease(q: str):
    if not q.strip(): raise HTTPException(400, "query is required")
    targets, err = tools.search_disease_targets(q, limit=10)
    return {"query": q, "targets": targets, "source": "Open Targets Platform", "error": err,
            "overview": "Disease associations retrieved from Open Targets. Review source records; missing data is not inferred."}

@app.get("/api/explore/literature")
def explore_literature(q: str):
    if not q.strip(): raise HTTPException(400, "query is required")
    papers, err = tools.search_pubmed(q, max_results=20)
    return {"query": q, "papers": papers, "count": len(papers), "error": err,
            "note": "Relevance-ranked sample, not a total publication count. Classification requires full text review."}

@app.get("/api/explore/drug")
def explore_drug(q: str):
    if not q.strip(): raise HTTPException(400, "query is required")
    papers, pe = tools.search_pubmed(q, max_results=8)
    trials, te = tools.search_clinical_trials(q, max_results=8)
    safety, se = tools.search_drug_safety(q)
    return {"query": q, "papers": papers, "trials": trials, "safety": safety,
            "errors": [e for e in [pe, te, se] if e]}
# Serve the frontend as static files at "/"
FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"
app.mount("/", StaticFiles(directory=str(FRONTEND_DIR), html=True), name="frontend")
