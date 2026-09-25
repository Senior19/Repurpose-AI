"""
Minimal persistence layer.

For the prototype we keep everything in memory (fast, zero setup) AND mirror
agent_logs + research_runs into SQLite so a demo run survives a server
restart and can be inspected with `sqlite3 repurposeai.db`.
"""
import json
import os
import sqlite3
import threading
from pathlib import Path
from typing import Dict, Optional

from schemas import ResearchRun

DB_PATH = Path(os.environ.get("REPURPOSEAI_DB_PATH", Path(__file__).resolve().with_name("repurposeai.db")))
_lock = threading.Lock()
_runs: Dict[str, ResearchRun] = {}


def _conn():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH), timeout=30)
    conn.execute(
        """CREATE TABLE IF NOT EXISTS research_runs (
            id TEXT PRIMARY KEY,
            disease TEXT,
            status TEXT,
            created_at REAL,
            data TEXT
        )"""
    )
    conn.execute(
        """CREATE TABLE IF NOT EXISTS agent_logs (
            id TEXT PRIMARY KEY,
            run_id TEXT,
            agent TEXT,
            action TEXT,
            status TEXT,
            result_summary TEXT,
            timestamp REAL
        )"""
    )
    return conn


def save_run(run: ResearchRun):
    with _lock:
        _runs[run.id] = run
        conn = _conn()
        conn.execute(
            "INSERT OR REPLACE INTO research_runs (id, disease, status, created_at, data) VALUES (?, ?, ?, ?, ?)",
            (run.id, run.disease, run.status, run.created_at, json.dumps(run.to_dict())),
        )
        conn.commit()
        conn.close()


def get_run(run_id: str) -> Optional[ResearchRun]:
    with _lock:
        return _runs.get(run_id)


def log_agent_step(log):
    with _lock:
        conn = _conn()
        conn.execute(
            "INSERT INTO agent_logs (id, run_id, agent, action, status, result_summary, timestamp) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (log.id, log.run_id, log.agent, log.action, log.status, log.result_summary, log.timestamp),
        )
        conn.commit()
        conn.close()


def list_runs():
    with _lock:
        return sorted(_runs.values(), key=lambda r: r.created_at, reverse=True)
