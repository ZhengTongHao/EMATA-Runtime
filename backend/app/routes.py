import asyncio
import os
import shutil
import tempfile
import threading
from pathlib import Path

from fastapi import APIRouter, Depends, FastAPI, File, Form, HTTPException, Request, UploadFile, status
from fastapi.responses import StreamingResponse

from app.contracts import (
    ApprovalResponse,
    AskArtifactListResponse,
    AskArtifactResponse,
    AskJobStatusResponse,
    FeishuBindingCompleteRequest,
    FeishuBindingStartRequest,
    FeishuBindingStatusResponse,
    AskCommandRequest,
    AskSessionCreateRequest,
    AskSessionResponse,
    AskOutputResponse,
    AskPendingCommandResponse,
    AskTurnCreateRequest,
    AskTurnListResponse,
    AskTurnResponse,
    AskTurnResultResponse,
    CancelResponse,
    ConnectorExecuteRequest,
    ConnectorExecuteResponse,
    DeliveryJobResponse,
    FeishuEventRequest,
    InternalKnowledgeRetrieveRequest,
    KnowledgeDocumentCreateRequest,
    KnowledgeDocumentCreateResponse,
    KnowledgeSearchItemResponse,
    KnowledgeIndexStatusResponse,
    KnowledgeSearchResponse,
    KnowledgeSearchTraceResponse,
    KnowledgeUploadIngestionSummaryResponse,
    KnowledgeUploadHistoryResponse,
    KnowledgeUploadStatusResponse,
    MeResponse,
    PlannerRequest,
    PlannerResponse,
    RoleBindingResponse,
    MemorySnapshotResponse,
    MemoryTurnCreateRequest,
    MemoryTurnResponse,
    MemoryFactResponse,
    RunCreateRequest,
    RunDecisionRequest,
    RunListResponse,
    RunResponse,
    StepResponse,
    WorkspaceItemResponse,
    WorkspaceListResponse,
)
from app.services import ServiceContainer


def get_container(request: Request) -> ServiceContainer:
    return request.app.state.container


def get_current_user(request: Request):
    return request.app.state.container.get_current_user()


def serialize_run(container: ServiceContainer, run_id: str) -> RunResponse:
    run = container.store.runs[run_id]
    approval_payload = None
    if run.approval_request_id:
        approval = container.store.approvals[run.approval_request_id]
        approval_payload = ApprovalResponse(
            id=approval.id,
            status=approval.status.value,
            requested_by=approval.requested_by,
            decided_by=approval.decided_by,
            comment=approval.comment,
        )
    return RunResponse(
        id=run.id,
        organization_id=run.organization_id,
        workspace_id=run.workspace_id,
        title=run.title,
        goal=run.goal,
        requested_capability=run.requested_capability,
        status=run.status.value,
        orchestrator_backend=run.orchestrator_backend,
        approval_request_id=run.approval_request_id,
        steps=[
            StepResponse(
                id=step.id,
                type=step.type.value,
                name=step.name,
                status=step.status.value,
            )
            for step in container.list_steps(run.id)
        ],
        approval=approval_payload,
    )


def serialize_feishu_binding_status(payload: dict) -> FeishuBindingStatusResponse:
    return FeishuBindingStatusResponse(
        status=payload.get("status", "UNBOUND"),
        verification_url=payload.get("verification_url", ""),
        device_code=payload.get("device_code", ""),
        required_scopes=payload.get("required_scopes", []),
        granted_scopes=payload.get("granted_scopes", []),
        missing_scopes=payload.get("missing_scopes", []),
        identity=payload.get("identity", {}),
        hint=payload.get("hint", ""),
        expires_in=payload.get("expires_in"),
        checked_at=payload.get("checked_at", ""),
    )


def serialize_ask_session(container: ServiceContainer, user, session) -> AskSessionResponse:
    binding = container.get_feishu_binding_status(user)
    return AskSessionResponse(
        id=session.id,
        user_id=session.user_id,
        organization_id=session.organization_id,
        skill_id=session.skill_id,
        title=session.title,
        status=session.status,
        summary=session.summary,
        active_context=session.active_context,
        feishu_binding_status=binding.get("status", "UNBOUND"),
        feishu_identity=binding.get("identity", {}),
        required_scopes=binding.get("required_scopes", []),
        missing_scopes=binding.get("missing_scopes", []),
        created_at=session.created_at,
        updated_at=session.updated_at,
    )


def serialize_ask_output(item: dict) -> AskOutputResponse:
    return AskOutputResponse(
        type=item.get("type", "message"),
        text=item.get("text", ""),
        data=item.get("data", {}),
    )


def serialize_ask_pending_command(item: dict) -> AskPendingCommandResponse:
    return AskPendingCommandResponse(
        id=item.get("id", ""),
        type=item.get("type", ""),
        title=item.get("title", ""),
        payload=item.get("payload", {}),
    )


def serialize_ask_turn(turn) -> AskTurnResponse:
    return AskTurnResponse(
        id=turn.id,
        session_id=turn.session_id,
        role=turn.role,
        input_type=turn.input_type,
        content=turn.content,
        outputs=[serialize_ask_output(item) for item in turn.outputs],
        state_patch=turn.state_patch,
        pending_commands=[serialize_ask_pending_command(item) for item in turn.pending_commands],
        created_at=turn.created_at,
    )


def serialize_ask_turn_result(payload: dict) -> AskTurnResultResponse:
    return AskTurnResultResponse(
        turn=serialize_ask_turn(payload["turn"]),
        outputs=[serialize_ask_output(item) for item in payload.get("outputs", [])],
        state_patch=payload.get("state_patch", {}),
        pending_commands=[
            serialize_ask_pending_command(item) for item in payload.get("pending_commands", [])
        ],
    )


def serialize_ask_artifact(artifact) -> AskArtifactResponse:
    return AskArtifactResponse(
        id=artifact.id,
        session_id=artifact.session_id,
        artifact_type=artifact.artifact_type,
        title=artifact.title,
        payload=artifact.payload,
        created_at=artifact.created_at,
    )


def serialize_ask_job(payload: dict) -> AskJobStatusResponse:
    return AskJobStatusResponse(
        id=payload.get("id", ""),
        status=payload.get("status", "pending"),
        job_type=payload.get("job_type", ""),
        summary=payload.get("summary", ""),
        user_id=payload.get("user_id", ""),
        session_id=payload.get("session_id", ""),
        outputs=[serialize_ask_output(item) for item in payload.get("outputs", [])],
        error_message=payload.get("error_message", ""),
        created_at=payload.get("created_at", ""),
        updated_at=payload.get("updated_at", ""),
    )


def serialize_search_item(item: dict) -> KnowledgeSearchItemResponse:
    return KnowledgeSearchItemResponse(
        chunk_id=item["chunk_id"],
        title=item["title"],
        scope=item["scope"],
        workspace_id=item.get("workspace_id"),
        snippet=item["snippet"],
        score=item.get("score"),
        block_type=item.get("block_type"),
        section_path=item.get("section_path", []),
        page_number=item.get("page_number"),
        page_end=item.get("page_end"),
        sheet_name=item.get("sheet_name"),
        slide_number=item.get("slide_number"),
        parser_backend=item.get("parser_backend"),
        matched_terms=item.get("matched_terms", []),
        matched_query=item.get("matched_query"),
    )


def serialize_upload_status(container: ServiceContainer, source_file) -> KnowledgeUploadStatusResponse:
    ingestion_summary = container.get_ingestion_summary_for_source_file(source_file.id)
    return KnowledgeUploadStatusResponse(
        id=source_file.id,
        workspace_id=source_file.workspace_id,
        scope=source_file.scope,
        filename=source_file.filename,
        mime_type=source_file.mime_type,
        source_type=source_file.source_type,
        storage_path=source_file.storage_path,
        status=source_file.status.value,
        created_at=source_file.created_at,
        chunk_count=container.get_chunk_count_for_source_file(source_file.id),
        ingestion_summary=(
            KnowledgeUploadIngestionSummaryResponse(**ingestion_summary)
            if ingestion_summary is not None
            else None
        ),
        error_code=source_file.error_code,
        error_message=source_file.error_message,
    )


def _map_upload_error_status(detail: str) -> int:
    if detail == "upload_canceled":
        return 499
    if detail in {"unsupported_source_type", "upload_payload_missing", "invalid_pdf_file"}:
        return status.HTTP_400_BAD_REQUEST
    if detail == "parse_timeout":
        return status.HTTP_504_GATEWAY_TIMEOUT
    if detail == "mineru_executable_not_found":
        return status.HTTP_503_SERVICE_UNAVAILABLE
    if detail == "mineru_output_missing" or detail.startswith("parse_failed:"):
        return status.HTTP_502_BAD_GATEWAY
    if detail.startswith("upload_processing_failed:"):
        return status.HTTP_500_INTERNAL_SERVER_ERROR
    return status.HTTP_400_BAD_REQUEST


public_router = APIRouter(prefix="/api/v1")
internal_router = APIRouter(prefix="/internal")
UPLOAD_STREAM_CHUNK_SIZE = 1024 * 1024


@public_router.get("/me", response_model=MeResponse)
def get_me(user=Depends(get_current_user)) -> MeResponse:
    return MeResponse(
        id=user.id,
        organization_id=user.organization_id,
        username=user.username,
        display_name=user.display_name,
        role_bindings=[
            RoleBindingResponse(
                organization_id=binding.organization_id,
                workspace_id=binding.workspace_id,
                role=binding.role,
            )
            for binding in user.role_bindings
        ],
    )


@public_router.get("/workspaces", response_model=WorkspaceListResponse)
def list_workspaces(
    container: ServiceContainer = Depends(get_container),
    user=Depends(get_current_user),
) -> WorkspaceListResponse:
    return WorkspaceListResponse(
        items=[
            WorkspaceItemResponse(
                id=item.id,
                organization_id=item.organization_id,
                name=item.name,
                description=item.description,
            )
            for item in container.list_workspaces(user)
        ]
    )


@public_router.post("/ask/sessions", response_model=AskSessionResponse, status_code=status.HTTP_201_CREATED)
def create_ask_session(
    payload: AskSessionCreateRequest,
    container: ServiceContainer = Depends(get_container),
    user=Depends(get_current_user),
) -> AskSessionResponse:
    session = container.create_ask_session(
        user=user,
        skill_id=payload.skill_id,
        title=payload.title,
        initial_context=payload.initial_context,
    )
    return serialize_ask_session(container, user, session)


@public_router.get("/ask/sessions/{session_id}", response_model=AskSessionResponse)
def get_ask_session(
    session_id: str,
    container: ServiceContainer = Depends(get_container),
    user=Depends(get_current_user),
) -> AskSessionResponse:
    try:
        session = container.get_ask_session(user, session_id)
    except KeyError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="ask_session_not_found") from exc
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    return serialize_ask_session(container, user, session)


@public_router.get("/ask/bindings/feishu/status", response_model=FeishuBindingStatusResponse)
def get_feishu_binding_status(
    container: ServiceContainer = Depends(get_container),
    user=Depends(get_current_user),
) -> FeishuBindingStatusResponse:
    return serialize_feishu_binding_status(container.get_feishu_binding_status(user))


@public_router.post("/ask/bindings/feishu/start", response_model=FeishuBindingStatusResponse)
def start_feishu_binding(
    payload: FeishuBindingStartRequest,
    container: ServiceContainer = Depends(get_container),
    user=Depends(get_current_user),
) -> FeishuBindingStatusResponse:
    try:
        status_payload = container.start_feishu_binding(user, force_rebind=payload.force_rebind)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc
    return serialize_feishu_binding_status(status_payload)


@public_router.post("/ask/bindings/feishu/complete", response_model=FeishuBindingStatusResponse)
def complete_feishu_binding(
    payload: FeishuBindingCompleteRequest,
    container: ServiceContainer = Depends(get_container),
    user=Depends(get_current_user),
) -> FeishuBindingStatusResponse:
    try:
        status_payload = container.complete_feishu_binding(user, device_code=payload.device_code)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc
    return serialize_feishu_binding_status(status_payload)


@public_router.post("/ask/bindings/feishu/disconnect", response_model=FeishuBindingStatusResponse)
def disconnect_feishu_binding(
    container: ServiceContainer = Depends(get_container),
    user=Depends(get_current_user),
) -> FeishuBindingStatusResponse:
    return serialize_feishu_binding_status(container.disconnect_feishu_binding(user))


@public_router.get("/ask/sessions/{session_id}/turns", response_model=AskTurnListResponse)
def list_ask_turns(
    session_id: str,
    container: ServiceContainer = Depends(get_container),
    user=Depends(get_current_user),
) -> AskTurnListResponse:
    try:
        turns = container.list_ask_turns(user, session_id)
    except KeyError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="ask_session_not_found") from exc
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    return AskTurnListResponse(items=[serialize_ask_turn(turn) for turn in turns])


@public_router.get("/ask/sessions/{session_id}/artifacts", response_model=AskArtifactListResponse)
def list_ask_artifacts(
    session_id: str,
    container: ServiceContainer = Depends(get_container),
    user=Depends(get_current_user),
) -> AskArtifactListResponse:
    try:
        artifacts = container.list_ask_artifacts(user, session_id)
    except KeyError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="ask_session_not_found") from exc
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    return AskArtifactListResponse(items=[serialize_ask_artifact(item) for item in artifacts])


@public_router.post("/ask/sessions/{session_id}/turns", response_model=AskTurnResultResponse)
def create_ask_turn(
    session_id: str,
    payload: AskTurnCreateRequest,
    container: ServiceContainer = Depends(get_container),
    user=Depends(get_current_user),
) -> AskTurnResultResponse:
    try:
        result = container.run_ask_turn(user, session_id, payload.content)
    except KeyError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="ask_session_not_found") from exc
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc
    return serialize_ask_turn_result(result)


@public_router.post("/ask/sessions/{session_id}/commands", response_model=AskTurnResultResponse)
def run_ask_command(
    session_id: str,
    payload: AskCommandRequest,
    container: ServiceContainer = Depends(get_container),
    user=Depends(get_current_user),
) -> AskTurnResultResponse:
    try:
        result = container.run_ask_command(user, session_id, payload.command, payload.payload)
    except KeyError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="ask_session_not_found") from exc
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc
    return serialize_ask_turn_result(result)


@public_router.get("/ask/jobs/{job_id}", response_model=AskJobStatusResponse)
def get_ask_job(
    job_id: str,
    container: ServiceContainer = Depends(get_container),
    user=Depends(get_current_user),
) -> AskJobStatusResponse:
    try:
        payload = container.get_ask_job(user, job_id)
    except KeyError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="ask_job_not_found") from exc
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    return serialize_ask_job(payload)


@public_router.get("/ask/jobs/{job_id}/events")
def stream_ask_job_events(
    job_id: str,
    container: ServiceContainer = Depends(get_container),
    user=Depends(get_current_user),
):
    try:
        container.get_ask_job(user, job_id)
    except KeyError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="ask_job_not_found") from exc
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    return StreamingResponse(
        container.ask_job_store.stream(job_id),
        media_type="text/event-stream",
    )


@public_router.post("/runs", response_model=RunResponse, status_code=status.HTTP_201_CREATED)
def create_run(
    payload: RunCreateRequest,
    container: ServiceContainer = Depends(get_container),
    user=Depends(get_current_user),
) -> RunResponse:
    try:
        run = container.create_run(
            user=user,
            workspace_id=payload.workspace_id,
            title=payload.title,
            goal=payload.goal,
            requested_capability=payload.requested_capability,
        )
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    return serialize_run(container, run.id)


@public_router.get("/runs", response_model=RunListResponse)
def list_runs(
    container: ServiceContainer = Depends(get_container),
    user=Depends(get_current_user),
) -> RunListResponse:
    allowed = {binding.workspace_id for binding in user.role_bindings}
    run_ids = [
        run.id
        for run in container.store.runs.values()
        if run.organization_id == user.organization_id and run.workspace_id in allowed
    ]
    run_ids.sort()
    return RunListResponse(items=[serialize_run(container, run_id) for run_id in run_ids])


@public_router.post("/runs/{run_id}/memory/turns", response_model=MemorySnapshotResponse, status_code=status.HTTP_201_CREATED)
def append_memory_turn(
    run_id: str,
    payload: MemoryTurnCreateRequest,
    container: ServiceContainer = Depends(get_container),
    user=Depends(get_current_user),
) -> MemorySnapshotResponse:
    snapshot = container.append_memory_turn(
        user=user,
        run_id=run_id,
        role=payload.role,
        content=payload.content,
        facts=[item.dict() for item in payload.facts],
    )
    return _serialize_memory_snapshot(container, run_id, snapshot)


@public_router.get("/runs/{run_id}/memory", response_model=MemorySnapshotResponse)
def get_run_memory(
    run_id: str,
    container: ServiceContainer = Depends(get_container),
    user=Depends(get_current_user),
) -> MemorySnapshotResponse:
    snapshot = container.get_memory_snapshot(user, run_id)
    return _serialize_memory_snapshot(container, run_id, snapshot)


@public_router.get("/runs/{run_id}", response_model=RunResponse)
def get_run(
    run_id: str,
    container: ServiceContainer = Depends(get_container),
    user=Depends(get_current_user),
) -> RunResponse:
    try:
        container.get_run(user, run_id)
    except KeyError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="run_not_found") from exc
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    return serialize_run(container, run_id)


@public_router.post("/runs/{run_id}/approve", response_model=RunResponse)
def approve_run(
    run_id: str,
    payload: RunDecisionRequest,
    container: ServiceContainer = Depends(get_container),
    user=Depends(get_current_user),
) -> RunResponse:
    try:
        run, _approval = container.decide_run(user, run_id, payload.decision, payload.comment)
    except KeyError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="run_not_found") from exc
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return serialize_run(container, run.id)


@public_router.post("/runs/{run_id}/retry", response_model=RunResponse)
def retry_run(
    run_id: str,
    container: ServiceContainer = Depends(get_container),
    user=Depends(get_current_user),
) -> RunResponse:
    run = container.retry_run(user, run_id)
    return serialize_run(container, run.id)


@public_router.post("/runs/{run_id}/cancel", response_model=CancelResponse)
def cancel_run(
    run_id: str,
    container: ServiceContainer = Depends(get_container),
    user=Depends(get_current_user),
) -> CancelResponse:
    run = container.cancel_run(user, run_id)
    return CancelResponse(id=run.id, status=run.status.value)


@public_router.get("/knowledge/search", response_model=KnowledgeSearchResponse)
async def search_knowledge(
    request: Request,
    workspace_id: str,
    query: str,
    container: ServiceContainer = Depends(get_container),
    user=Depends(get_current_user),
) -> KnowledgeSearchResponse:
    cancel_event = threading.Event()
    try:
        loop = asyncio.get_running_loop()
        worker = loop.run_in_executor(
            None,
            lambda: container.search_knowledge(
                user,
                workspace_id,
                query,
                cancel_event=cancel_event,
            ),
        )
        while not worker.done():
            if await request.is_disconnected():
                cancel_event.set()
            await asyncio.sleep(0.05)
        payload = await worker
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except ValueError as exc:
        detail = str(exc)
        status_code = 499 if detail == "search_canceled" else status.HTTP_400_BAD_REQUEST
        raise HTTPException(status_code=status_code, detail=detail) from exc
    return KnowledgeSearchResponse(
        items=[serialize_search_item(item) for item in payload["items"]],
        trace=KnowledgeSearchTraceResponse(**payload["trace"]),
    )


@public_router.get("/knowledge/index/status", response_model=KnowledgeIndexStatusResponse)
def get_knowledge_index_status(
    container: ServiceContainer = Depends(get_container),
) -> KnowledgeIndexStatusResponse:
    return KnowledgeIndexStatusResponse(**container.get_knowledge_index_status())


@public_router.post("/knowledge/documents", response_model=KnowledgeDocumentCreateResponse)
def create_document(
    payload: KnowledgeDocumentCreateRequest,
    container: ServiceContainer = Depends(get_container),
    user=Depends(get_current_user),
) -> KnowledgeDocumentCreateResponse:
    workspace_id = payload.workspace_id or "workspace-finance"
    document = container.ingest_knowledge(
        user=user,
        workspace_id=workspace_id,
        scope=payload.scope,
        title=payload.title,
        content=payload.content,
    )
    return KnowledgeDocumentCreateResponse(
        id=document.id,
        title=document.title,
        scope=document.scope,
        workspace_id=document.workspace_id,
    )


@public_router.get("/knowledge/uploads", response_model=KnowledgeUploadHistoryResponse)
def list_uploads(
    workspace_id: str,
    limit: int = 10,
    container: ServiceContainer = Depends(get_container),
    user=Depends(get_current_user),
) -> KnowledgeUploadHistoryResponse:
    items = container.list_uploads(user, workspace_id, limit=limit)
    return KnowledgeUploadHistoryResponse(
        items=[serialize_upload_status(container, source_file) for source_file in items]
    )


@public_router.get("/knowledge/uploads/{upload_id}", response_model=KnowledgeUploadStatusResponse)
def get_upload_status(
    upload_id: str,
    container: ServiceContainer = Depends(get_container),
    user=Depends(get_current_user),
) -> KnowledgeUploadStatusResponse:
    try:
        source_file = container.get_upload_status(user, upload_id)
    except KeyError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    return serialize_upload_status(container, source_file)


@public_router.post(
    "/knowledge/uploads",
    response_model=KnowledgeUploadStatusResponse,
    status_code=status.HTTP_201_CREATED,
)
async def upload_knowledge_file(
    request: Request,
    workspace_id: str = Form(...),
    scope: str = Form("workspace"),
    file: UploadFile = File(...),
    container: ServiceContainer = Depends(get_container),
    user=Depends(get_current_user),
) -> KnowledgeUploadStatusResponse:
    cancel_event = threading.Event()
    stream_temp_dir = tempfile.mkdtemp(prefix="emata-upload-stream-")
    stream_path = os.path.join(stream_temp_dir, Path(file.filename or "upload.bin").name)
    try:
        with open(stream_path, "wb") as handle:
            while True:
                chunk = await file.read(UPLOAD_STREAM_CHUNK_SIZE)
                if not chunk:
                    break
                handle.write(chunk)
                if await request.is_disconnected():
                    cancel_event.set()
                    raise HTTPException(status_code=499, detail="upload_canceled")
        loop = asyncio.get_running_loop()
        worker = loop.run_in_executor(
            None,
            lambda: container.ingest_uploaded_file(
                user=user,
                workspace_id=workspace_id,
                scope=scope,
                filename=file.filename or "upload.bin",
                content_type=file.content_type or "application/octet-stream",
                local_source_path=stream_path,
                cancel_event=cancel_event,
            ),
        )
        while not worker.done():
            if await request.is_disconnected():
                cancel_event.set()
            await asyncio.sleep(0.1)
        source_file = await worker
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except ValueError as exc:
        detail = str(exc)
        raise HTTPException(status_code=_map_upload_error_status(detail), detail=detail) from exc
    finally:
        await file.close()
        shutil.rmtree(stream_temp_dir, ignore_errors=True)

    return serialize_upload_status(container, source_file)


@internal_router.post("/planner/plan", response_model=PlannerResponse)
def build_plan(
    payload: PlannerRequest,
    container: ServiceContainer = Depends(get_container),
) -> PlannerResponse:
    plan = container.planner_service.plan(
        payload.workspace_id,
        payload.goal,
        payload.requested_capability,
    )
    return PlannerResponse(validated=True, plan=plan)


@internal_router.post("/knowledge/retrieve", response_model=KnowledgeSearchResponse)
async def retrieve_knowledge(
    request: Request,
    payload: InternalKnowledgeRetrieveRequest,
    container: ServiceContainer = Depends(get_container),
    user=Depends(get_current_user),
) -> KnowledgeSearchResponse:
    cancel_event = threading.Event()
    try:
        loop = asyncio.get_running_loop()
        worker = loop.run_in_executor(
            None,
            lambda: container.search_knowledge(
                user,
                payload.workspace_id,
                payload.query,
                cancel_event=cancel_event,
            ),
        )
        while not worker.done():
            if await request.is_disconnected():
                cancel_event.set()
            await asyncio.sleep(0.05)
        response_payload = await worker
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except ValueError as exc:
        detail = str(exc)
        status_code = 499 if detail == "search_canceled" else status.HTTP_400_BAD_REQUEST
        raise HTTPException(status_code=status_code, detail=detail) from exc
    return KnowledgeSearchResponse(
        items=[serialize_search_item(item) for item in response_payload["items"]],
        trace=KnowledgeSearchTraceResponse(**response_payload["trace"]),
    )


@internal_router.post("/connectors/execute", response_model=ConnectorExecuteResponse)
def execute_connector(
    payload: ConnectorExecuteRequest,
    container: ServiceContainer = Depends(get_container),
) -> ConnectorExecuteResponse:
    try:
        result = container.execute_connector(payload.connector, payload.action)
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    return ConnectorExecuteResponse(
        status=result,
        connector=payload.connector,
        action=payload.action,
    )


@internal_router.post("/feishu/events", response_model=DeliveryJobResponse, status_code=status.HTTP_202_ACCEPTED)
def enqueue_feishu_event(
    payload: FeishuEventRequest,
    container: ServiceContainer = Depends(get_container),
) -> DeliveryJobResponse:
    job = container.enqueue_feishu_event(
        organization_id=payload.organization_id,
        workspace_id=payload.workspace_id,
        event_type=payload.event_type,
        payload=payload.payload,
        targets=payload.targets.dict(),
    )
    return DeliveryJobResponse(
        id=job.id,
        status=job.status.value,
        channel=job.channel,
        event_type=job.event_type,
        attempts=job.attempts,
    )


@internal_router.post("/feishu/delivery/{delivery_id}/retry", response_model=DeliveryJobResponse)
def retry_delivery(
    delivery_id: str,
    container: ServiceContainer = Depends(get_container),
) -> DeliveryJobResponse:
    try:
        job = container.retry_delivery(delivery_id)
    except KeyError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="delivery_not_found") from exc
    return DeliveryJobResponse(
        id=job.id,
        status=job.status.value,
        channel=job.channel,
        event_type=job.event_type,
        attempts=job.attempts,
    )


def register_routers(app: FastAPI) -> None:
    app.include_router(public_router)
    app.include_router(internal_router)


def _serialize_memory_snapshot(
    container: ServiceContainer,
    run_id: str,
    snapshot: dict,
) -> MemorySnapshotResponse:
    if hasattr(snapshot, "id"):
        snapshot = container.get_memory_snapshot(container.get_current_user(), run_id)
    return MemorySnapshotResponse(
        session_id=snapshot["session_id"],
        run_id=run_id,
        total_turns=snapshot["total_turns"],
        summary=snapshot["summary"],
        facts=[
            MemoryFactResponse(key=item.key, value=item.value, source=item.source)
            for item in snapshot["facts"]
        ],
        recent_turns=[
            MemoryTurnResponse(
                id=item.id,
                role=item.role,
                content=item.content,
                created_at=item.created_at,
            )
            for item in snapshot["recent_turns"]
        ],
    )
