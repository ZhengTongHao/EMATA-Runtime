from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from app.ask_action_planner import AskActionPlanner
from app.ask_targeting import AskTargetResolver
from app.ask_tools import LarkCliError


SHANGHAI_TIMEZONE = timezone(timedelta(hours=8))


class AskActionDraftModule:
    CANCEL_MARKERS = ("取消", "算了", "不发了", "先不要", "不用了", "不约了")
    TIME_NUMERIC_CHARS = set("0123456789零〇一二两三四五六七八九十")
    MESSAGE_ACTION_MARKERS = (
        "发信息给",
        "发消息给",
        "发送信息给",
        "发送消息给",
        "发消息",
        "发信息",
        "发送消息",
        "发送信息",
        "发送",
        "发给",
        "发到",
        "发送到",
        "告诉",
        "通知",
    )
    MEETING_ACTION_MARKERS = (
        "开会",
        "会议",
        "日程",
        "约个会",
        "约会",
        "邀请",
    )
    NON_GENERIC_ACTION_MARKERS = (
        "一面",
        "二面",
        "面试安排",
        "候选人",
        "简历",
        "反馈汇总",
        "录用推进",
    )

    def __init__(
        self,
        *,
        target_resolver: Optional[AskTargetResolver] = None,
        action_planner: Optional[AskActionPlanner] = None,
        job_store: Any = None,
    ) -> None:
        self.target_resolver = target_resolver or AskTargetResolver()
        self.action_planner = action_planner or AskActionPlanner()
        self.job_store = job_store

    def handle_turn(
        self,
        *,
        session: Any,
        message: str,
        user: Any,
        tools: Dict[str, Any],
        route: str,
    ) -> Optional[Dict[str, Any]]:
        del route
        active_context = session.active_context or {}
        pending_draft = dict(active_context.get("pending_action_draft") or {})

        if pending_draft and active_context.get("active_skill_state") == "clarification_required":
            continuation = self._continue_pending_draft(
                pending_draft=pending_draft,
                active_context=active_context,
                message=message,
                user=user,
                tools=tools,
            )
            if continuation is not None:
                return continuation

        intent = self._detect_action_intent(message)
        if not intent:
            return None

        if intent == "calendar.schedule":
            draft = self._build_meeting_draft(message=message)
            if draft.get("missing_fields"):
                return self._build_clarification_result(intent=intent)

            direct_target = self._resolve_direct_target(draft.get("target_query", ""))
            if direct_target is not None:
                draft["resolved_target"] = direct_target
                return self._build_preview_result(draft=draft)

            exact_target = self.target_resolver.resolve_exact_candidate(
                query=draft["target_query"],
                user=user,
                tools=tools,
                preferred_kind="chat",
            )
            if exact_target:
                draft["resolved_target"] = exact_target
                return self._build_preview_result(draft=draft)

            candidates = self.target_resolver.resolve_candidates(
                query=draft["target_query"],
                user=user,
                tools=tools,
            )
            if len(candidates) == 1:
                draft["resolved_target"] = candidates[0]
                return self._build_preview_result(draft=draft)

            return self._build_target_selection_result(
                draft=draft,
                user=user,
                tools=tools,
            )

        draft = self._build_message_draft(message=message, active_context=active_context)
        if draft.get("missing_fields"):
            return self._build_clarification_result(intent=intent)

        direct_target = self._resolve_direct_target(draft.get("target_query", ""))
        if direct_target is not None:
            draft["resolved_target"] = direct_target
            return self._build_preview_result(draft=draft)

        return self._build_target_selection_result(
            draft=draft,
            user=user,
            tools=tools,
        )

    def handle_command(
        self,
        *,
        session: Any,
        command: str,
        payload: Dict[str, Any],
        user: Any,
        tools: Dict[str, Any],
    ) -> Optional[Dict[str, Any]]:
        active_context = session.active_context or {}
        pending_draft = dict(active_context.get("pending_action_draft") or {})
        if not pending_draft:
            return None

        if command == "select_option":
            kind = str((payload or {}).get("kind") or "").strip()
            if kind in {"user", "chat"}:
                pending_draft["resolved_target"] = payload
                return self._build_preview_result(draft=pending_draft)
            if kind == "other":
                return {
                    "outputs": [
                        {
                            "type": "card",
                            "text": "请直接在输入框里补充更完整的目标名称，我会继续帮你解析。",
                            "data": {"card_type": "clarification", "field": "target_query"},
                        }
                    ],
                    "state_patch": {
                        "active_skill_state": "clarification_required",
                        "pending_action_draft": pending_draft,
                        "pending_action_followup_field": "target_query",
                    },
                    "pending_commands": [],
                    "artifacts": [],
                }

        if command in {"approve_plan", "confirm"}:
            draft_updates = dict((payload or {}).get("draft_updates") or {})
            if draft_updates:
                pending_draft = self._apply_draft_updates(pending_draft, draft_updates)
            resolved_target = dict(pending_draft.get("resolved_target") or {})
            if not resolved_target and pending_draft.get("intent") == "message.send":
                return self._build_clarification_result(intent="message.send")

            execution_payload = self._build_execution_payload(draft=pending_draft)
            if self.job_store is None:
                result = self._execute_payload(
                    execution_payload=execution_payload,
                    tools=tools,
                    user=user,
                )
                return {
                    "outputs": [self._build_result_output(pending_draft, result)],
                    "state_patch": {
                        "pending_action_draft": {},
                        "active_skill_state": "completed",
                        "last_tool_result": result,
                        "pending_action_followup_field": "",
                    },
                    "pending_commands": [],
                    "artifacts": [],
                }

            job = self.job_store.enqueue(
                job_type=pending_draft.get("intent", "action"),
                summary=pending_draft.get("summary", "执行动作"),
                user_id=getattr(user, "id", ""),
                session_id=getattr(session, "id", ""),
                runner=lambda: [
                    self._build_result_output(
                        pending_draft,
                        self._execute_payload(
                            execution_payload=execution_payload,
                            tools=tools,
                            user=user,
                        ),
                    )
                ],
            )
            return {
                "outputs": [
                    {
                        "type": "message",
                        "text": "已接收后台执行请求，我会持续同步执行状态。",
                        "data": {
                            "job_id": job["id"],
                            "job_status": job["status"],
                            "job_type": job["job_type"],
                            "job_summary": job["summary"],
                        },
                    }
                ],
                "state_patch": {
                    "pending_action_draft": {},
                    "active_skill_state": "executing",
                    "pending_action_followup_field": "",
                    "last_job_id": job["id"],
                },
                "pending_commands": [],
                "artifacts": [],
            }

        if command == "cancel":
            return self._build_cancel_result()

        return None

    def _build_target_selection_result(
        self,
        *,
        draft: Dict[str, Any],
        user: Any,
        tools: Dict[str, Any],
    ) -> Dict[str, Any]:
        search_results = self.target_resolver.resolve_search_results(
            query=draft["target_query"],
            user=user,
            tools=tools,
        )
        options = [*search_results["contacts"], *search_results["chats"]][:3]
        card_text = "我找到了几个可能的目标，你选一个后我再生成预览。"
        if not options:
            query = draft["target_query"]
            if str(query).strip().endswith("群") or str(query).strip().endswith("群聊"):
                card_text = (
                    f"我暂时没有在飞书里找到“{query}”这个群。"
                    "你可以检查群名，或者点“其他”后重新输入更完整的群名，也可以直接提供 chat_id。"
                )
            else:
                card_text = (
                    f"我暂时没有在飞书里找到“{query}”这个联系人或会话。"
                    "你可以点“其他”后重新输入更完整的名称，或者直接提供对方的 open_id / 会话 ID。"
                )

        return {
            "outputs": [
                {
                    "type": "card",
                    "text": card_text,
                    "data": {
                        "card_type": "target_selection",
                        "options": [
                            *options,
                            {"kind": "other", "label": "其他", "value": "", "query": draft["target_query"]},
                            {"kind": "cancel", "label": "取消", "value": "", "query": draft["target_query"]},
                        ],
                        "search_results": search_results,
                    },
                }
            ],
            "state_patch": {
                "active_skill_state": "clarification_required",
                "pending_action_draft": draft,
                "pending_action_followup_field": "",
            },
            "pending_commands": [],
            "artifacts": [],
        }

    def _continue_pending_draft(
        self,
        *,
        pending_draft: Dict[str, Any],
        active_context: Dict[str, Any],
        message: str,
        user: Any,
        tools: Dict[str, Any],
    ) -> Optional[Dict[str, Any]]:
        content = (message or "").strip()
        if not content:
            return self._build_clarification_result(intent=pending_draft.get("intent", "message.send"))
        if content in self.CANCEL_MARKERS:
            return self._build_cancel_result()

        followup_field = str(active_context.get("pending_action_followup_field") or "").strip()
        updated_draft = dict(pending_draft)
        if followup_field == "target_query":
            updated_draft["target_query"] = content
            updated_draft["summary"] = self._build_summary(
                intent=updated_draft.get("intent", "message.send"),
                target_query=content,
                start=updated_draft.get("start", ""),
                end=updated_draft.get("end", ""),
            )
            actions = [dict(action) for action in updated_draft.get("actions", [])]
            if actions:
                actions[0]["summary"] = updated_draft["summary"]
            updated_draft["actions"] = actions
            updated_draft["resolved_target"] = {}

        updated_draft["missing_fields"] = [
            field for field in updated_draft.get("missing_fields", []) if field != followup_field
        ]
        if updated_draft.get("missing_fields"):
            return self._build_clarification_result(intent=updated_draft.get("intent", "message.send"))

        direct_target = self._resolve_direct_target(updated_draft.get("target_query", ""))
        if direct_target is not None:
            updated_draft["resolved_target"] = direct_target
            return self._build_preview_result(draft=updated_draft)

        candidates = self.target_resolver.resolve_candidates(
            query=updated_draft.get("target_query", ""),
            user=user,
            tools=tools,
        )
        if len(candidates) == 1:
            updated_draft["resolved_target"] = candidates[0]
            return self._build_preview_result(draft=updated_draft)

        return self._build_target_selection_result(
            draft=updated_draft,
            user=user,
            tools=tools,
        )

    def _build_message_draft(self, *, message: str, active_context: Dict[str, Any]) -> Dict[str, Any]:
        working_context = dict(active_context.get("working_context") or {})
        if not working_context:
            working_context = {
                "last_shareable_text": active_context.get("last_shareable_text", ""),
                "last_knowledge_answer_text": active_context.get("last_knowledge_answer_text", ""),
            }

        plan = self.action_planner.plan_message_action(
            message=message,
            working_context=working_context,
        )
        target_query = plan.get("target_query", "")
        body = plan.get("text", "")
        missing_fields: List[str] = []
        if not target_query:
            missing_fields.append("target_query")
        if not body:
            missing_fields.append("message_body")

        summary = str(plan.get("summary") or "").strip() or self._build_summary(
            intent="message.send",
            target_query=target_query,
            start="",
            end="",
        )
        return {
            "intent": plan.get("intent", "message.send"),
            "risk_level": plan.get("risk_level", "medium"),
            "target_query": target_query,
            "text": body,
            "summary": summary,
            "parse_mode": plan.get("parse_mode", "rule_fallback"),
            "confidence": plan.get("confidence", 0.0),
            "target_type_hint": plan.get("target_type_hint", ""),
            "editable_fields": plan.get("editable_fields", ["target", "text", "summary"]),
            "actions": [
                {
                    "capability": "message.send",
                    "summary": summary,
                    "text": body,
                }
            ],
            "missing_fields": missing_fields,
        }

    def _build_meeting_draft(self, *, message: str) -> Dict[str, Any]:
        target_query = self._extract_meeting_target_with_fallback(message)
        start, end = self._extract_meeting_window(message)
        missing_fields: List[str] = []
        if not target_query:
            missing_fields.append("target_query")
        if not start or not end:
            missing_fields.append("time_window")
        summary = self._build_summary(
            intent="calendar.schedule",
            target_query=target_query,
            start=start,
            end=end,
        )
        return {
            "intent": "calendar.schedule",
            "risk_level": "medium",
            "target_query": target_query,
            "start": start,
            "end": end,
            "summary": summary,
            "text": "",
            "editable_fields": ["target", "summary"],
            "actions": [
                {
                    "capability": "calendar.schedule",
                    "summary": summary,
                    "start": start,
                    "end": end,
                }
            ],
            "missing_fields": missing_fields,
        }

    def _extract_meeting_target_with_fallback(self, message: str) -> str:
        target_query = self._extract_meeting_target(message)
        if target_query:
            return target_query

        content = (message or "").strip()
        match = re.search(
            r"(?P<target>.+?)(?:(?:昨天|今天|明天|后天)?(?:上午|下午|中午|晚上)?[0123456789零〇一二两三四五六七八九十]+点(?:[0123456789零〇一二两三四五六七八九十]+分)?)(?:开会|开个会|会议)",
            content,
        )
        if not match:
            return ""
        return str(match.group("target") or "").strip('“”" ,，。；;！？!?')

    @classmethod
    def _build_summary(cls, *, intent: str, target_query: str, start: str, end: str) -> str:
        if intent == "calendar.schedule":
            label = cls._display_window(start, end)
            if target_query and label:
                return f"创建与 {target_query} 的会议（{label}）"
            if target_query:
                return f"创建与 {target_query} 的会议"
            return "创建会议"
        return f"发送消息给 {target_query}" if target_query else "发送消息"

    @staticmethod
    def _display_window(start: str, end: str) -> str:
        if not start or not end:
            return ""
        try:
            start_dt = datetime.fromisoformat(start)
            end_dt = datetime.fromisoformat(end)
            return f"{start_dt.strftime('%Y-%m-%d %H:%M')} - {end_dt.strftime('%H:%M')}"
        except ValueError:
            return ""

    @staticmethod
    def _extract_meeting_target(message: str) -> str:
        patterns = (
            r"在(?P<target>.+?)(?:开会|开个会|会议|群里开会)",
            r"和(?P<target>.+?)(?:开会|开个会|约个会|约会)",
            r"邀请(?P<target>.+?)(?:参加会议|开会)",
        )
        for pattern in patterns:
            match = re.search(pattern, message or "")
            if match:
                return str(match.group("target") or "").strip('“”" ，。；;！？!?')
        return ""

    @staticmethod
    def _extract_meeting_window(message: str) -> tuple[str, str]:
        content = message or ""
        now = datetime.now(SHANGHAI_TIMEZONE)
        day_offset = 0
        if "明天" in content:
            day_offset = 1
        elif "后天" in content:
            day_offset = 2

        point_index = content.find("点")
        if point_index < 0:
            return "", ""

        period = ""
        prefix = content[:point_index]
        if "下午" in prefix:
            period = "下午"
        elif "晚上" in prefix:
            period = "晚上"
        elif "中午" in prefix:
            period = "中午"
        elif "上午" in prefix:
            period = "上午"

        hour_token = AskActionDraftModule._extract_number_token_backward(content, point_index - 1)
        hour = AskActionDraftModule._parse_time_number(hour_token)
        if hour is None:
            return "", ""

        minute = 0
        minute_index = content.find("分", point_index + 1)
        if minute_index > point_index:
            minute_token = AskActionDraftModule._extract_number_token_forward(content, point_index + 1, minute_index)
            parsed_minute = AskActionDraftModule._parse_time_number(minute_token)
            if parsed_minute is not None:
                minute = parsed_minute
        if period in {"下午", "晚上"} and hour < 12:
            hour += 12
        if period == "中午" and hour < 11:
            hour += 12

        start_date = (now + timedelta(days=day_offset)).date()
        start_dt = datetime(
            start_date.year,
            start_date.month,
            start_date.day,
            hour,
            minute,
            tzinfo=SHANGHAI_TIMEZONE,
        )
        if day_offset == 0 and start_dt <= now:
            start_dt = start_dt + timedelta(days=1)
        end_dt = start_dt + timedelta(minutes=30)
        return start_dt.isoformat(), end_dt.isoformat()

    @classmethod
    def _extract_number_token_backward(cls, content: str, end_index: int) -> str:
        index = end_index
        while index >= 0 and content[index].isspace():
            index -= 1
        token_end = index + 1
        while index >= 0 and content[index] in cls.TIME_NUMERIC_CHARS:
            index -= 1
        return content[index + 1 : token_end]

    @classmethod
    def _extract_number_token_forward(cls, content: str, start_index: int, end_index: int) -> str:
        index = start_index
        while index < end_index and content[index].isspace():
            index += 1
        token_start = index
        while index < end_index and content[index] in cls.TIME_NUMERIC_CHARS:
            index += 1
        return content[token_start:index]

    @staticmethod
    def _parse_time_number(token: str) -> Optional[int]:
        normalized = str(token or "").strip()
        if not normalized:
            return None
        if normalized.isdigit():
            return int(normalized)

        digits = {
            "零": 0,
            "〇": 0,
            "一": 1,
            "二": 2,
            "两": 2,
            "三": 3,
            "四": 4,
            "五": 5,
            "六": 6,
            "七": 7,
            "八": 8,
            "九": 9,
        }
        if normalized == "十":
            return 10
        if "十" in normalized:
            head, _, tail = normalized.partition("十")
            tens = digits.get(head, 1) if head else 1
            ones = digits.get(tail, 0) if tail else 0
            return tens * 10 + ones
        if normalized in digits:
            return digits[normalized]
        return None

    @staticmethod
    def _build_preview_card(*, draft: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "type": "card",
            "text": "执行前请先确认这次动作预览。你可以继续编辑目标或正文。",
            "data": {
                "card_type": "action_preview",
                "editable": True,
                "draft": draft,
                "actions": draft.get("actions", []),
                "risk_level": draft.get("risk_level", "medium"),
            },
        }

    def _build_preview_result(self, *, draft: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "outputs": [self._build_preview_card(draft=draft)],
            "state_patch": {
                "pending_action_draft": draft,
                "last_confirmed_target": draft.get("resolved_target", {}),
                "active_skill_state": "waiting_confirmation",
                "pending_action_followup_field": "",
            },
            "pending_commands": [
                {"id": "approve-preview", "type": "approve_plan", "title": "确认执行", "payload": {}},
                {"id": "cancel-preview", "type": "cancel", "title": "取消", "payload": {}},
            ],
            "artifacts": [],
        }

    @staticmethod
    def _build_clarification_result(*, intent: str) -> Dict[str, Any]:
        text = (
            "我还缺少明确目标或时间。你可以直接说群名、人名和开会时间。"
            if intent == "calendar.schedule"
            else "我还缺少明确目标或可发送内容。你可以直接说人名、群名，或者补充要发的正文。"
        )
        return {
            "outputs": [
                {
                    "type": "card",
                    "text": text,
                    "data": {"card_type": "clarification"},
                }
            ],
            "state_patch": {"active_skill_state": "clarification_required"},
            "pending_commands": [],
            "artifacts": [],
        }

    @staticmethod
    def _build_cancel_result() -> Dict[str, Any]:
        return {
            "outputs": [
                {
                    "type": "message",
                    "text": "已取消这次待执行动作。",
                    "data": {"command": "cancel"},
                }
            ],
            "state_patch": {
                "pending_action_draft": {},
                "active_skill_state": "completed",
                "pending_action_followup_field": "",
            },
            "pending_commands": [],
            "artifacts": [],
        }

    @staticmethod
    def _apply_draft_updates(draft: Dict[str, Any], updates: Dict[str, Any]) -> Dict[str, Any]:
        merged = dict(draft)
        if "text" in updates:
            merged["text"] = str(updates.get("text") or "").strip()
        if "summary" in updates:
            merged["summary"] = str(updates.get("summary") or "").strip() or merged.get("summary", "")
        actions = [dict(action) for action in merged.get("actions", [])]
        if actions:
            if "text" in updates:
                actions[0]["text"] = merged.get("text", "")
            if "summary" in updates:
                actions[0]["summary"] = merged.get("summary", actions[0].get("summary", ""))
        merged["actions"] = actions
        return merged

    @staticmethod
    def _build_result_output(draft: Dict[str, Any], result: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "type": "tool_result",
            "text": f"{draft.get('summary', '执行动作')} {'已执行' if result.get('status') == 'success' else '未执行'}",
            "data": {"result": result},
        }

    @staticmethod
    def _execute_payload(*, execution_payload: Dict[str, Any], tools: Dict[str, Any], user: Any) -> Dict[str, Any]:
        try:
            return tools["lark_cli"].execute(execution_payload, user=user)
        except (LarkCliError, ValueError) as exc:
            return {
                "status": "failed",
                "summary": execution_payload.get("summary", "执行动作"),
                "result_link": "",
                "external_id": "",
                "error_code": getattr(exc, "code", "tool_execution_failed"),
                "error_message": str(exc),
            }

    @classmethod
    def _can_handle_turn(cls, message: str) -> bool:
        return bool(cls._detect_action_intent(message))

    @classmethod
    def _detect_action_intent(cls, message: str) -> str:
        content = (message or "").strip()
        if not content:
            return ""
        has_message_marker = any(marker in content for marker in cls.MESSAGE_ACTION_MARKERS) or bool(
            re.search(r"给.+?(?:发|发送)(?:消息|信息)?", content)
        )
        has_meeting_marker = any(marker in content for marker in cls.MEETING_ACTION_MARKERS) or bool(
            re.search(r"(?:约|开).{0,12}会", content)
        )
        if has_message_marker and has_meeting_marker:
            return ""
        if has_message_marker:
            return "message.send"
        if has_meeting_marker:
            return "calendar.schedule"
        if any(marker in content for marker in cls.NON_GENERIC_ACTION_MARKERS):
            return ""
        return ""

    @staticmethod
    def _build_execution_payload(*, draft: Dict[str, Any]) -> Dict[str, Any]:
        intent = draft.get("intent", "message.send")
        resolved_target = dict(draft.get("resolved_target") or {})
        if intent == "calendar.schedule":
            return {
                "capability": "calendar.schedule",
                "summary": draft.get("summary", "创建会议"),
                "start": draft.get("start", ""),
                "end": draft.get("end", ""),
            }
        return {
            "capability": "message.send",
            "summary": draft.get("summary", "发送消息"),
            "text": draft.get("text", ""),
            "target": {
                "type": resolved_target.get("kind", ""),
                "chat_id": resolved_target.get("value", "") if resolved_target.get("kind") == "chat" else "",
                "user_id": resolved_target.get("value", "") if resolved_target.get("kind") == "user" else "",
            },
        }

    @staticmethod
    def _resolve_direct_target(target_query: str) -> Optional[Dict[str, Any]]:
        normalized = str(target_query or "").strip()
        if not normalized:
            return None
        if re.fullmatch(r"ou_[A-Za-z0-9_]+", normalized):
            return {
                "kind": "user",
                "label": normalized,
                "value": normalized,
                "query": normalized,
            }
        if re.fullmatch(r"oc_[A-Za-z0-9_]+", normalized):
            return {
                "kind": "chat",
                "label": normalized,
                "value": normalized,
                "query": normalized,
            }
        return None
