from typing import Any, Dict, List, Optional

from pydantic import BaseModel


class RoleBindingResponse(BaseModel):
    organization_id: str
    workspace_id: str
    role: str


class MeResponse(BaseModel):
    id: str
    organization_id: str
    username: str
    display_name: str
    role_bindings: List[RoleBindingResponse]


class WorkspaceItemResponse(BaseModel):
    id: str
    organization_id: str
    name: str
    description: str


class WorkspaceListResponse(BaseModel):
    items: List[WorkspaceItemResponse]


class AskSessionCreateRequest(BaseModel):
    skill_id: str = "hr_recruiting"
    title: str = ""
    initial_context: Dict[str, Any] = {}


class AskSessionResponse(BaseModel):
    id: str
    user_id: str
    organization_id: str
    skill_id: str
    title: str
    status: str
    summary: str = ""
    active_context: Dict[str, Any] = {}
    feishu_binding_status: str = "UNBOUND"
    feishu_identity: Dict[str, Any] = {}
    required_scopes: List[str] = []
    missing_scopes: List[str] = []
    created_at: str
    updated_at: str


class AskTurnCreateRequest(BaseModel):
    content: str


class FeishuBindingStartRequest(BaseModel):
    force_rebind: bool = False


class FeishuBindingCompleteRequest(BaseModel):
    device_code: str = ""


class AskCommandRequest(BaseModel):
    command: str
    payload: Dict[str, Any] = {}


class AskOutputResponse(BaseModel):
    type: str
    text: str = ""
    data: Dict[str, Any] = {}


class AskPendingCommandResponse(BaseModel):
    id: str
    type: str
    title: str = ""
    payload: Dict[str, Any] = {}


class AskTurnResponse(BaseModel):
    id: str
    session_id: str
    role: str
    input_type: str
    content: str
    outputs: List[AskOutputResponse] = []
    state_patch: Dict[str, Any] = {}
    pending_commands: List[AskPendingCommandResponse] = []
    created_at: str


class AskTurnResultResponse(BaseModel):
    turn: AskTurnResponse
    outputs: List[AskOutputResponse] = []
    state_patch: Dict[str, Any] = {}
    pending_commands: List[AskPendingCommandResponse] = []


class AskTurnListResponse(BaseModel):
    items: List[AskTurnResponse]


class AskArtifactResponse(BaseModel):
    id: str
    session_id: str
    artifact_type: str
    title: str
    payload: Dict[str, Any] = {}
    created_at: str


class AskArtifactListResponse(BaseModel):
    items: List[AskArtifactResponse]


class AskJobStatusResponse(BaseModel):
    id: str
    status: str
    job_type: str
    summary: str = ""
    user_id: str = ""
    session_id: str = ""
    outputs: List[AskOutputResponse] = []
    error_message: str = ""
    created_at: str
    updated_at: str


class FeishuBindingStatusResponse(BaseModel):
    status: str
    verification_url: str = ""
    device_code: str = ""
    required_scopes: List[str] = []
    granted_scopes: List[str] = []
    missing_scopes: List[str] = []
    identity: Dict[str, Any] = {}
    hint: str = ""
    expires_in: Optional[int] = None
    checked_at: str = ""


class RunCreateRequest(BaseModel):
    workspace_id: str
    title: str
    goal: str
    requested_capability: str


class RunDecisionRequest(BaseModel):
    decision: str
    comment: Optional[str] = None


class MemoryFactInput(BaseModel):
    key: str
    value: str
    source: str = "user"


class MemoryTurnCreateRequest(BaseModel):
    role: str
    content: str
    facts: List[MemoryFactInput] = []


class MemoryFactResponse(BaseModel):
    key: str
    value: str
    source: str


class MemoryTurnResponse(BaseModel):
    id: str
    role: str
    content: str
    created_at: str


class MemorySnapshotResponse(BaseModel):
    session_id: str
    run_id: str
    total_turns: int
    summary: str
    facts: List[MemoryFactResponse]
    recent_turns: List[MemoryTurnResponse]


class StepResponse(BaseModel):
    id: str
    type: str
    name: str
    status: str


class ApprovalResponse(BaseModel):
    id: str
    status: str
    requested_by: str
    decided_by: Optional[str] = None
    comment: Optional[str] = None


class RunResponse(BaseModel):
    id: str
    organization_id: str
    workspace_id: str
    title: str
    goal: str
    requested_capability: str
    status: str
    orchestrator_backend: str
    approval_request_id: Optional[str] = None
    steps: List[StepResponse] = []
    approval: Optional[ApprovalResponse] = None


class RunListResponse(BaseModel):
    items: List[RunResponse]


class CancelResponse(BaseModel):
    id: str
    status: str


class KnowledgeSearchItemResponse(BaseModel):
    chunk_id: str
    title: str
    scope: str
    workspace_id: Optional[str] = None
    snippet: str
    score: Optional[float] = None
    block_type: Optional[str] = None
    section_path: List[str] = []
    page_number: Optional[int] = None
    page_end: Optional[int] = None
    sheet_name: Optional[str] = None
    slide_number: Optional[int] = None
    parser_backend: Optional[str] = None
    matched_terms: List[str] = []
    matched_query: Optional[str] = None


class KnowledgeSearchTraceResponse(BaseModel):
    backend_mode: str
    backend_reason: str
    query_variants: List[str]
    result_count: int
    rewrite_applied: bool = False


class KnowledgeIndexStatusResponse(BaseModel):
    backend_mode: str
    backend_reason: str
    collection_name: str
    collection_ready: bool = False
    indexed_record_count: int = 0
    endpoint: str = ""


class KnowledgeSearchResponse(BaseModel):
    items: List[KnowledgeSearchItemResponse]
    trace: KnowledgeSearchTraceResponse


class KnowledgeDocumentCreateRequest(BaseModel):
    workspace_id: Optional[str] = None
    scope: str = "workspace"
    title: str
    content: str


class KnowledgeDocumentCreateResponse(BaseModel):
    id: str
    title: str
    scope: str
    workspace_id: Optional[str] = None


class KnowledgeUploadIngestionSummaryResponse(BaseModel):
    parser_backend: Optional[str] = None
    page_start: Optional[int] = None
    page_end: Optional[int] = None
    section_samples: List[str] = []
    block_types: List[str] = []


class KnowledgeUploadStatusResponse(BaseModel):
    id: str
    workspace_id: Optional[str] = None
    scope: str
    filename: str
    mime_type: str
    source_type: str
    storage_path: str
    status: str
    created_at: str
    chunk_count: int = 0
    ingestion_summary: Optional[KnowledgeUploadIngestionSummaryResponse] = None
    error_code: Optional[str] = None
    error_message: Optional[str] = None


class KnowledgeUploadHistoryResponse(BaseModel):
    items: List[KnowledgeUploadStatusResponse]


class PlannerRequest(BaseModel):
    workspace_id: str
    goal: str
    requested_capability: str


class PlannerResponse(BaseModel):
    validated: bool
    plan: Dict[str, Any]


class InternalKnowledgeRetrieveRequest(BaseModel):
    organization_id: str
    workspace_id: str
    query: str


class ConnectorExecuteRequest(BaseModel):
    connector: str
    action: str
    workspace_id: str
    payload: Dict[str, Any] = {}


class ConnectorExecuteResponse(BaseModel):
    status: str
    connector: str
    action: str


class FeishuTargets(BaseModel):
    group_chat_ids: List[str] = []
    user_open_ids: List[str] = []


class FeishuEventRequest(BaseModel):
    event_type: str
    organization_id: str
    workspace_id: str
    run_id: str
    approval_id: Optional[str] = None
    targets: FeishuTargets
    payload: Dict[str, Any]


class DeliveryJobResponse(BaseModel):
    id: str
    status: str
    channel: str
    event_type: str
    attempts: int
