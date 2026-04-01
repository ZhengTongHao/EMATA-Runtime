# Ask HR Recruiting Copilot 设计说明

## 目标

为 EMATA 增加一个面向 HR 招聘协同的 `Ask` 对话入口，使用户可以在同一个多轮聊天线程里完成：

1. 看简历并生成候选人分析建议
2. 安排面试与内部协同
3. 汇总面试反馈并生成文档
4. 推进录用相关的内部沟通
5. 执行跨场景的多轮协作任务，例如“先生成沟通提纲，再约会并发给内部同事”

本设计同时要求具备高扩展性，支持未来在不推翻底层架构的情况下：

- 新增更多领域的 `Skill`
- 接入新的 `Tool`
- 参考或吸收外部开源 Skill 的设计思路

## 非目标

本期明确不做以下内容：

1. 不直接给候选人发消息或通知候选人
2. 不做“硬门槛筛选确认卡”和规则先筛流程
3. 不实现多个领域 Skill 的同时运行，第一版只落地 `HR Recruiting Skill`
4. 不把 `lark-cli` 直接暴露给模型拼接任意命令
5. 不做候选人专属页面，第一版仍以通用聊天线程为中心
6. 不做完整插件市场或远程加载能力

## 产品定位

`Ask` 页第一版定位为 **HR Recruiting Copilot**，但底层必须采用通用 `Skill Runtime`。

对用户而言：

- 它是一个多轮聊天线程
- 线程内可以随时切换候选人和任务
- 可以输出答案、建议、引用、文档、确认卡和执行结果

对系统而言：

- 它不是一个硬编码 HR 页面
- 它是通用 `Ask` 运行时上挂载的一个 `hr_recruiting` 领域 Skill

## 核心设计原则

1. `Skill-first`
- 领域逻辑由 Skill 承担
- 第一版只实现 `HR Recruiting Skill`

2. `Tool-pluggable`
- 外部能力全部封装成 Tool
- `lark-cli` 只是一个 Tool Adapter
- 未来可以替换或新增更多 Tool

3. `API-domain-agnostic`
- Ask API 不绑定 HR 路径
- HR 只是会话元数据中的 `skill_id`

4. `Memory-aware`
- 支持多轮上下文
- 线程内维护当前候选人、岗位和 JD 上下文

5. `Policy-governed`
- 低风险动作直接执行
- 高风险动作统一确认
- 风险判断独立于 Skill 和 Tool

## 整体架构

### 顶层组件

1. `Ask Web Page`
- 前端聊天页面
- 负责渲染统一输出块和触发命令

2. `Ask API`
- 提供 `Session + Turn + Command + Artifact` 通用接口

3. `Skill Runtime`
- 统一执行 Skill 生命周期
- 统一拼装上下文、调用 Tool、回写状态

4. `Skill Registry`
- 注册多个 Skill
- 第一版只注册 `hr_recruiting`

5. `Tool Registry`
- 注册 Tool 适配器
- 第一版包含 `lark_cli_tool` 及招聘场景需要的辅助 Tool

6. `Memory Runtime`
- 管理会话记忆、候选人上下文、岗位上下文

7. `Policy / Risk Engine`
- 判断动作风险等级
- 决定直接执行或返回确认卡

8. `Executor Runtime`
- 统一执行 Tool Plan
- 记录执行结果与审计日志

### 设计结论

本期不采用“一个大 Prompt 直接回答 + 直接调 CLI”的方案，而采用：

```text
Ask Page
-> Ask API
-> Skill Runtime
-> HR Recruiting Skill
-> Tool Registry / Memory Runtime / Policy Engine
-> Tool Execution
-> Standard Outputs
```

## Skill Runtime

### 会话级概念

每个会话只绑定一个主 Skill：

- `skill_id = hr_recruiting`

未来如果新增别的 Skill，例如：

- `finance_ops`
- `sales_enablement`
- `internal_coordination`

只需要在 `Skill Registry` 中增加注册项，不修改 Ask API。

### Skill 输入协议

每次 `turn` 或 `command` 执行前，Skill Runtime 向 Skill 提供统一输入：

- `user_message`
- `session_context`
- `memory_snapshot`
- `domain_context`
- `available_tools`
- `policy_context`

### Skill 输出协议

每次执行后，Skill 只允许输出以下标准结果：

- `answer`
- `clarification`
- `tool_plan`
- `confirmation_request`
- `final_result`

为了给前端稳定渲染，Skill Runtime 最终统一转换为：

- `message`
- `citation`
- `card`
- `artifact`
- `tool_result`

### State Patch

Skill 不能直接重写整个会话状态，只能输出增量 `state_patch`。

第一版允许更新的状态包括：

- `active_candidate`
- `active_position`
- `active_jd`
- `active_skill_state`
- `last_tool_result`
- `last_generated_artifact`

## Tool Runtime

### Tool 设计原则

Tool 只负责执行能力，不负责领域推理。

模型和 Skill 都不能直接生成原始 CLI 命令；必须先生成结构化 `Tool Plan`，再由 Tool Adapter 转换为底层调用。

### Tool 协议

每个 Tool 必须实现以下接口：

- `describe()`
- `validate(input)`
- `dry_run(input)`
- `execute(input)`
- `normalize(output)`

### 第一版 Tool 列表

1. `lark_cli_tool`
- 基于 `lark-cli` 执行飞书侧动作

2. `resume_fetch_tool`
- 根据飞书链接、卡片或候选人搜索结果获取简历来源

3. `resume_parse_tool`
- 解析简历文件，输出结构化简历摘要

4. `knowledge_search_tool`
- 检索岗位说明、制度和内部知识

5. `rerank_tool`
- 对候选证据进行重排

6. `doc_generate_tool`
- 生成反馈文档、协作纪要等文档产物

### lark-cli 的位置

`lark-cli` 在架构中严格作为 Tool 使用：

- 做 `dry-run`
- 做正式执行
- 做结果标准化

不承担以下职责：

- 领域意图理解
- 风险判断
- 会话状态更新

## Ask API

### 设计目标

Ask API 必须是领域无关的通用接口，不能把 HR 逻辑写死到路由结构里。

### 推荐接口

1. `POST /api/v1/ask/sessions`
- 创建会话
- 请求体可包含：
  - `skill_id`
  - `title`
  - `initial_context`

2. `GET /api/v1/ask/sessions/{session_id}`
- 获取会话元信息和上下文摘要

3. `GET /api/v1/ask/sessions/{session_id}/turns`
- 获取消息流

4. `POST /api/v1/ask/sessions/{session_id}/turns`
- 发起一次用户输入
- 返回统一 `TurnResult`

5. `POST /api/v1/ask/sessions/{session_id}/commands`
- 处理确认、选项点击、上下文切换等命令式交互

6. `GET /api/v1/ask/sessions/{session_id}/artifacts`
- 获取会话中生成的文档、分析结果、执行记录

### Command 类型

第一版保留以下通用命令：

- `confirm`
- `cancel`
- `select_option`
- `switch_context`
- `retry`
- `approve_plan`

### TurnResult 协议

`POST /turns` 和 `POST /commands` 都返回统一结构：

- `turn`
- `outputs`
- `state_patch`
- `pending_commands`

其中 `outputs` 为块级输出列表，元素类型限定为：

- `message`
- `citation`
- `card`
- `artifact`
- `tool_result`

## 数据模型

### AskSession

- `id`
- `user_id`
- `skill_id`
- `title`
- `status`
- `summary`
- `active_context`
- `created_at`
- `updated_at`

### AskTurn

- `id`
- `session_id`
- `role`
- `input_type`
- `content`
- `created_at`

### AskCommand

- `id`
- `session_id`
- `turn_id`
- `command_type`
- `payload`
- `created_at`

### AskArtifact

第一版支持以下类型：

- `resume_summary`
- `candidate_analysis`
- `interview_plan`
- `feedback_summary`
- `generated_doc`
- `action_execution_record`

### Active Context

会话里需要维护一个轻量的领域上下文：

- `active_candidate`
- `active_position`
- `active_jd`
- `active_skill_state`

### Candidate Context

`active_candidate` 至少包含：

- `candidate_id`
- `candidate_name`
- `resume_source`
- `target_position`
- `jd_source`
- `latest_resume_summary_id`
- `latest_feedback_doc_id`
- `latest_interview_plan_id`

## Memory 设计

### 短期记忆

短期记忆用于支持多轮聊天，主要包含：

- 最近对话轮次
- 上轮候选人分析
- 上轮动作执行结果
- 当前候选人、岗位、JD 绑定

### 长期记忆

长期记忆只保存提炼后的用户偏好和习惯，不保存整段原始聊天：

- 默认语言
- 常用岗位
- 常用招聘群
- 常用面试官
- 文档输出偏好

### 设计结论

第一版重点依赖短期记忆；长期记忆只保留最小实现，不作为主卖点。

## HR Recruiting Skill

### 设计目标

`HR Recruiting Skill` 负责招聘协同场景下的任务理解、上下文维护、知识问答、动作规划与输出组合。

第一版聚焦以下能力：

1. 看简历
2. 候选人分析建议
3. 安排面试
4. 汇总面试反馈并生成文档
5. 录用推进的内部协同
6. 多轮协作执行

### 内部状态

Skill 内部采用轻状态机：

- `idle`
- `resume_intake`
- `resume_analysis`
- `interview_coordination`
- `feedback_synthesis`
- `offer_progress`
- `waiting_confirmation`
- `executing`
- `completed`

状态只用于帮助 Skill 判断下一步，不向前端暴露领域内部复杂状态图。

## 线程与上下文规则

### 通用聊天线程

第一版采用 **通用聊天线程**，不使用“一候选人一线程”模型。

### 候选人切换

线程中提到新的候选人时，不自动切换。

规则如下：

1. 若识别到新的候选人姓名或新的飞书简历链接
2. 且与当前 `active_candidate` 不一致
3. 返回小卡片：
   - `切换到候选人 XXX 吗？`
4. 用户确认后才更新 `active_candidate`

### 岗位与 JD 规则

当用户提出“看简历”时：

1. 若没有岗位上下文，先追问岗位
2. 岗位确定后，先自动检索对应 JD
3. 若自动检索失败，再追问 HR 补充 JD 或岗位要求

## 主业务链

### 1. 看简历

入口支持两种方式：

1. 贴飞书链接或消息卡片
2. 输入候选人姓名

处理顺序：

1. 优先识别飞书链接/卡片
2. 否则按姓名搜索候选人
3. 若没有岗位上下文，先追问岗位
4. 自动检索 JD，找不到再追问 HR
5. 调用：
   - `resume_fetch_tool`
   - `resume_parse_tool`
   - `knowledge_search_tool`
   - `rerank_tool`
6. 输出：
   - 简历摘要
   - 岗位匹配分析
   - 亮点与风险点

输出块应包含：

- `message`
- `artifact: resume_summary`
- `artifact: candidate_analysis`

### 2. 候选人分析建议

第一版不做规则先筛和硬门槛卡。

候选人分析采用：

- 简历解析结果
- 岗位 / JD
- LLM 综合分析

输出内容包括：

- 匹配摘要
- 亮点
- 风险点
- 建议是否进入下一轮

最终决定仍由 HR 做出。

### 3. 安排面试

输入通常包括：

- 候选人
- 面试官或面试角色
- 时间诉求

处理规则：

1. 若候选人不明确，先确认上下文
2. 若时间不明确或冲突，先给 HR 推荐 `2-3` 个可选时间
3. 推荐时间通过 `card` 输出
4. HR 选择时间后，生成 `interview_plan`
5. 由于涉及他人会议，进入确认流

执行后输出：

- `artifact: interview_plan`
- `tool_result`

### 4. 面试反馈汇总

输入通常包括：

- 当前候选人
- 多位面试官反馈

处理步骤：

1. 汇总反馈
2. 提炼共识、亮点、风险、分歧点
3. 默认生成一份反馈汇总文档

文档默认生成位置：

- HR 自己的云文档空间

如果只是生成到 HR 私人空间，可视为低风险动作。

输出：

- `message`
- `artifact: feedback_summary`
- `artifact: generated_doc`

### 5. 录用推进

第一版只做内部协同，不直接联系候选人。

支持的动作包括：

- 向招聘群发送内部总结
- 通知面试官或 HRBP
- 生成内部录用推进建议

如果涉及多人可见消息，统一进入确认流。

### 6. 多轮协作执行

这条链覆盖招聘协同之外的内部协作场景，例如：

- 用户：`帮我准备和李雷的预算评审沟通`
- 系统：检索背景信息并生成提纲
- 用户：`那就约他明天下午 3 点开 30 分钟会，并把刚才的提纲发给他`

处理方式：

1. Skill 识别为 `问答 + 动作`
2. 生成两个动作：
   - 建会议
   - 发消息
3. 第二个动作依赖第一个动作结果，例如会议链接
4. 统一进入确认卡
5. 用户确认后顺序执行

输出：

- `card: confirmation`
- `tool_result`
- `artifact: action_execution_record`

## 风险与确认流

### 风险等级

内部使用三档风险：

- `low`
- `medium`
- `high`

对用户只表现成两种行为：

- 低风险直接执行
- 中高风险统一确认

### 低风险动作

- 读取简历和 JD
- 生成简历分析
- 生成 HR 自己的反馈文档
- 查询联系人、忙闲和内部资料

### 需要确认的动作

- 给他人发消息
- 给招聘群发消息
- 给他人建会议或邀请多人参会
- 任何多人可见写操作

### 统一确认卡

确认卡必须展示：

- 将执行的动作列表
- 目标对象
- 时间信息
- 消息预览
- 风险原因
- 相关候选人或上下文

第一版不做“每个动作单独确认”，而是采用统一确认卡。

## lark-cli Tool 设计

### 封装原则

`lark-cli` 不直接暴露给 Skill。

第一版通过 `lark_cli_tool` 做统一适配，内部流程为：

1. `validate`
2. `dry_run`
3. `risk_check`
4. `execute`
5. `normalize`

### 第一版使用边界

第一版重点使用 `lark-cli` 完成：

- 内部消息发送
- 联系人解析
- 日历与会议安排
- 文档生成与保存

不做：

- 候选人外发消息
- 任意自由命令执行
- 未经白名单的 CLI 子命令暴露

## 前端交互

### 页面布局

建议 `Ask` 页采用三段式布局：

1. 主聊天区
- 展示回答、分析、执行结果

2. 上下文区
- 当前候选人
- 当前岗位
- 当前 JD 来源

3. 卡片区
- 候选人切换卡
- 时间推荐卡
- 统一确认卡

### 前端原则

前端只做两件事：

1. 渲染标准 `outputs`
2. 触发 `commands`

前端不自己推断领域状态。

## 可扩展性设计

### 第一版限制

尽管第一版只实现 `HR Recruiting Skill`，但必须从第一天按多 Skill 架构设计：

- Ask API 通用
- Skill Registry 存在
- Tool Registry 存在
- Policy Engine 独立

### 后续扩展方式

后续新增领域能力时，优先采用以下扩展路径：

1. 新增 Tool，复用现有 Runtime
2. 基于现有 Runtime 新增 Skill
3. 参考外部开源 Skill 的 prompt、workflow 或 schema，将其映射到现有 Skill 协议中

明确不建议直接把外部 Skill 当作黑盒运行时依赖。

## 结论

本设计将 `Ask` 页落成一个通用的 `Skill Runtime`，并在第一版仅挂载 `HR Recruiting Skill`。

它满足以下要求：

- 支持多轮 HR 招聘协同
- 保留问答与检索能力
- 使用 `lark-cli` 作为受控 Tool
- 通过统一 API、统一输出块和统一确认流保证前后端稳定
- 为未来新增更多 Tool 与更多领域 Skill 留出清晰扩展路径

第一版的核心价值不是“做一个能聊天的页面”，而是建立：

- 一套通用 Ask Runtime
- 一个可落地的 HR Recruiting Skill
- 一组可替换、可扩展的 Tool 边界

这将成为后续更多领域 Copilot 的基础。
