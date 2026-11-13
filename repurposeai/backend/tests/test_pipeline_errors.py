import main
import db
from schemas import ResearchRun


def test_pipeline_error_is_safe_and_traceback_is_only_logged(tmp_path, monkeypatch, caplog):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "pipeline.db")
    monkeypatch.setattr(db, "_runs", {})
    run = ResearchRun(id="run_failure", disease="Test disease")
    db.save_run(run)

    def fail_plan(_run):
        raise RuntimeError("sensitive-provider-detail")

    monkeypatch.setattr(main.agents, "orchestrator_plan", fail_plan)

    with caplog.at_level("ERROR"):
        main.run_pipeline(run.id)

    saved = db.get_run(run.id)
    assert saved.status == "error"
    assert saved.error == "Research pipeline failed. Check server logs using the run ID."
    assert "sensitive-provider-detail" not in saved.error
    assert "Traceback" not in saved.error
    assert "sensitive-provider-detail" in caplog.text
