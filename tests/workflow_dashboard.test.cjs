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
const { createRoot } = requireWeb("react-dom/client");
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
      if (route === "/meta") return { actions_enabled: server.actions_enabled, project_name: "synthetic-project", board: "default", readiness: server.readiness, model_connections_supported: server.model_connections_supported };
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
      for (const { callback, period } of [...timers.values()]) { assert.equal(period, 20000); await callback(); }
    }),
    refresh: async () => view.click(container.querySelector('[aria-label="刷新工作流"]')),
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

test("attention includes blocked stages during other running work and missing records", async () => {
  const missing = execution(secondId); missing.rounds = [];
  view.server.records = [execution(firstId, ["running", "blocked", "triage", "triage"]), missing];
  await view.render();
  assert.equal(view.container.querySelectorAll(".wf-metric strong")[2].textContent, "2");
  await view.click(view.button("需要关注", ".wf-filters button"));
  assert.equal(view.container.querySelectorAll(".wf-execution").length, 2);
});

test("polling updates the selected detail and evidence without resetting the active tab", async () => {
  await view.render();
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
  assert.ok(view.container.querySelector(".wf-sync-error").textContent.includes("同步失败"));
  assert.ok([...view.container.querySelectorAll(".wf-action")].every((item) => item.disabled));
  view.overrides.clear();
  await view.poll();
  assert.equal(view.container.querySelector(".wf-sync-error"), null);
  assert.ok(!view.button("人工审批", ".wf-next-step button").disabled);
  assert.ok([...view.container.querySelectorAll(".wf-action")].find((item) => item.textContent.startsWith("启动多 Agent")).disabled);
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

test("a failed selection does not present another execution's synchronization time", async () => {
  view.server.records.push(execution(secondId));
  await view.render();
  assert.ok(view.container.querySelector(".wf-sync time"));
  view.overrides.set("/executions/" + secondId, () => { throw new Error("NetworkError"); });
  await view.click(view.container.querySelectorAll(".wf-execution")[1]);
  assert.equal(view.container.querySelector(".wf-sync time"), null);
  assert.ok(view.container.querySelector(".wf-detail").textContent.includes("暂时无法读取执行详情"));
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
  await view.click(view.button("验收证据", ".wf-tabs button"));
  assert.equal(view.container.querySelectorAll(".wf-proof").length, 2);
  await view.click(view.button("验收证据", ".wf-tabs button"));
  assert.equal(view.container.querySelectorAll(".wf-proof").length, 2);
});

test("failed evidence reads are shown as failed rather than loading forever", async () => {
  await view.render();
  view.overrides.set(`/executions/${firstId}/evidence/0/builder`, () => { throw new Error("NetworkError"); });
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
  assert.ok(view.container.querySelector(".wf-title-line .wf-badge").textContent.includes("尚未验收"));
  record.acceptance.status = "ACCEPTED";
  await view.refresh();
  assert.ok(view.container.querySelector(".wf-next-step").textContent.includes("交付已验收"));
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
  assert.ok([...view.container.querySelectorAll(".wf-action")].every((item) => item.disabled));
  assert.ok(view.requests.every(({ init }) => !init?.method || init.method === "GET"));
});

test("approval and launch require separate explicit confirmations", async () => {
  view.server.actions_enabled = true;
  await view.render();
  await view.click(view.button("人工审批", ".wf-next-step button"));
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
  await view.click(view.button("启动多 Agent", ".wf-next-step button"));
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
  assert.ok(!view.button("人工审批", ".wf-next-step button").disabled);
  assert.ok([...view.container.querySelectorAll(".wf-action")].find((item) => item.textContent.startsWith("启动多 Agent")).disabled);
  assert.ok(view.container.querySelector(".wf-readiness").textContent.includes("请安装并启动 Docker"));
  view.server.records[0].approved_write = true;
  await view.refresh();
  assert.ok(view.button("启动多 Agent", ".wf-next-step button").disabled);
  assert.ok(view.requests.every(({ init }) => !init?.method || init.method === "GET"));
});

test("execution prerequisites can be expanded and stay open across synchronization", async () => {
  view.server.actions_enabled = true;
  view.server.readiness = view.server.records[0].readiness;
  await view.render();
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
