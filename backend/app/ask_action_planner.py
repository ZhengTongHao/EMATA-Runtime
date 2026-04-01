from __future__ import annotations

import re
from typing import Any, Dict, Optional


class AskActionPlanner:
    def __init__(self, *, parse_service: Optional[Any] = None) -> None:
        self.parse_service = parse_service

    def plan_message_action(self, *, message: str, working_context: Dict[str, Any]) -> Dict[str, Any]:
        shareable_text = str(
            working_context.get("last_shareable_text")
            or working_context.get("last_knowledge_answer_text")
            or ""
        ).strip()

        structured = self._parse_with_llm(message=message, working_context=working_context)
        if self._is_usable_parse(structured):
            target_query = str(structured.get("target_query") or "").strip()
            text = str(structured.get("text") or "").strip()
            summary = str(structured.get("summary") or "").strip() or self._build_summary(target_query)
            return {
                "intent": "message.send",
                "risk_level": "medium",
                "requires_preview": True,
                "target_query": target_query,
                "text": text,
                "summary": summary,
                "editable_fields": ["target", "text", "summary"],
                "parse_mode": str(structured.get("parse_mode") or "llm"),
                "confidence": float(structured.get("confidence") or 0.0),
                "target_type_hint": str(structured.get("target_type_hint") or "").strip(),
            }

        target_query, text = self._extract_rule_fields(message=message, shareable_text=shareable_text)
        return {
            "intent": "message.send",
            "risk_level": "medium",
            "requires_preview": True,
            "target_query": target_query,
            "text": text,
            "summary": self._build_summary(target_query),
            "editable_fields": ["target", "text", "summary"],
            "parse_mode": "rule_fallback",
            "confidence": 0.0,
            "target_type_hint": "",
        }

    def _parse_with_llm(self, *, message: str, working_context: Dict[str, Any]) -> Dict[str, Any]:
        if self.parse_service is None:
            return {}
        try:
            payload = self.parse_service.parse_message_action(
                message=message,
                working_context=working_context,
            )
        except Exception:
            return {}
        return payload if isinstance(payload, dict) else {}

    @staticmethod
    def _is_usable_parse(payload: Dict[str, Any]) -> bool:
        if not payload:
            return False
        if str(payload.get("intent") or "").strip() not in {"", "message.send"}:
            return False
        return bool(str(payload.get("target_query") or "").strip() and str(payload.get("text") or "").strip())

    def _extract_rule_fields(self, *, message: str, shareable_text: str) -> tuple[str, str]:
        normalized = self._collapse_whitespace(message)
        for pattern in self._paired_patterns():
            match = re.search(pattern, normalized)
            if match:
                return (
                    self._clean_target(match.group("target")),
                    self._clean_body(match.group("body"), shareable_text=shareable_text),
                )

        target_query = self._extract_target(normalized)
        text = self._extract_message_body(normalized, shareable_text=shareable_text)
        return target_query, text

    @staticmethod
    def _paired_patterns() -> tuple[str, ...]:
        return (
            r'(?:给|向)[“"](?P<target>.+?)[”"](?:发送|发)(?:送)?(?:消息|信息)?[“"](?P<body>.+?)[”"]',
            r'(?:给|向)(?P<target>.+?)(?:发送|发)(?:送)?(?:消息|信息)?[“"](?P<body>.+?)[”"]',
            r'把[“"](?P<body>.+?)[”"](?:发送)?(?:消息|信息)?(?:发|发送)(?:到|给)(?P<target>.+?)(?:[，。；;！？!?]|$)',
            r'(?:告诉|通知)(?P<target>[^，。；;：: ]+)(?P<body>.+)$',
        )

    @staticmethod
    def _collapse_whitespace(text: str) -> str:
        return " ".join((text or "").strip().split())

    @staticmethod
    def _build_summary(target_query: str) -> str:
        return f"发送消息给 {target_query}" if target_query else "发送消息"

    @staticmethod
    def _clean_target(value: str) -> str:
        return str(value or "").strip('“”" ，。；;！？!?')

    @classmethod
    def _clean_body(cls, value: str, *, shareable_text: str) -> str:
        body = str(value or "").strip('“”" ，。；;！？!?')
        if body in {"刚才的结论", "刚才的内容", "刚才的摘要"}:
            return shareable_text
        return body

    @staticmethod
    def _extract_target(message: str) -> str:
        patterns = (
            r'(?:发信息给|发消息给|发送信息给|发送消息给|发给|告诉|通知)(?P<target>.+?)(?:[“"，。；;！？!?]|$)',
            r'(?:发到|发送到)(?P<target>.+?)(?:[“"，。；;！？!?]|$)',
            r'给(?P<target>.+?)(?:发|发送)(?:消息|信息)?',
            r'把.+?发到(?P<target>.+?)(?:[“"，。；;！？!?]|$)',
        )
        for pattern in patterns:
            match = re.search(pattern, message or "")
            if match:
                return AskActionPlanner._clean_target(match.group("target"))
        return ""

    @staticmethod
    def _extract_message_body(message: str, *, shareable_text: str) -> str:
        if any(marker in message for marker in ("刚才的结论", "刚才的内容", "刚才的摘要")):
            return shareable_text

        quoted_segments = re.findall(r'[“"](?P<body>.+?)[”"]', message or "")
        if quoted_segments:
            return AskActionPlanner._clean_body(quoted_segments[-1], shareable_text=shareable_text)

        tell_match = re.search(r'(?:告诉|通知)(?:他们|你们|他|她|TA|ta)?(?P<body>.+)$', message or "")
        if tell_match:
            return AskActionPlanner._clean_body(tell_match.group("body"), shareable_text=shareable_text)
        return ""
