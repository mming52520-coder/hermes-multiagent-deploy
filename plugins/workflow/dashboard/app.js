/* Hermes Dashboard plugin. Uses the host React and authenticated API client. */
(function () {
  "use strict";
  const SDK = window.__HERMES_PLUGIN_SDK__;
  if (!SDK || !window.__HERMES_PLUGINS__) return;
  const R = SDK.React, h = R.createElement;
  const { useState, useEffect } = R;
  const API = "/api/plugins/workflow";
  const ROLES = ["researcher", "builder", "reviewer", "orchestrator"];
  const NAMES = { researcher: "调查", builder: "开发", reviewer: "独立审查", orchestrator: "最终汇总" };
  const STATES = { triage: "待审批", todo: "等待依赖", ready: "待执行", running: "执行中", blocked: "已阻塞", done: "已完成", archived: "已归档", missing: "记录缺失" };
  const ACCEPT = { ACCEPTED: "已验收", NOT_ACCEPTED: "尚未验收", READY_FOR_ACCEPTANCE: "可提交验收" };
  const OUTCOMES = { completed: "成功完成", blocked: "已阻塞", failed: "执行失败", crashed: "意外退出", spawn_failed: "启动失败", gave_up: "已停止重试", reclaimed: "已由恢复流程接管", review_requested: "等待审查", changes_requested: "需要修改", dependency_wait: "等待依赖", timeout: "执行超时", timed_out: "执行超时", cancelled: "已取消", interrupted: "已中断", abandoned: "已终止" };
  const KINDS = { implementation: "实现问题", test: "测试问题", environment: "环境问题", api_model: "接口或模型问题", permission: "权限问题", requirements: "需求问题" };
  const ACTIONS = {
    start: ["授权执行", "将释放调查与开发任务，仅允许修改此执行的候选副本。可能产生模型费用，当前尚无全局费用硬限额。"],
    "prepare-review": ["准备独立审查", "将冻结开发候选并释放审查任务。已发布的审查副本不能替换。"],
    "verify-builder": ["验证开发结果", "在独立容器中运行操作员预设的验收命令，记录实际退出状态与日志。"],
    "verify-reviewer": ["验证审查副本", "针对相同候选的审查副本执行独立验证，记录可核对的证据。"],
    accept: ["提交质量验收", "后端将重新核对版本、实际变更、两份验证记录和独立审查结果；不合格的执行会被拒绝。"],
    repair: ["创建整改轮次", "仅针对当前独立审查失败创建开发、审查和汇总任务；新轮次仍需重新授权。"],
  };
  function cx() { return Array.from(arguments).filter(Boolean).join(" "); }
  function short(value) { return value ? String(value).slice(0, 10) : "尚未生成"; }
  function date(value) { return new Intl.DateTimeFormat("zh-CN", { month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit" }).format(new Date(value * 1000)); }
  function message(error) {
    let raw = String(error && error.message || error);
    try { const data = JSON.parse(raw.replace(/^\d+:\s*/, "")); raw = data.detail || raw; } catch (_) { /* host may return plain text */ }
    const hints = {
      WRITE_NOT_APPROVED: "本次执行尚未获得写入授权。", COST_UNAVAILABLE: "当前版本无法强制执行费用上限，请由操作员处理。",
      TIME_BUDGET: "执行时间预算已用尽，需要人工介入。", RUN_BUDGET: "任务尝试次数已达到上限，需要人工介入。",
      REPAIR_BUDGET: "整改轮次已达到上限。", REPEATED_FAILURE: "相同问题重复出现，需要人工介入。", HUMAN_REQUIRED: "此类问题需要人工处理。",
      Unauthorized: "登录状态已失效，请刷新页面或重新登录。", Forbidden: "当前账号或应用模式不允许此操作。",
      "Failed to fetch": "无法连接网页后台，请确认服务已启动后重试。", "NetworkError": "网络连接失败，请检查后台服务。",
      "Not Found": "找不到所需记录或接口，请检查插件安装并刷新页面。",
      "unsupported Hermes": "当前 Hermes 版本尚未适配此写入操作，请保持只读模式。",
      "baseline": "Hermes 源码未通过已审计基线校验，请由操作员检查安装来源。",
      "source has uncommitted changes": "源项目有尚未保存到版本库的改动，请先保留这些改动并选择干净的源版本。",
      "original source now has uncommitted changes": "源项目在执行期间产生了未提交改动，需要人工检查。",
      "source revision changed": "源项目版本已经改变，需要重新核对执行记录。",
      "candidate snapshot is missing": "候选副本尚未准备完成。", "candidate revision changed": "候选版本已经改变。",
      "candidate changed after snapshot": "候选内容在冻结后发生了变化，需要重新准备验证。",
      "candidate mutated during verification": "验证期间候选内容发生变化，本次证据不可用于验收。",
      "review revision mismatch": "审查副本与候选版本不一致。", "candidate/review content mismatch": "开发与审查副本的内容不一致。",
      "task is not successfully completed": "有任务尚未成功完成，请先检查四阶段状态。",
      "missing verification handoff": "缺少验证结果交接信息。", "missing operator verification receipt": "缺少操作员生成的验证证据。",
      "failed, stale, or altered verification receipt": "验证记录失败、已过期或被改动，不能用于验收。",
      "handoff mismatch": "任务交接信息与当前候选不一致。", "no real code-change evidence": "尚未发现可核对的实际代码变更。",
      "Builder changed_files": "开发任务报告的文件列表与实际变更不一致。", "Reviewer did not return PASS": "独立审查尚未通过。",
      "acceptance record is stale": "验收记录已失效，需要重新核对证据。",
      "worker is already running": "执行进程仍在运行，暂时不能修改目录权限。", "active workers must terminate": "请等待当前执行进程结束后再整改。",
      "review already released": "审查任务已经发布，不能替换其候选副本。", "prepare-review must freeze": "请先准备独立审查并冻结候选副本。",
      "missing verification command": "尚未配置验收命令。", "configure a meaningful WORKFLOW_TEST_COMMAND": "请先由操作员配置有效的验收命令。",
      "repair requires a completed Reviewer FAIL": "只有独立审查已完成且未通过时，才能创建整改轮次。",
    };
    if (Array.isArray(raw)) return "请求参数无效，请检查填写内容后重试。";
    const key = Object.keys(hints).find(item => String(raw).includes(item));
    return key ? hints[key] : /[\u3400-\u9fff]/.test(String(raw)) ? String(raw) : "操作未完成，请由操作员查看后台诊断日志。";
  }
  function request(path, init) { return SDK.fetchJSON(API + path, init); }
  function post(path, body) { return request(path, { method: "POST", headers: { "Content-Type": "application/json", "X-Hermes-Workflow-Action": "1" }, body: JSON.stringify(body) }); }
  function Badge(props) { return h("span", { className: cx("wf-badge", props.tone && "wf-" + props.tone) }, props.children); }
  function Empty(props) { return h("div", { className: "wf-empty" }, h("div", { className: "wf-empty-symbol", "aria-hidden": true }, "◇"), h("h3", null, props.title), h("p", null, props.children)); }
  function current(row) { return row && row.rounds.length ? row.rounds[row.rounds.length - 1].tasks : {}; }
  function state(row) { const tasks = Object.values(current(row)); return tasks.some(t => t.status === "running") ? "running" : tasks.some(t => ["blocked", "missing"].includes(t.status)) ? "blocked" : tasks.length && tasks.every(t => ["done", "archived"].includes(t.status)) ? "done" : "triage"; }

  function Help(props) {
    const browsing = [["刷新", "重新读取任务状态；不会启动任务。页面也会每 20 秒自动刷新。"], ["搜索研发目标", "输入目标名称查找记录；“需要关注”仅显示阻塞或记录缺失的目标。"], ["四阶段卡片", "点击调查、开发、独立审查或最终汇总，查看对应任务的运行结果。"], ["验收证据", "查看开发与审查副本的验证结果、原始命令和日志。"], ["整改记录", "查看失败分类、历史轮次，以及时间和尝试次数上限。"]];
    const definitions = items => h("dl", null, items.map(([label, text]) => h(R.Fragment, { key: label }, h("dt", null, label), h("dd", null, text))));
    return h("details", { className: "wf-help" }, h("summary", null, "使用说明与按键"),
      h("p", null, props.writable ? "操作需要人工确认，并由后端核验条件。支持范围请查看安装说明。" : "当前为只读模式。灰色按钮表示操作未开放，不是页面故障。Hermes v0.22.5 的工作流写入仍未适配。"),
      h("div", { className: "wf-help-grid" },
        h("section", null, h("h2", null, "浏览与查看"), definitions(browsing)),
        h("section", null, h("h2", null, "按钮的作用"), definitions([["新建目标", "创建待审批计划，不会立即运行。只读时不可用。"], ...Object.values(ACTIONS)])),
        h("section", null, h("h2", null, "键盘操作"), definitions([["Tab / Shift + Tab", "向后或向前移动焦点。"], ["Enter / 空格", "在按钮或说明标题上确认、展开或收起；输入框保留正常输入行为。"], ["Esc", "关闭操作确认弹窗；操作处理中需等待完成。"], ["确认勾选框", "执行操作前需要明确勾选，再点击“确认操作”；灰色按钮不能由键盘绕过。"]])),
        h("section", null, h("h2", null, "怎样理解状态"), definitions([["待审批", "任务已登记，尚未获准执行。"], ["等待依赖", "需要先完成前置任务。"], ["已阻塞", "存在需要处理的问题，请查看详情。"], ["已完成 / 已验收", "任务结束不代表交付合格；只有证据通过核对后才显示“已验收”。"], ["原始信息", "版本号、任务编号、命令、路径及验证日志保留原文，便于核对。"]]))));
  }

  function App() {
    const [meta, setMeta] = useState(null), [rows, setRows] = useState(null), [selected, setSelected] = useState(null);
    const [detail, setDetail] = useState(null), [tab, setTab] = useState("overview"), [focus, setFocus] = useState("researcher");
    const [query, setQuery] = useState(""), [attention, setAttention] = useState(false), [error, setError] = useState("");
    const [busy, setBusy] = useState(false), [dialog, setDialog] = useState(null), [objective, setObjective] = useState("");
    const [instance, setInstance] = useState(""), [ack, setAck] = useState(false), [kind, setKind] = useState("implementation"), [reason, setReason] = useState("");
    const [proof, setProof] = useState(null), [notice, setNotice] = useState("");
    const [dialogExecution, setDialogExecution] = useState(null);

    async function overview() {
      try {
        const [info, data] = await Promise.all([request("/meta"), request("/executions")]);
        setMeta(info); setRows(data.executions);
        setSelected(previous => data.executions.some(row => row.execution_id === previous) ? previous : data.executions[0]?.execution_id || null);
      } catch (e) { setError(message(e)); }
    }
    async function reload() {
      setBusy(true); setError("");
      try { await overview(); if (selected) setDetail(await request("/executions/" + selected)); }
      catch (e) { setError(message(e)); } finally { setBusy(false); }
    }
    useEffect(() => { overview(); const timer = setInterval(overview, 20000); return () => clearInterval(timer); }, []);
    useEffect(() => {
      let active = true; setDetail(null); setProof(null); setTab("overview");
      if (selected) request("/executions/" + selected).then(data => { if (active) setDetail(data); }).catch(e => { if (active) setError(message(e)); });
      return () => { active = false; };
    }, [selected]);
    useEffect(() => {
      let active = true;
      if (tab === "evidence" && detail) {
        setProof(null);
        const number = detail.rounds[detail.rounds.length - 1].number;
        Promise.all(["builder", "reviewer"].map(role => request(`/executions/${detail.execution_id}/evidence/${number}/${role}`)))
          .then(data => { if (active) setProof(data); }).catch(e => { if (active) setError(message(e)); });
      }
      return () => { active = false; };
    }, [tab, detail]);

    useEffect(() => {
      if (!dialog) return;
      const previous = document.activeElement;
      const modal = document.querySelector(".workflow-app .wf-modal");
      const selector = "button:not([disabled]),input:not([disabled]),textarea,select";
      modal.querySelector(selector)?.focus();
      function keyboard(event) {
        if (event.key === "Escape" && !busy) { event.preventDefault(); setDialog(null); }
        if (event.key === "Tab") {
          const fields = Array.from(modal.querySelectorAll(selector));
          const first = fields[0], last = fields[fields.length - 1];
          if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last?.focus(); }
          else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first?.focus(); }
        }
      }
      modal.addEventListener("keydown", keyboard);
      return () => { modal.removeEventListener("keydown", keyboard); previous?.focus(); };
    }, [dialog, busy]);

    async function execute(event) {
      event.preventDefault(); setBusy(true); setError("");
      try {
        if (dialog === "new") {
          const result = await post("/executions", { objective, instance });
          await overview(); setSelected(result.execution_id); setObjective(""); setInstance("");
          setNotice("目标已建立，任务等待审批。");
        } else {
          await post(`/executions/${dialogExecution}/actions/${dialog}`, { confirmed: ack, kind, reason });
          setDetail(await request("/executions/" + dialogExecution)); setSelected(dialogExecution); await overview();
          setNotice("操作已完成，执行状态已更新。");
        }
        setDialog(null); setAck(false); setReason("");
      } catch (e) { setError(message(e)); } finally { setBusy(false); }
    }
    const writable = !!meta?.actions_enabled;
    const visible = (rows || []).filter(row => row.objective.toLowerCase().includes(query.toLowerCase()) && (!attention || state(row) === "blocked"));
    const tasks = current(detail), activeTask = tasks[focus];
    const metrics = rows === null ? ["—", "—", "—"] : [rows.length, rows.reduce((n, row) => n + Object.values(current(row)).filter(t => t.status === "running").length, 0), rows.filter(row => state(row) === "blocked").length];
    const actionButton = key => h("button", { key, className: "wf-action", disabled: !writable || busy, title: !writable ? "当前为只读模式" : ACTIONS[key][1], onClick: () => { setAck(false); setDialogExecution(selected); setError(""); setDialog(key); } }, ACTIONS[key][0], h("span", { "aria-hidden": true }, "↗"));

    return h("main", { className: "workflow-app" },
      h("header", { className: "wf-header" }, h("div", null, h("div", { className: "wf-eyebrow" }, "Hermes · 多智能体工作流"), h("h1", null, "研发工作台"), h("p", null, "从研发目标到交付证据，每一步都可追溯。")),
        h("div", { className: "wf-header-actions" }, h(Badge, { tone: writable ? "green" : "neutral" }, h("i", null), writable ? "人工受控" : "只读模式"), h("button", { className: "wf-button", disabled: busy, onClick: reload, "aria-label": "刷新工作流" }, "↻ 刷新"), h("button", { className: "wf-button wf-primary", disabled: !writable || busy, onClick: () => setDialog("new"), title: !writable ? "操作员尚未启用任务提交" : "创建待审批计划" }, "＋ 新建目标"))),
      h("div", { className: "wf-boundary" }, h("span", { className: "wf-status-dot" }), h("strong", null, "安全验证 · 部分通过"), h("span", null, "费用硬限额与真实执行验证尚未完成；保持人工审批。")),
      h(Help, { writable }),
      error && h("div", { className: "wf-alert", role: "alert" }, h("span", null, error), h("button", { onClick: () => setError(""), "aria-label": "关闭错误" }, "×")),
      notice && h("div", { className: "wf-notice", role: "status" }, notice, h("button", { onClick: () => setNotice(""), "aria-label": "关闭提示" }, "×")),
      h("section", { className: "wf-metrics", "aria-label": "工作流统计" }, ["执行目标", "运行中的任务", "需要关注"].map((label, i) => h("div", { className: "wf-metric", key: label }, h("span", null, label), h("strong", null, metrics[i]), h("small", null, ["当前项目的执行记录", "由 Hermes 统一派发", "阻塞或缺失的任务"][i])))),
      h("div", { className: "wf-workspace" },
        h("aside", { className: "wf-executions" }, h("div", { className: "wf-section-heading" }, h("h2", null, "执行目标"), h("span", null, rows?.length || 0)),
          h("input", { className: "wf-search", placeholder: "搜索研发目标…", value: query, onChange: e => setQuery(e.target.value), "aria-label": "搜索研发目标" }),
          h("div", { className: "wf-filters" }, h("button", { className: !attention ? "active" : "", onClick: () => setAttention(false) }, "全部"), h("button", { className: attention ? "active" : "", onClick: () => setAttention(true) }, "需要关注")),
          rows === null ? h("p", { className: "wf-loading" }, "正在读取执行记录…") : visible.length ? visible.map(row => h("button", { key: row.execution_id, className: cx("wf-execution", selected === row.execution_id && "selected"), onClick: () => { setError(""); setSelected(row.execution_id); } },
            h("div", { className: "wf-execution-top" }, h(Badge, { tone: state(row) === "running" ? "green" : state(row) === "blocked" ? "amber" : "neutral" }, STATES[state(row)]), h("span", null, date(row.created_at))),
            h("h3", null, row.objective), h("div", { className: "wf-execution-meta" }, h("code", null, short(row.source_revision)), h("span", null, "第 " + ((row.rounds.at(-1)?.number || 0) + 1) + " 轮")))) : h(Empty, { title: query || attention ? "没有匹配的目标" : "还没有执行记录" }, "已有终端执行记录会自动显示在这里。")),
        h("section", { className: "wf-detail", "aria-label": "执行详情" }, !selected ? h(Empty, { title: "把下一步，放在清晰的计划里。" }, writable ? "创建研发目标后，在这里查看任务依赖与执行证据。" : "当前只读。启用受控提交后，可以建立新的待审批目标。") : !detail ? h("div", { className: "wf-loading" }, "正在核验执行状态与证据…") : h(R.Fragment, null,
          h("div", { className: "wf-detail-header" }, h("div", { className: "wf-eyebrow" }, (detail.board === "default" ? "默认看板" : detail.board) + " / 执行编号 " + detail.execution_id.slice(0, 8)), h("div", { className: "wf-title-line" }, h("h2", null, detail.objective), h(Badge, { tone: detail.acceptance.status === "ACCEPTED" ? "green" : "amber" }, ACCEPT[detail.acceptance.status])), h("p", null, "创建于 " + date(detail.created_at), " · ", detail.approved_write ? "已授权候选目录写入" : "尚未授权写入")),
          h("nav", { className: "wf-tabs", "aria-label": "执行详情页签" }, [["overview", "执行概览"], ["evidence", "验收证据"], ["repairs", "整改记录"]].map(([key, label]) => h("button", { key, className: tab === key ? "active" : "", onClick: () => setTab(key) }, label))),
          tab === "overview" && h("div", { className: "wf-content" }, h("div", { className: "wf-section-heading" }, h("h3", null, "任务依赖"), h("span", null, "第 " + (detail.rounds.at(-1).number + 1) + " 轮 · 4 个阶段")),
            h("div", { className: "wf-dag", "aria-label": "调查 → 开发 → 独立审查 → 最终汇总" }, ROLES.map((role, i) => h("button", { key: role, className: cx("wf-node", "wf-node-" + role, focus === role && "focused"), onClick: () => setFocus(role) }, h("span", { className: "wf-avatar" }, ["调", "开", "审", "汇"][i]), h("strong", null, NAMES[role]), h("small", null, STATES[tasks[role]?.status] || "记录缺失")))),
            h("div", { className: "wf-task-info" }, h("div", null, h("span", { className: "wf-label" }, NAMES[focus] + "任务"), h("code", null, activeTask?.id || "—")), h("div", null, h("span", { className: "wf-label" }, "最近运行"), h("strong", null, activeTask?.outcome ? (OUTCOMES[activeTask.outcome] || "其他运行结果") : "尚未运行")), h("div", null, h("span", { className: "wf-label" }, "角色"), h("span", null, NAMES[focus]), h("code", null, activeTask?.assignee || "尚未指派"))),
            h("div", { className: "wf-bottom-grid" }, h("div", { className: "wf-panel" }, h("h3", null, "交付检查"), h("p", { className: "wf-gate-reason" }, detail.acceptance.reason ? message(detail.acceptance.reason) : "当前版本、候选与验证证据已核对。"), h("dl", null, h("dt", null, "源版本"), h("dd", null, h("code", null, short(detail.source_revision))), h("dt", null, "候选版本"), h("dd", null, h("code", null, short(detail.candidate_revision))), h("dt", null, "实际模型接口费用"), h("dd", null, "未获取"))),
              h("div", { className: "wf-panel" }, h("div", { className: "wf-section-heading" }, h("h3", null, "人工操作"), !writable && h("span", null, "只读")), h("div", { className: "wf-actions" }, Object.keys(ACTIONS).map(actionButton)), h("p", { className: "wf-footnote" }, "每次操作都由后端核验条件，任务完成不等于交付验收。")))),
          tab === "evidence" && h("div", { className: "wf-content" }, h("h3", null, "独立验证记录"), h("p", { className: "wf-muted" }, "由操作员运行预设验收命令后生成，记录与当前候选绑定。"), !proof ? h("p", null, "正在读取证据…") : proof.map((item, index) => h("article", { className: "wf-proof", key: index }, h("div", { className: "wf-section-heading" }, h("h3", null, index === 0 ? "开发结果验证" : "审查副本验证"), h(Badge, { tone: item.available && item.receipt.status === "PASS" && item.log_matches ? "green" : "neutral" }, item.available ? (item.log_matches ? (item.receipt.status === "PASS" ? "通过" : "未通过") : "日志不一致") : "尚无证据")), item.available && h(R.Fragment, null, h("p", null, "退出码 ", h("code", null, item.receipt.exit_code), " · 日志校验 ", item.log_matches ? "一致" : "不一致"), h("pre", { className: "wf-command" }, item.receipt.command), h("details", null, h("summary", null, "查看验证日志（最近 16 千字节）"), h("pre", { className: "wf-log" }, item.log_tail))))), h("h3", null, "候选变更"), h("code", { className: "wf-digest" }, detail.candidate_digest || "候选尚未冻结"), h("ul", { className: "wf-files" }, detail.changed_files.map(file => h("li", { key: file }, h("code", null, file))))),
          tab === "repairs" && h("div", { className: "wf-content" }, h("h3", null, "整改与预算"), h("div", { className: "wf-budget" }, h("span", null, "整改上限 ", h("strong", null, detail.budget.max_rounds), " 轮"), h("span", null, "执行时间 ", h("strong", null, Math.round(detail.budget.max_seconds / 60)), " 分钟"), h("span", null, "任务尝试 ", h("strong", null, detail.budget.max_runs), " 次")), detail.failures.length ? detail.failures.map((failure, i) => h("article", { className: "wf-failure", key: i }, h(Badge, { tone: "amber" }, KINDS[failure.kind] || "其他问题"), h("h4", null, failure.reason), h("small", null, date(failure.at)))) : h(Empty, { title: "暂无整改记录" }, "独立审查未通过时，由操作员分类处理。重复失败与预算超限会转交人工。"))
        ))),
      h("footer", { className: "wf-footer" }, h("span", null, "Hermes 工作流"), h("span", null, "复用原生任务看板 · 默认人工受控 · 不自动提交或部署")),
      dialog && h("div", { className: "wf-modal-backdrop", onClick: event => { if (event.target === event.currentTarget && !busy) setDialog(null); } }, h("form", { className: "wf-modal", role: "dialog", "aria-modal": true, "aria-label": dialog === "new" ? "新建研发目标" : ACTIONS[dialog][0], onSubmit: execute },
        h("h2", null, dialog === "new" ? "新建研发目标" : ACTIONS[dialog][0]), dialog === "new" ? h(R.Fragment, null, h("label", null, "研发目标", h("textarea", { required: true, maxLength: 4000, rows: 4, value: objective, onChange: e => setObjective(e.target.value), placeholder: "描述目标、范围与可验证的验收标准…" })), h("label", null, "执行实例名（可选）", h("input", { maxLength: 128, value: instance, onChange: e => setInstance(e.target.value), placeholder: "留空可复用同一版本的已有执行" })), h("p", { className: "wf-muted" }, "只创建待审批任务，不会立即派发写入。")) : h(R.Fragment, null, h("p", null, ACTIONS[dialog][1]), h("code", { className: "wf-confirm-id" }, dialogExecution), dialog === "repair" && h(R.Fragment, null, h("label", null, "失败类型", h("select", { value: kind, onChange: e => setKind(e.target.value) }, [["implementation", "实现错误"], ["test", "测试错误"], ["environment", "环境错误（需人工）"], ["api_model", "接口或模型错误（需人工）"], ["permission", "权限错误（需人工）"], ["requirements", "需求不明确（需人工）"]].map(([value, label]) => h("option", { value, key: value }, label)))), h("label", null, "整改原因", h("textarea", { required: true, maxLength: 2000, rows: 3, value: reason, onChange: e => setReason(e.target.value) }))), h("label", { className: "wf-check" }, h("input", { type: "checkbox", checked: ack, onChange: e => setAck(e.target.checked) }), "我已确认本次操作及其影响范围")),
        error && h("p", { className: "wf-alert", role: "alert" }, error), h("div", { className: "wf-modal-actions" }, h("button", { type: "button", className: "wf-button", disabled: busy, onClick: () => setDialog(null) }, "取消"), h("button", { type: "submit", className: "wf-button wf-primary", disabled: busy || !writable || (dialog !== "new" && !ack) }, busy ? "正在处理…" : dialog === "new" ? "创建待审批目标" : "确认操作"))))
    );
  }
  window.__HERMES_PLUGINS__.register("workflow", App);
})();
