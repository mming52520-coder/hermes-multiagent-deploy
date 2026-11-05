# 角色工作方法与实际加载路径

本轮在已有总控直接发布、完整状态快照和本轮修改要求传递之上增加工作方法。没有另建编排 Agent、skill 路由服务或权限层。验收协议见 [ROLE_SKILLS_EVALUATION.md](ROLE_SKILLS_EVALUATION.md)；安装包包含复跑工具和合成用例。

## 有效机制

已核实的 Hermes 是 v0.22.5，源码 commit `bf0203a794a07aac3ff764972ab9087baa4e4f4e`。下列路径描述 workflow v2；历史 v1 仍走原有角色和流程。

| 执行入口 | 指令进入执行上下文的路径 | 边界 |
|---|---|---|
| 面向用户的架构师 | 网页/飞书 → `workflow_conversation.start` → 原 `PROMPT` + 受管理 `workflow-architecture/SKILL.md` 正文 → `AIAgent.run_conversation(system_message=...)` | 默认 profile 的模型；工具集为空，`skip_context_files=True`；不读取项目 SOUL 或任意全局 skill |
| 调查与编码 | `Workflow.populate_round` → 新任务 scoped profile 复制 SOUL 和对应 SKILL.md → Kanban `task.skills` → 原生 `build_kanban_policy` → `_run_task_turns` → `build_preloaded_skills_prompt` → 真实用户输入 | 角色确定后显式预载；不是模型语义分类；原生目录仍可经 `skills_list` / `skill_view` 发现和阅读 |
| 独立测试与审查 | 同一 scoped profile 创建流程 → 对应 SOUL → 原生 Agent 系统提示词 | 保留现有专业职责，只补本轮要求与历史证据的衔接 |
| 后台编排 | 原生 owner/dispatcher + `Workflow.advance` | 确定的依赖、预算、隔离快照、验证与验收逻辑；v2 不运行旧 `orchestrator` profile |

安装器把三份 skill 放入插件的 `operator/skills/`，复制 helper 至 `operator/workflow_skills.py`，并纳入 `.managed-files.json` 哈希检查。源码运行使用仓库 `skills/`。新 scoped profile 获得该任务自己的副本；批准、重试不重写已绑定任务的指导。任务绑定前初始化中断可重新复制，避免一个已存在但不完整的 profile 永久漏载。

架构师入口直接加载固定受管理文件，是工具为空时的适配，不宣称原生 skill 自动发现。Researcher/Builder 用原生显式预载；必需 skill 缺失时在调用模型前报错，不静默降级。默认 profile、已有任务、v1 和其他角色不新增 task.skills。

## 职责与 skill 映射

每个 skill 正文包含触发范围、不适用情境、必需输入、判断步骤、工具、交付物、完成条件及失败处理；下表用于定位，避免在多个文件复制同一方法。

| 角色 | 触发与不适用 | 输入和专业判断 | 工具、交付和完成 |
|---|---|---|---|
| 用户架构师 → [workflow-architecture](../skills/workflow-architecture/SKILL.md) | 工程需求、约束或方案取舍；进度查询/闲聊不展开设计 | 对话、current_request、decisions、真实状态快照；区分约束和假设，必要时比较方案，把需要代码证据的问题交调查 | 无工具；保持 reply/objective/publish/card_id 协议，目标能实施且验收可观察；材料不足明确未知 |
| Researcher → [workflow-investigation](../skills/workflow-investigation/SKILL.md) | v2 调查任务；不承担实现、独立验收或最终审查 | 完整任务、只读候选、实际父交接；查入口/调用链/配置/测试，复现故障，必要时检验竞争解释，外部行为核对版本一手来源 | 已启用的文件/搜索/终端/web；`/output/DESIGN.md` 提供事实、推断、未知、最小设计和验收矩阵；足够支持 Builder/Tester 则完成 |
| Builder → [workflow-implementation](../skills/workflow-implementation/SKILL.md) | 已授权 v2 编码或修复；不替代架构讨论和独立验收 | 任务、研究 DESIGN、修复轮 `/handoff/repair`；追踪受影响调用链，复用实现，修根因，按本轮要求检查实际 diff 和行为 | 既有文件/搜索/终端/web；授权候选内实现，`/output` 报告及原 kanban_complete 字段；记录实际验证和未验证项，不自报最终验收 |
| Tester → [既有 SOUL](../souls/tester.md) | 研究完成后独立设计验收；不等待并行 Builder 自证 | 当前要求 + 同一 DESIGN，原始只读快照；将每项要求落为行为断言，区分旧 PASS 覆盖范围 | `/output/tests` 和 TEST_DESIGN；可在未实现基线上预期失败，平台随后在冻结候选执行 |
| Reviewer → [既有 SOUL](../souls/reviewer.md) | Builder、Tester 完成且平台验证后 | 冻结候选、实际 diff、设计/测试/平台回执；核对本轮需求覆盖、证据身份及残余风险 | 只读审查，原 PASS/FAIL 和 findings；缺关键证据给具体缺口，完成不等于 ACCEPTED |

工具清单描述现有能力，不授予权限。Worker profile 仍过滤 delegation/code_execution，容器仍断网；只有授权 Builder 的候选可写，其他候选和 `/handoff` 只读，`/output` 可写。web 工具是否可用由独立的现有运行时策略控制，不能由 Docker 断网推断 web 被禁用。工具拒绝后可用已允许的同目的替代，不能修改审批或网络。

## 修改与可观察问题的对应

| 失败/缺口 | 证据和原因 | 本次最小对应修改 |
|---|---|---|
| 角色方法文件即使存在也未必进入模型 | 原任务 `skills` 为空；任务 profile 没有相应文件；总控无 skills 工具并跳过上下文文件 | 固定三项角色映射；worker 用原生预载，总控固定 system_message 适配；分别测发现和加载 |
| 调查员寻找自己的未来交接；Builder 连续猜测并行测试/未来平台文件 | 原始工具消息出现不存在路径及重复失败；阶段性输入/输出被混淆 | 在两个对应 skill 明确本阶段实际输入、输出、修复材料及核对一次后的处理 |
| 列目录的内联 Python 被单轮审批拒绝；测试使用错误 cwd | 原始 terminal 工具回执，随后简单搜索可继续 | 优先既有搜索/简单命令；要求候选 cwd；保留原审批，失败如实交接 |
| 旧绿灯掩盖本轮新增接口未实现 | 原需求、旧任务正文、diff 和测试回执一起证明历史任务漏传本轮要求 | 传递缺陷已由本次开始前的最新代码修复，不计作 skill 收益；只补角色如何核对当前要求与历史覆盖 |
| 新增 skill 初始化中断导致后续重试漏文件 | 独立验收者中断复制的复现；旧条件只看 profile 是否存在 | 任务尚未绑定时重做指导复制；绑定后保持版本；回归覆盖中断重试和批准时不覆盖 |

架构判断、竞争解释和根因修复是请求中的专业方法要求；现有少量轨迹不能证明每一项原来都做错。它们均按实际任务需要触发，不强制简单任务多方案、多假设或外部检索，也不将方法完整等同于模型效果已改善。

## 版本依据与验证边界

读取并比较了对应版本的 [Kanban worker](https://github.com/NousResearch/hermes-agent/blob/bf0203a794a07aac3ff764972ab9087baa4e4f4e/gateway/session_kanban.py)、[skill loader](https://github.com/NousResearch/hermes-agent/blob/bf0203a794a07aac3ff764972ab9087baa4e4f4e/agent/skill_commands.py)（[MIT](https://github.com/NousResearch/hermes-agent/blob/bf0203a794a07aac3ff764972ab9087baa4e4f4e/LICENSE)）与 [Agent Skills 格式](https://github.com/agentskills/agentskills/blob/main/docs/specification.mdx)（Apache-2.0）。复用原生加载契约，没有复制外部实现或新增依赖。未来 Hermes 版本应重新核对这条原生路径，不能从当前测试直接外推。

离线测试证明打包、发现、原生预载输入、异常路径和权限配置；在线回放才观察模型行为。已安装文件、已加载正文、遵循方法、最终交付四层应分开报告。生产 owner 的并发和失败恢复不在有限串行回放的证明范围。生产安装与服务重启须依据实际发布结果另行记录，不能拿源码测试代替已生效。
