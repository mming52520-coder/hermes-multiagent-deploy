const assert = require("node:assert/strict");
const { readFileSync } = require("node:fs");
const { createRequire } = require("node:module");
const path = require("node:path");
const { afterEach, beforeEach, test } = require("node:test");

// Reuse the pinned native frontend's existing React/jsdom dependencies.
process.env.NODE_ENV = "development";
assert.ok(process.env.HERMES_FRONTEND_SOURCE, "Set HERMES_FRONTEND_SOURCE to the pinned Hermes source with prepared web dependencies");
const requireWeb = createRequire(path.resolve(process.env.HERMES_FRONTEND_SOURCE, "web/package.json"));
const React = requireWeb("react");
const { JSDOM } = requireWeb("jsdom");
const source = readFileSync(path.join(__dirname, "../plugins/workflow/dashboard/app.js"), "utf8");
const roles = ["researcher", "builder", "reviewer", "orchestrator"];
const firstId = "a".repeat(32), secondId = "b".repeat(32);
let view;

function execution(id = firstId, statuses = ["triage", "triage", "triage", "triage"]) {
  return {
    execution_id: id, objective: id === firstId ? "目标一 / Objective one" : "目标二 / Objective two",
    board: "default", created_at: 1700000000, approved_write: false,
    source_revision: "c".repeat(40), changed_files: [], failures: [],
    rounds: [{ number: 0, tasks: Object.fromEntries(roles.map((role, i) => [role, {
      id: id + "-" + role, status: statuses[i], assignee: role, outcome: null,
    }])) }],
    acceptance: { status: "NOT_ACCEPTED", reason: "WRITE_NOT_APPROVED" },
    budget: { max_rounds: 2, max_seconds: 600, max_runs: 4 },
    readiness: { ready: true, checks: [] },
  };
}

function deferred() {
  let resolve;
  const promise = new Promise((done) => { resolve = done; });
  return { promise, resolve };
}

beforeEach(async () => {
  const dom = new JSDOM('<!doctype html><div id="app"></div>', { url: "http://localhost/" });
  const document = dom.window.document, container = document.getElementById("app");
  Object.assign(global, { window: dom.window, document, IS_REACT_ACT_ENVIRONMENT: true });
  const { createRoot } = requireWeb("react-dom/client");
  const locale = React.createContext({ locale: "zh" });
  const timers = new Map(), overrides = new Map(), requests = [];
  const server = { actions_enabled: false, records: [execution()], proofs: { builder: { available: false }, reviewer: { available: false } } };
  let App;
  dom.window.__HERMES_PLUGIN_SDK__ = {
    React, useI18n: () => React.useContext(locale),
    fetchJSON: async (url, init) => {
      const route = url.replace("/api/plugins/workflow", "");
      requests.push({ route, init });
      if (overrides.has(route)) return overrides.get(route)(init);
      if (route === "/meta") return { actions_enabled: server.actions_enabled, project_name: "synthetic-project", board: "default", readiness: server.readiness, model_connections_supported: server.model_connections_supported, conversation_supported: server.conversation_supported, architect_supported: server.architect_supported };
      if (route === "/architect") return structuredClone(server.architect);
      if (route === "/conversations") return { conversations: server.conversations || [] };
      if (route.startsWith("/conversations/")) return structuredClone(server.conversation);
      if (route.endsWith("/activity")) return structuredClone(server.activity || { events: [], roles: {}, workflow_state: "WAITING_APPROVAL" });
      if (route.startsWith("/model-connection")) return structuredClone(server.modelConnections);
      if (route === "/executions") return { executions: structuredClone(server.records) };
      if (route.includes("/evidence/")) return structuredClone(server.proofs[route.split("/").at(-1)]);
      const record = server.records.find((item) => route === "/executions/" + item.execution_id);
      if (record) return structuredClone(record);
      throw new Error("Unexpected request: " + route);
    },
  };
  dom.window.__HERMES_PLUGINS__ = { register: (name, component) => { assert.equal(name, "workflow"); App = component; } };
  new Function("window", "document", "setInterval", "clearInterval", source)(dom.window, document,
    (callback, period) => { const id = Symbol(); timers.set(id, { callback, period }); return id; },
    (id) => timers.delete(id));
  const root = createRoot(container);
  view = {
    dom, container, root, timers, overrides, requests, server,
    render: async (language = "zh") => React.act(async () => root.render(
      React.createElement(locale.Provider, { value: { locale: language } }, React.createElement(App)))),
    click: async (element) => { assert.ok(element, "Expected a visible control"); await React.act(async () => element.click()); },
    input: async (element, value) => React.act(async () => {
      element.value = value;
      element.dispatchEvent(new dom.window.Event(element.tagName === "SELECT" ? "change" : "input", { bubbles: true }));
    }),
    poll: async () => React.act(async () => {
      for (const { callback, period } of [...timers.values()]) { assert.ok([2000, 20000].includes(period)); await callback(); }
    }),
    refresh: async () => React.act(async () => { for (const { callback } of [...timers.values()]) void callback(); }),
    openDetails: async () => { if (!container.querySelector(".wf-tabs")) await view.click(container.querySelector('[aria-label="详细记录"]')); },
    openSettings: async () => view.click(container.querySelector('.wf-header [aria-controls="wf-model-settings"]')),
    button: (text, selector = "button") => [...container.querySelectorAll(selector)].find((item) => item.textContent.trim() === text),
  };
});

afterEach(async () => {
  await React.act(async () => view.root.unmount());
  assert.equal(view.timers.size, 0, "Unmount must stop polling");
  view.dom.window.close();
});

test("ready and dependency-waiting executions are not labelled as awaiting approval", async () => {
  view.server.records = [execution(firstId, ["done", "ready", "triage", "triage"]), execution(secondId, ["done", "todo", "triage", "triage"])];
  await view.render();
  const labels = [...view.container.querySelectorAll(".wf-execution .wf-badge")].map((item) => item.textContent);
  assert.deepEqual(labels, ["待执行", "等待依赖"]);
});

test("blocked tasks stay visible without dashboard metrics or filter buttons", async () => {
  const missing = execution(secondId); missing.rounds = [];
  view.server.records = [execution(firstId, ["running", "blocked", "triage", "triage"]), missing];
  await view.render();
  assert.equal(view.container.querySelectorAll(".wf-execution").length, 2);
  assert.ok([...view.container.querySelectorAll(".wf-execution .wf-badge")].every(item => item.textContent === "需要关注"));
  assert.equal(view.container.querySelector(".wf-metrics"), null);
  assert.equal(view.container.querySelector(".wf-filters"), null);
});

test("polling updates the selected detail and evidence without resetting the active tab", async () => {
  await view.render();
  await view.openDetails();
  await view.click(view.button("验收证据", ".wf-tabs button"));
  view.server.records[0].changed_files = ["updated.py"];
  view.server.proofs.builder = { available: true, log_matches: true, receipt: { status: "PASS", command: "python -m unittest", exit_code: 0 }, log_tail: "new verification output" };
  await view.poll();
  assert.equal(view.container.querySelector(".wf-tabs .active").textContent, "验收证据");
  assert.ok(view.container.querySelector(".wf-content").textContent.includes("updated.py"));
  assert.ok(view.container.querySelector(".wf-content").textContent.includes("new verification output"));
});

test("a late refresh response cannot replace a newly selected execution", async () => {
  view.server.records.push(execution(secondId));
  await view.render();
  const late = deferred();
  view.overrides.set("/executions/" + firstId, () => late.promise);
  await view.refresh();
  await view.click(view.container.querySelectorAll(".wf-execution")[1]);
  assert.equal(view.container.querySelector(".wf-title-line h2").textContent, view.server.records[1].objective);
  await React.act(async () => late.resolve(structuredClone(view.server.records[0])));
  assert.equal(view.container.querySelector(".wf-title-line h2").textContent, view.server.records[1].objective);
});

test("failed refresh retains the visible snapshot, marks it stale and pauses action buttons", async () => {
  view.server.actions_enabled = true;
  await view.render();
  view.overrides.set("/executions/" + firstId, () => { throw new Error("NetworkError"); });
  await view.poll();
  assert.ok(view.container.querySelector(".wf-title-line h2").textContent.includes("目标一"));
  assert.ok(view.container.querySelector(".wf-sync-error").textContent.includes("网络连接失败"));
  assert.ok(view.button("确认需求", ".wf-next-step button").disabled);
  view.overrides.clear();
  await view.poll();
  assert.equal(view.container.querySelector(".wf-sync-error"), null);
  assert.ok(!view.button("确认需求", ".wf-next-step button").disabled);
  assert.ok(view.requests.every(({ init }) => !init?.method || init.method === "GET"));
});

test("an initial detail failure offers recovery instead of a permanent loading message", async () => {
  view.overrides.set("/executions/" + firstId, () => { throw new Error("NetworkError"); });
  await view.render();
  assert.ok(view.container.querySelector(".wf-detail").textContent.includes("暂时无法读取执行详情"));
  view.overrides.clear();
  await view.refresh();
  assert.ok(view.container.querySelector(".wf-title-line h2").textContent.includes("目标一"));
});

test("a failed selection shows an error without synchronization decorations", async () => {
  view.server.records.push(execution(secondId));
  await view.render();
  assert.equal(view.container.querySelector(".wf-sync"), null);
  view.overrides.set("/executions/" + secondId, () => { throw new Error("NetworkError"); });
  await view.click(view.container.querySelectorAll(".wf-execution")[1]);
  assert.equal(view.container.querySelector(".wf-sync time"), null);
  assert.ok(view.container.querySelector(".wf-detail").textContent.includes("暂时无法读取执行详情"));
});

test("stage results and invoked skills follow the selected role in both languages", async () => {
  const tasks = view.server.records[0].rounds[0].tasks;
  Object.assign(tasks.researcher, { result: "已完成方案调查。\n交接开发实施。", skills_used: ["research-notes", "source-review"], skills_recorded: true });
  Object.assign(tasks.builder, { result: "已完成实际代码与测试。", skills_used: [], skills_recorded: true });
  await view.render();
  assert.ok(view.container.querySelector(".wf-task-results").textContent.includes("已完成方案调查。"));
  assert.deepEqual([...view.container.querySelectorAll(".wf-skills-used li")].map(item => item.textContent), ["research-notes", "source-review"]);
  assert.equal(view.container.querySelector(".wf-bottom-grid"), null);
  assert.equal(view.container.querySelector(".wf-header .wf-eyebrow"), null);
  assert.equal(view.container.querySelector(".wf-header .wf-badge"), null);
  await view.click(view.container.querySelector(".wf-node-builder"));
  assert.ok(view.container.querySelector(".wf-task-results").textContent.includes("已完成实际代码与测试。"));
  assert.equal(view.container.querySelector(".wf-skills-used"), null);
  await view.render("en");
  assert.equal(view.container.querySelector(".wf-task-results h3").textContent, "Build results");
  assert.equal(view.container.querySelector(".wf-skills-used"), null);
});

test("a stage without execution history does not claim skills were unused", async () => {
  await view.render();
  assert.equal(view.container.querySelector(".wf-task-results"), null);
  assert.equal(view.container.querySelector(".wf-skills-used"), null);
});

test("an initial list failure is recoverable and does not leave a loading placeholder", async () => {
  view.overrides.set("/executions", () => { throw new Error("NetworkError"); });
  await view.render();
  assert.ok(view.container.querySelector(".wf-executions").textContent.includes("暂时无法读取执行列表"));
  view.overrides.clear();
  await view.refresh();
  assert.equal(view.container.querySelectorAll(".wf-execution").length, 1);
});

test("a slow synchronization does not start overlapping polling requests", async () => {
  await view.render();
  const late = deferred();
  view.overrides.set("/executions/" + firstId, () => late.promise);
  await React.act(async () => { for (const { callback } of view.timers.values()) void callback(); });
  const count = view.requests.length;
  await view.poll();
  assert.equal(view.requests.length, count);
  await React.act(async () => late.resolve(structuredClone(view.server.records[0])));
  assert.equal(view.container.querySelector(".wf-sync-error"), null);
});

test("reselecting the current execution or evidence tab preserves the visible view", async () => {
  await view.render();
  await view.click(view.container.querySelector(".wf-execution"));
  assert.ok(view.container.querySelector(".wf-title-line h2"));
  await view.openDetails();
  await view.click(view.button("验收证据", ".wf-tabs button"));
  assert.equal(view.container.querySelectorAll(".wf-proof").length, 2);
  await view.openDetails();
  await view.click(view.button("验收证据", ".wf-tabs button"));
  assert.equal(view.container.querySelectorAll(".wf-proof").length, 2);
});

test("failed evidence reads are shown as failed rather than loading forever", async () => {
  await view.render();
  view.overrides.set(`/executions/${firstId}/evidence/0/builder`, () => { throw new Error("NetworkError"); });
  await view.openDetails();
  await view.click(view.button("验收证据", ".wf-tabs button"));
  assert.ok(view.container.querySelector(".wf-content").textContent.includes("证据读取未完成"));
});

test("progress and next steps distinguish native completion from quality acceptance", async () => {
  await view.render();
  assert.ok(view.container.querySelector(".wf-next-step").textContent.includes("等待人工审批"));
  assert.equal(view.container.querySelector("progress").value, 0);
  const record = view.server.records[0];
  record.approved_write = true;
  record.rounds[0].tasks.researcher.status = "done";
  record.rounds[0].tasks.builder.status = "done";
  await view.refresh();
  assert.equal(view.container.querySelector("progress").value, 2);
  assert.ok(view.container.querySelector(".wf-next-step").textContent.includes("准备独立审查"));
  for (const task of Object.values(record.rounds[0].tasks)) task.status = "done";
  record.candidate_digest = "d".repeat(64);
  record.candidate_revision = "e".repeat(40);
  await view.refresh();
  assert.equal(view.container.querySelector("progress").value, 4);
  assert.ok(view.container.querySelector(".wf-next-step").textContent.includes("核对交付证据"));
  assert.ok(view.container.querySelector(".wf-title-line .wf-badge").textContent.includes("待验收"));
  record.acceptance.status = "ACCEPTED";
  await view.refresh();
  assert.equal(view.container.querySelector(".wf-next-step"), null);
  assert.ok(view.container.querySelector(".wf-title-line .wf-badge").textContent.includes("已验收"));
});

test("blocked guidance can focus the affected stage", async () => {
  view.server.records[0] = execution(firstId, ["done", "blocked", "triage", "triage"]);
  await view.render();
  await view.click(view.button("查看阻塞阶段", ".wf-next-step button"));
  assert.ok(view.container.querySelector(".wf-node.focused").classList.contains("wf-node-builder"));
  assert.equal(view.dom.window.document.activeElement, view.container.querySelector(".wf-node-builder"));
});

test("partially released tasks point operators to the existing resumable actions", async () => {
  view.server.records[0].approved_write = true;
  await view.render();
  assert.ok(view.container.querySelector(".wf-next-step").textContent.includes("已审批，等待启动"));
  const record = view.server.records[0];
  record.rounds[0].tasks.researcher.status = "done";
  record.rounds[0].tasks.builder.status = "done";
  record.candidate_digest = "d".repeat(64);
  await view.refresh();
  assert.ok(view.container.querySelector(".wf-next-step").textContent.includes("继续释放审查任务"));
});

test("new guidance switches language while read-only controls and user objectives stay intact", async () => {
  await view.render();
  await view.render("en");
  assert.ok(!/[\u3400-\u9fff]/.test(view.container.querySelector(".wf-next-step").textContent));
  assert.ok(!/[\u3400-\u9fff]/.test(view.container.querySelector(".wf-progress").textContent));
  assert.equal(view.container.querySelector(".wf-title-line h2").textContent, view.server.records[0].objective);
  assert.ok(view.button("Approve request", ".wf-next-step button").disabled);
  assert.ok(view.requests.every(({ init }) => !init?.method || init.method === "GET"));
});

test("approval and launch require separate explicit confirmations", async () => {
  view.server.actions_enabled = true;
  await view.render();
  await view.click(view.button("确认需求", ".wf-next-step button"));
  const submit = view.container.querySelector('.wf-modal button[type="submit"]');
  assert.ok(submit.disabled);
  assert.ok(view.container.querySelector('.wf-confirm-target').textContent.includes(view.server.records[0].objective));
  assert.ok(view.container.querySelector('.wf-confirm-target').textContent.includes('第 1 轮'));
  await view.click(view.container.querySelector('.wf-check input'));
  await view.poll();
  assert.ok(view.container.querySelector(".wf-modal"), "Background refresh must preserve the confirmation dialog");
  assert.ok(!submit.disabled);
  view.overrides.set(`/executions/${firstId}/actions/approve`, () => {
    view.server.records[0].approved_write = true;
    return { completed: true };
  });
  await view.click(submit);
  const posts = view.requests.filter(({ init }) => init?.method === "POST");
  assert.equal(posts.length, 1);
  assert.equal(JSON.parse(posts[0].init.body).confirmed, true);
  assert.equal(JSON.parse(posts[0].init.body).round_number, 0);
  assert.equal(posts[0].route, `/executions/${firstId}/actions/approve`);
  assert.equal(view.container.querySelector(".wf-modal"), null);
  assert.ok(view.container.querySelector(".wf-next-step").textContent.includes("已审批，等待启动"));
  await view.click(view.button("开始开发", ".wf-next-step button"));
  assert.ok(view.container.querySelector('.wf-modal button[type="submit"]').disabled);
  await view.click(view.container.querySelector('.wf-check input'));
  view.overrides.set(`/executions/${firstId}/actions/launch`, () => {
    view.server.records[0].rounds[0].tasks.researcher.status = "running";
    view.server.records[0].rounds[0].tasks.builder.status = "todo";
    return { dispatch: { spawned: [{ task_id: "research-id" }] } };
  });
  await view.click(view.container.querySelector('.wf-modal button[type="submit"]'));
  assert.ok(view.container.querySelector(".wf-next-step").textContent.includes("等待调查与开发完成"));
});

test("missing prerequisites permit approval but keep launch disabled", async () => {
  view.server.actions_enabled = true;
  const readiness = { ready: false, checks: [{ code: "docker", label: "Docker 执行环境", ready: false, detail: "请安装并启动 Docker。" }] };
  view.server.readiness = readiness;
  view.server.records[0].readiness = readiness;
  await view.render();
  assert.ok(!view.button("确认需求", ".wf-next-step button").disabled);
  assert.equal(view.button("开始开发", ".wf-next-step button"), undefined);
  assert.equal(view.container.querySelector(".wf-readiness"), null);
  view.server.records[0].approved_write = true;
  await view.refresh();
  assert.equal(view.button("开始开发", ".wf-next-step button"), undefined);
  await view.click(view.button("查看问题", ".wf-next-step button"));
  assert.ok(view.container.querySelector(".wf-readiness").open);
  assert.ok(view.container.querySelector(".wf-readiness").textContent.includes("请安装并启动 Docker"));
  assert.ok(view.requests.every(({ init }) => !init?.method || init.method === "GET"));
});

test("execution prerequisites can be expanded and stay open across synchronization", async () => {
  view.server.actions_enabled = true;
  view.server.readiness = view.server.records[0].readiness;
  await view.render();
  await view.openDetails();
  const checklist = view.container.querySelector('.wf-readiness');
  assert.equal(checklist.open, false);
  await view.click(checklist.querySelector('summary'));
  assert.equal(checklist.open, true);
  await view.poll();
  assert.equal(view.container.querySelector('.wf-readiness').open, true);
});

function enableModelConnections() {
  view.server.actions_enabled = true;
  view.server.model_connections_supported = true;
  view.server.modelConnections = {
    providers: [
      { id: "openrouter", label: "OpenRouter", default_model: "synthetic/shared", models: ["synthetic/shared"], base_url: "https://openrouter.ai/api/v1", protocol: "chat_completions" },
      { id: "openai-api", label: "OpenAI API", default_model: "synthetic-code", models: ["synthetic-code"], base_url: "https://api.openai.com/v1", protocol: "native" },
      { id: "custom", label: "自定义兼容 API", default_model: "", models: [], base_url: "", protocol: "chat_completions" },
    ],
    roles: Object.fromEntries(roles.map(role => [role, { provider: "openrouter", model: "synthetic/shared", has_key: false, profile: role }])),
  };
}

test("all four agents are editable in one screen and a shared connection stays a draft until saved", async () => {
  enableModelConnections();
  await view.render();
  await view.openSettings();
  assert.equal(view.container.querySelectorAll('.wf-agent-row').length, 4);
  assert.equal(view.container.querySelectorAll('.wf-model-settings input[type="password"]').length, 5);
  assert.equal(view.container.querySelector('[role="dialog"]'), null);
  await view.input(view.container.querySelector('[aria-label="共用 API Key"]'), 'synthetic-one-key');
  await view.click(view.button('一套连接应用全部'));
  assert.equal(view.requests.filter(({ init }) => init?.method).length, 0);
  view.overrides.set('/model-connections/models', init => {
    const body = JSON.parse(init.body);
    assert.deepEqual(Object.keys(body.connections), roles);
    for (const role of roles) assert.equal(body.connections[role].api_key, 'synthetic-one-key');
    return { roles: Object.fromEntries(roles.map(role => [role, { models: ['synthetic/shared'], source: 'provider', has_key: true }])) };
  });
  await view.click(view.button('获取全部模型'));
  assert.ok([...view.container.querySelectorAll('.wf-agent-row input[type="password"]')].every(input => !input.value));
  view.overrides.set('/model-connections', init => {
    const body = JSON.parse(init.body);
    assert.equal(init.method, 'PUT');
    assert.equal(body.execution, firstId);
    assert.deepEqual(Object.keys(body.connections), roles);
    for (const role of roles) {
      assert.equal(body.connections[role].model, 'synthetic/shared');
      assert.equal(body.connections[role].api_key, '');
    }
    return { saved: true };
  });
  await view.click(view.button('保存模型配置'));
  assert.ok(view.requests.every(({ route }) => !route.includes('/actions/launch')));
});

test("four independent provider keys load their own catalogs and save the selected models together", async () => {
  enableModelConnections();
  await view.render();
  await view.openSettings();
  const row = role => view.container.querySelector(`[data-role="${role}"]`);
  await view.input(row('builder').querySelector('select'), 'openai-api');
  for (const role of roles) await view.input(row(role).querySelector('input[type="password"]'), `synthetic-${role}-key`);
  view.overrides.set('/model-connections/models', init => {
    const body = JSON.parse(init.body);
    for (const role of roles) assert.equal(body.connections[role].api_key, `synthetic-${role}-key`);
    assert.equal(body.connections.builder.provider, 'openai-api');
    assert.equal(body.connections.reviewer.provider, 'openrouter');
    return { roles: Object.fromEntries(roles.map(role => [role, { models: [`${role}-model`], source: 'provider', has_key: true }])) };
  });
  await view.click(view.button('获取全部模型'));
  for (const role of roles) {
    const picker = row(role).querySelectorAll('select')[1];
    assert.deepEqual([...picker.options].map(option => option.value), ['', `${role}-model`]);
    await view.input(picker, `${role}-model`);
  }
  view.overrides.set('/model-connections', init => {
    const body = JSON.parse(init.body);
    for (const role of roles) assert.equal(body.connections[role].model, `${role}-model`);
    assert.equal(body.connections.builder.provider, 'openai-api');
    assert.equal(body.connections.reviewer.provider, 'openrouter');
    return { saved: true };
  });
  await view.click(view.button('保存模型配置'));
  await view.render('en');
  assert.ok(!/[\u3400-\u9fff]/.test(view.container.querySelector('.wf-model-settings').textContent));
});

test("loading one role leaves the other drafts unchanged and a failed role can be retried", async () => {
  enableModelConnections();
  await view.render();
  await view.openSettings();
  const builder = view.container.querySelector('[data-role="builder"]');
  await view.input(builder.querySelector('select'), 'custom');
  await view.input(builder.querySelector('input[type="password"]'), 'synthetic-builder-key');
  await view.input(builder.querySelector('input[type="url"]'), 'http://models.example/v1');
  await view.input(builder.querySelector('.wf-role-advanced select'), 'anthropic_messages');
  view.overrides.set('/model-connections/models', init => {
    const body = JSON.parse(init.body);
    assert.deepEqual(Object.keys(body.connections), ['builder']);
    assert.equal(body.connections.builder.protocol, 'anthropic_messages');
    return { roles: { builder: { error: '暂时无法读取模型' } } };
  });
  await view.click(builder.querySelector('.wf-role-load'));
  assert.ok(builder.textContent.includes('暂时无法读取模型'));
  assert.equal(builder.querySelector('input[type="password"]').value, 'synthetic-builder-key');
  assert.equal(view.container.querySelector('[data-role="reviewer"] select').value, 'openrouter');
  view.overrides.set('/model-connections/models', () => ({ roles: { builder: { models: ['custom-code'], source: 'provider', has_key: true } } }));
  await view.click(builder.querySelector('.wf-role-load'));
  await view.input(builder.querySelectorAll('select')[1], 'custom-code');
  view.overrides.set('/model-connections', init => {
    const body = JSON.parse(init.body);
    assert.deepEqual(Object.keys(body.connections), ['builder']);
    assert.equal(body.connections.builder.model, 'custom-code');
    assert.equal(body.connections.builder.base_url, 'http://models.example/v1');
    return { saved: true };
  });
  await view.click(view.button('保存模型配置'));
});

test("customer view starts with final results and keeps technical records and settings out of the way", async () => {
  enableModelConnections();
  const record = execution(firstId, ["done", "done", "done", "done"]);
  record.objective = "交付一个可用功能\n完整开发要求与验收细节";
  record.acceptance.status = "ACCEPTED";
  record.rounds[0].tasks.orchestrator.result = "功能已完成，测试已通过。";
  view.server.records = [record];
  await view.render();
  assert.equal(view.container.querySelector(".wf-title-line h2").textContent, "交付一个可用功能");
  assert.equal(view.container.querySelector(".wf-execution h3").textContent, "交付一个可用功能");
  assert.ok(view.container.querySelector(".wf-task-results").textContent.includes("功能已完成"));
  assert.equal(view.container.querySelector(".wf-node.focused").classList.contains("wf-node-orchestrator"), true);
  assert.ok(view.container.querySelector("#wf-model-settings").hidden);
  assert.equal(view.container.querySelector(".wf-record-meta"), null);
  assert.equal(view.container.querySelector(".wf-boundary,.wf-help,.wf-metrics,.wf-footer"), null);
  assert.equal(view.container.querySelectorAll(".wf-header button").length, 2);
  await view.openSettings();
  const key = view.container.querySelector('[aria-label="调查：API Key"]');
  await view.input(key, "synthetic-unsaved-key");
  await view.openSettings();
  await view.poll();
  await view.openSettings();
  assert.equal(key.value, "synthetic-unsaved-key");
  await view.openDetails();
  assert.ok(view.container.querySelector(".wf-record-meta").textContent.includes("完整开发要求与验收细节"));
});

function readyForDelivery() {
  view.server.actions_enabled = true;
  const record = execution(firstId, ["done", "done", "done", "done"]);
  Object.assign(record, { approved_write: true, candidate_digest: "d".repeat(64) });
  view.server.records = [record];
  return record;
}

test("one confirmed delivery action runs required tests in order and then requests acceptance", async () => {
  const record = readyForDelivery();
  for (const action of ["verify-builder", "verify-reviewer", "accept"]) {
    view.overrides.set(`/executions/${firstId}/actions/${action}`, () => {
      if (action === "accept") record.acceptance.status = "ACCEPTED";
      return { completed: true };
    });
  }
  await view.render();
  await view.click(view.button("检查并交付", ".wf-next-step button"));
  const submit = view.container.querySelector('.wf-modal button[type="submit"]');
  assert.ok(submit.disabled);
  assert.equal(view.requests.filter(({ init }) => init?.method === "POST").length, 0);
  await view.click(view.container.querySelector(".wf-check input"));
  await view.click(submit);
  const posts = view.requests.filter(({ init }) => init?.method === "POST");
  assert.deepEqual(posts.map(({ route }) => route.split("/").at(-1)), ["verify-builder", "verify-reviewer", "accept"]);
  assert.ok(posts.every(({ init }) => JSON.parse(init.body).confirmed === true));
  assert.ok(view.container.querySelector(".wf-title-line .wf-badge").textContent.includes("已验收"));
});

test("delivery reuses current passing evidence and stops on a failed remaining test", async () => {
  const record = readyForDelivery();
  view.server.proofs.builder = { available: true, log_matches: true, receipt: { status: "PASS", candidate_digest: record.candidate_digest } };
  view.overrides.set(`/executions/${firstId}/actions/verify-reviewer`, () => { throw new Error("NetworkError"); });
  await view.render();
  await view.click(view.button("检查并交付", ".wf-next-step button"));
  await view.click(view.container.querySelector(".wf-check input"));
  await view.click(view.container.querySelector('.wf-modal button[type="submit"]'));
  assert.deepEqual(view.requests.filter(({ init }) => init?.method === "POST").map(({ route }) => route.split("/").at(-1)), ["verify-reviewer"]);
  assert.ok(view.container.querySelector('.wf-modal [role="alert"]'));
  assert.notEqual(record.acceptance.status, "ACCEPTED");
});

test("requesting changes keeps failure classification in optional fields", async () => {
  const record = readyForDelivery();
  record.acceptance.reason = "Reviewer did not return PASS";
  await view.render();
  await view.click(view.button("继续修改", ".wf-next-step button"));
  const options = view.container.querySelector(".wf-modal-options");
  assert.equal(options.open, false);
  assert.equal(options.querySelector("select").value, "implementation");
  await view.input(options.querySelector("select"), "test");
  const area = view.container.querySelector(".wf-modal textarea");
  await React.act(async () => {
    Object.getOwnPropertyDescriptor(view.dom.window.HTMLTextAreaElement.prototype, "value").set.call(area, "修正测试场景");
    area.dispatchEvent(new view.dom.window.Event("input", { bubbles: true }));
  });
  await view.click(view.container.querySelector(".wf-check input"));
  view.overrides.set(`/executions/${firstId}/actions/repair`, init => {
    assert.equal(JSON.parse(init.body).kind, "test");
    assert.equal(JSON.parse(init.body).reason, "修正测试场景");
    return { completed: true };
  });
  await view.click(view.container.querySelector('.wf-modal button[type="submit"]'));
  assert.equal(view.requests.filter(({ route, init }) => route.endsWith("/repair") && init?.method === "POST").length, 1);
});

function developmentExecution(statuses = ["triage", "triage", "triage", "triage"]) {
  const record = execution();
  record.workflow_version = 2;
  record.workflow_state = "WAITING_APPROVAL";
  record.rounds[0].tasks = Object.fromEntries(["researcher", "builder", "tester", "reviewer"].map((role, i) =>
    [role, { id: firstId + "-" + role, assignee: role, status: statuses[i] }]));
  view.server.actions_enabled = true;
  view.server.records = [record];
  return record;
}

test("new workflow shows independent testing and one approval starts execution", async () => {
  const record = developmentExecution();
  await view.render();
  assert.deepEqual([...view.container.querySelectorAll(".wf-node strong")].map(item => item.textContent), ["方案", "开发", "独立测试", "独立审查"]);
  await view.click(view.button("批准并开始", ".wf-next-step button"));
  await view.click(view.container.querySelector(".wf-check input"));
  view.overrides.set(`/executions/${firstId}/actions/approve`, () => {
    record.approved_write = true;
    record.workflow_state = "RUNNING_RESEARCH";
    record.rounds[0].tasks.researcher.status = "running";
    return { state: "RUNNING_RESEARCH" };
  });
  await view.click(view.container.querySelector('.wf-modal button[type="submit"]'));
  assert.deepEqual(view.requests.filter(({ init }) => init?.method === "POST").map(({ route }) => route.split("/").at(-1)), ["approve"]);
  assert.equal(view.container.querySelector(".wf-next-step h3").textContent, "正在执行");
  assert.equal(view.container.querySelectorAll(".wf-next-step button").length, 0);
  assert.ok(view.requests.every(({ route }) => !route.endsWith("/accept")));
});

test("new delivery uses the platform receipt and accepts without rerunning tests", async () => {
  const record = developmentExecution(["done", "done", "done", "done"]);
  record.approved_write = true;
  record.workflow_state = "READY_FOR_ACCEPTANCE";
  record.acceptance.status = "READY_FOR_ACCEPTANCE";
  view.server.proofs.platform = { available: true, log_matches: true, receipt: { status: "PASS", command: "python -m unittest" }, log_tail: "independent tests passed" };
  await view.render();
  await view.openDetails();
  await view.click(view.button("验收证据", ".wf-tabs button"));
  assert.equal(view.container.querySelectorAll(".wf-proof").length, 1);
  assert.equal(view.container.querySelector(".wf-proof h3").textContent, "独立测试验收");
  assert.ok(view.requests.some(({ route }) => route.endsWith("/evidence/0/platform")));
  await view.click(view.button("执行概览", ".wf-tabs button"));
  await view.click(view.button("确认交付", ".wf-next-step button"));
  await view.click(view.container.querySelector(".wf-check input"));
  view.overrides.set(`/executions/${firstId}/actions/accept`, () => {
    record.acceptance.status = "ACCEPTED";
    return { completed: true };
  });
  await view.click(view.container.querySelector('.wf-modal button[type="submit"]'));
  assert.deepEqual(view.requests.filter(({ init }) => init?.method === "POST").map(({ route }) => route.split("/").at(-1)), ["accept"]);
});

test("new repair explicitly approves the new round before resuming", async () => {
  const record = developmentExecution(["done", "done", "done", "done"]);
  record.approved_write = true;
  record.workflow_state = "REPAIR_REQUIRED";
  await view.render();
  await view.click(view.button("批准整改并执行", ".wf-next-step button"));
  const area = view.container.querySelector(".wf-modal textarea");
  await React.act(async () => {
    Object.getOwnPropertyDescriptor(view.dom.window.HTMLTextAreaElement.prototype, "value").set.call(area, "修复审查问题");
    area.dispatchEvent(new view.dom.window.Event("input", { bubbles: true }));
  });
  await view.click(view.container.querySelector(".wf-check input"));
  view.overrides.set(`/executions/${firstId}/actions/repair`, init => {
    assert.equal(JSON.parse(init.body).reason, "修复审查问题");
    return { completed: true, round_number: 1 };
  });
  view.overrides.set(`/executions/${firstId}/actions/approve`, init => {
    assert.equal(JSON.parse(init.body).round_number, 1);
    assert.equal(JSON.parse(init.body).confirmed, true);
    return { state: "RUNNING_RESEARCH" };
  });
  await view.click(view.container.querySelector('.wf-modal button[type="submit"]'));
  assert.deepEqual(view.requests.filter(({ init }) => init?.method === "POST").map(({ route }) => route.split("/").at(-1)), ["repair", "approve"]);
});

test("new tester result includes its skills and test record in either language", async () => {
  const record = developmentExecution(["done", "running", "done", "triage"]);
  record.approved_write = true;
  Object.assign(record.rounds[0].tasks.tester, { result: "独立验收用例已准备", verification: { status: "TESTS_READY", tests: ["test_target.py"] }, skills_used: ["test-design"] });
  await view.render();
  await view.click(view.container.querySelector(".wf-node-tester"));
  const output = view.container.querySelector(".wf-task-results");
  assert.ok(output.textContent.includes("test_target.py"));
  assert.equal(output.querySelector(".wf-skills-used li").textContent, "test-design");
  await view.render("en");
  assert.equal(output.querySelector("h3").textContent, "Test results");
  assert.equal(output.querySelector("summary").textContent, "Test records");
});

test("new workflow configures the independent tester with its saved connection", async () => {
  enableModelConnections();
  developmentExecution();
  view.server.modelConnections.roles = Object.fromEntries(["researcher", "builder", "tester", "reviewer"].map(role =>
    [role, { provider: "openrouter", model: `${role}-saved-model`, has_key: true, profile: role }]));
  await view.render();
  await view.openSettings();
  assert.deepEqual([...view.container.querySelectorAll(".wf-agent-row")].map(item => item.dataset.role), ["researcher", "builder", "tester", "reviewer"]);
  const tester = view.container.querySelector('[data-role="tester"]');
  assert.equal(tester.querySelector("h3").textContent, "独立测试");
  assert.equal(tester.querySelector('input[type="password"]').value, "");
  assert.equal(tester.querySelectorAll("select")[1].value, "tester-saved-model");
  assert.equal(view.container.querySelector('[data-role="orchestrator"]'), null);
  await view.render("en");
  assert.equal(tester.querySelector("h3").textContent, "Independent testing");
});

test("tester labels distinguish prepared cases from successful platform execution", async () => {
  const record = developmentExecution();
  record.approved_write = true;
  const testerLabel = () => view.container.querySelector(".wf-node-tester small").textContent;
  await view.render();
  assert.equal(testerLabel(), "等待方案");
  record.rounds[0].tasks.tester.status = "done";
  record.workflow_state = "RUNNING_BUILD_AND_TEST";
  await view.poll();
  assert.equal(testerLabel(), "用例已准备");
  for (const state of ["RUNNING_REVIEW", "READY_FOR_ACCEPTANCE", "ACCEPTED"]) {
    record.workflow_state = state;
    await view.poll();
    assert.equal(testerLabel(), "测试通过");
  }
  record.workflow_state = "REPAIR_REQUIRED";
  await view.poll();
  assert.equal(testerLabel(), "查看测试结果");
  await view.render("en");
  assert.equal(testerLabel(), "Check test results");
});

function enableController() {
  view.server.conversation_supported = true;
  view.server.conversations = [];
  view.server.conversation = { id: "d".repeat(32), messages: [], status: "idle", objective: "", pending: null };
}

async function typeArea(selector, value) {
  const area = view.container.querySelector(selector);
  assert.ok(area);
  await React.act(async () => {
    Object.getOwnPropertyDescriptor(view.dom.window.HTMLTextAreaElement.prototype, "value").set.call(area, value);
    area.dispatchEvent(new view.dom.window.Event("input", { bubbles: true }));
  });
}

test("controller chat creates an editable task draft without starting any agents", async () => {
  developmentExecution(); enableController();
  view.overrides.set("/conversations", init => init?.method === "POST" ? view.server.conversation : { conversations: [] });
  view.overrides.set(`/conversations/${view.server.conversation.id}/messages`, init => {
    assert.equal(JSON.parse(init.body).message, "开发一个小功能");
    Object.assign(view.server.conversation, { messages: [{ id: 1, role: "user", content: "开发一个小功能" },
      { id: 2, role: "assistant", content: "请核对任务草案。" }], objective: "范围和固定验收标准" });
    return { status: "running" };
  });
  await view.render();
  await view.click(view.button("新建任务", ".wf-header button"));
  assert.equal(view.container.querySelector('[role="dialog"]'), null);
  await typeArea('.wf-chat-composer textarea', "开发一个小功能");
  await view.click(view.button("发送"));
  assert.ok(view.container.querySelector(".wf-chat-messages").textContent.includes("请核对任务草案"));
  assert.equal(view.container.querySelector(".wf-task-draft textarea").value, "范围和固定验收标准");
  await typeArea('.wf-task-draft textarea', "用户修订后的固定验收标准");
  await view.poll();
  assert.equal(view.container.querySelector(".wf-task-draft textarea").value, "用户修订后的固定验收标准");
  assert.ok(view.requests.every(({ route }) => !route.includes("/actions/") && !route.endsWith("/task")));
});

test("controller task approval names the action and keeps round-bound explicit consent", async () => {
  const record = developmentExecution(); enableController();
  await view.render();
  await view.click(view.button("批准并开始", ".wf-next-step button"));
  assert.equal(view.container.querySelector('.wf-modal input[type="checkbox"]'), null);
  assert.equal(view.container.querySelector('.wf-modal button[type="submit"]').textContent, "批准并开始");
  view.overrides.set(`/executions/${firstId}/actions/approve`, init => {
    const body = JSON.parse(init.body); assert.equal(body.confirmed, true); assert.equal(body.round_number, 0);
    record.approved_write = true; record.workflow_state = "RUNNING_RESEARCH";
    record.rounds[0].tasks.researcher.status = "running";
    return { state: "RUNNING_RESEARCH" };
  });
  await view.click(view.container.querySelector('.wf-modal button[type="submit"]'));
  assert.equal(view.container.querySelector('[role="dialog"]'), null);
  assert.ok(view.requests.every(({ route }) => !route.endsWith("/accept")));
});

test("live worker activity follows the selected role and renders tool output as text", async () => {
  developmentExecution(["done", "running", "running", "triage"]); enableController();
  view.server.activity = { workflow_state: "RUNNING_BUILD_AND_TEST", roles: { researcher: { status: "done" }, builder: { status: "running" }, tester: { status: "running" }, reviewer: { status: "triage" } }, events: [
    { id: "one", at: 1700000001, role: "builder", kind: "tool", name: "patch", text: '<img src=x onerror=bad>' },
    { id: "two", at: 1700000002, role: "tester", kind: "message", name: "工作摘要", text: "正在编写独立用例" },
  ] };
  await view.render();
  assert.ok(view.container.querySelector(".wf-activity").textContent.includes("正在编写独立用例"));
  assert.equal(view.container.querySelector('.wf-activity img'), null);
  await view.click(view.button("开发", ".wf-activity-filters button"));
  assert.equal(view.container.querySelectorAll(".wf-activity-event").length, 1);
  assert.ok(view.container.querySelector('.wf-activity-event').textContent.includes('<img src=x onerror=bad>'));
  await view.render("en");
  assert.equal(view.container.querySelector(".wf-controller h2").textContent, "Controller chat");
  assert.equal(view.container.querySelector(".wf-activity h3").textContent, "Work activity");
});

test("accepted delivery has one current status and keeps the historical report collapsed", async () => {
  const record = developmentExecution(["done", "done", "done", "done"]); enableController();
  record.workflow_state = "ACCEPTED"; record.acceptance.status = "ACCEPTED";
  record.rounds[0].tasks.reviewer.result = "历史报告：等待验收";
  await view.render();
  assert.equal(view.container.querySelector('.wf-execution .wf-badge').textContent, "已验收");
  assert.ok(view.container.querySelector('.wf-delivery').textContent.includes("本次交付已验收"));
  assert.equal(view.container.querySelector('.wf-raw-result').open, false);
  assert.ok(view.button("下载交付代码"));
  assert.equal(view.button("确认验收"), undefined);
});

test("interrupted role retry binds consent to that role and exact run", async () => {
  const record = developmentExecution(["blocked", "triage", "triage", "triage"]); enableController();
  record.approved_write = true; record.workflow_state = "HUMAN_REQUIRED";
  Object.assign(record.rounds[0].tasks.researcher, { outcome: "crashed", run_id: 12 });
  await view.render();
  await view.click(view.button("重试失败角色", ".wf-next-step button"));
  view.overrides.set(`/executions/${firstId}/actions/retry-worker`, init => {
    const body = JSON.parse(init.body);
    assert.equal(body.confirmed, true); assert.equal(body.role, "researcher");
    assert.equal(body.run_id, 12); assert.equal(body.round_number, 0);
    return { state: "RUNNING_RESEARCH" };
  });
  await view.click(view.container.querySelector('.wf-modal button[type="submit"]'));
  assert.equal(view.requests.filter(({ route }) => route.endsWith("/retry-worker")).length, 1);
});

test("task labels use the concrete request after a generic model heading", async () => {
  const record = developmentExecution(); enableController();
  record.objective = "目标\n为状态接口增加轮次编号\n\n验收标准…";
  await view.render();
  assert.equal(view.container.querySelector('.wf-execution h3').textContent, "为状态接口增加轮次编号");
});

test("pre-authorized auto acceptance, decision reasons and reject are visible to the customer", async () => {
  const record = developmentExecution(["done", "done", "done", "done"]); enableController();
  record.approved_write = true;
  record.workflow_state = "READY_FOR_ACCEPTANCE"; record.acceptance.status = "READY_FOR_ACCEPTANCE";
  record.decision = { round: 0, reasons: [{ category: "新增或升级依赖", paths: ["package.json"] }] };
  record.rounds[0].tasks.reviewer.findings = [
    { severity: "minor", summary: "naming nit" }, { severity: "blocker", summary: "crash on empty input", file: "app.py" }];
  await view.render();
  await view.click(view.button("独立审查", ".wf-node strong")?.parentElement);
  const delivery = view.container.querySelector(".wf-delivery").textContent;
  assert.ok(delivery.includes("需要你决定的改动") && delivery.includes("package.json"));
  await view.click(view.button("不做了"));
  assert.ok(view.container.querySelector(".wf-modal").textContent.includes("定了不做的事"));
  await typeArea(".wf-modal textarea", "不引入这个依赖");
  view.overrides.set(`/executions/${firstId}/actions/reject`, (init) => {
    assert.equal(JSON.parse(init.body).reason, "不引入这个依赖");
    record.workflow_state = "REJECTED"; record.rejection = { reason: "不引入这个依赖" };
    return { completed: true };
  });
  await view.click(view.container.querySelector('.wf-modal button[type="submit"]'));
  assert.equal(view.container.querySelector(".wf-execution .wf-badge").textContent, "已决定不做");
  record.workflow_state = "ACCEPTED"; record.acceptance.status = "ACCEPTED"; record.accepted_by = "policy";
  await view.poll();
  assert.ok(view.container.querySelector(".wf-delivery").textContent.includes("已在授权范围内自动验收"));
});

test("a Feishu card link opens the linked execution", async () => {
  view.dom.reconfigure({ url: "http://localhost/workflow?execution=" + secondId });
  view.server.records.push(execution(secondId));
  await view.render();
  assert.equal(view.container.querySelector(".wf-title-line h2").textContent, view.server.records[1].objective);
});

test("next step explains rejected and paused tasks instead of showing only a title", async () => {
  const record = developmentExecution(["done", "done", "done", "triage"]); enableController();
  Object.assign(record, { approved_write: true, workflow_state: "REJECTED", rejection: { reason: "不引入新依赖", at: 1700000000 } });
  await view.render();
  const card = view.container.querySelector(".wf-next-step");
  assert.equal(card.querySelector("h3").textContent, "已决定不做");
  assert.equal(card.querySelector("blockquote").textContent, "不引入新依赖");
  assert.ok(card.querySelector("small").textContent.startsWith("决定于"));
  assert.ok(card.classList.contains("wf-tone-grey"));
  assert.equal(card.querySelectorAll("button").length, 0);
  record.workflow_state = "HUMAN_REQUIRED"; delete record.rejection;
  await view.poll();
  assert.equal(card.querySelector("h3").textContent, "需要处理");
  assert.equal(card.querySelector("p").textContent, "任务暂停等待你检查，确认无误后继续执行。");
  assert.ok(view.button("继续执行", ".wf-next-step button"));
  assert.ok(view.button("不做了", ".wf-next-step button").classList.contains("wf-danger"));
});

test("blocked and interrupted roles are named in the next step", async () => {
  const record = developmentExecution(["done", "blocked", "running", "triage"]); enableController();
  Object.assign(record, { approved_write: true, workflow_state: "HUMAN_REQUIRED" });
  await view.render();
  assert.equal(view.container.querySelector(".wf-next-step p").textContent, "开发被阻塞，请在「工作过程」查看原因。");
  await view.click(view.button("查看阻塞阶段", ".wf-next-step button"));
  assert.ok(view.container.querySelector(".wf-node-builder").classList.contains("focused"));
  Object.assign(record.rounds[0].tasks.builder, { outcome: "timed_out", run_id: 7 });
  await view.render("en");
  await view.poll();
  assert.equal(view.container.querySelector(".wf-next-step p").textContent, "Build stopped (Timed out). You can retry and keep the failed run.");
});

test("repair guidance counts blockers and stops offering repair when the round budget is used", async () => {
  const record = developmentExecution(["done", "done", "done", "done"]); enableController();
  Object.assign(record, { approved_write: true, workflow_state: "REPAIR_REQUIRED" });
  record.rounds[0].tasks.reviewer.findings = [{ severity: "blocker", summary: "a" }, { severity: "blocker", summary: "b" }, { severity: "minor", summary: "c" }];
  await view.render();
  const card = view.container.querySelector(".wf-next-step");
  assert.equal(card.querySelector("p").textContent, "独立审查发现 2 个阻断问题，填写修改意见后开始第 2 轮（共 3 轮）。");
  assert.ok(view.button("批准修复", ".wf-next-step button"));
  record.rounds.push(structuredClone(record.rounds[0]), structuredClone(record.rounds[0]));
  record.rounds[1].number = 1; record.rounds[2].number = 2;
  await view.poll();
  assert.equal(card.querySelector("h3").textContent, "整改轮次已用完");
  assert.equal(view.button("批准修复", ".wf-next-step button"), undefined);
  assert.ok(view.button("不做了", ".wf-next-step button"));
  record.rounds = record.rounds.slice(0, 1);
  record.rounds[0].tasks.reviewer.findings = [];
  await view.poll();
  assert.equal(card.querySelector("p").textContent, "平台测试未通过，填写修改意见后开始第 2 轮（共 3 轮）。");
});

test("tasks that need the user are listed first, counted and coloured consistently", async () => {
  enableController();
  const running = developmentExecution(["done", "running", "running", "triage"]);
  Object.assign(running, { execution_id: secondId, objective: "运行中的任务", approved_write: true, workflow_state: "RUNNING_BUILD_AND_TEST" });
  const waiting = developmentExecution(["done", "done", "done", "done"]);
  Object.assign(waiting, { objective: "等你验收的任务", approved_write: true, workflow_state: "READY_FOR_ACCEPTANCE" });
  waiting.acceptance.status = "READY_FOR_ACCEPTANCE";
  view.server.records = [running, waiting];
  await view.render();
  const items = [...view.container.querySelectorAll(".wf-executions .wf-execution")];
  assert.deepEqual(items.map(item => item.querySelector("h3").textContent), ["等你验收的任务", "运行中的任务"]);
  assert.ok(items[0].classList.contains("selected"), "the first task needing a decision opens by default");
  assert.ok(items[0].querySelector(".wf-badge").classList.contains("wf-amber"));
  assert.ok(items[1].querySelector(".wf-badge").classList.contains("wf-blue"));
  assert.equal(view.container.querySelector(".wf-executions .wf-section-heading .wf-badge").textContent, "1 项待你处理");
  assert.ok(view.container.querySelector(".wf-title-line .wf-badge").classList.contains("wf-amber"));
});

test("search ignores surrounding spaces for both tasks and drafts", async () => {
  enableController();
  view.server.conversations = [{ id: "e".repeat(32), title: "登录草案", execution_id: "" }];
  await view.render();
  const search = view.container.querySelector(".wf-search");
  const type = value => React.act(async () => {
    Object.getOwnPropertyDescriptor(view.dom.window.HTMLInputElement.prototype, "value").set.call(search, value);
    search.dispatchEvent(new view.dom.window.Event("input", { bubbles: true }));
  });
  await type("  登录  ");
  assert.deepEqual([...view.container.querySelectorAll(".wf-execution h3")].map(item => item.textContent), ["登录草案"]);
  await type(" 目标一 ");
  assert.deepEqual([...view.container.querySelectorAll(".wf-execution h3")].map(item => item.textContent), ["目标一 / Objective one"]);
});

test("build and independent testing render as one parallel column", async () => {
  developmentExecution(["done", "running", "running", "triage"]); enableController();
  await view.render();
  const columns = [...view.container.querySelector(".wf-dag").children];
  assert.deepEqual(columns.map(item => item.className.split(" ")[0]), ["wf-node", "wf-dag-parallel", "wf-node"]);
  assert.deepEqual([...columns[1].querySelectorAll("strong")].map(item => item.textContent), ["开发", "独立测试"]);
});

test("code changes load once and toggle, and downloads keep the blob URL alive past the click", async () => {
  const record = developmentExecution(["done", "done", "done", "done"]); enableController();
  Object.assign(record, { approved_write: true, workflow_state: "READY_FOR_ACCEPTANCE", changed_files: ["app.py", "test_app.py"] });
  record.acceptance.status = "READY_FOR_ACCEPTANCE";
  let reads = 0;
  view.overrides.set(`/executions/${firstId}/delivery`, () => { reads += 1; return { changed_files: ["app.py"], patch: "+fix" }; });
  await view.render();
  const toggle = view.button("查看代码改动（2 个文件）");
  await view.click(toggle);
  assert.ok(view.container.querySelector(".wf-diff pre").textContent.includes("+fix"));
  assert.equal(toggle.textContent, "收起代码改动");
  await view.click(toggle);
  assert.equal(view.container.querySelector(".wf-diff"), null);
  await view.click(toggle);
  assert.equal(reads, 1);

  const revoked = [], delayed = [], clicked = [];
  const { createObjectURL, revokeObjectURL } = URL, { setTimeout: realTimeout } = global, click = view.dom.window.HTMLAnchorElement.prototype.click;
  Object.assign(URL, { createObjectURL: () => "blob:synthetic", revokeObjectURL: url => revoked.push(url) });
  global.setTimeout = (callback, delay) => { delayed.push(delay); callback(); };
  view.dom.window.HTMLAnchorElement.prototype.click = function () { clicked.push(this.isConnected && this.download); };
  view.dom.window.__HERMES_PLUGIN_SDK__.authedFetch = async () => ({ ok: true, blob: async () => new Blob(["x"]) });
  try { await view.click(view.button("下载交付代码")); }
  finally { Object.assign(URL, { createObjectURL, revokeObjectURL }); global.setTimeout = realTimeout; view.dom.window.HTMLAnchorElement.prototype.click = click; }
  assert.deepEqual(clicked, ["delivery-aaaaaaaa.tar.gz"]);
  assert.deepEqual(delayed, [60000]);
  assert.deepEqual(revoked, ["blob:synthetic"]);
  assert.equal(view.container.ownerDocument.querySelector("a[download]"), null);
});

test("the won't-do dialog is visibly destructive and the chat can be collapsed", async () => {
  developmentExecution(); enableController();
  await view.render();
  await view.click(view.button("不做了", ".wf-next-step button"));
  assert.ok(view.container.querySelector(".wf-modal").classList.contains("wf-modal-danger"));
  const submit = view.container.querySelector('.wf-modal button[type="submit"]');
  assert.equal(submit.textContent, "确认不做");
  assert.ok(submit.classList.contains("wf-danger-solid"));
  await view.click(view.button("取消", ".wf-modal button"));
  const chat = view.container.querySelector(".wf-controller");
  await view.click(view.button("收起对话", ".wf-controller button"));
  assert.ok(chat.classList.contains("wf-collapsed"));
  assert.equal(view.button("展开对话", ".wf-controller button").getAttribute("aria-expanded"), "false");
});

function enableArchitect() {
  view.server.actions_enabled = true;
  view.server.architect_supported = true;
  view.server.conversation_supported = true;
  const card = {
    type: "card", card_id: "1".repeat(16), execution_id: firstId, round: 0, state: "READY_FOR_ACCEPTANCE",
    objective: "导出 CSV 并保护公式内容", source_revision: "c".repeat(40), title: "等待确认交付",
    text: "测试与审查已通过，请确认交付范围。", advice: { text: "建议保留公式转义保护。", source: "model" },
    reasons: [{ category: "新增或升级依赖", paths: ["package.json"] }], blockers: [],
    actions: ["accept", "request-changes", "reject"], at: 102, resolved: null,
  };
  view.server.architect = {
    conversation: { id: "d".repeat(32), status: "idle", objective: "", pending: null },
    items: [
      { type: "message", id: 1, role: "user", content: "导出结果给我", at: 100, channel: "feishu", name: "同事甲" },
      { type: "progress", id: "progress-1", execution_id: firstId, objective: "导出结果给我", label: "平台测试通过，开始独立审查", text: "「导出结果给我」平台测试通过，开始独立审查", at: 101 }, card,
    ], pending: 1, legacy: [],
  };
  return card;
}

test("architect timeline renders messages, system progress and advice in their original order", async () => {
  enableArchitect();
  await view.render();
  const timeline = view.container.querySelector(".wf-architect-timeline");
  assert.match(timeline.children[0].textContent, /飞书 · 同事甲/);
  assert.match(timeline.children[1].textContent, /系统进展/);
  assert.match(timeline.children[2].textContent, /架构师建议/);
  assert.match(timeline.children[2].textContent, /package.json/);
  assert.equal(view.container.querySelectorAll(".wf-chat-composer").length, 1);
  assert.equal(view.button("新建任务"), undefined);
  assert.equal(view.container.querySelector(".wf-task-drawer"), null);
});

test("an architect decision still needs its explicit modal and sends only the card capability", async () => {
  const card = enableArchitect();
  await view.render();
  await view.click(view.button("确认验收", ".wf-architect-card button"));
  assert.ok(view.container.querySelector('[role="dialog"]').textContent.includes(card.objective));
  assert.ok(view.container.querySelector('[role="dialog"]').textContent.includes("第 1 轮"));
  assert.equal(view.requests.filter(({ route }) => route === "/architect/decisions").length, 0);
  view.overrides.set("/architect/decisions", init => {
    assert.deepEqual(JSON.parse(init.body), { card_id: card.card_id, action: "accept", reason: "" });
    assert.equal(init.headers["X-Hermes-Workflow-Action"], "1");
    card.resolved = { action: "accept", by: "web", name: "你", at: 110 }; card.actions = [];
    view.server.architect.pending = 0;
    return { completed: true };
  });
  await view.click(view.container.querySelector('.wf-modal button[type="submit"]'));
  assert.equal(view.container.querySelector('[role="dialog"]'), null);
  assert.match(view.container.querySelector(".wf-resolved").textContent, /已由/);
});

test("an expired architect card reports the conflict and refreshes without replaying a decision", async () => {
  const card = enableArchitect();
  await view.render();
  await view.click(view.button("确认验收", ".wf-architect-card button"));
  view.overrides.set("/architect/decisions", () => { card.resolved = { action: "accept", by: "feishu:synthetic", name: "同事乙", at: 110 };
    throw new Error('409: {"detail":"卡片已过期，请刷新。"}'); });
  const reads = view.requests.filter(({ route }) => route === "/architect").length;
  await view.click(view.container.querySelector('.wf-modal button[type="submit"]'));
  assert.match(view.container.querySelector('[role="alert"]').textContent, /卡片已过期/);
  assert.ok(view.requests.filter(({ route }) => route === "/architect").length > reads);
  assert.equal(view.requests.filter(({ route }) => route === "/architect/decisions").length, 1);
});

test("resolved cards keep their original location and cannot be acted on again", async () => {
  const card = enableArchitect();
  card.resolved = { action: "accept", by: "feishu:synthetic", name: "同事乙", at: 110 };
  await view.render();
  const node = view.container.querySelector(".wf-architect-card");
  assert.ok(node.classList.contains("resolved"));
  assert.match(node.textContent, /同事乙/);
  assert.match(node.textContent, /飞书/);
  assert.equal(node.querySelector(".wf-button-row"), null);
  assert.equal(view.container.querySelector(".wf-architect-timeline").children[2], node);
});

test("a card deep link scrolls to and highlights that card", async () => {
  const card = enableArchitect(), scrolled = [];
  view.dom.window.HTMLElement.prototype.scrollIntoView = function () { scrolled.push(this.id); };
  view.dom.reconfigure({ url: "http://localhost/workflow?card=" + card.card_id + "&execution=" + firstId });
  await view.render();
  assert.deepEqual(scrolled, ["wf-card-" + card.card_id]);
  assert.ok(view.container.querySelector(".wf-architect-card").classList.contains("highlight"));
  assert.equal(view.container.querySelector(".wf-task-drawer"), null);
});

test("opening and closing the task drawer preserves the single architect polling loop", async () => {
  enableArchitect();
  await view.render();
  const reads = () => view.requests.filter(({ route }) => route === "/architect").length;
  await view.click(view.button("任务", ".wf-architect > .wf-header button"));
  assert.ok(view.container.querySelector(".wf-task-drawer"));
  assert.equal(view.container.querySelectorAll(".wf-chat-composer").length, 1);
  await view.poll();
  const before = reads();
  await view.click(view.container.querySelector('[aria-label="关闭任务抽屉"]'));
  await view.poll();
  assert.ok(reads() > before);
  assert.equal(view.container.querySelectorAll(".wf-architect-conversation").length, 1);
});

test("pending count locates the earliest unresolved decision", async () => {
  const card = enableArchitect(), scrolled = [];
  view.dom.window.HTMLElement.prototype.scrollIntoView = function () { scrolled.push(this.id); };
  view.server.architect.items.push({ ...card, card_id: "2".repeat(16), at: 104 });
  view.server.architect.pending = 2;
  await view.render();
  await view.click(view.button("2 项待你决定"));
  assert.deepEqual(scrolled, ["wf-card-" + card.card_id]);
});

test("saying yes in architect chat only sends a message and never a decision", async () => {
  enableArchitect();
  view.overrides.set("/architect/messages", init => {
    assert.deepEqual(JSON.parse(init.body), { message: "可以，接受" });
    return { status: "running" };
  });
  await view.render();
  await typeArea(".wf-architect .wf-chat-composer textarea", "可以，接受");
  await view.click(view.button("发送"));
  assert.equal(view.requests.filter(({ route }) => route === "/architect/messages").length, 1);
  assert.equal(view.requests.filter(({ route }) => route === "/architect/decisions").length, 0);
});

test("new architect messages scroll into view while unchanged polling preserves the reading position", async () => {
  enableArchitect();
  await view.render();
  const log = view.container.querySelector(".wf-architect-timeline");
  Object.defineProperty(log, "scrollHeight", { value: 900 });
  view.server.architect.items.push({ type: "message", id: 3, role: "assistant", content: "新的回复", at: 110, channel: "web" });
  await view.poll();
  assert.equal(log.scrollTop, 900);
  log.scrollTop = 100;
  await view.poll();
  assert.equal(log.scrollTop, 100);
});

test("an edited architect draft survives polling and creates only an unapproved task", async () => {
  enableArchitect();
  view.server.architect.conversation.objective = "模型草案";
  await view.render();
  await typeArea(".wf-task-draft textarea", "用户修订后的验收标准");
  await view.poll();
  assert.equal(view.container.querySelector(".wf-task-draft textarea").value, "用户修订后的验收标准");
  view.overrides.set("/architect/tasks", init => {
    assert.deepEqual(JSON.parse(init.body), { objective: "用户修订后的验收标准" });
    view.server.architect.conversation.objective = "用户修订后的验收标准";
    view.server.architect.conversation.submitted_objective = "用户修订后的验收标准";
    return { execution_id: firstId };
  });
  await view.click(view.button("生成任务卡"));
  assert.equal(view.requests.filter(({ route }) => route === "/architect/decisions").length, 0);
  assert.equal(view.container.querySelector(".wf-task-draft"), null);
});

test("legacy conversations remain read-only and timeline language switches without changing user text", async () => {
  enableArchitect();
  view.server.architect.legacy = [{ id: "d".repeat(32), title: "历史需求" }];
  view.server.conversation = { messages: [{ id: 3, role: "user", content: "原始记录" }] };
  await view.render();
  await view.click(view.button("历史需求"));
  assert.match(view.container.querySelector(".wf-legacy-messages").textContent, /原始记录/);
  assert.equal(view.container.querySelector(".wf-legacy textarea"), null);
  await view.render("en");
  assert.equal(view.container.querySelector(".wf-architect h1").textContent, "Project architect");
  assert.match(view.container.querySelector(".wf-architect-timeline").textContent, /Feishu · 同事甲/);
  assert.match(view.container.querySelector(".wf-architect-timeline").textContent, /导出结果给我/);
  assert.match(view.container.querySelector(".wf-timeline-progress").textContent, /Platform tests passed; independent review started/);
});

test("bilingual labels contain no duplicate dictionary keys", () => {
  const dictionary = source.slice(source.indexOf("  const EN = {"), source.indexOf("  const ZH ="));
  const keys = [...dictionary.matchAll(/^    "([^"]+)":/gm)].map(match => match[1]);
  assert.equal(new Set(keys).size, keys.length);
});


test("a legacy task keeps its original explicit approval in the task drawer", async () => {
  enableArchitect();
  view.server.records[0].workflow_version = 1;
  await view.render();
  await view.click(view.button("任务", ".wf-architect > .wf-header button"));
  assert.ok(view.container.querySelector(".wf-task-drawer .wf-legacy-task"));
  const button = view.button("确认需求", ".wf-task-drawer .wf-next-step button");
  assert.equal(button.disabled, false);
  await view.click(button);
  assert.ok(view.container.querySelector(".wf-modal .wf-check input"));
  assert.equal(view.container.querySelector('.wf-modal button[type="submit"]').disabled, true);
  assert.equal(view.requests.filter(({ route }) => route.includes("/actions/")).length, 0);
});
