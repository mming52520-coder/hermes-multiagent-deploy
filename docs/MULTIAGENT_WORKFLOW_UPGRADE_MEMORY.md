# Multi-Agent Workflow 改造工作记忆

本文件是本次改造的唯一工作记忆。状态按证据更新；`NOT_TESTED` 表示未执行，`NOT_VERIFIED` 表示证据不足。

## 2026-10-29：只读审计基线

- 仓库：`/workspace/hermes-multiagent-deploy`，分支 `work`，HEAD `01a40f840671e122b045746873726426859af9b3`。
- 审计开始时没有 tracked/untracked 用户修改；已有 ignored `deploy.env` 和 Python 缓存予以保留，不读取密钥值。
- 部署基线：Hermes v0.18.2，`NousResearch/hermes-agent@aaf5691261f12601db845386d650dce1cdfa30f9`。本地依赖源码来自此前校验的固定提交归档，CLI 实测版本 v0.18.2；没有升级实际安装。
- 上游 HEAD 只读查询：`ef75bc708867e3884cb40a91363be6dc6fddc034`；审计了该提交的 `hermes_cli/kanban_db.py`、`kanban_decompose.py`、`pyproject.toml`，不采用其 API 或执行其代码。
- 原有调用链：root bootstrap → 非 root deploy → 配置/API 预检 → 在线安装 Hermes → 四 Profile → Docker → Board → Gateway/Timer → Researcher smoke。`submit-feature.sh` 创建 Research → Build → Review → Gate；`upgrade.sh` 执行未固定版本的 `hermes update`。
- 已阅读 README、SOURCE_BASELINE、Packy 文档、全部 Python/Shell 脚本、四 SOUL、中文使用手册。仓库没有现有测试套件/CI。

### 上游证据索引

以下路径均相对于固定版本源码；行号对应审计时的原始源码。

| 标记 | 证据 |
|---|---|
| U1 | `hermes_cli/kanban_db.py:2386` create_task，`:2813` link_tasks，`:3372` claim_task，`:6950` dispatch_once：原生任务、依赖、claim 和 Dispatcher。 |
| U2 | 同文件 `:3281` recompute_ready、`:7085` 无条件调用；`hermes_cli/kanban_decompose.py:297` 才读取 auto_promote_children。该配置不是人工审批屏障。 |
| U3 | 同文件 `:3978` complete_task：metadata 是自由字典；`:4150` 附近提交后触发生命周期 hooks。`tests/hermes_cli/test_kanban_lifecycle_hooks.py` 明确 hook 异常不阻止完成。 |
| U4 | 同文件 `:5434` 每个 task 建立独立 worktree，默认 `<project>/.worktrees/<task>`；`:7730` 注入 workspace/TERMINAL_CWD。`cli.py:592-666` 显式 profile cwd 又可能覆盖该值。Builder/Reviewer 分别创建 worktree 不等于审查相同候选代码。 |
| U5 | `tools/environments/docker.py:650-721` 原生 Docker mounts 与自动 cwd mount；`tools/terminal_tool.py:1300-1324` cwd remap。必须测试最终 mount/cwd，不能只检查配置中出现 :ro。 |
| U6 | `hermes_cli/kanban_db.py` release_stale_claims、detect_crashed_workers、enforce_max_runtime、_record_task_failure、dispatch lock/per-profile cap；复用恢复与调度，不新建服务。 |
| U7 | `hermes_cli/profiles.py:990` create_profile；`tools/memory_tool.py:1` 文件化记忆；`hermes_cli/cron.py:1` 原生 Cron；`gateway/platforms/webhook.py:1` HMAC/限流/去重；`hermes_cli/plugins.py:135` hooks。 |
| U8 | 旧版 `hermes_cli/goals.py:295` 的 Completion Contract 属于目标/模型判定，不是 task complete 的确定性代码验收。原生 review 列装载 sdlc-review，含 PR merge 行为，不直接启用。 |
| U9 | 新 HEAD `hermes_cli/kanban_db.py:640,1170,2640` 新增 task completion_contract/prepare_acceptance。与旧版不兼容；其约束能力细节 `NOT_VERIFIED`，本次不升级。 |

### 差距矩阵（改动前）

| 能力 | 已有实现/证据 | 缺失内容 | 复用方案 | 风险 | 优先级 |
|---|---|---|---|---|---|
| Chief of Staff | souls/orchestrator.md：拆解/路由/最终汇总 | 项目资源与业务授权契约 | 复用 Profile/Skills U7 | 不应增加执行权限 | P1 |
| Project Manager | submit-feature.sh 固定四卡 | 动态计划/阻塞跟踪 | 复用原生 Profile/依赖 U1/U7 | P0 前不启用 | P1 |
| Task Classification | 固定 feature 流程 | Playbook 选择 | Skills U7 | 误分类扩大写权限 | P1 |
| Dynamic Task Graph | 原生 link_tasks U1 | 有约束的规划与局部整改 | REUSED_EXISTING_IMPLEMENTATION：依赖、环检测 | 不另建 DAG DB | P1 |
| Parallel Workers | configure_profiles max_in_progress/per_profile；U6 | 写冲突/全局资源证明 | REUSED_EXISTING_IMPLEMENTATION：原生并发限额 | 同目录可写 | P0 |
| Context Handoff | submit-feature body/complete metadata；U3 | 角色化版本与证据字段 | 原生 run metadata/history | 自述不等于证据 | P0/P1 |
| Independent Review | souls/reviewer.md；configure_profiles.py | Reviewer RW；两 worktree 版本不同 U4 | 同一候选快照、RO mounts U5 | 自检/错版本 | P0 |
| Deterministic Gate | Orchestrator 提示词；U3/U8 | 无代码验收/独立接受状态 | 小型适配器 + 原生 runs；不用 post hook 假装强制阻断 | CLI/tool/API 可直接 done | P0 |
| Failure Recovery | souls/orchestrator.md 重建三卡；U6 | 全局整改轮数/时限/重复失败/费用 | 原生重试/恢复 + 提交边界预算 | 无限整改/未知费用 | P0 |
| Project Memory | Agent memory/session_search；U7 | 项目事实索引 | REUSED_EXISTING_IMPLEMENTATION：history + 文件 | 记忆过时 | P1 |
| Workflow Skills | toolsets skills U7 | 六种 Playbook | 原生 Skills | 不用巨型路由器 | P1 |
| Schedule / Event | 仅备份 Timer；U7 | 只读计划/认证来源策略 | REUSED_EXISTING_IMPLEMENTATION：Cron/Webhook | 默认不开放外部入口 | P2 |
| Observability | status.sh/原生 diagnostics/Dashboard | 执行 ID/接受状态/证据索引 | 扩展已有命令/原生 comments | done≠accepted | P0/P2 |
| Resource Budget | 单卡 max-runtime/max-retries、CPU/MEM | 全执行总预算、可信实际费用 | U6 + 显式未知成本处理 | 无原生跨请求硬费用限额证据 | P0/P2 |
| Human Approval | approvals smart；auto_promote=false | 可信写授权与接受授权 | 显式操作员入口；U2 不充当审批 | Worker 可自行完成 gate 卡 | P0 |
| Version Reproducibility | SOURCE_BASELINE 与 installed-commit.txt | 在线安装不锁 commit；upgrade 漂移 | 固定上游安装器的 --commit + 验证 | 同版本号不同源码 | P0 |

分类：U1–U8 属 A（部署基线已支持）；U9 属 B（只读确认新版本接口存在）；业务预算、独立接受状态属于 C（需要小型适配）；新 HEAD 的完整安全性质/实际模型费用属于 D（NOT_VERIFIED）。

## 实施计划与验收

- **P0 可信执行与安全验收**：隔离配置与实际 workspace 对应；独立接受状态校验源码/候选/测试/Review；原生幂等加 execution/revision；整改/时间/调用/费用边界；固定版本。必须通过离线正常/拒绝/恢复/重复派发测试。真实 Docker/模型未执行项单列，不伪称生产验证。
- **P1 自主规划与动态工作流**：仅在 P0 评审/测试达到可用安全边界后开展；Chief/PM、六类 Skills、DAG/handoff/项目事实索引。验收涵盖环/冲突/并行与旧流程兼容。
- **P2 长期自治**：仅在前两阶段稳定后开展；默认关闭的只读 Cron/认证事件/预算/可观测性。未测试外部入口不得启用。

设计决策：复用 Hermes Kanban/Profiles/Docker/恢复，不新增数据库、队列、Dispatcher，不修改上游。旧版不能统一拦截 done；接受状态必须独立校验，且明确覆盖边界。所有实际部署、模型请求、生产/硬件操作禁止；不执行 git commit/push/PR/reset/clean。

## 实施进展

只读审计完成；以下继续追加实施、测试证据、剩余阻断与阶段判定。

### 2026-10-29：P0 实施与复核

- 新增 `scripts/workflow_control.py`，作为操作员侧薄适配器；使用 v0.18.2 的原生 Profile clone、create_task、specify_triage_task、task runs、comments、Dispatcher/恢复，不写自建任务 DB，不修改上游。
- 原始项目/Kanban RO；每执行独立 candidate clone，Review 复制同一候选；不共享 linked-worktree 的可写 Git 元数据。Builder 在显式 start --approve-write 前也为 RO。各角色只写独立输出目录。
- 实际路径复核发现：原生 terminal_tool 会把 `/home/...` 判断为不可用 container cwd，即使已经 bind。修复为 host 路径 + `/candidate` 双 mount；scoped profile cwd=/candidate；原生配置转换与 DockerEnvironment 参数都已测试。
- scoped profile 明确使用 Docker，清除 extra_args/forward_env，禁网络、禁跨进程 container 复用、禁 orphan reaper；移除可能在同一候选里并发的 delegation/code_execution；Orchestrator 保留六类最小工具。原四 Provider/协议不变。
- 独立接受状态与 native done 分开。接受条件包含正常原生 completed runs、Builder 真实变更清单、source/candidate revision、candidate/review 内容 digest、两份可信操作员验证 receipt/日志 hash、Reviewer PASS。Worker 不挂载 operator 文件目录；普通 complete/伪造 verdict 不能创建有效接受证据。宿主同 UID 管理员仍是信任边界。
- 验证入口只执行操作员预先配置命令，使用原生 Docker CLI 新建自己的无网络/只读输入容器，私有 scratch、无 capabilities、UID 隔离；超时只清理自己的唯一容器名。此路径只用替身验证参数/退出状态，未执行真实 Docker。
- execution ID 纳入 objective/source HEAD/instance；保留 JOB_KEY 和原双参数 shell 调用；manifest 逐卡保留原生 IDs，覆盖提交中断、done/archived 重试。旧入口输出变为 JSON、默认 triage，这属于明确的安全语义变更。
- 整改只允许 implementation/test；environment/api_model/permission/requirements 转人工。复用成功 Research，只重建 Build/Review/Gate；同 Review findings 指纹不能通过改写 reason 隐藏；轮数/受控入口时间/run 预算有限。
- 固定官方安装器 commit/SHA256/--commit；先验证实际 CLI 来源，再做 Provider preflight。非 Git 归档安装逐文件验证，不以版本号或 marker 当作源码证明。未执行安装/升级；升级默认拒绝，显式授权只能恢复已审计基线。
- HERMES_HOME 可选配置路径对齐；保留用户已有 SOUL；没有对真实用户配置执行生成器。未改变实际 deploy.env、凭据或 Hermes 安装。

### 修改文件及交付物

完整逐文件原功能/改动/兼容性见 `docs/MULTIAGENT_WORKFLOW_P0.md` 第 3 节；实际文件为：

- 修改：10-deploy.sh、README.md、SOURCE_BASELINE.md、deploy.env.example、docs/Hermes多Agent_使用手册.md、scripts/configure_profiles.py、scripts/submit-feature.sh、scripts/upgrade.sh、souls/builder.md、souls/reviewer.md、souls/orchestrator.md。
- 新增：scripts/hermes_baseline.py、scripts/install-pinned-hermes.sh、scripts/workflow_control.py、tests/test_workflow.py、docs/MULTIAGENT_WORKFLOW_P0.md、docs/P0_TEST_RESULTS.txt、本工作记忆。

### 测试证据

- 最终 `/workspace/.venvs/hermes-agent/bin/python -m unittest discover -s tests -v`：**32 tests / 18.230s / OK**；无跳过/expected-failure。原始输出：`docs/P0_TEST_RESULTS.txt`。
- 覆盖正常 PASS、Builder 阻塞、Reviewer FAIL、缺手动验证 receipt/交接、测试非零、Commit 不匹配、内容变更、日志改动、超时、自有容器清理参数、原生 Worker 崩溃/失败上限、DB 重连恢复 claim、重复派发、原生 done 绕过拒绝、受控整改/上限/重复失败/人工类、权限配置、原生 Docker 参数、提交中断/归档幂等、旧 shell/JOB_KEY 接口、Provider/SOUL 回归、版本来源拒绝。
- 首次新增崩溃 fixture 的失败原因是注入时刻尚处上游 launch grace；调整 fixture 到契约规定时刻后针对性测试通过，未降低生产断言。
- 当前固定上游源归档逐文件校验：**PASS**（v0.18.2 / aaf5691261f12601db845386d650dce1cdfa30f9 / verified-archive）。
- 11 个 Shell bash -n 与 ShellCheck error 级别、5 个 Python AST、git diff --check：**PASS**。原有 SC1090 动态 source warning 没有被描述为代码错误，也未修改源文件来压制。
- 真实 Docker 权限、实际 Worker 镜像/模型 API、多 Agent 真实执行、真实 Gateway 服务重启、部署/升级/回滚：**NOT_TESTED**。临时 native DB 重连/函数恢复不能冒充这些服务级测试。

### 未解决问题与阶段判定

**Overall Result: PARTIAL_PASS。P0 离线实现可审查，整体 P0 安全验收未通过；P1/P2 BLOCKED。**

1. v0.18.2 的 task run 次数不是 LLM 调用次数；未找到可靠、统一、不可绕过的在途模型调用/费用硬限额契约。实际 API 费用始终为 unknown/null，设置有限费用上限时入口拒绝。此能力 **NOT_VERIFIED/未实现**。
2. 执行总时限/run 预算仅在操作员入口检查，单卡超时/恢复由原生执行；不能统一中止已经派发的整个执行，也不能约束绕过适配器的原生 task 创建。硬总时限 **未实现**。
3. 旧版普通 CLI/tool/Dashboard done 入口仍存在；独立接受状态解决交付判断，不能假称封锁所有原生执行路径。auto_promote_children 不能作为审批屏障；hook 是提交后观察，不能用其伪装同步强制门禁。
4. 真实物理容器隔离与服务/模型集成未执行。现有云机磁盘/systemd/凭据条件也不构成已部署证据；本任务明确禁止实际部署。

### 下一阶段目标

先确认可兼容旧版本的预算强制接口/可信计费来源，或在独立审计中提出有边界的上游迁移方案；明确在途总预算的强制语义，再在专用隔离环境验证真实 mount、镜像和 Gateway 恢复。保持旧版本可用，不自动升级。不越过这些 P0 阻断实现或默认启用 Chief/PM/Playbook/定时与事件自动写入。

最终代码审查：本次没有未授权 commit/push/PR、reset/clean、root 变更、真实部署/服务/生产数据/机器人/ROS/其他容器操作；没有新增数据库、队列、调度器或模型 Provider。已有用户文件保留。细节与未测试事项已同步交付报告，后续仍追加本文件。

## 2026-10-29：用户新增请求——将 CLI 封装为网页应用

用户确认选择「网页版应用，复用 Hermes Dashboard」。这是原工作流的界面封装，不是越过 P0 实施 Chief/PM、动态规划或长期自治。

- 只读检查固定版本原生 Dashboard 后，确认具备用户插件 manifest、React SDK/fetchJSON、后端 APIRouter 和现成 token/cookie 认证接口。直接复用，不新增服务器架构、任务 DB、消息队列或调度器。
- 新增 `plugins/workflow`：中文工作台、执行列表/搜索/阻塞筛选、四阶段依赖、候选与 Gate 状态、独立 receipt/log 查看、整改/预算，以及后端开关控制的固定人工操作。默认只读由后端执行。
- 后端使用原生 `_require_token` 与 SDK fetchJSON；操作要求同源、自定义操作头和明确确认，不能由 HTTP 指定命令、环境配置路径或其他项目。缺失 native DB 返回冲突而非新建空替代库。显示费用 unknown，保持 done/accepted 区别。
- 安装器只复制受管资产与现有控制模块，保护本地改动及 config.json，复用原生 enable 且 --no-allow-tool-override。真实本地安装已完成；只读、0 条真实执行、无 Gateway/Worker/模型启动。
- Native Dashboard 资源原本缺失；在独立源码副本按 package-lock 安装依赖并通过 tsc/Vite。一次工作目录错误导致 npm ci 在原上游目录创建 node_modules；已停止并把仅该次生成的两个目录移入独立副本。原上游 package/lock 保留，后续真实 HTTP 提交再次通过固定源码校验，原目录无 node_modules 残留。
- 原 P0 核心只增加 package/direct-script 两种明确导入方式，以便 API 与 CLI 共享同一实现；没有改 Provider、执行门禁或预算标准。
- 验证：完整回归 45 tests / 23.527s PASS；新增项目范围检查后，最终应用套件 14 tests / 4.586s PASS；安装器无工具覆盖授权的针对性复验 PASS。原 32 项 P0 测试仍通过。
- 真实 Chromium 通过 6 组检查：原生 SDK/登录集成、四阶段、证据日志、搜索/阻塞、移动无横向溢出、隔离表单提交/triage、XSS 转义、勾选确认/Esc 取消不派发。无浏览器页面错误。只使用临时项目和替身 Worker；测试服务已停止。
- 当前环境原生发现/加载插件、已认证 API 与静态资产均验证成功；新启动脚本 --help、语法/JS 检查通过。没有把本地地址发布为公网应用，没有升级 Hermes、触及生产或自动提交 Git。
- 操作说明/完整边界：`docs/WORKFLOW_APP.md`；最终应用日志：`docs/WORKFLOW_APP_TEST_RESULTS.txt`；隔离演示截图：`/workspace/artifacts/workflow-app/desktop.png`、`mobile.png`。

阶段结论：网页封装已完成并验证，默认只读。原 P0 总预算、真实隔离/模型/服务恢复的阻断未解除；P1/P2 继续保持 BLOCKED。应用只读开关只约束本插件，不改变原生 Dashboard 其他功能的权限。

## 2026-10-29：用户选择 Ubuntu/Debian 本机运行，已有 Hermes v0.22.5

用户明确要全部程序运行在自己电脑，已安装 Hermes v0.22.5 并验证版本/帮助；模型是否已配置、Docker daemon 是否可用尚未确认。保留现有版本，不重复安装或降级；本次没有连接用户电脑。程序本地运行不意味着 Packy/DeepSeek 在本地推理。

- 对官方稳定 v0.22.5 源码 bf0203a794a07aac3ff764972ab9087baa4e4f4e 做独立审计与验证。归档 SHA-256=0dc2cca54657d162845a77f634e107c61c3fb0bd6c8505212aa2e200591b7cc9，缓存于 /workspace/.cache/hermes-compat-v0.22.5。该版本 pyproject 版本为 0.0.0，版本由 install stamp 管理；不能放宽旧基线规则仅按版本字符串放行。
- 使用官方 PM、Python 3.14.9、独立 HERMES_HOME/HERMES_RUNTIME_DIR 与可写缓存完成临时运行环境。早期裸 uv 参数/锁文件版本不符和只读缓存错误均已诊断，未向原环境安装包。一次 exec-server 离线已恢复；可选 Chromium 下载遭 cdn.playwright.dev 策略拒绝，未绕过策略，不是网页应用阻断。实际浏览器使用已有系统 Chromium。
- 真实运行发现并修复三处界面兼容问题：configure_profiles.py 顶层 PyYAML 导入影响只读路由，改为仅配置读写时导入；workflow_control.status 依赖旧 connect_closing，改为直接 SQLite mode=ro 并关闭连接，不创建/迁移原生 DB；插件缺 __init__.py/register，补齐无模型工具/后台 hook 的注册入口并加入安装器资产。
- 新增 tests/check_workflow_readonly.py，临时真实原生 DB/manifest、原生 Dashboard enable helper/插件管理器与路由、认证、元信息/四阶段/详情/证据、POST 拒绝且没有新增卡片。最初试图在空 home 调用 CLI 被 PM 安装状态保护拒绝；改用原生 Dashboard helper，它仍通过 PM 准备所需环境，没有跳过保护。只验证默认 in_process 模式，不声称 host 或多 Profile 并行兼容。
- 使用该 v0.22.5 的 source_build 官方流程准备冻结 Node 依赖并构建原生 Dashboard：PASS。新增 tests/browser_workflow_readonly.cjs，真实新版前端/SDK + API + Chromium：PASS；四阶段、只读按钮、证据、移动布局、无页面错误。测试 fixture 全部已停止。
- 保留旧写入来源门禁；没有把 v0.22.5 的只读验证扩展为 submit/start/repair/accept/Worker 写入兼容承诺。此前 P0 的硬预算/真实模型、Docker 和服务恢复限制仍在，P1/P2 仍 BLOCKED。
- 原 v0.18.2 最终完整回归：47 tests / 20.604s / OK（33 P0 + 14 应用），新增状态查询不能重建缺失 DB 的验证；两版本只读检查均通过。证据已存 docs/LOCAL_HERMES_V0225_TEST_RESULTS.txt。git diff --check 通过。
- 更新云端已安装插件的受管代码，保留实际 config.json 和只读状态，没有启动 Gateway/Worker/模型或升级现有 Hermes。
- 交付 /workspace/artifacts/hermes-workflow-local-readonly-v0225.tar.gz（1,581,146 bytes，78 files），SHA-256 ea830e52e81d2b319b0d363397f09d10fc8f8a00af7c85b6a996433b45d12901。包含插件/安装器/控制模块、官方 v0.22.5 已构建 web_dist、许可证、README、测试和逐文件哈希；按固定白名单打包，不含 .git、deploy.env、凭据、用户状态或运行环境。解压后校验 77 项内容哈希并以标准库 Python 安装到临时 home，默认只读与前端均验证成功。README 使用 HERMES_WEB_DIST 指定随包前端，避免默认 --skip-build 在缺资源时恢复构建的行为。
- 本地步骤及边界见 docs/LOCAL_HERMES_V0225.md，已从 WORKFLOW_APP.md 链接。Git HEAD 仍为 01a40f840671e122b045746873726426859af9b3，代码没有 commit/push/PR，GitHub main 未更新。用户报告的 npm 安全告警具体影响范围未确认，未 audit fix --force 或改上游锁文件。

## 2026-10-29：中文网页、按钮和按键说明

用户要求网页及按键说明等改为中文。完成工作流与交付前端中文适配；没有连接或改动用户电脑，没有改变执行权限或阶段范围。

- 工作流页补齐中文阶段标记、运行结果、验收状态、失败分类、常见拒绝提示、可访问性名称及页脚；命令、版本、编号、路径、用户输入和原始证据日志保留原文。接口字段、任务与质量门禁不变。
- 页面新增可折叠「使用说明与按键」，解释按钮用途、灰色按钮、Tab/Shift+Tab、Enter/空格、Esc 和确认勾选；可在只读模式阅读。另交付 docs/WORKFLOW_APP_BUTTONS_ZH.md，安装器的说明、选项和应用输出补为中文。
- scripts/dashboard-zh.js 在中文包首次访问时选择原生简体中文，之后保留用户手动选择的语言；没有新增后台偏好或改变模型设置。
- 截图发现原生翻译有缺失，补齐文件、频道、事件回调、设备配对、系统管理、任务看板、成就等导航及共享指标/资源提示。localization/dashboard-zh.patch 仅应用于 /workspace/.cache/hermes-workflow-zh/dashboard-source 独立前端源码副本，原生后端、认证与依赖锁文件未修改；共享指标仍需用户选择，未自动启用。
- 新增 scripts/package-local-app.py，白名单打包中文静态前端、插件、安装器、必要控制模块、文档与翻译补丁，保留许可证，拒绝覆盖已有输出，生成逐文件哈希和包哈希；不包含凭据、deploy.env、Git 元数据或用户状态。
- 构建初次仅复用根 node_modules，类型检查发现 web 工作区嵌套依赖缺失；补齐冻结的 web/node_modules 后通过，未跳过检查或改依赖。导航浏览器检查还发现成就插件实际名为 hermes-achievements；修正映射后再次构建并复测通过。
- 最终验证：应用接口/安装保护 14 tests / 5.205s OK；原 v0.18.2 的 6 组真实浏览器回归通过（含中文运行结果与验证徽标、提交与取消门禁）；新前端 TypeScript 与原生 source_build 构建通过。
- 最终包解压后使用其自身安装器、插件、前端和测试，在真实 v0.22.5 默认 in_process 模式检查原生加载/认证/只读 API、中文导航与页头、语言默认与后续选择、中文拒绝原因、按钮与键盘说明、四阶段/证据、移动布局：PASS，无页面错误。83 个文件、82 项内容哈希校验通过，截图人工复核通过。详见 docs/WORKFLOW_APP_ZH_TEST_RESULTS.txt。
- 最终中文包：/workspace/artifacts/hermes-workflow-local-readonly-v0225-zh-CN-v3.tar.gz，SHA-256 c57d66e6657656517a044477638adbcf5a649ca255af7e96517acb365e7cfe2a。早期测试包保留，最终交付仅指向 v3。
- 最终截图：/workspace/artifacts/workflow-app-zh/release/desktop.png、help.png、mobile.png，均为清楚标注的离线演示数据。
- 云端原有受管插件已更新中文代码，config.json 保留；本机使用者需按 README 更新并重新启动自己的 Dashboard。所有本次测试网页进程已停止；测试服务受控停止的 130/143 退出码不作为功能失败。没有启动真实 Gateway/Worker/模型/Docker，没有 Git commit/push/PR。
- v0.22.5 的完整工作流写入仍未适配且保持关闭，旧版源码门禁保留；P0/P1/P2 原有结论与 npm 安全告警状态未改变。

## 2026-10-29：用户授权同步到其 GitHub 仓库

用户明确要求「先同步进我的仓库」，授权本次整理提交与推送。此前实现阶段不 commit/push 的要求已由此指令更新；仍不执行生产部署、服务变更、模型请求或主分支合并。

- 选用 codex/chinese-workflow-app 分支保存本次 P0 控制适配、中文网页、v0.22.5 只读接入、翻译补丁、测试和说明，保留 main 供审查。
- downloads 中随代码提供可直接下载的中文只读接入包和 SHA-256；文档与中文离线演示截图一起入库，README 增加下载/安装/按钮说明入口。仅 README 与清单从已验证的 v3 接入包变化，执行代码、界面和静态资源与浏览器验证版本一致。
- 同步前完整回归：47 tests / 25.389s / OK，见 docs/GITHUB_SYNC_VALIDATION.txt；JavaScript 语法、ShellCheck error 级别、git diff --check、包内 82 项哈希和外层 SHA-256 通过。凭据扫描最初误匹配供应商代码的 mask-image CSS 名称，补齐词边界后复核无密钥/令牌模式匹配。deploy.env 与本地状态继续忽略，包内无凭据或 Git 元数据。
- GitHub Git 读取正常，远端 main 仍为 01a40f840671e122b045746873726426859af9b3；GitHub API 的 GraphQL/REST 均被当前网络策略拒绝，api.github.com 不在允许列表中，因此不能把 PR 创建当成已完成。推送结果需以远端分支 SHA 核对，不能把 compare 链接描述为已创建 PR。
- P0 仍 PARTIAL_PASS，P1/P2 仍 BLOCKED；v0.22.5 完整写入保持未适配/关闭，不以入库代替部署和生产验证。

同步结果：实现提交 c7c11a610d75bd3c164aade2404ae20345f3d5f9 已推送到 origin/codex/chinese-workflow-app，git ls-remote 核对一致；main 保持 01a40f840671e122b045746873726426859af9b3。GitHub API 受当前网络策略限制，未创建 PR，创建入口为 https://github.com/mming52520-coder/hermes-multiagent-deploy/pull/new/codex/chinese-workflow-app 。仓库 downloads 目录中的新包 SHA-256 为 163a7aa73fb6965c51411121aced116e1730213997fa149a5ef1ac8ed67eeba5，仅 README 与清单相对于已浏览器验证的 v3 包更新。凭据和运行状态未上传；未执行部署或主分支合并。
