from typing import Any, Dict, List, Optional

from app.ask_actions import AskActionDraftModule
from app.ask_context import AskContextManager
from app.integrations import tokenize_text


class AskIntentRouter:
    ACTION_MARKERS = (
        "安排",
        "发给",
        "发到",
        "发消息",
        "发信息",
        "发送",
        "通知",
        "创建",
        "约",
        "告诉",
        "开会",
        "会议",
        "日程",
        "约个会",
        "邀请",
    )
    KNOWLEDGE_MARKERS = (
        "多少",
        "是什么",
        "什么是",
        "怎么",
        "如何",
        "规则",
        "流程",
        "制度",
        "政策",
        "额度",
        "报销",
        "?",
        "？",
    )
    AMBIGUOUS_ACTION_MESSAGES = {
        "发给他",
        "发给她",
        "发给它",
        "发到群里",
        "通知一下",
    }

    def route(self, *, message: str, active_context: Dict[str, Any]) -> Dict[str, Any]:
        content = (message or "").strip()
        lowered = content.lower()
        if not content:
            return {"route": "clarification"}
        if any(marker in content or marker in lowered for marker in self.ACTION_MARKERS):
            if content in self.AMBIGUOUS_ACTION_MESSAGES:
                return {"route": "clarification"}
            if ("刚才" in content or "上一个" in content) and active_context.get("last_shareable_text"):
                return {"route": "answer_then_action"}
            return {"route": "action_only"}
        if any(marker in content or marker in lowered for marker in self.KNOWLEDGE_MARKERS):
            return {"route": "knowledge_qa"}
        return {"route": "skill_default"}


class AskPolicyEngine:
    def classify(self, plan: Dict[str, Any]) -> Dict[str, Any]:
        risk = plan.get("risk_level", "low")
        return {
            "risk_level": risk,
            "requires_confirmation": risk in {"medium", "high"},
        }


class AskKnowledgeQaModule:
    ACTION_MARKERS = (
        "安排",
        "发给",
        "发到",
        "发消息",
        "发信息",
        "发送",
        "创建",
        "生成文档",
        "帮我看简历",
        "面试反馈",
        "录用推进",
        "通知",
        "约",
        "开会",
        "会议",
        "日程",
        "约个会",
        "邀请",
    )
    QUESTION_MARKERS = (
        "多少",
        "是什么",
        "什么是",
        "什么",
        "怎么",
        "如何",
        "规则",
        "流程",
        "制度",
        "政策",
        "额度",
        "报销",
        "介绍",
        "说明",
        "?",
        "？",
    )
    ENTERPRISE_MARKERS = (
        "报销",
        "额度",
        "审批",
        "制度",
        "政策",
        "公司",
        "企业",
        "候选人",
        "面试",
        "录用",
        "入职",
        "财务",
        "hr",
        "erp",
        "crm",
        "飞书",
    )
    GENERIC_MATCH_TERMS = {
        "policy",
        "document",
        "guideline",
        "company",
        "shared",
        "approval",
        "approvals",
        "制度",
        "政策",
        "规则",
        "流程",
        "说明",
        "介绍",
        "公司",
        "企业",
    }

    def can_handle(self, *, session: Any, message: str, user: Any, tools: Dict[str, Any]) -> bool:
        del session, user, tools
        content = (message or "").strip()
        if not content:
            return False
        lowered = content.lower()
        if any(marker in content or marker in lowered for marker in self.ACTION_MARKERS):
            return False
        return any(marker in content or marker in lowered for marker in self.QUESTION_MARKERS)

    def handle_turn(self, *, session: Any, message: str, user: Any, tools: Dict[str, Any]) -> Dict[str, Any]:
        del session
        search_payload = tools["knowledge_search"].execute({"query": message, "limit": 8}, user=user)
        items = search_payload.get("items", [])
        trace = dict(search_payload.get("trace", {}))

        rerank_payload = tools["rerank"].execute(
            {
                "query": message,
                "items": items,
                "top_n": 5,
            },
            user=user,
        )
        trace["rerank_mode"] = rerank_payload.get("mode", "none")
        ranked_items = rerank_payload.get("items", [])
        grounded_items = self._select_grounded_items(message=message, items=ranked_items)[:5]

        if grounded_items:
            generation_result = tools["answer_generate"].execute(
                {
                    "mode": "grounded",
                    "question": message,
                    "contexts": [
                        {
                            "title": item.get("title", ""),
                            "snippet": item.get("snippet", ""),
                            "chunk_id": item.get("chunk_id", ""),
                        }
                        for item in grounded_items
                    ],
                },
                user=user,
            )
            answer_mode = generation_result.get("mode", "extractive_fallback")
            answer = generation_result.get("answer", "").strip()
            if not answer:
                answer = self._compose_extractive_answer(items=grounded_items)
            return self._build_grounded_response(
                message=message,
                answer=answer,
                answer_mode=answer_mode,
                items=grounded_items,
                trace=trace,
            )

        if self._should_use_general_llm(message):
            general_result = tools["answer_generate"].execute(
                {
                    "mode": "general",
                    "question": message,
                },
                user=user,
            )
            answer = general_result.get("answer", "").strip()
            if answer:
                return self._build_general_response(
                    message=message,
                    answer=answer,
                    answer_mode=general_result.get("mode", "general_llm"),
                    trace=trace,
                )

        return self._build_no_result_response(message=message, trace=trace)

    @classmethod
    def _should_use_general_llm(cls, message: str) -> bool:
        lowered = message.lower()
        return not any(marker in message or marker in lowered for marker in cls.ENTERPRISE_MARKERS)

    @classmethod
    def _select_grounded_items(cls, *, message: str, items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        selected: List[Dict[str, Any]] = []
        for index, item in enumerate(items):
            if cls._is_relevant_hit(message=message, item=item, index=index):
                selected.append(item)
        if selected:
            return selected
        # 没有足够证据时，宁可转 general/miss，也不要把泛命中强行当作 grounded 回答。
        return []

    @classmethod
    def _is_relevant_hit(cls, *, message: str, item: Dict[str, Any], index: int) -> bool:
        matched_terms = [str(term).lower() for term in item.get("matched_terms", []) if str(term).strip()]
        specific_terms = [term for term in matched_terms if term not in cls.GENERIC_MATCH_TERMS]
        if specific_terms:
            return True

        score = float(item.get("rerank_score", 0.0) or 0.0)
        if score >= 0.75:
            return True

        query_tokens = {
            token
            for token in tokenize_text(message)
            if len(token) >= 2 and token not in cls.GENERIC_MATCH_TERMS
        }
        haystack_tokens = {
            token
            for token in tokenize_text(f"{item.get('title', '')} {item.get('snippet', '')}")
            if len(token) >= 2 and token not in cls.GENERIC_MATCH_TERMS
        }
        overlap = query_tokens & haystack_tokens
        if overlap:
            return True

        # 当没有任何更强信号时，只接受排序第一且分数明显高于零的结果。
        return index == 0 and score >= 0.2 and bool(matched_terms)

    @staticmethod
    def _compose_extractive_answer(*, items: List[Dict[str, Any]]) -> str:
        top = items[0]
        title = top.get("title", "未命名文档")
        snippet = (top.get("snippet") or "").strip()
        return f"我先根据 {title} 给你一个检索摘要：{snippet}。当前先按证据摘要回答。"

    @staticmethod
    def _build_grounded_response(
        *,
        message: str,
        answer: str,
        answer_mode: str,
        items: List[Dict[str, Any]],
        trace: Dict[str, Any],
    ) -> Dict[str, Any]:
        citations = [
            {
                "type": "citation",
                "text": AskKnowledgeQaModule._format_citation(item),
                "data": {
                    "chunk_id": item.get("chunk_id", ""),
                    "title": item.get("title", ""),
                    "workspace_id": item.get("workspace_id"),
                },
            }
            for item in items
        ]
        confidence = "high" if items and (items[0].get("rerank_score", 0.0) or 0.0) >= 0.5 else "medium"
        return {
            "outputs": [
                {
                    "type": "message",
                    "text": answer,
                    "data": {
                        "answer_mode": "grounded_rag",
                        "mode": answer_mode,
                        "query": message,
                        "trace": trace,
                        "confidence": confidence,
                        "used_tools": ["knowledge_search", "rerank", "answer_generate"],
                    },
                },
                *citations,
            ],
            "state_patch": {
                "active_skill_state": "knowledge_qa",
                "conversation_memory": {
                    "last_knowledge_query": message,
                    "last_knowledge_hits": [item.get("chunk_id", "") for item in items],
                },
                "working_context": {
                    "last_knowledge_answer_mode": answer_mode,
                    "last_knowledge_answer_text": answer,
                    "last_shareable_text": answer,
                },
                "last_knowledge_query": message,
                "last_knowledge_hits": [item.get("chunk_id", "") for item in items],
                "last_knowledge_answer_mode": answer_mode,
                "last_knowledge_answer_text": answer,
                "last_shareable_text": answer,
            },
            "pending_commands": [],
            "artifacts": [
                {
                    "artifact_type": "knowledge_answer",
                    "title": "Knowledge QA",
                    "payload": {
                        "query": message,
                        "answer": answer,
                        "answer_mode": answer_mode,
                        "citations": [
                            {
                                "title": item.get("title", ""),
                                "chunk_id": item.get("chunk_id", ""),
                                "snippet": item.get("snippet", ""),
                            }
                            for item in items
                        ],
                    },
                }
            ],
        }

    @staticmethod
    def _build_general_response(
        *,
        message: str,
        answer: str,
        answer_mode: str,
        trace: Dict[str, Any],
    ) -> Dict[str, Any]:
        return {
            "outputs": [
                {
                    "type": "message",
                    "text": answer,
                    "data": {
                        "answer_mode": "general_llm",
                        "mode": answer_mode,
                        "query": message,
                        "trace": trace,
                        "confidence": "medium",
                        "used_tools": ["answer_generate"],
                    },
                }
            ],
            "state_patch": {
                "active_skill_state": "knowledge_qa",
                "conversation_memory": {
                    "last_knowledge_query": message,
                    "last_knowledge_hits": [],
                },
                "working_context": {
                    "last_knowledge_answer_mode": answer_mode,
                    "last_knowledge_answer_text": answer,
                    "last_shareable_text": answer,
                },
                "last_knowledge_query": message,
                "last_knowledge_hits": [],
                "last_knowledge_answer_mode": answer_mode,
                "last_knowledge_answer_text": answer,
                "last_shareable_text": answer,
            },
            "pending_commands": [],
            "artifacts": [
                {
                    "artifact_type": "knowledge_answer",
                    "title": "Knowledge QA",
                    "payload": {
                        "query": message,
                        "answer": answer,
                        "answer_mode": answer_mode,
                        "citations": [],
                    },
                }
            ],
        }

    @staticmethod
    def _build_no_result_response(*, message: str, trace: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "outputs": [
                {
                    "type": "message",
                    "text": "我没有在当前可访问知识库里找到足够证据来回答这个问题。你可以换个问法，或者先去知识库上传/确认相关文档。",
                    "data": {
                        "answer_mode": "knowledge_qa_miss",
                        "mode": "knowledge_qa_miss",
                        "query": message,
                        "trace": trace,
                        "confidence": "low",
                        "used_tools": ["knowledge_search", "rerank"],
                    },
                }
            ],
            "state_patch": {
                "active_skill_state": "knowledge_qa",
                "conversation_memory": {
                    "last_knowledge_query": message,
                    "last_knowledge_hits": [],
                },
                "working_context": {
                    "last_knowledge_answer_mode": "knowledge_qa_miss",
                },
                "last_knowledge_query": message,
                "last_knowledge_hits": [],
                "last_knowledge_answer_mode": "knowledge_qa_miss",
            },
            "pending_commands": [],
            "artifacts": [
                {
                    "artifact_type": "knowledge_answer",
                    "title": "Knowledge QA",
                    "payload": {
                        "query": message,
                        "answer": "",
                        "answer_mode": "knowledge_qa_miss",
                        "citations": [],
                    },
                }
            ],
        }

    @staticmethod
    def _format_citation(item: Dict[str, Any]) -> str:
        title = item.get("title", "未命名文档")
        snippet = (item.get("snippet") or "").strip()
        return f"{title}：{snippet}"


class AskRuntime:
    def __init__(
        self,
        *,
        skill_registry: Dict[str, Any],
        tool_registry: Dict[str, Any],
        policy_engine: AskPolicyEngine,
        intent_router: Optional[AskIntentRouter] = None,
        knowledge_module: Optional[AskKnowledgeQaModule] = None,
        action_module: Optional[AskActionDraftModule] = None,
        context_manager: Optional[AskContextManager] = None,
    ) -> None:
        self.skill_registry = skill_registry
        self.tool_registry = tool_registry
        self.policy_engine = policy_engine
        self.intent_router = intent_router or AskIntentRouter()
        self.knowledge_module = knowledge_module
        self.action_module = action_module
        self.context_manager = context_manager or AskContextManager()

    def run_turn(self, *, session: Any, message: str, user: Any) -> Dict[str, Any]:
        active_context = self.context_manager.flatten(
            self.context_manager.normalize(session.active_context or {})
        )
        if self.action_module and active_context.get("pending_action_draft"):
            action_result = self.action_module.handle_turn(
                session=session,
                message=message,
                user=user,
                tools=self.tool_registry,
                route="action_only",
            )
            if action_result is not None:
                return action_result

        route = self.intent_router.route(
            message=message,
            active_context=active_context,
        )
        if route["route"] == "knowledge_qa" and self.knowledge_module:
            return self.knowledge_module.handle_turn(
                session=session,
                message=message,
                user=user,
                tools=self.tool_registry,
            )
        if route["route"] in {"action_only", "answer_then_action"} and self.action_module:
            action_result = self.action_module.handle_turn(
                session=session,
                message=message,
                user=user,
                tools=self.tool_registry,
                route=route["route"],
            )
            if action_result is not None:
                return action_result
        if route["route"] == "clarification":
            return {
                "outputs": [
                    {
                        "type": "card",
                        "text": "我还缺少明确目标。你可以直接说人名、群名，或者稍后从候选列表里选。",
                        "data": {"card_type": "clarification", "route": "clarification"},
                    }
                ],
                "state_patch": {"active_skill_state": "clarification_required"},
                "pending_commands": [],
                "artifacts": [],
            }
        skill = self._resolve_skill(session.skill_id)
        if self._skill_can_handle(skill=skill, session=session, message=message):
            return skill.handle_turn(
                session=session,
                user=user,
                message=message,
                tools=self.tool_registry,
                policy_engine=self.policy_engine,
            )
        if route["route"] == "skill_default" and self.knowledge_module and self.knowledge_module.can_handle(
            session=session,
            message=message,
            user=user,
            tools=self.tool_registry,
        ):
            return self.knowledge_module.handle_turn(
                session=session,
                message=message,
                user=user,
                tools=self.tool_registry,
            )
        return skill.handle_turn(
            session=session,
            user=user,
            message=message,
            tools=self.tool_registry,
            policy_engine=self.policy_engine,
        )

    def run_command(self, *, session: Any, command: str, payload: Dict[str, Any], user: Any) -> Dict[str, Any]:
        if self.action_module:
            action_result = self.action_module.handle_command(
                session=session,
                command=command,
                payload=payload,
                user=user,
                tools=self.tool_registry,
            )
            if action_result is not None:
                return action_result
        skill = self._resolve_skill(session.skill_id)
        return skill.handle_command(
            session=session,
            user=user,
            command=command,
            payload=payload,
            tools=self.tool_registry,
            policy_engine=self.policy_engine,
        )

    def _resolve_skill(self, skill_id: str) -> Any:
        try:
            return self.skill_registry[skill_id]
        except KeyError as exc:
            raise ValueError(f"unsupported_skill:{skill_id}") from exc

    @staticmethod
    def _skill_can_handle(*, skill: Any, session: Any, message: str) -> bool:
        if hasattr(skill, "can_handle_turn"):
            return bool(skill.can_handle_turn(session=session, message=message))
        return True
