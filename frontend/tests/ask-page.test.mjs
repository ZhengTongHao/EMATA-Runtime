import test from "node:test";
import assert from "node:assert/strict";

import {
  buildActionPreviewModel,
  buildTargetSelectionModel,
  buildAskPageViewModel,
  formatAskOutputLabel,
  formatAskJobStatus,
  formatFeishuBindingHint,
  formatFeishuBindingStatus,
  formatToolResultError,
  getTargetSelectionOptions,
  partitionTurnOutputs,
  renderAskPagePreview,
} from "../lib/ask.js";

test("ask page view model exposes generic ask copy without sample prompts", () => {
  const viewModel = buildAskPageViewModel();

  assert.match(viewModel.title, /Ask/i);
  assert.equal(viewModel.samplePrompts.length, 0);
  assert.match(viewModel.emptyState, /自然语言/);
});

test("target selection helper returns candidates and keeps other option", () => {
  const output = {
    type: "card",
    data: {
      card_type: "target_selection",
      options: [
        { kind: "user", label: "李雷", value: "ou_li_lei" },
        { kind: "chat", label: "Ai应用开发群", value: "oc_ai_group" },
        { kind: "other", label: "其他", value: "" },
      ],
    },
  };

  const options = getTargetSelectionOptions(output);
  assert.equal(options.length, 3);
  assert.equal(options[2].kind, "other");
});

test("target selection model exposes grouped contact and chat search results", () => {
  const model = buildTargetSelectionModel({
    type: "card",
    data: {
      card_type: "target_selection",
      options: [
        { kind: "chat", label: "Ai应用开发群", value: "oc_ai_group" },
        { kind: "other", label: "其他", value: "" },
      ],
      search_results: {
        contacts: [{ kind: "user", label: "李雷", value: "ou_li_lei" }],
        chats: [{ kind: "chat", label: "Ai应用开发群", value: "oc_ai_group" }],
      },
    },
  });

  assert.equal(model.contacts.length, 1);
  assert.equal(model.contacts[0].label, "李雷");
  assert.equal(model.chats.length, 1);
  assert.equal(model.chats[0].label, "Ai应用开发群");
  assert.equal(model.otherOption.kind, "other");
});

test("action preview helper exposes editable fields and selected target", () => {
  const model = buildActionPreviewModel({
    type: "card",
    data: {
      card_type: "action_preview",
      editable: true,
      draft: {
        summary: "发送消息给 Ai应用开发群",
        text: "这个候选人不错",
        target_query: "Ai应用开发群",
        resolved_target: { kind: "chat", label: "Ai应用开发群", value: "oc_ai_group" },
        editable_fields: ["target", "text"],
        actions: [{ capability: "message.send", summary: "发送消息给 Ai应用开发群" }],
      },
    },
  });

  assert.equal(model.editable, true);
  assert.equal(model.targetLabel, "Ai应用开发群");
  assert.equal(model.text, "这个候选人不错");
  assert.deepEqual(model.editableFields, ["target", "text"]);
});

test("target selection helper keeps other option so cancel can be rendered alongside it in card UI", () => {
  const output = {
    type: "card",
    data: {
      card_type: "target_selection",
      options: [{ kind: "other", label: "其他", value: "" }],
    },
  };

  const options = getTargetSelectionOptions(output);
  assert.equal(options.length, 1);
  assert.equal(options[0].kind, "other");
});

test("ask page preview renders hero without sample prompts", () => {
  const html = renderAskPagePreview(buildAskPageViewModel());

  assert.match(html, /Ask/);
  assert.doesNotMatch(html, /aside/i);
});

test("ask output label formats standard output types", () => {
  assert.equal(formatAskOutputLabel("message"), "答复");
  assert.equal(formatAskOutputLabel("citation"), "引用");
  assert.equal(formatAskOutputLabel("card"), "确认卡");
  assert.equal(formatAskOutputLabel("tool_result"), "执行结果");
});

test("binding status formatter covers unbound pending and active states", () => {
  assert.equal(formatFeishuBindingStatus(null), "未绑定");
  assert.equal(formatFeishuBindingStatus({ status: "PENDING" }), "绑定中");
  assert.equal(formatFeishuBindingStatus({ status: "REAUTH_REQUIRED" }), "需要重新授权");
  assert.equal(
    formatFeishuBindingStatus({
      status: "ACTIVE",
      identity: { user_name: "测试 HR" },
    }),
    "已绑定：测试 HR",
  );
});

test("binding hint explains pending and missing scopes", () => {
  assert.match(formatFeishuBindingHint({ status: "PENDING" }), /完成授权/);
  assert.match(
    formatFeishuBindingHint({
      status: "ACTIVE",
      missing_scopes: ["calendar:calendar.event:create"],
    }),
    /calendar:calendar.event:create/,
  );
});

test("binding hint calls out chat read scope for group collaboration", () => {
  assert.match(
    formatFeishuBindingHint({
      status: "ACTIVE",
      missing_scopes: ["im:chat:read"],
    }),
    /im:chat:read/,
  );
});

test("binding hint explains reauth required and external contact message scope", () => {
  assert.match(
    formatFeishuBindingHint({
      status: "REAUTH_REQUIRED",
      hint: "当前飞书授权不可用，请重新授权或切换账号后再继续。",
    }),
    /重新授权/,
  );
  assert.match(
    formatFeishuBindingHint({
      status: "ACTIVE",
      missing_scopes: ["search:message"],
    }),
    /search:message/,
  );
});

test("tool result error formatter surfaces readable failure details", () => {
  assert.match(
    formatToolResultError({
      data: {
        result: {
          status: "failed",
          error_message: "机器人可能不在目标群里，或这个群当前对应用不可见。",
        },
      },
    }),
    /机器人可能不在目标群里/,
  );
});

test("job status formatter exposes readable backend execution labels", () => {
  assert.equal(formatAskJobStatus("pending"), "排队中");
  assert.equal(formatAskJobStatus("running"), "执行中");
  assert.equal(formatAskJobStatus("finished"), "已完成");
});

test("turn outputs partition citations behind primary answer content", () => {
  const outputs = [
    { type: "message", text: "答案" },
    { type: "citation", text: "引用 1" },
    { type: "citation", text: "引用 2" },
    { type: "tool_result", text: "执行结果" },
  ];

  const grouped = partitionTurnOutputs(outputs);

  assert.deepEqual(
    grouped.primaryOutputs.map((item) => item.type),
    ["message", "tool_result"],
  );
  assert.deepEqual(
    grouped.citationOutputs.map((item) => item.text),
    ["引用 1", "引用 2"],
  );
});
