# EMATA Runtime

**Enterprise Memory-Augmented Task Agent**

EMATA Runtime🏠 是一个面向企业内部场景的 **Ask Runtime** 原型。它的目标不是做一个“会聊天的机器人”，而是把以下能力统一到一套可扩展运行时里：

- **Knowledge**：知识库管理、文档入库、检索、RAG 问答
- **Context**：多轮对话上下文、工作上下文、待确认动作草案
- **Agent**：意图路由、动作规划、预览、确认、执行
- **Tool Use**：Milvus、MinerU、Feishu、文档处理、外部模型 API

当前系统的两个核心入口：

- [`/knowledge`](./frontend/app/knowledge/page.js)：知识运营台
- [`/ask`](./frontend/app/ask/page.js)：统一对话入口

这两个入口页面分离，但底层共享同一套知识检索、上下文和工具能力。

---

## Why This Project

这个项目的重点不在“重新训练一个大模型”，而在于：

1. 把 **企业级 RAG** 做成可验证、可解释、可引用的链路
2. 把 **Context 管理** 从“聊天历史堆 prompt”提升成结构化运行时状态
3. 把 **Agent** 从“黑盒自动调用工具”收成可控的 `preview -> confirm -> execute`
4. 把 **多技能/多工具/多知识源扩展** 预留成模块边界，而不是写死在单一页面或单一业务里

这是一条更贴近企业内部落地的技术路线：

- 模型能力来自成熟 API
- 工程价值体现在 **Runtime、RAG、Context、Tool Orchestration**
- 面向的是“稳定、可维护、可扩展”的企业内工作流，而不是一次性的 demo

---

## Core Architecture

EMATA Runtime 的设计核心是把系统拆成 5 层：

### 1. Runtime

负责统一编排 Ask 会话生命周期。

核心职责：

- `Intent Router`
- `Turn / Command` 协调
- `Context` 读写
- `Knowledge QA` 与 `Action` 分流
- `Job / SSE` 执行状态同步

这一层的目标是：**把对话入口从具体业务中抽离出来**。

### 2. Skill

Skill 表示具体领域能力。当前先落地的是：

- `HR Recruiting Skill`

但系统并不是只为 HR 设计。当前架构已经把 Skill 当成独立层，后续可以继续接：

- Finance Skill
- Sales Skill
- Ops Coordination Skill

这部分的关键点是：**业务能力是可插拔的，不是写死在 Ask 页面里**。

### 3. Tool

Tool 表示外部能力适配层。当前重点接入：

- `Milvus`
- `MinerU`
- `lark-cli`
- DashScope-compatible model APIs

设计原则是：

- Skill 不直接拼底层命令
- Tool 只暴露受控能力
- 外部 provider 可替换

### 4. Knowledge

Knowledge 层负责：

- 文档上传
- 结构化切块
- 向量索引
- 检索 trace
- RAG 输入准备

这一层同时服务：

- `/knowledge` 管理台
- `/ask` 问答入口

### 5. Policy

Policy 层负责控制风险和执行边界。

当前最重要的机制是：

- 中高风险动作先预览
- 用户确认后再执行
- 不把高风险动作直接交给模型自由执行

这部分是企业 Agent 非常关键的一层。

---

## RAG Orchestration

项目里的 RAG 不是“直接把文档喂给模型”，而是分层编排：

```text
User Question
-> Intent Router
-> Knowledge Search
-> Rerank
-> Context Packing
-> Answer Generation
-> Answer + Citations
```

### 检索链路

当前链路是：

- `embedding`: `text-embedding-async-v1`
- `vector store`: `Milvus`
- `rerank`: `qwen3-rerank`
- `generation`: `qwen3.5-flash`

### 回答模式

Ask 当前支持两类回答模式：

#### 1. Grounded RAG

适用于企业私有知识问题，例如：

- 报销额度
- 审批流程
- HR 制度
- 项目内部文档内容

特点：

- 先检索，再 rerank，再回答
- 返回 `answer + citations`
- 证据不足时拒答或明确说明证据不足

#### 2. General LLM

适用于一般常识问题，例如：

- 多模态是什么
- Agent 是什么
- RAG 和 fine-tuning 的区别

特点：

- 不依赖企业知识库
- 不冒充企业内部知识结论

### 为什么这样做

这样拆的意义是：

- 企业知识问题尽量低幻觉
- 常识问题也能正常回答
- 不会把“企业制度”和“模型常识”混成一类答案

---

## Context Management

这个项目没有把上下文简单理解成“把所有历史消息继续喂给模型”。
我把上下文拆成了 3 层：

### 1. Conversation Memory

最近几轮自然语言对话。

作用：

- 连续追问
- 保持短期对话连贯

### 2. Working Context

当前工作状态，例如：

- 当前候选人
- 当前岗位 / JD
- 上一轮可分享结论
- 当前目标群 / 联系人
- 当前检索模式

作用：

- 支撑 Ask 的多轮工作流
- 避免所有逻辑都靠 prompt 回忆

### 3. Pending Action Draft

当前待确认动作草案，例如：

- 目标对象
- 消息正文
- 会议时间
- 风险级别

作用：

- 让 `preview -> confirm -> execute` 成为结构化链路
- 防止线程中断时动作状态丢失

### 设计价值

这种拆法的价值是：

- 不会把历史消息无上限塞进 prompt
- 不会把知识状态和动作状态混在一起
- 更适合做企业级 Ask Runtime，而不是普通 Chat UI

---

## Agent Execution Model

项目里的 Agent 重点不在“全自动”，而在 **可控执行**。

核心链路：

```text
Intent Router
-> Action Planner
-> Target Resolver
-> Preview Card
-> Confirm / Cancel
-> Tool Execute
-> Result / Trace
```

### 为什么不直接执行

企业内部动作天然带风险，例如：

- 发群消息
- 发联系人消息
- 创建会议
- 共享文档

如果模型直接执行，容易出现：

- 目标解析错误
- 正文串位
- 上下文误解
- 错误消息被发出去

因此当前系统统一采用：

- `preview`
- `confirm`
- `execute`

这使它更接近企业真正需要的 Agent，而不是黑盒自动化。

---

## Tooling and Integrations

### Milvus

知识检索已真实接入 Milvus。当前 `/knowledge` 页面可以直接看到索引状态，验证不是 fallback 检索，而是：

- `backend_mode = sdk`

### MinerU

PDF 解析通过 MinerU 接入。当前支持：

- 有效 PDF 真实解析入库
- 无效 PDF 快速失败
- Windows 文件名边界修复

### Feishu

当前重点接通的是企业内部协同：

- 群消息
- 日程邀请
- 绑定状态与权限检查

当前明确保留边界：

- 外部联系人
- 外部群
- 高风险自动执行

这样做是有意为之：先把内部稳定能力做通。

---

## Current Demo Scenarios

### Demo 1: Grounded RAG

在 `/ask` 输入：

```text
报销标准额度是多少
```

继续追问：

```text
超过3000元怎么办
```

展示点：

- search -> rerank -> answer -> citations
- grounded 模式
- 连续追问

### Demo 2: Context Reuse + Group Messaging

先输入：

```text
报销标准额度是多少
```

再输入：

```text
把刚才的结论发到 Ai应用开发群
```

展示点：

- working context
- preview / confirm / execute
- Feishu 内部群消息

### Demo 3: Dialog-driven Coordination

输入：

```text
下午五点在 Ai应用开发群开会！
```

展示点：

- 通用动作解析
- 目标解析
- 预览确认
- 日程执行

---

## Tech Stack

### Backend

- FastAPI
- SQLAlchemy
- SQLite / PostgreSQL snapshot persistence
- Milvus
- MinerU
- `lark-cli`

### Frontend

- Next.js
- View Model / API Adapter 模式

### Models

- DashScope-compatible API
- `text-embedding-async-v1`
- `qwen3-rerank`
- `qwen3.5-flash`

---

## Repository Structure

```text
.
├─ backend/
│  ├─ app/
│  └─ tests/
├─ frontend/
│  ├─ app/
│  ├─ components/
│  ├─ lib/
│  └─ tests/
├─ docs/
│  └─ superpowers/
├─ infra/
├─ scripts/
├─ docker-compose.yml
├─ .env.example
└─ README.md
```

---

## Local Development

### Option A: Local App + Docker Middleware

适合调试和开发：

1. 启动 Docker Desktop
2. 让 Milvus / MinIO / etcd 等中间件运行
3. 本地启动后端
4. 本地启动前端

后端：

```powershell
cd E:\Project\Agent\backend
C:\Users\Hank\.conda\envs\emata\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

前端：

```powershell
cd E:\Project\Agent\frontend
npm run dev
```

### Option B: Full Docker

```powershell
docker compose up --build
```

默认入口：

- API: [http://127.0.0.1:8000](http://127.0.0.1:8000)
- Ask: [http://127.0.0.1:3000/ask](http://127.0.0.1:3000/ask)
- Knowledge: [http://127.0.0.1:3000/knowledge](http://127.0.0.1:3000/knowledge)
- Temporal UI: [http://127.0.0.1:8088](http://127.0.0.1:8088)

---

## Key Environment Variables

See [`.env.example`](./.env.example).

### Model / RAG

- `EMATA_MODEL_BASE_URL`
- `EMATA_MODEL_API_KEY`
- `EMATA_MODEL_NAME`
- `EMATA_RERANK_BASE_URL`
- `EMATA_RERANK_API_KEY`
- `EMATA_RERANK_MODEL`
- `EMATA_EMBEDDING_BASE_URL`
- `EMATA_EMBEDDING_API_KEY`
- `EMATA_EMBEDDING_MODEL`

### Knowledge

- `EMATA_MILVUS_URI`
- `EMATA_MILVUS_COLLECTION`
- `EMATA_UPLOAD_BASE_DIR`
- `EMATA_STORAGE_BACKEND`
- `EMATA_MINERU_EXECUTABLE`

### Feishu飞书

- `EMATA_FEISHU_APP_ID`
- `EMATA_FEISHU_APP_SECRET`
- `EMATA_DEFAULT_INTERNAL_CHAT_QUERY`

---

## Current Boundaries

当前项目最适合展示的是：

- 企业知识问答
- Milvus + Rerank + Answer Generation
- 多轮上下文管理
- 可控 Agent 执行链
- 内部群消息与日程

当前有意不把这些能力包装成“已完全解决”：

- 外部联系人自动私聊
- 外部群复杂协同
- 高风险动作全自动执行
- 完整生产级权限治理

这不是缺陷掩盖，而是有意识的系统边界设计。

---

## Why This Project Is Strong for Interviews

这个项目对技术面试官的价值，不在于“有没有自己训练一个大模型”，而在于：

- 把 **RAG、Context、Agent、Tool Use** 做成了统一运行时
- 模块之间有边界，而不是把所有逻辑塞进一个页面或一个 prompt
- 既能展示系统设计，也能展示真实集成和工程落地

如果要一句话概括：

> EMATA Runtime 是一个企业内部 Ask Runtime，把知识问答、上下文管理和可控工具执行统一到同一套模块化架构里。

---

## Roadmap

- 更强的 Intent Router
- 更通用的 Action Planner
- 更稳定的 Target Resolver
- Async execution + SSE
- 更完整的 trace / observability
- 更多企业工具与 Skill 扩展

---

## License

当前仓库未附带开源许可证。
如需对外长期公开，建议补充 License，并在公开前再次确认本地敏感配置和运行时文件未被提交。
