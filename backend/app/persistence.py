import json
import os
from dataclasses import asdict, is_dataclass
from datetime import datetime
from enum import Enum
from typing import Any, Dict, Iterable

from sqlalchemy import Column, String, Text, create_engine, select
from sqlalchemy.orm import Session, declarative_base, sessionmaker

from app.core import (
    ApprovalRecord,
    ApprovalStatus,
    AskArtifactRecord,
    AskSessionRecord,
    AskTurnRecord,
    DeliveryJobRecord,
    DeliveryStatus,
    FeishuBindingRecord,
    InMemoryStore,
    KnowledgeDocumentRecord,
    MemoryFactRecord,
    MemorySessionRecord,
    MemoryTurnRecord,
    RunRecord,
    RunStatus,
    StepRecord,
    StepStatus,
    StepType,
    build_seed_documents,
)
from app.document_models import KnowledgeChunkRecord, KnowledgeSourceFile, UploadStatus

Base = declarative_base()


def _utcnow() -> str:
    return datetime.utcnow().replace(microsecond=0).isoformat() + "Z"


class SnapshotModel(Base):
    __tablename__ = "state_snapshots"

    entity_type = Column(String(64), primary_key=True)
    entity_id = Column(String(128), primary_key=True)
    payload = Column(Text, nullable=False)


def _serialize(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if is_dataclass(value):
        return {key: _serialize(item) for key, item in asdict(value).items()}
    if isinstance(value, list):
        return [_serialize(item) for item in value]
    if isinstance(value, dict):
        return {key: _serialize(item) for key, item in value.items()}
    return value


class SqlAlchemySnapshotStore(InMemoryStore):
    def __init__(self, database_url: str) -> None:
        self.database_url = database_url
        connect_args = {"check_same_thread": False} if database_url.startswith("sqlite") else {}
        self.engine = create_engine(database_url, future=True, connect_args=connect_args)
        self.session_factory = sessionmaker(bind=self.engine, future=True)
        Base.metadata.create_all(self.engine)

        super().__init__()
        self._hydrate()
        self._sync_seed_documents()
        self._persist_seed_documents()

    def _hydrate(self) -> None:
        with self.session_factory() as session:
            rows = session.execute(select(SnapshotModel)).scalars().all()
        grouped: Dict[str, Dict[str, Dict[str, Any]]] = {}
        for row in rows:
            grouped.setdefault(row.entity_type, {})[row.entity_id] = json.loads(row.payload)
        self.runs = {
            key: self._build_run(value) for key, value in grouped.get("run", {}).items()
        }
        self.steps = {
            key: self._build_step(value) for key, value in grouped.get("step", {}).items()
        }
        self.approvals = {
            key: self._build_approval(value)
            for key, value in grouped.get("approval", {}).items()
        }
        self.delivery_jobs = {
            key: self._build_delivery(value)
            for key, value in grouped.get("delivery_job", {}).items()
        }
        self.memory_sessions = {}
        for value in grouped.get("memory_session", {}).values():
            session_record = self._build_memory_session(value)
            self.memory_sessions[session_record.run_id] = session_record
        self.memory_turns = {
            key: self._build_memory_turn(value)
            for key, value in grouped.get("memory_turn", {}).items()
        }
        self.ask_sessions = {
            key: self._build_ask_session(value)
            for key, value in grouped.get("ask_session", {}).items()
        }
        self.ask_turns = {
            key: self._build_ask_turn(value)
            for key, value in grouped.get("ask_turn", {}).items()
        }
        self.ask_artifacts = {
            key: self._build_ask_artifact(value)
            for key, value in grouped.get("ask_artifact", {}).items()
        }
        self.feishu_bindings = {
            key: self._build_feishu_binding(value)
            for key, value in grouped.get("feishu_binding", {}).items()
        }
        persisted_docs = {
            key: self._build_document(value)
            for key, value in grouped.get("document", {}).items()
        }
        if persisted_docs:
            self.documents = persisted_docs
        self.chunks = {
            key: self._build_chunk(value)
            for key, value in grouped.get("chunk", {}).items()
        }
        self.source_files = {
            key: self._build_source_file(value)
            for key, value in grouped.get("source_file", {}).items()
        }

    def _persist_seed_documents(self) -> None:
        for document in self.documents.values():
            self.save_document(document)

    def _sync_seed_documents(self) -> None:
        seed_documents = build_seed_documents()

        self._remove_corrupted_demo_documents()

        for document_id, seed_document in seed_documents.items():
            current = self.documents.get(document_id)
            if current is None or self._should_refresh_seed_document(current, seed_document):
                self.documents[document_id] = seed_document
                self.save_document(seed_document)
                self._upsert_seed_chunk(seed_document)
            elif f"{document_id}-chunk-0" not in self.chunks:
                self._upsert_seed_chunk(current)

    def _remove_corrupted_demo_documents(self) -> None:
        doomed_ids = [
            document.id
            for document in self.documents.values()
            if document.title == "Expense Approval Quick Reference"
            and self._looks_corrupted_text(document.content)
            and document.id != "doc-finance-quick-reference"
        ]
        for document_id in doomed_ids:
            self.documents.pop(document_id, None)
            self.delete_document(document_id)
            chunk_ids = [
                chunk_id
                for chunk_id, chunk in self.chunks.items()
                if chunk.source_file_id == document_id
            ]
            for chunk_id in chunk_ids:
                self.chunks.pop(chunk_id, None)
                self.delete_chunk(chunk_id)

    def _upsert_seed_chunk(self, document: KnowledgeDocumentRecord) -> None:
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
        self.chunks[chunk.id] = chunk
        self.save_chunk(chunk)

    @staticmethod
    def _should_refresh_seed_document(
        current: KnowledgeDocumentRecord,
        seed_document: KnowledgeDocumentRecord,
    ) -> bool:
        if current.content == seed_document.content:
            return False
        if current.id == "doc-finance-policy":
            return current.content.strip() in {
                "Finance policy for reimbursements, ERP changes, and approval policy steps.",
                (
                    "Finance policy for reimbursements, ERP changes, and approval policy steps. "
                    "Standard reimbursement cap is 3000 CNY per submission. "
                    "Amounts above 3000 CNY require additional finance approval. "
                    "鎶ラ攢鏍囧噯棰濆害涓?3000 鍏冿紝瓒呰繃 3000 鍏冮渶瑕佽储鍔￠澶栧鎵广€?"
                ),
            }
        if current.id == "doc-finance-quick-reference":
            return SqlAlchemySnapshotStore._looks_corrupted_text(current.content)
        return False

    @staticmethod
    def _looks_corrupted_text(value: str) -> bool:
        if not value:
            return False
        stripped = value.strip()
        return "????" in stripped or stripped.count("?") >= 8

    def _upsert(self, entity_type: str, entity_id: str, payload: Dict[str, Any]) -> None:
        encoded = json.dumps(_serialize(payload), ensure_ascii=False)
        with self.session_factory() as session:
            row = session.get(SnapshotModel, {"entity_type": entity_type, "entity_id": entity_id})
            if row is None:
                row = SnapshotModel(entity_type=entity_type, entity_id=entity_id, payload=encoded)
                session.add(row)
            else:
                row.payload = encoded
            session.commit()

    def _bulk_save(self, pairs: Iterable[Any]) -> None:
        for entity_type, entity_id, payload in pairs:
            self._upsert(entity_type, entity_id, payload)

    def _delete(self, entity_type: str, entity_id: str) -> None:
        with self.session_factory() as session:
            row = session.get(SnapshotModel, {"entity_type": entity_type, "entity_id": entity_id})
            if row is not None:
                session.delete(row)
                session.commit()

    def save_run(self, run: RunRecord) -> None:
        self._upsert("run", run.id, _serialize(run))

    def save_step(self, step: StepRecord) -> None:
        self._upsert("step", step.id, _serialize(step))

    def save_approval(self, approval: ApprovalRecord) -> None:
        self._upsert("approval", approval.id, _serialize(approval))

    def save_delivery_job(self, job: DeliveryJobRecord) -> None:
        self._upsert("delivery_job", job.id, _serialize(job))

    def save_document(self, document: KnowledgeDocumentRecord) -> None:
        self._upsert("document", document.id, _serialize(document))

    def save_chunk(self, chunk: KnowledgeChunkRecord) -> None:
        self._upsert("chunk", chunk.id, _serialize(chunk))

    def save_source_file(self, source_file: KnowledgeSourceFile) -> None:
        self._upsert("source_file", source_file.id, _serialize(source_file))

    def delete_chunk(self, chunk_id: str) -> None:
        self._delete("chunk", chunk_id)

    def delete_document(self, document_id: str) -> None:
        self._delete("document", document_id)

    def save_memory_session(self, session_record: MemorySessionRecord) -> None:
        self._upsert("memory_session", session_record.id, _serialize(session_record))

    def save_memory_turn(self, turn: MemoryTurnRecord) -> None:
        self._upsert("memory_turn", turn.id, _serialize(turn))

    def save_ask_session(self, session_record: AskSessionRecord) -> None:
        self._upsert("ask_session", session_record.id, _serialize(session_record))

    def save_ask_turn(self, turn: AskTurnRecord) -> None:
        self._upsert("ask_turn", turn.id, _serialize(turn))

    def save_ask_artifact(self, artifact: AskArtifactRecord) -> None:
        self._upsert("ask_artifact", artifact.id, _serialize(artifact))

    def save_feishu_binding(self, binding: FeishuBindingRecord) -> None:
        self._upsert("feishu_binding", binding.id, _serialize(binding))

    def delete_feishu_binding(self, binding_id: str) -> None:
        self._delete("feishu_binding", binding_id)

    @staticmethod
    def _build_run(payload: Dict[str, Any]) -> RunRecord:
        return RunRecord(
            id=payload["id"],
            organization_id=payload["organization_id"],
            workspace_id=payload["workspace_id"],
            title=payload["title"],
            goal=payload["goal"],
            requested_capability=payload["requested_capability"],
            status=RunStatus(payload["status"]),
            requested_by=payload["requested_by"],
            orchestrator_backend=payload["orchestrator_backend"],
            approval_request_id=payload.get("approval_request_id"),
            step_ids=payload.get("step_ids", []),
            created_at=payload.get("created_at", ""),
            updated_at=payload.get("updated_at", ""),
        )

    @staticmethod
    def _build_step(payload: Dict[str, Any]) -> StepRecord:
        return StepRecord(
            id=payload["id"],
            run_id=payload["run_id"],
            type=StepType(payload["type"]),
            name=payload["name"],
            status=StepStatus(payload["status"]),
            detail=payload.get("detail", {}),
        )

    @staticmethod
    def _build_approval(payload: Dict[str, Any]) -> ApprovalRecord:
        return ApprovalRecord(
            id=payload["id"],
            run_id=payload["run_id"],
            workspace_id=payload["workspace_id"],
            organization_id=payload["organization_id"],
            status=ApprovalStatus(payload["status"]),
            requested_by=payload["requested_by"],
            decided_by=payload.get("decided_by"),
            comment=payload.get("comment"),
            created_at=payload.get("created_at", ""),
            updated_at=payload.get("updated_at", ""),
        )

    @staticmethod
    def _build_delivery(payload: Dict[str, Any]) -> DeliveryJobRecord:
        return DeliveryJobRecord(
            id=payload["id"],
            organization_id=payload["organization_id"],
            workspace_id=payload["workspace_id"],
            channel=payload["channel"],
            event_type=payload["event_type"],
            payload=payload.get("payload", {}),
            targets=payload.get("targets", {}),
            status=DeliveryStatus(payload["status"]),
            attempts=payload.get("attempts", 0),
            last_error=payload.get("last_error"),
            created_at=payload.get("created_at", ""),
            updated_at=payload.get("updated_at", ""),
        )

    @staticmethod
    def _build_document(payload: Dict[str, Any]) -> KnowledgeDocumentRecord:
        return KnowledgeDocumentRecord(
            id=payload["id"],
            organization_id=payload["organization_id"],
            workspace_id=payload.get("workspace_id"),
            scope=payload["scope"],
            title=payload["title"],
            content=payload["content"],
            source_type=payload.get("source_type", "manual"),
        )

    @staticmethod
    def _build_memory_session(payload: Dict[str, Any]) -> MemorySessionRecord:
        return MemorySessionRecord(
            id=payload["id"],
            run_id=payload["run_id"],
            summary=payload.get("summary", ""),
            total_turns=payload.get("total_turns", 0),
            compressed_turn_ids=payload.get("compressed_turn_ids", []),
            recent_turn_ids=payload.get("recent_turn_ids", []),
            facts=[
                MemoryFactRecord(
                    key=item["key"],
                    value=item["value"],
                    source=item.get("source", "user"),
                )
                for item in payload.get("facts", [])
            ],
            created_at=payload.get("created_at", ""),
            updated_at=payload.get("updated_at", ""),
        )

    @staticmethod
    def _build_memory_turn(payload: Dict[str, Any]) -> MemoryTurnRecord:
        return MemoryTurnRecord(
            id=payload["id"],
            run_id=payload["run_id"],
            role=payload["role"],
            content=payload["content"],
            created_at=payload.get("created_at", ""),
        )

    @staticmethod
    def _build_ask_session(payload: Dict[str, Any]) -> AskSessionRecord:
        return AskSessionRecord(
            id=payload["id"],
            user_id=payload["user_id"],
            organization_id=payload["organization_id"],
            skill_id=payload["skill_id"],
            title=payload["title"],
            status=payload.get("status", "ACTIVE"),
            summary=payload.get("summary", ""),
            active_context=payload.get("active_context", {}),
            created_at=payload.get("created_at", ""),
            updated_at=payload.get("updated_at", ""),
        )

    @staticmethod
    def _build_ask_turn(payload: Dict[str, Any]) -> AskTurnRecord:
        return AskTurnRecord(
            id=payload["id"],
            session_id=payload["session_id"],
            role=payload["role"],
            input_type=payload["input_type"],
            content=payload["content"],
            outputs=payload.get("outputs", []),
            state_patch=payload.get("state_patch", {}),
            pending_commands=payload.get("pending_commands", []),
            created_at=payload.get("created_at", ""),
        )

    @staticmethod
    def _build_ask_artifact(payload: Dict[str, Any]) -> AskArtifactRecord:
        return AskArtifactRecord(
            id=payload["id"],
            session_id=payload["session_id"],
            artifact_type=payload["artifact_type"],
            title=payload["title"],
            payload=payload.get("payload", {}),
            created_at=payload.get("created_at", ""),
        )

    @staticmethod
    def _build_feishu_binding(payload: Dict[str, Any]) -> FeishuBindingRecord:
        return FeishuBindingRecord(
            id=payload["id"],
            user_id=payload["user_id"],
            organization_id=payload["organization_id"],
            status=payload.get("status", "UNBOUND"),
            identity_type=payload.get("identity_type", ""),
            user_open_id=payload.get("user_open_id", ""),
            user_name=payload.get("user_name", ""),
            config_dir=payload.get("config_dir", ""),
            verification_url=payload.get("verification_url", ""),
            device_code=payload.get("device_code", ""),
            granted_scopes=payload.get("granted_scopes", []),
            missing_scopes=payload.get("missing_scopes", []),
            hint=payload.get("hint", ""),
            expires_in=payload.get("expires_in"),
            checked_at=payload.get("checked_at", ""),
            created_at=payload.get("created_at", ""),
            updated_at=payload.get("updated_at", ""),
        )

    @staticmethod
    def _build_chunk(payload: Dict[str, Any]) -> KnowledgeChunkRecord:
        return KnowledgeChunkRecord(
            id=payload["id"],
            source_file_id=payload["source_file_id"],
            organization_id=payload["organization_id"],
            workspace_id=payload.get("workspace_id"),
            scope=payload["scope"],
            title=payload["title"],
            content=payload["content"],
            block_type=payload["block_type"],
            section_path=payload.get("section_path", []),
            page_number=payload.get("page_number"),
            sheet_name=payload.get("sheet_name"),
            slide_number=payload.get("slide_number"),
            chunk_index=payload["chunk_index"],
            token_count_estimate=payload["token_count_estimate"],
            metadata=payload.get("metadata", {}),
        )

    @staticmethod
    def _build_source_file(payload: Dict[str, Any]) -> KnowledgeSourceFile:
        return KnowledgeSourceFile(
            id=payload["id"],
            organization_id=payload["organization_id"],
            workspace_id=payload.get("workspace_id"),
            scope=payload["scope"],
            filename=payload["filename"],
            mime_type=payload["mime_type"],
            source_type=payload["source_type"],
            storage_path=payload["storage_path"],
            status=UploadStatus(payload["status"]),
            created_at=payload.get("created_at", _utcnow()),
            error_code=payload.get("error_code"),
            error_message=payload.get("error_message"),
        )


def resolve_database_url(database_url: str = None) -> str:
    if database_url:
        return database_url
    return os.getenv("EMATA_DATABASE_URL", "sqlite:///./emata.db")
