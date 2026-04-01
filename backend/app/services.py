import asyncio
import os
import shutil
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse

from app.ask_action_planner import AskActionPlanner
from app.ask_actions import AskActionDraftModule
from app.ask_context import AskContextManager
from app.ask_intent import AskIntentRouter
from app.ask_jobs import InMemoryAskJobStore
from app.ask_parse import AskMessageParseService
from app.ask_runtime import AskKnowledgeQaModule, AskPolicyEngine, AskRuntime
from app.ask_skill_hr_recruiting import HRRecruitingSkill
from app.ask_tools import FeishuBindingService, LarkCliRunner, build_tool_registry
from app.ask_targeting import AskTargetResolver
from app.core import (
    ApprovalRecord,
    ApprovalStatus,
    AskArtifactRecord,
    AskSessionRecord,
    AskTurnRecord,
    DeliveryJobRecord,
    DeliveryStatus,
    MemoryFactRecord,
    MemorySessionRecord,
    MemoryTurnRecord,
    KnowledgeDocumentRecord,
    RunRecord,
    RunStatus,
    StepRecord,
    StepStatus,
    StepType,
    UserRecord,
    make_id,
    utcnow,
)
from app.document_ingestion import ChunkPolicyEngine, DoclingParserAdapter
from app.document_models import KnowledgeChunkRecord, KnowledgeSourceFile, UploadStatus
from app.integrations import (
    EmbeddingProvider,
    FeishuMcpClient,
    MilvusKnowledgeIndex,
    QueryRewriteService,
    TemporalRuntime,
    tokenize_text,
)
from app.rag import AnswerGenerationService, RerankProvider
from app.persistence import SqlAlchemySnapshotStore, resolve_database_url
from app.storage import build_storage_adapter


HIGH_RISK_CAPABILITIES = {"erp.write", "crm.write"}
CONTROLLED_CONNECTORS = {
    "feishu": {"send_message", "send_card"},
    "email": {"send_mail"},
    "erp": {"upsert_order", "update_order"},
    "crm": {"upsert_account"},
}


class TemporalRunOrchestrator:
    def __init__(self, runtime: TemporalRuntime) -> None:
        self.runtime = runtime
        self.backend = "temporal"
        self.events: List[Dict[str, str]] = []

    def submit_run(self, run: RunRecord) -> None:
        event = {"type": "submit_run", "run_id": run.id, "status": run.status.value}
        event.update(self.runtime.describe())
        if self.runtime.mode == "sdk":
            asyncio.run(
                self.runtime.start_run_workflow(
                    workflow_id=run.id,
                    payload={
                        "run_id": run.id,
                        "organization_id": run.organization_id,
                        "workspace_id": run.workspace_id,
                        "title": run.title,
                        "goal": run.goal,
                        "requested_capability": run.requested_capability,
                        "requires_approval": run.status == RunStatus.WAITING_APPROVAL,
                    },
                )
            )
        self.events.append(event)

    def signal_approval(self, run_id: str, decision: str) -> None:
        if self.runtime.mode == "sdk":
            asyncio.run(
                self.runtime.signal_run_workflow(
                    workflow_id=run_id,
                    signal_name="approval",
                    payload={"decision": decision},
                )
            )
        self.events.append({"type": "approval", "run_id": run_id, "decision": decision})

    def signal_cancel(self, run_id: str) -> None:
        if self.runtime.mode == "sdk":
            asyncio.run(
                self.runtime.signal_run_workflow(
                    workflow_id=run_id,
                    signal_name="cancel",
                    payload={},
                )
            )
        self.events.append({"type": "cancel", "run_id": run_id})


class PlannerService:
    def plan(self, workspace_id: str, goal: str, requested_capability: str) -> Dict[str, Any]:
        return {
            "workspace_id": workspace_id,
            "goal": goal,
            "requested_capability": requested_capability,
            "steps": [
                {"type": "planning", "name": "Validate objective and workspace scope"},
                {
                    "type": "tool_call",
                    "name": "Execute controlled connector action",
                    "capability": requested_capability,
                },
            ],
        }


def build_search_hit(
    *,
    chunk_id: str,
    title: str,
    snippet: str,
    scope: str,
    workspace_id: Optional[str],
    score: Optional[float] = None,
    block_type: Optional[str] = None,
    section_path: Optional[List[str]] = None,
    page_number: Optional[int] = None,
    page_end: Optional[int] = None,
    sheet_name: Optional[str] = None,
    slide_number: Optional[int] = None,
    parser_backend: Optional[str] = None,
    matched_terms: Optional[List[str]] = None,
    matched_query: Optional[str] = None,
) -> Dict[str, Any]:
    return {
        "chunk_id": chunk_id,
        "title": title,
        "scope": scope,
        "workspace_id": workspace_id,
        "snippet": snippet,
        "score": score,
        "block_type": block_type,
        "section_path": section_path or [],
        "page_number": page_number,
        "page_end": page_end,
        "sheet_name": sheet_name,
        "slide_number": slide_number,
        "parser_backend": parser_backend,
        "matched_terms": matched_terms or [],
        "matched_query": matched_query,
    }


def _dedupe_terms(values: List[str]) -> List[str]:
    seen = set()
    result: List[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result


def build_match_explanation(query_variants: List[str], title: str, content: str) -> Tuple[Optional[str], List[str]]:
    if not query_variants:
        return None, []

    haystack_tokens = set(tokenize_text(f"{title} {content}"))
    best_variant = query_variants[0]
    best_terms: List[str] = []
    best_score = -1

    for variant in query_variants:
        variant_terms = _dedupe_terms(tokenize_text(variant))
        matched_terms = [term for term in variant_terms if term in haystack_tokens]
        if len(matched_terms) > best_score:
            best_variant = variant
            best_terms = matched_terms
            best_score = len(matched_terms)

    return best_variant, best_terms[:5]


class ServiceContainer:
    def __init__(self, database_url: str = None, temporal_runtime: Optional[TemporalRuntime] = None) -> None:
        resolved_database_url = resolve_database_url(database_url)
        self.store = SqlAlchemySnapshotStore(resolved_database_url)
        self.temporal_runtime = temporal_runtime or TemporalRuntime(
            target_hostport=os.getenv("EMATA_TEMPORAL_TARGET", "temporal:7233"),
            namespace=os.getenv("EMATA_TEMPORAL_NAMESPACE", "default"),
        )
        self.orchestrator = TemporalRunOrchestrator(self.temporal_runtime)
        self.planner_service = PlannerService()
        self.embedding_provider = EmbeddingProvider()
        self.rerank_provider = RerankProvider()
        self.answer_generation_service = AnswerGenerationService()
        self.query_rewriter = QueryRewriteService()
        self._storage = None
        self.document_parser = DoclingParserAdapter()
        self.chunk_policy = ChunkPolicyEngine()
        self.knowledge_index = MilvusKnowledgeIndex(
            uri=os.getenv("EMATA_MILVUS_URI", "http://milvus:19530"),
            collection_name=os.getenv("EMATA_MILVUS_COLLECTION", "emata_documents"),
            embedding_provider=self.embedding_provider,
            query_rewriter=self.query_rewriter,
        )
        self.feishu_client = FeishuMcpClient(
            executable=os.getenv("EMATA_FEISHU_MCP_EXECUTABLE", "npx"),
            package=os.getenv("EMATA_FEISHU_MCP_PACKAGE", "@larksuiteoapi/lark-mcp"),
            transport=os.getenv("EMATA_FEISHU_MCP_TRANSPORT", "stdio"),
        )
        self.lark_cli_runner = LarkCliRunner()
        self.feishu_binding_service = FeishuBindingService(
            store=self.store,
            runner=self.lark_cli_runner,
        )
        self.ask_job_store = InMemoryAskJobStore()
        self.ask_context_manager = AskContextManager()
        self.ask_tool_registry = build_tool_registry(
            binding_service=self.feishu_binding_service,
            runner=self.lark_cli_runner,
            search_callback=self.search_accessible_knowledge,
            parse_callback=self.parse_resume_payload,
            generation_provider=self.answer_generation_service,
            rerank_provider=self.rerank_provider,
        )
        self.ask_runtime = AskRuntime(
            skill_registry={"hr_recruiting": HRRecruitingSkill()},
            tool_registry=self.ask_tool_registry,
            policy_engine=AskPolicyEngine(),
            intent_router=AskIntentRouter(),
            knowledge_module=AskKnowledgeQaModule(),
            action_module=AskActionDraftModule(
                target_resolver=AskTargetResolver(),
                action_planner=AskActionPlanner(
                    parse_service=AskMessageParseService(
                        generation_service=self.answer_generation_service,
                    )
                ),
                job_store=self.ask_job_store,
            ),
            context_manager=self.ask_context_manager,
        )
        self._hydrate_knowledge_index()

    @property
    def storage(self):
        if self._storage is None:
            self._storage = build_storage_adapter()
        return self._storage

    def close(self) -> None:
        if hasattr(self.store, "engine"):
            self.store.engine.dispose()

    def _hydrate_knowledge_index(self) -> None:
        for document in self.store.documents.values():
            chunk_id = f"{document.id}-chunk-0"
            chunk = self.store.chunks.get(chunk_id)
            if chunk is None:
                chunk = KnowledgeChunkRecord(
                    id=chunk_id,
                    source_file_id=document.id,
                    organization_id=document.organization_id,
                    workspace_id=document.workspace_id,
                    scope=document.scope,
                    title=document.title,
                    content=document.content,
                    block_type="legacy_document",
                    section_path=[],
                    page_number=None,
                    sheet_name=None,
                    slide_number=None,
                    chunk_index=0,
                    token_count_estimate=max(1, len(document.content) // 2),
                    metadata={"legacy": True, "source_type": document.source_type},
                )
                self.store.chunks[chunk.id] = chunk
                self.store.save_chunk(chunk)
        for chunk in self.store.chunks.values():
            self._index_chunk(chunk)

    def get_knowledge_index_status(self) -> Dict[str, Any]:
        return {
            "backend_mode": self.knowledge_index.mode,
            "backend_reason": self.knowledge_index.reason,
            "collection_name": self.knowledge_index.collection_name,
            "collection_ready": bool(getattr(self.knowledge_index, "_collection_ready", False)),
            "indexed_record_count": len(self.knowledge_index.records),
            "endpoint": self._format_knowledge_index_endpoint(self.knowledge_index.uri),
        }

    def get_current_user(self) -> UserRecord:
        return self.store.users["user-admin"]

    @staticmethod
    def _format_knowledge_index_endpoint(uri: str) -> str:
        if not uri:
            return ""
        parsed = urlparse(uri if "://" in uri else f"http://{uri}")
        host = parsed.hostname or ""
        port = parsed.port or 19530
        if not host:
            return uri
        return f"{host}:{port}"

    def get_feishu_binding_status(self, user: UserRecord) -> Dict[str, Any]:
        return self.feishu_binding_service.get_status(user)

    def start_feishu_binding(self, user: UserRecord, *, force_rebind: bool = False) -> Dict[str, Any]:
        return self.feishu_binding_service.start_binding(user, force_rebind=force_rebind)

    def complete_feishu_binding(self, user: UserRecord, *, device_code: str = "") -> Dict[str, Any]:
        return self.feishu_binding_service.complete_binding(user, device_code=device_code)

    def disconnect_feishu_binding(self, user: UserRecord) -> Dict[str, Any]:
        return self.feishu_binding_service.disconnect(user)

    def list_workspaces(self, user: UserRecord):
        allowed = {binding.workspace_id for binding in user.role_bindings}
        items = []
        for workspace in self.store.workspaces.values():
            if workspace.organization_id == user.organization_id and workspace.id in allowed:
                items.append(workspace)
        items.sort(key=lambda item: item.id)
        return items

    def create_ask_session(
        self,
        user: UserRecord,
        *,
        skill_id: str,
        title: str = "",
        initial_context: Optional[Dict[str, Any]] = None,
    ) -> AskSessionRecord:
        session = AskSessionRecord(
            id=make_id("ask"),
            user_id=user.id,
            organization_id=user.organization_id,
            skill_id=skill_id,
            title=title or self._default_ask_session_title(skill_id),
            active_context=initial_context or {},
        )
        self.store.ask_sessions[session.id] = session
        self.store.save_ask_session(session)
        return session

    def get_ask_session(self, user: UserRecord, session_id: str) -> AskSessionRecord:
        session = self.store.ask_sessions[session_id]
        if session.user_id != user.id or session.organization_id != user.organization_id:
            raise PermissionError("ask_session_access_denied")
        return session

    def list_ask_turns(self, user: UserRecord, session_id: str) -> List[AskTurnRecord]:
        self.get_ask_session(user, session_id)
        items = [turn for turn in self.store.ask_turns.values() if turn.session_id == session_id]
        return sorted(items, key=lambda item: (item.created_at, item.id))

    def list_ask_artifacts(self, user: UserRecord, session_id: str) -> List[AskArtifactRecord]:
        self.get_ask_session(user, session_id)
        items = [artifact for artifact in self.store.ask_artifacts.values() if artifact.session_id == session_id]
        return sorted(items, key=lambda item: (item.created_at, item.id))

    def run_ask_turn(self, user: UserRecord, session_id: str, content: str) -> Dict[str, Any]:
        session = self.get_ask_session(user, session_id)
        runtime_result = self.ask_runtime.run_turn(session=session, message=content, user=user)
        return self._persist_ask_result(
            session=session,
            role="user",
            input_type="message",
            content=content,
            runtime_result=runtime_result,
        )

    def run_ask_command(
        self,
        user: UserRecord,
        session_id: str,
        command: str,
        payload: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        session = self.get_ask_session(user, session_id)
        runtime_result = self.ask_runtime.run_command(
            session=session,
            command=command,
            payload=payload or {},
            user=user,
        )
        return self._persist_ask_result(
            session=session,
            role="system",
            input_type="command",
            content=command,
            runtime_result=runtime_result,
        )

    def get_ask_job(self, user: UserRecord, job_id: str) -> Dict[str, Any]:
        job = self.ask_job_store.get(job_id)
        if job.get("user_id") not in {"", user.id}:
            raise PermissionError("ask_job_access_denied")
        return job

    @staticmethod
    def _default_ask_session_title(skill_id: str) -> str:
        if skill_id == "hr_recruiting":
            return "HR Recruiting Copilot"
        return "Ask Session"

    def _persist_ask_result(
        self,
        *,
        session: AskSessionRecord,
        role: str,
        input_type: str,
        content: str,
        runtime_result: Dict[str, Any],
    ) -> Dict[str, Any]:
        state_patch = runtime_result.get("state_patch", {})
        if state_patch:
            session.active_context = self.ask_context_manager.apply_patch(
                session.active_context or {},
                state_patch,
            )
        session.updated_at = utcnow()
        self.store.save_ask_session(session)

        turn = AskTurnRecord(
            id=make_id("askturn"),
            session_id=session.id,
            role=role,
            input_type=input_type,
            content=content,
            outputs=runtime_result.get("outputs", []),
            state_patch=state_patch,
            pending_commands=runtime_result.get("pending_commands", []),
        )
        self.store.ask_turns[turn.id] = turn
        self.store.save_ask_turn(turn)

        artifacts = []
        for item in runtime_result.get("artifacts", []):
            artifact = AskArtifactRecord(
                id=make_id("artifact"),
                session_id=session.id,
                artifact_type=item.get("artifact_type", "note"),
                title=item.get("title", item.get("artifact_type", "artifact")),
                payload=item.get("payload", {}),
            )
            self.store.ask_artifacts[artifact.id] = artifact
            self.store.save_ask_artifact(artifact)
            artifacts.append(artifact)

        return {
            "turn": turn,
            "outputs": turn.outputs,
            "state_patch": state_patch,
            "pending_commands": turn.pending_commands,
            "artifacts": artifacts,
        }

    def assert_workspace_access(self, user: UserRecord, workspace_id: str) -> None:
        allowed = {binding.workspace_id for binding in user.role_bindings}
        if workspace_id not in allowed:
            raise PermissionError("workspace_access_denied")

    def create_run(
        self,
        user: UserRecord,
        workspace_id: str,
        title: str,
        goal: str,
        requested_capability: str,
    ) -> RunRecord:
        self.assert_workspace_access(user, workspace_id)
        status = (
            RunStatus.WAITING_APPROVAL
            if requested_capability in HIGH_RISK_CAPABILITIES
            else RunStatus.RUNNING
        )
        run = RunRecord(
            id=make_id("run"),
            organization_id=user.organization_id,
            workspace_id=workspace_id,
            title=title,
            goal=goal,
            requested_capability=requested_capability,
            status=status,
            requested_by=user.id,
            orchestrator_backend=self.orchestrator.backend,
        )
        self.store.runs[run.id] = run
        self.store.save_run(run)
        self._create_step(
            run.id,
            StepType.PLANNING,
            "Generate structured plan",
            StepStatus.COMPLETED,
            {"planner": "langgraph"},
        )
        self._create_step(
            run.id,
            StepType.TOOL_CALL,
            "Execute controlled connector action",
            StepStatus.WAITING_APPROVAL if status == RunStatus.WAITING_APPROVAL else StepStatus.PENDING,
            {"requested_capability": requested_capability},
        )
        if status == RunStatus.WAITING_APPROVAL:
            self._create_step(
                run.id,
                StepType.APPROVAL,
                "Await human approval",
                StepStatus.WAITING_APPROVAL,
                {},
            )
            approval = ApprovalRecord(
                id=make_id("approval"),
                run_id=run.id,
                workspace_id=workspace_id,
                organization_id=user.organization_id,
                status=ApprovalStatus.PENDING,
                requested_by=user.id,
            )
            self.store.approvals[approval.id] = approval
            run.approval_request_id = approval.id
            self.store.save_approval(approval)
            self.store.save_run(run)
        self.orchestrator.submit_run(run)
        self._ensure_memory_session(run.id)
        return run

    def _ensure_memory_session(self, run_id: str) -> MemorySessionRecord:
        existing = self.store.memory_sessions.get(run_id)
        if existing:
            return existing
        session = MemorySessionRecord(id=make_id("session"), run_id=run_id)
        self.store.memory_sessions[run_id] = session
        self.store.save_memory_session(session)
        return session

    def _create_step(
        self,
        run_id: str,
        step_type: StepType,
        name: str,
        status: StepStatus,
        detail: Dict[str, Any],
    ) -> StepRecord:
        step = StepRecord(
            id=make_id("step"),
            run_id=run_id,
            type=step_type,
            name=name,
            status=status,
            detail=detail,
        )
        self.store.steps[step.id] = step
        self.store.runs[run_id].step_ids.append(step.id)
        self.store.save_step(step)
        self.store.save_run(self.store.runs[run_id])
        return step

    def get_run(self, user: UserRecord, run_id: str) -> RunRecord:
        run = self.store.runs[run_id]
        self.assert_workspace_access(user, run.workspace_id)
        return run

    def list_steps(self, run_id: str) -> List[StepRecord]:
        run = self.store.runs[run_id]
        return [self.store.steps[step_id] for step_id in run.step_ids]

    def decide_run(self, user: UserRecord, run_id: str, decision: str, comment: Optional[str]) -> Tuple[RunRecord, ApprovalRecord]:
        run = self.get_run(user, run_id)
        if not run.approval_request_id:
            raise ValueError("approval_not_required")
        approval = self.store.approvals[run.approval_request_id]
        if approval.status != ApprovalStatus.PENDING:
            raise ValueError("approval_already_decided")
        normalized = decision.lower()
        if normalized == "approve":
            approval.status = ApprovalStatus.APPROVED
            run.status = RunStatus.RUNNING
        elif normalized == "reject":
            approval.status = ApprovalStatus.REJECTED
            run.status = RunStatus.CANCELED
        else:
            raise ValueError("invalid_decision")
        approval.decided_by = user.id
        approval.comment = comment
        self.store.save_approval(approval)
        self.store.save_run(run)
        self.orchestrator.signal_approval(run.id, normalized)
        return run, approval

    def retry_run(self, user: UserRecord, run_id: str) -> RunRecord:
        run = self.get_run(user, run_id)
        run.status = RunStatus.RETRYING
        self.store.save_run(run)
        self.orchestrator.submit_run(run)
        return run

    def cancel_run(self, user: UserRecord, run_id: str) -> RunRecord:
        run = self.get_run(user, run_id)
        run.status = RunStatus.CANCELED
        self.store.save_run(run)
        self.orchestrator.signal_cancel(run.id)
        return run

    def search_knowledge(
        self,
        user: UserRecord,
        workspace_id: str,
        query: str,
        cancel_event: Optional[Any] = None,
    ):
        self.assert_workspace_access(user, workspace_id)
        search_payload = self.knowledge_index.search_with_trace(
            query=query,
            organization_id=user.organization_id,
            workspace_id=workspace_id,
            limit=10,
            cancel_event=cancel_event,
        )
        results = search_payload["items"]
        query_variants = search_payload["trace"].get("query_variants", [query])
        if results:
            return {
                "items": [
                    self._build_search_hit_from_record(item, query_variants)
                    for item in results
                ],
                "trace": search_payload["trace"],
            }
        lowered = query.lower()
        items = []
        for document in self.store.documents.values():
            if document.organization_id != user.organization_id:
                continue
            if document.scope == "workspace" and document.workspace_id != workspace_id:
                continue
            haystack = f"{document.title} {document.content}".lower()
            if lowered in haystack:
                items.append(
                    {
                        "document_id": document.id,
                        "title": document.title,
                        "content": document.content,
                        "metadata": {
                            "scope": document.scope,
                            "workspace_id": document.workspace_id,
                            "block_type": "legacy_document",
                            "source_type": document.source_type,
                        },
                    }
                )
        fallback_trace = search_payload["trace"].copy()
        fallback_trace["backend_mode"] = "document-store"
        fallback_trace["backend_reason"] = "legacy_document_fallback"
        fallback_trace["result_count"] = len(items)
        return {
            "items": [
                self._build_search_hit_from_record(item, query_variants)
                for item in items
            ],
            "trace": fallback_trace,
        }

    def search_accessible_knowledge(self, *, user: UserRecord, query: str, limit: int = 3) -> Dict[str, Any]:
        accessible = sorted({binding.workspace_id for binding in user.role_bindings})
        merged_items: List[Dict[str, Any]] = []
        merged_variants: List[str] = [query]
        for workspace_id in accessible:
            try:
                payload = self.search_knowledge(user, workspace_id, query)
            except PermissionError:
                continue
            merged_items.extend(payload.get("items", []))
            merged_variants = payload.get("trace", {}).get("query_variants", merged_variants)
        merged_items.sort(key=lambda item: item.get("score") or 0.0, reverse=True)
        return {
            "items": merged_items[:limit],
            "trace": {
                "backend_mode": "accessible_workspaces",
                "query_variants": merged_variants,
                "result_count": len(merged_items[:limit]),
            },
        }

    def parse_resume_payload(
        self,
        *,
        local_path: str = "",
        content: str = "",
        source_type: str = "",
    ) -> Dict[str, Any]:
        if content:
            lines = [line.strip() for line in str(content).splitlines() if line.strip()]
            return {
                "status": "parsed",
                "source_type": source_type or "text",
                "text": "\n".join(lines),
                "highlights": lines[:5],
            }
        if not local_path:
            raise ValueError("resume_payload_missing")
        resolved_source_type = source_type or self._infer_source_type(local_path, "")
        blocks = self.document_parser.parse_file(local_path, resolved_source_type)
        text_parts = [block.text.strip() for block in blocks if getattr(block, "text", "").strip()]
        return {
            "status": "parsed",
            "source_type": resolved_source_type,
            "text": "\n".join(text_parts),
            "highlights": text_parts[:5],
        }

    def get_upload_status(self, user: UserRecord, upload_id: str) -> KnowledgeSourceFile:
        source_file = self.store.source_files.get(upload_id)
        if source_file is None:
            raise KeyError("upload_not_found")
        if source_file.organization_id != user.organization_id:
            raise PermissionError("upload_out_of_scope")
        if source_file.scope == "workspace" and source_file.workspace_id:
            self.assert_workspace_access(user, source_file.workspace_id)
        return source_file

    def list_uploads(self, user: UserRecord, workspace_id: str, limit: int = 10) -> List[KnowledgeSourceFile]:
        self.assert_workspace_access(user, workspace_id)
        items = []
        for source_file in self.store.source_files.values():
            if source_file.organization_id != user.organization_id:
                continue
            if source_file.scope == "workspace" and source_file.workspace_id != workspace_id:
                continue
            if source_file.scope == "shared":
                items.append(source_file)
                continue
            items.append(source_file)
        items.sort(key=lambda item: item.created_at, reverse=True)
        return items[:limit]

    def ingest_uploaded_file(
        self,
        user: UserRecord,
        workspace_id: str,
        scope: str,
        filename: str,
        content_type: str,
        file_bytes: Optional[bytes] = None,
        local_source_path: Optional[str] = None,
        cancel_event: Optional[Any] = None,
    ) -> KnowledgeSourceFile:
        if scope == "workspace":
            self.assert_workspace_access(user, workspace_id)
            scoped_workspace_id = workspace_id
        else:
            scoped_workspace_id = None

        source_type = self._infer_source_type(filename, content_type)
        source_file = KnowledgeSourceFile(
            id=make_id("upload"),
            organization_id=user.organization_id,
            workspace_id=scoped_workspace_id,
            scope=scope,
            filename=filename,
            mime_type=content_type,
            source_type=source_type,
            storage_path="",
            status=UploadStatus.PROCESSING,
        )

        storage_key = "/".join(
            [
                user.organization_id,
                scoped_workspace_id or "shared",
                source_file.id,
                Path(filename).name,
            ]
        )
        if local_source_path:
            source_file.storage_path = self.storage.put_file(storage_key, local_source_path, content_type)
        elif file_bytes is not None:
            source_file.storage_path = self.storage.put_bytes(storage_key, file_bytes, content_type)
        else:
            raise ValueError("upload_payload_missing")
        self.store.source_files[source_file.id] = source_file
        self.store.save_source_file(source_file)

        temp_dir = tempfile.mkdtemp(prefix="emata-ingestion-")
        saved_chunk_ids: List[str] = []
        try:
            if self._is_upload_canceled(cancel_event):
                return self._finalize_canceled_upload(source_file, saved_chunk_ids)
            local_path = self.storage.get_to_local_path(source_file.storage_path, temp_dir)
            blocks = self.document_parser.parse_file(local_path, source_type)
            chunks = self.chunk_policy.build_chunks(
                blocks=blocks,
                source_file_id=source_file.id,
                title=Path(filename).stem,
                organization_id=user.organization_id,
                workspace_id=scoped_workspace_id,
                scope=scope,
            )
            if self._is_upload_canceled(cancel_event):
                return self._finalize_canceled_upload(source_file, saved_chunk_ids)
            for chunk in chunks:
                if self._is_upload_canceled(cancel_event):
                    return self._finalize_canceled_upload(source_file, saved_chunk_ids)
                self.store.chunks[chunk.id] = chunk
                self.store.save_chunk(chunk)
                saved_chunk_ids.append(chunk.id)
                self._index_chunk(chunk)
            source_file.status = UploadStatus.COMPLETED
            source_file.error_code = None
            source_file.error_message = None
            self.store.save_source_file(source_file)
            return source_file
        except ValueError as exc:
            self._rollback_uploaded_chunks(saved_chunk_ids)
            if str(exc) == "upload_canceled":
                source_file.status = UploadStatus.CANCELED
                source_file.error_code = "upload_canceled"
                source_file.error_message = "upload_canceled"
                self.store.save_source_file(source_file)
                return source_file
            source_file.status = UploadStatus.FAILED
            source_file.error_code = str(exc)
            source_file.error_message = str(exc)
            self.store.save_source_file(source_file)
            raise
        except Exception as exc:
            self._rollback_uploaded_chunks(saved_chunk_ids)
            source_file.status = UploadStatus.FAILED
            source_file.error_code = f"upload_processing_failed:{exc.__class__.__name__}"
            source_file.error_message = str(exc)
            self.store.save_source_file(source_file)
            raise
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    @staticmethod
    def _infer_source_type(filename: str, content_type: str) -> str:
        normalized = (content_type or "").lower()
        if normalized == "text/plain":
            return "txt"
        suffix = Path(filename).suffix.lower()
        mapping = {
            ".txt": "txt",
            ".pdf": "pdf",
            ".docx": "docx",
            ".pptx": "pptx",
            ".xlsx": "xlsx",
        }
        if suffix in mapping:
            return mapping[suffix]
        raise ValueError("unsupported_source_type")

    def ingest_knowledge(
        self,
        user: UserRecord,
        workspace_id: str,
        scope: str,
        title: str,
        content: str,
    ):
        if scope == "workspace":
            self.assert_workspace_access(user, workspace_id)
            scoped_workspace_id = workspace_id
        else:
            scoped_workspace_id = None
        document = KnowledgeDocumentRecord(
            id=make_id("doc"),
            organization_id=user.organization_id,
            workspace_id=scoped_workspace_id,
            scope=scope,
            title=title,
            content=content,
        )
        self.store.documents[document.id] = document
        self.store.save_document(document)
        chunk = KnowledgeChunkRecord(
            id=f"{document.id}-chunk-0",
            source_file_id=document.id,
            organization_id=document.organization_id,
            workspace_id=document.workspace_id,
            scope=document.scope,
            title=document.title,
            content=document.content,
            block_type="legacy_document",
            section_path=[],
            page_number=None,
            sheet_name=None,
            slide_number=None,
            chunk_index=0,
            token_count_estimate=max(1, len(document.content) // 2),
            metadata={"legacy": True, "source_type": document.source_type},
        )
        self.store.chunks[chunk.id] = chunk
        self.store.save_chunk(chunk)
        self._index_chunk(chunk)
        return document

    def _index_chunk(self, chunk: KnowledgeChunkRecord) -> None:
        self.knowledge_index.upsert_chunk(
            chunk_id=chunk.id,
            title=chunk.title,
            content=chunk.content,
            metadata={
                "organization_id": chunk.organization_id,
                "workspace_id": chunk.workspace_id,
                "scope": chunk.scope,
                "block_type": chunk.block_type,
                "section_path": chunk.section_path,
                "page_number": chunk.page_number,
                "page_end": chunk.metadata.get("page_end"),
                "sheet_name": chunk.sheet_name,
                "slide_number": chunk.slide_number,
                "parser": chunk.metadata.get("parser"),
                "source_type": chunk.metadata.get("source_type"),
            },
        )

    def get_chunk_count_for_source_file(self, source_file_id: str) -> int:
        return sum(1 for chunk in self.store.chunks.values() if chunk.source_file_id == source_file_id)

    def get_ingestion_summary_for_source_file(self, source_file_id: str) -> Optional[Dict[str, Any]]:
        chunks = [
            chunk
            for chunk in self.store.chunks.values()
            if chunk.source_file_id == source_file_id
        ]
        if not chunks:
            return None

        chunks.sort(key=lambda item: item.chunk_index)
        section_samples: List[str] = []
        block_types: List[str] = []
        page_numbers: List[int] = []
        parser_backend = None

        for chunk in chunks:
            if chunk.page_number is not None:
                page_numbers.append(chunk.page_number)
            if chunk.block_type and chunk.block_type not in block_types:
                block_types.append(chunk.block_type)
            if chunk.section_path:
                label = " / ".join(chunk.section_path)
                if label not in section_samples:
                    section_samples.append(label)
            if parser_backend is None:
                parser_backend = chunk.metadata.get("parser") or chunk.metadata.get("source_type")

        source_file = self.store.source_files.get(source_file_id)
        if parser_backend is None and source_file is not None:
            parser_backend = source_file.source_type.upper()

        page_end_candidates = [
            chunk.metadata.get("page_end", chunk.page_number)
            for chunk in chunks
            if chunk.metadata.get("page_end", chunk.page_number) is not None
        ]

        return {
            "parser_backend": parser_backend,
            "page_start": min(page_numbers) if page_numbers else None,
            "page_end": max(page_end_candidates) if page_end_candidates else None,
            "section_samples": section_samples[:3],
            "block_types": block_types,
        }

    @staticmethod
    def _build_search_hit_from_record(item: Dict[str, Any], query_variants: List[str]) -> Dict[str, Any]:
        metadata = item.get("metadata", {})
        matched_query, matched_terms = build_match_explanation(
            query_variants,
            item.get("title", ""),
            item.get("content", ""),
        )
        return build_search_hit(
            chunk_id=item["document_id"],
            title=item["title"],
            snippet=item.get("content", "")[:160],
            scope=metadata.get("scope", "workspace"),
            workspace_id=metadata.get("workspace_id"),
            score=item.get("score"),
            block_type=metadata.get("block_type"),
            section_path=metadata.get("section_path", []),
            page_number=metadata.get("page_number"),
            page_end=metadata.get("page_end"),
            sheet_name=metadata.get("sheet_name"),
            slide_number=metadata.get("slide_number"),
            parser_backend=metadata.get("parser") or metadata.get("source_type"),
            matched_terms=matched_terms,
            matched_query=matched_query,
        )

    @staticmethod
    def _is_upload_canceled(cancel_event: Optional[Any]) -> bool:
        return bool(cancel_event and cancel_event.is_set())

    def _finalize_canceled_upload(
        self,
        source_file: KnowledgeSourceFile,
        saved_chunk_ids: List[str],
    ) -> KnowledgeSourceFile:
        self._rollback_uploaded_chunks(saved_chunk_ids)
        source_file.status = UploadStatus.CANCELED
        source_file.error_code = "upload_canceled"
        source_file.error_message = "upload_canceled"
        self.store.save_source_file(source_file)
        return source_file

    def _rollback_uploaded_chunks(self, chunk_ids: List[str]) -> None:
        for chunk_id in reversed(chunk_ids):
            self.knowledge_index.delete_chunk(chunk_id)
            self.store.chunks.pop(chunk_id, None)
            if hasattr(self.store, "delete_chunk"):
                self.store.delete_chunk(chunk_id)

    def execute_connector(self, connector: str, action: str) -> str:
        allowed_actions = CONTROLLED_CONNECTORS.get(connector)
        if not allowed_actions or action not in allowed_actions:
            raise PermissionError("connector_action_not_allowed")
        return "ACCEPTED"

    def enqueue_feishu_event(
        self,
        organization_id: str,
        workspace_id: str,
        event_type: str,
        payload: Dict[str, Any],
        targets: Dict[str, List[str]],
    ) -> DeliveryJobRecord:
        job = DeliveryJobRecord(
            id=make_id("delivery"),
            organization_id=organization_id,
            workspace_id=workspace_id,
            channel="feishu",
            event_type=event_type,
            payload=payload,
            targets=targets,
            status=DeliveryStatus.QUEUED,
        )
        self.store.delivery_jobs[job.id] = job
        self.store.save_delivery_job(job)
        delivery_result = self.feishu_client.deliver(event_type=event_type, payload=payload, targets=targets)
        if delivery_result["status"] == "SENT":
            job.status = DeliveryStatus.SENT
        elif delivery_result["status"] == "FAILED":
            job.status = DeliveryStatus.FAILED
            job.last_error = delivery_result["reason"]
        self.store.save_delivery_job(job)
        return job

    def retry_delivery(self, delivery_id: str) -> DeliveryJobRecord:
        job = self.store.delivery_jobs[delivery_id]
        job.status = DeliveryStatus.QUEUED
        job.attempts += 1
        delivery_result = self.feishu_client.deliver(
            event_type=job.event_type,
            payload=job.payload,
            targets=job.targets,
        )
        if delivery_result["status"] == "SENT":
            job.status = DeliveryStatus.SENT
            job.last_error = None
        elif delivery_result["status"] == "FAILED":
            job.status = DeliveryStatus.FAILED
            job.last_error = delivery_result["reason"]
        self.store.save_delivery_job(job)
        return job

    def append_memory_turn(
        self,
        user: UserRecord,
        run_id: str,
        role: str,
        content: str,
        facts: List[Dict[str, str]],
    ) -> MemorySessionRecord:
        run = self.get_run(user, run_id)
        session = self._ensure_memory_session(run.id)
        turn = MemoryTurnRecord(
            id=make_id("turn"),
            run_id=run.id,
            role=role,
            content=content,
        )
        self.store.memory_turns[turn.id] = turn
        session.recent_turn_ids.append(turn.id)
        session.total_turns += 1
        self.store.save_memory_turn(turn)
        for fact in facts:
            session.facts.append(
                MemoryFactRecord(
                    key=fact["key"],
                    value=fact["value"],
                    source=fact.get("source", role),
                )
            )
        self._compress_memory_session(session)
        self.store.save_memory_session(session)
        return session

    def _compress_memory_session(self, session: MemorySessionRecord) -> None:
        keep_recent = 3
        while len(session.recent_turn_ids) > keep_recent:
            old_turn_id = session.recent_turn_ids.pop(0)
            session.compressed_turn_ids.append(old_turn_id)
        if session.compressed_turn_ids:
            compressed_turns = [
                self.store.memory_turns[turn_id].content
                for turn_id in session.compressed_turn_ids
            ]
            session.summary = " ".join(compressed_turns[-5:])

    def get_memory_snapshot(self, user: UserRecord, run_id: str) -> Dict[str, Any]:
        self.get_run(user, run_id)
        session = self._ensure_memory_session(run_id)
        return {
            "session_id": session.id,
            "run_id": run_id,
            "total_turns": session.total_turns,
            "summary": session.summary,
            "facts": session.facts,
            "recent_turns": [
                self.store.memory_turns[turn_id] for turn_id in session.recent_turn_ids
            ],
        }
