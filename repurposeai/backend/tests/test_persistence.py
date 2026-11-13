import json

import db
from schemas import AgentLog, Candidate, EvidenceItem, ResearchRun


def test_run_survives_cache_clear_and_database_reload(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "test.db")
    run = ResearchRun(
        id="run_test123",
        disease="Parkinson disease",
        status="done",
        candidates=[
            Candidate(
                drug="Example compound",
                evidence=[
                    EvidenceItem(
                        claim="A test claim",
                        evidence_type="literature",
                        stance="supporting",
                        source="PubMed",
                        url="https://pubmed.ncbi.nlm.nih.gov/",
                    )
                ],
            )
        ],
        logs=[
            AgentLog(
                id="log_test123",
                run_id="run_test123",
                agent="biology",
                action="lookup",
                status="done",
                result_summary="Retrieved one record",
            )
        ],
        report={"summary": "Test report"},
    )

    db.save_run(run)
    db._runs.clear()  # Simulate a fresh application process.

    restored = db.get_run("run_test123")
    assert restored is not None
    assert restored.disease == "Parkinson disease"
    assert restored.candidates[0].drug == "Example compound"
    assert restored.candidates[0].evidence[0].source == "PubMed"
    assert restored.logs[0].agent == "biology"
    assert restored.report == {"summary": "Test report"}


def test_list_runs_reads_persisted_records(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "test.db")
    db.save_run(ResearchRun(id="run_a", disease="Disease A"))
    db.save_run(ResearchRun(id="run_b", disease="Disease B"))

    db._runs.clear()
    runs = db.list_runs()

    assert {run.id for run in runs} == {"run_a", "run_b"}
