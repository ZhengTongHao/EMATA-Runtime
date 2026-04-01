from __future__ import annotations

from typing import Any, Dict, Optional


class AskMessageParseService:
    def __init__(self, *, generation_service: Optional[Any] = None) -> None:
        self.generation_service = generation_service

    def parse_message_action(self, *, message: str, working_context: Dict[str, Any]) -> Dict[str, Any]:
        if self.generation_service is None:
            return {}
        if getattr(self.generation_service, "mode", "disabled") != "openai-compatible":
            return {}
        try:
            payload = self.generation_service.generate_message_action_parse(
                message=message,
                working_context=working_context,
            )
        except Exception:
            return {}
        return payload if isinstance(payload, dict) else {}
