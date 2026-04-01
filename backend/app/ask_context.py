from __future__ import annotations

from copy import deepcopy
from typing import Any, Dict


class AskContextManager:
    SECTION_KEYS = ("conversation_memory", "working_context", "pending_action_draft")
    CONVERSATION_MEMORY_KEYS = {
        "last_knowledge_query",
        "last_knowledge_hits",
        "last_knowledge_answer_mode",
        "last_knowledge_answer_text",
        "recent_messages",
    }
    DEFAULT_CONTEXT = {
        "conversation_memory": {},
        "working_context": {},
        "pending_action_draft": {},
    }

    def normalize(self, value: Dict[str, Any] | None) -> Dict[str, Dict[str, Any]]:
        normalized = deepcopy(self.DEFAULT_CONTEXT)
        if not isinstance(value, dict):
            return normalized

        for section in self.SECTION_KEYS:
            incoming = value.get(section)
            if isinstance(incoming, dict):
                normalized[section].update(incoming)

        for key, incoming in value.items():
            if key in self.SECTION_KEYS:
                continue
            if key in self.CONVERSATION_MEMORY_KEYS:
                normalized["conversation_memory"][key] = incoming
            else:
                normalized["working_context"][key] = incoming
        return normalized

    def apply_patch(self, current: Dict[str, Any] | None, patch: Dict[str, Any] | None) -> Dict[str, Any]:
        merged = self.normalize(current)
        incoming = self.normalize(patch)

        merged["conversation_memory"].update(incoming["conversation_memory"])
        merged["working_context"].update(incoming["working_context"])
        if isinstance(patch, dict) and "pending_action_draft" in patch:
            merged["pending_action_draft"] = dict(incoming["pending_action_draft"])
        else:
            merged["pending_action_draft"].update(incoming["pending_action_draft"])

        return self.flatten(merged)

    def flatten(self, normalized: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
        conversation_memory = dict(normalized.get("conversation_memory", {}))
        working_context = dict(normalized.get("working_context", {}))
        pending_action_draft = dict(normalized.get("pending_action_draft", {}))

        flattened: Dict[str, Any] = {
            "conversation_memory": conversation_memory,
            "working_context": working_context,
            "pending_action_draft": pending_action_draft,
        }
        flattened.update(conversation_memory)
        flattened.update(working_context)
        flattened["pending_action_draft"] = pending_action_draft
        return flattened
