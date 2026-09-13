"""Pydantic models for inter-service communication."""

from pydantic import BaseModel
from typing import Any, Dict, List, Optional


class InitTaskRequest(BaseModel):
    task_id: str
    task_data: Dict[str, Any]


class SetBackendRequest(BaseModel):
    backend: str


class SetBackendResponse(BaseModel):
    status: str
    environment_backend: str


class ExecuteSQLRequest(BaseModel):
    sql: str
    task_id: str


class ExecuteSQLResponse(BaseModel):
    result: str
    success: bool
    error: Optional[str] = None


class SubmitSQLRequest(BaseModel):
    sql: str
    task_id: str


class SubmitSQLResponse(BaseModel):
    passed: bool
    message: str
    reward: float = 0.0
    phase_completed: Optional[int] = None
    has_follow_up: bool = False
    follow_up_query: Optional[str] = None
    #: The engine's id for the grading execution of this submission, on a
    #: semantic-layer backend. Carried so the run's own results JSON records
    #: which engine query produced the graded answer: that file is one run by
    #: construction, so attribution needs no timestamp matching against the
    #: long-lived services. None on the raw backend, which never touches the
    #: engine. Never shown to the agent - system_agent/tools.py composes the
    #: agent-visible text from named fields, and this is not one of them.
    query_id: Optional[str] = None
    #: Leaderboard mode only: the Postgres SQL the semantic-layer engine actually
    #: dispatched for the graded execution (one entry per outbound statement),
    #: fetched via get_outbound_queries right after grading. This is what the
    #: submission file carries as the predicted SQL, since the agent's logical
    #: SQL cannot run on the BIRD team's evaluator. None on the raw path, where
    #: the submitted SQL already is Postgres SQL.
    outbound_sql: Optional[List[str]] = None
    #: The phase this submission was graded in (1 or 2), so the trajectory can
    #: name it without inferring it from the message text.
    phase: Optional[int] = None


class SchemaRequest(BaseModel):
    task_id: str


class ColumnMeaningRequest(BaseModel):
    task_id: str
    table_name: str
    column_name: str


class KnowledgeRequest(BaseModel):
    task_id: str
    knowledge_name: Optional[str] = None


class AskUserRequest(BaseModel):
    question: str
    task_id: str


class AskUserResponse(BaseModel):
    answer: str


class PhaseTransitionRequest(BaseModel):
    task_id: str
