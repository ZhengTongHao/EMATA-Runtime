import os
import json
import re
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from app.ask_tools import LarkCliError


DEFAULT_INTERNAL_CHAT_QUERY = os.getenv(
    "EMATA_DEFAULT_INTERNAL_CHAT_QUERY",
    os.getenv("EMATA_HR_INTERNAL_CHAT_QUERY", "技术面试群"),
)
SHANGHAI_TIMEZONE = timezone(timedelta(hours=8))


class HRRecruitingSkill:
    def can_handle_turn(self, *, session: Any, message: str) -> bool:
        content = (message or "").strip()
        active_context = session.active_context or {}
        candidate_name = self._detect_candidate_name(content, active_context)

        return any(
            (
                self._is_feedback_summary_request(content),
                self._is_collaboration_execution_request(content),
                self._is_interview_schedule_request(content),
                self._needs_position_before_resume_analysis(content, active_context),
                bool(active_context.get("position_required") and content),
                bool(candidate_name and active_context.get("active_position")),
            )
        )

    def handle_turn(
        self,
        *,
        session: Any,
        user: Any,
        message: str,
        tools: Dict[str, Any],
        policy_engine: Any,
    ) -> Dict[str, Any]:
        del policy_engine
        content = (message or "").strip()
        active_context = session.active_context or {}
        candidate_name = self._detect_candidate_name(content, active_context)

        if self._is_feedback_summary_request(content):
            return self._handle_feedback_summary(
                user=user,
                content=content,
                active_context=active_context,
                tools=tools,
            )

        if self._is_collaboration_execution_request(content):
            plan = self._build_collaboration_plan(content, active_context=active_context)
            if plan.get("missing_fields"):
                return {
                    "outputs": [
                        {
                            "type": "card",
                            "text": "我识别到你想建会并发送消息，但当前还缺少可发送的具体内容。你可以直接写出要发送的话，或者引用刚才的结论/提纲。",
                            "data": {
                                "card_type": "clarification",
                                "missing_fields": plan.get("missing_fields", []),
                            },
                        }
                    ],
                    "state_patch": {
                        "active_skill_state": "clarification_required",
                    },
                    "pending_commands": [],
                    "artifacts": [],
                }
            return {
                "outputs": [
                    {
                        "type": "card",
                        "text": "我已经拆成“建会议 + 发消息”两个动作。因为涉及内部协同，先给你统一确认卡。",
                        "data": {
                            "card_type": "confirmation_request",
                            "risk_level": "high",
                            "actions": plan["actions"],
                        },
                    }
                ],
                "state_patch": {
                    "active_skill_state": "waiting_confirmation",
                    "pending_action_plan": plan,
                },
                "pending_commands": [
                    {"id": "confirm-plan", "type": "confirm", "title": "确认执行", "payload": {}},
                    {"id": "cancel-plan", "type": "cancel", "title": "取消", "payload": {}},
                ],
                "artifacts": [],
            }

        if self._is_interview_schedule_request(content) and not self._contains_explicit_time(content):
            binding = tools["lark_cli"].binding_service.get_status(user)
            interview_target = self._extract_interview_target_name(content)
            if binding["status"] != "ACTIVE":
                return self._build_binding_required_result(
                    "安排面试前需要先绑定飞书，这样我才能读取日历忙闲并给你推荐 2-3 个真实可用时间。",
                    binding,
                    state_patch={
                        "active_skill_state": "interview_coordination",
                        "pending_interview_target": {"name": interview_target} if interview_target else {},
                    },
                )
            suggestions = tools["lark_cli"].execute(
                {
                    "capability": "calendar.suggest_slots",
                    "summary": "为面试生成建议时间",
                    "duration_minutes": 30,
                },
                user=user,
            )
            slots = suggestions.get("options", [])[:3]
            return {
                "outputs": [
                    {
                        "type": "card",
                        "text": "我先给你 3 个可选时间，你选一个我再继续安排面试和内部通知。",
                        "data": {
                            "card_type": "time_suggestions",
                            "options": slots,
                        },
                    }
                ],
                "state_patch": {
                    "active_skill_state": "interview_coordination",
                    "pending_time_options": slots,
                    "pending_interview_target": {"name": interview_target} if interview_target else {},
                },
                "pending_commands": [
                    {
                        "id": f"time-option-{index + 1}",
                        "type": "select_option",
                        "title": slot["label"],
                        "payload": slot,
                    }
                    for index, slot in enumerate(slots)
                ],
                "artifacts": [],
            }

        if candidate_name and active_context.get("active_position"):
            current_candidate = self._resolve_candidate_name(active_context)
            if current_candidate and current_candidate != candidate_name:
                return {
                    "outputs": [
                        {
                            "type": "card",
                            "text": f"检测到新的候选人 {candidate_name}。要切换到候选人 {candidate_name} 吗？",
                            "data": {
                                "card_type": "candidate_switch",
                                "candidate_name": candidate_name,
                            },
                        }
                    ],
                    "state_patch": {
                        "active_skill_state": "resume_intake",
                        "pending_candidate": {"name": candidate_name},
                    },
                    "pending_commands": [
                        {
                            "id": "switch-candidate",
                            "type": "switch_context",
                            "title": f"切换到候选人 {candidate_name}",
                            "payload": {"candidate_name": candidate_name},
                        },
                        {
                            "id": "cancel-switch-candidate",
                            "type": "cancel",
                            "title": "保留当前候选人",
                            "payload": {},
                        },
                    ],
                    "artifacts": [],
                }

            return self._build_resume_analysis_result(
                candidate_name=candidate_name,
                active_context=active_context,
                user=user,
                tools=tools,
                source=content if content.startswith("http") else "",
            )

        if self._needs_position_before_resume_analysis(content, active_context):
            return {
                "outputs": [
                    {
                        "type": "card",
                        "text": "先告诉我岗位，我会先自动检索对应 JD，再继续看简历。",
                        "data": {"card_type": "position_request"},
                    }
                ],
                "state_patch": {
                    "active_skill_state": "resume_intake",
                    "resume_intent": "resume_review",
                    "position_required": True,
                },
                "pending_commands": [],
                "artifacts": [],
            }

        if active_context.get("position_required") and content:
            jd_hint = self._build_jd_hint(content, user=user, tools=tools)
            return {
                "outputs": [
                    {
                        "type": "message",
                        "text": f"已记录岗位：{content}。{jd_hint} 请贴飞书简历链接或卡片，或者直接输入候选人姓名。",
                        "data": {"stage": "position_recorded"},
                    }
                ],
                "state_patch": {
                    "active_position": content,
                    "position_required": False,
                    "active_skill_state": "resume_intake",
                },
                "pending_commands": [],
                "artifacts": [],
            }

        return {
            "outputs": [
                {
                    "type": "message",
                    "text": "HR Recruiting Skill 已接收请求。你可以继续提供候选人、岗位、面试安排、面试反馈或录用推进需求。",
                    "data": {"stage": "idle"},
                }
            ],
            "state_patch": {"active_skill_state": "idle"},
            "pending_commands": [],
            "artifacts": [],
        }

    def handle_command(
        self,
        *,
        session: Any,
        user: Any,
        command: str,
        payload: Dict[str, Any],
        tools: Dict[str, Any],
        policy_engine: Any,
    ) -> Dict[str, Any]:
        del policy_engine
        outputs: List[Dict[str, Any]]
        state_patch: Dict[str, Any] = {}

        if command == "switch_context":
            candidate_name = (payload or {}).get("candidate_name", "").strip()
            if candidate_name:
                result = self._build_resume_analysis_result(
                    candidate_name=candidate_name,
                    active_context=session.active_context or {},
                    user=user,
                    tools=tools,
                    source="",
                )
                state_patch = {
                    **result.get("state_patch", {}),
                    "pending_candidate": {},
                }
                return {
                    "outputs": result.get("outputs", []),
                    "state_patch": state_patch,
                    "pending_commands": result.get("pending_commands", []),
                    "artifacts": result.get("artifacts", []),
                }
            outputs = [
                {
                    "type": "message",
                    "text": "已收到上下文切换命令，但没有识别到候选人姓名。",
                    "data": {"command": command},
                }
            ]
        elif command in {"confirm", "approve_plan"}:
            pending_plan = (session.active_context or {}).get("pending_action_plan") or {}
            if not pending_plan:
                outputs = [
                    {
                        "type": "message",
                        "text": "当前没有待执行的动作计划。",
                        "data": {"command": command},
                    }
                ]
            else:
                binding = tools["lark_cli"].binding_service.get_status(user)
                if binding["status"] != "ACTIVE":
                    return self._build_binding_required_result(
                        "执行内部协同动作前需要先绑定飞书。",
                        binding,
                        state_patch={"pending_action_plan": pending_plan, "active_skill_state": "waiting_confirmation"},
                    )
                outputs = self._execute_plan(plan=pending_plan, tools=tools, user=user)
                state_patch["pending_action_plan"] = {}
                state_patch["active_skill_state"] = "completed"
                if outputs:
                    latest_tool_result = next(
                        (item.get("data", {}).get("result", {}) for item in reversed(outputs) if item.get("type") == "tool_result"),
                        {},
                    )
                    if latest_tool_result:
                        state_patch["last_tool_result"] = latest_tool_result
        elif command == "cancel":
            outputs = [
                {
                    "type": "message",
                    "text": "已取消当前待处理项。",
                    "data": {"command": command},
                }
            ]
            state_patch["pending_action_plan"] = {}
        elif command == "select_option":
            start = (payload or {}).get("start", "")
            end = (payload or {}).get("end", "")
            label = (payload or {}).get("label") or (payload or {}).get("value") or "未命名时间"
            interview_target = ((session.active_context or {}).get("pending_interview_target") or {}).get("name", "")
            outputs = [
                {
                    "type": "card",
                    "text": f"已选择时间：{label}。确认后我会继续创建面试日程并发送内部通知。",
                    "data": {
                        "card_type": "confirmation_request",
                        "selected_slot": {"start": start, "end": end, "label": label},
                    },
                }
            ]
            state_patch["selected_time_slot"] = {"start": start, "end": end, "label": label}
            state_patch["pending_action_plan"] = self._build_interview_schedule_plan(
                start=start,
                end=end,
                label=label,
                interview_target=interview_target,
            )
            return {
                "outputs": outputs,
                "state_patch": state_patch,
                "pending_commands": [
                    {"id": "confirm-selected-slot", "type": "confirm", "title": "确认执行", "payload": {}},
                    {"id": "cancel-selected-slot", "type": "cancel", "title": "取消", "payload": {}},
                ],
                "artifacts": [],
            }
        else:
            outputs = [
                {
                    "type": "message",
                    "text": "已收到命令，但当前没有匹配的后续动作。",
                    "data": {"command": command},
                }
            ]

        return {
            "outputs": outputs,
            "state_patch": state_patch,
            "pending_commands": [],
            "artifacts": [],
        }

    @staticmethod
    def _needs_position_before_resume_analysis(content: str, active_context: Dict[str, Any]) -> bool:
        if active_context.get("active_position"):
            return False
        if not content:
            return False
        return "简历" in content

    @staticmethod
    def _is_interview_schedule_request(content: str) -> bool:
        keywords = ("面试", "一面", "二面", "安排")
        return any(keyword in content for keyword in keywords)

    @staticmethod
    def _contains_explicit_time(content: str) -> bool:
        time_markers = ("点", "分钟", "下午", "上午", "明天", "今天", "周")
        return any(marker in content for marker in time_markers)

    @staticmethod
    def _is_feedback_summary_request(content: str) -> bool:
        return "反馈" in content and ("汇总" in content or "生成文档" in content)

    @staticmethod
    def _extract_candidate_name(content: str) -> str:
        stripped = content.strip()
        for suffix in ("的面试反馈并生成文档", "的面试反馈", "面试反馈", "简历"):
            if suffix in stripped:
                return stripped.split(suffix, 1)[0].replace("汇总", "").strip()
        return ""

    @staticmethod
    def _extract_interview_target_name(content: str) -> str:
        stripped = (content or "").strip()
        if not stripped:
            return ""
        match = re.search(r"安排(.+?)的?[一二三四五六七八九]?面", stripped)
        if match:
            return match.group(1).strip()
        return ""

    @staticmethod
    def _resolve_candidate_name(active_context: Dict[str, Any]) -> str:
        candidate = active_context.get("active_candidate") or {}
        return candidate.get("name", "")

    @staticmethod
    def _is_collaboration_execution_request(content: str) -> bool:
        message_markers = (
            "发给",
            "发送给",
            "发到",
            "发送到",
            "发信息给",
            "发消息给",
            "发送信息给",
            "发送消息给",
            "告诉",
            "通知",
        )
        meeting_markers = ("开", "会议", "分钟会")
        return any(marker in content for marker in message_markers) and any(
            marker in content for marker in meeting_markers
        )

    @staticmethod
    def _current_time() -> datetime:
        return datetime.now(SHANGHAI_TIMEZONE)

    @staticmethod
    def _infer_collaboration_target_kind(name: str) -> str:
        normalized_name = (name or "").strip()
        if normalized_name.endswith("群") or normalized_name.endswith("群聊"):
            return "chat"
        return "user"

    @staticmethod
    def _clean_collaboration_target_name(raw_target: str) -> str:
        cleaned = (raw_target or "").strip().strip("，。；,; ")
        cleaned = re.sub(r"^(?:给|到)", "", cleaned)
        cleaned = re.sub(r"(?:里|里面)$", "", cleaned)
        return cleaned.strip()

    @classmethod
    def _extract_collaboration_meeting_target(cls, content: str) -> Dict[str, str]:
        patterns = (
            r"约(?P<name>[A-Za-z0-9_\-\u4e00-\u9fff]{1,20}?)(?=明天|今天|后天|下午|上午|晚上|中午|\d{1,2}\s*点|开|聊|沟通|对齐|评审|预算)",
            r"和(?P<name>[A-Za-z0-9_\-\u4e00-\u9fff]{1,20}?)(?=开|聊|沟通|对齐|评审|预算)",
        )
        for pattern in patterns:
            match = re.search(pattern, content)
            if not match:
                continue
            name = cls._clean_collaboration_target_name(match.group("name"))
            if name and name not in {"他", "她", "它"} and cls._infer_collaboration_target_kind(name) == "user":
                return {"kind": "user", "name": name}
        return {"kind": "", "name": ""}

    @classmethod
    def _extract_collaboration_message_target(
        cls,
        content: str,
        *,
        fallback_user_name: str = "",
    ) -> Dict[str, str]:
        patterns = (
            r"(?:发(?:信息|消息)?给|发送(?:信息|消息)?给)(?P<target>[^，。；,]+)",
            r"(?:发给|发送给)(?P<target>[^，。；,]+)",
            r"(?:发(?:信息|消息)?到|发送(?:信息|消息)?到)(?P<target>[^，。；,]+)",
            r"(?:发到|发送到)(?P<target>[^，。；,]+)",
        )
        for pattern in patterns:
            match = re.search(pattern, content)
            if not match:
                continue
            target_name = cls._clean_collaboration_target_name(match.group("target"))
            if target_name in {"他", "她", "它"} and fallback_user_name:
                target_name = fallback_user_name
            if target_name:
                return {
                    "kind": cls._infer_collaboration_target_kind(target_name),
                    "name": target_name,
                }
        if fallback_user_name:
            return {"kind": "user", "name": fallback_user_name}
        return {"kind": "chat", "name": DEFAULT_INTERNAL_CHAT_QUERY}

    @classmethod
    def _extract_collaboration_message_body(cls, content: str, *, active_context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        shareable_text = cls._resolve_shareable_text(active_context or {})
        quoted_match = re.search(r"[“\"](?P<body>[^”\"]+)[”\"]", content)
        if quoted_match:
            body = quoted_match.group("body").strip()
            return {
                "summary_text": f"“{body}”",
                "text": body,
                "resolved": True,
            }

        body_match = re.search(r"把(?P<body>.+?)(?:发给|发送给|发到|发送到)", content)
        if body_match:
            body = body_match.group("body").strip().strip("，。；,; ")
            if body:
                if shareable_text and body in {"刚才的提纲", "刚才的结论", "刚才的摘要", "刚才的内容"}:
                    return {
                        "summary_text": body,
                        "text": shareable_text,
                        "resolved": True,
                    }
                return {
                    "summary_text": f"“{body}”",
                    "text": body,
                    "resolved": True,
                }

        tell_match = re.search(r"(?:告诉|通知)(?:他|她|对方|大家|所有人|候选人|[A-Za-z0-9_\-\u4e00-\u9fff]{1,20})?[，,:：]?(?P<body>.+)$", content)
        if tell_match:
            body = tell_match.group("body").strip().strip("，。；,; ")
            if body:
                return {
                    "summary_text": f"“{body}”",
                    "text": body,
                    "resolved": True,
                }

        if shareable_text and any(marker in content for marker in ("刚才", "刚刚", "上面", "前面", "上一条", "提纲", "结论", "摘要")):
            return {
                "summary_text": cls._resolve_reference_label(content),
                "text": shareable_text,
                "resolved": True,
            }

        return {
            "summary_text": "消息正文",
            "text": "",
            "resolved": False,
        }

    @classmethod
    def _extract_collaboration_schedule(cls, content: str) -> Dict[str, str]:
        now = cls._current_time()
        meeting_date = now.date()
        if "后天" in content:
            meeting_date = meeting_date + timedelta(days=2)
        elif "明天" in content:
            meeting_date = meeting_date + timedelta(days=1)

        hour = 15
        minute = 0
        time_match = re.search(r"(?:(上午|下午|晚上|中午))?\s*(\d{1,2})\s*点(?:\s*(半|\d{1,2})\s*分?)?", content)
        if time_match:
            meridiem = time_match.group(1) or ""
            hour = int(time_match.group(2))
            minute_token = time_match.group(3) or ""
            if minute_token == "半":
                minute = 30
            elif minute_token.isdigit():
                minute = int(minute_token)
            if meridiem in {"下午", "晚上"} and hour < 12:
                hour += 12
            elif meridiem == "中午" and hour < 11:
                hour += 12
            elif meridiem == "上午" and hour == 12:
                hour = 0

        duration_minutes = 30
        duration_match = re.search(r"(\d{1,3})\s*分钟", content)
        if duration_match:
            duration_minutes = int(duration_match.group(1))

        start = datetime(
            year=meeting_date.year,
            month=meeting_date.month,
            day=meeting_date.day,
            hour=hour,
            minute=minute,
            tzinfo=SHANGHAI_TIMEZONE,
        )
        end = start + timedelta(minutes=duration_minutes)
        return {"start": start.isoformat(), "end": end.isoformat()}

    @classmethod
    def _build_collaboration_plan(cls, content: str, *, active_context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        meeting_target = cls._extract_collaboration_meeting_target(content)
        message_target = cls._extract_collaboration_message_target(
            content,
            fallback_user_name=meeting_target.get("name", ""),
        )
        message_body = cls._extract_collaboration_message_body(content, active_context=active_context)
        schedule = cls._extract_collaboration_schedule(content)
        meeting_summary = "创建内部协同会议"
        if meeting_target.get("kind") == "user" and meeting_target.get("name"):
            meeting_summary = f"创建与 {meeting_target['name']} 的内部协同会议"
        if not message_body.get("resolved"):
            return {
                "kind": "collaboration_execution",
                "risk_level": "high",
                "source_text": content,
                "missing_fields": ["message_body"],
                "actions": [],
            }
        return {
            "kind": "collaboration_execution",
            "risk_level": "high",
            "source_text": content,
            "actions": [
                {
                    "capability": "calendar.schedule",
                    "summary": meeting_summary,
                    **({"contact_query": meeting_target["name"]} if meeting_target.get("kind") == "user" else {}),
                    "start": schedule["start"],
                    "end": schedule["end"],
                },
                {
                    "capability": "message.send",
                    "summary": f"发送{message_body['summary_text']}给 {message_target['name']}",
                    "target": {"query": message_target["name"], "type": message_target["kind"]},
                    "text": message_body["text"],
                    "append_previous_link": True,
                },
            ],
        }

    def _build_interview_schedule_plan(
        self,
        *,
        start: str,
        end: str,
        label: str,
        interview_target: str = "",
    ) -> Dict[str, Any]:
        candidate_label = interview_target or "候选人"
        notification_text = f"已安排 {candidate_label} 的面试时间：{label}。请相关同事确认并跟进。"
        return {
            "kind": "interview_schedule",
            "risk_level": "high",
            "actions": [
                {
                    "capability": "calendar.schedule",
                    "summary": f"安排内部面试：{label}",
                    **({"contact_query": interview_target} if interview_target else {}),
                    "start": start,
                    "end": end,
                },
                {
                    "capability": "message.send",
                    "summary": f"发送 {candidate_label} 面试通知到 {DEFAULT_INTERNAL_CHAT_QUERY}",
                    "target": {"query": DEFAULT_INTERNAL_CHAT_QUERY, "type": "chat"},
                    "text": notification_text,
                    "append_previous_link": True,
                },
            ],
        }

    @staticmethod
    def _resolve_shareable_text(active_context: Dict[str, Any]) -> str:
        for key in (
            "last_shareable_text",
            "last_knowledge_answer_text",
            "last_resume_analysis_summary",
            "last_feedback_summary_text",
        ):
            value = str(active_context.get(key) or "").strip()
            if value:
                return value
        return ""

    @staticmethod
    def _resolve_reference_label(content: str) -> str:
        if "提纲" in content:
            return "刚才的提纲"
        if "摘要" in content:
            return "刚才的摘要"
        if "结论" in content:
            return "刚才的结论"
        return "刚才的内容"

    def _execute_plan(self, *, plan: Dict[str, Any], tools: Dict[str, Any], user: Any) -> List[Dict[str, Any]]:
        lark_cli = tools["lark_cli"]
        outputs: List[Dict[str, Any]] = [
            {
                "type": "message",
                "text": "已确认，我正在按计划执行内部协同动作。",
                "data": {"plan_kind": plan.get("kind", "")},
            }
        ]
        previous_link = ""
        for action in plan.get("actions", []):
            execution_payload, resolution_note, resolution_failure = self._prepare_action_for_execution(
                action=action,
                lark_cli=lark_cli,
                user=user,
            )
            if resolution_note:
                outputs.append(
                    {
                        "type": "message",
                        "text": resolution_note,
                        "data": {"plan_kind": plan.get("kind", "")},
                    }
                )
            if resolution_failure:
                outputs.append(
                    {
                        "type": "tool_result",
                        "text": f"{action.get('summary', action.get('capability', 'action'))} 未执行",
                        "data": {
                            "preview": lark_cli.dry_run(action, user=user),
                            "result": resolution_failure,
                        },
                    }
                )
                continue
            preview = lark_cli.dry_run(execution_payload, user=user)
            if execution_payload.get("append_previous_link") and previous_link:
                execution_payload["text"] = f"{execution_payload.get('text', '').strip()}\n\n会议链接：{previous_link}".strip()
            try:
                result = lark_cli.execute(execution_payload, user=user)
            except (LarkCliError, ValueError) as exc:
                outputs.append(
                    {
                        "type": "tool_result",
                        "text": f"{action.get('summary', action.get('capability', 'action'))} 未执行",
                        "data": {
                            "preview": preview,
                            "result": self._build_tool_execution_failure(
                                summary=action.get("summary", action.get("capability", "action")),
                                exc=exc,
                            ),
                        },
                    }
                )
                continue
            previous_link = result.get("result_link", previous_link)
            outputs.append(
                {
                    "type": "tool_result",
                    "text": f"{action.get('summary', action.get('capability', 'action'))} 已执行",
                    "data": {
                        "preview": preview,
                        "result": result,
                    },
                }
            )
        return outputs

    @staticmethod
    def _pick_contact_match(matches: List[Dict[str, Any]], query: str) -> Dict[str, Any]:
        normalized_query = (query or "").strip()
        if not normalized_query:
            return matches[0] if matches else {}
        for item in matches:
            name = str(item.get("name") or item.get("user_name") or "")
            if name == normalized_query:
                return item
        return matches[0] if matches else {}

    @staticmethod
    def _pick_chat_match(matches: List[Dict[str, Any]], query: str) -> Dict[str, Any]:
        normalized_query = (query or "").strip()
        if not normalized_query:
            return matches[0] if matches else {}
        for item in matches:
            name = str(item.get("name") or item.get("chat_name") or "")
            if name == normalized_query:
                return item
        return matches[0] if matches else {}

    @staticmethod
    def _build_tool_resolution_failure(*, summary: str, exc: LarkCliError) -> Dict[str, Any]:
        missing_scopes = list(exc.details.get("missing_scopes") or [])
        error_message = exc.message
        if exc.code == "feishu_scope_missing" and missing_scopes:
            scope_list = ", ".join(missing_scopes)
            error_message = (
                f"{summary} 需要额外飞书权限：{scope_list}。"
                "请在飞书开放平台开通后点击“重新绑定飞书”完成授权刷新。"
            )
        return {
            "status": "failed",
            "summary": summary,
            "result_link": "",
            "external_id": "",
            "error_code": exc.code,
            "error_message": error_message,
        }

    @classmethod
    def _build_tool_execution_failure(cls, *, summary: str, exc: Exception) -> Dict[str, Any]:
        if isinstance(exc, LarkCliError):
            if exc.code == "feishu_cli_command_failed":
                raw_message = str(exc.details.get("stderr") or exc.details.get("stdout") or exc.message or "")
                friendly_message = raw_message
                try:
                    parsed = json.loads(raw_message)
                except json.JSONDecodeError:
                    parsed = None
                if isinstance(parsed, dict):
                    error = parsed.get("error") or {}
                    error_message = str(error.get("message") or "").strip()
                    error_code = str(error.get("code") or "").strip()
                    if error_code == "230001" or "invalid receive_id" in error_message:
                        friendly_message = "机器人可能不在目标群里，或这个群当前对应用不可见。请先把应用机器人加入群，再重试。"
                    elif "Bot/User can NOT be out of the chat" in error_message:
                        friendly_message = "机器人当前不在这个群里，请先把应用机器人加入目标群，再重试。"
                    elif error_message:
                        friendly_message = error_message
                elif "bot is not allowed to send message to this chat" in raw_message:
                    friendly_message = "机器人当前不能向这个会话发消息，请确认机器人已经入群并具备发言权限。"
                elif "Bot/User can NOT be out of the chat" in raw_message:
                    friendly_message = "机器人当前不在这个群里，请先把应用机器人加入目标群，再重试。"
                return {
                    "status": "failed",
                    "summary": summary,
                    "result_link": "",
                    "external_id": "",
                    "error_code": exc.code,
                    "error_message": friendly_message,
                }
            return cls._build_tool_resolution_failure(summary=summary, exc=exc)
        return {
            "status": "failed",
            "summary": summary,
            "result_link": "",
            "external_id": "",
            "error_code": "tool_execution_failed",
            "error_message": str(exc) or "Tool execution failed.",
        }

    def _prepare_action_for_execution(
        self,
        *,
        action: Dict[str, Any],
        lark_cli: Any,
        user: Any,
    ) -> tuple[Dict[str, Any], str, Optional[Dict[str, Any]]]:
        execution_payload = dict(action)
        capability = execution_payload.get("capability", "")
        if capability == "calendar.schedule":
            query = str(execution_payload.pop("contact_query", "")).strip()
            if query:
                try:
                    contact_result = lark_cli.execute({"capability": "contact.resolve", "query": query}, user=user)
                    contact = self._pick_contact_match(contact_result.get("matches", []), query)
                    open_id = str(contact.get("open_id") or "")
                except LarkCliError as exc:
                    note = f"暂时无法把 {query} 自动加入会议参会人"
                    if exc.code == "feishu_scope_missing":
                        missing_scopes = ", ".join(exc.details.get("missing_scopes") or [])
                        note = f"{note}（缺少 {missing_scopes}），我先创建你的日程。"
                    else:
                        note = f"{note}，我先创建你的日程。"
                    return execution_payload, note, None
                if open_id:
                    attendee_ids = list(execution_payload.get("attendee_ids") or [])
                    if open_id not in attendee_ids:
                        attendee_ids.append(open_id)
                    execution_payload["attendee_ids"] = attendee_ids
                    return execution_payload, f"已将 {query} 解析为飞书联系人并加入会议参会人。", None
                try:
                    chat_result = lark_cli.execute({"capability": "chat.resolve", "query": query}, user=user)
                    chat = self._pick_chat_match(chat_result.get("matches", []), query)
                    chat_id = str(chat.get("chat_id") or chat.get("id") or "")
                except LarkCliError as exc:
                    note = f"没有在飞书通讯录里找到 {query}"
                    if exc.code == "feishu_scope_missing":
                        missing_scopes = ", ".join(exc.details.get("missing_scopes") or [])
                        note = f"{note}，而且外部联系人会话检索还缺少 {missing_scopes}，本次先只创建你的日程。"
                    else:
                        note = f"{note}，本次先只创建你的日程。"
                    return execution_payload, note, None
                if chat_id:
                    attendee_ids = list(execution_payload.get("attendee_ids") or [])
                    if chat_id not in attendee_ids:
                        attendee_ids.append(chat_id)
                    execution_payload["attendee_ids"] = attendee_ids
                    return execution_payload, f"已将 {query} 解析为飞书私聊会话并加入会议参会对象。", None
                return execution_payload, f"没有在飞书通讯录里找到 {query}，本次先只创建你的日程。", None

        if capability == "message.send":
            target = dict(execution_payload.get("target") or {})
            query = str(target.get("query") or "").strip()
            if query and not target.get("chat_id") and not target.get("user_id"):
                target_type = str(target.get("type") or "").strip() or ("chat" if query.endswith("群") else "user")
                try:
                    if target_type == "chat":
                        chat_result = lark_cli.execute({"capability": "chat.resolve", "query": query}, user=user)
                        chat = self._pick_chat_match(chat_result.get("matches", []), query)
                        chat_id = str(chat.get("chat_id") or chat.get("id") or "")
                        if not chat_id:
                            return execution_payload, "", {
                                "status": "failed",
                                "summary": f"没有找到可发送的飞书群聊：{query}",
                                "result_link": "",
                                "external_id": "",
                                "error_code": "chat_not_found",
                                "error_message": f"没有在飞书群聊里找到 {query}",
                            }
                        target.pop("query", None)
                        target["chat_id"] = chat_id
                        execution_payload["target"] = target
                        return execution_payload, f"已将 {query} 解析为飞书群聊，消息会发到这个群。", None

                    contact_result = lark_cli.execute({"capability": "contact.resolve", "query": query}, user=user)
                    contact = self._pick_contact_match(contact_result.get("matches", []), query)
                    open_id = str(contact.get("open_id") or "")
                    if not open_id:
                        chat_result = lark_cli.execute({"capability": "chat.resolve", "query": query}, user=user)
                        chat = self._pick_chat_match(chat_result.get("matches", []), query)
                        chat_id = str(chat.get("chat_id") or "")
                        if not chat_id:
                            return execution_payload, "", {
                                "status": "failed",
                                "summary": f"没有找到可发送的飞书联系人或会话：{query}",
                                "result_link": "",
                                "external_id": "",
                                "error_code": "contact_not_found",
                                "error_message": f"没有在飞书通讯录或私聊会话里找到 {query}",
                            }
                        target.pop("query", None)
                        target["chat_id"] = chat_id
                        execution_payload["target"] = target
                        return execution_payload, f"已将 {query} 解析为飞书私聊会话，消息会发到这个会话。", None
                    target.pop("query", None)
                    target["user_id"] = open_id
                    execution_payload["target"] = target
                    return execution_payload, f"已将 {query} 解析为飞书联系人，消息会发给这个成员。", None
                except LarkCliError as exc:
                    return execution_payload, "", self._build_tool_resolution_failure(
                        summary=f"未能解析发送目标：{query}",
                        exc=exc,
                    )

        return execution_payload, "", None

    @staticmethod
    def _detect_candidate_name(content: str, active_context: Dict[str, Any]) -> str:
        content = content.strip()
        if not content:
            return ""
        if content.startswith("http://") or content.startswith("https://"):
            return ""
        if any(token in content for token in ("面试", "安排", "反馈", "文档", "发给", "会议", "岗位", "JD")):
            return ""
        if active_context.get("position_required"):
            return ""
        if len(content) <= 6 and all("\u4e00" <= ch <= "\u9fff" for ch in content):
            return content
        return ""

    def _build_resume_analysis_result(
        self,
        *,
        candidate_name: str,
        active_context: Dict[str, Any],
        user: Any,
        tools: Dict[str, Any],
        source: str,
    ) -> Dict[str, Any]:
        position = active_context.get("active_position", "当前岗位")
        summary_title = f"{candidate_name} 简历摘要"
        analysis_title = f"{candidate_name} 候选人分析"
        binding = tools["lark_cli"].binding_service.get_status(user)
        if binding["status"] != "ACTIVE":
            return self._build_binding_required_result(
                "继续看简历前需要先绑定飞书，这样我才能读取飞书里的简历附件或文档。",
                binding,
                state_patch={
                    "active_candidate": {"name": candidate_name},
                    "active_skill_state": "resume_intake",
                },
            )

        jd_search = tools["knowledge_search"].execute({"query": position, "limit": 3}, user=user)
        jd_items = jd_search.get("items", [])
        jd_titles = [item.get("title", "") for item in jd_items if item.get("title")]

        highlights = ["请补充飞书简历链接后，我可以给出更精确的亮点和风险。"]
        analysis_text = "建议先获取简历原文后再做最终判断。"
        recommendation = "待补充简历原文后确认"
        resume_payload: Dict[str, Any] = {
            "candidate_name": candidate_name,
            "position": position,
            "highlights": highlights,
            "source": "candidate_name",
        }

        if source.startswith("http://") or source.startswith("https://"):
            try:
                fetched = tools["resume_fetch"].execute({"source": source}, user=user)
                parsed = tools["resume_parse"].execute(
                    {
                        "local_path": fetched.get("local_path", ""),
                        "content": fetched.get("content", ""),
                        "source_type": fetched.get("source_type", ""),
                    }
                )
                parsed_highlights = parsed.get("highlights", [])
                if parsed_highlights:
                    highlights = parsed_highlights[:5]
                if highlights:
                    analysis_text = f"已基于飞书简历原文给出初步分析，建议结合 {position} 继续评估。"
                    recommendation = "建议继续推进下一轮"
                resume_payload.update(
                    {
                        "source": source,
                        "fetched_title": fetched.get("title", ""),
                        "parsed_text": parsed.get("text", ""),
                        "highlights": highlights,
                    }
                )
            except Exception:
                analysis_text = "我已识别到简历来源，但暂时没有成功解析，建议重新贴一次飞书链接或卡片。"
        shareable_summary = f"{candidate_name}：{recommendation}。{analysis_text}"

        return {
            "outputs": [
                {
                    "type": "message",
                    "text": f"我已经基于岗位 {position} 给出 {candidate_name} 的候选人分析建议，先看亮点、风险和是否建议推进下一轮。",
                    "data": {
                        "stage": "resume_analysis",
                        "candidate_name": candidate_name,
                        "jd_titles": jd_titles,
                    },
                },
                {
                    "type": "artifact",
                    "text": summary_title,
                    "data": {"artifact_type": "resume_summary", "title": summary_title},
                },
                {
                    "type": "artifact",
                    "text": analysis_title,
                    "data": {"artifact_type": "candidate_analysis", "title": analysis_title},
                },
            ],
            "state_patch": {
                "active_candidate": {"name": candidate_name},
                "active_skill_state": "resume_analysis",
                "active_jd_titles": jd_titles,
                "last_resume_analysis_summary": shareable_summary,
                "last_shareable_text": shareable_summary,
            },
            "pending_commands": [],
            "artifacts": [
                {
                    "artifact_type": "resume_summary",
                    "title": summary_title,
                    "payload": resume_payload,
                },
                {
                    "artifact_type": "candidate_analysis",
                    "title": analysis_title,
                    "payload": {
                        "candidate_name": candidate_name,
                        "position": position,
                        "recommendation": recommendation,
                        "analysis": analysis_text,
                        "risks": ["需要结合 JD 与项目深度继续核验"],
                        "jd_titles": jd_titles,
                    },
                },
            ],
        }

    def _handle_feedback_summary(
        self,
        *,
        user: Any,
        content: str,
        active_context: Dict[str, Any],
        tools: Dict[str, Any],
    ) -> Dict[str, Any]:
        candidate_name = self._extract_candidate_name(content) or self._resolve_candidate_name(active_context) or "当前候选人"
        binding = tools["lark_cli"].binding_service.get_status(user)
        if binding["status"] != "ACTIVE":
            return self._build_binding_required_result(
                "生成反馈汇总文档前需要先绑定飞书。",
                binding,
                state_patch={"active_skill_state": "feedback_synthesis"},
            )

        markdown = "\n".join(
            [
                f"# {candidate_name} 面试反馈汇总",
                "",
                "## 亮点",
                "- 项目经历贴近当前岗位",
                "",
                "## 风险点",
                "- 需要继续核验系统设计深度",
                "",
                "## 建议动作",
                "- 建议进入下一轮面试",
            ]
        )
        doc_result = tools["doc_generate"].execute(
            {
                "title": f"{candidate_name} 面试反馈汇总",
                "markdown": markdown,
                "summary": f"已在 HR 私人云文档空间生成 {candidate_name} 的面试反馈汇总",
            },
            user=user,
        )
        return {
            "outputs": [
                {
                    "type": "message",
                    "text": "我已经整理好面试反馈摘要，并默认生成到 HR 自己的云文档空间。",
                    "data": {"stage": "feedback_synthesis"},
                },
                {
                    "type": "tool_result",
                    "text": "面试反馈汇总文档已生成",
                    "data": {"result": doc_result},
                },
                {
                    "type": "artifact",
                    "text": f"{candidate_name} 面试反馈汇总",
                    "data": {
                        "artifact_type": "generated_doc",
                        "title": f"{candidate_name} 面试反馈汇总",
                    },
                },
            ],
            "state_patch": {
                "active_skill_state": "feedback_synthesis",
                "last_generated_artifact": {
                    "artifact_type": "generated_doc",
                    "title": f"{candidate_name} 面试反馈汇总",
                },
                "last_feedback_summary_text": f"{candidate_name} 面试反馈已汇总，建议进入下一轮面试。",
                "last_shareable_text": f"{candidate_name} 面试反馈已汇总，建议进入下一轮面试。",
            },
            "pending_commands": [],
            "artifacts": [
                {
                    "artifact_type": "generated_doc",
                    "title": f"{candidate_name} 面试反馈汇总",
                    "payload": {
                        "candidate_name": candidate_name,
                        "space": "hr_private_docs",
                        "result_link": doc_result.get("result_link", ""),
                        "external_id": doc_result.get("external_id", ""),
                    },
                }
            ],
        }

    @staticmethod
    def _build_binding_required_result(
        text: str,
        binding: Dict[str, Any],
        *,
        state_patch: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        return {
            "outputs": [
                {
                    "type": "card",
                    "text": text,
                    "data": {
                        "card_type": "feishu_binding_required",
                        "binding_status": binding.get("status", "UNBOUND"),
                        "missing_scopes": binding.get("missing_scopes", []),
                    },
                }
            ],
            "state_patch": state_patch or {},
            "pending_commands": [],
            "artifacts": [],
        }

    @staticmethod
    def _build_jd_hint(position: str, *, user: Any, tools: Dict[str, Any]) -> str:
        try:
            result = tools["knowledge_search"].execute({"query": position, "limit": 2}, user=user)
            items = result.get("items", [])
        except Exception:
            items = []
        if items:
            titles = "、".join(item.get("title", "") for item in items[:2] if item.get("title"))
            return f"我已经先帮你检索了相关 JD，命中的资料有：{titles}。"
        return "我暂时没有自动命中 JD，后续你也可以直接补充 JD 或岗位要求。"
