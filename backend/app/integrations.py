import hashlib
import json
import math
import os
import re
import socket
import subprocess
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

import httpx


def tokenize_text(text: str) -> List[str]:
    return re.findall(r"[A-Za-z0-9]+|[\u4e00-\u9fff]+", text.lower())


class QueryRewriteService:
    RULES = [
        (("erp", "订单", "财务系统"), ["enterprise resource planning", "order system"]),
        (("crm", "客户", "客户管理"), ["customer relationship management", "account management"]),
        (("approval", "审批", "审核"), ["authorize", "review"]),
        (("policy", "制度", "规范"), ["guideline", "policy document"]),
        (("reimbursement", "报销", "费用"), ["expense reimbursement", "expense policy"]),
        (("feishu", "飞书", "lark"), ["feishu", "lark"]),
        (("finance", "财务"), ["finance", "financial operations"]),
    ]

    def variants(self, query: str) -> List[str]:
        original = self._collapse_whitespace(query)
        if not original:
            return [""]
        lowered = original.lower()
        expanded_terms: List[str] = []
        for triggers, additions in self.RULES:
            if any(trigger in lowered or trigger in original for trigger in triggers):
                expanded_terms.extend(additions)
        rewritten = self._collapse_whitespace(" ".join([original, *expanded_terms]))
        variants = [original]
        if rewritten and rewritten != original:
            variants.append(rewritten)
        return variants

    @staticmethod
    def _collapse_whitespace(text: str) -> str:
        return " ".join(text.strip().split())


class EmbeddingProvider:
    def __init__(
        self,
        base_url: Optional[str] = None,
        api_key: Optional[str] = None,
        model: Optional[str] = None,
        vector_size: Optional[int] = None,
        timeout_seconds: float = 15.0,
    ) -> None:
        self.base_url = (base_url or os.getenv("EMATA_EMBEDDING_BASE_URL") or os.getenv("EMATA_MODEL_BASE_URL", "")).rstrip("/")
        self.api_key = api_key or os.getenv("EMATA_EMBEDDING_API_KEY") or os.getenv("EMATA_MODEL_API_KEY", "")
        self.model = model or os.getenv("EMATA_EMBEDDING_MODEL", "text-embedding-async-v1")
        self.vector_size = vector_size or int(os.getenv("EMATA_EMBEDDING_DIMENSION", "1024"))
        self.timeout_seconds = timeout_seconds
        self.mode = "deterministic"
        self.reason = "embedding_provider_fallback"

        if self._has_remote_config():
            self.mode = "openai-compatible"
            self.reason = "available"

    def embed_texts(self, texts: List[str]) -> List[List[float]]:
        cleaned = [text.strip() for text in texts]
        if self.mode == "openai-compatible":
            try:
                return self._embed_remote(cleaned)
            except Exception as exc:
                self.mode = "deterministic"
                self.reason = f"remote_request_failed:{exc.__class__.__name__}"
        return [self._embed_deterministic(text) for text in cleaned]

    def _embed_remote(self, texts: List[str]) -> List[List[float]]:
        response = httpx.post(
            f"{self.base_url}/embeddings",
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": self.model,
                "input": texts,
                "encoding_format": "float",
            },
            timeout=self.timeout_seconds,
        )
        response.raise_for_status()
        payload = response.json()
        items = sorted(payload.get("data", []), key=lambda item: item.get("index", 0))
        embeddings = [item["embedding"] for item in items]
        if len(embeddings) != len(texts):
            raise ValueError("embedding_count_mismatch")
        return embeddings

    def _embed_deterministic(self, text: str) -> List[float]:
        tokens = tokenize_text(text) or ["_empty_"]
        vector = [0.0] * self.vector_size
        for token in tokens:
            digest = hashlib.sha256(token.encode("utf-8")).digest()
            for offset in range(0, len(digest), 4):
                chunk = digest[offset : offset + 4]
                if len(chunk) < 4:
                    continue
                bucket = int.from_bytes(chunk[:2], "big") % self.vector_size
                sign = 1.0 if chunk[2] % 2 == 0 else -1.0
                weight = 1.0 + (chunk[3] / 255.0)
                vector[bucket] += sign * weight
        norm = math.sqrt(sum(value * value for value in vector)) or 1.0
        return [value / norm for value in vector]

    def _has_remote_config(self) -> bool:
        if not self.base_url or not self.api_key:
            return False
        return self.api_key.lower() not in {"replace-me", "your-api-key", "changeme"}


class TextGenerationProvider:
    def __init__(
        self,
        base_url: Optional[str] = None,
        api_key: Optional[str] = None,
        model: Optional[str] = None,
        timeout_seconds: float = 30.0,
    ) -> None:
        self.base_url = (
            base_url
            or os.getenv("EMATA_MODEL_BASE_URL")
            or self._fallback_base_url_from_embedding()
            or ""
        ).rstrip("/")
        self.api_key = (
            api_key
            or os.getenv("EMATA_MODEL_API_KEY")
            or self._fallback_api_key_from_embedding()
            or ""
        )
        self.model = model or os.getenv("EMATA_MODEL_NAME") or "qwen3.5-flash"
        self.timeout_seconds = timeout_seconds
        self.mode = "disabled"
        self.reason = "generation_provider_not_configured"

        if self._has_remote_config():
            self.mode = "openai-compatible"
            self.reason = "available"

    def generate_answer(self, *, question: str, contexts: List[Dict[str, Any]]) -> str:
        if self.mode != "openai-compatible":
            raise RuntimeError("generation_provider_unavailable")
        prompt = self._build_user_prompt(question=question, contexts=contexts)
        response = httpx.post(
            f"{self.base_url}/chat/completions",
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": self.model,
                "temperature": 0.2,
                "messages": [
                    {
                        "role": "system",
                        "content": (
                            "你是企业知识助手。"
                            "只能依据提供的知识片段回答。"
                            "如果证据不足，要明确说不知道或证据不足。"
                            "优先用中文回答，并在答案里自然引用来源编号。"
                        ),
                    },
                    {
                        "role": "user",
                        "content": prompt,
                    },
                ],
            },
            timeout=self.timeout_seconds,
        )
        response.raise_for_status()
        payload = response.json()
        content = self._extract_message_content(payload)
        if not content:
            raise ValueError("generation_response_empty")
        return content

    @staticmethod
    def _build_user_prompt(*, question: str, contexts: List[Dict[str, Any]]) -> str:
        rendered_contexts = []
        for index, item in enumerate(contexts, start=1):
            rendered_contexts.append(
                "\n".join(
                    [
                        f"[{index}] 标题：{item.get('title', '未命名文档')}",
                        f"[{index}] 内容：{item.get('snippet', '').strip()}",
                    ]
                )
            )
        joined_contexts = "\n\n".join(rendered_contexts)
        return (
            f"用户问题：{question}\n\n"
            "可用知识片段：\n"
            f"{joined_contexts}\n\n"
            "请先直接回答问题，再给出简短依据。不要编造知识片段中没有的信息。"
        )

    @staticmethod
    def _extract_message_content(payload: Dict[str, Any]) -> str:
        choices = payload.get("choices", [])
        if not choices:
            return ""
        message = choices[0].get("message", {})
        content = message.get("content", "")
        if isinstance(content, str):
            return content.strip()
        if isinstance(content, list):
            parts = []
            for item in content:
                if isinstance(item, dict) and item.get("type") == "text":
                    parts.append(str(item.get("text", "")))
            return "".join(parts).strip()
        return str(content).strip()

    @staticmethod
    def _fallback_base_url_from_embedding() -> str:
        return os.getenv("EMATA_EMBEDDING_BASE_URL", "")

    @staticmethod
    def _fallback_api_key_from_embedding() -> str:
        return os.getenv("EMATA_EMBEDDING_API_KEY", "")

    def _has_remote_config(self) -> bool:
        if not self.base_url or not self.api_key or not self.model:
            return False
        return self.api_key.lower() not in {"replace-me", "your-api-key", "changeme"}


class MilvusKnowledgeIndex:
    def __init__(
        self,
        uri: str,
        collection_name: str,
        embedding_provider: Optional[EmbeddingProvider] = None,
        query_rewriter: Optional[QueryRewriteService] = None,
        connect_timeout_seconds: float = 0.2,
    ) -> None:
        self.uri = uri
        self.collection_name = collection_name
        self.connect_timeout_seconds = connect_timeout_seconds
        self.embedding_provider = embedding_provider or EmbeddingProvider()
        self.query_rewriter = query_rewriter or QueryRewriteService()
        self.records: Dict[str, Dict[str, Any]] = {}
        self.mode = "fallback"
        self.reason = "fallback_search"
        self._client = None
        self._collection_ready = False

        try:
            if not self._can_reach_endpoint():
                self.reason = "endpoint_unreachable"
                return
            self._client = self._build_sdk_client()
            self.mode = "sdk"
            self.reason = "available"
            self._collection_ready = self._client.has_collection(self.collection_name)
            if self._collection_ready:
                self._client.load_collection(self.collection_name)
        except Exception as exc:
            self._client = None
            self.mode = "fallback"
            self.reason = f"sdk_init_failed:{exc.__class__.__name__}"

    def upsert(
        self,
        document_id: str,
        title: str,
        content: str,
        metadata: Dict[str, Any],
    ) -> None:
        self.upsert_chunk(
            chunk_id=document_id,
            title=title,
            content=content,
            metadata=metadata,
        )

    def upsert_chunk(
        self,
        chunk_id: str,
        title: str,
        content: str,
        metadata: Dict[str, Any],
    ) -> None:
        self.records[chunk_id] = {
            "document_id": chunk_id,
            "title": title,
            "content": content,
            "metadata": metadata,
        }
        if self.mode != "sdk" or not self._client:
            return

        embedding_input = f"{title}\n{content}"
        vector = self.embedding_provider.embed_texts([embedding_input])[0]
        self._ensure_collection(len(vector))
        self._client.upsert(
            self.collection_name,
            [
                {
                    "id": chunk_id,
                    "organization_id": str(metadata.get("organization_id", "")),
                    "workspace_id": str(metadata.get("workspace_id") or ""),
                    "scope": str(metadata.get("scope", "workspace")),
                    "title": self._truncate(title, 1024),
                    "content_preview": self._truncate(content, 4096),
                    "vector": vector,
                }
            ],
        )

    def delete_chunk(self, chunk_id: str) -> None:
        self.records.pop(chunk_id, None)
        if self.mode != "sdk" or not self._client or not self._collection_ready:
            return
        self._client.delete(self.collection_name, ids=[chunk_id])

    def search(
        self,
        query: str,
        organization_id: str,
        workspace_id: str,
        limit: int = 5,
        cancel_event: Optional[Any] = None,
    ) -> List[Dict[str, Any]]:
        return self.search_with_trace(
            query=query,
            organization_id=organization_id,
            workspace_id=workspace_id,
            limit=limit,
            cancel_event=cancel_event,
        )["items"]

    def search_with_trace(
        self,
        query: str,
        organization_id: str,
        workspace_id: str,
        limit: int = 5,
        cancel_event: Optional[Any] = None,
    ) -> Dict[str, Any]:
        self._raise_if_canceled(cancel_event)
        query_variants = self.query_rewriter.variants(query)
        backend_mode = "fallback"
        backend_reason = self.reason
        if self.mode == "sdk" and self._client:
            try:
                results = self._search_via_milvus(
                    query_variants=query_variants,
                    organization_id=organization_id,
                    workspace_id=workspace_id,
                    limit=limit,
                    cancel_event=cancel_event,
                )
                backend_mode = "sdk"
                backend_reason = self.reason
                return {
                    "items": results,
                    "trace": {
                        "backend_mode": backend_mode,
                        "backend_reason": backend_reason,
                        "query_variants": query_variants,
                        "result_count": len(results),
                        "rewrite_applied": len(query_variants) > 1,
                    },
                }
            except Exception as exc:
                backend_reason = f"sdk_search_failed:{exc.__class__.__name__}"
                self.reason = backend_reason
                if str(exc) == "search_canceled":
                    raise
        results = self._fallback_search(
            query_variants=query_variants,
            organization_id=organization_id,
            workspace_id=workspace_id,
            limit=limit,
            cancel_event=cancel_event,
        )
        return {
            "items": results,
            "trace": {
                "backend_mode": backend_mode,
                "backend_reason": backend_reason,
                "query_variants": query_variants,
                "result_count": len(results),
                "rewrite_applied": len(query_variants) > 1,
            },
        }

    def _search_via_milvus(
        self,
        query_variants: List[str],
        organization_id: str,
        workspace_id: str,
        limit: int,
        cancel_event: Optional[Any],
    ) -> List[Dict[str, Any]]:
        if not self._collection_ready and not self._client.has_collection(self.collection_name):
            return []

        merged: Dict[str, Dict[str, Any]] = {}
        search_limit = max(limit * 3, limit)
        filter_expression = self._build_filter_expression(
            organization_id=organization_id,
            workspace_id=workspace_id,
        )
        for variant in query_variants:
            self._raise_if_canceled(cancel_event)
            vector = self.embedding_provider.embed_texts([variant])[0]
            self._ensure_collection(len(vector))
            raw_hits = self._client.search(
                self.collection_name,
                data=[vector],
                limit=search_limit,
                filter=filter_expression,
                output_fields=[
                    "id",
                    "organization_id",
                    "workspace_id",
                    "scope",
                    "title",
                    "content_preview",
                ],
                search_params={"metric_type": "COSINE"},
            )
            for hit_group in raw_hits:
                self._raise_if_canceled(cancel_event)
                for hit in hit_group:
                    entity = hit.get("entity", {})
                    document_id = hit.get("id") or entity.get("id")
                    if not document_id:
                        continue
                    score = float(hit.get("distance", 0.0))
                    merge_key = self._dedupe_result_key(str(document_id))
                    current = merged.get(merge_key)
                    preferred_document_id = self._prefer_result_id(
                        current["document_id"] if current else None,
                        str(document_id),
                    )
                    if current and current["score"] >= score:
                        if current["document_id"] != preferred_document_id:
                            current["document_id"] = preferred_document_id
                            cached_record = self._lookup_record(preferred_document_id)
                            if cached_record:
                                current["title"] = cached_record["title"] or current["title"]
                                current["content"] = cached_record["content"] or current["content"]
                                current["metadata"] = {
                                    **cached_record["metadata"],
                                    **current["metadata"],
                                }
                        continue
                    cached_record = self._lookup_record(preferred_document_id)
                    merged_metadata = {
                        "organization_id": entity.get("organization_id", ""),
                        "workspace_id": entity.get("workspace_id") or None,
                        "scope": entity.get("scope", "workspace"),
                    }
                    if cached_record:
                        merged_metadata = {
                            **cached_record["metadata"],
                            **merged_metadata,
                        }
                    merged[merge_key] = {
                        "document_id": preferred_document_id,
                        "title": cached_record["title"] if cached_record else entity.get("title", ""),
                        "content": cached_record["content"] if cached_record else entity.get("content_preview", ""),
                        "metadata": merged_metadata,
                        "score": score,
                    }
        results = sorted(merged.values(), key=lambda item: item["score"], reverse=True)
        return results[:limit]

    def _fallback_search(
        self,
        query_variants: List[str],
        organization_id: str,
        workspace_id: str,
        limit: int,
        cancel_event: Optional[Any],
    ) -> List[Dict[str, Any]]:
        tokens = set()
        for variant in query_variants:
            self._raise_if_canceled(cancel_event)
            tokens.update(self._tokenize(variant))
        results: List[Dict[str, Any]] = []
        for record in self.records.values():
            self._raise_if_canceled(cancel_event)
            if record["metadata"].get("organization_id") != organization_id:
                continue
            scope = record["metadata"].get("scope", "workspace")
            record_workspace_id = record["metadata"].get("workspace_id")
            if scope == "workspace" and record_workspace_id != workspace_id:
                continue
            haystack_tokens = set(self._tokenize(f"{record['title']} {record['content']}"))
            overlap = len(tokens & haystack_tokens)
            if overlap == 0:
                continue
            results.append(
                {
                    "document_id": record["document_id"],
                    "title": record["title"],
                    "content": record["content"],
                    "metadata": record["metadata"],
                    "score": overlap,
                }
            )
        results.sort(key=lambda item: item["score"], reverse=True)
        return results[:limit]

    @staticmethod
    def _raise_if_canceled(cancel_event: Optional[Any]) -> None:
        if cancel_event and cancel_event.is_set():
            raise ValueError("search_canceled")

    @staticmethod
    def _tokenize(text: str) -> List[str]:
        return tokenize_text(text)

    def _build_sdk_client(self) -> Any:
        from pymilvus import MilvusClient  # type: ignore

        return MilvusClient(uri=self.uri)

    def _can_reach_endpoint(self) -> bool:
        parsed = urlparse(self.uri if "://" in self.uri else f"http://{self.uri}")
        host = parsed.hostname
        port = parsed.port or 19530
        if not host:
            return False
        try:
            with socket.create_connection((host, port), timeout=self.connect_timeout_seconds):
                return True
        except OSError:
            return False

    def _ensure_collection(self, vector_dimension: int) -> None:
        if not self._client:
            return
        if self._collection_ready:
            return

        from pymilvus import CollectionSchema, DataType, FieldSchema  # type: ignore

        if self._client.has_collection(self.collection_name):
            self._client.load_collection(self.collection_name)
            self._collection_ready = True
            return

        fields = [
            FieldSchema(name="id", dtype=DataType.VARCHAR, is_primary=True, max_length=128, auto_id=False),
            FieldSchema(name="organization_id", dtype=DataType.VARCHAR, max_length=128),
            FieldSchema(name="workspace_id", dtype=DataType.VARCHAR, max_length=128),
            FieldSchema(name="scope", dtype=DataType.VARCHAR, max_length=32),
            FieldSchema(name="title", dtype=DataType.VARCHAR, max_length=1024),
            FieldSchema(name="content_preview", dtype=DataType.VARCHAR, max_length=4096),
            FieldSchema(name="vector", dtype=DataType.FLOAT_VECTOR, dim=vector_dimension),
        ]
        schema = CollectionSchema(fields=fields)
        index_params = self._client.prepare_index_params()
        index_params.add_index(field_name="vector", metric_type="COSINE", index_type="AUTOINDEX")
        self._client.create_collection(
            collection_name=self.collection_name,
            schema=schema,
            index_params=index_params,
        )
        self._client.load_collection(self.collection_name)
        self._collection_ready = True

    @staticmethod
    def _build_filter_expression(organization_id: str, workspace_id: str) -> str:
        safe_org = MilvusKnowledgeIndex._escape_filter_value(organization_id)
        safe_workspace = MilvusKnowledgeIndex._escape_filter_value(workspace_id)
        return (
            f'organization_id == "{safe_org}" '
            f'and (scope == "shared" or workspace_id == "{safe_workspace}")'
        )

    @staticmethod
    def _escape_filter_value(value: str) -> str:
        return value.replace("\\", "\\\\").replace('"', '\\"')

    @staticmethod
    def _truncate(value: str, max_length: int) -> str:
        encoded = value.encode("utf-8")
        if len(encoded) <= max_length:
            return value

        left = 0
        right = len(value)
        best = ""
        while left <= right:
            middle = (left + right) // 2
            candidate = value[:middle]
            candidate_size = len(candidate.encode("utf-8"))
            if candidate_size <= max_length:
                best = candidate
                left = middle + 1
            else:
                right = middle - 1
        return best

    @staticmethod
    def _dedupe_result_key(document_id: str) -> str:
        match = re.match(r"^(?P<base>.+)-chunk-(?P<index>\d+)$", document_id)
        if match and match.group("index") == "0":
            return match.group("base")
        return document_id

    @staticmethod
    def _prefer_result_id(current_id: Optional[str], candidate_id: str) -> str:
        if current_id is None:
            return candidate_id
        if current_id.endswith("-chunk-0"):
            return current_id
        if candidate_id.endswith("-chunk-0"):
            return candidate_id
        return current_id

    def _lookup_record(self, document_id: str) -> Optional[Dict[str, Any]]:
        for candidate in self._record_candidates(document_id):
            record = self.records.get(candidate)
            if record is not None:
                return record
        return None

    @staticmethod
    def _record_candidates(document_id: str) -> List[str]:
        candidates = [document_id]
        match = re.match(r"^(?P<base>.+)-chunk-(?P<index>\d+)$", document_id)
        if match:
            candidates.append(match.group("base"))
        else:
            candidates.append(f"{document_id}-chunk-0")
        return candidates


class TemporalRuntime:
    def __init__(self, target_hostport: str, namespace: str) -> None:
        self.target_hostport = target_hostport
        self.namespace = namespace
        self.workflow_name = "emata_run_workflow"
        self.task_queue = "emata-runs"
        self.mode = "fallback"
        self.reason = "temporalio_not_installed"
        self._client_cls = None

        try:
            from temporalio.client import Client  # type: ignore

            self._client_cls = Client
            self.mode = "sdk"
            self.reason = "available"
        except Exception:
            self._client_cls = None

    def describe(self) -> Dict[str, str]:
        return {
            "mode": self.mode,
            "target_hostport": self.target_hostport,
            "namespace": self.namespace,
            "workflow_name": self.workflow_name,
            "task_queue": self.task_queue,
            "reason": self.reason,
        }

    async def start_run_workflow(self, workflow_id: str, payload: Dict[str, Any]) -> Dict[str, str]:
        if not self._client_cls:
            raise RuntimeError("temporalio_not_installed")

        from app.temporal_workflow import EMATARunWorkflow

        client = await self._client_cls.connect(self.target_hostport, namespace=self.namespace)
        await client.start_workflow(
            EMATARunWorkflow.run,
            payload,
            id=workflow_id,
            task_queue=self.task_queue,
        )
        return {"workflow_id": workflow_id, "status": "started"}

    async def signal_run_workflow(
        self,
        workflow_id: str,
        signal_name: str,
        payload: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, str]:
        if not self._client_cls:
            raise RuntimeError("temporalio_not_installed")

        client = await self._client_cls.connect(self.target_hostport, namespace=self.namespace)
        handle = client.get_workflow_handle(workflow_id)
        if payload:
            await handle.signal(signal_name, payload)
        else:
            await handle.signal(signal_name)
        return {"workflow_id": workflow_id, "signal_name": signal_name, "status": "sent"}


class FeishuMcpClient:
    def __init__(
        self,
        executable: str = "npx",
        package: str = "@larksuiteoapi/lark-mcp",
        transport: str = "stdio",
        app_id: Optional[str] = None,
        app_secret: Optional[str] = None,
        tool_name: str = "im.v1.message.create",
    ) -> None:
        self.executable = executable
        self.package = package
        self.transport = transport
        self.app_id = app_id or os.getenv("EMATA_FEISHU_APP_ID", "")
        self.app_secret = app_secret or os.getenv("EMATA_FEISHU_APP_SECRET", "")
        self.tool_name = tool_name

    def build_command(self) -> List[str]:
        command = [
            self.executable,
            "-y",
            self.package,
            "mcp",
        ]
        if self.app_id:
            command.extend(["-a", self.app_id])
        if self.app_secret:
            command.extend(["-s", self.app_secret])
        command.extend([
            "-t",
            self.tool_name,
            "--transport",
            self.transport,
        ])
        return command

    def deliver(self, event_type: str, payload: Dict[str, Any], targets: Dict[str, List[str]]) -> Dict[str, Any]:
        command = self.build_command()
        if os.getenv("EMATA_FEISHU_MCP_ENABLED", "false").lower() != "true":
            return {
                "status": "SKIPPED",
                "reason": "feishu_mcp_disabled",
                "command": command,
                "event_type": event_type,
            }
        if not self.app_id or not self.app_secret:
            return {
                "status": "FAILED",
                "reason": "missing_feishu_app_credentials",
                "command": command,
                "event_type": event_type,
            }

        request_body = {
            "event_type": event_type,
            "payload": payload,
            "targets": targets,
        }
        process = subprocess.run(
            command,
            input=json.dumps(request_body, ensure_ascii=False),
            text=True,
            capture_output=True,
            check=False,
        )
        return {
            "status": "SENT" if process.returncode == 0 else "FAILED",
            "reason": process.stderr.strip() if process.returncode != 0 else "ok",
            "stdout": process.stdout.strip(),
            "command": command,
        }
