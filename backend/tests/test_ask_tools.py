import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import MagicMock, patch
import subprocess

from app.ask_tools import FeishuBindingService, LarkCliError, LarkCliRunner, LarkCliTool
from app.core import FeishuBindingRecord, InMemoryStore, UserRecord


class LarkCliRunnerTestCase(unittest.TestCase):
    def test_base_command_falls_back_to_npx_when_global_lark_cli_shim_is_broken(self) -> None:
        runner = LarkCliRunner(executable="lark-cli")

        def fake_which(name: str) -> str | None:
            if name == "lark-cli.cmd":
                return "C:/Users/Hank/AppData/Roaming/npm/lark-cli.cmd"
            if name == "npx.cmd":
                return "C:/shim/npx.cmd"
            return None

        original_exists = Path.exists

        def fake_exists(path: Path) -> bool:
            if str(path).replace("\\", "/").endswith("node_modules/@larksuite/cli/scripts/run.js"):
                return False
            return original_exists(path)

        with patch("app.ask_tools.shutil.which", side_effect=fake_which):
            with patch("app.ask_tools.Path.exists", new=fake_exists):
                self.assertEqual(runner.base_command(), ["C:/shim/npx.cmd", "-y", "@larksuite/cli"])

    def test_base_command_prefers_global_lark_cli_even_when_configured_as_npx(self) -> None:
        runner = LarkCliRunner(executable="npx")

        def fake_which(name: str) -> str | None:
            if name == "lark-cli.cmd":
                return "C:/shim/lark-cli.cmd"
            if name == "npx.cmd":
                return "C:/shim/npx.cmd"
            return None

        original_exists = Path.exists

        def fake_exists(path: Path) -> bool:
            if str(path).replace("\\", "/").endswith("node_modules/@larksuite/cli/scripts/run.js"):
                return True
            return original_exists(path)

        with patch("app.ask_tools.shutil.which", side_effect=fake_which):
            with patch("app.ask_tools.Path.exists", new=fake_exists):
                self.assertEqual(runner.base_command(), ["C:/shim/lark-cli.cmd"])

    def test_base_command_prefers_cmd_shim_for_windows_global_install(self) -> None:
        runner = LarkCliRunner(executable="lark-cli")

        original_exists = Path.exists

        def fake_exists(path: Path) -> bool:
            if str(path).replace("\\", "/").endswith("node_modules/@larksuite/cli/scripts/run.js"):
                return True
            return original_exists(path)

        with patch("app.ask_tools.shutil.which", side_effect=lambda name: f"C:/shim/{name}" if name == "lark-cli.cmd" else None):
            with patch("app.ask_tools.Path.exists", new=fake_exists):
                self.assertEqual(runner.base_command(), ["C:/shim/lark-cli.cmd"])

    def test_base_command_prefers_cmd_shim_for_npx_on_windows(self) -> None:
        runner = LarkCliRunner(executable="npx")

        with patch("app.ask_tools.shutil.which", side_effect=lambda name: f"C:/shim/{name}" if name == "npx.cmd" else None):
            self.assertEqual(runner.base_command(), ["C:/shim/npx.cmd", "-y", "@larksuite/cli"])

    def test_run_subprocess_uses_utf8_decoding_for_cli_output(self) -> None:
        runner = LarkCliRunner()

        with patch("app.ask_tools.subprocess.run") as run_mock:
            run_mock.return_value.stdout = "{}"
            run_mock.return_value.stderr = ""
            run_mock.return_value.returncode = 0

            runner._run_subprocess(
                ["npx.cmd", "-y", "@larksuite/cli", "--version"],
                env={"PATH": "test"},
                input_text=None,
                json_expected=True,
            )

            kwargs = run_mock.call_args.kwargs
            self.assertEqual(kwargs["encoding"], "utf-8")
            self.assertEqual(kwargs["errors"], "replace")

    def test_run_subprocess_can_parse_structured_json_from_nonzero_exit(self) -> None:
        runner = LarkCliRunner()
        command = ["npx.cmd", "-y", "@larksuite/cli", "auth", "check"]
        error = subprocess.CalledProcessError(
            1,
            command,
            output='{"ok": false, "granted": ["contact:user:search"], "missing": ["im:message:send_as_bot"]}',
            stderr="",
        )

        with patch("app.ask_tools.subprocess.run", side_effect=error):
            payload = runner._run_subprocess(
                command,
                env={"PATH": "test"},
                input_text=None,
                json_expected=True,
                allow_json_error_result=True,
            )

        self.assertEqual(payload["granted"], ["contact:user:search"])
        self.assertEqual(payload["missing"], ["im:message:send_as_bot"])

    def test_ensure_initialized_repairs_missing_config_even_if_sentinel_exists(self) -> None:
        with TemporaryDirectory(prefix="lark-runner-") as tempdir:
            runner = LarkCliRunner(
                executable="npx",
                config_base_dir=tempdir,
            )
            user = UserRecord(
                id="user-admin",
                organization_id="org-acme",
                username="admin",
                display_name="Admin",
            )
            config_dir = Path(tempdir) / "org-acme" / "user-admin"
            config_dir.mkdir(parents=True, exist_ok=True)
            (config_dir / ".initialized").write_text("initialized\n", encoding="utf-8")

            with patch.dict(
                "os.environ",
                {
                    "EMATA_LARK_APP_ID": "app-id",
                    "EMATA_LARK_APP_SECRET": "app-secret",
                },
                clear=False,
            ):
                with patch.object(runner, "_run_subprocess", return_value={"ok": True}) as run_mock:
                    repaired_dir = runner.ensure_initialized(user)

            self.assertEqual(repaired_dir, config_dir)
            self.assertTrue(run_mock.called)


class FeishuBindingServiceTestCase(unittest.TestCase):
    def test_get_status_recovers_active_binding_from_existing_cli_config(self) -> None:
        with TemporaryDirectory(prefix="feishu-binding-") as tempdir:
            config_dir = Path(tempdir) / "org-acme" / "user-admin"
            config_dir.mkdir(parents=True, exist_ok=True)
            (config_dir / "config.json").write_text("{}", encoding="utf-8")

            class FakeRunner:
                def __init__(self, expected_dir: Path) -> None:
                    self.expected_dir = expected_dir
                    self.calls = []

                def config_dir_for(self, user: UserRecord) -> Path:
                    del user
                    return self.expected_dir

                def run(self, *, user: UserRecord, args, input_text=None, json_expected=True, allow_json_error_result=False):
                    del user, input_text, json_expected, allow_json_error_result
                    self.calls.append(args)
                    if args == ["auth", "status", "--verify"]:
                        return {
                            "identity": "user",
                            "userName": "Recovered User",
                            "userOpenId": "ou_recovered",
                            "scope": "contact:user:search search:docs:read",
                        }
                    if args[:3] == ["auth", "check", "--scope"]:
                        return {"granted": ["contact:user:search"], "missing": ["search:docs:read"]}
                    raise AssertionError(f"Unexpected args: {args}")

            store = InMemoryStore()
            user = store.users["user-admin"]
            service = FeishuBindingService(store=store, runner=FakeRunner(config_dir))

            payload = service.get_status(user)

            self.assertEqual(payload["status"], "ACTIVE")
            self.assertEqual(payload["identity"]["user_name"], "Recovered User")
            self.assertIn(user.id, store.feishu_bindings)

    def test_refresh_status_uses_cli_commands_supported_by_current_version(self) -> None:
        class FakeRunner:
            def __init__(self) -> None:
                self.calls = []

            def config_dir_for(self, user: UserRecord) -> Path:
                return Path("E:/Project/Agent/.runtime/lark-cli") / user.organization_id / user.id

            def run(self, *, user: UserRecord, args, input_text=None, json_expected=True, allow_json_error_result=False):
                del user, input_text, json_expected, allow_json_error_result
                self.calls.append(args)
                if args == ["auth", "status", "--verify"]:
                    return {
                        "identity": "user",
                        "userName": "Test User",
                        "userOpenId": "ou_test",
                        "scope": "contact:user:search search:docs:read",
                    }
                if args[:3] == ["auth", "check", "--scope"]:
                    return {"granted": ["contact:user:search"], "missing": ["search:docs:read"]}
                raise AssertionError(f"Unexpected args: {args}")

        store = InMemoryStore()
        user = store.users["user-admin"]
        record = FeishuBindingRecord(
            id="binding-test",
            user_id=user.id,
            organization_id=user.organization_id,
            status="ACTIVE",
            config_dir="E:/Project/Agent/.runtime/lark-cli/org-acme/user-admin",
        )
        store.feishu_bindings[user.id] = record
        service = FeishuBindingService(store=store, runner=FakeRunner())

        payload = service.get_status(user)

        self.assertEqual(payload["status"], "ACTIVE")
        self.assertEqual(payload["identity"]["user_name"], "Test User")
        self.assertIn(["auth", "status", "--verify"], service.runner.calls)
        self.assertTrue(
            any(call[:3] == ["auth", "check", "--scope"] for call in service.runner.calls)
        )
        self.assertEqual(payload["missing_scopes"], ["search:docs:read"])

    def test_get_status_marks_reauth_required_when_existing_config_cannot_refresh(self) -> None:
        with TemporaryDirectory(prefix="feishu-binding-") as tempdir:
            config_dir = Path(tempdir) / "org-acme" / "user-admin"
            config_dir.mkdir(parents=True, exist_ok=True)
            (config_dir / "config.json").write_text("{}", encoding="utf-8")

            class FailingRunner:
                def config_dir_for(self, user: UserRecord) -> Path:
                    del user
                    return config_dir

                def run(self, *, user: UserRecord, args, input_text=None, json_expected=True, allow_json_error_result=False):
                    del user, args, input_text, json_expected, allow_json_error_result
                    raise LarkCliError("feishu_cli_command_failed", "token expired")

            store = InMemoryStore()
            user = store.users["user-admin"]
            service = FeishuBindingService(store=store, runner=FailingRunner())

            payload = service.get_status(user)

            self.assertEqual(payload["status"], "REAUTH_REQUIRED")
            self.assertIn("重新授权", payload["hint"])

    def test_start_binding_returns_existing_active_status_without_force(self) -> None:
        class ActiveRunner:
            def __init__(self) -> None:
                self.calls = []

            def config_dir_for(self, user: UserRecord) -> Path:
                return Path("E:/Project/Agent/.runtime/lark-cli") / user.organization_id / user.id

            def run(self, *, user: UserRecord, args, input_text=None, json_expected=True, allow_json_error_result=False):
                del user, input_text, json_expected, allow_json_error_result
                self.calls.append(args)
                if args == ["auth", "status", "--verify"]:
                    return {
                        "identity": "user",
                        "userName": "Active User",
                        "userOpenId": "ou_active",
                        "scope": "contact:user:search",
                    }
                if args[:3] == ["auth", "check", "--scope"]:
                    return {"granted": ["contact:user:search"], "missing": ["search:docs:read"]}
                raise AssertionError(f"Unexpected args: {args}")

        store = InMemoryStore()
        user = store.users["user-admin"]
        record = FeishuBindingRecord(
            id="binding-test",
            user_id=user.id,
            organization_id=user.organization_id,
            status="ACTIVE",
            config_dir="E:/Project/Agent/.runtime/lark-cli/org-acme/user-admin",
        )
        store.feishu_bindings[user.id] = record
        runner = ActiveRunner()
        service = FeishuBindingService(store=store, runner=runner)

        payload = service.start_binding(user)

        self.assertEqual(payload["status"], "ACTIVE")
        self.assertFalse(any(call[:2] == ["auth", "login"] for call in runner.calls))

    def test_complete_binding_returns_pending_when_authorization_is_still_in_progress(self) -> None:
        class PendingRunner:
            def __init__(self) -> None:
                self.calls = []

            def config_dir_for(self, user: UserRecord) -> Path:
                return Path("E:/Project/Agent/.runtime/lark-cli") / user.organization_id / user.id

            def run(self, *, user: UserRecord, args, input_text=None, json_expected=True, allow_json_error_result=False):
                del user, input_text, json_expected, allow_json_error_result
                self.calls.append(args)
                if args[:2] == ["auth", "login"] and "--device-code" in args:
                    return {
                        "ok": False,
                        "error": {
                            "type": "authorization_pending",
                            "message": "authorization pending",
                        },
                    }
                raise AssertionError(f"Unexpected args: {args}")

        store = InMemoryStore()
        user = store.users["user-admin"]
        record = FeishuBindingRecord(
            id="binding-test",
            user_id=user.id,
            organization_id=user.organization_id,
            status="PENDING",
            device_code="device-code-123",
            verification_url="https://open.feishu.cn/device/verify",
            config_dir="E:/Project/Agent/.runtime/lark-cli/org-acme/user-admin",
        )
        store.feishu_bindings[user.id] = record
        service = FeishuBindingService(store=store, runner=PendingRunner())

        payload = service.complete_binding(user)

        self.assertEqual(payload["status"], "PENDING")
        self.assertIn("完成授权", payload["hint"])


class LarkCliToolTestCase(unittest.TestCase):
    def test_message_send_does_not_require_bot_scope_from_user_binding(self) -> None:
        binding_service = MagicMock()
        runner = MagicMock()
        runner.run.return_value = {
            "message_id": "om_test",
            "chat_id": "oc_test",
            "message_url": "https://feishu.cn/im/message/om_test",
        }
        tool = LarkCliTool(runner=runner, binding_service=binding_service)
        user = UserRecord(
            id="user-admin",
            organization_id="org-acme",
            username="admin",
            display_name="Admin",
        )

        result = tool.execute(
            {
                "capability": "message.send",
                "target": {"chat_id": "oc_test"},
                "text": "hello",
            },
            user=user,
        )

        binding_service.ensure_active.assert_called_once_with(user, scopes=[])
        self.assertEqual(result["external_id"], "om_test")

    def test_calendar_schedule_uses_current_cli_flags(self) -> None:
        binding_service = MagicMock()
        runner = MagicMock()
        runner.run.return_value = {
            "event_id": "evt_test",
            "event_url": "https://feishu.cn/calendar/event/evt_test",
        }
        tool = LarkCliTool(runner=runner, binding_service=binding_service)
        user = UserRecord(
            id="user-admin",
            organization_id="org-acme",
            username="admin",
            display_name="Admin",
        )

        result = tool.execute(
            {
                "capability": "calendar.schedule",
                "summary": "测试会议",
                "start": "2026-04-01T15:00:00+08:00",
                "end": "2026-04-01T15:30:00+08:00",
            },
            user=user,
        )

        args = runner.run.call_args.kwargs["args"]
        self.assertEqual(args[:2], ["calendar", "+create"])
        self.assertNotIn("--json", args)
        self.assertEqual(result["external_id"], "evt_test")

    def test_calendar_suggestions_use_duration_minutes_flag(self) -> None:
        binding_service = MagicMock()
        runner = MagicMock()
        runner.run.return_value = {"data": {"suggestions": []}}
        tool = LarkCliTool(runner=runner, binding_service=binding_service)
        user = UserRecord(
            id="user-admin",
            organization_id="org-acme",
            username="admin",
            display_name="Admin",
        )

        tool.execute(
            {
                "capability": "calendar.suggest_slots",
                "duration_minutes": 30,
            },
            user=user,
        )

        args = runner.run.call_args.kwargs["args"]
        self.assertIn("--duration-minutes", args)
        self.assertNotIn("--duration", args)
        self.assertIn("--format", args)

    def test_calendar_suggestions_parse_event_start_time_fields(self) -> None:
        binding_service = MagicMock()
        runner = MagicMock()
        runner.run.return_value = {
            "data": {
                "suggestions": [
                    {
                        "event_start_time": "2026-03-31T15:00:00+08:00",
                        "event_end_time": "2026-03-31T15:30:00+08:00",
                    }
                ]
            }
        }
        tool = LarkCliTool(runner=runner, binding_service=binding_service)
        user = UserRecord(
            id="user-admin",
            organization_id="org-acme",
            username="admin",
            display_name="Admin",
        )

        result = tool.execute(
            {
                "capability": "calendar.suggest_slots",
                "duration_minutes": 30,
            },
            user=user,
        )

        self.assertEqual(result["options"][0]["start"], "2026-03-31T15:00:00+08:00")
        self.assertEqual(result["options"][0]["end"], "2026-03-31T15:30:00+08:00")

    def test_message_send_uses_current_cli_flags(self) -> None:
        binding_service = MagicMock()
        runner = MagicMock()
        runner.run.return_value = {
            "message_id": "om_test",
            "message_url": "https://feishu.cn/im/message/om_test",
        }
        tool = LarkCliTool(runner=runner, binding_service=binding_service)
        user = UserRecord(
            id="user-admin",
            organization_id="org-acme",
            username="admin",
            display_name="Admin",
        )

        tool.execute(
            {
                "capability": "message.send",
                "target": {"user_id": "ou_test"},
                "text": "hello",
            },
            user=user,
        )

        args = runner.run.call_args.kwargs["args"]
        self.assertEqual(args[:2], ["im", "+messages-send"])
        self.assertIn("--as", args)
        self.assertIn("bot", args)
        self.assertNotIn("--json", args)

    def test_contact_resolve_uses_format_json(self) -> None:
        binding_service = MagicMock()
        runner = MagicMock()
        runner.run.return_value = {"users": [{"open_id": "ou_1", "name": "李雷"}]}
        tool = LarkCliTool(runner=runner, binding_service=binding_service)
        user = UserRecord(
            id="user-admin",
            organization_id="org-acme",
            username="admin",
            display_name="Admin",
        )

        result = tool.execute(
            {
                "capability": "contact.resolve",
                "query": "李雷",
            },
            user=user,
        )

        args = runner.run.call_args.kwargs["args"]
        self.assertIn("--format", args)
        self.assertIn("json", args)
        self.assertNotIn("--json", args)
        self.assertEqual(result["matches"][0]["open_id"], "ou_1")

    def test_chat_resolve_uses_current_cli_flags(self) -> None:
        binding_service = MagicMock()
        runner = MagicMock()
        runner.run.return_value = {
            "data": {
                "items": [
                    {
                        "chat_id": "oc_tech_interview",
                        "name": "鎶€鏈潰璇曠兢",
                    }
                ]
            }
        }
        tool = LarkCliTool(runner=runner, binding_service=binding_service)
        user = UserRecord(
            id="user-admin",
            organization_id="org-acme",
            username="admin",
            display_name="Admin",
        )

        result = tool.execute(
            {
                "capability": "chat.resolve",
                "query": "鎶€鏈潰璇曠兢",
            },
            user=user,
        )

        args = runner.run.call_args.kwargs["args"]
        self.assertEqual(args[:2], ["im", "+chat-search"])
        self.assertIn("--format", args)
        self.assertIn("json", args)
        self.assertEqual(result["matches"][0]["chat_id"], "oc_tech_interview")

    def test_chat_resolve_falls_back_to_private_or_external_search(self) -> None:
        binding_service = MagicMock()
        runner = MagicMock()
        runner.run.side_effect = [
            {"data": {"items": []}},
            {"data": {"items": []}},
        ]
        tool = LarkCliTool(runner=runner, binding_service=binding_service)
        user = UserRecord(
            id="user-admin",
            organization_id="org-acme",
            username="admin",
            display_name="Admin",
        )

        result = tool.execute(
            {
                "capability": "chat.resolve",
                "query": "李雷",
            },
            user=user,
        )

        self.assertEqual(result["matches"], [])
        self.assertEqual(runner.run.call_count, 2)
        second_args = runner.run.call_args_list[1].kwargs["args"]
        self.assertEqual(second_args[:2], ["im", "+chat-search"])
        self.assertIn("--search-types", second_args)
        self.assertIn("private,external", second_args)

    def test_chat_resolve_returns_private_or_external_chat_before_message_search(self) -> None:
        binding_service = MagicMock()
        runner = MagicMock()
        runner.run.side_effect = [
            {"data": {"items": []}},
            {
                "data": {
                    "items": [
                        {
                            "chat_id": "oc_external_li_lei",
                            "name": "李雷",
                            "chat_mode": "p2p",
                        }
                    ]
                }
            },
        ]
        tool = LarkCliTool(runner=runner, binding_service=binding_service)
        user = UserRecord(
            id="user-admin",
            organization_id="org-acme",
            username="admin",
            display_name="Admin",
        )

        result = tool.execute(
            {
                "capability": "chat.resolve",
                "query": "李雷",
            },
            user=user,
        )

        self.assertEqual(result["matches"][0]["chat_id"], "oc_external_li_lei")
        self.assertEqual(runner.run.call_count, 2)
        second_args = runner.run.call_args_list[1].kwargs["args"]
        self.assertEqual(second_args[:2], ["im", "+chat-search"])
        self.assertIn("--search-types", second_args)
        self.assertIn("private,external", second_args)

    def test_chat_resolve_does_not_fall_back_to_p2p_search_for_group_queries(self) -> None:
        binding_service = MagicMock()
        runner = MagicMock()
        runner.run.return_value = {"data": {"items": []}}
        tool = LarkCliTool(runner=runner, binding_service=binding_service)
        user = UserRecord(
            id="user-admin",
            organization_id="org-acme",
            username="admin",
            display_name="Admin",
        )

        result = tool.execute(
            {
                "capability": "chat.resolve",
                "query": "技术面试群",
            },
            user=user,
        )

        self.assertEqual(result["matches"], [])
        self.assertEqual(runner.run.call_count, 1)
        args = runner.run.call_args.kwargs["args"]
        self.assertEqual(args[:2], ["im", "+chat-search"])

    def test_doc_create_uses_current_cli_flags(self) -> None:
        binding_service = MagicMock()
        runner = MagicMock()
        runner.run.return_value = {"doc_id": "doc_test", "doc_url": "https://feishu.cn/docx/doc_test"}
        tool = LarkCliTool(runner=runner, binding_service=binding_service)
        user = UserRecord(
            id="user-admin",
            organization_id="org-acme",
            username="admin",
            display_name="Admin",
        )

        tool.execute(
            {
                "capability": "doc.create",
                "title": "测试文档",
                "markdown": "hello",
            },
            user=user,
        )

        args = runner.run.call_args.kwargs["args"]
        self.assertEqual(args[:2], ["docs", "+create"])
        self.assertNotIn("--json", args)

    def test_drive_search_uses_format_json(self) -> None:
        binding_service = MagicMock()
        runner = MagicMock()
        runner.run.return_value = {"data": []}
        tool = LarkCliTool(runner=runner, binding_service=binding_service)
        user = UserRecord(
            id="user-admin",
            organization_id="org-acme",
            username="admin",
            display_name="Admin",
        )

        tool.execute(
            {
                "capability": "drive.search",
                "query": "JD",
            },
            user=user,
        )

        args = runner.run.call_args.kwargs["args"]
        self.assertIn("--format", args)
        self.assertIn("json", args)
        self.assertNotIn("--json", args)


if __name__ == "__main__":
    unittest.main()
