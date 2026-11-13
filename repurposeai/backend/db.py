"""SQLite persistence for research runs and agent activity."""
import json
import os
import sqlite3
import threading
from pathlib import Path
from typing import Dict, Optional

from schemas import ResearchRun, research_run_from_dict

DB_PATH = Path(os.environ.get(
    "REPURPOSEAI_DB_PATH",
    Path(__file__).resolve().with_name("repurposeai.db"),
))
_lock = threading.RLock()
_runs: Dict[str, ResearchRun] = {}


def _conn():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH), timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute(
        """CREATE TABLE IF NOT EXISTS research_runs (
            id TEXT PRIMARY KEY,
            disease TEXT NOT NULL,
            status TEXT NOT NULL,
            created_at REAL NOT NULL,
            data TEXT NOT NULL
        )"""
    )
    conn.execute(
        """CREATE TABLE IF NOT EXISTS agent_logs (
            id TEXT PRIMARY KEY,
            run_id TEXT NOT NULL,
            agent TEXT NOT NULL,
            action TEXT NOT NULL,
            status TEXT NOT NULL,
            result_summary TEXT NOT NULL,
            timestamp REAL NOT NULL
        )"""
    )
    return conn


def save_run(run: ResearchRun):
    payload = json.dumps(run.to_dict(), ensure_ascii=False)
    with _lock:
        conn = _conn()
        try:
            conn.execute(
                """INSERT OR REPLACE INTO research_runs
                   (id, disease, status, created_at, data)
                   VALUES (?, ?, ?, ?, ?)""",
                (run.id, run.disease, run.status, run.created_at, payload),
            )
            conn.commit()
            _runs[run.id] = run
        finally:
            conn.close()


def get_run(run_id: str) -> Optional[ResearchRun]:
    with _lock:
        cached = _runs.get(run_id)
        if cached is not None:
            return cached
        conn = _conn()
        try:
            row = conn.execute(
                "SELECT data FROM research_runs WHERE id = ?", (run_id,)
            ).fetchone()
            if row is None:
                return None
            run = research_run_from_dict(json.loads(row["data"]))
            _runs[run.id] = run
            return run
        finally:
            conn.close()


def log_agent_step(log):
    with _lock:
        conn = _conn()
        try:
            conn.execute(
                """INSERT OR REPLACE INTO agent_logs
                   (id, run_id, agent, action, status, result_summary, timestamp)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (log.id, log.run_id, log.agent, log.action, log.status,
                 log.result_summary, log.timestamp),
            )
            conn.commit()
        finally:
            conn.close()


def list_runs():
    with _lock:
        conn = _conn()
        try:
            rows = conn.execute(
                "SELECT data FROM research_runs ORDER BY created_at DESC"
            ).fetchall()
            runs = [research_run_from_dict(json.loads(row["data"])) for row in rows]
            _runs.update({run.id: run for run in runs})
            return runs
        finally:
            conn.close()
