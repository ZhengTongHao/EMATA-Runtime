# Ask HR Recruiting Copilot Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在通用 Ask Runtime 上落地第一版 `HR Recruiting Skill`，支持多轮招聘协同、受控 `lark-cli` 动作执行、统一确认流和可扩展的 Tool/Skill 架构。

**Architecture:** 后端先搭建通用 `Session + Turn + Command + Artifact` Ask 运行时，再注册唯一的 `hr_recruiting` skill；外部能力统一通过 Tool Registry 暴露，其中 `lark-cli` 作为受控 tool adapter 提供 `dry_run -> risk_check -> execute -> normalize` 流程。前端新增 `/ask` 聊天页，只渲染标准 outputs 和触发 commands，不承载领域状态真相。

**Tech Stack:** Python, FastAPI, Pydantic, SQLAlchemy snapshot store, Next.js, node:test, unittest, lark-cli

---

## Next Task Queue

- [ ] 下一阶段优先做 `后台任务 + 前端轮询或 SSE 流式状态`，把当前同步执行的飞书动作改成异步任务回执，降低确认执行后的卡顿感。

> **用户约束：** 本计划明确不包含 git worktree、commit、branch 步骤；实现直接在当前工作目录推进。

## 文件结构

- Create: `E:/Project/Agent/backend/app/ask_runtime.py`
- Create: `E:/Project/Agent/backend/app/ask_tools.py`
- Create: `E:/Project/Agent/backend/app/ask_skill_hr_recruiting.py`
- Create: `E:/Project/Agent/backend/tests/test_ask_api.py`
- Modify: `E:/Project/Agent/backend/app/contracts.py`
- Modify: `E:/Project/Agent/backend/app/core.py`
- Modify: `E:/Project/Agent/backend/app/persistence.py`
- Modify: `E:/Project/Agent/backend/app/routes.py`
- Modify: `E:/Project/Agent/backend/app/services.py`
- Create: `E:/Project/Agent/frontend/app/ask/page.js`
- Create: `E:/Project/Agent/frontend/components/ask-chat.js`
- Create: `E:/Project/Agent/frontend/lib/ask.js`
- Create: `E:/Project/Agent/frontend/tests/ask-page.test.mjs`
- Modify: `E:/Project/Agent/frontend/lib/api.js`
- Modify: `E:/Project/Agent/frontend/app/page.js`

### Task 1: 建立通用 Ask 会话与 API 契约

**Files:**
- Modify: `E:/Project/Agent/backend/app/contracts.py`
- Modify: `E:/Project/Agent/backend/app/core.py`
- Modify: `E:/Project/Agent/backend/app/persistence.py`
- Modify: `E:/Project/Agent/backend/app/routes.py`
- Test: `E:/Project/Agent/backend/tests/test_ask_api.py`

- [ ] **Step 1: 先写后端失败测试，约束 Ask 基础会话接口**

```python
async def test_create_ask_session_returns_generic_session_shape(self) -> None:
    response = await client.post(
        "/api/v1/ask/sessions",
        json={"skill_id": "hr_recruiting", "title": "Recruiting copilot"},
    )
    self.assertEqual(response.status_code, 201)
    payload = response.json()
    self.assertEqual(payload["skill_id"], "hr_recruiting")
    self.assertIn("active_context", payload)
```

- [ ] **Step 2: 运行测试确认失败**

Run: `& 'C:\Users\Hank\.conda\envs\emata\python.exe' -m unittest tests.test_ask_api -v`

Expected: FAIL，因为 `/api/v1/ask/sessions` 及相关响应模型尚不存在。

- [ ] **Step 3: 增加 Ask 相关 record 与响应模型**

```python
@dataclass
class AskSessionRecord:
    id: str
    user_id: str
    skill_id: str
    title: str
    status: str
    summary: str = ""
    active_context: Dict[str, Any] = field(default_factory=dict)
```

```python
class AskSessionResponse(BaseModel):
    id: str
    user_id: str
    skill_id: str
    title: str
    status: str
    summary: str = ""
    active_context: Dict[str, Any] = {}
```

- [ ] **Step 4: 在 persistence 层保存与恢复 Ask session/turn/artifact**

```python
def save_ask_session(self, session: AskSessionRecord) -> None:
    self._upsert("ask_session", session.id, _serialize(session))
```

- [ ] **Step 5: 增加基础路由**

```python
@public_router.post("/ask/sessions", status_code=status.HTTP_201_CREATED)
def create_ask_session(...):
    session = container.create_ask_session(user, payload.skill_id, payload.title)
    return serialize_ask_session(session)
```

- [ ] **Step 6: 运行测试确认通过**

Run: `& 'C:\Users\Hank\.conda\envs\emata\python.exe' -m unittest tests.test_ask_api -v`

Expected: PASS 至少覆盖 session 创建和读取。

### Task 2: 建立 Ask Runtime、标准输出协议和 Command 机制

**Files:**
- Create: `E:/Project/Agent/backend/app/ask_runtime.py`
- Modify: `E:/Project/Agent/backend/app/contracts.py`
- Modify: `E:/Project/Agent/backend/app/services.py`
- Modify: `E:/Project/Agent/backend/app/routes.py`
- Test: `E:/Project/Agent/backend/tests/test_ask_api.py`

- [ ] **Step 1: 先写失败测试，约束 turn/command 返回统一 TurnResult**

```python
async def test_ask_turn_returns_outputs_state_patch_and_pending_commands(self) -> None:
    session = await client.post("/api/v1/ask/sessions", json={"skill_id": "hr_recruiting"})
    response = await client.post(
        f"/api/v1/ask/sessions/{session.json()['id']}/turns",
        json={"content": "帮我看简历"},
    )
    payload = response.json()
    self.assertIn("outputs", payload)
    self.assertIn("state_patch", payload)
    self.assertIn("pending_commands", payload)
```

- [ ] **Step 2: 运行测试确认失败**

Run: `& 'C:\Users\Hank\.conda\envs\emata\python.exe' -m unittest tests.test_ask_api -v`

Expected: FAIL，因为 `/turns` 与 `/commands` 还未实现。

- [ ] **Step 3: 定义 AskRuntime 的统一协议**

```python
class AskRuntime:
    def run_turn(self, *, session, message, user) -> Dict[str, Any]:
        skill = self.skill_registry[session.skill_id]
        result = skill.handle_turn(...)
        return {
            "turn": turn_payload,
            "outputs": result["outputs"],
            "state_patch": result.get("state_patch", {}),
            "pending_commands": result.get("pending_commands", []),
        }
```

- [ ] **Step 4: 增加通用 command 接口**

```python
@public_router.post("/ask/sessions/{session_id}/commands")
def run_ask_command(...):
    return container.run_ask_command(...)
```

- [ ] **Step 5: 在 service container 中接入 AskRuntime**

```python
self.ask_runtime = AskRuntime(
    skill_registry={"hr_recruiting": HRRecruitingSkill(...)},
    tool_registry=build_tool_registry(...),
    policy_engine=AskPolicyEngine(),
)
```

- [ ] **Step 6: 运行测试确认通过**

Run: `& 'C:\Users\Hank\.conda\envs\emata\python.exe' -m unittest tests.test_ask_api -v`

Expected: PASS，turn 与 command 返回统一结构。

### Task 3: 建立 Tool Registry 与受控 lark-cli adapter

**Files:**
- Create: `E:/Project/Agent/backend/app/ask_tools.py`
- Modify: `E:/Project/Agent/backend/app/services.py`
- Test: `E:/Project/Agent/backend/tests/test_ask_api.py`

- [ ] **Step 1: 先写失败测试，约束 tool 走 validate/dry_run/normalize 流程**

```python
def test_lark_cli_tool_dry_run_is_called_before_execute(self):
    tool = LarkCliTool(executable="lark-cli")
    preview = tool.dry_run({"capability": "message.send"})
    self.assertIn("status", preview)
```

- [ ] **Step 2: 运行测试确认失败**

Run: `& 'C:\Users\Hank\.conda\envs\emata\python.exe' -m unittest tests.test_ask_api -v`

Expected: FAIL，因为 `LarkCliTool` 尚不存在。

- [ ] **Step 3: 定义通用 Tool 协议**

```python
class BaseTool:
    def validate(self, payload: Dict[str, Any]) -> None: ...
    def dry_run(self, payload: Dict[str, Any]) -> Dict[str, Any]: ...
    def execute(self, payload: Dict[str, Any]) -> Dict[str, Any]: ...
    def normalize(self, result: Dict[str, Any]) -> Dict[str, Any]: ...
```

- [ ] **Step 4: 实现受控的 lark-cli adapter**

```python
class LarkCliTool(BaseTool):
    ALLOWED_CAPABILITIES = {
        "message.send",
        "calendar.schedule",
        "contact.resolve",
        "doc.create",
    }
```

- [ ] **Step 5: 构建 Tool Registry**

```python
def build_tool_registry(...) -> Dict[str, BaseTool]:
    return {
        "lark_cli": LarkCliTool(...),
        "resume_fetch": ResumeFetchTool(),
        "resume_parse": ResumeParseTool(parser=document_parser),
        "knowledge_search": KnowledgeSearchTool(container=self),
        "rerank": RerankTool(),
        "doc_generate": DocGenerateTool(),
    }
```

- [ ] **Step 6: 运行测试确认通过**

Run: `& 'C:\Users\Hank\.conda\envs\emata\python.exe' -m unittest tests.test_ask_api -v`

Expected: PASS，至少覆盖 capability 白名单和 dry-run。

### Task 4: 实现 HR Recruiting Skill 的“看简历”主链

**Files:**
- Create: `E:/Project/Agent/backend/app/ask_skill_hr_recruiting.py`
- Modify: `E:/Project/Agent/backend/app/services.py`
- Test: `E:/Project/Agent/backend/tests/test_ask_api.py`

- [ ] **Step 1: 先写失败测试，约束没有岗位时先追问岗位**

```python
async def test_hr_skill_asks_for_position_before_resume_analysis(self) -> None:
    session = await client.post("/api/v1/ask/sessions", json={"skill_id": "hr_recruiting"})
    response = await client.post(
        f"/api/v1/ask/sessions/{session.json()['id']}/turns",
        json={"content": "帮我看简历"},
    )
    payload = response.json()
    self.assertEqual(payload["outputs"][0]["type"], "card")
    self.assertIn("岗位", payload["outputs"][0]["text"])
```

- [ ] **Step 2: 运行测试确认失败**

Run: `& 'C:\Users\Hank\.conda\envs\emata\python.exe' -m unittest tests.test_ask_api -v`

Expected: FAIL，因为 HR skill 还未处理 resume intake 状态。

- [ ] **Step 3: 实现 HRRecruitingSkill 的简历入口逻辑**

```python
class HRRecruitingSkill:
    def handle_turn(self, *, session, message, memory, tools, policy):
        if self._looks_like_resume_request(message) and not session.active_context.get("active_position"):
            return {
                "outputs": [{"type": "card", "text": "请先确认岗位名称或目标 JD。"}],
                "state_patch": {"active_skill_state": "resume_intake"},
                "pending_commands": [],
            }
```

- [ ] **Step 4: 增加 JD 自动检索和简历分析骨架**

```python
jd_hits = tools["knowledge_search"].search({"query": position_name, "kind": "jd"})
resume_profile = tools["resume_parse"].execute({"source": resume_source})
analysis = self._analyze_resume(resume_profile, jd_hits)
```

- [ ] **Step 5: 让 “看简历” 产出标准 artifacts**

```python
outputs = [
    {"type": "message", "text": analysis["summary"]},
    {"type": "artifact", "artifact_type": "resume_summary", "data": resume_profile},
    {"type": "artifact", "artifact_type": "candidate_analysis", "data": analysis},
]
```

- [ ] **Step 6: 运行测试确认通过**

Run: `& 'C:\Users\Hank\.conda\envs\emata\python.exe' -m unittest tests.test_ask_api -v`

Expected: PASS，至少覆盖岗位追问、JD 自动检索失败时追问、简历分析输出。

### Task 5: 实现候选人切换、面试安排与时间推荐

**Files:**
- Modify: `E:/Project/Agent/backend/app/ask_skill_hr_recruiting.py`
- Modify: `E:/Project/Agent/backend/app/ask_runtime.py`
- Test: `E:/Project/Agent/backend/tests/test_ask_api.py`

- [ ] **Step 1: 先写失败测试，约束新候选人出现时先弹切换卡**

```python
async def test_new_candidate_requires_switch_confirmation(self) -> None:
    response = await client.post(
        f"/api/v1/ask/sessions/{session_id}/turns",
        json={"content": "那就看看王敏的简历"},
    )
    payload = response.json()
    self.assertTrue(any(item["type"] == "card" for item in payload["outputs"]))
    self.assertEqual(payload["pending_commands"][0]["command_type"], "switch_context")
```

- [ ] **Step 2: 运行测试确认失败**

Run: `& 'C:\Users\Hank\.conda\envs\emata\python.exe' -m unittest tests.test_ask_api -v`

Expected: FAIL，因为候选人切换和 command 还没打通。

- [ ] **Step 3: 实现候选人切换确认卡**

```python
if candidate_name != active_candidate_name:
    return {
        "outputs": [{"type": "card", "text": f"切换到候选人 {candidate_name} 吗？"}],
        "pending_commands": [{"command_type": "switch_context", "payload": {"candidate_name": candidate_name}}],
    }
```

- [ ] **Step 4: 先写失败测试，约束时间不明确时给出 2-3 个时间推荐**

```python
async def test_interview_schedule_returns_time_suggestions_when_time_is_missing(self) -> None:
    response = await client.post(
        f"/api/v1/ask/sessions/{session_id}/turns",
        json={"content": "帮我约李雷和候选人一面"},
    )
    payload = response.json()
    card = next(item for item in payload["outputs"] if item["type"] == "card")
    self.assertIn("可选时间", card["text"])
```

- [ ] **Step 5: 实现面试时间推荐和 interview_plan artifact**

```python
slots = self._suggest_time_slots()
return {
    "outputs": [
        {"type": "card", "text": "我找到了 3 个可选时间，请选择。", "options": slots},
        {"type": "artifact", "artifact_type": "interview_plan", "data": {"candidate": candidate_name, "slots": slots}},
    ],
    "pending_commands": [{"command_type": "select_option", "payload": {"kind": "time_slot"}}],
}
```

- [ ] **Step 6: 运行测试确认通过**

Run: `& 'C:\Users\Hank\.conda\envs\emata\python.exe' -m unittest tests.test_ask_api -v`

Expected: PASS，候选人切换和面试时间推荐可用。

### Task 6: 实现反馈汇总、文档生成与统一确认流

**Files:**
- Modify: `E:/Project/Agent/backend/app/ask_skill_hr_recruiting.py`
- Modify: `E:/Project/Agent/backend/app/ask_runtime.py`
- Test: `E:/Project/Agent/backend/tests/test_ask_api.py`

- [ ] **Step 1: 先写失败测试，约束反馈汇总默认生成 HR 私人文档**

```python
async def test_feedback_summary_generates_private_doc_artifact(self) -> None:
    response = await client.post(
        f"/api/v1/ask/sessions/{session_id}/turns",
        json={"content": "汇总今天的面试反馈并生成文档"},
    )
    payload = response.json()
    artifacts = [item for item in payload["outputs"] if item["type"] == "artifact"]
    self.assertTrue(any(item["artifact_type"] == "generated_doc" for item in artifacts))
```

- [ ] **Step 2: 运行测试确认失败**

Run: `& 'C:\Users\Hank\.conda\envs\emata\python.exe' -m unittest tests.test_ask_api -v`

Expected: FAIL，因为 doc_generate 流程未接入。

- [ ] **Step 3: 实现反馈汇总与文档生成**

```python
doc = tools["doc_generate"].execute({
    "space": "hr_private",
    "title": f"{candidate_name} 面试反馈汇总",
    "sections": summary_sections,
})
```

- [ ] **Step 4: 先写失败测试，约束多人可见动作先返回统一确认卡**

```python
async def test_multi_action_internal_collaboration_requires_single_confirmation(self) -> None:
    response = await client.post(
        f"/api/v1/ask/sessions/{session_id}/turns",
        json={"content": "约李雷明天下午 3 点开会，并把刚才提纲发给他"},
    )
    payload = response.json()
    card = next(item for item in payload["outputs"] if item["type"] == "card")
    self.assertIn("将执行的动作", card["text"])
    self.assertEqual(payload["pending_commands"][0]["command_type"], "approve_plan")
```

- [ ] **Step 5: 实现统一确认流与顺序执行**

```python
plan = {
    "actions": [
        {"capability": "calendar.schedule", "payload": meeting_payload},
        {"capability": "message.send", "depends_on": 0, "payload": message_payload},
    ]
}
```

- [ ] **Step 6: 运行测试确认通过**

Run: `& 'C:\Users\Hank\.conda\envs\emata\python.exe' -m unittest tests.test_ask_api -v`

Expected: PASS，反馈文档和统一确认流可用。

### Task 7: 新增 Ask 前端页面并渲染标准 outputs

**Files:**
- Create: `E:/Project/Agent/frontend/app/ask/page.js`
- Create: `E:/Project/Agent/frontend/components/ask-chat.js`
- Create: `E:/Project/Agent/frontend/lib/ask.js`
- Modify: `E:/Project/Agent/frontend/lib/api.js`
- Modify: `E:/Project/Agent/frontend/app/page.js`
- Test: `E:/Project/Agent/frontend/tests/ask-page.test.mjs`

- [ ] **Step 1: 先写前端失败测试，约束 Ask 页面渲染聊天与上下文区**

```javascript
test("ask page renders chat, context and command cards", () => {
  const html = renderAskPagePreview(buildAskViewModel());
  assert.match(html, /Ask/);
  assert.match(html, /当前候选人/);
  assert.match(html, /确认卡/);
});
```

- [ ] **Step 2: 运行前端测试确认失败**

Run: `node --test E:/Project/Agent/frontend/tests/ask-page.test.mjs`

Expected: FAIL，因为 `/ask` 页面和相关 view model 尚不存在。

- [ ] **Step 3: 增加 Ask API 客户端**

```javascript
export async function createAskSession(payload) {
  return fetchJson(`${API_BASE_URL}/api/v1/ask/sessions`, { method: "POST", body: JSON.stringify(payload) });
}
```

- [ ] **Step 4: 实现 Ask 页面与标准 outputs 渲染**

```javascript
export default function AskChat({ session, outputs }) {
  return outputs.map((item) => {
    if (item.type === "message") return <p key={item.id}>{item.text}</p>;
    if (item.type === "card") return <CommandCard key={item.id} item={item} />;
    if (item.type === "artifact") return <ArtifactCard key={item.id} item={item} />;
    return <ToolResultCard key={item.id} item={item} />;
  });
}
```

- [ ] **Step 5: 在首页增加 Ask 入口**

```javascript
<Link className="ghost-link" href="/ask">
  进入 Ask Copilot
</Link>
```

- [ ] **Step 6: 运行前端测试确认通过**

Run: `node --test E:/Project/Agent/frontend/tests/ask-page.test.mjs E:/Project/Agent/frontend/tests/dashboard.test.mjs`

Expected: PASS，Ask 页面、入口和卡片渲染通过。

### Task 8: 关键路径验证

**Files:**
- Modify: `E:/Project/Agent/backend/tests/test_ask_api.py`
- Modify: `E:/Project/Agent/frontend/tests/ask-page.test.mjs`

- [ ] **Step 1: 跑 Ask 相关后端测试**

Run: `& 'C:\Users\Hank\.conda\envs\emata\python.exe' -m unittest tests.test_ask_api tests.test_api_contract tests.test_upload_api -v`

Expected: PASS

- [ ] **Step 2: 跑前端测试**

Run: `node --test E:/Project/Agent/frontend/tests/ask-page.test.mjs E:/Project/Agent/frontend/tests/knowledge-page.test.mjs E:/Project/Agent/frontend/tests/dashboard.test.mjs`

Expected: PASS

- [ ] **Step 3: 跑前端构建**

Run: `npm run build`

Directory: `E:/Project/Agent/frontend`

Expected: Next.js build PASS

- [ ] **Step 4: 手工验证主链**

验证路径：
- 创建 Ask session
- “帮我看简历”时先追问岗位
- 补岗位后自动检索 JD 并输出简历分析
- 新候选人出现时先出切换卡
- 安排面试时无明确时间给 2-3 个时间推荐
- 反馈汇总默认生成 HR 私人文档
- 多轮协作执行先出统一确认卡，再执行工具动作
