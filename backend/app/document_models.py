from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional


class UploadStatus(str, Enum):
    PENDING = "PENDING"
    PROCESSING = "PROCESSING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELED = "CANCELED"


@dataclass
class CanonicalBlock:
    block_type: str
    text: str
    section_path: List[str] = field(default_factory=list)
    page_number: Optional[int] = None
    sheet_name: Optional[str] = None
    slide_number: Optional[int] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class KnowledgeChunkRecord:
    id: str
    source_file_id: str
    organization_id: str
    workspace_id: Optional[str]
    scope: str
    title: str
    content: str
    block_type: str
    section_path: List[str]
    page_number: Optional[int]
    sheet_name: Optional[str]
    slide_number: Optional[int]
    chunk_index: int
    token_count_estimate: int
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class KnowledgeSourceFile:
    id: str
    organization_id: str
    workspace_id: Optional[str]
    scope: str
    filename: str
    mime_type: str
    source_type: str
    storage_path: str
    status: UploadStatus
    created_at: str = field(default_factory=lambda: datetime.utcnow().replace(microsecond=0).isoformat() + "Z")
    error_code: Optional[str] = None
    error_message: Optional[str] = None
