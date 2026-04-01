import json
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from app.core import FeishuBindingRecord, UserRecord, make_id, utcnow


FEISHU_USER_REQUIRED_SCOPES = [
    "contact:user:search",
    "search:docs:read",
    "docx:document:readonly",
    "docx:document:create",
    "drive:file:download",
    "im:chat:read",
    "calendar:calendar.free_busy:read",
    "calendar:calendar.event:create",
    "calendar:calendar.event:update",
]

CAPABILITY_SCOPES = {
    "calendar.schedule": [
        "calendar:calendar.event:create",
        "calendar:calendar.event:update",
    ],
    "calendar.suggest_slots": ["calendar:calendar.free_busy:read"],
    "message.send": [],
    "contact.resolve": ["contact:user:search"],
    "chat.resolve": ["im:chat:read"],
    "doc.create": ["docx:document:create"],
    "drive.search": ["search:docs:read"],
    "drive.fetch": [],
}


class LarkCliError(RuntimeError):
    def __init__(self, code: str, message: str, *, details: Optional[Dict[str, Any]] = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details or {}


class BaseTool:
    def describe(self) -> Dict[str, Any]:
        return {"name": self.__class__.__name__}

    def validate(self, payload: Dict[str, Any]) -> None:
        if not isinstance(payload, dict):
            raise ValueError("tool_payload_invalid")

    def dry_run(self, payload: Dict[str, Any], *, user: Optional[UserRecord] = None) -> Dict[str, Any]:
        del user
        self.validate(payload)
        return {"status": "preview", "payload": payload}

    def execute(self, payload: Dict[str, Any], *, user: Optional[UserRecord] = None) -> Dict[str, Any]:
        del user
        self.validate(payload)
        return {"status": "executed", "tool": self.__class__.__name__, "payload": payload}

    def normalize(self, result: Dict[str, Any]) -> Dict[str, Any]:
        return result


class LarkCliRunner:
    def __init__(
        self,
        *,
        executable: Optional[str] = None,
        package: Optional[str] = None,
        brand: Optional[str] = None,
        config_base_dir: Optional[str] = None,
    ) -> None:
        self.executable = executable or os.getenv("EMATA_LARK_CLI_EXECUTABLE", "npx")
        self.package = package or os.getenv("EMATA_LARK_CLI_PACKAGE", "@larksuite/cli")
        self.brand = brand or os.getenv("EMATA_LARK_BRAND", "feishu")
        self.config_base_dir = Path(
            config_base_dir
            or os.getenv("EMATA_LARK_CLI_CONFIG_BASE_DIR", os.path.join(".", ".runtime", "lark-cli"))
        )

    def config_dir_for(self, user: UserRecord) -> Path:
        return self.config_base_dir / user.organization_id / user.id

    def base_command(self) -> List[str]:
        executable_name = Path(self.executable).name.lower()
        global_cli = self._resolve_healthy_global_lark_cli()
        if executable_name == "npx":
            if global_cli:
                return [global_cli]
        if executable_name in {"lark-cli", "lark-cli.exe", "lark-cli.cmd"}:
            if global_cli:
                return [global_cli]
            npx_cmd = shutil.which("npx.cmd") or shutil.which("npx")
            if npx_cmd:
                return [npx_cmd, "-y", self.package]
            resolved = shutil.which(self.executable) or self.executable
            return [resolved]
        resolved = self.executable
        if executable_name == "npx":
            resolved = shutil.which("npx.cmd") or shutil.which("npx") or self.executable
        return [resolved, "-y", self.package]

    def _resolve_healthy_global_lark_cli(self) -> Optional[str]:
        for candidate in ("lark-cli.cmd", "lark-cli", "lark-cli.exe"):
            resolved = shutil.which(candidate)
            if resolved and self._is_healthy_lark_cli(resolved):
                return resolved
        return None

    @staticmethod
    def _is_healthy_lark_cli(executable_path: str) -> bool:
        path = Path(executable_path)
        name = path.name.lower()
        if name == "lark-cli.exe":
            return path.exists()
        run_js = path.parent / "node_modules" / "@larksuite" / "cli" / "scripts" / "run.js"
        return run_js.exists()

    def ensure_initialized(self, user: UserRecord) -> Path:
        app_id = os.getenv("EMATA_LARK_APP_ID", "").strip()
        app_secret = os.getenv("EMATA_LARK_APP_SECRET", "").strip()
        if not app_id or not app_secret:
            raise LarkCliError(
                "feishu_cli_not_configured",
                "Feishu CLI credentials are not configured.",
            )

        config_dir = self.config_dir_for(user)
        config_dir.mkdir(parents=True, exist_ok=True)
        sentinel = config_dir / ".initialized"
        config_file = config_dir / "config.json"
        if sentinel.exists() and config_file.exists():
            return config_dir

        command = self.base_command() + [
            "config",
            "init",
            "--app-id",
            app_id,
            "--app-secret-stdin",
            "--brand",
            self.brand,
        ]
        self._run_subprocess(
            command,
            env=self._build_env(config_dir),
            input_text=app_secret + "\n",
            json_expected=False,
        )
        sentinel.write_text("initialized\n", encoding="utf-8")
        return config_dir

    def run(
        self,
        *,
        user: UserRecord,
        args: List[str],
        input_text: Optional[str] = None,
        json_expected: bool = True,
        allow_json_error_result: bool = False,
    ) -> Dict[str, Any]:
        config_dir = self.ensure_initialized(user)
        command = self.base_command() + args
        return self._run_subprocess(
            command,
            env=self._build_env(config_dir),
            input_text=input_text,
            json_expected=json_expected,
            allow_json_error_result=allow_json_error_result,
        )

    @staticmethod
    def _build_env(config_dir: Path) -> Dict[str, str]:
        env = os.environ.copy()
        env["LARKSUITE_CLI_CONFIG_DIR"] = str(config_dir)
        env["NO_COLOR"] = "1"
        return env

    def _run_subprocess(
        self,
        command: List[str],
        *,
        env: Dict[str, str],
        input_text: Optional[str],
        json_expected: bool,
        allow_json_error_result: bool = False,
    ) -> Dict[str, Any]:
        try:
            result = subprocess.run(
                command,
                check=True,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                input=input_text,
                env=env,
            )
        except FileNotFoundError as exc:
            raise LarkCliError("feishu_cli_not_found", "lark-cli is not installed or not available.") from exc
        except subprocess.CalledProcessError as exc:
            stderr = (exc.stderr or "").strip()
            stdout = (exc.stdout or "").strip()
            if json_expected and allow_json_error_result:
                structured_output = stdout or stderr
                if structured_output:
                    try:
                        parsed = json.loads(structured_output)
                    except json.JSONDecodeError:
                        parsed = None
                    if isinstance(parsed, dict):
                        return parsed
            raise LarkCliError(
                "feishu_cli_command_failed",
                stderr or stdout or "lark-cli command failed.",
                details={"returncode": exc.returncode, "stdout": stdout, "stderr": stderr},
            ) from exc

        stdout = (result.stdout or "").strip()
        if not json_expected:
            return {"ok": True, "stdout": stdout}
        if not stdout:
            return {}
        try:
            parsed = json.loads(stdout)
        except json.JSONDecodeError as exc:
            raise LarkCliError(
                "feishu_cli_result_invalid",
                "lark-cli returned non-JSON output.",
                details={"stdout": stdout},
            ) from exc
        if isinstance(parsed, dict):
            return parsed
        return {"data": parsed}


class FeishuBindingService:
    def __init__(self, *, store: Any, runner: LarkCliRunner) -> None:
        self.store = store
        self.runner = runner

    def required_scopes(self) -> List[str]:
        return list(FEISHU_USER_REQUIRED_SCOPES)

    def get_status(self, user: UserRecord) -> Dict[str, Any]:
        record = self.store.feishu_bindings.get(user.id)
        if record is None:
            config_dir = self.runner.config_dir_for(user)
            if (config_dir / "config.json").exists():
                recovered = FeishuBindingRecord(
                    id=make_id("binding"),
                    user_id=user.id,
                    organization_id=user.organization_id,
                    status="ACTIVE",
                    config_dir=str(config_dir),
                )
                try:
                    return self._refresh_status(user, recovered)
                except LarkCliError as exc:
                    return self._mark_reauth_required(recovered, exc)
            return self._status_payload(None)
        if record.status == "PENDING":
            return self._status_payload(record)
        if record.status in {"ACTIVE", "REAUTH_REQUIRED"}:
            try:
                return self._refresh_status(user, record)
            except LarkCliError as exc:
                return self._mark_reauth_required(record, exc)
        return self._status_payload(record)

    def start_binding(self, user: UserRecord, *, force_rebind: bool = False) -> Dict[str, Any]:
        current_status = self.get_status(user)
        if not force_rebind and current_status["status"] in {"ACTIVE", "PENDING"}:
            return current_status
        if force_rebind or current_status["status"] == "REAUTH_REQUIRED":
            self._clear_binding(user)

        payload = self.runner.run(
            user=user,
            args=[
                "auth",
                "login",
                "--json",
                "--scope",
                " ".join(self.required_scopes()),
                "--no-wait",
            ],
        )
        record = self.store.feishu_bindings.get(user.id) or FeishuBindingRecord(
            id=make_id("binding"),
            user_id=user.id,
            organization_id=user.organization_id,
            config_dir=str(self.runner.config_dir_for(user)),
        )
        record.status = "PENDING"
        record.config_dir = str(self.runner.config_dir_for(user))
        record.verification_url = payload.get("verification_url", "")
        record.device_code = payload.get("device_code", "")
        record.hint = payload.get("hint", "")
        record.expires_in = payload.get("expires_in")
        record.granted_scopes = []
        record.missing_scopes = list(self.required_scopes())
        record.checked_at = utcnow()
        record.updated_at = utcnow()
        self._save(record)
        return self._status_payload(record)

    def complete_binding(self, user: UserRecord, *, device_code: str = "") -> Dict[str, Any]:
        current_status = self.get_status(user)
        if current_status["status"] == "ACTIVE":
            return current_status
        record = self.store.feishu_bindings.get(user.id)
        resolved_device_code = (device_code or (record.device_code if record else "")).strip()
        if not resolved_device_code:
            raise ValueError("feishu_device_code_required")

        payload = self.runner.run(
            user=user,
            args=["auth", "login", "--device-code", resolved_device_code, "--json"],
            allow_json_error_result=True,
        )
        error = payload.get("error") if isinstance(payload, dict) else None
        if isinstance(error, dict):
            error_type = str(error.get("type") or "").strip()
            error_message = str(error.get("message") or "").strip()
            record = record or FeishuBindingRecord(
                id=make_id("binding"),
                user_id=user.id,
                organization_id=user.organization_id,
                config_dir=str(self.runner.config_dir_for(user)),
            )
            if error_type in {"authorization_pending", "slow_down"} or "pending" in error_message.lower():
                record.status = "PENDING"
                record.device_code = resolved_device_code
                record.hint = "请先在飞书完成授权，系统会继续检查绑定状态。"
                record.updated_at = utcnow()
                self._save(record)
                return self._status_payload(record)
            if error_type in {"expired_token", "device_code_expired"} or "expired" in error_message.lower():
                return self._mark_reauth_required(
                    record,
                    LarkCliError("feishu_binding_expired", error_message or "Feishu authorization expired."),
                    hint="这次飞书授权已经过期，请重新绑定或切换账号后再继续。",
                )
            raise LarkCliError(
                "feishu_cli_command_failed",
                error_message or "Feishu binding failed.",
            )
        record = record or FeishuBindingRecord(
            id=make_id("binding"),
            user_id=user.id,
            organization_id=user.organization_id,
            config_dir=str(self.runner.config_dir_for(user)),
        )
        record.status = "ACTIVE"
        record.device_code = resolved_device_code
        record.hint = ""
        self._save(record)
        return self._refresh_status(user, record)

    def disconnect(self, user: UserRecord) -> Dict[str, Any]:
        self._clear_binding(user)
        return self._status_payload(None)

    def ensure_active(self, user: UserRecord, *, scopes: Optional[List[str]] = None) -> Dict[str, Any]:
        status_payload = self.get_status(user)
        if status_payload["status"] != "ACTIVE":
            raise LarkCliError("feishu_binding_required", "Feishu account is not bound.")
        missing = list(status_payload["missing_scopes"])
        if scopes:
            granted = set(status_payload["granted_scopes"])
            missing = [scope for scope in scopes if scope not in granted]
        if missing:
            raise LarkCliError(
                "feishu_scope_missing",
                "Required Feishu permissions are missing.",
                details={"missing_scopes": missing},
            )
        return status_payload

    def _refresh_status(self, user: UserRecord, record: FeishuBindingRecord) -> Dict[str, Any]:
        status_payload = self.runner.run(user=user, args=["auth", "status", "--verify"])
        scope_payload = self.runner.run(
            user=user,
            args=[
                "auth",
                "check",
                "--scope",
                " ".join(self.required_scopes()),
            ],
            allow_json_error_result=True,
        )
        record.status = "ACTIVE"
        record.identity_type = status_payload.get("identity", "user")
        record.user_name = status_payload.get("userName", "")
        record.user_open_id = status_payload.get("userOpenId", "")
        record.granted_scopes = list(scope_payload.get("granted", status_payload.get("scope", [])))
        record.missing_scopes = list(scope_payload.get("missing") or [])
        record.hint = ""
        record.checked_at = utcnow()
        record.updated_at = utcnow()
        self._save(record)
        return self._status_payload(record)

    def _clear_binding(self, user: UserRecord) -> None:
        record = self.store.feishu_bindings.get(user.id)
        try:
            self.runner.run(user=user, args=["auth", "logout", "--json"])
        except LarkCliError:
            pass
        config_dir = Path((record.config_dir if record else "") or self.runner.config_dir_for(user))
        if config_dir.exists():
            shutil.rmtree(config_dir, ignore_errors=True)
        if record is not None:
            self.store.feishu_bindings.pop(user.id, None)
            if hasattr(self.store, "delete_feishu_binding"):
                self.store.delete_feishu_binding(record.id)

    def _mark_reauth_required(
        self,
        record: FeishuBindingRecord,
        exc: LarkCliError,
        *,
        hint: str = "",
    ) -> Dict[str, Any]:
        record.status = "REAUTH_REQUIRED"
        record.hint = hint or "当前飞书授权不可用，请重新授权或切换账号后再继续。"
        record.checked_at = utcnow()
        record.updated_at = utcnow()
        if not record.missing_scopes:
            record.missing_scopes = list(self.required_scopes())
        self._save(record)
        return self._status_payload(record)

    def _save(self, record: FeishuBindingRecord) -> None:
        self.store.feishu_bindings[record.user_id] = record
        if hasattr(self.store, "save_feishu_binding"):
            self.store.save_feishu_binding(record)

    def _status_payload(self, record: Optional[FeishuBindingRecord]) -> Dict[str, Any]:
        if record is None:
            return {
                "status": "UNBOUND",
                "verification_url": "",
                "device_code": "",
                "required_scopes": self.required_scopes(),
                "granted_scopes": [],
                "missing_scopes": self.required_scopes(),
                "identity": {"type": "", "user_open_id": None, "user_name": ""},
                "hint": "",
                "expires_in": None,
                "checked_at": "",
            }
        return {
            "status": record.status,
            "verification_url": record.verification_url,
            "device_code": record.device_code,
            "required_scopes": self.required_scopes(),
            "granted_scopes": list(record.granted_scopes),
            "missing_scopes": list(record.missing_scopes),
            "identity": {
                "type": record.identity_type,
                "user_open_id": record.user_open_id or None,
                "user_name": record.user_name,
            },
            "hint": record.hint,
            "expires_in": record.expires_in,
            "checked_at": record.checked_at,
        }


class LarkCliTool(BaseTool):
    ALLOWED_CAPABILITIES = set(CAPABILITY_SCOPES.keys())

    def __init__(self, *, runner: LarkCliRunner, binding_service: FeishuBindingService) -> None:
        self.runner = runner
        self.binding_service = binding_service

    def validate(self, payload: Dict[str, Any]) -> None:
        super().validate(payload)
        capability = payload.get("capability")
        if capability not in self.ALLOWED_CAPABILITIES:
            raise ValueError(f"unsupported_capability:{capability}")

    def dry_run(self, payload: Dict[str, Any], *, user: Optional[UserRecord] = None) -> Dict[str, Any]:
        self.validate(payload)
        capability = payload["capability"]
        return {
            "status": "preview",
            "tool": "lark_cli",
            "capability": capability,
            "summary": payload.get("summary", ""),
            "required_scopes": CAPABILITY_SCOPES.get(capability, []),
            "payload": payload,
            "identity_mode": "bot" if capability == "message.send" else "user",
        }

    def execute(self, payload: Dict[str, Any], *, user: Optional[UserRecord] = None) -> Dict[str, Any]:
        self.validate(payload)
        if user is None:
            raise ValueError("tool_user_required")
        capability = payload["capability"]
        self.binding_service.ensure_active(user, scopes=self._resolve_required_scopes(capability, payload))

        if capability == "calendar.schedule":
            result = self._execute_calendar_schedule(user=user, payload=payload)
        elif capability == "calendar.suggest_slots":
            result = self._execute_calendar_suggestions(user=user, payload=payload)
        elif capability == "message.send":
            result = self._execute_message_send(user=user, payload=payload)
        elif capability == "contact.resolve":
            result = self._execute_contact_resolve(user=user, payload=payload)
        elif capability == "chat.resolve":
            result = self._execute_chat_resolve(user=user, payload=payload)
        elif capability == "doc.create":
            result = self._execute_doc_create(user=user, payload=payload)
        elif capability == "drive.search":
            result = self._execute_drive_search(user=user, payload=payload)
        elif capability == "drive.fetch":
            result = self._execute_drive_fetch(user=user, payload=payload)
        else:
            raise ValueError(f"unsupported_capability:{capability}")
        return self.normalize(result)

    @staticmethod
    def _resolve_required_scopes(capability: str, payload: Dict[str, Any]) -> List[str]:
        if capability != "drive.fetch":
            return CAPABILITY_SCOPES.get(capability, [])
        source = (payload.get("source") or "").strip()
        if _is_doc_url(source):
            return ["docx:document:readonly"]
        return ["drive:file:download"]

    @staticmethod
    def normalize(result: Dict[str, Any]) -> Dict[str, Any]:
        if "status" not in result:
            result["status"] = "success"
        result.setdefault("summary", "")
        result.setdefault("result_link", "")
        result.setdefault("external_id", "")
        result.setdefault("error_code", "")
        result.setdefault("error_message", "")
        return result

    def _execute_calendar_schedule(self, *, user: UserRecord, payload: Dict[str, Any]) -> Dict[str, Any]:
        command = [
            "calendar",
            "+create",
            "--summary",
            payload.get("summary", "内部协同会议"),
            "--start",
            payload.get("start", ""),
            "--end",
            payload.get("end", ""),
        ]
        attendee_ids = payload.get("attendee_ids") or []
        if attendee_ids:
            command.extend(["--attendee-ids", ",".join(attendee_ids)])
        raw = self.runner.run(user=user, args=command)
        return {
            "status": "success",
            "summary": payload.get("summary", "已创建日程"),
            "result_link": raw.get("event_url", ""),
            "external_id": raw.get("event_id", ""),
            "raw": raw,
        }

    def _execute_calendar_suggestions(self, *, user: UserRecord, payload: Dict[str, Any]) -> Dict[str, Any]:
        duration_minutes = int(payload.get("duration_minutes", 30))
        command = [
            "calendar",
            "+suggestion",
            "--duration-minutes",
            str(duration_minutes),
            "--format",
            "json",
        ]
        raw = self.runner.run(user=user, args=command)
        suggestions = []
        for item in raw.get("data", {}).get("suggestions", [])[:3]:
            start = item.get("event_start_time") or item.get("start", "")
            end = item.get("event_end_time") or item.get("end", "")
            label = f"{self._display_time(start)} - {self._display_time(end)}".strip(" -")
            suggestions.append(
                {
                    "label": label or f"建议时段 {len(suggestions) + 1}",
                    "value": start,
                    "start": start,
                    "end": end,
                }
            )
        return {
            "status": "success",
            "summary": "已生成建议时间",
            "options": suggestions,
            "raw": raw,
        }

    def _execute_message_send(self, *, user: UserRecord, payload: Dict[str, Any]) -> Dict[str, Any]:
        command = ["im", "+messages-send", "--as", "bot"]
        target = payload.get("target", {})
        if target.get("chat_id"):
            command.extend(["--chat-id", target["chat_id"]])
        elif target.get("user_id"):
            command.extend(["--user-id", target["user_id"]])
        else:
            raise ValueError("message_target_missing")
        command.extend(["--text", payload.get("text", "")])
        raw = self.runner.run(user=user, args=command)
        return {
            "status": "success",
            "summary": payload.get("summary", "已发送消息"),
            "result_link": raw.get("message_url", ""),
            "external_id": raw.get("message_id", ""),
            "raw": raw,
        }

    def _execute_contact_resolve(self, *, user: UserRecord, payload: Dict[str, Any]) -> Dict[str, Any]:
        query = (payload.get("query") or payload.get("target") or "").strip()
        if not query:
            raise ValueError("contact_query_missing")
        raw = self.runner.run(
            user=user,
            args=["contact", "+search-user", "--query", query, "--format", "json"],
        )
        matches = raw.get("users")
        if matches is None:
            data = raw.get("data", raw)
            if isinstance(data, dict):
                matches = data.get("users", [])
            else:
                matches = data
        return {
            "status": "success",
            "summary": f"已检索联系人 {query}",
            "matches": matches or [],
            "raw": raw,
        }

    def _execute_chat_resolve(self, *, user: UserRecord, payload: Dict[str, Any]) -> Dict[str, Any]:
        query = (payload.get("query") or payload.get("target") or "").strip()
        if not query:
            raise ValueError("chat_query_missing")
        raw = self.runner.run(
            user=user,
            args=["im", "+chat-search", "--query", query, "--format", "json"],
        )
        data = raw.get("data", raw)
        matches: Any = []
        if isinstance(data, dict):
            matches = data.get("items")
            if matches is None:
                matches = data.get("chats", [])
        elif isinstance(data, list):
            matches = data
        should_try_private_or_external_fallback = not self._looks_like_group_query(query)
        if not matches and should_try_private_or_external_fallback:
            scoped_raw = self.runner.run(
                user=user,
                args=["im", "+chat-search", "--query", query, "--search-types", "private,external", "--format", "json"],
            )
            scoped_data = scoped_raw.get("data", scoped_raw)
            if isinstance(scoped_data, dict):
                matches = scoped_data.get("items")
                if matches is None:
                    matches = scoped_data.get("chats", [])
            elif isinstance(scoped_data, list):
                matches = scoped_data
            if matches:
                raw = scoped_raw
        return {
            "status": "success",
            "summary": f"已检索会话 {query}",
            "matches": matches or [],
            "raw": raw,
        }

    @staticmethod
    def _looks_like_group_query(query: str) -> bool:
        normalized = (query or "").strip()
        return normalized.endswith("群") or normalized.endswith("群聊")

    def _execute_doc_create(self, *, user: UserRecord, payload: Dict[str, Any]) -> Dict[str, Any]:
        raw = self.runner.run(
            user=user,
            args=[
                "docs",
                "+create",
                "--title",
                payload.get("title", "EMATA 文档"),
                "--markdown",
                payload.get("markdown", ""),
            ],
        )
        return {
            "status": "success",
            "summary": payload.get("summary", payload.get("title", "已生成文档")),
            "result_link": raw.get("doc_url", ""),
            "external_id": raw.get("doc_id", ""),
            "raw": raw,
        }

    def _execute_drive_search(self, *, user: UserRecord, payload: Dict[str, Any]) -> Dict[str, Any]:
        query = (payload.get("query") or "").strip()
        if not query:
            raise ValueError("drive_search_query_missing")
        raw = self.runner.run(
            user=user,
            args=["docs", "+search", "--query", query, "--format", "json"],
        )
        return {
            "status": "success",
            "summary": f"已检索飞书文档 {query}",
            "items": raw.get("data", raw),
            "raw": raw,
        }

    def _execute_drive_fetch(self, *, user: UserRecord, payload: Dict[str, Any]) -> Dict[str, Any]:
        source = (payload.get("source") or "").strip()
        if not source:
            raise ValueError("drive_fetch_source_missing")
        if _is_doc_url(source):
            raw = self.runner.run(
                user=user,
                args=["docs", "+fetch", "--doc", source, "--format", "json"],
            )
            return {
                "status": "success",
                "summary": "已读取飞书文档",
                "result_link": raw.get("doc_url", source),
                "external_id": raw.get("doc_id", ""),
                "content": raw.get("markdown", raw.get("content", "")),
                "title": raw.get("title", ""),
                "source_type": "doc",
                "raw": raw,
            }

        file_token = _extract_drive_file_token(source)
        if not file_token:
            raise ValueError("unsupported_drive_source")
        file_name = payload.get("file_name") or f"{file_token}.pdf"
        output_dir = Path(tempfile.mkdtemp(prefix="emata-feishu-drive-"))
        output_path = output_dir / file_name
        self.runner.run(
            user=user,
            args=[
                "drive",
                "+download",
                "--file-token",
                file_token,
                "--output",
                str(output_path),
            ],
            json_expected=False,
        )
        return {
            "status": "success",
            "summary": "已下载飞书文件",
            "result_link": source,
            "external_id": file_token,
            "local_path": str(output_path),
            "title": file_name,
            "source_type": _guess_source_type(file_name),
        }

    @staticmethod
    def _display_time(value: str) -> str:
        if "T" not in value:
            return value
        date_part, time_part = value.split("T", 1)
        time_part = time_part.split("+", 1)[0].split("Z", 1)[0]
        return f"{date_part} {time_part[:5]}"


class ResumeFetchTool(BaseTool):
    def __init__(self, *, lark_cli_tool: LarkCliTool) -> None:
        self.lark_cli_tool = lark_cli_tool

    def execute(self, payload: Dict[str, Any], *, user: Optional[UserRecord] = None) -> Dict[str, Any]:
        self.validate(payload)
        if user is None:
            raise ValueError("tool_user_required")
        source = (payload.get("source") or "").strip()
        candidate_name = (payload.get("candidate_name") or "").strip()
        if source:
            return self.lark_cli_tool.execute(
                {"capability": "drive.fetch", "source": source, "file_name": payload.get("file_name", "")},
                user=user,
            )
        if candidate_name:
            search_result = self.lark_cli_tool.execute(
                {"capability": "drive.search", "query": candidate_name},
                user=user,
            )
            return {
                "status": "candidate_search_only",
                "summary": f"已检索候选人 {candidate_name} 的飞书资料",
                "items": search_result.get("items", []),
            }
        raise ValueError("resume_source_missing")


class ResumeParseTool(BaseTool):
    def __init__(self, *, parse_callback: Optional[Callable[..., Dict[str, Any]]] = None) -> None:
        self.parse_callback = parse_callback

    def execute(self, payload: Dict[str, Any], *, user: Optional[UserRecord] = None) -> Dict[str, Any]:
        del user
        self.validate(payload)
        if self.parse_callback is None:
            raise ValueError("resume_parser_unavailable")
        local_path = payload.get("local_path", "")
        content = payload.get("content", "")
        source_type = payload.get("source_type", "")
        return self.parse_callback(local_path=local_path, content=content, source_type=source_type)


class KnowledgeSearchTool(BaseTool):
    def __init__(self, search_callback: Optional[Callable[..., Dict[str, Any]]] = None) -> None:
        self.search_callback = search_callback

    def execute(self, payload: Dict[str, Any], *, user: Optional[UserRecord] = None) -> Dict[str, Any]:
        self.validate(payload)
        if self.search_callback is None:
            return {"items": [], "trace": {"backend_mode": "none", "query": payload.get("query", "")}}
        if user is None:
            raise ValueError("tool_user_required")
        return self.search_callback(user=user, query=payload.get("query", ""), limit=payload.get("limit", 3))


class AnswerGenerationTool(BaseTool):
    def __init__(self, generation_provider: Optional[Any] = None) -> None:
        self.generation_provider = generation_provider

    def execute(self, payload: Dict[str, Any], *, user: Optional[UserRecord] = None) -> Dict[str, Any]:
        del user
        self.validate(payload)
        if self.generation_provider is None or getattr(self.generation_provider, "mode", "disabled") != "openai-compatible":
            return {
                "status": "unavailable",
                "mode": payload.get("mode", "extractive_fallback"),
                "reason": getattr(self.generation_provider, "reason", "generation_provider_not_configured"),
                "answer": "",
            }
        mode = payload.get("mode", "grounded")
        try:
            if mode == "general":
                answer = self.generation_provider.generate_general_answer(
                    question=payload.get("question", ""),
                )
            else:
                answer = self.generation_provider.generate_grounded_answer(
                    question=payload.get("question", ""),
                    contexts=payload.get("contexts", []),
                )
        except Exception as exc:
            return {
                "status": "failed",
                "mode": mode,
                "reason": f"generation_failed:{exc.__class__.__name__}",
                "answer": "",
                "error_message": str(exc),
            }
        return {
            "status": "success",
            "mode": "general_llm" if mode == "general" else "llm_rag",
            "reason": "generated",
            "answer": answer,
            "model": getattr(self.generation_provider, "model", ""),
        }


class RerankTool(BaseTool):
    def __init__(self, rerank_provider: Optional[Any] = None) -> None:
        self.rerank_provider = rerank_provider

    def execute(self, payload: Dict[str, Any], *, user: Optional[UserRecord] = None) -> Dict[str, Any]:
        del user
        self.validate(payload)
        items = payload.get("items", [])
        query = payload.get("query", "")
        if not items:
            return {"status": "success", "items": [], "mode": "empty"}
        if self.rerank_provider is None:
            return {"status": "success", "items": items, "mode": "noop"}

        documents = [
            f"{item.get('title', '')}\n{item.get('snippet', '')}"
            for item in items
        ]
        try:
            rankings = self.rerank_provider.rerank(
                query=query,
                documents=documents,
                top_n=min(len(documents), payload.get("top_n", len(documents))),
            )
        except Exception as exc:
            return {
                "status": "failed",
                "items": items,
                "mode": "fallback",
                "reason": f"rerank_failed:{exc.__class__.__name__}",
                "error_message": str(exc),
            }

        reranked_items = []
        for rank in rankings:
            index = rank.get("index", 0)
            if 0 <= index < len(items):
                item = dict(items[index])
                item["rerank_score"] = rank.get("score", 0.0)
                reranked_items.append(item)
        if not reranked_items:
            reranked_items = items
        return {
            "status": "success",
            "items": reranked_items,
            "mode": getattr(self.rerank_provider, "mode", "fallback"),
        }


class DocGenerateTool(BaseTool):
    def __init__(self, *, lark_cli_tool: LarkCliTool) -> None:
        self.lark_cli_tool = lark_cli_tool

    def execute(self, payload: Dict[str, Any], *, user: Optional[UserRecord] = None) -> Dict[str, Any]:
        self.validate(payload)
        return self.lark_cli_tool.execute(
            {
                "capability": "doc.create",
                "title": payload.get("title", "EMATA 文档"),
                "markdown": payload.get("markdown", ""),
                "summary": payload.get("summary", payload.get("title", "已生成文档")),
            },
            user=user,
        )


def build_tool_registry(
    *,
    binding_service: FeishuBindingService,
    runner: LarkCliRunner,
    search_callback: Optional[Callable[..., Dict[str, Any]]] = None,
    parse_callback: Optional[Callable[..., Dict[str, Any]]] = None,
    generation_provider: Optional[Any] = None,
    rerank_provider: Optional[Any] = None,
) -> Dict[str, BaseTool]:
    lark_cli_tool = LarkCliTool(runner=runner, binding_service=binding_service)
    return {
        "lark_cli": lark_cli_tool,
        "resume_fetch": ResumeFetchTool(lark_cli_tool=lark_cli_tool),
        "resume_parse": ResumeParseTool(parse_callback=parse_callback),
        "knowledge_search": KnowledgeSearchTool(search_callback=search_callback),
        "answer_generate": AnswerGenerationTool(generation_provider=generation_provider),
        "rerank": RerankTool(rerank_provider=rerank_provider),
        "doc_generate": DocGenerateTool(lark_cli_tool=lark_cli_tool),
    }


def _extract_drive_file_token(source: str) -> str:
    match = re.search(r"/drive/file/([A-Za-z0-9_\\-]+)", source)
    if match:
        return match.group(1)
    return ""


def _is_doc_url(source: str) -> bool:
    return any(token in source for token in ("/docx/", "/docs/", "/wiki/"))


def _guess_source_type(file_name: str) -> str:
    suffix = Path(file_name).suffix.lower().lstrip(".")
    if suffix in {"pdf", "docx", "txt", "md"}:
        return suffix
    return "pdf"
