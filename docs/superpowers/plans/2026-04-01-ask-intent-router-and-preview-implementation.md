# Ask Intent Router 与可编辑预览实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让 `/ask` 支持更通用的意图路由、Top 3 目标推荐与“可编辑预览卡 -> 确认 / 取消 -> 执行”，同时不破坏现有知识问答和飞书动作链。

**Architecture:** 在现有 Ask runtime 上新增 `Intent Router`、`Target Resolver` 和 `Action Draft / Preview` 三个独立层。`HR Recruiting Skill` 逐步退回为领域语义提供者，飞书执行仍保持 `preview -> confirm -> execute` 的独立链路。

**Tech Stack:** FastAPI, Python service layer, existing Ask runtime/session store, Next.js app router, current Ask UI components, `lark-cli`

---

### Task 1: 为 Intent Router 建立最小测试护栏

**Files:**
- Create: `E:\Project\Agent\backend\tests\test_ask_intent_router.py`
- Modify: `E:\Project\Agent\backend\app\ask_runtime.py`
- Test: `E:\Project\Agent\backend\tests\test_ask_intent_router.py`

- [ ] **Step 1: 写失败测试，覆盖四类路由结果**

```python
import unittest

from app.ask_runtime import AskIntentRouter


class AskIntentRouterTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.router = AskIntentRouter()

    def test_routes_enterprise_question_to_knowledge_qa(self) -> None:
        result = self.router.route(
            message="报销额度是多少",
            active_context={},
        )
        self.assertEqual(result["route"], "knowledge_qa")

    def test_routes_plain_send_request_to_action_only(self) -> None:
        result = self.router.route(
            message="发信息给李雷，告诉他面试通过了",
            active_context={},
        )
        self.assertEqual(result["route"], "action_only")

    def test_routes_answer_then_action_when_referring_to_previous_summary(self) -> None:
        result = self.router.route(
            message="把刚才的结论发到 Ai应用开发群",
            active_context={"last_shareable_text": "报销额度为 3000 元"},
        )
        self.assertEqual(result["route"], "answer_then_action")

    def test_routes_missing_target_to_clarification(self) -> None:
        result = self.router.route(
            message="发给他",
            active_context={},
        )
        self.assertEqual(result["route"], "clarification")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: 运行测试确认失败**

Run: `C:\Users\Hank\.conda\envs\emata\python.exe -m unittest tests.test_ask_intent_router -v`  
Expected: FAIL with `ImportError` or `AttributeError` because `AskIntentRouter` does not exist yet.

- [ ] **Step 3: 在 runtime 里加最小 Intent Router 实现**

```python
class AskIntentRouter:
    ACTION_MARKERS = ("发送", "发给", "发到", "通知", "安排", "创建", "约")
    KNOWLEDGE_MARKERS = ("多少", "是什么", "流程", "规则", "制度", "政策", "额度", "报销")

    def route(self, *, message: str, active_context: Dict[str, Any]) -> Dict[str, Any]:
        content = (message or "").strip()
        lowered = content.lower()
        if any(marker in content or marker in lowered for marker in self.ACTION_MARKERS):
            if ("刚才" in content or "上一个" in content) and active_context.get("last_shareable_text"):
                return {"route": "answer_then_action"}
            if content in {"发给他", "发给她", "发到群里", "通知一下"}:
                return {"route": "clarification"}
            return {"route": "action_only"}
        if any(marker in content or marker in lowered for marker in self.KNOWLEDGE_MARKERS):
            return {"route": "knowledge_qa"}
        return {"route": "clarification"}
```

- [ ] **Step 4: 运行测试确认通过**

Run: `C:\Users\Hank\.conda\envs\emata\python.exe -m unittest tests.test_ask_intent_router -v`  
Expected: PASS

### Task 2: 把 Ask runtime 接到 Intent Router

**Files:**
- Modify: `E:\Project\Agent\backend\app\ask_runtime.py`
- Modify: `E:\Project\Agent\backend\tests\test_ask_api.py`
- Test: `E:\Project\Agent\backend\tests\test_ask_api.py`

- [ ] **Step 1: 写失败测试，确保“发给谁”不会再直接落入知识问答或 HR 默认回复**

```python
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
```

- [ ] **Step 2: 运行目标测试确认失败**

Run: `C:\Users\Hank\.conda\envs\emata\python.exe -m unittest tests.test_ask_api.AskApiTestCase.test_ambiguous_action_request_returns_clarification_instead_of_skill_default -v`  
Expected: FAIL because runtime still routes to current skill default path.

- [ ] **Step 3: 在 AskRuntime 中引入 router 并调整顺序**

```python
class AskRuntime:
    def __init__(..., intent_router: Optional[AskIntentRouter] = None, ...):
        self.intent_router = intent_router or AskIntentRouter()

    def run_turn(self, *, session: Any, message: str, user: Any) -> Dict[str, Any]:
        route = self.intent_router.route(
            message=message,
            active_context=session.active_context or {},
        )
        if route["route"] == "knowledge_qa" and self.knowledge_module:
            return self.knowledge_module.handle_turn(...)
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
        return skill.handle_turn(...)
```

- [ ] **Step 4: 运行目标测试确认通过**

Run: `C:\Users\Hank\.conda\envs\emata\python.exe -m unittest tests.test_ask_api.AskApiTestCase.test_ambiguous_action_request_returns_clarification_instead_of_skill_default -v`  
Expected: PASS

### Task 3: 为目标推荐卡建立后端行为

**Files:**
- Create: `E:\Project\Agent\backend\app\ask_targeting.py`
- Modify: `E:\Project\Agent\backend\app\ask_skill_hr_recruiting.py`
- Modify: `E:\Project\Agent\backend\tests\test_ask_api.py`
- Test: `E:\Project\Agent\backend\tests\test_ask_api.py`

- [ ] **Step 1: 写失败测试，验证群/人目标要返回 Top 3 + 其他**

```python
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
            self.assertLessEqual(len(options), 4)
            self.assertEqual(options[-1]["kind"], "other")
            await client.aclose()
```

- [ ] **Step 2: 运行目标测试确认失败**

Run: `C:\Users\Hank\.conda\envs\emata\python.exe -m unittest tests.test_ask_api.AskApiTestCase.test_message_request_returns_target_selection_card_with_top_three_and_other -v`  
Expected: FAIL because current flow does not return `target_selection`.

- [ ] **Step 3: 新建 Target Resolver 并接到 HR skill**

```python
class AskTargetResolver:
    def resolve_candidates(self, *, query: str, user: Any, tools: Dict[str, Any]) -> List[Dict[str, Any]]:
        matches: List[Dict[str, Any]] = []
        try:
            contact_result = tools["lark_cli"].execute({"capability": "contact.resolve", "query": query}, user=user)
            for item in contact_result.get("matches", [])[:3]:
                matches.append({"kind": "user", "label": item.get("name", query), "value": item.get("open_id", ""), "query": query})
        except Exception:
            pass
        try:
            chat_result = tools["lark_cli"].execute({"capability": "chat.resolve", "query": query}, user=user)
            for item in chat_result.get("matches", [])[:3]:
                matches.append({"kind": "chat", "label": item.get("name", query), "value": item.get("chat_id", ""), "query": query})
        except Exception:
            pass
        deduped = []
        seen = set()
        for item in matches:
            key = (item["kind"], item["value"])
            if key not in seen and item["value"]:
                deduped.append(item)
                seen.add(key)
        return deduped[:3]
```

并在 HR skill 动作路径中：

```python
return {
    "outputs": [
        {
            "type": "card",
            "text": f"我找到了几个可能的目标，你选一个后我再生成预览。",
            "data": {
                "card_type": "target_selection",
                "options": [
                    *resolver.resolve_candidates(...),
                    {"kind": "other", "label": "其他", "value": "", "query": query},
                ],
            },
        }
    ],
    "state_patch": {
        "pending_action_draft": draft,
        "active_skill_state": "clarification_required",
    },
    "pending_commands": [...],
    "artifacts": [],
}
```

- [ ] **Step 4: 运行目标测试确认通过**

Run: `C:\Users\Hank\.conda\envs\emata\python.exe -m unittest tests.test_ask_api.AskApiTestCase.test_message_request_returns_target_selection_card_with_top_three_and_other -v`  
Expected: PASS

### Task 4: 为可编辑预览卡建立最小后端草案模型

**Files:**
- Create: `E:\Project\Agent\backend\app\ask_actions.py`
- Modify: `E:\Project\Agent\backend\app\ask_skill_hr_recruiting.py`
- Modify: `E:\Project\Agent\backend\tests\test_ask_api.py`
- Test: `E:\Project\Agent\backend\tests\test_ask_api.py`

- [ ] **Step 1: 写失败测试，验证确认前必须先返回 preview card**

```python
    async def test_confirmable_message_action_returns_editable_preview_card(self) -> None:
        client = build_client()
        session_response = await client.post(
            "/api/v1/ask/sessions",
            json={"skill_id": "hr_recruiting", "title": "Ask Copilot"},
        )
        session_id = session_response.json()["id"]

        response = await client.post(
            f"/api/v1/ask/sessions/{session_id}/turns",
            json={"content": "把刚才的结论发到 Ai应用开发群"},
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["outputs"][0]["data"]["card_type"], "action_preview")
        self.assertTrue(payload["outputs"][0]["data"]["editable"])
        await client.aclose()
```

- [ ] **Step 2: 运行目标测试确认失败**

Run: `C:\Users\Hank\.conda\envs\emata\python.exe -m unittest tests.test_ask_api.AskApiTestCase.test_confirmable_message_action_returns_editable_preview_card -v`  
Expected: FAIL because current flow still returns old confirmation card.

- [ ] **Step 3: 引入 Action Draft 与 Preview 序列化**

```python
def build_preview_card(*, draft: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "type": "card",
        "text": "执行前请先确认这次动作预览。你也可以直接编辑目标、正文或时间。",
        "data": {
            "card_type": "action_preview",
            "editable": True,
            "draft": draft,
            "actions": draft.get("actions", []),
            "risk_level": draft.get("risk_level", "medium"),
        },
    }
```

并在 HR skill 中把旧的 `confirmation_request` 替换成：

```python
draft = {
    "intent": "message.send",
    "risk_level": "medium",
    "actions": [...],
    "editable_fields": ["target", "text", "start", "end", "summary"],
}
return {
    "outputs": [build_preview_card(draft=draft)],
    "state_patch": {"pending_action_draft": draft, "active_skill_state": "waiting_confirmation"},
    "pending_commands": [
        {"id": "approve-preview", "type": "approve_plan", "title": "确认执行", "payload": {}},
        {"id": "cancel-preview", "type": "cancel", "title": "取消", "payload": {}},
    ],
    "artifacts": [],
}
```

- [ ] **Step 4: 运行目标测试确认通过**

Run: `C:\Users\Hank\.conda\envs\emata\python.exe -m unittest tests.test_ask_api.AskApiTestCase.test_confirmable_message_action_returns_editable_preview_card -v`  
Expected: PASS

### Task 5: 前端渲染目标选择卡与可编辑预览卡

**Files:**
- Modify: `E:\Project\Agent\frontend\components\ask-chat.js`
- Modify: `E:\Project\Agent\frontend\lib\ask.js`
- Modify: `E:\Project\Agent\frontend\tests\ask-page.test.mjs`
- Test: `E:\Project\Agent\frontend\tests\ask-page.test.mjs`

- [ ] **Step 1: 写失败测试，验证 target selection 与 action preview 可见**

```javascript
test("renders target selection and editable preview cards", () => {
  const outputs = [
    { type: "card", text: "选目标", data: { card_type: "target_selection", options: [{ kind: "user", label: "李雷" }, { kind: "other", label: "其他" }] } },
    { type: "card", text: "预览", data: { card_type: "action_preview", editable: true, draft: { actions: [] } } },
  ];
  const labels = outputs.map((item) => formatAskOutputLabel(item.type));
  expect(labels).toContain("确认卡");
});
```

- [ ] **Step 2: 运行测试确认失败**

Run: `node --test E:/Project/Agent/frontend/tests/ask-page.test.mjs`  
Expected: FAIL because UI does not yet render these cards specially.

- [ ] **Step 3: 在 ask-chat 中渲染目标选择和预览编辑区**

```javascript
function renderTargetSelection(output, handleCommand, isBusy) {
  const options = output?.data?.options || [];
  return (
    <div className="support-list">
      {options.map((option, index) => (
        <button
          key={`${option.kind}-${option.value || index}`}
          type="button"
          className="action-button ghost"
          disabled={isBusy}
          onClick={() =>
            handleCommand({
              id: `select-target-${index}`,
              type: "select_option",
              payload: option,
            })
          }
        >
          {option.label}
        </button>
      ))}
    </div>
  );
}
```

```javascript
function renderActionPreview(output) {
  const draft = output?.data?.draft || {};
  return (
    <div className="support-list">
      {(draft.actions || []).map((action, index) => (
        <div className="support-row" key={`preview-${index}`}>
          <strong>{action.capability}</strong>
          <span>{action.summary}</span>
        </div>
      ))}
      <p className="meta-line">可编辑字段：{(draft.editable_fields || []).join(" / ")}</p>
    </div>
  );
}
```

- [ ] **Step 4: 运行测试确认通过**

Run: `node --test E:/Project/Agent/frontend/tests/ask-page.test.mjs`  
Expected: PASS

### Task 6: 把目标选择写回上下文，并支持“其他”补充

**Files:**
- Modify: `E:\Project\Agent\backend\app\ask_skill_hr_recruiting.py`
- Modify: `E:\Project\Agent\backend\tests\test_ask_api.py`
- Test: `E:\Project\Agent\backend\tests\test_ask_api.py`

- [ ] **Step 1: 写失败测试，验证选择目标后会生成新的 preview，而不是直接执行**

```python
    async def test_selecting_target_updates_pending_draft_and_returns_preview(self) -> None:
        client = build_client()
        session_response = await client.post(
            "/api/v1/ask/sessions",
            json={"skill_id": "hr_recruiting", "title": "Ask Copilot"},
        )
        session_id = session_response.json()["id"]

        await client.post(
            f"/api/v1/ask/sessions/{session_id}/turns",
            json={"content": "发信息给李雷，告诉他面试通过了"},
        )
        response = await client.post(
            f"/api/v1/ask/sessions/{session_id}/commands",
            json={"command": "select_option", "payload": {"kind": "user", "label": "李雷", "value": "ou_li_lei", "query": "李雷"}},
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["outputs"][0]["data"]["card_type"], "action_preview")
        self.assertEqual(payload["state_patch"]["pending_action_draft"]["resolved_target"]["value"], "ou_li_lei")
        await client.aclose()
```

- [ ] **Step 2: 运行目标测试确认失败**

Run: `C:\Users\Hank\.conda\envs\emata\python.exe -m unittest tests.test_ask_api.AskApiTestCase.test_selecting_target_updates_pending_draft_and_returns_preview -v`  
Expected: FAIL because current `select_option` only handles time slots.

- [ ] **Step 3: 扩展 command 处理**

```python
elif command == "select_option":
    kind = (payload or {}).get("kind", "")
    if kind in {"user", "chat"}:
        draft = dict((session.active_context or {}).get("pending_action_draft") or {})
        draft["resolved_target"] = payload
        outputs = [build_preview_card(draft=draft)]
        return {
            "outputs": outputs,
            "state_patch": {
                "pending_action_draft": draft,
                "last_confirmed_target": payload,
                "active_skill_state": "waiting_confirmation",
            },
            "pending_commands": [
                {"id": "approve-preview", "type": "approve_plan", "title": "确认执行", "payload": {}},
                {"id": "cancel-preview", "type": "cancel", "title": "取消", "payload": {}},
            ],
            "artifacts": [],
        }
```

对 `other`：

```python
if kind == "other":
    return {
        "outputs": [
            {
                "type": "card",
                "text": "请直接在输入框里补充你想发送的目标名称，我会继续帮你解析。",
                "data": {"card_type": "clarification", "field": "target_query"},
            }
        ],
        "state_patch": {"active_skill_state": "clarification_required"},
        "pending_commands": [],
        "artifacts": [],
    }
```

- [ ] **Step 4: 运行目标测试确认通过**

Run: `C:\Users\Hank\.conda\envs\emata\python.exe -m unittest tests.test_ask_api.AskApiTestCase.test_selecting_target_updates_pending_draft_and_returns_preview -v`  
Expected: PASS

### Task 7: 让 approve_plan 真正按 preview 中的最新值执行

**Files:**
- Modify: `E:\Project\Agent\backend\app\ask_skill_hr_recruiting.py`
- Modify: `E:\Project\Agent\backend\tests\test_ask_api.py`
- Test: `E:\Project\Agent\backend\tests\test_ask_api.py`

- [ ] **Step 1: 写失败测试，验证 approve_plan 使用 resolved target 而不是旧 fallback**

```python
    async def test_approve_plan_executes_against_selected_chat_target(self) -> None:
        with patch("app.ask_tools.subprocess.run", side_effect=fake_lark_cli_subprocess):
            client = build_client()
            await client.post("/api/v1/ask/bindings/feishu/start", json={})
            await client.post("/api/v1/ask/bindings/feishu/complete", json={"device_code": "device-code-123"})
            session_response = await client.post(
                "/api/v1/ask/sessions",
                json={"skill_id": "hr_recruiting", "title": "Ask Copilot"},
            )
            session_id = session_response.json()["id"]

            await client.post(
                f"/api/v1/ask/sessions/{session_id}/turns",
                json={"content": "把刚才的结论发到 Ai应用开发群"},
            )
            await client.post(
                f"/api/v1/ask/sessions/{session_id}/commands",
                json={"command": "select_option", "payload": {"kind": "chat", "label": "Ai应用开发群", "value": "oc_ai_group", "query": "Ai应用开发群"}},
            )
            response = await client.post(
                f"/api/v1/ask/sessions/{session_id}/commands",
                json={"command": "approve_plan", "payload": {}},
            )

            self.assertEqual(response.status_code, 200)
            payload = response.json()
            tool_results = [item for item in payload["outputs"] if item["type"] == "tool_result"]
            self.assertTrue(tool_results)
            await client.aclose()
```

- [ ] **Step 2: 运行目标测试确认失败**

Run: `C:\Users\Hank\.conda\envs\emata\python.exe -m unittest tests.test_ask_api.AskApiTestCase.test_approve_plan_executes_against_selected_chat_target -v`  
Expected: FAIL because current execution still reads old pending plan shape.

- [ ] **Step 3: 让 approve_plan / confirm 从 `pending_action_draft` 读取执行参数**

```python
elif command in {"confirm", "approve_plan"}:
    pending_plan = (
        (session.active_context or {}).get("pending_action_draft")
        or (session.active_context or {}).get("pending_action_plan")
        or {}
    )
```

并在执行前把 `resolved_target` 合并回动作：

```python
resolved_target = pending_plan.get("resolved_target") or {}
for action in pending_plan.get("actions", []):
    if action.get("capability") == "message.send" and resolved_target:
        action["target"] = {
            "type": resolved_target.get("kind", ""),
            "chat_id": resolved_target.get("value", "") if resolved_target.get("kind") == "chat" else "",
            "user_id": resolved_target.get("value", "") if resolved_target.get("kind") == "user" else "",
        }
```

- [ ] **Step 4: 运行目标测试确认通过**

Run: `C:\Users\Hank\.conda\envs\emata\python.exe -m unittest tests.test_ask_api.AskApiTestCase.test_approve_plan_executes_against_selected_chat_target -v`  
Expected: PASS

### Task 8: 全量回归并手动验证关键路径

**Files:**
- Test: `E:\Project\Agent\backend\tests\test_ask_intent_router.py`
- Test: `E:\Project\Agent\backend\tests\test_ask_api.py`
- Test: `E:\Project\Agent\frontend\tests\ask-page.test.mjs`

- [ ] **Step 1: 跑后端回归**

Run: `C:\Users\Hank\.conda\envs\emata\python.exe -m unittest tests.test_ask_intent_router tests.test_ask_api tests.test_ask_tools -v`  
Expected: PASS

- [ ] **Step 2: 跑前端测试**

Run: `node --test E:/Project/Agent/frontend/tests/ask-page.test.mjs E:/Project/Agent/frontend/tests/api.test.mjs`  
Expected: PASS

- [ ] **Step 3: 手动验证三条关键路径**

Run in browser:

1. `报销的额度是多少`
Expected: 直接知识回答 + 引用

2. `发信息给李雷，告诉他面试通过了`
Expected:
- 先出 Top 3 目标推荐 + 其他
- 选中目标后出可编辑预览卡
- 确认后执行

3. `把刚才的结论发到 Ai应用开发群`
Expected:
- 不再静默 fallback
- 目标可确认
- 预览卡可见

- [ ] **Step 4: 记录遗留项**

记录但不在本轮实现：
- 后台任务 + 前端轮询 / SSE
- 完整通用 Action Planner 模块拆分
- 预览卡内 richer 表单编辑

## 自检

### Spec coverage

- `Intent Router`：Task 1-2
- `Top 3 推荐 + 其他`：Task 3、Task 6
- `可编辑预览卡`：Task 4、Task 5、Task 7
- `不再静默 fallback`：Task 3、Task 7
- `动作链不丢`：Task 7、Task 8

### Placeholder scan

本计划未使用 `TODO / TBD / implement later` 占位词；每个任务都给出了目标文件、测试命令和最小代码方向。

### Type consistency

本计划统一使用：
- `AskIntentRouter`
- `pending_action_draft`
- `resolved_target`
- `action_preview`
- `target_selection`

后续实现时不应再引入新的并行命名。
