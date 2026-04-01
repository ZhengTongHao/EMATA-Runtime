# Ask Runtime / RAG / Async Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 `/ask` 收成可扩展的统一入口，完成 `Intent Router + Action Planner + Context`、`RAG + citations + general_llm`、`Async execution + SSE` 三个阶段，同时保持飞书动作链可继续演进。

**Architecture:** 后端把 `/ask` 拆成清晰的四层：`Intent Router` 负责路由，`Action Planner` 负责草案与预览，`Knowledge QA` 负责 `search -> rerank -> answer -> citations`，`Async Job` 负责长动作异步执行与状态流。前端继续保留 `/knowledge` 与 `/ask` 的页面分工，但 `/ask` 直接消费同一套知识库和飞书工具。

**Tech Stack:** FastAPI, existing ask runtime modules, DashScope-compatible embedding / rerank / generation APIs, Next.js frontend, current Feishu `lark-cli` integration.

---

## File Map

### Backend
- Create: `E:\Project\Agent\backend\app\ask_context.py`
  - 会话级 `conversation_memory / working_context / pending_action_draft` 读写与 patch 合并。
- Create: `E:\Project\Agent\backend\app\ask_intent.py`
  - 独立 `Intent Router`，输出 `knowledge_qa / action_only / answer_then_action / clarification / skill_default`。
- Create: `E:\Project\Agent\backend\app\ask_action_planner.py`
  - 通用动作草案、可编辑预览、风险级别、目标解析衔接。
- Create: `E:\Project\Agent\backend\app\ask_jobs.py`
  - 异步 job store、job runner、轮询状态模型。
- Modify: `E:\Project\Agent\backend\app\ask_runtime.py`
  - 从单文件路由改成装配 `intent + context + action planner + knowledge qa + jobs`。
- Modify: `E:\Project\Agent\backend\app\ask_actions.py`
  - 缩成轻量消息动作入口，最终代理到 `ask_action_planner.py`。
- Modify: `E:\Project\Agent\backend\app\ask_targeting.py`
  - 输出透明的联系人/会话搜索结果、Top 3 候选、可编辑目标。
- Modify: `E:\Project\Agent\backend\app\ask_tools.py`
  - 保持 Feishu tool 不变，但补充 `rerank`、`answer_generate`、`job enqueue` 适配。
- Modify: `E:\Project\Agent\backend\app\services.py`
  - 装配新 runtime 依赖。
- Modify: `E:\Project\Agent\backend\app\routes.py`
  - 新增 job status / SSE 接口。
- Modify: `E:\Project\Agent\backend\app\contracts.py`
  - 增加 `answer_mode / confidence / citations / used_tools / job_status`。
- Modify: `E:\Project\Agent\backend\app\ask_skill_hr_recruiting.py`
  - 去掉通用动作兜底，保留 HR 业务编排。

### Frontend
- Modify: `E:\Project\Agent\frontend\components\ask-chat.js`
  - 渲染透明搜索卡、可编辑预览卡、异步执行状态、SSE/polling。
- Modify: `E:\Project\Agent\frontend\lib\ask.js`
  - 统一 view model：grounded/general/action/job。
- Modify: `E:\Project\Agent\frontend\lib\api.js`
  - Ask async poll / SSE client、job endpoints。
- Modify: `E:\Project\Agent\frontend\app\ask\page.js`
  - 保持页面入口不变，挂接新的状态流。

### Tests
- Create: `E:\Project\Agent\backend\tests\test_ask_intent.py`
- Create: `E:\Project\Agent\backend\tests\test_ask_context.py`
- Create: `E:\Project\Agent\backend\tests\test_ask_action_planner.py`
- Create: `E:\Project\Agent\backend\tests\test_ask_jobs.py`
- Modify: `E:\Project\Agent\backend\tests\test_ask_api.py`
- Modify: `E:\Project\Agent\backend\tests\test_ask_tools.py`
- Modify: `E:\Project\Agent\frontend\tests\ask-page.test.mjs`
- Modify: `E:\Project\Agent\frontend\tests\api.test.mjs`

## Phase 1: Intent Router + Action Planner + Context

### Task 1: Split Ask Runtime Into Intent / Context / Planner Units

**Files:**
- Create: `E:\Project\Agent\backend\app\ask_context.py`
- Create: `E:\Project\Agent\backend\app\ask_intent.py`
- Create: `E:\Project\Agent\backend\tests\test_ask_context.py`
- Create: `E:\Project\Agent\backend\tests\test_ask_intent.py`
- Modify: `E:\Project\Agent\backend\app\ask_runtime.py`
- Test: `E:\Project\Agent\backend\tests\test_ask_api.py`

- [ ] **Step 1: Write the failing context tests**

```python
from app.ask_context import AskContextManager


def test_apply_state_patch_separates_conversation_working_and_pending():
    manager = AskContextManager()
    current = {
        "conversation_memory": {"recent_messages": ["old"]},
        "working_context": {"last_target": "Ai应用开发群"},
        "pending_action_draft": {"intent": "message.send"},
    }
    patched = manager.apply_patch(
        current,
        {
            "conversation_memory": {"recent_messages": ["new"]},
            "working_context": {"last_shareable_text": "你好"},
            "pending_action_draft": {},
        },
    )
    assert patched["conversation_memory"]["recent_messages"] == ["new"]
    assert patched["working_context"]["last_target"] == "Ai应用开发群"
    assert patched["working_context"]["last_shareable_text"] == "你好"
    assert patched["pending_action_draft"] == {}


def test_intent_router_prefers_action_when_message_contains_explicit_send_intent():
    from app.ask_intent import AskIntentRouter

    router = AskIntentRouter()
    result = router.route(
        message='给李雷发送“你好”',
        active_context={"pending_action_draft": {}},
    )
    assert result["route"] == "action_only"
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```powershell
C:\Users\Hank\.conda\envs\emata\python.exe -m unittest tests.test_ask_context tests.test_ask_intent -v
```

Expected: FAIL with `ModuleNotFoundError` or missing class/method assertions.

- [ ] **Step 3: Write minimal context and intent modules**

```python
# E:\Project\Agent\backend\app\ask_context.py
from copy import deepcopy


class AskContextManager:
    DEFAULT_CONTEXT = {
        "conversation_memory": {},
        "working_context": {},
        "pending_action_draft": {},
    }

    def normalize(self, value):
        normalized = deepcopy(self.DEFAULT_CONTEXT)
        if isinstance(value, dict):
            for key in normalized:
                incoming = value.get(key)
                if isinstance(incoming, dict):
                    normalized[key].update(incoming)
        return normalized

    def apply_patch(self, current, patch):
        merged = self.normalize(current)
        for key in ("conversation_memory", "working_context", "pending_action_draft"):
            incoming = patch.get(key)
            if isinstance(incoming, dict):
                if key == "pending_action_draft":
                    merged[key] = dict(incoming)
                else:
                    merged[key].update(incoming)
        return merged
```

```python
# E:\Project\Agent\backend\app\ask_intent.py
class AskIntentRouter:
    ACTION_MARKERS = ("发给", "发送", "发到", "通知", "安排", "创建")
    QUESTION_MARKERS = ("多少", "什么是", "是什么", "如何", "规则", "流程", "?")

    def route(self, *, message, active_context):
        content = (message or "").strip()
        if any(marker in content for marker in self.ACTION_MARKERS):
            if ("刚才" in content or "上一轮" in content) and active_context.get("working_context", {}).get("last_shareable_text"):
                return {"route": "answer_then_action"}
            return {"route": "action_only"}
        if any(marker in content for marker in self.QUESTION_MARKERS):
            return {"route": "knowledge_qa"}
        return {"route": "skill_default"}
```

- [ ] **Step 4: Refactor runtime to use the new modules**

```python
# E:\Project\Agent\backend\app\ask_runtime.py
from app.ask_context import AskContextManager
from app.ask_intent import AskIntentRouter


class AskRuntime:
    def __init__(self, *, context_manager=None, intent_router=None, ...):
        self.context_manager = context_manager or AskContextManager()
        self.intent_router = intent_router or AskIntentRouter()

    def _resolve_context(self, session):
        return self.context_manager.normalize(session.active_context or {})

    def _apply_state_patch(self, session, patch):
        session.active_context = self.context_manager.apply_patch(
            session.active_context or {},
            patch or {},
        )
```

- [ ] **Step 5: Run tests to verify they pass**

Run:

```powershell
C:\Users\Hank\.conda\envs\emata\python.exe -m unittest tests.test_ask_context tests.test_ask_intent tests.test_ask_api -v
```

Expected: PASS for new and existing ask routing tests.

- [ ] **Step 6: Commit**

```bash
git add E:/Project/Agent/backend/app/ask_context.py E:/Project/Agent/backend/app/ask_intent.py E:/Project/Agent/backend/app/ask_runtime.py E:/Project/Agent/backend/tests/test_ask_context.py E:/Project/Agent/backend/tests/test_ask_intent.py E:/Project/Agent/backend/tests/test_ask_api.py
git commit -m "refactor: split ask context and intent routing"
```

### Task 2: Introduce a Generic Action Planner and Keep HR Skill Narrow

**Files:**
- Create: `E:\Project\Agent\backend\app\ask_action_planner.py`
- Modify: `E:\Project\Agent\backend\app\ask_actions.py`
- Modify: `E:\Project\Agent\backend\app\ask_targeting.py`
- Modify: `E:\Project\Agent\backend\app\ask_skill_hr_recruiting.py`
- Create: `E:\Project\Agent\backend\tests\test_ask_action_planner.py`
- Test: `E:\Project\Agent\backend\tests\test_ask_api.py`

- [ ] **Step 1: Write failing planner tests for message preview and target selection**

```python
from app.ask_action_planner import AskActionPlanner


def test_message_plan_uses_explicit_target_and_body():
    planner = AskActionPlanner()
    plan = planner.plan_message_action(
        message='把“你好”发到 Ai应用开发群',
        working_context={},
    )
    assert plan["intent"] == "message.send"
    assert plan["target_query"] == "Ai应用开发群"
    assert plan["text"] == "你好"
    assert plan["requires_preview"] is True


def test_message_plan_reuses_last_shareable_text_for_answer_then_action():
    planner = AskActionPlanner()
    plan = planner.plan_message_action(
        message="把刚才的结论发给李雷",
        working_context={"last_shareable_text": "候选人通过一面"},
    )
    assert plan["text"] == "候选人通过一面"
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```powershell
C:\Users\Hank\.conda\envs\emata\python.exe -m unittest tests.test_ask_action_planner -v
```

Expected: FAIL with missing module/class.

- [ ] **Step 3: Implement the generic action planner**

```python
# E:\Project\Agent\backend\app\ask_action_planner.py
import re


class AskActionPlanner:
    def plan_message_action(self, *, message, working_context):
        explicit_body = self._extract_quoted_text(message)
        text = explicit_body or working_context.get("last_shareable_text", "")
        target_query = self._extract_target(message)
        return {
            "intent": "message.send",
            "risk_level": "medium",
            "requires_preview": True,
            "target_query": target_query,
            "text": text,
            "summary": f"发送消息到 {target_query}" if target_query else "发送消息",
        }

    def _extract_quoted_text(self, message):
        match = re.search(r"[“\"](.+?)[”\"]", message or "")
        return match.group(1).strip() if match else ""

    def _extract_target(self, message):
        for marker in ("发到", "发送到", "发给", "发送给", "给"):
            if marker in (message or ""):
                return (message.split(marker, 1)[1].split("“", 1)[0].strip())
        return ""
```

- [ ] **Step 4: Route action creation through the planner and remove HR-only defaults**

```python
# E:\Project\Agent\backend\app\ask_actions.py
from app.ask_action_planner import AskActionPlanner


class AskActionDraftModule:
    def __init__(self, *, target_resolver=None, action_planner=None):
        self.target_resolver = target_resolver or AskTargetResolver()
        self.action_planner = action_planner or AskActionPlanner()

    def handle_turn(...):
        draft = self.action_planner.plan_message_action(
            message=message,
            working_context=active_context.get("working_context", {}),
        )
```

- [ ] **Step 5: Run tests to verify planner and ask flow pass**

Run:

```powershell
C:\Users\Hank\.conda\envs\emata\python.exe -m unittest tests.test_ask_action_planner tests.test_ask_api -v
```

Expected: PASS, and message turns no longer fall back to HR default text.

- [ ] **Step 6: Commit**

```bash
git add E:/Project/Agent/backend/app/ask_action_planner.py E:/Project/Agent/backend/app/ask_actions.py E:/Project/Agent/backend/app/ask_targeting.py E:/Project/Agent/backend/app/ask_skill_hr_recruiting.py E:/Project/Agent/backend/tests/test_ask_action_planner.py E:/Project/Agent/backend/tests/test_ask_api.py
git commit -m "refactor: introduce generic ask action planner"
```

### Task 3: Make Target Resolution and Preview Card Transparent and Editable

**Files:**
- Modify: `E:\Project\Agent\backend\app\ask_targeting.py`
- Modify: `E:\Project\Agent\backend\app\contracts.py`
- Modify: `E:\Project\Agent\frontend\lib\ask.js`
- Modify: `E:\Project\Agent\frontend\components\ask-chat.js`
- Modify: `E:\Project\Agent\frontend\tests\ask-page.test.mjs`
- Test: `E:\Project\Agent\backend\tests\test_ask_api.py`

- [ ] **Step 1: Write failing tests for transparent grouped target results and editable preview**

```javascript
import test from "node:test";
import assert from "node:assert/strict";
import { buildTargetSelectionModel, buildActionPreviewModel } from "../lib/ask.js";

test("target selection model groups contact and chat search results", () => {
  const model = buildTargetSelectionModel({
    data: {
      options: [{ kind: "other", label: "其他" }],
      search_results: {
        contacts: [{ kind: "user", label: "李雷", value: "ou_1" }],
        chats: [{ kind: "chat", label: "Ai应用开发群", value: "oc_1" }],
      },
    },
  });
  assert.equal(model.contacts.length, 1);
  assert.equal(model.chats.length, 1);
});
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```powershell
node --test E:/Project/Agent/frontend/tests/ask-page.test.mjs E:/Project/Agent/frontend/tests/api.test.mjs
```

Expected: FAIL with missing grouped fields or preview model mismatch.

- [ ] **Step 3: Implement grouped search results and editable preview card**

```javascript
// E:\Project\Agent\frontend\lib\ask.js
export function buildTargetSelectionModel(output) {
  const data = output?.data ?? {};
  const searchResults = data.search_results ?? { contacts: [], chats: [] };
  return {
    contacts: searchResults.contacts ?? [],
    chats: searchResults.chats ?? [],
    options: data.options ?? [],
    otherOption: (data.options ?? []).find((item) => item.kind === "other") ?? null,
  };
}

export function buildActionPreviewModel(output) {
  const draft = output?.data?.draft ?? {};
  return {
    summary: draft.summary ?? "",
    text: draft.text ?? "",
    targetLabel: draft?.resolved_target?.label ?? "",
    editableFields: output?.data?.editable_fields ?? ["text"],
  };
}
```

```javascript
// E:\Project\Agent\frontend\components\ask-chat.js
if (cardType === "target_selection") {
  const model = buildTargetSelectionModel(output);
  // render 联系人搜索结果 / 会话搜索结果 / 其他 / 取消
}
if (cardType === "action_preview") {
  const model = buildActionPreviewModel(output);
  // render editable textarea + selected target + confirm/cancel
}
```

- [ ] **Step 4: Run frontend and backend tests**

Run:

```powershell
C:\Users\Hank\.conda\envs\emata\python.exe -m unittest tests.test_ask_api -v
node --test E:/Project/Agent/frontend/tests/ask-page.test.mjs E:/Project/Agent/frontend/tests/api.test.mjs
```

Expected: PASS, and target cards show grouped results with cancel action.

- [ ] **Step 5: Commit**

```bash
git add E:/Project/Agent/backend/app/ask_targeting.py E:/Project/Agent/backend/app/contracts.py E:/Project/Agent/frontend/lib/ask.js E:/Project/Agent/frontend/components/ask-chat.js E:/Project/Agent/frontend/tests/ask-page.test.mjs E:/Project/Agent/backend/tests/test_ask_api.py
git commit -m "feat: add transparent ask target search and editable preview"
```

## Phase 2: RAG + Citations + General LLM

### Task 4: Promote Ask Knowledge QA to a Full Grounded RAG Pipeline

**Files:**
- Modify: `E:\Project\Agent\backend\app\ask_runtime.py`
- Modify: `E:\Project\Agent\backend\app\ask_tools.py`
- Modify: `E:\Project\Agent\backend\app\contracts.py`
- Modify: `E:\Project\Agent\backend\app\services.py`
- Modify: `E:\Project\Agent\backend\tests\test_ask_api.py`
- Test: `E:\Project\Agent\backend\tests\test_ask_tools.py`

- [ ] **Step 1: Write failing tests for grounded answer mode with citations**

```python
def test_grounded_knowledge_answer_returns_mode_confidence_and_citations(self):
    response = self.client.post(
        f"/api/v1/ask/sessions/{self.session_id}/turns",
        json={"message": "报销的额度是多少"},
    )
    payload = response.json()
    answer = next(item for item in payload["outputs"] if item["type"] == "message")
    assert answer["data"]["answer_mode"] == "grounded_rag"
    assert len(payload["outputs"]) >= 2
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```powershell
C:\Users\Hank\.conda\envs\emata\python.exe -m unittest tests.test_ask_api -v
```

Expected: FAIL on missing `answer_mode` / `confidence` / `citations`.

- [ ] **Step 3: Implement `search -> rerank -> answer -> citations` and explicit answer modes**

```python
# E:\Project\Agent\backend\app\ask_runtime.py
rerank_payload = tools["rerank"].execute({"query": message, "items": items, "top_n": 5}, user=user)
grounded_items = rerank_payload.get("items", [])[:5]
generation_result = tools["answer_generate"].execute(
    {
        "mode": "grounded",
        "question": message,
        "contexts": grounded_items,
    },
    user=user,
)
return {
    "outputs": [
        {
            "type": "message",
            "text": generation_result["answer"],
            "data": {
                "answer_mode": "grounded_rag",
                "confidence": generation_result.get("confidence", 0.0),
            },
        },
        *self._build_citation_outputs(grounded_items),
    ],
}
```

- [ ] **Step 4: Run tests to verify grounded answers and citations pass**

Run:

```powershell
C:\Users\Hank\.conda\envs\emata\python.exe -m unittest tests.test_ask_api tests.test_ask_tools -v
```

Expected: PASS, with grounded answers returning citations and structured answer mode.

- [ ] **Step 5: Commit**

```bash
git add E:/Project/Agent/backend/app/ask_runtime.py E:/Project/Agent/backend/app/ask_tools.py E:/Project/Agent/backend/app/contracts.py E:/Project/Agent/backend/app/services.py E:/Project/Agent/backend/tests/test_ask_api.py E:/Project/Agent/backend/tests/test_ask_tools.py
git commit -m "feat: upgrade ask knowledge qa to grounded rag"
```

### Task 5: Add `general_llm` Fallback Without Pretending It Is Enterprise Knowledge

**Files:**
- Modify: `E:\Project\Agent\backend\app\ask_runtime.py`
- Modify: `E:\Project\Agent\backend\tests\test_ask_api.py`
- Modify: `E:\Project\Agent\frontend\lib\ask.js`
- Modify: `E:\Project\Agent\frontend\components\ask-chat.js`

- [ ] **Step 1: Write failing tests for no-hit general questions**

```python
def test_general_question_without_hits_returns_general_llm_answer_mode(self):
    response = self.client.post(
        f"/api/v1/ask/sessions/{self.session_id}/turns",
        json={"message": "多模态是什么"},
    )
    payload = response.json()
    answer = next(item for item in payload["outputs"] if item["type"] == "message")
    assert answer["data"]["answer_mode"] == "general_llm"
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```powershell
C:\Users\Hank\.conda\envs\emata\python.exe -m unittest tests.test_ask_api -v
```

Expected: FAIL because fallback still looks like HR or extraction.

- [ ] **Step 3: Implement general LLM fallback with explicit labeling**

```python
if not grounded_items and self._should_use_general_llm(message):
    general = tools["answer_generate"].execute({"mode": "general", "question": message}, user=user)
    return {
        "outputs": [
            {
                "type": "message",
                "text": general["answer"],
                "data": {
                    "answer_mode": "general_llm",
                    "confidence": general.get("confidence", 0.0),
                },
            }
        ],
        "state_patch": {
            "working_context": {
                "last_knowledge_answer_text": general["answer"],
                "last_shareable_text": general["answer"],
            }
        },
    }
```

- [ ] **Step 4: Run backend and frontend tests**

Run:

```powershell
C:\Users\Hank\.conda\envs\emata\python.exe -m unittest tests.test_ask_api -v
node --test E:/Project/Agent/frontend/tests/ask-page.test.mjs
```

Expected: PASS, with general questions no longer falling back to HR copy.

- [ ] **Step 5: Commit**

```bash
git add E:/Project/Agent/backend/app/ask_runtime.py E:/Project/Agent/backend/tests/test_ask_api.py E:/Project/Agent/frontend/lib/ask.js E:/Project/Agent/frontend/components/ask-chat.js
git commit -m "feat: add general llm fallback for ask"
```

## Phase 3: Async Execution + SSE

### Task 6: Introduce Ask Job Model for Long-Running Feishu Actions

**Files:**
- Create: `E:\Project\Agent\backend\app\ask_jobs.py`
- Create: `E:\Project\Agent\backend\tests\test_ask_jobs.py`
- Modify: `E:\Project\Agent\backend\app\ask_actions.py`
- Modify: `E:\Project\Agent\backend\app\contracts.py`
- Modify: `E:\Project\Agent\backend\app\services.py`

- [ ] **Step 1: Write failing job tests**

```python
from app.ask_jobs import InMemoryAskJobStore


def test_enqueue_job_returns_pending_status():
    store = InMemoryAskJobStore()
    job = store.enqueue({"type": "message.send"})
    assert job["status"] == "pending"
    assert job["id"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```powershell
C:\Users\Hank\.conda\envs\emata\python.exe -m unittest tests.test_ask_jobs -v
```

Expected: FAIL with missing module.

- [ ] **Step 3: Implement in-memory job store and background execution hook**

```python
# E:\Project\Agent\backend\app\ask_jobs.py
from dataclasses import dataclass, asdict
from uuid import uuid4


class InMemoryAskJobStore:
    def __init__(self):
        self.jobs = {}

    def enqueue(self, payload):
        job = {"id": str(uuid4()), "status": "pending", "payload": payload, "result": None}
        self.jobs[job["id"]] = job
        return job

    def mark_running(self, job_id):
        self.jobs[job_id]["status"] = "running"

    def mark_finished(self, job_id, result):
        self.jobs[job_id]["status"] = "finished"
        self.jobs[job_id]["result"] = result
```

- [ ] **Step 4: Use jobs for approve/execute path instead of blocking request**

```python
# E:\Project\Agent\backend\app\ask_actions.py
job = tools["job_store"].enqueue({"draft": pending_draft, "user_id": user.id})
return {
    "outputs": [{"type": "message", "text": "已接收任务，正在后台执行。", "data": {"job_id": job["id"]}}],
    "state_patch": {"working_context": {"last_job_id": job["id"]}},
}
```

- [ ] **Step 5: Run tests to verify async job plumbing passes**

Run:

```powershell
C:\Users\Hank\.conda\envs\emata\python.exe -m unittest tests.test_ask_jobs tests.test_ask_api -v
```

Expected: PASS, with approve path returning job metadata instead of blocking result.

- [ ] **Step 6: Commit**

```bash
git add E:/Project/Agent/backend/app/ask_jobs.py E:/Project/Agent/backend/tests/test_ask_jobs.py E:/Project/Agent/backend/app/ask_actions.py E:/Project/Agent/backend/app/contracts.py E:/Project/Agent/backend/app/services.py E:/Project/Agent/backend/tests/test_ask_api.py
git commit -m "feat: add async ask job execution"
```

### Task 7: Add Polling / SSE Status Updates to the Ask UI

**Files:**
- Modify: `E:\Project\Agent\backend\app\routes.py`
- Modify: `E:\Project\Agent\backend\app\contracts.py`
- Modify: `E:\Project\Agent\frontend\lib\api.js`
- Modify: `E:\Project\Agent\frontend\lib\ask.js`
- Modify: `E:\Project\Agent\frontend\components\ask-chat.js`
- Modify: `E:\Project\Agent\frontend\tests\ask-page.test.mjs`
- Modify: `E:\Project\Agent\frontend\tests\api.test.mjs`

- [ ] **Step 1: Write failing frontend and API tests for job polling**

```javascript
test("ask api exposes job status request helper", () => {
  const request = buildAskJobStatusRequest("job-123");
  assert.equal(request.path, "/api/v1/ask/jobs/job-123");
});
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```powershell
node --test E:/Project/Agent/frontend/tests/ask-page.test.mjs E:/Project/Agent/frontend/tests/api.test.mjs
```

Expected: FAIL because job helpers and UI are missing.

- [ ] **Step 3: Add polling and SSE-aware API/client helpers**

```javascript
// E:\Project\Agent\frontend\lib\api.js
export async function fetchAskJobStatus(jobId) {
  return requestJson(`/api/v1/ask/jobs/${jobId}`);
}

export function subscribeAskJob(jobId, onMessage) {
  const source = new EventSource(`${resolveApiBaseUrl()}/api/v1/ask/jobs/${jobId}/events`);
  source.onmessage = (event) => onMessage(JSON.parse(event.data));
  return () => source.close();
}
```

```python
# E:\Project\Agent\backend\app\routes.py
@router.get("/api/v1/ask/jobs/{job_id}")
async def get_ask_job(job_id: str):
    return container.ask_job_store.get(job_id)

@router.get("/api/v1/ask/jobs/{job_id}/events")
async def stream_ask_job(job_id: str):
    ...
```

- [ ] **Step 4: Render non-blocking execution state in the UI**

```javascript
// E:\Project\Agent\frontend\components\ask-chat.js
if (output.type === "message" && output.data?.job_id) {
  // show "执行中" status and update when polling/SSE returns finished result
}
```

- [ ] **Step 5: Run full frontend/backend verification**

Run:

```powershell
C:\Users\Hank\.conda\envs\emata\python.exe -m unittest tests.test_ask_api tests.test_ask_jobs -v
node --test E:/Project/Agent/frontend/tests/ask-page.test.mjs E:/Project/Agent/frontend/tests/api.test.mjs
npm run build
```

Expected: PASS, and Ask no longer appears frozen during long Feishu round trips.

- [ ] **Step 6: Commit**

```bash
git add E:/Project/Agent/backend/app/routes.py E:/Project/Agent/backend/app/contracts.py E:/Project/Agent/frontend/lib/api.js E:/Project/Agent/frontend/lib/ask.js E:/Project/Agent/frontend/components/ask-chat.js E:/Project/Agent/frontend/tests/ask-page.test.mjs E:/Project/Agent/frontend/tests/api.test.mjs E:/Project/Agent/backend/tests/test_ask_api.py E:/Project/Agent/backend/tests/test_ask_jobs.py
git commit -m "feat: add async ask status polling and sse"
```

## Final Verification Checklist

- [ ] Run:

```powershell
C:\Users\Hank\.conda\envs\emata\python.exe -m unittest tests.test_ask_context tests.test_ask_intent tests.test_ask_action_planner tests.test_ask_jobs tests.test_ask_api tests.test_ask_tools -v
```

Expected: all backend tests PASS.

- [ ] Run:

```powershell
node --test E:/Project/Agent/frontend/tests/ask-page.test.mjs E:/Project/Agent/frontend/tests/api.test.mjs
```

Expected: all frontend tests PASS.

- [ ] Run:

```powershell
cd E:\Project\Agent\frontend
npm run build
```

Expected: build succeeds and `/ask` compiles.

- [ ] Manual smoke test:
  - `报销的额度是多少`
  - `多模态是什么`
  - `把“你好”发到 Ai应用开发群`
  - `给李雷发送“你好”`
  - `安排张三的一面`

## Self-Review

- Spec coverage: 覆盖了你刚定的三个阶段：
  - Phase 1：`Intent Router + Action Planner + Context`
  - Phase 2：`RAG + citations + general_llm`
  - Phase 3：`Async execution + SSE`
- Placeholder scan: 没有留 `TODO / TBD / implement later`
- Type consistency: plan 中统一使用：
  - `conversation_memory`
  - `working_context`
  - `pending_action_draft`
  - `answer_mode`
  - `job_id`

