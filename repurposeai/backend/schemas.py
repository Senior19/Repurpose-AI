"""
Shared data shapes for RepurposeAI.
Kept as plain dataclasses (not pydantic) so the whole backend has zero
required dependency beyond `fastapi`, `uvicorn`, and `requests`.
"""
from dataclasses import dataclass, field
from typing import Optional
import time
import uuid


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:10]}"


PIPELINE_STEPS = [
    "planning",
    "biology",
    "drug_discovery",
    "literature",
    "clinical",
    "safety",
    "critic",
    "synthesis",
    "done",
]

STEP_LABELS = {
    "planning": "Research planning",
    "biology": "Disease biology investigation",
    "drug_discovery": "Drug candidate discovery",
    "literature": "Literature search",
    "clinical": "Clinical evidence",
    "safety": "Safety analysis",
    "critic": "Contradiction / gap analysis",
    "synthesis": "Final synthesis",
    "done": "Complete",
}


@dataclass
class EvidenceItem:
    claim: str
    evidence_type: str          # "mechanistic" | "preclinical" | "literature" | "clinical" | "safety"
    stance: str                 # "supporting" | "contradictory" | "neutral"
    source: str                 # human readable source name
    url: Optional[str] = None
    confidence: str = "moderate"  # "low" | "moderate" | "high"


@dataclass
class Candidate:
    drug: str
    target: Optional[str] = None
    pathway: Optional[str] = None
    existing_indication: Optional[str] = None
    mechanism_hypothesis: str = ""
    evidence: list = field(default_factory=list)   # list[EvidenceItem]
    clinical_trials: list = field(default_factory=list)
    safety_notes: list = field(default_factory=list)
    knowledge_gaps: list = field(default_factory=list)
    confidence: str = "moderate"
    review_status: str = "pending"  # pending | accepted | needs_more_evidence | rejected

    def to_dict(self):
        d = dict(self.__dict__)
        d["evidence"] = [e.__dict__ if hasattr(e, "__dict__") else e for e in self.evidence]
        return d


@dataclass
class AgentLog:
    id: str
    run_id: str
    agent: str
    action: str
    status: str          # "running" | "done" | "error"
    result_summary: str
    timestamp: float = field(default_factory=time.time)

    def to_dict(self):
        return self.__dict__


@dataclass
class ResearchRun:
    id: str
    disease: str
    status: str = "pending"     # pending -> one of PIPELINE_STEPS -> done | error
    hypothesis: Optional[str] = None
    created_at: float = field(default_factory=time.time)
    candidates: list = field(default_factory=list)   # list[Candidate]
    logs: list = field(default_factory=list)          # list[AgentLog]
    report: Optional[dict] = None
    error: Optional[str] = None

    def to_dict(self):
        return {
            "id": self.id,
            "disease": self.disease,
            "hypothesis": self.hypothesis,
            "status": self.status,
            "created_at": self.created_at,
            "candidates": [c.to_dict() for c in self.candidates],
            "logs": [l.to_dict() for l in self.logs],
            "report": self.report,
            "error": self.error,
        }
