import json
import os
import re
from typing import Any, Dict, List, Optional

import httpx

from app.integrations import tokenize_text


class RerankProvider:
    def __init__(
        self,
        *,
        base_url: Optional[str] = None,
        api_key: Optional[str] = None,
        model: Optional[str] = None,
        timeout_seconds: float = 20.0,
    ) -> None:
        self.base_url = (
            base_url
            or os.getenv("EMATA_RERANK_BASE_URL")
            or "https://dashscope.aliyuncs.com/compatible-api/v1"
        ).rstrip("/")
        self.api_key = (
            api_key
            or os.getenv("EMATA_RERANK_API_KEY")
            or os.getenv("EMATA_MODEL_API_KEY")
            or os.getenv("EMATA_EMBEDDING_API_KEY")
            or ""
        )
        self.model = model or os.getenv("EMATA_RERANK_MODEL") or "qwen3-rerank"
        self.timeout_seconds = timeout_seconds
        self.mode = "disabled"
        self.reason = "rerank_provider_not_configured"

        if self._has_remote_config():
            self.mode = "openai-compatible"
            self.reason = "available"

    def rerank(self, *, query: str, documents: List[str], top_n: Optional[int] = None) -> List[Dict[str, Any]]:
        if not documents:
            return []
        if self.mode != "openai-compatible":
            return self._fallback_rerank(query=query, documents=documents, top_n=top_n)

        response = httpx.post(
            f"{self.base_url}/reranks",
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": self.model,
                "query": query,
                "documents": documents,
                "top_n": top_n or len(documents),
            },
            timeout=self.timeout_seconds,
        )
        response.raise_for_status()
        payload = response.json()
        results = payload.get("output", {}).get("results", [])
        return [
            {
                "index": int(item.get("index", 0)),
                "score": float(item.get("relevance_score", 0.0)),
            }
            for item in results
        ]

    @staticmethod
    def _fallback_rerank(*, query: str, documents: List[str], top_n: Optional[int] = None) -> List[Dict[str, Any]]:
        query_tokens = set(tokenize_text(query))
        ranked = []
        for index, document in enumerate(documents):
            document_tokens = set(tokenize_text(document))
            overlap = len(query_tokens & document_tokens)
            ranked.append({"index": index, "score": float(overlap)})
        ranked.sort(key=lambda item: item["score"], reverse=True)
        return ranked[: (top_n or len(ranked))]

    def _has_remote_config(self) -> bool:
        if not self.base_url or not self.api_key or not self.model:
            return False
        return self.api_key.lower() not in {"replace-me", "your-api-key", "changeme"}


class AnswerGenerationService:
    def __init__(
        self,
        *,
        base_url: Optional[str] = None,
        api_key: Optional[str] = None,
        model: Optional[str] = None,
        timeout_seconds: float = 30.0,
    ) -> None:
        self.base_url = (
            base_url
            or os.getenv("EMATA_MODEL_BASE_URL")
            or os.getenv("EMATA_EMBEDDING_BASE_URL")
            or ""
        ).rstrip("/")
        self.api_key = (
            api_key
            or os.getenv("EMATA_MODEL_API_KEY")
            or os.getenv("EMATA_EMBEDDING_API_KEY")
            or ""
        )
        self.model = model or os.getenv("EMATA_MODEL_NAME") or "qwen3.5-flash"
        self.timeout_seconds = timeout_seconds
        self.mode = "disabled"
        self.reason = "generation_provider_not_configured"

        if self._has_remote_config():
            self.mode = "openai-compatible"
            self.reason = "available"

    def generate_grounded_answer(self, *, question: str, contexts: List[Dict[str, Any]]) -> str:
        if self.mode != "openai-compatible":
            raise RuntimeError("generation_provider_unavailable")
        prompt = self._build_grounded_prompt(question=question, contexts=contexts)
        return self._complete(
            system_prompt=(
                "You are an enterprise knowledge assistant. "
                "Answer only from the provided evidence. "
                "If the evidence is insufficient, say so clearly. "
                "Answer in Chinese when the user asks in Chinese, and naturally reference citation numbers like [1], [2]."
            ),
            user_prompt=prompt,
        )

    def generate_general_answer(self, *, question: str) -> str:
        if self.mode != "openai-compatible":
            raise RuntimeError("generation_provider_unavailable")
        return self._complete(
            system_prompt=(
                "You are a helpful assistant. "
                "Answer in Chinese when the user asks in Chinese. "
                "If you are unsure, say so clearly instead of making up details."
            ),
            user_prompt=(
                f"User question: {question}\n\n"
                "Provide a direct, concise answer. "
                "Do not pretend this answer comes from a private enterprise knowledge base."
            ),
        )

    def generate_message_action_parse(self, *, message: str, working_context: Dict[str, Any]) -> Dict[str, Any]:
        if self.mode != "openai-compatible":
            raise RuntimeError("generation_provider_unavailable")
        shareable_text = str(
            working_context.get("last_shareable_text")
            or working_context.get("last_knowledge_answer_text")
            or ""
        ).strip()
        raw = self._complete(
            system_prompt=(
                "You extract structured message-sending intents from Chinese user requests. "
                "Return JSON only. "
                "Do not include markdown fences or explanations. "
                "Use this schema: "
                "{\"intent\":\"message.send\",\"target_query\":\"...\",\"target_type_hint\":\"user|chat|unknown\","
                "\"text\":\"...\",\"summary\":\"...\",\"confidence\":0.0}."
            ),
            user_prompt=(
                f"User message: {message}\n"
                f"Reusable previous answer text: {shareable_text}\n\n"
                "Rules:\n"
                "1. target_query is the person or group name the user wants to send to.\n"
                "2. text is the message body to be sent.\n"
                "3. If the user refers to \"刚才的结论/内容/摘要\", reuse the previous answer text.\n"
                "4. target_type_hint should be chat for group-like targets and user for person-like targets.\n"
                "5. summary should be a short Chinese summary of the send action.\n"
                "6. confidence should be between 0 and 1.\n"
            ),
        )
        return self._extract_message_parse_payload(raw)

    def _complete(self, *, system_prompt: str, user_prompt: str) -> str:
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
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
            },
            timeout=self.timeout_seconds,
        )
        response.raise_for_status()
        payload = response.json()
        choices = payload.get("choices", [])
        if not choices:
            raise ValueError("generation_response_empty")
        message = choices[0].get("message", {})
        content = message.get("content", "")
        if isinstance(content, str):
            text = content.strip()
        elif isinstance(content, list):
            text = "".join(
                str(item.get("text", ""))
                for item in content
                if isinstance(item, dict) and item.get("type") == "text"
            ).strip()
        else:
            text = str(content).strip()
        if not text:
            raise ValueError("generation_response_empty")
        return text

    @staticmethod
    def _build_grounded_prompt(*, question: str, contexts: List[Dict[str, Any]]) -> str:
        rendered_contexts = []
        for index, item in enumerate(contexts, start=1):
            rendered_contexts.append(
                "\n".join(
                    [
                        f"[{index}] Title: {item.get('title', 'Untitled document')}",
                        f"[{index}] Content: {item.get('snippet', '').strip()}",
                    ]
                )
            )
        joined_contexts = "\n\n".join(rendered_contexts)
        return (
            f"User question: {question}\n\n"
            "Available evidence:\n"
            f"{joined_contexts}\n\n"
            "Answer the question first, then give a brief supporting explanation. "
            "Do not invent facts that are not supported by the evidence."
        )

    @staticmethod
    def _extract_message_parse_payload(raw: str) -> Dict[str, Any]:
        text = (raw or "").strip()
        if not text:
            raise ValueError("message_parse_empty")
        try:
            payload = json.loads(text)
        except json.JSONDecodeError:
            match = re.search(r"\{.*\}", text, re.DOTALL)
            if not match:
                raise ValueError("message_parse_invalid_json") from None
            payload = json.loads(match.group(0))
        if not isinstance(payload, dict):
            raise ValueError("message_parse_not_object")
        confidence = payload.get("confidence", 0.0)
        try:
            confidence_value = float(confidence)
        except (TypeError, ValueError):
            confidence_value = 0.0
        return {
            "intent": str(payload.get("intent") or "message.send").strip() or "message.send",
            "target_query": str(payload.get("target_query") or "").strip(),
            "target_type_hint": str(payload.get("target_type_hint") or "unknown").strip() or "unknown",
            "text": str(payload.get("text") or "").strip(),
            "summary": str(payload.get("summary") or "").strip(),
            "confidence": max(0.0, min(1.0, confidence_value)),
            "parse_mode": "llm",
        }

    def _has_remote_config(self) -> bool:
        if not self.base_url or not self.api_key or not self.model:
            return False
        return self.api_key.lower() not in {"replace-me", "your-api-key", "changeme"}
