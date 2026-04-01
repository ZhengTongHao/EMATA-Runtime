from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional
from uuid import uuid4

from app.document_models import KnowledgeChunkRecord, KnowledgeSourceFile


def utcnow() -> str:
    return datetime.utcnow().replace(microsecond=0).isoformat() + "Z"


def make_id(prefix: str) -> str:
    return f"{prefix}-{uuid4().hex[:8]}"


class RunStatus(str, Enum):
    CREATED = "CREATED"
    PLANNING = "PLANNING"
    WAITING_APPROVAL = "WAITING_APPROVAL"
    RUNNING = "RUNNING"
    RETRYING = "RETRYING"
    BLOCKED = "BLOCKED"
    COMPENSATING = "COMPENSATING"
    FAILED = "FAILED"
    COMPLETED = "COMPLETED"
    CANCELED = "CANCELED"


class StepType(str, Enum):
    PLANNING = "planning"
    RETRIEVAL = "retrieval"
    TOOL_CALL = "tool_call"
    APPROVAL = "approval"
    NOTIFICATION = "notification"
    COMPENSATION = "compensation"


class StepStatus(str, Enum):
    PENDING = "PENDING"
    COMPLETED = "COMPLETED"
    WAITING_APPROVAL = "WAITING_APPROVAL"


class ApprovalStatus(str, Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class DeliveryStatus(str, Enum):
    QUEUED = "QUEUED"
    SENT = "SENT"
    FAILED = "FAILED"


@dataclass
class RoleBindingRecord:
    user_id: str
    organization_id: str
    workspace_id: str
    role: str


@dataclass
class UserRecord:
    id: str
    organization_id: str
    username: str
    display_name: str
    role_bindings: List[RoleBindingRecord] = field(default_factory=list)


@dataclass
class WorkspaceRecord:
    id: str
    organization_id: str
    name: str
    description: str


@dataclass
class KnowledgeDocumentRecord:
    id: str
    organization_id: str
    workspace_id: Optional[str]
    scope: str
    title: str
    content: str
    source_type: str = "manual"


@dataclass
class StepRecord:
    id: str
    run_id: str
    type: StepType
    name: str
    status: StepStatus
    detail: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ApprovalRecord:
    id: str
    run_id: str
    workspace_id: str
    organization_id: str
    status: ApprovalStatus
    requested_by: str
    decided_by: Optional[str] = None
    comment: Optional[str] = None
    created_at: str = field(default_factory=utcnow)
    updated_at: str = field(default_factory=utcnow)


@dataclass
class DeliveryJobRecord:
    id: str
    organization_id: str
    workspace_id: str
    channel: str
    event_type: str
    payload: Dict[str, Any]
    targets: Dict[str, List[str]]
    status: DeliveryStatus
    attempts: int = 0
    last_error: Optional[str] = None
    created_at: str = field(default_factory=utcnow)
    updated_at: str = field(default_factory=utcnow)


@dataclass
class RunRecord:
    id: str
    organization_id: str
    workspace_id: str
    title: str
    goal: str
    requested_capability: str
    status: RunStatus
    requested_by: str
    orchestrator_backend: str
    approval_request_id: Optional[str] = None
    step_ids: List[str] = field(default_factory=list)
    created_at: str = field(default_factory=utcnow)
    updated_at: str = field(default_factory=utcnow)


@dataclass
class MemoryFactRecord:
    key: str
    value: str
    source: str = "user"


@dataclass
class MemoryTurnRecord:
    id: str
    run_id: str
    role: str
    content: str
    created_at: str = field(default_factory=utcnow)


@dataclass
class MemorySessionRecord:
    id: str
    run_id: str
    summary: str = ""
    total_turns: int = 0
    compressed_turn_ids: List[str] = field(default_factory=list)
    recent_turn_ids: List[str] = field(default_factory=list)
    facts: List[MemoryFactRecord] = field(default_factory=list)
    created_at: str = field(default_factory=utcnow)
    updated_at: str = field(default_factory=utcnow)


@dataclass
class AskSessionRecord:
    id: str
    user_id: str
    organization_id: str
    skill_id: str
    title: str
    status: str = "ACTIVE"
    summary: str = ""
    active_context: Dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=utcnow)
    updated_at: str = field(default_factory=utcnow)


@dataclass
class AskTurnRecord:
    id: str
    session_id: str
    role: str
    input_type: str
    content: str
    outputs: List[Dict[str, Any]] = field(default_factory=list)
    state_patch: Dict[str, Any] = field(default_factory=dict)
    pending_commands: List[Dict[str, Any]] = field(default_factory=list)
    created_at: str = field(default_factory=utcnow)


@dataclass
class AskArtifactRecord:
    id: str
    session_id: str
    artifact_type: str
    title: str
    payload: Dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=utcnow)


@dataclass
class FeishuBindingRecord:
    id: str
    user_id: str
    organization_id: str
    status: str = "UNBOUND"
    identity_type: str = ""
    user_open_id: str = ""
    user_name: str = ""
    config_dir: str = ""
    verification_url: str = ""
    device_code: str = ""
    granted_scopes: List[str] = field(default_factory=list)
    missing_scopes: List[str] = field(default_factory=list)
    hint: str = ""
    expires_in: Optional[int] = None
    checked_at: str = ""
    created_at: str = field(default_factory=utcnow)
    updated_at: str = field(default_factory=utcnow)


def build_seed_documents() -> Dict[str, KnowledgeDocumentRecord]:
    return {
        "doc-shared-policy": KnowledgeDocumentRecord(
            id="doc-shared-policy",
            organization_id="org-acme",
            workspace_id=None,
            scope="shared",
            title="Company Shared Policy",
            content="Shared company policy for approvals, compliance, and policy reviews.",
        ),
        "doc-finance-policy": KnowledgeDocumentRecord(
            id="doc-finance-policy",
            organization_id="org-acme",
            workspace_id="workspace-finance",
            scope="workspace",
            title="Finance Expense Policy",
            content=(
                "Finance policy for reimbursements, ERP changes, and approval policy steps. "
                "Standard reimbursement cap is 3000 CNY per submission. "
                "Amounts above 3000 CNY require additional finance manager approval."
            ),
        ),
        "doc-finance-quick-reference": KnowledgeDocumentRecord(
            id="doc-finance-quick-reference",
            organization_id="org-acme",
            workspace_id="workspace-finance",
            scope="workspace",
            title="Expense Approval Quick Reference",
            content=(
                "Expense approval quick reference. Standard reimbursement cap is 3000 CNY per claim. "
                "Claims above 3000 CNY require finance manager approval. "
                "Claims above 10000 CNY require finance director approval. "
                "Hotel lodging reimbursement is capped at 800 CNY per night."
            ),
        ),
        "doc-sales-battlecard": KnowledgeDocumentRecord(
            id="doc-sales-battlecard",
            organization_id="org-acme",
            workspace_id="workspace-sales",
            scope="workspace",
            title="Sales Battlecard",
            content="Sales-only competitive notes and battlecard content.",
        ),
    }


class InMemoryStore:
    def __init__(self) -> None:
        self.workspaces: Dict[str, WorkspaceRecord] = {
            "workspace-finance": WorkspaceRecord(
                id="workspace-finance",
                organization_id="org-acme",
                name="Finance",
                description="Finance operations workspace.",
            ),
            "workspace-sales": WorkspaceRecord(
                id="workspace-sales",
                organization_id="org-acme",
                name="Sales",
                description="Sales operations workspace.",
            ),
        }
        self.users: Dict[str, UserRecord] = {
            "user-admin": UserRecord(
                id="user-admin",
                organization_id="org-acme",
                username="admin",
                display_name="EMATA Admin",
                role_bindings=[
                    RoleBindingRecord(
                        user_id="user-admin",
                        organization_id="org-acme",
                        workspace_id="workspace-finance",
                        role="workspace_admin",
                    ),
                    RoleBindingRecord(
                        user_id="user-admin",
                        organization_id="org-acme",
                        workspace_id="workspace-sales",
                        role="workspace_admin",
                    ),
                ],
            )
        }
        self.documents: Dict[str, KnowledgeDocumentRecord] = {
            "doc-shared-policy": KnowledgeDocumentRecord(
                id="doc-shared-policy",
                organization_id="org-acme",
                workspace_id=None,
                scope="shared",
                title="Company Shared Policy",
                content="Shared company policy for approvals, compliance, and policy reviews.",
            ),
            "doc-finance-policy": KnowledgeDocumentRecord(
                id="doc-finance-policy",
                organization_id="org-acme",
                workspace_id="workspace-finance",
                scope="workspace",
                title="Finance Expense Policy",
                content=(
                    "Finance policy for reimbursements, ERP changes, and approval policy steps. "
                    "Standard reimbursement cap is 3000 CNY per submission. "
                    "Amounts above 3000 CNY require additional finance approval. "
                    "报销标准额度为 3000 元，超过 3000 元需要财务额外审批。"
                ),
            ),
            "doc-sales-battlecard": KnowledgeDocumentRecord(
                id="doc-sales-battlecard",
                organization_id="org-acme",
                workspace_id="workspace-sales",
                scope="workspace",
                title="Sales Battlecard",
                content="Sales-only competitive notes and battlecard content.",
            ),
        }
        self.documents = build_seed_documents()
        self.chunks: Dict[str, KnowledgeChunkRecord] = {}
        self.source_files: Dict[str, KnowledgeSourceFile] = {}
        self.runs: Dict[str, RunRecord] = {}
        self.steps: Dict[str, StepRecord] = {}
        self.approvals: Dict[str, ApprovalRecord] = {}
        self.delivery_jobs: Dict[str, DeliveryJobRecord] = {}
        self.memory_sessions: Dict[str, MemorySessionRecord] = {}
        self.memory_turns: Dict[str, MemoryTurnRecord] = {}
        self.ask_sessions: Dict[str, AskSessionRecord] = {}
        self.ask_turns: Dict[str, AskTurnRecord] = {}
        self.ask_artifacts: Dict[str, AskArtifactRecord] = {}
        self.feishu_bindings: Dict[str, FeishuBindingRecord] = {}
