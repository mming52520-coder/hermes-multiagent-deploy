/* Hermes Dashboard plugin. Uses the host React and authenticated API client. */
(function () {
  "use strict";
  const SDK = window.__HERMES_PLUGIN_SDK__;
  if (!SDK || !window.__HERMES_PLUGINS__) return;
  const R = SDK.React, h = R.createElement;
  const { useState, useEffect } = R;
  const EN = {
    "统一模型配置": "Unified model settings",
    "四个 Agent · 统一模型配置": "Four agents · Model settings",
    "在此配置全部角色：选择厂商、导入 Key、选择模型，最后统一保存。": "Configure every role here: choose providers, import keys, select models, then save together.",
    "每个角色的厂商、密钥和模型独立保存。": "Each role keeps its own provider, key and model.",
    "获取全部模型": "Load all model lists",
    "正在获取模型…": "Loading models…",
    "获取模型": "Load models",
    "获取中…": "Loading…",
    "导入 Key 后选择模型": "Import a key, then choose a model",
    "没有获取到模型，可在高级设置手动填写。": "No models returned. Enter a model ID in advanced settings.",
    "厂商未返回实时目录，显示推荐模型。": "The provider did not return a live catalog. Showing recommended models.",
    "已获取 {0} 个模型": "Loaded {0} models",
    "高级设置：API 地址、协议与手动模型": "Advanced: API endpoint, protocol and model ID",
    "手动模型编号": "Manual model ID",
    "快捷操作：一套配置应用全部": "Shortcut: use one connection for every role",
    "共用模型厂商": "Shared provider",
    "共用 API Key": "Shared API key",
    "保存模型配置": "Save model settings",
    "{0}：模型厂商": "{0}: Provider",
    "{0}：API Key": "{0}: API key",
    "{0}：模型名称": "{0}: Model",
    "{0}：API 地址": "{0}: API endpoint",
    "{0}：API 协议": "{0}: API protocol",
    "{0}：手动模型编号": "{0}: Manual model ID",
    "{0}：API 地区": "{0}: API region",
    "Z.AI 国际站 API": "Z.AI international API",
    "智谱中国站 API": "Zhipu China API",
    "Agent 模型连接": "Agent model connections",
    "四个角色可分别选择厂商、模型、API 地址和 Key。": "Each role can use its own provider, model, API endpoint and key.",
    "{0} / 4 已配置": "{0} / 4 configured",
    "一套连接应用全部": "Apply one connection to all",
    "单独配置": "Configure role",
    "尚未配置": "Not configured",
    "Key 已保存": "Key saved",
    "需要填写 Key": "API key required",
    "配置全部 Agent": "Configure all agents",
    "配置{0}": "Configure {0}",
    "模型厂商": "Provider",
    "模型名称": "Model",
    "API 地址": "API endpoint",
    "API 协议": "API protocol",
    "自定义兼容 API": "Custom compatible API",
    "保存并应用": "Save and apply",
    "模型配置已保存": "Model configuration saved",
    "新目标将使用此连接；当前目标的配置不会改变。": "New objectives will use this connection. The current objective keeps its settings.",
    "同步到当前未启动目标；修改后需要重新审批。": "Also update the current unstarted objective. New approval is required after the change.",
    "模型配置读取失败，请重试。": "Could not load model settings. Try again.",
    "重试读取": "Retry",
    "正在读取模型连接…": "Loading model connections…",
    "使用推荐模型即可；也可输入其他模型名称。": "Use the recommended model or enter another model ID.",
    "API Key": "API key",
    "已保存，留空沿用": "Saved; leave blank to reuse",
    "输入所选厂商的 Key": "Enter the selected provider's key",
    "密钥保存在本机角色配置中，不会返回到浏览器。": "Keys are stored in local role profiles and are never returned to the browser.",
    "只填写一个 Key，即可让四个 Agent 使用所选连接。": "Enter one key to let all four agents use this connection.",
    "不同厂商需要各自的 Key；OpenRouter 等聚合服务可用一把 Key 选择多家模型。": "Direct providers need their own keys. Aggregators such as OpenRouter offer multiple model vendors with one key.",
    "获取 API Key": "Get an API key",
    "原生接口": "Native API",
    "Google Gemini 原生接口": "Google Gemini API",
    "阿里云百炼（中国）": "Alibaba Cloud DashScope (China)",
    "阿里云百炼（国际）": "Qwen Cloud",
    "阿里云 Coding Plan": "Alibaba Cloud (Coding Plan)",
    "阿里云 Coding Plan（中国）": "Alibaba Cloud (Coding Plan, China)",
    "阿里云 Token Plan": "Alibaba Cloud (Token Plan)",
    "阿里云 Token Plan（中国）": "Alibaba Cloud (Token Plan, China)",
    "Google AI Studio（Gemini）": "Google AI Studio",
    "月之暗面 Kimi（中国）": "Kimi / Moonshot (China)",
    "月之暗面 Kimi（国际）": "Kimi / Kimi Coding Plan",
    "智谱 GLM": "Z.AI (GLM)",
    "MiniMax（中国）": "MiniMax (China)",
    "阶跃星辰 Step Plan": "StepFun Step Plan",
    "腾讯 TokenHub": "Tencent TokenHub",
    "腾讯 TokenPlan": "Tencent TokenPlan",
    "小米 MiMo": "Xiaomi MiMo",
    "执行预算策略": "Execution budget policy",
    "实际费用硬限额尚未实现；配置有限费用上限时将拒绝执行。": "Hard API cost limits are not implemented. Execution is refused when a finite cost cap is configured.",
    "任务输出和容器镜像": "Task outputs and container image",
    "在项目绑定配置中设置 OUTPUT_DIR 和 DOCKER_IMAGE。": "Set OUTPUT_DIR and DOCKER_IMAGE in the project configuration.",
    "需要 Hermes v0.22.5，并启用 kanban.dispatch_in_gateway。": "Requires Hermes v0.22.5 with kanban.dispatch_in_gateway enabled.",
    "已审批待启动": "Approved, awaiting launch",
    "待启动": "Awaiting launch",
    "待准备审查": "Awaiting review preparation",
    "人工审批于 {0}": "Approved by an operator at {0}",

    "人工审批": "Approve objective",
    "启动多 Agent": "Start multi-agent execution",
    "仅记录当前目标与轮次的人工授权，不会派发任务或调用模型。": "Record operator approval for this objective and round. No task dispatch or model call occurs.",
    "按任务依赖启动原生多智能体执行，可能调用真实模型并产生费用。": "Start native multi-agent execution according to dependencies. Real model calls may incur charges.",
    "执行准备": "Execution readiness",
    "创建目标 → 人工审批 → 启动执行": "Create objective → Approve → Start execution",
    "可以先创建目标和审批；启动前需要完成以下准备。": "You can create and approve an objective first. Complete these prerequisites before starting.",
    "已就绪": "Ready",
    "未就绪": "Not ready",
    "配置角色和模型": "Configure roles and models",
    "系统设置": "System settings",
    "Docker 执行环境": "Docker environment",
    "验收命令": "Verification command",
    "项目源版本": "Project source revision",
    "原生执行引擎": "Native execution engine",
    "请安装并启动 Docker。": "Install and start Docker.",
    "Docker 已就绪。": "Docker is ready.",
    "Docker 服务不可用，请检查服务和当前用户权限。": "Docker is unavailable. Check the service and current user permissions.",
    "Docker 检查失败或超时。": "Docker check failed or timed out.",
    "由操作员在项目绑定配置中设置，不接收网页任意命令。": "Set by the operator in the project configuration. Arbitrary commands cannot be supplied from this page.",
    "使用干净且版本一致的项目；候选修改保存在独立副本。": "Use a clean, matching project revision. Candidate changes stay in an independent copy.",
    "模型配置已就绪。": "Model configuration is ready.",
    "请在此角色配置中设置模型及其凭据。": "Set the model and its credentials in this role profile.",
    "启动时按需连接原生 Gateway。": "The native Gateway is connected on demand at launch.",
    "网页启动需要已适配的 Hermes v0.22.5。": "Starting from the dashboard requires the supported Hermes v0.22.5.",
    "等待人工审批": "Awaiting operator approval",
    "确认目标和候选范围后，先审批当前轮次；审批不会立即启动。": "Check the objective and candidate scope, then approve this round. Approval does not start execution.",
    "已审批，等待启动": "Approved, awaiting launch",
    "审批已记录。执行环境就绪后，点击启动，由原生引擎按依赖派发任务。": "Approval is recorded. When prerequisites are ready, start the native engine to dispatch tasks by dependency.",
    "请先完成人工审批": "Approve this objective first",
    "执行环境尚未就绪，请查看执行准备": "Execution prerequisites are incomplete. Check readiness.",
    "当前轮次已经审批": "This round is already approved",
    "调度请求已处理，请查看任务状态；没有把等待资源当作执行成功。": "The dispatch request was processed. Check task status; waiting for resources is not reported as successful execution.",
    "已派发 {0} 个任务，后续阶段按依赖执行。": "Dispatched {0} task(s). Later stages follow their dependencies.",
    "准备审查或启动执行后，可在此查看任务依赖与运行结果。": "After preparing review or starting execution, inspect dependencies and results here.",
    "项目：{0} · 看板：{1}": "Project: {0} · Board: {1}",

    "下一步": "Next step",
    "状态已同步": "Status synchronized",
    "正在同步状态…": "Synchronizing status…",
    "上次同步 {0}": "Last synced {0}",
    "尚未同步": "Not synced yet",
    "同步失败，正在显示上次成功读取的状态。": "Sync failed. Showing the last successfully loaded status.",
    "同步失败，尚无可用状态。": "Sync failed. No status is available yet.",
    "同步完成前暂不可操作": "Actions are paused until synchronization succeeds",
    "重新读取": "Retry",
    "暂时无法读取执行详情": "Execution details are temporarily unavailable",
    "暂时无法读取执行列表": "Execution list is temporarily unavailable",
    "保留目标选择，刷新后重新核验。": "Your selection is preserved. Refresh to check the execution again.",
    "等待人工授权": "Awaiting operator authorization",
    "确认目标和候选范围后，由操作员授权调查与开发。": "After checking the objective and candidate scope, an operator can authorize research and build.",
    "当前只读，可查看进度和证据；执行操作需由操作员授权。": "Read-only: progress and evidence are available. Execution actions require operator authorization.",
    "等待调查与开发完成": "Waiting for research and build",
    "继续释放待审批任务": "Resume pending task release",
    "本次已获授权，仍有待审批任务；操作员可重试授权执行以恢复放行。": "This execution is authorized but still has pending tasks. An operator can retry approval to resume their release.",
    "继续释放审查任务": "Resume review task release",
    "候选副本已冻结，仍有待审批的审查或汇总任务；可由操作员重试准备独立审查。": "The candidate is frozen but review or summary tasks are still pending. An operator can retry review preparation.",
    "任务由 Hermes 派发，完成后再准备冻结候选副本。": "Hermes dispatches the tasks. Wait for completion before freezing the candidate.",
    "调查与开发已经完成，由操作员冻结候选副本并释放审查任务。": "Research and build have finished. An operator can freeze the candidate and release review tasks.",
    "等待独立审查": "Waiting for independent review",
    "独立审查使用冻结副本，完成后再核对最终汇总与交付证据。": "Review uses the frozen snapshot. Then check the final summary and delivery evidence.",
    "等待最终汇总": "Waiting for the final summary",
    "等待汇总任务完成，再检查验证记录和审查结论。": "Wait for the summary task, then check verification records and the review verdict.",
    "核对交付证据": "Check delivery evidence",
    "四阶段任务已完成；请检查两份验证记录和审查结论，再提交质量验收。": "All four tasks have finished. Check both verification records and the review verdict before requesting acceptance.",
    "等待人工验收": "Awaiting operator acceptance",
    "交付证据已通过当前检查，仍需操作员明确提交验收。": "The evidence passes the current checks. An operator must still explicitly request acceptance.",
    "交付已验收": "Delivery accepted",
    "当前候选与验证记录已通过验收，可在证据页核对交付内容。": "The current candidate and verification records passed acceptance. Inspect the delivery on the evidence tab.",
    "处理阻塞任务": "Resolve blocked tasks",
    "有阶段被阻塞，请先查看对应任务，再由操作员决定整改或人工处理。": "A stage is blocked. Inspect the task, then let an operator decide on repair or manual intervention.",
    "任务记录不完整": "Task records are incomplete",
    "当前任务记录缺失，请由操作员检查任务看板和执行记录。": "Task records are missing. Ask an operator to check the board and execution records.",
    "查看阻塞阶段": "View blocked stage",
    "查看验收证据": "View evidence",
    "阶段完成进度": "Stage completion progress",
    "{0} / 4 个阶段完成": "{0} / 4 stages complete",
    "阶段完成不代表质量验收通过。": "Stage completion does not imply quality acceptance.",
    "建议基于当前状态，具体操作仍会重新核验。": "Guidance reflects the current status. Each action is checked again before execution.",
    "证据读取未完成，请刷新后重试。": "Evidence could not be loaded. Refresh to try again.",
    "第 {0} 轮": "Round {0}",
    "第 {0} 轮 · 4 个阶段": "Round {0} · 4 stages",
    " / 执行编号 ": " / Execution ID ",
    " · 日志校验 ": " · Log checksum ",
    " 分钟": " minutes",
    " 次": " attempts",
    " 轮": " rounds",
    " 轮 · 4 个阶段": " · 4 stages",
    "Enter / 空格": "Enter / Space",
    "Hermes · 多智能体工作流": "Hermes · Multi-agent workflow",
    "Hermes 工作流": "Hermes Workflow",
    "Hermes 源码未通过已审计基线校验，请由操作员检查安装来源。": "Hermes source did not pass the audited baseline check. Ask the operator to verify the installation.",
    "↻ 刷新": "↻ Refresh",
    "一致": "Matches",
    "不一致": "Mismatch",
    "交付检查": "Delivery checks",
    "人工受控": "Operator controlled",
    "人工操作": "Operator actions",
    "仅针对当前独立审查失败创建开发、审查和汇总任务；新轮次仍需重新授权。": "Create build, review and summary tasks for the current failed review. The new round requires fresh approval.",
    "从研发目标到交付证据，每一步都可追溯。": "Trace every step from an engineering objective to delivery evidence.",
    "任务": " task",
    "任务交接信息与当前候选不一致。": "Task handoff does not match the current candidate.",
    "任务依赖": "Task dependencies",
    "任务尝试 ": "Task attempts ",
    "任务尝试次数已达到上限，需要人工介入。": "The task-attempt budget is exhausted. Operator intervention is required.",
    "任务已登记，尚未获准执行。": "The task is registered and awaiting approval.",
    "任务结束不代表交付合格；只有证据通过核对后才显示“已验收”。": "Task completion is not delivery acceptance. Accepted is shown only after the evidence passes verification.",
    "使用说明与按键": "Help and keyboard shortcuts",
    "候选内容在冻结后发生了变化，需要重新准备验证。": "Candidate content changed after preparation. Verification must be prepared again.",
    "候选副本尚未准备完成。": "The candidate snapshot has not been prepared.",
    "候选变更": "Candidate changes",
    "候选尚未冻结": "Candidate not prepared",
    "候选版本": "Candidate revision",
    "候选版本已经改变。": "The candidate revision has changed.",
    "全部": "All",
    "关闭提示": "Dismiss notice",
    "关闭操作确认弹窗；操作处理中需等待完成。": "Close the confirmation dialog. Wait if an operation is in progress.",
    "关闭错误": "Dismiss error",
    "其他运行结果": "Other outcome",
    "其他问题": "Other issue",
    "准备独立审查": "Prepare independent review",
    "创建于 ": "Created ",
    "创建待审批目标": "Create pending objective",
    "创建待审批计划": "Create a plan for approval",
    "创建待审批计划，不会立即运行。只读时不可用。": "Create a plan awaiting approval. It does not run immediately and is unavailable in read-only mode.",
    "创建整改轮次": "Create repair round",
    "创建研发目标后，在这里查看任务依赖与执行证据。": "Create an objective to inspect task dependencies and execution evidence here.",
    "刷新": "Refresh",
    "刷新工作流": "Refresh workflow",
    "原始信息": "Original details",
    "取消": "Cancel",
    "只创建待审批任务，不会立即派发写入。": "Create pending tasks only. Write operations are not dispatched immediately.",
    "只有独立审查已完成且未通过时，才能创建整改轮次。": "A repair round requires a completed, failed independent review.",
    "只读": "Read-only",
    "只读模式": "Read-only mode",
    "可提交验收": "Ready for acceptance",
    "后端将重新核对版本、实际变更、两份验证记录和独立审查结果；不合格的执行会被拒绝。": "The backend checks revisions, actual changes, both verification receipts and the independent review. Incomplete evidence is rejected.",
    "向后或向前移动焦点。": "Move focus forward or backward.",
    "启动失败": "Launch failed",
    "四阶段卡片": "Four-stage cards",
    "在按钮或说明标题上确认、展开或收起；输入框保留正常输入行为。": "Activate a button or expand/collapse help. Text fields retain their normal input behavior.",
    "在独立容器中运行操作员预设的验收命令，记录实际退出状态与日志。": "Run the operator-configured checks in an isolated container and record the actual exit status and logs.",
    "复用原生任务看板 · 默认人工受控 · 不自动提交或部署": "Native Kanban · Operator controlled · No automatic commits or deployment",
    "失败类型": "Failure category",
    "存在需要处理的问题，请查看详情。": "This execution needs attention. Open its details.",
    "安全验证 · 部分通过": "Safety validation · Partial pass",
    "实现错误": "Implementation error",
    "实现问题": "Implementation issue",
    "实际模型接口费用": "Actual model API cost",
    "审": "R",
    "审查任务已经发布，不能替换其候选副本。": "The review has already been released. Its candidate snapshot cannot be replaced.",
    "审查副本与候选版本不一致。": "The review revision does not match the candidate.",
    "审查副本验证": "Review snapshot verification",
    "将冻结开发候选并释放审查任务。已发布的审查副本不能替换。": "Prepare the candidate snapshot and release the review task. A published snapshot cannot be replaced.",
    "将释放调查与开发任务，仅允许修改此执行的候选副本。可能产生模型费用，当前尚无全局费用硬限额。": "Release research and build tasks. Only this execution's candidate is writable. Model charges may apply; a global hard cost cap is not yet available.",
    "尚无证据": "No evidence yet",
    "尚未发现可核对的实际代码变更。": "No verifiable code changes were found.",
    "尚未指派": "Unassigned",
    "尚未授权写入": "Write access not approved",
    "尚未生成": "Not generated",
    "尚未运行": "Not run yet",
    "尚未配置验收命令。": "No verification command is configured.",
    "尚未验收": "Not accepted",
    "工作流统计": "Workflow statistics",
    "已中断": "Interrupted",
    "已停止重试": "Retries stopped",
    "已取消": "Cancelled",
    "已完成": "Completed",
    "已完成 / 已验收": "Completed / Accepted",
    "已归档": "Archived",
    "已授权候选目录写入": "Candidate write access approved",
    "已有终端执行记录会自动显示在这里。": "Existing CLI execution records appear here automatically.",
    "已由恢复流程接管": "Reclaimed by recovery",
    "已终止": "Terminated",
    "已阻塞": "Blocked",
    "已验收": "Accepted",
    "开": "B",
    "开发": "Build",
    "开发与审查副本的内容不一致。": "The candidate and review snapshots have different content.",
    "开发任务报告的文件列表与实际变更不一致。": "The builder's changed-file list does not match the actual candidate.",
    "开发结果验证": "Build verification",
    "当前 Hermes 版本尚未适配此写入操作，请保持只读模式。": "This Hermes version does not support workflow writes. Keep read-only mode enabled.",
    "当前为只读模式": "Read-only mode is enabled",
    "当前为只读模式。灰色按钮表示操作未开放，不是页面故障。Hermes v0.22.5 的工作流写入仍未适配。": "Read-only mode is enabled. Disabled buttons are unavailable actions, not a page error. Hermes v0.22.5 workflow writes are not yet supported.",
    "当前只读。启用受控提交后，可以建立新的待审批目标。": "Read-only mode. Enable controlled submission to create objectives awaiting approval.",
    "当前版本、候选与验证证据已核对。": "Revisions, candidate content and verification evidence match.",
    "当前版本无法强制执行费用上限，请由操作员处理。": "This version cannot enforce a hard cost cap. Operator intervention is required.",
    "当前账号或应用模式不允许此操作。": "This account or application mode does not allow this operation.",
    "当前项目的执行记录": "Execution records for this project",
    "待审批": "Awaiting approval",
    "待执行": "Ready",
    "怎样理解状态": "Understanding states",
    "意外退出": "Crashed",
    "成功完成": "Completed successfully",
    "我已确认本次操作及其影响范围": "I confirm this operation and its scope",
    "执行中": "Running",
    "执行失败": "Failed",
    "执行实例名（可选）": "Execution instance (optional)",
    "执行操作前需要明确勾选，再点击“确认操作”；灰色按钮不能由键盘绕过。": "Tick the confirmation box before selecting Confirm. Keyboard shortcuts cannot bypass disabled actions.",
    "执行时间 ": "Execution time ",
    "执行时间预算已用尽，需要人工介入。": "The execution time budget is exhausted. Operator intervention is required.",
    "执行概览": "Overview",
    "执行目标": "Objectives",
    "执行详情": "Execution details",
    "执行详情页签": "Execution detail tabs",
    "执行超时": "Timed out",
    "执行进程仍在运行，暂时不能修改目录权限。": "A worker is still running. Its mounted permissions cannot be changed.",
    "找不到所需记录或接口，请检查插件安装并刷新页面。": "The record or API was not found. Check plugin installation and refresh.",
    "把下一步，放在清晰的计划里。": "Put the next step in a clear plan.",
    "按钮的作用": "What the buttons do",
    "授权执行": "Approve execution",
    "接口或模型错误（需人工）": "API or model error (operator required)",
    "接口或模型问题": "API or model issue",
    "描述目标、范围与可验证的验收标准…": "Describe the objective, scope and verifiable acceptance criteria…",
    "提交质量验收": "Submit for acceptance",
    "搜索研发目标": "Search engineering objectives",
    "搜索研发目标…": "Search objectives…",
    "操作员尚未启用任务提交": "The operator has not enabled task submission",
    "操作已完成，执行状态已更新。": "Operation completed. Execution status is updated.",
    "操作未完成，请由操作员查看后台诊断日志。": "Operation failed. Ask the operator to inspect backend diagnostics.",
    "操作需要人工确认，并由后端核验条件。支持范围请查看安装说明。": "Actions require operator confirmation and backend validation. See the installation guide for supported versions.",
    "整改上限 ": "Repair limit ",
    "整改与预算": "Repairs and budgets",
    "整改原因": "Repair reason",
    "整改记录": "Repairs",
    "整改轮次已达到上限。": "The maximum number of repair rounds has been reached.",
    "新建目标": "New objective",
    "新建研发目标": "New engineering objective",
    "无法连接网页后台，请确认服务已启动后重试。": "Cannot connect to the backend. Check the server and try again.",
    "日志不一致": "Log mismatch",
    "暂无整改记录": "No repair records",
    "最终汇总": "Final summary",
    "最近运行": "Latest run",
    "有任务尚未成功完成，请先检查四阶段状态。": "Some tasks have not completed successfully. Check all four stages.",
    "未获取": "Unavailable",
    "未通过": "Failed",
    "本次执行尚未获得写入授权。": "Write access has not been approved for this execution.",
    "执行依赖尚未就绪，请查看页面顶部的检查项。": "Execution prerequisites are not ready. Review the checklist above.",
    "当前为只读模式。灰色按钮表示操作员尚未开放写入。": "Read-only mode. Disabled buttons mean the operator has not enabled writes.",
    "{0} 项待完成": "{0} pending",
    "源版本 {0} · 第 {1} 轮": "Source {0} · Round {1}",
    "执行轮次已变化，请刷新后重新确认。": "The execution round changed. Refresh and confirm again.",
    "权限错误（需人工）": "Permission error (operator required)",
    "权限问题": "Permission issue",
    "查看失败分类、历史轮次，以及时间和尝试次数上限。": "Inspect failure categories, previous rounds, time limits and attempt budgets.",
    "查看开发与审查副本的验证结果、原始命令和日志。": "Inspect build/review verification results, original commands and logs.",
    "查看验证日志（最近 16 千字节）": "View verification log (last 16 KB)",
    "正在处理…": "Processing…",
    "正在核验执行状态与证据…": "Checking execution status and evidence…",
    "正在读取执行记录…": "Loading execution records…",
    "正在读取证据…": "Loading evidence…",
    "此类问题需要人工处理。": "This failure category requires operator intervention.",
    "每次操作都由后端核验条件，任务完成不等于交付验收。": "The backend validates every action. Task completion does not mean delivery acceptance.",
    "汇": "G",
    "没有匹配的目标": "No matching objectives",
    "测试错误": "Test error",
    "测试问题": "Test issue",
    "浏览与查看": "Browsing and inspection",
    "源版本": "Source revision",
    "源项目在执行期间产生了未提交改动，需要人工检查。": "The source project acquired uncommitted changes during execution. Operator inspection is required.",
    "源项目有尚未保存到版本库的改动，请先保留这些改动并选择干净的源版本。": "The source project has uncommitted changes. Preserve them and select a clean source revision.",
    "源项目版本已经改变，需要重新核对执行记录。": "The source revision changed. Recheck the execution record.",
    "点击调查、开发、独立审查或最终汇总，查看对应任务的运行结果。": "Select Research, Build, Independent review or Final summary to inspect the corresponding run.",
    "版本号、任务编号、命令、路径及验证日志保留原文，便于核对。": "Revisions, task IDs, commands, paths and verification logs keep their original text for inspection.",
    "独立审查": "Independent review",
    "独立审查尚未通过。": "The independent review has not passed.",
    "独立审查未通过时，由操作员分类处理。重复失败与预算超限会转交人工。": "The operator classifies failed reviews. Repeated failures and exhausted budgets require human intervention.",
    "独立验证记录": "Independent verification",
    "环境错误（需人工）": "Environment error (operator required)",
    "环境问题": "Environment issue",
    "由 Hermes 统一派发": "Dispatched by Hermes",
    "由操作员运行预设验收命令后生成，记录与当前候选绑定。": "Generated by operator-configured checks and bound to the current candidate.",
    "留空可复用同一版本的已有执行": "Leave empty to reuse an existing execution for the same revision",
    "登录状态已失效，请刷新页面或重新登录。": "Your session expired. Refresh the page or sign in again.",
    "目标已建立，任务等待审批。": "Objective created. Tasks are awaiting approval.",
    "相同问题重复出现，需要人工介入。": "The same failure occurred again. Operator intervention is required.",
    "研发工作台": "Engineering workspace",
    "研发目标": "Engineering objective",
    "确认勾选框": "Confirmation checkbox",
    "确认操作": "Confirm",
    "第 ": "Round ",
    "等待依赖": "Waiting for dependencies",
    "等待审查": "Awaiting review",
    "缺少操作员生成的验证证据。": "Operator verification evidence is missing.",
    "缺少验证结果交接信息。": "Verification handoff is missing.",
    "网络连接失败，请检查后台服务。": "Network connection failed. Check the backend service.",
    "角色": "Role",
    "记录缺失": "Missing record",
    "请先准备独立审查并冻结候选副本。": "Prepare independent review and the candidate snapshot first.",
    "请先由操作员配置有效的验收命令。": "Ask the operator to configure a meaningful verification command first.",
    "请求参数无效，请检查填写内容后重试。": "Invalid request. Check the input and try again.",
    "请等待当前执行进程结束后再整改。": "Wait for the current worker to stop before creating repairs.",
    "调": "R",
    "调查": "Research",
    "调查 → 开发 → 独立审查 → 最终汇总": "Research → Build → Independent review → Final summary",
    "费用硬限额与真实执行验证尚未完成；保持人工审批。": "Hard cost limits and real execution validation are incomplete. Keep operator approval enabled.",
    "输入目标名称查找记录；“需要关注”仅显示阻塞或记录缺失的目标。": "Search by objective. Needs attention shows blocked tasks and missing records.",
    "运行中的任务": "Running tasks",
    "还没有执行记录": "No executions yet",
    "退出码 ": "Exit code ",
    "通过": "Passed",
    "重新读取任务状态；不会启动任务。页面也会每 20 秒自动刷新。": "Reload task status without starting any task. The page also refreshes automatically every 20 seconds.",
    "针对相同候选的审查副本执行独立验证，记录可核对的证据。": "Verify the review snapshot of the same candidate and record independent evidence.",
    "键盘操作": "Keyboard shortcuts",
    "阻塞或缺失的任务": "Blocked tasks or missing records",
    "需求不明确（需人工）": "Unclear requirements (operator required)",
    "需求问题": "Requirements issue",
    "需要修改": "Changes requested",
    "需要先完成前置任务。": "Prerequisite tasks must complete first.",
    "需要关注": "Needs attention",
    "验收记录已失效，需要重新核对证据。": "The acceptance record is stale. Recheck the evidence.",
    "验收证据": "Evidence",
    "验证审查副本": "Verify review snapshot",
    "验证开发结果": "Verify build",
    "验证期间候选内容发生变化，本次证据不可用于验收。": "The candidate changed during verification. This evidence cannot be accepted.",
    "验证记录失败、已过期或被改动，不能用于验收。": "The verification record failed, expired or changed and cannot be accepted.",
    "默认看板": "Default board",
    "＋ 新建目标": "＋ New objective"
  };
  const ZH = Object.fromEntries(Object.entries(EN).map(([zh, en]) => [en, zh]));
  function useText() {
    const { locale } = SDK.useI18n();
    return (value, ...values) => {
      const text = locale === "en" ? (EN[value] ?? value) : (ZH[value] ?? value);
      return typeof text === "string" ? text.replace(/\{(\d+)\}/g, (token, index) => Number(index) < values.length ? String(values[Number(index)]) : token) : text;
    };
  }
  const API = "/api/plugins/workflow";
  const ROLES = ["researcher", "builder", "reviewer", "orchestrator"];
  const NAMES = { researcher: "调查", builder: "开发", reviewer: "独立审查", orchestrator: "最终汇总" };
  const STATES = { approved: "已审批待启动", triage: "待审批", todo: "等待依赖", ready: "待执行", running: "执行中", blocked: "已阻塞", done: "已完成", archived: "已归档", missing: "记录缺失" };
  const ACCEPT = { ACCEPTED: "已验收", NOT_ACCEPTED: "尚未验收", READY_FOR_ACCEPTANCE: "可提交验收" };
  const OUTCOMES = { completed: "成功完成", blocked: "已阻塞", failed: "执行失败", crashed: "意外退出", spawn_failed: "启动失败", gave_up: "已停止重试", reclaimed: "已由恢复流程接管", review_requested: "等待审查", changes_requested: "需要修改", dependency_wait: "等待依赖", timeout: "执行超时", timed_out: "执行超时", cancelled: "已取消", interrupted: "已中断", abandoned: "已终止" };
  const KINDS = { implementation: "实现问题", test: "测试问题", environment: "环境问题", api_model: "接口或模型问题", permission: "权限问题", requirements: "需求问题" };
  const ACTIONS = {
    approve: ["人工审批", "仅记录当前目标与轮次的人工授权，不会派发任务或调用模型。"],
    launch: ["启动多 Agent", "按任务依赖启动原生多智能体执行，可能调用真实模型并产生费用。"],
    "prepare-review": ["准备独立审查", "将冻结开发候选并释放审查任务。已发布的审查副本不能替换。"],
    "verify-builder": ["验证开发结果", "在独立容器中运行操作员预设的验收命令，记录实际退出状态与日志。"],
    "verify-reviewer": ["验证审查副本", "针对相同候选的审查副本执行独立验证，记录可核对的证据。"],
    accept: ["提交质量验收", "后端将重新核对版本、实际变更、两份验证记录和独立审查结果；不合格的执行会被拒绝。"],
    repair: ["创建整改轮次", "仅针对当前独立审查失败创建开发、审查和汇总任务；新轮次仍需重新授权。"],
  };
  function cx() { return Array.from(arguments).filter(Boolean).join(" "); }
  function short(value) { return value ? String(value).slice(0, 10) : "尚未生成"; }
  function date(value, locale) { return new Intl.DateTimeFormat(locale === "en" ? "en" : "zh-CN", { month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit" }).format(new Date(value * 1000)); }
  function message(error) {
    let raw = String(error && error.message || error);
    try { const data = JSON.parse(raw.replace(/^\d+:\s*/, "")); raw = data.detail || raw; } catch (_) { /* host may return plain text */ }
    const hints = {
      WRITE_NOT_APPROVED: "本次执行尚未获得写入授权。", ROUND_CHANGED: "执行轮次已变化，请刷新后重新确认。", EXECUTION_NOT_READY: "执行依赖尚未就绪，请查看页面顶部的检查项。", COST_UNAVAILABLE: "当前版本无法强制执行费用上限，请由操作员处理。",
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
  function finished(task) { return task && ["done", "archived"].includes(task.status); }
  function needsAttention(row) { const tasks = current(row); return ROLES.some(role => !tasks[role] || ["blocked", "missing"].includes(tasks[role].status)); }
  function state(row) {
    const tasks = ROLES.map(role => current(row)[role]);
    if (tasks.some(task => !task || task.status === "missing")) return "missing";
    if (tasks.some(task => task.status === "running")) return "running";
    if (tasks.some(task => task.status === "blocked")) return "blocked";
    if (tasks.every(finished)) return "done";
    if (row.approved_write && tasks.every(task => task.status === "triage")) return "approved";
    return ["ready", "todo", "triage"].find(status => tasks.some(task => task.status === status)) || "missing";
  }
  function nextStep(detail) {
    const tasks = current(detail);
    if (detail.acceptance.status === "ACCEPTED") return { title: "交付已验收", text: "当前候选与验证记录已通过验收，可在证据页核对交付内容。", evidence: true };
    if (ROLES.some(role => !tasks[role] || tasks[role].status === "missing")) return { title: "任务记录不完整", text: "当前任务记录缺失，请由操作员检查任务看板和执行记录。" };
    const blocked = ROLES.find(role => tasks[role].status === "blocked");
    if (blocked) return { title: "处理阻塞任务", text: "有阶段被阻塞，请先查看对应任务，再由操作员决定整改或人工处理。", focus: blocked };
    if (detail.acceptance.status === "READY_FOR_ACCEPTANCE") return { title: "等待人工验收", text: "交付证据已通过当前检查，仍需操作员明确提交验收。", action: "accept", evidence: true };
    if (!detail.approved_write) return { title: "等待人工审批", text: "确认目标和候选范围后，先审批当前轮次；审批不会立即启动。", action: "approve" };
    if (!detail.candidate_digest && ["researcher", "builder"].some(role => tasks[role].status === "triage")) return { title: "已审批，等待启动", text: "审批已记录。执行环境就绪后，点击启动，由原生引擎按依赖派发任务。", action: "launch" };
    if (!finished(tasks.researcher) || !finished(tasks.builder)) return { title: "等待调查与开发完成", text: "任务由 Hermes 派发，完成后再准备冻结候选副本。" };
    if (!detail.candidate_digest) return { title: "准备独立审查", text: "调查与开发已经完成，由操作员冻结候选副本并释放审查任务。", action: "prepare-review" };
    if (["reviewer", "orchestrator"].some(role => tasks[role].status === "triage")) return { title: "继续释放审查任务", text: "候选副本已冻结，仍有待审批的审查或汇总任务；可由操作员重试准备独立审查。", action: "prepare-review" };
    if (!finished(tasks.reviewer)) return { title: "等待独立审查", text: "独立审查使用冻结副本，完成后再核对最终汇总与交付证据。", action: tasks.reviewer.status === "running" ? null : "launch" };
    if (!finished(tasks.orchestrator)) return { title: "等待最终汇总", text: "等待汇总任务完成，再检查验证记录和审查结论。", action: tasks.orchestrator.status === "running" ? null : "launch" };
    return { title: "核对交付证据", text: "四阶段任务已完成；请检查两份验证记录和审查结论，再提交质量验收。", evidence: true };
  }

  function Help(props) {
    const ui = useText();
    const browsing = [[ui("刷新"), ui("重新读取任务状态；不会启动任务。页面也会每 20 秒自动刷新。")], [ui("搜索研发目标"), ui("输入目标名称查找记录；“需要关注”仅显示阻塞或记录缺失的目标。")], [ui("四阶段卡片"), ui("点击调查、开发、独立审查或最终汇总，查看对应任务的运行结果。")], [ui("验收证据"), ui("查看开发与审查副本的验证结果、原始命令和日志。")], [ui("整改记录"), ui("查看失败分类、历史轮次，以及时间和尝试次数上限。")]];
    const definitions = items => h("dl", null, items.map(([label, text]) => h(R.Fragment, { key: label }, h("dt", null, ui(label)), h("dd", null, ui(text)))));
    return h("details", { className: "wf-help" }, h("summary", null, ui("使用说明与按键")),
      h("p", null, props.writable ? ui("操作需要人工确认，并由后端核验条件。支持范围请查看安装说明。") : ui("当前为只读模式。灰色按钮表示操作员尚未开放写入。")),
      h("div", { className: "wf-help-grid" },
        h("section", null, h("h2", null, ui("浏览与查看")), definitions(browsing)),
        h("section", null, h("h2", null, ui("按钮的作用")), definitions([[ui("新建目标"), ui("创建待审批计划，不会立即运行。只读时不可用。")], ...Object.values(ACTIONS)])),
        h("section", null, h("h2", null, ui("键盘操作")), definitions([["Tab / Shift + Tab", ui("向后或向前移动焦点。")], [ui("Enter / 空格"), ui("在按钮或说明标题上确认、展开或收起；输入框保留正常输入行为。")], ["Esc", ui("关闭操作确认弹窗；操作处理中需等待完成。")], [ui("确认勾选框"), ui("执行操作前需要明确勾选，再点击“确认操作”；灰色按钮不能由键盘绕过。")]])),
        h("section", null, h("h2", null, ui("怎样理解状态")), definitions([[ui("待审批"), ui("任务已登记，尚未获准执行。")], [ui("等待依赖"), ui("需要先完成前置任务。")], [ui("已阻塞"), ui("存在需要处理的问题，请查看详情。")], [ui("已完成 / 已验收"), ui("任务结束不代表交付合格；只有证据通过核对后才显示“已验收”。")], [ui("原始信息"), ui("版本号、任务编号、命令、路径及验证日志保留原文，便于核对。")]]))));
  }

  function ModelConnections({ execution, onConfigured }) {
    const ui = useText();
    const [data, setData] = useState(null), [drafts, setDrafts] = useState({});
    const [error, setError] = useState(""), [notice, setNotice] = useState("");
    const [saving, setSaving] = useState(false), [fetching, setFetching] = useState([]);
    const [syncCurrent, setSyncCurrent] = useState(true), [refresh, setRefresh] = useState(0);
    const [bulkProvider, setBulkProvider] = useState("openrouter"), [bulkKey, setBulkKey] = useState("");
    const protocols = { chat_completions: "OpenAI Chat Completions", codex_responses: "OpenAI Responses", anthropic_messages: "Anthropic Messages", gemini: "Google Gemini 原生接口", native: "原生接口" };
    const changed = ROLES.filter(role => drafts[role]?.dirty);
    const working = saving || fetching.length > 0;
    useEffect(() => {
      let active = true;
      request("/model-connection").then(value => {
        if (!active) return;
        setData(value);
        setDrafts(Object.fromEntries(ROLES.map(role => {
          const saved = value.roles[role] || {};
          const vendor = value.providers.find(item => item.id === saved.provider) || value.providers[0];
          const matches = saved.provider === vendor.id;
          const model = matches && saved.has_key ? saved.model : "";
          return [role, { provider: vendor.id, model, base_url: matches && saved.base_url || vendor.base_url,
            protocol: matches && saved.protocol || vendor.protocol || "chat_completions", key: "", imported: matches && saved.has_key,
            models: model ? [model] : [], dirty: false, error: "", source: "" }];
        })));
      }, () => { if (active) setError("模型配置读取失败，请重试。"); });
      return () => { active = false; };
    }, [refresh]);
    function update(role, patch) {
      setDrafts(previous => ({ ...previous, [role]: { ...previous[role], ...patch, dirty: true, error: "" } }));
      setNotice("");
    }
    function pickProvider(role, provider) {
      const vendor = data.providers.find(item => item.id === provider);
      update(role, { provider, model: "", models: [], key: "", imported: false, source: "", base_url: vendor.base_url,
        protocol: vendor.protocol === "native" || vendor.protocol === "gemini" ? "chat_completions" : vendor.protocol });
    }
    function parameters(draft) {
      return { provider: draft.provider, model: draft.model, api_key: draft.key, base_url: draft.base_url,
        protocol: draft.provider === "custom" ? draft.protocol : "chat_completions" };
    }
    async function loadModels(roles) {
      setFetching(previous => [...previous, ...roles]); setError(""); setNotice("");
      try {
        const result = await request("/model-connections/models", { method: "POST",
          headers: { "Content-Type": "application/json", "X-Hermes-Workflow-Action": "1" },
          body: JSON.stringify({ connections: Object.fromEntries(roles.map(role => [role, parameters(drafts[role])])) }) });
        setDrafts(previous => {
          const next = { ...previous };
          for (const role of roles) {
            const row = result.roles[role];
            next[role] = row.error ? { ...previous[role], error: row.error } : { ...previous[role], key: "", imported: true,
              models: row.models, model: row.models.includes(previous[role].model) ? previous[role].model : "",
              source: row.source, dirty: true, error: row.models.length ? "" : "没有获取到模型，可在高级设置手动填写。" };
          }
          return next;
        });
      } catch (e) { setError(message(e)); }
      finally { setFetching(previous => previous.filter(role => !roles.includes(role))); }
    }
    async function save(event) {
      event.preventDefault(); setSaving(true); setError(""); setNotice("");
      try {
        await request("/model-connections", { method: "PUT",
          headers: { "Content-Type": "application/json", "X-Hermes-Workflow-Action": "1" },
          body: JSON.stringify({ connections: Object.fromEntries(changed.map(role => [role, parameters(drafts[role])])), execution: syncCurrent ? execution : "" }) });
        setBulkKey(""); setNotice("模型配置已保存"); setRefresh(value => value + 1); onConfigured();
      } catch (e) { setError(message(e)); } finally { setSaving(false); }
    }
    function applyShared() {
      const vendor = data.providers.find(item => item.id === bulkProvider);
      setDrafts(previous => Object.fromEntries(ROLES.map(role => [role, { ...previous[role], provider: vendor.id,
        base_url: vendor.base_url, protocol: vendor.protocol === "native" || vendor.protocol === "gemini" ? "chat_completions" : vendor.protocol,
        model: vendor.default_model, key: bulkKey, models: [], imported: false, dirty: true, source: "", error: "" }])));
      setBulkKey(""); setNotice("");
    }
    return h("section", { className: "wf-model-settings", "aria-label": ui("统一模型配置") },
      h("div", { className: "wf-section-heading" }, h("div", null, h("h2", null, ui("四个 Agent · 统一模型配置")),
        h("p", { className: "wf-muted" }, ui("在此配置全部角色：选择厂商、导入 Key、选择模型，最后统一保存。"))),
        h("span", { className: "wf-badge" }, ui("{0} / 4 已配置", ROLES.filter(role => data?.roles[role]?.has_key && data?.roles[role]?.model).length))),
      !data && h("p", { className: "wf-muted" }, ui("正在读取模型连接…")),
      !data && error && h("button", { className: "wf-button", onClick: () => { setError(""); setRefresh(value => value + 1); } }, ui("重试读取")),
      data && h("form", { className: "wf-model-unified", onSubmit: save },
        h("div", { className: "wf-model-toolbar" },
          h("span", { className: "wf-muted" }, ui("每个角色的厂商、密钥和模型独立保存。")),
          h("button", { type: "button", className: "wf-button", disabled: working, onClick: () => loadModels(ROLES) }, ui(fetching.length ? "正在获取模型…" : "获取全部模型"))),
        h("div", { className: "wf-agent-rows" }, ROLES.map(role => {
          const draft = drafts[role], vendor = data.providers.find(item => item.id === draft.provider);
          const busy = saving || fetching.includes(role);
          const reset = patch => update(role, { ...patch, model: "", models: [], imported: false, source: "" });
          return h("article", { key: role, className: "wf-agent-row", "data-role": role, "aria-label": ui(NAMES[role]) },
            h("div", { className: "wf-role-name" }, h("h3", null, ui(NAMES[role])), h("small", { className: draft.imported ? "wf-key-ready" : "wf-muted" }, ui(draft.imported ? "Key 已保存" : "需要填写 Key"))),
            h("label", null, ui("模型厂商"), h("select", { value: draft.provider, disabled: busy, "aria-label": ui("{0}：模型厂商", ui(NAMES[role])), onChange: event => pickProvider(role, event.target.value) }, data.providers.map(item => h("option", { key: item.id, value: item.id }, ui(item.label)))),
              vendor.regions && h("select", { value: draft.base_url, disabled: busy, "aria-label": ui("{0}：API 地区", ui(NAMES[role])), onChange: event => reset({ base_url: event.target.value }) }, vendor.regions.map(region => h("option", { key: region.base_url, value: region.base_url }, ui(region.label))))),
            h("label", null, ui("API Key"), h("input", { type: "password", autoComplete: "new-password", value: draft.key, disabled: busy,
              "aria-label": ui("{0}：API Key", ui(NAMES[role])), placeholder: ui(draft.imported ? "已保存，留空沿用" : "输入所选厂商的 Key"), onInput: event => reset({ key: event.target.value }) })),
            h("label", null, ui("模型名称"), h("select", { value: draft.model, required: draft.dirty, disabled: busy || !draft.models.length && !draft.model,
              "aria-label": ui("{0}：模型名称", ui(NAMES[role])), onChange: event => update(role, { model: event.target.value }) },
              h("option", { value: "" }, ui("导入 Key 后选择模型")),
              Array.from(new Set([...draft.models, ...(draft.model ? [draft.model] : [])])).map(model => h("option", { key: model, value: model }, model)))),
            h("button", { type: "button", className: "wf-button wf-role-load", disabled: busy, onClick: () => loadModels([role]) }, ui(fetching.includes(role) ? "获取中…" : "获取模型")),
            h("div", { className: "wf-role-extra" },
              draft.source && h("span", { className: "wf-muted" }, ui(draft.source === "catalog" ? "厂商未返回实时目录，显示推荐模型。" : "已获取 {0} 个模型", draft.models.length)),
              draft.error && h("p", { className: "wf-alert", role: "alert" }, ui(draft.error)),
              h("details", { className: "wf-role-advanced", open: draft.provider === "custom" ? true : undefined },
                h("summary", null, ui("高级设置：API 地址、协议与手动模型")),
                h("div", { className: "wf-role-advanced-fields" },
                  h("label", null, ui("API 地址"), h("input", { type: "url", value: draft.base_url, required: draft.dirty && draft.provider === "custom", disabled: busy,
                    "aria-label": ui("{0}：API 地址", ui(NAMES[role])), onInput: event => reset({ base_url: event.target.value }) })),
                  h("label", null, ui("API 协议"), draft.provider === "custom" ? h("select", { value: draft.protocol, disabled: busy,
                    "aria-label": ui("{0}：API 协议", ui(NAMES[role])), onChange: event => reset({ protocol: event.target.value }) },
                    ["chat_completions", "codex_responses", "anthropic_messages"].map(id => h("option", { key: id, value: id }, protocols[id]))) : h("span", { className: "wf-protocol" }, ui(protocols[vendor.protocol] || "原生接口"))),
                  h("label", null, ui("手动模型编号"), h("input", { value: draft.model, disabled: busy,
                    "aria-label": ui("{0}：手动模型编号", ui(NAMES[role])), onInput: event => update(role, { model: event.target.value }) }))))));
        })),
        h("details", { className: "wf-model-bulk" }, h("summary", null, ui("快捷操作：一套配置应用全部")),
          h("div", { className: "wf-model-bulk-fields" },
            h("label", null, ui("模型厂商"), h("select", { value: bulkProvider, disabled: working, "aria-label": ui("共用模型厂商"), onChange: event => setBulkProvider(event.target.value) }, data.providers.map(item => h("option", { key: item.id, value: item.id }, ui(item.label))))),
            h("label", null, ui("API Key"), h("input", { type: "password", autoComplete: "new-password", value: bulkKey, disabled: working,
              "aria-label": ui("共用 API Key"), onInput: event => setBulkKey(event.target.value) })),
            h("button", { type: "button", className: "wf-button", disabled: working, onClick: applyShared }, ui("一套连接应用全部")))),
        h("div", { className: "wf-model-savebar" },
          execution ? h("label", { className: "wf-check" }, h("input", { type: "checkbox", checked: syncCurrent, disabled: working, onChange: event => setSyncCurrent(event.target.checked) }), ui("同步到当前未启动目标；修改后需要重新审批。")) : h("p", { className: "wf-muted" }, ui("新目标将使用此连接；当前目标的配置不会改变。")),
          h("button", { type: "submit", className: "wf-button wf-primary", disabled: working || !changed.length || changed.some(role => !drafts[role].model) }, ui(saving ? "正在处理…" : "保存模型配置")))),
      error && h("p", { className: "wf-alert", role: "alert" }, ui(error)),
      notice && h("p", { className: "wf-notice", role: "status" }, ui(notice)));
  }

  function App() {
    const ui = useText();
    const { locale } = SDK.useI18n();
    const formatDate = value => date(value, locale);
    const [meta, setMeta] = useState(null), [rows, setRows] = useState(null), [selected, setSelected] = useState(null);
    const [snapshotDetail, setDetail] = useState(null), [tab, setTab] = useState("overview"), [focus, setFocus] = useState("researcher");
    const [query, setQuery] = useState(""), [attention, setAttention] = useState(false), [error, setError] = useState("");
    const [busy, setBusy] = useState(false), [dialog, setDialog] = useState(null), [objective, setObjective] = useState("");
    const [instance, setInstance] = useState(""), [ack, setAck] = useState(false), [kind, setKind] = useState("implementation"), [reason, setReason] = useState("");
    const [proof, setProof] = useState(null), [notice, setNotice] = useState("");
    const [dialogExecution, setDialogExecution] = useState(null), [dialogTarget, setDialogTarget] = useState(null);
    const [refreshKey, setRefreshKey] = useState(0), [refreshing, setRefreshing] = useState(true);
    const [readError, setReadError] = useState(""), [updatedAt, setUpdatedAt] = useState(null);
    const detail = snapshotDetail?.execution_id === selected ? snapshotDetail : null;

    function reload() {
      setRefreshing(true);
      setRefreshKey(value => value + 1);
    }
    useEffect(() => {
      if (busy) return;
      let active = true;
      let inFlight = false;
      async function synchronize() {
        if (inFlight) return;
        inFlight = true;
        setRefreshing(true); setReadError("");
        try {
          const [info, data] = await Promise.all([request("/meta"), request("/executions")]);
          if (!active) return;
          setMeta(info); setRows(data.executions);
          const target = data.executions.some(row => row.execution_id === selected) ? selected : data.executions[0]?.execution_id || null;
          if (target !== selected) {
            setSelected(target); setDetail(null); setProof(null); setUpdatedAt(null); setTab("overview");
            return;
          }
          const nextDetail = target ? await request("/executions/" + target) : null;
          let nextProof = null;
          if (nextDetail && tab === "evidence") {
            const number = nextDetail.rounds.at(-1).number;
            nextProof = await Promise.all(["builder", "reviewer"].map(role => request(`/executions/${target}/evidence/${number}/${role}`)));
          }
          if (active) { setDetail(nextDetail); setProof(nextProof); setUpdatedAt(Date.now()); }
        } catch (error) {
          if (active) setReadError(message(error));
        } finally {
          inFlight = false;
          if (active) setRefreshing(false);
        }
      }
      synchronize();
      const timer = setInterval(synchronize, 20000);
      return () => { active = false; clearInterval(timer); };
    }, [selected, tab, refreshKey, busy]);

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
      event.preventDefault();
      if (!canOperate || (dialog !== "new" && (!ack || actionBlocked(dialog)))) return;
      setBusy(true); setError(""); setUpdatedAt(null);
      try {
        if (dialog === "new") {
          const result = await post("/executions", { objective, instance });
          setSelected(result.execution_id); setTab("overview"); setDetail(null); setProof(null); setObjective(""); setInstance("");
          setNotice(ui("目标已建立，任务等待审批。"));
        } else {
          const result = await post(`/executions/${dialogExecution}/actions/${dialog}`, { confirmed: ack, round_number: dialogTarget.round_number, kind, reason });
          setSelected(dialogExecution);
          setNotice(dialog === "launch" ? (result.dispatch?.spawned?.length ? ui("已派发 {0} 个任务，后续阶段按依赖执行。", result.dispatch.spawned.length) : ui("调度请求已处理，请查看任务状态；没有把等待资源当作执行成功。")) : ui("操作已完成，执行状态已更新。"));
        }
        setDialog(null); setAck(false); setReason("");
      } catch (e) { setError(message(e)); } finally { setBusy(false); reload(); }
    }
    const writable = !!meta?.actions_enabled;
    const canOperate = writable && !busy && !refreshing && !readError && updatedAt !== null && (!selected || !!detail);
    const visible = (rows || []).filter(row => row.objective.toLowerCase().includes(query.trim().toLowerCase()) && (!attention || needsAttention(row)));
    const tasks = current(detail), activeTask = tasks[focus];
    const stageLabel = role => detail?.approved_write && tasks[role]?.status === "triage" ? ui(["researcher", "builder"].includes(role) ? "待启动" : "待准备审查") : ui(STATES[tasks[role]?.status]) || ui("记录缺失");
    const metrics = rows === null ? ["—", "—", "—"] : [rows.length, rows.reduce((n, row) => n + Object.values(current(row)).filter(t => t.status === "running").length, 0), rows.filter(needsAttention).length];
    const readiness = detail?.readiness || meta?.readiness;
    function actionBlocked(key) {
      if (!canOperate) return !writable ? ui("当前为只读模式") : ui("同步完成前暂不可操作");
      if (key === "approve" && detail?.approved_write) return ui("当前轮次已经审批");
      if (key === "launch" && !detail?.approved_write) return ui("请先完成人工审批");
      if (key === "launch" && !readiness?.ready) return ui("执行环境尚未就绪，请查看执行准备");
      return "";
    }
    const step = detail ? nextStep(detail) : null;
    const completed = ROLES.filter(role => finished(tasks[role])).length;
    function openAction(key) { setAck(false); setDialogExecution(selected); setDialogTarget({ objective: detail.objective, revision: detail.source_revision, round_number: detail.rounds.at(-1).number }); setError(""); setDialog(key); }
    function focusStage(role) { setFocus(role); document.querySelector(".workflow-app .wf-node-" + role)?.focus(); }
    const actionButton = key => h("button", { key, className: "wf-action", disabled: !!actionBlocked(key), title: actionBlocked(key) || ui(ACTIONS[key][1]), onClick: () => openAction(key) }, ui(ACTIONS[key][0]), h("span", { "aria-hidden": true }, "↗"));

    return h("main", { className: "workflow-app" },
      h("header", { className: "wf-header" }, h("div", null, h("div", { className: "wf-eyebrow" }, ui("Hermes · 多智能体工作流")), h("h1", null, ui("研发工作台")), h("p", null, ui("从研发目标到交付证据，每一步都可追溯。"))),
        h("div", { className: "wf-header-actions" }, h(Badge, { tone: writable ? "green" : "neutral" }, h("i", null), writable ? ui("人工受控") : ui("只读模式")), h("button", { className: "wf-button", disabled: busy || refreshing, onClick: reload, "aria-label": ui("刷新工作流") }, ui("↻ 刷新")), h("button", { className: "wf-button wf-primary", disabled: !canOperate, onClick: () => setDialog("new"), title: !writable ? ui("操作员尚未启用任务提交") : !canOperate ? ui("同步完成前暂不可操作") : ui("创建待审批计划") }, ui("＋ 新建目标")))),
      h("div", { className: cx("wf-sync", readError && "wf-sync-error"), role: "status", "aria-live": "polite" },
        h("span", null, h("i", { "aria-hidden": true }), readError ? ui(updatedAt ? "同步失败，正在显示上次成功读取的状态。" : "同步失败，尚无可用状态。") + " " + ui(readError) : refreshing ? ui("正在同步状态…") : ui("状态已同步")),
        h("span", { className: "wf-sync-meta" }, updatedAt ? h("time", { dateTime: new Date(updatedAt).toISOString() }, ui("上次同步 {0}", new Intl.DateTimeFormat(locale === "en" ? "en" : "zh-CN", { hour: "2-digit", minute: "2-digit", second: "2-digit" }).format(updatedAt))) : ui("尚未同步"), readError && h("button", { type: "button", className: "wf-button", disabled: busy || refreshing, onClick: reload }, ui("重新读取")))),
      writable && meta?.model_connections_supported && h(ModelConnections, { execution: detail && Object.values(current(detail)).length === 4 && Object.values(current(detail)).every(task => task.status === "triage") ? selected : "", onConfigured: reload }),
      writable && readiness && h("details", { className: "wf-readiness", "aria-label": ui("执行准备") },
        h("summary", { className: "wf-section-heading" }, h("h2", null, ui("创建目标 → 人工审批 → 启动执行")), h(Badge, { tone: readiness.ready ? "green" : "amber" }, readiness.ready ? ui("已就绪") : ui("{0} 项待完成", readiness.checks.filter(check => !check.ready).length))),
        h("p", { className: "wf-muted" }, ui("可以先创建目标和审批；启动前需要完成以下准备。")),
        h("p", { className: "wf-muted" }, ui("项目：{0} · 看板：{1}", meta.project_name || "—", meta.board || "—")),
        h("ul", { className: "wf-readiness-list" }, readiness.checks.map(check => h("li", { key: check.code, className: check.ready ? "ready" : "pending" },
          h("span", { className: "wf-readiness-dot", "aria-hidden": true }), h("div", null, h("strong", null, ui(NAMES[check.code] || check.label)), h("span", null, ui(check.detail)), check.revision && h("code", null, check.revision), check.profile && h("code", null, check.profile), check.model && h("code", null, check.provider + " / " + check.model)), h("small", null, ui(check.ready ? "已就绪" : "未就绪"))))),
        h("div", { className: "wf-next-actions" }, h("a", { href: "/profiles", className: "wf-button" }, ui("配置角色和模型")), h("a", { href: "/system", className: "wf-button" }, ui("系统设置")))),
      h("div", { className: "wf-boundary" }, h("span", { className: "wf-status-dot" }), h("strong", null, ui("安全验证 · 部分通过")), h("span", null, ui("费用硬限额与真实执行验证尚未完成；保持人工审批。"))),
      h(Help, { writable }),
      error && h("div", { className: "wf-alert", role: "alert" }, h("span", null, ui(error)), h("button", { onClick: () => setError(""), "aria-label": ui("关闭错误") }, "×")),
      notice && h("div", { className: "wf-notice", role: "status" }, ui(notice), h("button", { onClick: () => setNotice(""), "aria-label": ui("关闭提示") }, "×")),
      h("section", { className: "wf-metrics", "aria-label": ui("工作流统计") }, [ui("执行目标"), ui("运行中的任务"), ui("需要关注")].map((label, i) => h("div", { className: "wf-metric", key: label }, h("span", null, label), h("strong", null, metrics[i]), h("small", null, [ui("当前项目的执行记录"), ui("由 Hermes 统一派发"), ui("阻塞或缺失的任务")][i])))),
      h("div", { className: "wf-workspace" },
        h("aside", { className: "wf-executions" }, h("div", { className: "wf-section-heading" }, h("h2", null, ui("执行目标")), h("span", null, rows?.length || 0)),
          h("input", { className: "wf-search", placeholder: ui("搜索研发目标…"), value: query, onChange: e => setQuery(e.target.value), "aria-label": ui("搜索研发目标") }),
          h("div", { className: "wf-filters" }, h("button", { className: !attention ? "active" : "", "aria-pressed": !attention, onClick: () => setAttention(false) }, ui("全部")), h("button", { className: attention ? "active" : "", "aria-pressed": attention, onClick: () => setAttention(true) }, ui("需要关注"))),
          rows === null ? (readError ? h(Empty, { title: ui("暂时无法读取执行列表") }, ui("保留目标选择，刷新后重新核验。")) : h("p", { className: "wf-loading" }, ui("正在读取执行记录…"))) : visible.length ? visible.map(row => h("button", { key: row.execution_id, className: cx("wf-execution", selected === row.execution_id && "selected"), "aria-pressed": selected === row.execution_id, onClick: () => { if (selected === row.execution_id) return; setError(""); setReadError(""); setSelected(row.execution_id); setDetail(null); setProof(null); setUpdatedAt(null); setTab("overview"); } },
            h("div", { className: "wf-execution-top" }, h(Badge, { tone: state(row) === "running" ? "green" : state(row) === "blocked" ? "amber" : "neutral" }, ui(STATES[state(row)])), h("span", null, formatDate(row.created_at))),
            h("h3", null, row.objective), h("div", { className: "wf-execution-meta" }, h("code", null, ui(short(row.source_revision))), h("span", null, ui("第 {0} 轮", (row.rounds.at(-1)?.number || 0) + 1))))) : h(Empty, { title: query || attention ? ui("没有匹配的目标") : ui("还没有执行记录") }, ui("已有终端执行记录会自动显示在这里。"))),
        h("section", { className: "wf-detail", "aria-label": ui("执行详情") }, !selected ? h(Empty, { title: ui("把下一步，放在清晰的计划里。") }, writable ? ui("创建研发目标后，在这里查看任务依赖与执行证据。") : ui("当前只读。启用受控提交后，可以建立新的待审批目标。")) : !detail ? (readError ? h(Empty, { title: ui("暂时无法读取执行详情") }, ui("保留目标选择，刷新后重新核验。")) : h("div", { className: "wf-loading" }, ui("正在核验执行状态与证据…"))) : h(R.Fragment, null,
          h("div", { className: "wf-detail-header" }, h("div", { className: "wf-eyebrow" }, (detail.board === "default" ? ui("默认看板") : detail.board) + ui(" / 执行编号 ") + detail.execution_id.slice(0, 8)), h("div", { className: "wf-title-line" }, h("h2", null, detail.objective), h(Badge, { tone: detail.acceptance.status === "ACCEPTED" ? "green" : "amber" }, ui(ACCEPT[detail.acceptance.status]))), h("p", null, ui("创建于 ") + formatDate(detail.created_at), " · ", detail.approved_write ? ui("已授权候选目录写入") : ui("尚未授权写入"))),
          h("nav", { className: "wf-tabs", "aria-label": ui("执行详情页签") }, [["overview", ui("执行概览")], ["evidence", ui("验收证据")], ["repairs", ui("整改记录")]].map(([key, label]) => h("button", { key, className: tab === key ? "active" : "", "aria-pressed": tab === key, onClick: () => { if (key === tab) return; setProof(null); setTab(key); } }, label))),
          tab === "overview" && h("div", { className: "wf-content" }, h("div", { className: "wf-section-heading" }, h("h3", null, ui("任务依赖")), h("span", null, ui("第 {0} 轮 · 4 个阶段", detail.rounds.at(-1).number + 1))),
            h("section", { className: "wf-next-step", "aria-label": ui("下一步") },
              h("div", null, h("span", { className: "wf-eyebrow" }, ui("下一步")), h("h3", null, ui(step.title)), h("p", null, ui(step.text)), h("small", null, ui(writable ? "建议基于当前状态，具体操作仍会重新核验。" : "当前只读，可查看进度和证据；执行操作需由操作员授权。"))),
              h("div", { className: "wf-next-actions" },
                step.focus && h("button", { className: "wf-button", onClick: () => focusStage(step.focus) }, ui("查看阻塞阶段")),
                step.evidence && h("button", { className: "wf-button", onClick: () => { setProof(null); setTab("evidence"); } }, ui("查看验收证据")),
                step.action && h("button", { className: "wf-button wf-primary", disabled: !!actionBlocked(step.action), title: actionBlocked(step.action) || ui(ACTIONS[step.action][1]), onClick: () => openAction(step.action) }, ui(ACTIONS[step.action][0])))),
            h("div", { className: "wf-progress" }, h("div", null, h("span", null, ui("{0} / 4 个阶段完成", completed)), h("small", null, ui("阶段完成不代表质量验收通过。"))), h("progress", { "aria-label": ui("阶段完成进度"), max: 4, value: completed })),
            h("div", { className: "wf-dag", "aria-label": ui("调查 → 开发 → 独立审查 → 最终汇总") }, ROLES.map((role, i) => h("button", { key: role, className: cx("wf-node", "wf-node-" + role, "wf-state-" + (tasks[role]?.status || "missing"), focus === role && "focused"), "aria-pressed": focus === role, onClick: () => setFocus(role) }, h("span", { className: "wf-avatar" }, [ui("调"), ui("开"), ui("审"), ui("汇")][i]), h("strong", null, ui(NAMES[role])), h("small", null, stageLabel(role))))),
            h("div", { className: "wf-task-info" }, h("div", null, h("span", { className: "wf-label" }, ui(NAMES[focus]) + ui("任务")), h("code", null, activeTask?.id || "—")), h("div", null, h("span", { className: "wf-label" }, ui("最近运行")), h("strong", null, activeTask?.outcome ? (ui(OUTCOMES[activeTask.outcome]) || ui("其他运行结果")) : ui("尚未运行"))), h("div", null, h("span", { className: "wf-label" }, ui("角色")), h("span", null, ui(NAMES[focus])), h("code", null, activeTask?.assignee || ui("尚未指派")))),
            h("div", { className: "wf-bottom-grid" }, h("div", { className: "wf-panel" }, h("h3", null, ui("交付检查")), h("p", { className: "wf-gate-reason" }, detail.acceptance.reason ? ui(message(detail.acceptance.reason)) : ui("当前版本、候选与验证证据已核对。")), h("dl", null, h("dt", null, ui("源版本")), h("dd", null, h("code", null, ui(short(detail.source_revision)))), h("dt", null, ui("候选版本")), h("dd", null, h("code", null, ui(short(detail.candidate_revision)))), h("dt", null, ui("实际模型接口费用")), h("dd", null, ui("未获取")))),
              h("div", { className: "wf-panel" }, h("div", { className: "wf-section-heading" }, h("h3", null, ui("人工操作")), !writable && h("span", null, ui("只读"))), h("div", { className: "wf-actions" }, Object.keys(ACTIONS).map(actionButton)), h("p", { className: "wf-footnote" }, ui("每次操作都由后端核验条件，任务完成不等于交付验收。"))))),
          tab === "evidence" && h("div", { className: "wf-content" }, h("h3", null, ui("独立验证记录")), h("p", { className: "wf-muted" }, ui("由操作员运行预设验收命令后生成，记录与当前候选绑定。")), !proof ? h("p", null, ui(readError ? "证据读取未完成，请刷新后重试。" : "正在读取证据…")) : proof.map((item, index) => h("article", { className: "wf-proof", key: index }, h("div", { className: "wf-section-heading" }, h("h3", null, index === 0 ? ui("开发结果验证") : ui("审查副本验证")), h(Badge, { tone: item.available && item.receipt.status === "PASS" && item.log_matches ? "green" : "neutral" }, item.available ? (item.log_matches ? (item.receipt.status === "PASS" ? ui("通过") : ui("未通过")) : ui("日志不一致")) : ui("尚无证据"))), item.available && h(R.Fragment, null, h("p", null, ui("退出码 "), h("code", null, item.receipt.exit_code), ui(" · 日志校验 "), item.log_matches ? ui("一致") : ui("不一致")), h("pre", { className: "wf-command" }, item.receipt.command), h("details", null, h("summary", null, ui("查看验证日志（最近 16 千字节）")), h("pre", { className: "wf-log" }, item.log_tail))))), h("h3", null, ui("候选变更")), h("code", { className: "wf-digest" }, detail.candidate_digest || ui("候选尚未冻结")), h("ul", { className: "wf-files" }, detail.changed_files.map(file => h("li", { key: file }, h("code", null, file))))),
          tab === "repairs" && h("div", { className: "wf-content" }, h("h3", null, ui("整改与预算")), h("div", { className: "wf-budget" }, h("span", null, ui("整改上限 "), h("strong", null, detail.budget.max_rounds), ui(" 轮")), h("span", null, ui("执行时间 "), h("strong", null, Math.round(detail.budget.max_seconds / 60)), ui(" 分钟")), h("span", null, ui("任务尝试 "), h("strong", null, detail.budget.max_runs), ui(" 次"))), detail.failures.length ? detail.failures.map((failure, i) => h("article", { className: "wf-failure", key: i }, h(Badge, { tone: "amber" }, ui(KINDS[failure.kind]) || ui("其他问题")), h("h4", null, failure.reason), h("small", null, formatDate(failure.at)))) : h(Empty, { title: ui("暂无整改记录") }, ui("独立审查未通过时，由操作员分类处理。重复失败与预算超限会转交人工。")))
        ))),
      h("footer", { className: "wf-footer" }, h("span", null, ui("Hermes 工作流")), h("span", null, ui("复用原生任务看板 · 默认人工受控 · 不自动提交或部署"))),
      dialog && h("div", { className: "wf-modal-backdrop", onClick: event => { if (event.target === event.currentTarget && !busy) setDialog(null); } }, h("form", { className: "wf-modal", role: "dialog", "aria-modal": true, "aria-label": dialog === "new" ? ui("新建研发目标") : ui(ACTIONS[dialog][0]), onSubmit: execute },
        h("h2", null, dialog === "new" ? ui("新建研发目标") : ui(ACTIONS[dialog][0])), dialog !== "new" && h("div", { className: "wf-confirm-target" }, h("strong", null, dialogTarget.objective), h("small", null, ui("源版本 {0} · 第 {1} 轮", short(dialogTarget.revision), dialogTarget.round_number + 1))), dialog === "new" ? h(R.Fragment, null, h("label", null, ui("研发目标"), h("textarea", { required: true, maxLength: 4000, rows: 4, value: objective, onChange: e => setObjective(e.target.value), placeholder: ui("描述目标、范围与可验证的验收标准…") })), h("label", null, ui("执行实例名（可选）"), h("input", { maxLength: 128, value: instance, onChange: e => setInstance(e.target.value), placeholder: ui("留空可复用同一版本的已有执行") })), h("p", { className: "wf-muted" }, ui("只创建待审批任务，不会立即派发写入。"))) : h(R.Fragment, null, h("p", null, ui(ACTIONS[dialog][1])), h("code", { className: "wf-confirm-id" }, dialogExecution), dialog === "repair" && h(R.Fragment, null, h("label", null, ui("失败类型"), h("select", { value: kind, onChange: e => setKind(e.target.value) }, [["implementation", ui("实现错误")], ["test", ui("测试错误")], ["environment", ui("环境错误（需人工）")], ["api_model", ui("接口或模型错误（需人工）")], ["permission", ui("权限错误（需人工）")], ["requirements", ui("需求不明确（需人工）")]].map(([value, label]) => h("option", { value, key: value }, label)))), h("label", null, ui("整改原因"), h("textarea", { required: true, maxLength: 2000, rows: 3, value: reason, onChange: e => setReason(e.target.value) }))), h("label", { className: "wf-check" }, h("input", { type: "checkbox", checked: ack, onChange: e => setAck(e.target.checked) }), ui("我已确认本次操作及其影响范围"))),
        error && h("p", { className: "wf-alert", role: "alert" }, ui(error)), h("div", { className: "wf-modal-actions" }, h("button", { type: "button", className: "wf-button", disabled: busy, onClick: () => setDialog(null) }, ui("取消")), h("button", { type: "submit", className: "wf-button wf-primary", disabled: !canOperate || (dialog !== "new" && (!ack || !!actionBlocked(dialog))) }, busy ? ui("正在处理…") : dialog === "new" ? ui("创建待审批目标") : ui("确认操作")))))
    );
  }
  window.__HERMES_PLUGINS__.register("workflow", App);
})();
