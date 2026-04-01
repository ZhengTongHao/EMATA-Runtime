import asyncio
import json
import os
import subprocess
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import httpx

from app.ask_skill_hr_recruiting import HRRecruitingSkill
from app.integrations import TemporalRuntime
from app.main import create_app


class TestFallbackTemporalRuntime(TemporalRuntime):
    def __init__(self) -> None:
        super().__init__(target_hostport="temporal:7233", namespace="default")
        self.mode = "fallback"
        self.reason = "test_runtime"


def build_test_app(*, preserve_model_env: bool = False):
    tempdir = tempfile.mkdtemp(prefix="emata-ask-")
    database_url = f"sqlite:///{os.path.join(tempdir, 'test.db')}"
    os.environ["EMATA_LARK_CLI_CONFIG_BASE_DIR"] = os.path.join(tempdir, "lark-cli")
    if not preserve_model_env:
        os.environ["EMATA_EMBEDDING_BASE_URL"] = ""
        os.environ["EMATA_EMBEDDING_API_KEY"] = ""
        os.environ["EMATA_MODEL_BASE_URL"] = ""
        os.environ["EMATA_MODEL_API_KEY"] = ""
        os.environ["EMATA_MODEL_NAME"] = ""
        os.environ["EMATA_RERANK_BASE_URL"] = ""
        os.environ["EMATA_RERANK_API_KEY"] = ""
        os.environ["EMATA_RERANK_MODEL"] = ""
    app = create_app(
        database_url=database_url,
        temporal_runtime=TestFallbackTemporalRuntime(),
    )
    return app, tempdir


def build_client(*, preserve_model_env: bool = False) -> httpx.AsyncClient:
    app, _tempdir = build_test_app(preserve_model_env=preserve_model_env)
    transport = httpx.ASGITransport(app=app)
    return httpx.AsyncClient(transport=transport, base_url="http://testserver")


def fake_lark_cli_subprocess(command, **kwargs):
    joined = " ".join(command)

    if " config init " in f" {joined} ":
        return subprocess.CompletedProcess(command, 0, stdout=json.dumps({"ok": True}), stderr="")

    if " auth login " in f" {joined} " and "--no-wait" in command:
        payload = {
            "verification_url": "https://open.feishu.cn/device/verify",
            "device_code": "device-code-123",
            "expires_in": 900,
            "hint": "Open the verification URL to continue.",
        }
        return subprocess.CompletedProcess(command, 0, stdout=json.dumps(payload), stderr="")

    if " auth login " in f" {joined} " and "--device-code" in command:
        payload = {
            "userName": "测试 HR",
            "userOpenId": "ou_test_hr",
            "identity": "user",
        }
        return subprocess.CompletedProcess(command, 0, stdout=json.dumps(payload), stderr="")

    if " auth status " in f" {joined} ":
        payload = {
            "identity": "user",
            "userName": "测试 HR",
            "userOpenId": "ou_test_hr",
            "tokenStatus": "valid",
            "scope": [
                "contact:user:search",
                "search:docs:read",
                "docx:document:readonly",
                "docx:document:create",
                "drive:file:download",
                "im:chat:read",
                "calendar:calendar.free_busy:read",
                "calendar:calendar.event:create",
                "calendar:calendar.event:update",
                "im:message:send_as_bot",
            ],
        }
        return subprocess.CompletedProcess(command, 0, stdout=json.dumps(payload), stderr="")

    if " auth check " in f" {joined} ":
        payload = {
            "ok": True,
            "granted": [
                "contact:user:search",
                "search:docs:read",
                "docx:document:readonly",
                "docx:document:create",
                "drive:file:download",
                "im:chat:read",
                "calendar:calendar.free_busy:read",
                "calendar:calendar.event:create",
                "calendar:calendar.event:update",
                "im:message:send_as_bot",
            ],
            "missing": [],
        }
        return subprocess.CompletedProcess(command, 0, stdout=json.dumps(payload), stderr="")

    if " auth logout " in f" {joined} ":
        return subprocess.CompletedProcess(command, 0, stdout=json.dumps({"ok": True}), stderr="")

    if " contact +search-user " in f" {joined} ":
        if "李雷" in joined:
            payload = {"users": []}
        else:
            payload = {
                "users": [
                    {
                        "open_id": "ou_internal_candidate",
                        "name": "张三",
                        "email": "zhangsan@example.com",
                    }
                ]
            }
        return subprocess.CompletedProcess(command, 0, stdout=json.dumps(payload), stderr="")

    if " im +chat-search " in f" {joined} ":
        if "李雷" in joined:
            if "--search-types" in command:
                payload = {
                    "data": {
                        "items": [
                            {
                                "chat_id": "oc_li_lei_p2p",
                                "name": "李雷",
                                "chat_mode": "p2p",
                            }
                        ]
                    }
                }
            else:
                payload = {"data": {"items": []}}
        elif "Ai" in joined:
            payload = {
                "data": {
                    "items": [
                        {
                            "chat_id": "oc_ai_group",
                            "name": "Ai应用开发群",
                        }
                    ]
                }
            }
        else:
            payload = {
                "data": {
                    "items": [
                        {
                            "chat_id": "oc_tech_interview",
                            "name": "鎶€鏈潰璇曠兢",
                        }
                    ]
                }
            }
        return subprocess.CompletedProcess(command, 0, stdout=json.dumps(payload), stderr="")

    if " calendar +suggestion " in f" {joined} ":
        payload = {
            "data": {
                "suggestions": [
                    {"event_start_time": "2026-03-31T14:00:00+08:00", "event_end_time": "2026-03-31T14:30:00+08:00"},
                    {"event_start_time": "2026-03-31T15:00:00+08:00", "event_end_time": "2026-03-31T15:30:00+08:00"},
                    {"event_start_time": "2026-03-31T16:00:00+08:00", "event_end_time": "2026-03-31T16:30:00+08:00"},
                ]
            }
        }
        return subprocess.CompletedProcess(command, 0, stdout=json.dumps(payload), stderr="")

    if " calendar +create " in f" {joined} ":
        payload = {
            "event_id": "evt_123",
            "summary": "与李雷预算评审沟通",
            "start": "2026-03-31T15:00:00+08:00",
            "end": "2026-03-31T15:30:00+08:00",
            "event_url": "https://feishu.cn/calendar/event/evt_123",
        }
        return subprocess.CompletedProcess(command, 0, stdout=json.dumps(payload), stderr="")

    if " im +messages-send " in f" {joined} ":
        if "--chat-id" in command and "oc_li_lei_p2p" in command:
            payload = {
                "message_id": "om_li_lei_123",
                "chat_id": "oc_li_lei_p2p",
                "create_time": "1711771200000",
                "message_url": "https://feishu.cn/im/message/om_li_lei_123",
            }
            return subprocess.CompletedProcess(command, 0, stdout=json.dumps(payload), stderr="")
        if "--chat-id" in command:
            payload = {
                "message_id": "om_group_123",
                "chat_id": "oc_tech_interview",
                "create_time": "1711771200000",
                "message_url": "https://feishu.cn/im/message/om_group_123",
            }
            return subprocess.CompletedProcess(command, 0, stdout=json.dumps(payload), stderr="")
        payload = {
            "message_id": "om_123",
            "chat_id": "oc_123",
            "create_time": "1711771200000",
            "message_url": "https://feishu.cn/im/message/om_123",
        }
        return subprocess.CompletedProcess(command, 0, stdout=json.dumps(payload), stderr="")

    if " docs +create " in f" {joined} ":
        payload = {
            "doc_id": "doc_123",
            "doc_url": "https://feishu.cn/docx/doc_123",
            "message": "document created",
        }
        return subprocess.CompletedProcess(command, 0, stdout=json.dumps(payload), stderr="")

    raise AssertionError(f"Unexpected lark-cli command: {joined}")


class AskApiTestCase(unittest.IsolatedAsyncioTestCase):
    async def test_ambiguous_action_request_returns_clarification_instead_of_skill_default(self) -> None:
        client = build_client()
        session_response = await client.post(
            "/api/v1/ask/sessions",
            json={"skill_id": "hr_recruiting", "title": "Ask Copilot"},
        )
        session_id = session_response.json()["id"]

        response = await client.post(
            f"/api/v1/ask/sessions/{session_id}/turns",
            json={"content": "发给他"},
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["outputs"][0]["type"], "card")
        self.assertEqual(payload["outputs"][0]["data"]["card_type"], "clarification")
        await client.aclose()

    async def test_message_request_returns_target_selection_card_with_top_three_and_other(self) -> None:
        with patch("app.ask_tools.subprocess.run", side_effect=fake_lark_cli_subprocess):
            client = build_client()
            await client.post("/api/v1/ask/bindings/feishu/start", json={})
            await client.post("/api/v1/ask/bindings/feishu/complete", json={"device_code": "device-code-123"})
            session_response = await client.post(
                "/api/v1/ask/sessions",
                json={"skill_id": "hr_recruiting", "title": "Ask Copilot"},
            )
            session_id = session_response.json()["id"]

            response = await client.post(
                f"/api/v1/ask/sessions/{session_id}/turns",
                json={"content": "发信息给李雷，告诉他面试通过了"},
            )

            self.assertEqual(response.status_code, 200)
            payload = response.json()
            self.assertEqual(payload["outputs"][0]["data"]["card_type"], "target_selection")
            options = payload["outputs"][0]["data"]["options"]
            self.assertLessEqual(len(options), 5)
            self.assertEqual(options[-2]["kind"], "other")
            self.assertEqual(options[-1]["kind"], "cancel")
            self.assertIn("search_results", payload["outputs"][0]["data"])
            await client.aclose()

    async def test_message_request_exposes_contact_and_chat_search_results_in_target_selection_card(self) -> None:
        with patch("app.ask_tools.subprocess.run", side_effect=fake_lark_cli_subprocess):
            client = build_client()
            await client.post("/api/v1/ask/bindings/feishu/start", json={})
            await client.post("/api/v1/ask/bindings/feishu/complete", json={"device_code": "device-code-123"})
            session_response = await client.post(
                "/api/v1/ask/sessions",
                json={"skill_id": "hr_recruiting", "title": "Ask Copilot"},
            )
            session_id = session_response.json()["id"]

            response = await client.post(
                f"/api/v1/ask/sessions/{session_id}/turns",
                json={"content": "把“你好”发到 Ai应用开发群"},
            )

            self.assertEqual(response.status_code, 200)
            payload = response.json()
            search_results = payload["outputs"][0]["data"]["search_results"]
            self.assertIn("contacts", search_results)
            self.assertIn("chats", search_results)
            self.assertGreaterEqual(len(search_results["chats"]), 1)
            self.assertEqual(search_results["chats"][0]["label"], "Ai应用开发群")
            await client.aclose()

    async def test_message_request_with_exact_group_target_goes_straight_to_preview(self) -> None:
        with patch("app.ask_tools.subprocess.run", side_effect=fake_lark_cli_subprocess):
            client = build_client()
            await client.post("/api/v1/ask/bindings/feishu/start", json={})
            await client.post("/api/v1/ask/bindings/feishu/complete", json={"device_code": "device-code-123"})
            session_response = await client.post(
                "/api/v1/ask/sessions",
                json={"skill_id": "hr_recruiting", "title": "Ask Copilot"},
            )
            session_id = session_response.json()["id"]

            response = await client.post(
                f"/api/v1/ask/sessions/{session_id}/turns",
                json={"content": "给“Ai应用开发群”发送消息“下午两点开会”"},
            )

            self.assertEqual(response.status_code, 200)
            payload = response.json()
            self.assertEqual(payload["outputs"][0]["data"]["card_type"], "action_preview")
            self.assertEqual(payload["outputs"][0]["data"]["draft"]["resolved_target"]["value"], "oc_ai_group")
            self.assertEqual(payload["outputs"][0]["data"]["draft"]["text"], "下午两点开会")
            await client.aclose()

    async def test_message_request_accepts_target_before_verb_word_order(self) -> None:
        with patch("app.ask_tools.subprocess.run", side_effect=fake_lark_cli_subprocess):
            client = build_client()
            await client.post("/api/v1/ask/bindings/feishu/start", json={})
            await client.post("/api/v1/ask/bindings/feishu/complete", json={"device_code": "device-code-123"})
            session_response = await client.post(
                "/api/v1/ask/sessions",
                json={"skill_id": "hr_recruiting", "title": "Ask Copilot"},
            )
            session_id = session_response.json()["id"]

            response = await client.post(
                f"/api/v1/ask/sessions/{session_id}/turns",
                json={"content": "给李雷发消息“不错”"},
            )

            self.assertEqual(response.status_code, 200)
            payload = response.json()
            self.assertEqual(payload["outputs"][0]["data"]["card_type"], "target_selection")
            await client.aclose()

    async def test_message_request_accepts_send_without_message_noun(self) -> None:
        with patch("app.ask_tools.subprocess.run", side_effect=fake_lark_cli_subprocess):
            client = build_client()
            await client.post("/api/v1/ask/bindings/feishu/start", json={})
            await client.post("/api/v1/ask/bindings/feishu/complete", json={"device_code": "device-code-123"})
            session_response = await client.post(
                "/api/v1/ask/sessions",
                json={"skill_id": "hr_recruiting", "title": "Ask Copilot"},
            )
            session_id = session_response.json()["id"]

            response = await client.post(
                f"/api/v1/ask/sessions/{session_id}/turns",
                json={"content": "给李雷发送“你好”"},
            )

            self.assertEqual(response.status_code, 200)
            payload = response.json()
            self.assertEqual(payload["outputs"][0]["data"]["card_type"], "target_selection")
            await client.aclose()

    async def test_meeting_request_in_group_enters_generic_action_flow(self) -> None:
        with patch("app.ask_tools.subprocess.run", side_effect=fake_lark_cli_subprocess):
            client = build_client()
            await client.post("/api/v1/ask/bindings/feishu/start", json={})
            await client.post("/api/v1/ask/bindings/feishu/complete", json={"device_code": "device-code-123"})
            session_response = await client.post(
                "/api/v1/ask/sessions",
                json={"skill_id": "hr_recruiting", "title": "Ask Copilot"},
            )
            session_id = session_response.json()["id"]

            response = await client.post(
                f"/api/v1/ask/sessions/{session_id}/turns",
                json={"content": "下午五点 在Ai应用开发群开会"},
            )

            self.assertEqual(response.status_code, 200)
            payload = response.json()
            self.assertEqual(payload["outputs"][0]["data"]["card_type"], "action_preview")
            self.assertEqual(payload["outputs"][0]["data"]["draft"]["intent"], "calendar.schedule")
            await client.aclose()

    async def test_meeting_request_with_group_name_before_time_enters_generic_action_flow(self) -> None:
        with patch("app.ask_tools.subprocess.run", side_effect=fake_lark_cli_subprocess):
            client = build_client()
            await client.post("/api/v1/ask/bindings/feishu/start", json={})
            await client.post("/api/v1/ask/bindings/feishu/complete", json={"device_code": "device-code-123"})
            session_response = await client.post(
                "/api/v1/ask/sessions",
                json={"skill_id": "hr_recruiting", "title": "Ask Copilot"},
            )
            session_id = session_response.json()["id"]

            response = await client.post(
                f"/api/v1/ask/sessions/{session_id}/turns",
                json={"content": "Ai应用开发群下午两点开会"},
            )

            self.assertEqual(response.status_code, 200)
            payload = response.json()
            self.assertEqual(payload["outputs"][0]["data"]["card_type"], "action_preview")
            self.assertEqual(payload["outputs"][0]["data"]["draft"]["intent"], "calendar.schedule")
            self.assertEqual(payload["outputs"][0]["data"]["draft"]["target_query"], "Ai应用开发群")
            await client.aclose()

    async def test_selecting_target_updates_pending_draft_and_returns_preview(self) -> None:
        client = build_client()
        session_response = await client.post(
            "/api/v1/ask/sessions",
            json={"skill_id": "hr_recruiting", "title": "Ask Copilot"},
        )
        session_id = session_response.json()["id"]

        first_response = await client.post(
            f"/api/v1/ask/sessions/{session_id}/turns",
            json={"content": "发信息给李雷，告诉他面试通过了"},
        )
        self.assertEqual(first_response.status_code, 200)

        response = await client.post(
            f"/api/v1/ask/sessions/{session_id}/commands",
            json={"command": "select_option", "payload": {"kind": "user", "label": "李雷", "value": "ou_li_lei", "query": "李雷"}},
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["outputs"][0]["data"]["card_type"], "action_preview")
        self.assertEqual(payload["state_patch"]["pending_action_draft"]["resolved_target"]["value"], "ou_li_lei")
        await client.aclose()

    async def test_other_target_followup_continues_message_action_instead_of_falling_back_to_hr_skill(self) -> None:
        with patch("app.ask_tools.subprocess.run", side_effect=fake_lark_cli_subprocess):
            client = build_client()
            await client.post("/api/v1/ask/bindings/feishu/start", json={})
            await client.post("/api/v1/ask/bindings/feishu/complete", json={"device_code": "device-code-123"})
            session_response = await client.post(
                "/api/v1/ask/sessions",
                json={"skill_id": "hr_recruiting", "title": "Ask Copilot"},
            )
            session_id = session_response.json()["id"]

            first_response = await client.post(
                f"/api/v1/ask/sessions/{session_id}/turns",
                json={"content": "给李雷发送“你好”"},
            )
            self.assertEqual(first_response.status_code, 200)

            other_response = await client.post(
                f"/api/v1/ask/sessions/{session_id}/commands",
                json={"command": "select_option", "payload": {"kind": "other", "label": "其他", "value": "", "query": "李雷"}},
            )
            self.assertEqual(other_response.status_code, 200)

            followup_response = await client.post(
                f"/api/v1/ask/sessions/{session_id}/turns",
                json={"content": "李雷"},
            )
            self.assertEqual(followup_response.status_code, 200)
            payload = followup_response.json()
            self.assertEqual(payload["outputs"][0]["data"]["card_type"], "action_preview")
            self.assertEqual(payload["state_patch"]["pending_action_draft"]["resolved_target"]["value"], "oc_li_lei_p2p")
            await client.aclose()

    async def test_other_target_followup_accepts_direct_user_open_id_and_returns_preview(self) -> None:
        with patch("app.ask_tools.subprocess.run", side_effect=fake_lark_cli_subprocess):
            client = build_client()
            await client.post("/api/v1/ask/bindings/feishu/start", json={})
            await client.post("/api/v1/ask/bindings/feishu/complete", json={"device_code": "device-code-123"})
            session_response = await client.post(
                "/api/v1/ask/sessions",
                json={"skill_id": "hr_recruiting", "title": "Ask Copilot"},
            )
            session_id = session_response.json()["id"]

            first_response = await client.post(
                f"/api/v1/ask/sessions/{session_id}/turns",
                json={"content": "给李雷发送“你好”"},
            )
            self.assertEqual(first_response.status_code, 200)

            other_response = await client.post(
                f"/api/v1/ask/sessions/{session_id}/commands",
                json={"command": "select_option", "payload": {"kind": "other", "label": "其他", "value": "", "query": "李雷"}},
            )
            self.assertEqual(other_response.status_code, 200)

            followup_response = await client.post(
                f"/api/v1/ask/sessions/{session_id}/turns",
                json={"content": "ou_direct_lei"},
            )
            self.assertEqual(followup_response.status_code, 200)
            payload = followup_response.json()
            self.assertEqual(payload["outputs"][0]["data"]["card_type"], "action_preview")
            self.assertEqual(payload["state_patch"]["pending_action_draft"]["resolved_target"]["value"], "ou_direct_lei")
            await client.aclose()

    async def test_text_cancel_clears_pending_message_draft_during_target_clarification(self) -> None:
        with patch("app.ask_tools.subprocess.run", side_effect=fake_lark_cli_subprocess):
            client = build_client()
            await client.post("/api/v1/ask/bindings/feishu/start", json={})
            await client.post("/api/v1/ask/bindings/feishu/complete", json={"device_code": "device-code-123"})
            session_response = await client.post(
                "/api/v1/ask/sessions",
                json={"skill_id": "hr_recruiting", "title": "Ask Copilot"},
            )
            session_id = session_response.json()["id"]

            first_response = await client.post(
                f"/api/v1/ask/sessions/{session_id}/turns",
                json={"content": "给李雷发送“你好”"},
            )
            self.assertEqual(first_response.status_code, 200)

            other_response = await client.post(
                f"/api/v1/ask/sessions/{session_id}/commands",
                json={"command": "select_option", "payload": {"kind": "other", "label": "其他", "value": "", "query": "李雷"}},
            )
            self.assertEqual(other_response.status_code, 200)

            cancel_response = await client.post(
                f"/api/v1/ask/sessions/{session_id}/turns",
                json={"content": "取消"},
            )
            self.assertEqual(cancel_response.status_code, 200)
            payload = cancel_response.json()
            self.assertEqual(payload["outputs"][0]["type"], "message")
            self.assertIn("已取消", payload["outputs"][0]["text"])
            self.assertEqual(payload["state_patch"]["pending_action_draft"], {})
            self.assertEqual(payload["state_patch"]["active_skill_state"], "completed")
            await client.aclose()

    async def test_message_request_with_direct_chat_id_returns_preview_without_target_selection(self) -> None:
        client = build_client()
        session_response = await client.post(
            "/api/v1/ask/sessions",
            json={"skill_id": "hr_recruiting", "title": "Ask Copilot"},
        )
        session_id = session_response.json()["id"]

        response = await client.post(
            f"/api/v1/ask/sessions/{session_id}/turns",
            json={"content": "把“你好”发到 oc_e68072397da0c76e8fe0e7fdd8c7f46e"},
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["outputs"][0]["data"]["card_type"], "action_preview")
        self.assertEqual(payload["state_patch"]["pending_action_draft"]["resolved_target"]["kind"], "chat")
        self.assertEqual(
            payload["state_patch"]["pending_action_draft"]["resolved_target"]["value"],
            "oc_e68072397da0c76e8fe0e7fdd8c7f46e",
        )
        await client.aclose()

    async def test_message_request_suggests_more_specific_target_when_no_candidates_are_found(self) -> None:
        def fake_no_match_subprocess(command, **kwargs):
            joined = " ".join(command)
            if " contact +search-user " in f" {joined} ":
                return subprocess.CompletedProcess(command, 0, stdout=json.dumps({"users": []}), stderr="")
            if " im +chat-search " in f" {joined} ":
                return subprocess.CompletedProcess(command, 0, stdout=json.dumps({"data": {"items": []}}), stderr="")
            return fake_lark_cli_subprocess(command, **kwargs)

        with patch("app.ask_tools.subprocess.run", side_effect=fake_no_match_subprocess):
            client = build_client()
            await client.post("/api/v1/ask/bindings/feishu/start", json={})
            await client.post("/api/v1/ask/bindings/feishu/complete", json={"device_code": "device-code-123"})
            session_response = await client.post(
                "/api/v1/ask/sessions",
                json={"skill_id": "hr_recruiting", "title": "Ask Copilot"},
            )
            session_id = session_response.json()["id"]

            response = await client.post(
                f"/api/v1/ask/sessions/{session_id}/turns",
                json={"content": "给李雷发送“你好”"},
            )

            self.assertEqual(response.status_code, 200)
            payload = response.json()
            self.assertIn("open_id / 会话 ID", payload["outputs"][0]["text"])
            self.assertEqual(payload["outputs"][0]["data"]["options"][-2]["kind"], "other")
            self.assertEqual(payload["outputs"][0]["data"]["options"][-1]["kind"], "cancel")
            await client.aclose()

    async def test_approve_plan_executes_against_selected_chat_target(self) -> None:
        captured_commands = []

        def fake_selected_chat_subprocess(command, **kwargs):
            captured_commands.append(command)
            joined = " ".join(command)
            if " im +messages-send " in f" {joined} " and "--chat-id" in command:
                chat_id = command[command.index("--chat-id") + 1]
                payload = {
                    "message_id": "om_selected_chat",
                    "chat_id": chat_id,
                    "create_time": "1711771200000",
                    "message_url": "https://feishu.cn/im/message/om_selected_chat",
                }
                return subprocess.CompletedProcess(command, 0, stdout=json.dumps(payload), stderr="")
            return fake_lark_cli_subprocess(command, **kwargs)

        with patch("app.ask_tools.subprocess.run", side_effect=fake_selected_chat_subprocess):
            client = build_client()
            await client.post("/api/v1/ask/bindings/feishu/start", json={})
            await client.post("/api/v1/ask/bindings/feishu/complete", json={"device_code": "device-code-123"})
            session_response = await client.post(
                "/api/v1/ask/sessions",
                json={"skill_id": "hr_recruiting", "title": "Ask Copilot"},
            )
            session_id = session_response.json()["id"]

            turn_response = await client.post(
                f"/api/v1/ask/sessions/{session_id}/turns",
                json={"content": "把“这个候选人不错”发到 Ai应用开发群"},
            )
            self.assertEqual(turn_response.status_code, 200)

            preview_response = await client.post(
                f"/api/v1/ask/sessions/{session_id}/commands",
                json={"command": "select_option", "payload": {"kind": "chat", "label": "Ai应用开发群", "value": "oc_ai_group", "query": "Ai应用开发群"}},
            )
            self.assertEqual(preview_response.status_code, 200)

            response = await client.post(
                f"/api/v1/ask/sessions/{session_id}/commands",
                json={"command": "approve_plan", "payload": {}},
            )

            self.assertEqual(response.status_code, 200)
            payload = response.json()
            self.assertEqual(payload["outputs"][0]["type"], "message")
            job_id = payload["outputs"][0]["data"]["job_id"]
            self.assertTrue(job_id)
            self.assertEqual(payload["outputs"][0]["data"]["job_status"], "pending")

            deadline = datetime.now(timezone.utc) + timedelta(seconds=2)
            job_payload = {"status": "pending"}
            while job_payload["status"] not in {"finished", "failed"} and datetime.now(timezone.utc) < deadline:
                job_response = await client.get(f"/api/v1/ask/jobs/{job_id}")
                self.assertEqual(job_response.status_code, 200)
                job_payload = job_response.json()
                await asyncio.sleep(0.05)

            self.assertEqual(job_payload["status"], "finished")
            self.assertEqual(job_payload["outputs"][0]["data"]["result"]["external_id"], "om_selected_chat")
            self.assertTrue(any("--chat-id" in cmd and "oc_ai_group" in cmd for cmd in captured_commands))
            await client.aclose()

    async def test_create_ask_session_returns_binding_fields(self) -> None:
        client = build_client()

        response = await client.post(
            "/api/v1/ask/sessions",
            json={"skill_id": "hr_recruiting", "title": "Recruiting copilot"},
        )

        self.assertEqual(response.status_code, 201)
        payload = response.json()
        self.assertEqual(payload["skill_id"], "hr_recruiting")
        self.assertEqual(payload["feishu_binding_status"], "UNBOUND")
        self.assertIn("required_scopes", payload)
        self.assertIn("missing_scopes", payload)
        self.assertIn("feishu_identity", payload)
        await client.aclose()

    async def test_feishu_binding_status_defaults_to_unbound(self) -> None:
        client = build_client()

        response = await client.get("/api/v1/ask/bindings/feishu/status")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["status"], "UNBOUND")
        self.assertEqual(payload["required_scopes"][0], "contact:user:search")
        self.assertIsNone(payload["identity"].get("user_open_id"))
        await client.aclose()

    async def test_feishu_binding_start_returns_device_flow_payload(self) -> None:
        with patch.dict(
            os.environ,
            {
                "EMATA_LARK_APP_ID": "cli_test_app",
                "EMATA_LARK_APP_SECRET": "cli_test_secret",
            },
            clear=False,
        ):
            with patch("app.ask_tools.subprocess.run", side_effect=fake_lark_cli_subprocess):
                client = build_client(preserve_model_env=True)

                response = await client.post("/api/v1/ask/bindings/feishu/start", json={})

                self.assertEqual(response.status_code, 200)
                payload = response.json()
                self.assertEqual(payload["status"], "PENDING")
                self.assertEqual(payload["verification_url"], "https://open.feishu.cn/device/verify")
                self.assertEqual(payload["device_code"], "device-code-123")
                await client.aclose()

    async def test_feishu_binding_complete_returns_active_identity_and_scopes(self) -> None:
        with patch.dict(
            os.environ,
            {
                "EMATA_LARK_APP_ID": "cli_test_app",
                "EMATA_LARK_APP_SECRET": "cli_test_secret",
            },
            clear=False,
        ):
            with patch("app.ask_tools.subprocess.run", side_effect=fake_lark_cli_subprocess):
                client = build_client(preserve_model_env=True)

                start_response = await client.post("/api/v1/ask/bindings/feishu/start", json={})
                self.assertEqual(start_response.status_code, 200)

                response = await client.post(
                    "/api/v1/ask/bindings/feishu/complete",
                    json={"device_code": "device-code-123"},
                )

                self.assertEqual(response.status_code, 200)
                payload = response.json()
                self.assertEqual(payload["status"], "ACTIVE")
                self.assertEqual(payload["identity"]["user_open_id"], "ou_test_hr")
                self.assertEqual(payload["missing_scopes"], [])
                await client.aclose()

    async def test_feishu_binding_start_is_idempotent_when_account_is_already_active(self) -> None:
        with patch.dict(
            os.environ,
            {
                "EMATA_LARK_APP_ID": "cli_test_app",
                "EMATA_LARK_APP_SECRET": "cli_test_secret",
            },
            clear=False,
        ):
            with patch("app.ask_tools.subprocess.run", side_effect=fake_lark_cli_subprocess):
                client = build_client()

                await client.post("/api/v1/ask/bindings/feishu/start", json={})
                await client.post(
                    "/api/v1/ask/bindings/feishu/complete",
                    json={"device_code": "device-code-123"},
                )

                response = await client.post("/api/v1/ask/bindings/feishu/start", json={})

                self.assertEqual(response.status_code, 200)
                payload = response.json()
                self.assertEqual(payload["status"], "ACTIVE")
                self.assertEqual(payload["identity"]["user_open_id"], "ou_test_hr")
                await client.aclose()

    async def test_feishu_binding_start_can_force_rebind_after_active_binding(self) -> None:
        with patch.dict(
            os.environ,
            {
                "EMATA_LARK_APP_ID": "cli_test_app",
                "EMATA_LARK_APP_SECRET": "cli_test_secret",
            },
            clear=False,
        ):
            with patch("app.ask_tools.subprocess.run", side_effect=fake_lark_cli_subprocess):
                client = build_client()

                await client.post("/api/v1/ask/bindings/feishu/start", json={})
                await client.post(
                    "/api/v1/ask/bindings/feishu/complete",
                    json={"device_code": "device-code-123"},
                )

                response = await client.post(
                    "/api/v1/ask/bindings/feishu/start",
                    json={"force_rebind": True},
                )

                self.assertEqual(response.status_code, 200)
                payload = response.json()
                self.assertEqual(payload["status"], "PENDING")
                self.assertEqual(payload["device_code"], "device-code-123")
                await client.aclose()

    async def test_resume_review_requests_position_before_candidate_analysis(self) -> None:
        client = build_client()
        session_response = await client.post(
            "/api/v1/ask/sessions",
            json={"skill_id": "hr_recruiting", "title": "Recruiting copilot"},
        )
        session_id = session_response.json()["id"]

        response = await client.post(
            f"/api/v1/ask/sessions/{session_id}/turns",
            json={"content": "帮我看简历"},
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["outputs"][0]["type"], "card")
        self.assertIn("岗位", payload["outputs"][0]["text"])
        self.assertEqual(payload["state_patch"]["active_skill_state"], "resume_intake")
        await client.aclose()

    async def test_ask_turn_answers_generic_knowledge_question_via_knowledge_qa(self) -> None:
        client = build_client()
        session_response = await client.post(
            "/api/v1/ask/sessions",
            json={"skill_id": "hr_recruiting", "title": "Recruiting copilot"},
        )
        session_id = session_response.json()["id"]

        response = await client.post(
            f"/api/v1/ask/sessions/{session_id}/turns",
            json={"content": "报销的额度是多少"},
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["outputs"][0]["type"], "message")
        self.assertIn("3000", payload["outputs"][0]["text"])
        self.assertEqual(payload["outputs"][0]["data"]["answer_mode"], "grounded_rag")
        self.assertEqual(payload["outputs"][0]["data"]["used_tools"], ["knowledge_search", "rerank", "answer_generate"])
        self.assertTrue(any(item["type"] == "citation" for item in payload["outputs"]))
        self.assertEqual(payload["state_patch"]["active_skill_state"], "knowledge_qa")
        await client.aclose()

    async def test_ask_turn_uses_generation_model_for_knowledge_answer_when_configured(self) -> None:
        def fake_generation_only(url, headers=None, json=None, timeout=None):
            self.assertIn("/chat/completions", url)
            self.assertEqual(json["model"], "qwen-flash")
            return httpx.Response(
                200,
                json={
                    "choices": [
                        {
                            "message": {
                                "content": "根据当前知识库证据，标准报销额度为 3000 元，超过后需要额外审批。"
                            }
                        }
                    ]
                },
                request=httpx.Request("POST", url),
            )

        with patch.dict(
            os.environ,
            {
                "EMATA_EMBEDDING_BASE_URL": "",
                "EMATA_EMBEDDING_API_KEY": "",
                "EMATA_MODEL_BASE_URL": "https://dashscope.aliyuncs.com/compatible-mode/v1",
                "EMATA_MODEL_API_KEY": "test-key",
                "EMATA_MODEL_NAME": "qwen-flash",
            },
            clear=False,
        ):
            with patch("app.rag.httpx.post", side_effect=fake_generation_only):
                client = build_client(preserve_model_env=True)
                session_response = await client.post(
                    "/api/v1/ask/sessions",
                    json={"skill_id": "hr_recruiting", "title": "Recruiting copilot"},
                )
                session_id = session_response.json()["id"]

                response = await client.post(
                    f"/api/v1/ask/sessions/{session_id}/turns",
                    json={"content": "报销的额度是多少"},
                )

                self.assertEqual(response.status_code, 200)
                payload = response.json()
                self.assertIn("3000", payload["outputs"][0]["text"])
                self.assertNotIn("当前可参考的知识内容是", payload["outputs"][0]["text"])
                await client.aclose()

    async def test_general_question_without_knowledge_hits_uses_general_llm_when_model_is_configured(self) -> None:
        def fake_generation_only(url, headers=None, json=None, timeout=None):
            self.assertIn("/chat/completions", url)
            return httpx.Response(
                200,
                json={
                    "choices": [
                        {
                            "message": {
                                "content": "多模态是指模型可以同时处理文本、图像、音频等多种模态信息。"
                            }
                        }
                    ]
                },
                request=httpx.Request("POST", url),
            )

        with patch.dict(
            os.environ,
            {
                "EMATA_EMBEDDING_BASE_URL": "",
                "EMATA_EMBEDDING_API_KEY": "",
                "EMATA_MODEL_BASE_URL": "https://dashscope.aliyuncs.com/compatible-mode/v1",
                "EMATA_MODEL_API_KEY": "test-key",
                "EMATA_MODEL_NAME": "qwen3.5-flash",
            },
            clear=False,
        ):
            with patch("app.rag.httpx.post", side_effect=fake_generation_only):
                client = build_client(preserve_model_env=True)
                session_response = await client.post(
                    "/api/v1/ask/sessions",
                    json={"skill_id": "hr_recruiting", "title": "Recruiting copilot"},
                )
                session_id = session_response.json()["id"]

                response = await client.post(
                    f"/api/v1/ask/sessions/{session_id}/turns",
                    json={"content": "多模态是什么"},
                )

                self.assertEqual(response.status_code, 200)
                payload = response.json()
                self.assertIn("多模态", payload["outputs"][0]["text"])
                self.assertEqual(payload["outputs"][0]["data"]["answer_mode"], "general_llm")
                self.assertEqual(payload["outputs"][0]["data"]["used_tools"], ["answer_generate"])
                await client.aclose()

    async def test_enterprise_question_without_hits_returns_knowledge_miss_instead_of_hr_fallback(self) -> None:
        client = build_client()
        session_response = await client.post(
            "/api/v1/ask/sessions",
            json={"skill_id": "hr_recruiting", "title": "Recruiting copilot"},
        )
        session_id = session_response.json()["id"]

        response = await client.post(
            f"/api/v1/ask/sessions/{session_id}/turns",
            json={"content": "公司的午休制度是什么"},
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["outputs"][0]["type"], "message")
        self.assertIn("没有在当前可访问知识库里找到足够证据", payload["outputs"][0]["text"])
        self.assertNotIn("HR Recruiting Skill", payload["outputs"][0]["text"])
        self.assertEqual(payload["state_patch"]["active_skill_state"], "knowledge_qa")
        await client.aclose()

    async def test_interview_schedule_without_explicit_time_returns_three_suggested_slots_after_binding(self) -> None:
        with patch.dict(
            os.environ,
            {
                "EMATA_LARK_APP_ID": "cli_test_app",
                "EMATA_LARK_APP_SECRET": "cli_test_secret",
            },
            clear=False,
        ):
            with patch("app.ask_tools.subprocess.run", side_effect=fake_lark_cli_subprocess):
                client = build_client()
                await client.post("/api/v1/ask/bindings/feishu/start", json={})
                await client.post(
                    "/api/v1/ask/bindings/feishu/complete",
                    json={"device_code": "device-code-123"},
                )
                session_response = await client.post(
                    "/api/v1/ask/sessions",
                    json={"skill_id": "hr_recruiting", "title": "Recruiting copilot"},
                )
                session_id = session_response.json()["id"]

                response = await client.post(
                    f"/api/v1/ask/sessions/{session_id}/turns",
                    json={"content": "帮我安排张三的一面"},
                )

                self.assertEqual(response.status_code, 200)
                payload = response.json()
                self.assertEqual(payload["outputs"][0]["type"], "card")
                self.assertIn("可选时间", payload["outputs"][0]["text"])
                self.assertEqual(len(payload["pending_commands"]), 3)
                self.assertTrue(all(item["type"] == "select_option" for item in payload["pending_commands"]))
                await client.aclose()

    async def test_confirm_plan_requires_binding_before_real_execution(self) -> None:
        client = build_client()
        session_response = await client.post(
            "/api/v1/ask/sessions",
            json={"skill_id": "hr_recruiting", "title": "Recruiting copilot"},
        )
        session_id = session_response.json()["id"]

        request_response = await client.post(
            f"/api/v1/ask/sessions/{session_id}/turns",
            json={"content": "那就约李雷明天下午 3 点开 30 分钟会，并把刚才的提纲发给他"},
        )
        self.assertEqual(request_response.status_code, 200)

        confirm_response = await client.post(
            f"/api/v1/ask/sessions/{session_id}/commands",
            json={"command": "confirm", "payload": {}},
        )

        self.assertEqual(confirm_response.status_code, 200)
        payload = confirm_response.json()
        self.assertEqual(payload["outputs"][0]["type"], "card")
        self.assertIn("绑定飞书", payload["outputs"][0]["text"])
        await client.aclose()

    async def test_confirm_plan_executes_real_lark_cli_after_binding(self) -> None:
        with patch.dict(
            os.environ,
            {
                "EMATA_LARK_APP_ID": "cli_test_app",
                "EMATA_LARK_APP_SECRET": "cli_test_secret",
            },
            clear=False,
        ):
            with patch("app.ask_tools.subprocess.run", side_effect=fake_lark_cli_subprocess):
                client = build_client()

                await client.post("/api/v1/ask/bindings/feishu/start", json={})
                complete_response = await client.post(
                    "/api/v1/ask/bindings/feishu/complete",
                    json={"device_code": "device-code-123"},
                )
                self.assertEqual(complete_response.status_code, 200)

                session_response = await client.post(
                    "/api/v1/ask/sessions",
                    json={"skill_id": "hr_recruiting", "title": "Recruiting copilot"},
                )
                session_id = session_response.json()["id"]

                request_response = await client.post(
                    f"/api/v1/ask/sessions/{session_id}/turns",
                    json={"content": "那就约李雷明天下午 3 点开 30 分钟会，并把刚才的提纲发给他"},
                )
                self.assertEqual(request_response.status_code, 200)

                confirm_response = await client.post(
                    f"/api/v1/ask/sessions/{session_id}/commands",
                    json={"command": "confirm", "payload": {}},
                )

                self.assertEqual(confirm_response.status_code, 200)
                payload = confirm_response.json()
                tool_results = [item for item in payload["outputs"] if item["type"] == "tool_result"]
                self.assertEqual(len(tool_results), 2)
                first_result = tool_results[0]["data"]["result"]
                second_result = tool_results[1]["data"]["result"]
                self.assertEqual(first_result["status"], "success")
                self.assertEqual(first_result["external_id"], "evt_123")
                self.assertEqual(second_result["status"], "success")
                self.assertEqual(second_result["external_id"], "om_li_lei_123")
                self.assertNotIn("mock-event", json.dumps(payload, ensure_ascii=False))
                self.assertNotIn("mock-message", json.dumps(payload, ensure_ascii=False))
                await client.aclose()

    async def test_confirm_plan_can_resolve_group_target_after_binding(self) -> None:
        with patch.dict(
            os.environ,
            {
                "EMATA_LARK_APP_ID": "cli_test_app",
                "EMATA_LARK_APP_SECRET": "cli_test_secret",
            },
            clear=False,
        ):
            with patch("app.ask_tools.subprocess.run", side_effect=fake_lark_cli_subprocess):
                client = build_client()

                await client.post("/api/v1/ask/bindings/feishu/start", json={})
                await client.post(
                    "/api/v1/ask/bindings/feishu/complete",
                    json={"device_code": "device-code-123"},
                )

                session_response = await client.post(
                    "/api/v1/ask/sessions",
                    json={"skill_id": "hr_recruiting", "title": "Recruiting copilot"},
                )
                session_id = session_response.json()["id"]

                request_response = await client.post(
                    f"/api/v1/ask/sessions/{session_id}/turns",
                    json={"content": "那就明天下午 3 点开 30 分钟会，并把刚才的提纲发到技术面试群"},
                )
                self.assertEqual(request_response.status_code, 200)

                confirm_response = await client.post(
                    f"/api/v1/ask/sessions/{session_id}/commands",
                    json={"command": "confirm", "payload": {}},
                )

                self.assertEqual(confirm_response.status_code, 200)
                payload = confirm_response.json()
                tool_results = [item for item in payload["outputs"] if item["type"] == "tool_result"]
                self.assertEqual(len(tool_results), 2)
                self.assertEqual(tool_results[1]["data"]["result"]["external_id"], "om_group_123")
                await client.aclose()

    async def test_collaboration_plan_extracts_chat_target_without_swallowing_whole_sentence(self) -> None:
        client = build_client()
        session_response = await client.post(
            "/api/v1/ask/sessions",
            json={"skill_id": "hr_recruiting", "title": "Recruiting copilot"},
        )
        session_id = session_response.json()["id"]

        response = await client.post(
            f"/api/v1/ask/sessions/{session_id}/turns",
            json={"content": "那就明天下午 3 点开 30 分钟会，并把刚才的提纲发到技术面试群"},
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        actions = payload["outputs"][0]["data"]["actions"]
        self.assertEqual(actions[0]["summary"], "创建内部协同会议")
        self.assertEqual(actions[1]["summary"], "发送“刚才的提纲”给 技术面试群")
        self.assertEqual(actions[1]["target"]["query"], "技术面试群")
        await client.aclose()

    async def test_collaboration_plan_parses_relative_time_and_duration(self) -> None:
        client = build_client()
        session_response = await client.post(
            "/api/v1/ask/sessions",
            json={"skill_id": "hr_recruiting", "title": "Recruiting copilot"},
        )
        session_id = session_response.json()["id"]

        with patch.object(
            HRRecruitingSkill,
            "_current_time",
            return_value=datetime(2026, 3, 31, 9, 0, tzinfo=timezone(timedelta(hours=8))),
        ):
            response = await client.post(
                f"/api/v1/ask/sessions/{session_id}/turns",
                json={"content": "那就明天下午 3 点开 30 分钟会，并把刚才的提纲发到技术面试群"},
            )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        actions = payload["outputs"][0]["data"]["actions"]
        self.assertEqual(actions[0]["start"], "2026-04-01T15:00:00+08:00")
        self.assertEqual(actions[0]["end"], "2026-04-01T15:30:00+08:00")
        await client.aclose()

    async def test_collaboration_plan_uses_explicit_message_body_instead_of_hardcoded_copy(self) -> None:
        client = build_client()
        session_response = await client.post(
            "/api/v1/ask/sessions",
            json={"skill_id": "hr_recruiting", "title": "Recruiting copilot"},
        )
        session_id = session_response.json()["id"]

        response = await client.post(
            f"/api/v1/ask/sessions/{session_id}/turns",
            json={"content": "那就明天下午 3 点开 30 分钟会，并把“这个候选人不错”发送到技术面试群"},
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        actions = payload["outputs"][0]["data"]["actions"]
        self.assertEqual(actions[1]["summary"], "发送“这个候选人不错”给 技术面试群")
        self.assertEqual(actions[1]["text"], "这个候选人不错")
        await client.aclose()

    async def test_collaboration_plan_reuses_last_knowledge_answer_when_user_refers_to_previous_conclusion(self) -> None:
        client = build_client()
        session_response = await client.post(
            "/api/v1/ask/sessions",
            json={"skill_id": "hr_recruiting", "title": "Recruiting copilot"},
        )
        session_id = session_response.json()["id"]

        first_response = await client.post(
            f"/api/v1/ask/sessions/{session_id}/turns",
            json={"content": "报销的额度是多少"},
        )
        self.assertEqual(first_response.status_code, 200)

        second_response = await client.post(
            f"/api/v1/ask/sessions/{session_id}/turns",
            json={"content": "那就明天下午 3 点开 30 分钟会，并把刚才的结论发到技术面试群"},
        )

        self.assertEqual(second_response.status_code, 200)
        payload = second_response.json()
        actions = payload["outputs"][0]["data"]["actions"]
        self.assertIn("3000", actions[1]["text"])
        self.assertEqual(actions[1]["target"]["query"], "技术面试群")
        await client.aclose()

    async def test_select_interview_slot_notifies_default_group_after_binding(self) -> None:
        with patch.dict(
            os.environ,
            {
                "EMATA_LARK_APP_ID": "cli_test_app",
                "EMATA_LARK_APP_SECRET": "cli_test_secret",
            },
            clear=False,
        ):
            with patch("app.ask_tools.subprocess.run", side_effect=fake_lark_cli_subprocess):
                client = build_client()

                await client.post("/api/v1/ask/bindings/feishu/start", json={})
                await client.post(
                    "/api/v1/ask/bindings/feishu/complete",
                    json={"device_code": "device-code-123"},
                )
                session_response = await client.post(
                    "/api/v1/ask/sessions",
                    json={"skill_id": "hr_recruiting", "title": "Recruiting copilot"},
                )
                session_id = session_response.json()["id"]

                request_response = await client.post(
                    f"/api/v1/ask/sessions/{session_id}/turns",
                    json={"content": "帮我安排张三的一面"},
                )
                self.assertEqual(request_response.status_code, 200)
                slot_payload = request_response.json()["pending_commands"][0]["payload"]

                select_response = await client.post(
                    f"/api/v1/ask/sessions/{session_id}/commands",
                    json={"command": "select_option", "payload": slot_payload},
                )
                self.assertEqual(select_response.status_code, 200)
                pending_plan = select_response.json()["state_patch"]["pending_action_plan"]
                self.assertIn("张三", pending_plan["actions"][1]["text"])
                self.assertIn(slot_payload["label"], pending_plan["actions"][1]["text"])

                confirm_response = await client.post(
                    f"/api/v1/ask/sessions/{session_id}/commands",
                    json={"command": "confirm", "payload": {}},
                )
                self.assertEqual(confirm_response.status_code, 200)
                payload = confirm_response.json()
                tool_results = [item for item in payload["outputs"] if item["type"] == "tool_result"]
                self.assertEqual(len(tool_results), 2)
                self.assertEqual(tool_results[1]["data"]["result"]["external_id"], "om_group_123")
                await client.aclose()

    async def test_select_interview_slot_resolves_external_contact_via_p2p_chat_when_available(self) -> None:
        with patch.dict(
            os.environ,
            {
                "EMATA_LARK_APP_ID": "cli_test_app",
                "EMATA_LARK_APP_SECRET": "cli_test_secret",
            },
            clear=False,
        ):
            with patch("app.ask_tools.subprocess.run", side_effect=fake_lark_cli_subprocess):
                client = build_client()

                await client.post("/api/v1/ask/bindings/feishu/start", json={})
                await client.post(
                    "/api/v1/ask/bindings/feishu/complete",
                    json={"device_code": "device-code-123"},
                )
                session_response = await client.post(
                    "/api/v1/ask/sessions",
                    json={"skill_id": "hr_recruiting", "title": "Recruiting copilot"},
                )
                session_id = session_response.json()["id"]

                request_response = await client.post(
                    f"/api/v1/ask/sessions/{session_id}/turns",
                    json={"content": "帮我安排李雷的一面"},
                )
                self.assertEqual(request_response.status_code, 200)
                slot_payload = request_response.json()["pending_commands"][0]["payload"]

                await client.post(
                    f"/api/v1/ask/sessions/{session_id}/commands",
                    json={"command": "select_option", "payload": slot_payload},
                )
                confirm_response = await client.post(
                    f"/api/v1/ask/sessions/{session_id}/commands",
                    json={"command": "confirm", "payload": {}},
                )
                self.assertEqual(confirm_response.status_code, 200)
                payload = confirm_response.json()
                resolution_messages = [item["text"] for item in payload["outputs"] if item["type"] == "message"]
                self.assertTrue(any("李雷" in text and "加入会议参会对象" in text for text in resolution_messages))
                await client.aclose()

    async def test_select_interview_slot_degrades_gracefully_when_external_contact_cannot_be_resolved(self) -> None:
        def fake_missing_contact_subprocess(command, **kwargs):
            joined = " ".join(command)
            if " contact +search-user " in f" {joined} " and "李雷" in joined:
                return subprocess.CompletedProcess(command, 0, stdout=json.dumps({"users": []}), stderr="")
            if " im +chat-search " in f" {joined} " and "李雷" in joined:
                return subprocess.CompletedProcess(command, 0, stdout=json.dumps({"data": {"items": []}}), stderr="")
            return fake_lark_cli_subprocess(command, **kwargs)

        with patch.dict(
            os.environ,
            {
                "EMATA_LARK_APP_ID": "cli_test_app",
                "EMATA_LARK_APP_SECRET": "cli_test_secret",
            },
            clear=False,
        ):
            with patch("app.ask_tools.subprocess.run", side_effect=fake_missing_contact_subprocess):
                client = build_client()

                await client.post("/api/v1/ask/bindings/feishu/start", json={})
                await client.post(
                    "/api/v1/ask/bindings/feishu/complete",
                    json={"device_code": "device-code-123"},
                )
                session_response = await client.post(
                    "/api/v1/ask/sessions",
                    json={"skill_id": "hr_recruiting", "title": "Recruiting copilot"},
                )
                session_id = session_response.json()["id"]

                request_response = await client.post(
                    f"/api/v1/ask/sessions/{session_id}/turns",
                    json={"content": "帮我安排李雷的一面"},
                )
                self.assertEqual(request_response.status_code, 200)
                slot_payload = request_response.json()["pending_commands"][0]["payload"]

                await client.post(
                    f"/api/v1/ask/sessions/{session_id}/commands",
                    json={"command": "select_option", "payload": slot_payload},
                )
                confirm_response = await client.post(
                    f"/api/v1/ask/sessions/{session_id}/commands",
                    json={"command": "confirm", "payload": {}},
                )
                self.assertEqual(confirm_response.status_code, 200)
                payload = confirm_response.json()
                tool_results = [item["data"]["result"] for item in payload["outputs"] if item["type"] == "tool_result"]
                resolution_messages = [item["text"] for item in payload["outputs"] if item["type"] == "message"]
                self.assertEqual(tool_results[0]["status"], "success")
                self.assertTrue(any("李雷" in text and "创建你的日程" in text for text in resolution_messages))
                await client.aclose()

    async def test_confirm_plan_returns_structured_tool_failure_when_message_send_execution_fails(self) -> None:
        def fake_message_send_failure(command, **kwargs):
            joined = " ".join(command)
            if " im +messages-send " in f" {joined} ":
                raise subprocess.CalledProcessError(
                    1,
                    command,
                    output="",
                    stderr="bot is not allowed to send message to this chat",
                )
            return fake_lark_cli_subprocess(command, **kwargs)

        with patch.dict(
            os.environ,
            {
                "EMATA_LARK_APP_ID": "cli_test_app",
                "EMATA_LARK_APP_SECRET": "cli_test_secret",
            },
            clear=False,
        ):
            with patch("app.ask_tools.subprocess.run", side_effect=fake_message_send_failure):
                client = build_client()

                await client.post("/api/v1/ask/bindings/feishu/start", json={})
                await client.post(
                    "/api/v1/ask/bindings/feishu/complete",
                    json={"device_code": "device-code-123"},
                )
                session_response = await client.post(
                    "/api/v1/ask/sessions",
                    json={"skill_id": "hr_recruiting", "title": "Recruiting copilot"},
                )
                session_id = session_response.json()["id"]

                request_response = await client.post(
                    f"/api/v1/ask/sessions/{session_id}/turns",
                    json={"content": "帮我安排张三的一面"},
                )
                self.assertEqual(request_response.status_code, 200)
                slot_payload = request_response.json()["pending_commands"][0]["payload"]

                await client.post(
                    f"/api/v1/ask/sessions/{session_id}/commands",
                    json={"command": "select_option", "payload": slot_payload},
                )
                confirm_response = await client.post(
                    f"/api/v1/ask/sessions/{session_id}/commands",
                    json={"command": "confirm", "payload": {}},
                )

                self.assertEqual(confirm_response.status_code, 200)
                payload = confirm_response.json()
                tool_results = [item["data"]["result"] for item in payload["outputs"] if item["type"] == "tool_result"]
                self.assertEqual(tool_results[0]["status"], "success")
                self.assertEqual(tool_results[1]["status"], "failed")
                self.assertEqual(tool_results[1]["error_code"], "feishu_cli_command_failed")
                followup_response = await client.post(
                    f"/api/v1/ask/sessions/{session_id}/turns",
                    json={"content": "帮我看简历"},
                )
                self.assertEqual(followup_response.status_code, 200)
                await client.aclose()

    async def test_confirm_plan_surfaces_invalid_receive_id_as_friendly_group_send_error(self) -> None:
        def fake_invalid_receive_id(command, **kwargs):
            joined = " ".join(command)
            if " im +messages-send " in f" {joined} ":
                raise subprocess.CalledProcessError(
                    1,
                    command,
                    output="",
                    stderr=json.dumps(
                        {
                            "ok": False,
                            "identity": "bot",
                            "error": {
                                "type": "api_error",
                                "code": 230001,
                                "message": "HTTP 400: Your request contains an invalid request parameter, ext=invalid receive_id",
                            },
                        },
                        ensure_ascii=False,
                    ),
                )
            return fake_lark_cli_subprocess(command, **kwargs)

        with patch.dict(
            os.environ,
            {
                "EMATA_LARK_APP_ID": "cli_test_app",
                "EMATA_LARK_APP_SECRET": "cli_test_secret",
            },
            clear=False,
        ):
            with patch("app.ask_tools.subprocess.run", side_effect=fake_invalid_receive_id):
                client = build_client()
                await client.post("/api/v1/ask/bindings/feishu/start", json={})
                await client.post(
                    "/api/v1/ask/bindings/feishu/complete",
                    json={"device_code": "device-code-123"},
                )
                session_response = await client.post(
                    "/api/v1/ask/sessions",
                    json={"skill_id": "hr_recruiting", "title": "Recruiting copilot"},
                )
                session_id = session_response.json()["id"]

                request_response = await client.post(
                    f"/api/v1/ask/sessions/{session_id}/turns",
                    json={"content": "那就明天下午 3 点开 30 分钟会，并把“这个候选人不错”发送到技术面试群"},
                )
                self.assertEqual(request_response.status_code, 200)

                confirm_response = await client.post(
                    f"/api/v1/ask/sessions/{session_id}/commands",
                    json={"command": "confirm", "payload": {}},
                )

                self.assertEqual(confirm_response.status_code, 200)
                payload = confirm_response.json()
                failed_results = [
                    item["data"]["result"]
                    for item in payload["outputs"]
                    if item["type"] == "tool_result" and item["data"]["result"]["status"] == "failed"
                ]
                self.assertTrue(any("机器人可能不在目标群里" in item["error_message"] for item in failed_results))
                await client.aclose()

    async def test_confirm_plan_surfaces_bot_out_of_chat_as_friendly_group_send_error(self) -> None:
        def fake_bot_out_of_chat(command, **kwargs):
            joined = " ".join(command)
            if " im +messages-send " in f" {joined} ":
                raise subprocess.CalledProcessError(
                    1,
                    command,
                    output="",
                    stderr="HTTP 400: Bot/User can NOT be out of the chat.",
                )
            return fake_lark_cli_subprocess(command, **kwargs)

        with patch.dict(
            os.environ,
            {
                "EMATA_LARK_APP_ID": "cli_test_app",
                "EMATA_LARK_APP_SECRET": "cli_test_secret",
            },
            clear=False,
        ):
            with patch("app.ask_tools.subprocess.run", side_effect=fake_bot_out_of_chat):
                client = build_client()
                await client.post("/api/v1/ask/bindings/feishu/start", json={})
                await client.post(
                    "/api/v1/ask/bindings/feishu/complete",
                    json={"device_code": "device-code-123"},
                )
                session_response = await client.post(
                    "/api/v1/ask/sessions",
                    json={"skill_id": "hr_recruiting", "title": "Recruiting copilot"},
                )
                session_id = session_response.json()["id"]

                request_response = await client.post(
                    f"/api/v1/ask/sessions/{session_id}/turns",
                    json={"content": "那就明天下午 3 点开 30 分钟会，并把“这个候选人不错”发送到技术面试群"},
                )
                self.assertEqual(request_response.status_code, 200)

                confirm_response = await client.post(
                    f"/api/v1/ask/sessions/{session_id}/commands",
                    json={"command": "confirm", "payload": {}},
                )

                self.assertEqual(confirm_response.status_code, 200)
                payload = confirm_response.json()
                failed_results = [
                    item["data"]["result"]
                    for item in payload["outputs"]
                    if item["type"] == "tool_result" and item["data"]["result"]["status"] == "failed"
                ]
                self.assertTrue(any("机器人当前不在这个群里" in item["error_message"] for item in failed_results))
                await client.aclose()

    async def test_confirm_plan_returns_service_error_when_lark_cli_execution_fails(self) -> None:
        client = build_client()

        with patch("app.services.ServiceContainer.run_ask_command", side_effect=RuntimeError("calendar create failed")):
            confirm_response = await client.post(
                "/api/v1/ask/sessions/ask-test/commands",
                json={"command": "confirm", "payload": {}},
            )

        self.assertEqual(confirm_response.status_code, 503)
        self.assertIn("calendar create failed", confirm_response.text)
        await client.aclose()


if __name__ == "__main__":
    unittest.main()
