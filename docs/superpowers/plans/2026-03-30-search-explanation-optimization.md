# Search Explanation Optimization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在不改动检索排序逻辑的前提下，让知识检索结果能解释“为什么命中”

**Architecture:** 后端在现有 `trace` 和 `item` 基础上补充最小解释字段，前端将这些字段转成用户可读摘要与逐条命中说明。当前阶段不引入 rerank，只优化可观测性与可解释性。

**Tech Stack:** Python, FastAPI, Pydantic, Next.js, node:test, unittest

---

## 文件结构

- Modify: `E:/Project/Agent/backend/app/contracts.py`
- Modify: `E:/Project/Agent/backend/app/integrations.py`
- Modify: `E:/Project/Agent/backend/app/routes.py`
- Modify: `E:/Project/Agent/backend/app/services.py`
- Modify: `E:/Project/Agent/backend/tests/test_api_contract.py`
- Modify: `E:/Project/Agent/frontend/components/knowledge-search-panel.js`
- Modify: `E:/Project/Agent/frontend/lib/knowledge.js`
- Modify: `E:/Project/Agent/frontend/tests/knowledge-page.test.mjs`

### Task 1: 定义检索解释契约

**Files:**
- Modify: `E:/Project/Agent/backend/tests/test_api_contract.py`
- Modify: `E:/Project/Agent/frontend/tests/knowledge-page.test.mjs`

- [ ] **Step 1: 先写后端失败测试，约束搜索结果返回解释字段**
- [ ] **Step 2: 运行后端测试确认失败**
- [ ] **Step 3: 先写前端失败测试，约束 trace 摘要和逐条命中说明**
- [ ] **Step 4: 运行前端测试确认失败**

### Task 2: 实现后端解释字段

**Files:**
- Modify: `E:/Project/Agent/backend/app/contracts.py`
- Modify: `E:/Project/Agent/backend/app/integrations.py`
- Modify: `E:/Project/Agent/backend/app/routes.py`
- Modify: `E:/Project/Agent/backend/app/services.py`

- [ ] **Step 1: 扩展搜索结果响应模型**
- [ ] **Step 2: 在检索层计算匹配 query variant 和 matched terms**
- [ ] **Step 3: 透传 parser/page_end 等定位解释字段**
- [ ] **Step 4: 运行后端测试确认通过**

### Task 3: 实现前端解释展示

**Files:**
- Modify: `E:/Project/Agent/frontend/lib/knowledge.js`
- Modify: `E:/Project/Agent/frontend/components/knowledge-search-panel.js`
- Modify: `E:/Project/Agent/frontend/tests/knowledge-page.test.mjs`

- [ ] **Step 1: 新增格式化函数，把 trace 和 item explanation 转成可读文案**
- [ ] **Step 2: 在搜索面板中展示本次检索解释和逐条命中原因**
- [ ] **Step 3: 运行前端测试确认通过**

### Task 4: 关键路径验证

**Files:**
- Modify: `E:/Project/Agent/backend/tests/test_api_contract.py`
- Modify: `E:/Project/Agent/frontend/tests/knowledge-page.test.mjs`

- [ ] **Step 1: 跑后端相关测试**
- [ ] **Step 2: 跑前端相关测试**
- [ ] **Step 3: 汇总验证结果与剩余风险**
