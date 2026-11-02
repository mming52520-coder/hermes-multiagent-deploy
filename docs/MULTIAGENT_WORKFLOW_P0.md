# P0 交付报告与人工受控使用说明

```text
Overall Result: PARTIAL_PASS
Completed Phase: P0（离线实现与测试完成；整体安全验收未通过）
P1: BLOCKED
P2: BLOCKED
```

P0 的文件、原生 Kanban 适配和离线测试可以审查；不能据此宣称已部署、真实多 Agent 已端到端运行，或可以开启无人值守写入。**当前不启用 Chief、Project Manager、Playbook Router 或长期自治。** 完整的改造前 16 项差距矩阵、上游 A/B/C/D 分类和持续进展见 [唯一工作记忆](MULTIAGENT_WORKFLOW_UPGRADE_MEMORY.md)。

## 1. 实际结果与阻断

已经实现：原始项目和共享 Kanban 只读、执行/角色范围内的独立候选与 Review 副本、显式写授权、独立接受状态、可信操作员验证记录、受控整改、原生幂等与版本绑定、固定安装源码检查。

仍然阻断 P0 的完整验收：

1. v0.18.2 的 task run 不是模型调用计数，也没有经过本次确认的可信实际账单字段。配置有限 `WORKFLOW_MAX_COST_USD` 时适配器明确拒绝继续，费用显示 `null`，不能把未知当零。**全入口、在途模型调用的次数与费用硬限额：NOT_VERIFIED / 未实现。**
2. 总执行时间、task run 次数与整改次数在受控操作入口检查；原生 Dispatcher 继续负责单卡超时、进程恢复、并发和重试。适配层不能统一中止已经派发的全部工作，也不能约束绕过适配器直接创建的原生任务。**在途执行级总时限硬停止：未实现。** 没有新增 watchdog、调度服务或数据库来伪装解决。
3. 真实 Docker 文件权限、镜像依赖可用性、运行中的 Gateway 重启恢复、实际模型四角色协作：**NOT_TESTED**。测试使用真实旧版 Kanban 与隔离临时 clone，Worker/Docker 进程是替身；数据库重新连接不是一次真实 Gateway 服务重启。
4. 普通 CLI、工具和 Dashboard 仍可把卡标成 `done`。旧版没有统一同步 completion contract；完成后的 hooks 不能阻止已提交的转换。它们无法直接产生适配器的有效 `ACCEPTED`，但仍可能直接派发任务。原生 `auto_promote_children: false` **不是人工审批屏障**。

因此按任务要求在 P0 停止依赖它的 P1/P2。不是以关闭断言、绕过失败或升级上游来获得 PASS。

## 2. 差距修复矩阵

| 原始问题 | 对应文件 | 修改/复用方案 | 离线结果 | 剩余风险 |
|---|---|---|---|---|
| Reviewer/Builder 可写原项目，共享目录可互相修改 | configure_profiles.py、workflow_control.py | 原项目/Kanban RO；Builder 仅一个候选 RW；Reviewer 对冻结副本 RO；输出按执行/轮次/角色分开；复用原生 Docker | 配置、原生参数转换、重叠路径/共享 Git 元数据拒绝测试 PASS | 物理 Docker 权限 NOT_TESTED |
| 只改 :ro 仍会审查错误 worktree/错误 cwd | 同上 | 独立 clone 不共享 Git 元数据；同候选快照；host 路径与容器 /candidate 双映射；显式 cwd；关闭自动挂载和跨进程复用 | 原生 _get_env_config 与 DockerEnvironment 参数测试 PASS | 不执行真实容器；大型副本开销未评估 |
| 提示词 PASS/原生 done 被当接受 | workflow_control.py、三份 SOUL | 独立接受 JSON + 原生审计 comment；重新核对实际文件、SHA/digest、原生 run、两份操作员验证 receipt、日志 hash 和 Reviewer PASS | 正向/缺失/失败/错版本/日志改动/候选变化/绕过原生 done 测试 PASS | 信任操作员与主机文件权限；不抵御宿主同 UID 管理员 |
| 模型自述测试通过 | workflow_control.py | 操作员选择真实验收命令；在新的无网络、只读输入 Docker 中执行；私有 scratch；主机捕获 exit/log；Worker 不挂载 receipt 目录 | 成功/非零退出/超时/自己的容器清理参数测试 PASS | 实际命令与镜像 NOT_TESTED；命令覆盖充分性仍须人审 |
| 全流程测试缺失 | tests/test_workflow.py | 复用真实原生 create/claim/complete/dispatch/recovery；临时 clone；Worker 替身 | 最终 32/32 PASS | 不冒充真实模型/生产 Gateway 测试 |
| 无限整改/错误归类 | workflow_control.py | 六类错误；只允许 implementation/test 代码整改；同 Review findings 指纹、轮数/时限/run 限额；复用原生失败计数和恢复 | FAIL→局部整改、重复失败/上限/人工阻塞 PASS；已通过 Research 不重跑 | 全入口/在途总预算不是强制硬限额 |
| 目标哈希跨版本错误去重 | submit-feature.sh、workflow_control.py | SHA256(objective, source HEAD, instance)；保留 JOB_KEY；原生 idempotency；manifest 保留已完成/归档 task IDs，逐卡持久化 | 重试/归档/新实例/不同 SHA/中断恢复 PASS | 显式输入必须是 clean Git 源；不自动提交用户修改 |
| 在线安装/升级漂移 | 10-deploy.sh、hermes_baseline.py、install-pinned-hermes.sh、upgrade.sh、SOURCE_BASELINE.md | 固定 installer/hash/--commit；实际 CLI source clean HEAD 或逐文件归档校验；禁止未授权 unpinned update | 实际固定归档逐文件校验 PASS；错来源/错 hash 拒绝 PASS | 安装、升级、回滚执行 NOT_TESTED，均未触及实际安装 |
| 覆盖用户 SOUL | configure_profiles.py | 已存在 SOUL 保留；模型协议不变；可指定已有 HERMES_HOME | 自定义 SOUL/四 Provider 路由/文件 0600 回归 PASS | config.yaml/.env 仍是原部署生成器的管理文件；实际应用前需 staging diff |

`REUSED_EXISTING_IMPLEMENTATION`：Kanban 数据库、任务依赖/环检测、claim、Dispatcher 锁、重试、单卡超时、原生恢复、Profile clone、DockerEnvironment、History/Comment。没有实现另一套这些组件。

## 3. 修改文件清单

| 文件 | 原功能 | 本次改动与必要原因 | 兼容性 |
|---|---|---|---|
| scripts/configure_profiles.py | 生成四角色配置 | 精确 RO/RW mount helper、独立 clone 检查、输出范围、HERMES_HOME、保留已有 SOUL | 四 Provider/协议/基础角色不变；Builder 原项目直写被有意禁止 |
| scripts/workflow_control.py（新增） | 无 | 补旧版缺失的执行身份、授权、快照、验证 receipt、确定性接受与整改边界 | 复用原生模块；不改上游核心 |
| scripts/hermes_baseline.py（新增） | 无 | 防止同版本号但不同/脏源码被默认为兼容 | 仅支持已声明的固定基线 |
| scripts/install-pinned-hermes.sh（新增） | 原来远程浮动安装 | 校验固定安装器，传递上游原生 --commit | 仍采用官方安装器；没有执行 |
| scripts/submit-feature.sh | 四卡创建并立即 dispatch | 同参数转交原生 Hermes 解释器中的受控提交；保留 JOB_KEY、加入 revision/instance | 调用形式保留；输出为 JSON；默认 triage、取消自动派发是明确安全变更 |
| 10-deploy.sh | 安装/配置/启动 | 固定安装、先验证实际版本来源再 API 预检；commit 记录不从错误 checkout 覆盖；可沿用 HERMES_HOME | 原部署流程保留；不兼容版本提前拒绝；没有执行 |
| scripts/upgrade.sh | 未固定 hermes update | 默认拒绝；只有显式导出 HERMES_APPROVED_UPGRADE_COMMIT=固定 SHA 才允许恢复该已审计基线 | 不再支持未审计原地追 main；没有执行 |
| deploy.env.example | 部署变量 | 新增人工受控测试命令、预算、实例与来源/解释器选项 | 原变量/模型默认值保留；未改实际 deploy.env |
| souls/builder.md | Builder 合同 | 不自动 commit、结构化候选证据、范围限制 | 旧角色保留；commit 必须另有授权 |
| souls/reviewer.md | Reviewer 合同 | 同候选只读审查、版本/digest 绑定，PASS 非接受 | FAIL 通过原生 complete 交接仍保留 |
| souls/orchestrator.md | 编排与自然语言 Gate | 识别 scoped Profile、报告式最终卡、受控整改请求、done/accepted 区别 | 保留最小工具面和四步链 |
| tests/test_workflow.py（新增） | 无自动测试 | 32 项真实 native DB/配置与替身集成测试 | 无模型、无部署、无 Git commit |
| README.md | 历史部署入口 | 增加 P0 状态与行为变更入口 | 原手册保留，明确旧实例/新版区别 |
| docs/Hermes多Agent_使用手册.md | 日常实例操作 | 增加新版受控入口说明与链接 | 历史实例说明保留，不宣称已迁移 |
| SOURCE_BASELINE.md | 声明源码基线 | 增加实际 pin/hash/来源校验和迁移约束 | 支持版本未升级 |
| docs/MULTIAGENT_WORKFLOW_UPGRADE_MEMORY.md（新增） | 无 | 唯一持续工作记忆、16 项矩阵、证据/决策/结果/后续目标 | 后续继续追加同一文件 |
| docs/MULTIAGENT_WORKFLOW_P0.md（本文件） | 无 | 完整交付、用法、迁移与风险说明 | 文档与实际阶段一致 |
| docs/P0_TEST_RESULTS.txt（新增） | 无 | 保存最终测试原始输出 | 仅脱敏的 fixture 测试名称/结果 |

## 4. 测试报告

本次机器上实际执行：

```bash
cd /workspace/hermes-multiagent-deploy
/workspace/.venvs/hermes-agent/bin/python -m unittest discover -s tests -v
/workspace/.venvs/hermes-deploy/bin/shellcheck --severity=error 00-bootstrap-root.sh 10-deploy.sh scripts/*.sh
for script in 00-bootstrap-root.sh 10-deploy.sh scripts/*.sh; do bash -n "$script"; done
git diff --check
```

| 检查 | 范围 | 实际结果 |
|---|---|---|
| unittest 最终全套 | 32 个测试；隔离临时项目、真实 v0.18.2 模块、原生 DB；Worker/Docker 替身 | PASS：32 tests / 18.230s / OK；[原始输出](P0_TEST_RESULTS.txt) |
| 固定源码校验 | 当前依赖源码，对固定 70 MB 归档中每个常规文件比较 hash | PASS：v0.18.2 / aaf5691261f12601db845386d650dce1cdfa30f9 / verified-archive |
| 负向来源检查 | 不支持的 Git HEAD、错误归档、无来源安装 | PASS：明确拒绝 |
| Shell | 11 个脚本 bash -n、ShellCheck error 级别 | PASS；默认 warning 级别仍有原有动态 source 的 SC1090 |
| Python AST | 4 个脚本 + 1 个测试文件 | PASS |
| whitespace/diff | git diff --check | PASS |
| 真实 Worker/模型/挂载 | 未拉镜像、未起容器、未调用 API | NOT_TESTED |
| 真实 Gateway 中断重启/生产部署/升级/回滚 | 未启动/停止服务；只测试临时 DB 重连、原生 claim 与恢复函数 | NOT_TESTED |
| 全入口费用/模型调用硬限制 | 缺少旧版可依赖的强制执行契约 | NOT_VERIFIED；不是 PASS |

测试开发中崩溃 fixture 曾失败：注入的死亡 PID 位于上游启动宽限期，恢复函数按设计暂不检查。按真实上游契约把 fixture 的 started_at 移到宽限期后，针对性原生恢复测试通过；没有放宽生产断言。最终测试日志没有失败/跳过/expected-failure。

## 5. 新入口用法（人工受控；不是启用无人值守的建议）

前提：操作员已经准备好固定版本 Hermes、四个基础 Profile、存在的 Board、干净的目标 Git 项目，并在本机填好 deploy.env。真实运行仍需经过上面的未完成验证。测试与代码审查不需要真实模型密钥。

`WORKFLOW_TEST_COMMAND` 必须由操作员设定为该项目真实验收命令（例如已经存在的单元/集成测试命令），不能填 credentials、用 true 代替测试或从 Agent metadata 中取可执行命令。镜像必须预先可用，verification 使用 --pull=never、无网络和私有临时目录；缺依赖应停止并由操作员准备镜像，不能关闭验证。

已有提交形式：

```bash
bash scripts/submit-feature.sh ./deploy.env "明确的研发目标"
```

返回 execution_id、source_revision、四个 scoped task IDs。默认状态是 triage；没有新 Dispatcher 或后台进程。JOB_KEY / WORKFLOW_EXECUTION_ID 指定同版本的执行实例；同实例重试不重复建卡，不同 source HEAD 可以重跑同目标。项目有未提交修改时拒绝，保留原文件，不自动 commit/reset/clean。

后续命令都使用**同一个已验证 Hermes 安装的 Python**，下例 $hermes_python 由操作员指向该解释器：

```bash
# 仅展示接口；当前任务未对真实项目执行以下操作。
"$hermes_python" scripts/workflow_control.py --env ./deploy.env status <execution-id>
"$hermes_python" scripts/workflow_control.py --env ./deploy.env start <execution-id> --approve-write
# Builder 正常完成后，操作员冻结同一候选，才释放 Reviewer/Orchestrator。
"$hermes_python" scripts/workflow_control.py --env ./deploy.env prepare-review <execution-id>
# 各角色完成交接后，由操作员分别运行独立验证。
"$hermes_python" scripts/workflow_control.py --env ./deploy.env verify <execution-id> --role builder
"$hermes_python" scripts/workflow_control.py --env ./deploy.env verify <execution-id> --role reviewer
# 四卡正常完成、两份 receipt 合格、版本和内容匹配，才能接受。
"$hermes_python" scripts/workflow_control.py --env ./deploy.env accept <execution-id>
"$hermes_python" scripts/workflow_control.py --env ./deploy.env status <execution-id>
```

`status` 从原生 task/run 读取每轮状态，并重新计算接受条件。合格但没有操作员接受记录时是 READY_FOR_ACCEPTANCE；缺证据是 NOT_ACCEPTED，并给原因；只有有效已记录接受为 ACCEPTED。之后候选/Review/验证日志改变会使当前接受校验失败。历史已接受记录不会仅因为时间流逝被当成还在运行的超时任务。

候选不会自动合并、commit、push 或创建 PR。基础四角色保留；scoped 名称包含执行和轮次，复用原生 Profile clone。默认配置的 Builder 也不能再直写原始项目；旧的 worktree 写任务要在维护窗口迁移到受控入口，不要假称完全兼容了不安全的旧权限。

查看依赖图/执行状态：submit 返回的 four task IDs 与 parent 关系仍是标准 Research → Build → Review → Gate；可用现有 `hermes -p orchestrator kanban --board <board> show <task-id> --json`、list、diagnostics 和原 Dashboard。本次没有另造管理后台。

证据位于 `$HERMES_HOME/workflow/executions/<execution-id>/round-N/`：candidate_files/digest 在 execution.json；两份 verification JSON、日志；最终 acceptance.json；原生 run metadata 和 Gate 卡的 operator-quality-gate comment 可追溯。**不要把这个 operator 目录加入 Worker 的额外 mount，也不要把宿主机同 UID 管理员视为不可信 Worker。**

Reviewer FAIL 后：

```bash
"$hermes_python" scripts/workflow_control.py --env ./deploy.env repair <execution-id> \
  --kind implementation --reason "基于具体 Review findings 的窄范围整改"
```

只重建 Build/Review/Gate；复用原 Research，新轮次重新授权。implementation/test 以外的 environment/api_model/permission/requirements 转人工；同类同 findings 重复、超轮数/时限/run 预算均拒绝。旧卡的完成不等于接受，不能凭自然语言无限重建整改图。

Chief、Project Manager、六类 Playbook、动态并行计划、项目记忆自动整理、长期 Cron/事件入口：**未实施（P1/P2 BLOCKED）**，没有可使用的命令。以后需先解决 P0 硬预算边界和真实隔离验证，再复用原生 Skills/Cron/HMAC Webhook；不开放网络端口，不创建定时任务。

## 6. 迁移、升级与回滚

- 不自动改变用户的实际 Hermes 安装、模型、密钥、服务或源码版本。本次只改部署包；安装/升级脚本没有执行。
- 升级到另一上游版本前，应单独审计 task schema、Profile config bridge、Docker mount/cwd、Completion Contract 的 CLI/tool/Dashboard 完成路径、恢复语义和 Provider 协议；先在隔离环境通过这些测试，才修改 pin/hash/契约。保留旧版本安装与测试结果。
- 原 backup.sh 会停 Gateway，并排除实际 Hermes 源码/venvs/bin；**它单独不足以回滚运行时版本**。真实维护窗口内应另保留可验证的源码、依赖环境、Profile/Board 数据快照与权限。此处仅说明要求，没有运行备份/恢复脚本。
- upgrade.sh 默认在任何备份/服务操作前拒绝。导出 HERMES_APPROVED_UPGRADE_COMMIT=当前固定 SHA 仅授权恢复已审计基线，不代表支持追踪 main 或自动升级新版本；脚本仍有服务副作用，需另有明确维护授权。新版本必须在单独改造任务中提供迁移方案。
- 回滚时由操作员在维护窗口切回已验证的旧源码/依赖与对应配置/状态快照，再执行只读版本检查和隔离 smoke。不要在本次工作区自动 reset/clean/commit，也不要直接调用 restore-state.sh。

## 7. 最终审查记录

未修改上游源码、模型 Provider/API 协议、Kanban 数据库实现或 Gateway；未引入新依赖框架/数据库/队列/服务。未执行 git commit/push/PR、root 系统变更、部署/升级/恢复、生产数据库/机器人/ROS 操作；未运行真实 Worker 或影响其他 Docker 容器。实际 deploy.env 与用户配置保留。

代码差异、权限/接受边界、接口变化、测试状态与文档已核对。P0 剩余阻断明确记录；下一步是针对**可信预算强制接口和真实隔离验证**的兼容性设计，而不是直接开展 P1/P2 或启用自动写入。

## 8. 2026-10-30：执行恢复与隔离边界修复

基线为 `codex/chinese-workflow-app@599f3f4c587188a4c06e934529450e90de2f2e93`。GitHub API 与 Git refs 确认该最新分支存在；查询时唯一 PR 是已合并的 #1，新分支尚未创建 PR。本轮使用独立检出，原本地 main 工作区和配置保留。前文的测试数字属于历史记录。

```text
Overall Result: PARTIAL_PASS
Completed Phase: P0 执行恢复与隔离修复（离线验证通过）
P0 overall: PARTIAL_PASS，完整安全验收仍未通过
P1 / P2: BLOCKED
```

### 本轮差距修复矩阵

| 原始问题 | 修复与复用 | 本轮证据 | 剩余风险 |
|---|---|---|---|
| start 部分放行后中断，已有 Researcher 运行时无法重试 | 已有授权仅补放行剩余 triage 卡，不重写运行中 Profile；复用原生幂等转换 | 部分启动中断/实时运行状态测试 | 不改变原生 Dispatcher |
| 审查已准备后仍可 start 重写权限 | 拒绝重新打开该轮，须使用受控 repair | CLI 与已认证 HTTP action 拒绝测试 | 真实物理容器隔离 NOT_TESTED |
| prepare-review 放行 Reviewer 后中断无法重试 | 核对已记录的版本/内容，只补放行 Gate，不替换已发布副本 | 中断释放、同快照重试、改动后拒绝测试 | 逻辑快照不是 OS 层不可变文件系统 |
| 候选在复制期间变化仍放行 | 复制前后核对 candidate/review 的 HEAD 与文件内容；变化时保持 triage | 复制竞态故障注入 | 后续变化由原有接受校验拒绝 |
| repair 新轮保存后中断，旧授权仍为 true | 保存新轮前撤销授权；重试复用既有 failure、轮次和原生卡片 | 整轮/部分建卡中断、重复 repair、第二轮成功 ACCEPTED；Researcher 仅一次 run | 全入口、在途总预算仍未实现 |
| RW output 可嵌套覆盖 RO candidate；candidate 可位于共享 Kanban | 拒绝双向重叠；项目/输出不能暴露 operator 记录目录 | 挂载策略及 operator 路径回归 | Docker 参数测试不冒充物理挂载验证 |
| 缺日志/缺卡导致 status 抛异常 | 缺日志为 NOT_ACCEPTED；缺卡显示 missing；HTTP 详情正常返回失效状态 | CLI/HTTP 缺日志与原生缺卡测试 | 损坏 DB 不自动重建 |
| 新目录检查可能破坏最小只读配置 | 只读模式仍只需 PROJECT_DIR、BOARD_SLUG，不强制 OUTPUT_DIR | 最小配置测试及两版原生只读检查 | v0.22.5 写入未开放 |

`REUSED_EXISTING_IMPLEMENTATION`：Kanban 依赖、triage 转换、幂等 ID、运行历史、Dispatcher、恢复与 Profile clone。未新增数据库、队列、常驻进程或公共 CLI。

### 修改文件清单

| 文件 | 原有功能 | 本次修改与必要性 | 兼容性 |
|---|---|---|---|
| `scripts/configure_profiles.py` | Worker 挂载生成 | 补 candidate/output/Kanban 重叠检查，封闭实际 RW/RO 越界路径 | 合法分离目录、Provider、配置字段不变 |
| `scripts/workflow_control.py` | 四阶段控制与验收 | 授权生命周期、中断恢复、快照核对、缺证据状态 | 现有命令/参数及 manifest 结构保留 |
| `tests/test_workflow.py` | 原生 DB 与替身集成 | 新增 14 项恢复、授权、快照、隔离与缺记录回归 | 临时 clone/DB，Worker/Docker 替身 |
| `tests/test_workflow_app.py` | 已认证插件 API | 新增 2 项 HTTP 授权/缺日志回归 | 路由、接口字段、前端资产不变 |
| `README.md` | 项目入口 | 标明源码状态与旧下载包边界 | 历史手册及包保留 |
| 本报告、唯一工作记忆、`P0_TEST_RESULTS.txt` | 交付与证据 | 追加本轮结果和阻断 | 不另建工作记忆，保留历史 |

### 测试报告

使用工作区内独立 Python 环境和固定官方源码，未借用实际安装运行旧版测试。以下命令在仓库根目录执行；变量由操作员指向隔离测试目录：

```bash
PYTHONPATH="$HERMES_SOURCE" HERMES_HOME="$TEST_HOME" \
HERMES_BASELINE_ARCHIVE="$BASELINE_ARCHIVE" \
"$TEST_PYTHON" -m unittest discover -s tests -v

# 分别指定 aaf5691 与 bf0203a 源码；脚本自行创建临时 home/DB。
PYTHONPATH="$HERMES_SOURCE" "$TEST_PYTHON" tests/check_workflow_readonly.py
```

| 检查 | 实际结果 |
|---|---|
| 完整 unittest：47 项原有 + 16 项新增 | **PASS：63 tests / 15.189s / OK**，无跳过 |
| v0.18.2 归档 SHA-256 与逐文件来源验证 | PASS：aaf5691261f12601db845386d650dce1cdfa30f9，verified-archive |
| 已审计 v0.22.5 归档 SHA-256 | PASS：bf0203a794a07aac3ff764972ab9087baa4e4f4e；0dc2cca54657d162845a77f634e107c61c3fb0bd6c8505212aa2e200591b7cc9 |
| 两版原生插件/路由/认证/四阶段/证据/只读拒绝 | PASS，default in-process 模式；不代表写入兼容 |
| 12 个 Shell bash -n、ShellCheck error 级别、12 个 Python AST、工作流 JS 语法、git diff --check | PASS |
| 本轮浏览器/前端重建 | NOT_TESTED：前端未改，HTTP 控制层已回归；不将历史截图当本轮证据 |
| 真实 Docker、模型、Gateway 服务恢复、部署/升级/回滚 | NOT_TESTED：当前环境无 Docker 命令，未操作实际安装或服务 |

测试环境首次因 venv/依赖不齐未能运行；改用工作区内 uv 环境补齐后通过。未修改系统 Python 或安装 root 包。测试依赖有 Starlette/httpx 弃用提示；新版原生检查对测试 SQLite 3.45.1 显示 WAL 风险并选择 DELETE journal，没有关闭该保护。

### 使用说明与下一阶段

命令仍见第 5 节。start、prepare-review 或 repair 中断后可以重试原命令；仅恢复相同执行/快照，不重复消费整改轮次或创建卡片。已准备审查的轮次不能重新 start；Reviewer FAIL 后使用既有 repair。源码安装器会复制本轮更新的控制模块；downloads 包仍是此前的中文只读版本，本轮未重新打包。

进一步核对已审计 v0.22.5 源码后，P0 阻断仍有具体依据：

- `hermes_cli/kanban_db_connect.py:788` 才提供 connect_closing，不能仅放宽版本号校验启用旧适配器写入。
- `kanban_pr_acceptance_store.py:prepare_acceptance` 对 local-only 返回 None；PR completion contract 不能直接替代本地候选验收。
- `plugins.py` 的 API/辅助调用 hooks 是 observer；`plugins_dispatch.py:60` 仅将 pre_tool_call timeout 作为 fail-closed。不能用可跳过的观察回调宣称已实现所有重试/辅助请求的硬费用上限。

这是源码事实；由此推断，单纯升级或添加 observer 不足以解除 P0。跨 Worker 总预算强制接口仍 NOT_VERIFIED。下一步需明确该接口与在途截止语义，制定版本迁移/回滚方案，再进行双版本写入及专用 Docker/Gateway 故障验证。保持旧 pin 和实际安装不变；P1/P2 没有可使用的新命令。本轮未 commit、push、创建/合并 PR 或执行部署。


## 9. 2026-10-30：经人工受控的 v0.22.5 写入接入

用户进一步明确要求创建研发目标、人工审批、启动多 Agent，更新了旧版只读交付范围。本轮工作流写入仅新增已审计 bf0203a 的精确来源门禁，旧部署/升级脚本继续锁定 v0.18.2；不是修改版本字符串或跳过源码校验。第 8 节的“新版写入未开放/未重新打包”属于当时记录，当前状态以本节和 LOCAL_HERMES_V0225.md 为准。

创建使用原生四张 triage 卡；审批独立保存版本/轮次授权，不释放卡片；启动再检查 Docker、角色和运行配置，调用原生 Gateway/dispatcher。UI 确认绑定所见目标和轮次，过期确认拒绝。Profile 选择器不能更换服务端绑定的 home/board。没有新增数据库、调度循环、Provider 或公共 CLI 参数。

原生 Dashboard 可在独立数据根中显式启用人工操作，并绑定已提交项目的干净副本。缺 Docker/角色凭据时能创建和审批，启动被拒绝；相关接口测试使用独立数据库和合成目标。

91 项检查通过：63 项旧版回归、10 项新版原生 DB/Profile/HTTP/派发测试、18 项组件测试；新版默认只读检查仍通过。真实浏览器检查目标创建、审批范围/未勾选禁用、启动依赖、双语和 1280px/390px 布局。派发测试的 Gateway/推理进程使用替身，不是实际模型运行。

Overall Result 仍 PARTIAL_PASS，P1/P2 未启用。实际模型/容器隔离、Gateway 服务恢复、费用/调用次数硬上限与在途总截止仍未完成。新的手动执行入口不改变这些结论。接入包已更新，安装仍默认只读；详见 WORKFLOW_APP_TEST_RESULTS.txt 与 LOCAL_HERMES_V0225.md。
