from fastapi.testclient import TestClient

import db
import main
from schemas import ResearchRun


client = TestClient(main.app)


def test_invalid_investigation_input_is_rejected():
    response = client.post("/api/investigate", json={"disease": " "})
    assert response.status_code == 422


def test_review_decision_is_restricted():
    response = client.post(
        "/api/runs/nonexistent/review",
        json={"drug": "Example", "decision": "maybe"},
    )
    assert response.status_code == 422


def test_duplicate_explore_routes_are_not_registered():
    paths = [route.path for route in main.app.routes]
    assert paths.count("/api/explore/disease") == 1
    assert paths.count("/api/explore/drug") == 1
    assert paths.count("/api/explore/literature") == 1


def test_pipeline_records_agent_failure_when_provider_key_is_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "test.db")
    monkeypatch.setattr(db, "_runs", {})
    run = ResearchRun(id="run_missing_key", disease="diabetes")
    db.save_run(run)

    def fail_llm(*_args, **_kwargs):
        raise RuntimeError("GROQ_API_KEY is missing.")

    monkeypatch.setattr(main.agents, "call_llm_json", fail_llm)
    main.run_pipeline(run.id)

    failed_run = db.get_run(run.id)
    assert failed_run.status == "error"
    assert failed_run.logs[0].agent == "orchestrator"
    assert failed_run.logs[0].status == "error"
    assert failed_run.logs[0].result_summary == "Agent execution failed. Check server logs using the run ID."
