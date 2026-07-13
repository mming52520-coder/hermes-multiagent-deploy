# Hermes 多 Agent 使用手册

> 版本：v1.0
>
> 本文说明已部署 Hermes 多 Agent 系统的日常使用、任务编排、运维检查与安全边界。首次安装请先阅读仓库根目录的[一键部署手册](../README.md)。

> [!IMPORTANT]
> 下表记录的是当前已验证部署实例的基线，并非所有环境的通用默认值。版本、Board、容器名或项目路径变化后，应同步更新本文。

## 适用环境

| 项目 | 当前基线 |
| --- | --- |
| 操作系统 | Ubuntu 20.04 |
| Hermes Agent | v0.18.2 |
| 运行用户 | `hermes` |
| Kanban Board | `my-project` |
| Profile | `orchestrator`、`researcher`、`builder`、`reviewer` |
| 当前外部入口 | CLI |
| Gateway | systemd 用户服务运行 |
| Worker | Docker 隔离运行 |
| Researcher | 项目目录只读 |
| Orchestrator | 不具备 Terminal、File、Code Execution 等实施权限 |

## 1. 系统定位

当前 Hermes 不是单一的代码助手，而是一套多 Agent 工作流系统：

```text
用户
  ↓
Orchestrator
  ├── 拆解任务
  ├── 分配任务
  ├── 管理依赖
  └── 最终验收
  ↓
Researcher → Builder → Reviewer
  ↓
Kanban
```

各 Profile 的职责如下：

| Profile | 核心职责 | 禁止事项 |
| --- | --- | --- |
| Orchestrator | 任务拆解、分配、依赖管理、验收 | 不直接执行命令或修改项目 |
| Researcher | 阅读代码、调查问题、提供证据 | 不修改项目文件 |
| Builder | 实施修改、运行测试、生成产物 | 不自行批准自己的结果 |
| Reviewer | 独立审查代码、报告和测试结果 | 不依赖 Builder 自述作为唯一证据 |

## 2. 启动 Hermes

### 2.1 推荐启动方式

在普通用户 `a` 的终端执行：

```bash
sudo -iu hermes
```

进入 `hermes` 用户环境后：

```bash
hermes -p orchestrator chat
```

也可以简写为：

```bash
hermes -p orchestrator
```

### 2.2 一条命令直接启动

```bash
sudo -iu hermes hermes -p orchestrator chat
```

如果出现 `hermes: command not found`：

```bash
sudo -iu hermes bash -lc '
export PATH="$HOME/.local/bin:$HOME/.hermes/bin:$PATH"
hermes -p orchestrator chat
'
```

### 2.3 退出 Hermes

在对话中输入：

```text
/quit
```

或者按 `Ctrl+C`。

## 3. Hermes 的三种使用模式

### 3.1 持续交互模式

适合：

- 澄清需求；
- 设计任务链；
- 查询工作进度；
- 审核结果；
- 决定是否进入下一阶段。

启动：

```bash
hermes -p orchestrator chat
```

### 3.2 单次查询模式

执行一次任务后退出：

```bash
hermes -p orchestrator chat \
  -q "检查当前 Kanban 状态，并总结未完成任务"
```

该模式会显示较完整的执行过程。

### 3.3 纯文本单次模式

只输出最终答案：

```bash
hermes -p orchestrator -z \
  "总结当前任务状态，只输出三行"
```

适合：

- Shell 脚本；
- 自动化检查；
- 获取机器可解析的简洁结果；
- 不需要查看工具执行过程的任务。

## 4. 正确的提问结构

不要只输入：

```text
检查一下项目。
```

推荐采用以下结构：

```text
目标：
需要解决的核心问题。

范围：
需要检查或修改哪些模块。

排除范围：
明确哪些模块不得触碰。

任务链：
- Researcher 调查；
- Builder 实施；
- Reviewer 独立核验；
- Orchestrator 最终验收。

约束：
- 不得修改配置；
- 不得重启服务；
- 不得输出密钥；
- 不得触碰无关模块。

验收标准：
明确文件、测试、日志和最终结果要求。

交付物：
报告、代码、测试结果、任务 ID、残余风险。
```

## 5. 推荐提示词模板

### 5.1 只读架构审查

```text
为当前项目建立一次只读架构审查工作流。

目标：
确认项目是否真正实现感知、决策、执行三层分离。

范围：
- ROS 节点和功能包
- Topic、Service 和 Action 接口
- 控制权仲裁
- 状态机
- 安全与故障恢复
- 自动回充
- 测试和可观测性

任务链：
1. researcher 阅读源码并提供文件路径、类和函数证据；
2. builder 将结果整理成正式报告，只写入输出目录；
3. reviewer 独立抽查至少 5 个关键结论；
4. reviewer PASS 后由 orchestrator 完成最终 Gate。

约束：
- 不修改项目源码；
- 不创建 Git commit；
- 区分已验证事实、合理推断和未知项；
- 最终返回任务 ID、报告路径和残余风险。
```

### 5.2 小范围代码修改

```text
为以下问题建立受控代码修改工作流：

问题：
磁导航请求消息缺少运动方向、目标速度和转向符号，导致磁导航管理器无法区分不同运行阶段。

要求：
1. researcher 定位接口、调用链和影响范围；
2. builder 仅修改必要消息、节点和测试；
3. builder 运行构建和相关测试；
4. reviewer 独立检查 diff、接口兼容性和测试证据；
5. reviewer PASS 后 orchestrator 才能接受。

限制：
- 不修改无关功能包；
- 不改变现有默认行为；
- 不直接 push；
- 不修改硬件端口和部署配置；
- 失败时不得扩大修改范围。

Builder 完成时必须返回：
- changed_files
- root_cause
- implementation
- verification
- residual_risk

Reviewer 完成时必须返回：
- verdict
- checked_files
- verified_claims
- rejected_claims
- test_result
- residual_risk
```

### 5.3 故障调查

```text
调查当前故障，但暂时不要修改代码。

目标：
确定故障发生在配置、通信、状态机、控制仲裁还是执行层。

要求：
- researcher 收集日志、配置和代码证据；
- 输出最可能的三个根因；
- 给出每个根因的验证命令；
- 不重启系统；
- 不修改参数；
- 不操作硬件；
- 不把相关性描述为因果关系。

完成调查后，先向我提交诊断结论和修改建议，不创建 Builder 任务。
```

## 6. Kanban 基本操作

### 6.1 查看任务列表

```bash
sudo -iu hermes hermes -p orchestrator \
  kanban --board my-project list
```

### 6.2 持续观察任务

```bash
sudo -iu hermes hermes -p orchestrator \
  kanban --board my-project watch
```

按 `Ctrl+C` 退出监控，任务不会因此停止。

### 6.3 查看指定任务

```bash
sudo -iu hermes hermes -p orchestrator \
  kanban --board my-project show <任务ID>
```

查看 JSON：

```bash
sudo -iu hermes hermes -p orchestrator \
  kanban --board my-project show <任务ID> --json
```

### 6.4 Kanban 诊断

```bash
sudo -iu hermes hermes -p orchestrator \
  kanban --board my-project diagnostics
```

建议在以下情况运行：

- 任务长期不启动；
- 父任务完成后子任务没有继续；
- Worker 数量异常；
- 任务状态与实际结果不一致；
- Dispatcher 没有派发任务。

## 7. 使用标准任务提交脚本

对于真实代码任务，优先使用部署包中的标准入口：

```bash
sudo -iu hermes bash -lc '
cd /opt/hermes-multiagent-deploy
./scripts/submit-feature.sh ./deploy.env \
  "修复双磁导航请求缺少方向、速度和转向符号的问题，并补充测试"
'
```

该入口会自动建立：

```text
Research
  ↓
Build
  ↓
Review
  ↓
Gate
```

相比仅在聊天窗口中说“帮我修改代码”，标准脚本更容易保证：

- Assignee 正确；
- 依赖关系正确；
- 最大运行时间明确；
- 重试次数受控；
- Reviewer 不被绕过；
- Orchestrator 不直接实施。

## 8. 推荐的多 Agent 工作流

### 8.1 只读调查工作流

```text
Researcher
  ↓
Builder 生成报告
  ↓
Reviewer 独立核验
  ↓
Orchestrator Gate
```

适用于：

- 架构审查；
- 故障根因分析；
- 配置审查；
- 代码质量审查；
- 安全审查；
- 技术路线评估。

### 8.2 代码修改工作流

```text
Researcher 定位问题
  ↓
Builder 修改代码并测试
  ↓
Reviewer 查看 diff 并独立验证
  ↓
Orchestrator 接受或安排整改
```

适用于：

- 修复明确 Bug；
- 添加小功能；
- 修改接口；
- 增加单元测试；
- 局部重构。

### 8.3 大规模重构工作流

不要一次提交“重构整个机器人系统”。应拆成：

1. 现状审查；
2. 目标架构和接口设计；
3. 控制权仲裁层；
4. 感知层迁移；
5. 决策层迁移；
6. 执行层迁移；
7. 兼容性和回归测试；
8. 仿真和实车测试计划。

每个阶段单独进入 Review 和 Gate。

## 9. 任务拆分原则

一个合格的 Builder 任务应满足：

- 只解决一个核心问题；
- 修改范围明确；
- 输入和输出明确；
- 验收命令明确；
- 可以独立回滚；
- 可以由 Reviewer 独立验证；
- 通常在 30～60 分钟内能够完成。

不要把以下事项放入同一个任务：

- 架构重构；
- 新功能；
- 硬件接口变更；
- 参数调试；
- 自动回充；
- 急停逻辑；
- 上位机修改；
- 部署修改。

这些内容应拆成不同工作流。

## 10. 会话管理

### 10.1 继续最近会话

```bash
sudo -iu hermes hermes -p orchestrator --continue
```

### 10.2 按名称继续会话

```bash
sudo -iu hermes hermes -p orchestrator \
  --continue "双磁导航审查"
```

### 10.3 查看会话

```bash
sudo -iu hermes hermes -p orchestrator sessions
```

### 10.4 会话使用建议

不同主题应使用不同会话，例如：

- 双磁导航审查；
- 自动回充整改；
- 急停与复位逻辑；
- 三层架构重构；
- Hermes 运维。

不要把所有项目问题长期堆积在同一会话中，否则容易出现：

- 上下文混杂；
- 旧约束影响新任务；
- 无关代码和报告进入提示词；
- Token 使用量上升；
- Agent 对当前目标判断错误。

## 11. Gateway 管理

当前 Gateway 已作为后台服务运行，正常情况下不需要每次启动。

### 11.1 查看状态

```bash
sudo -iu hermes bash -lc '
hermes -p orchestrator gateway status
'
```

### 11.2 启动 Gateway

```bash
sudo -iu hermes bash -lc '
hermes -p orchestrator gateway start
'
```

### 11.3 重启 Gateway

```bash
sudo -iu hermes bash -lc '
hermes -p orchestrator gateway restart
'
```

只有在以下情况才重启：

- Profile 配置已经正式变更；
- Gateway 服务异常退出；
- 外部消息平台配置发生变更；
- 已确认重启不会中断正在执行的关键任务。

### 11.4 查看 Gateway 日志

```bash
sudo -iu hermes journalctl --user \
  -u hermes-gateway-orchestrator.service \
  -f
```

当前只启用了 CLI 入口，没有启用 Telegram、Webhook、API Server 等外部入口。

## 12. 系统状态检查

### 12.1 部署包状态脚本

```bash
sudo -iu hermes bash -lc '
cd /opt/hermes-multiagent-deploy
./scripts/status.sh ./deploy.env
'
```

### 12.2 Hermes 诊断

```bash
sudo -iu hermes hermes -p orchestrator doctor
```

> [!IMPORTANT]
> Doctor 的 Tool Availability 不等于 Orchestrator 实际启用权限。Doctor 会显示宿主环境中可用的工具能力。

当前 Orchestrator 实际允许的工具集是：

- `kanban`
- `memory`
- `session_search`
- `todo`
- `clarify`
- `skills`

即使 Doctor 显示 Terminal 或 File Operations 可用，也不要据此修改配置。

### 12.3 查看版本

```bash
sudo -iu hermes hermes --version
```

## 13. Worker 和 Docker 检查

### 13.1 查看容器

```bash
docker ps -a \
  --format 'table {{.Names}}\t{{.Status}}\t{{.Image}}'
```

当前实例的正常状态应包括：

- Hermes Worker 容器运行；
- `exam-local-mysql` 为 `running/healthy`；
- `yanfaguanli-mysql-1` 保持 `exited`。

> [!NOTE]
> 上述两个 MySQL 容器名及期望状态属于当前部署实例。其他环境应先记录自己的业务容器基线，不要机械套用。

### 13.2 检查 Worker 镜像

```bash
docker image inspect \
  nikolaik/python-nodejs:python3.11-nodejs20 \
  --format 'ID={{.Id}} ARCH={{.Architecture}} OS={{.Os}}'
```

预期：

```text
ARCH=amd64
OS=linux
```

### 13.3 检查 Researcher 只读挂载

```bash
docker inspect \
  $(docker ps -q --filter "name=researcher" | head -n 1) \
  --format '{{range .Mounts}}{{println .Source .Destination .RW}}{{end}}'
```

项目挂载应显示：

```text
RW=false
```

## 14. 日志和故障排查顺序

遇到任务失败时，按以下顺序排查：

```text
任务状态
  ↓
任务详情和 metadata
  ↓
Kanban diagnostics
  ↓
Worker 容器状态
  ↓
Gateway 日志
  ↓
模型接口
  ↓
宿主网络和磁盘
```

不要一出现失败就：

- 重新部署；
- 删除容器；
- 清理 Docker；
- 修改 API Key；
- 重启 Docker；
- 放宽 Agent 权限。

### 14.1 Hermes 日志

```bash
sudo -iu hermes hermes -p orchestrator logs
```

### 14.2 Gateway 日志

```bash
sudo -iu hermes journalctl --user \
  -u hermes-gateway-orchestrator.service \
  -n 200 --no-pager
```

### 14.3 查看系统资源

```bash
df -h
free -h
docker system df
```

不要在没有确认影响范围时执行：

```bash
docker system prune
```

## 15. 常见故障

### 15.1 `hermes: command not found`

```bash
sudo -iu hermes bash -lc '
export PATH="$HOME/.local/bin:$HOME/.hermes/bin:$PATH"
command -v hermes
hermes --version
'
```

### 15.2 Gateway inactive

检查状态：

```bash
sudo -iu hermes hermes -p orchestrator gateway status
```

查看日志：

```bash
sudo -iu hermes journalctl --user \
  -u hermes-gateway-orchestrator.service \
  -n 200 --no-pager
```

确认原因后再启动：

```bash
sudo -iu hermes hermes -p orchestrator gateway start
```

### 15.3 任务长期 pending

依次执行：

```bash
sudo -iu hermes hermes -p orchestrator \
  kanban --board my-project diagnostics
sudo -iu hermes hermes -p orchestrator \
  kanban --board my-project list
docker ps -a
```

重点检查：

- 父任务是否完成；
- Assignee 是否存在；
- Worker 是否运行；
- Dispatcher 是否正常；
- 是否达到并发限制；
- 是否因为 Reviewer FAIL 被阻塞。

### 15.4 模型请求失败

先检查 Profile：

```bash
sudo -iu hermes hermes -p orchestrator doctor
```

然后检查：

- Endpoint 是否可访问；
- API Key 是否有效；
- 模型名称是否正确；
- 服务商是否限流；
- 网络代理是否只对当前用户生效；
- 请求格式是否与模型接口兼容。

不要在终端打印完整 API Key。

### 15.5 Doctor 显示 Terminal 和 File 可用

这不代表当前 Orchestrator 权限失效。当前已完成实际工具集审计，Orchestrator 的实际 CLI 工具集没有：

- `terminal`
- `process`
- `read_file`
- `write_file`
- `patch`
- `search_files`
- `execute_code`
- `delegate_task`
- `computer_use`

因此无需修改配置。

## 16. Token 和成本控制

### 16.1 查看 Prompt 体积

```bash
sudo -iu hermes hermes -p orchestrator prompt-size
```

### 16.2 查看活动与成本

```bash
sudo -iu hermes hermes -p orchestrator insights
```

### 16.3 降低成本的原则

- Orchestrator 只接收任务摘要，不读取完整仓库；
- Researcher 只提交必要证据；
- Builder 只读取父任务和目标文件；
- Reviewer 只检查关键 diff、测试和高风险路径；
- 报告保存为文件，不在任务评论中反复粘贴全文；
- 不让多个 Agent 重复扫描整个仓库；
- 一个任务只解决一个明确问题；
- 小问题不要建立过长的四层任务树。

## 17. 安全使用原则

### 17.1 不扩大 Orchestrator 权限

不要执行：

```bash
hermes -p orchestrator chat \
  --toolsets terminal,file,code_execution
```

Orchestrator 应保持编排和验收职责。需要执行命令或修改文件时，应创建 Builder 任务。

### 17.2 不显示敏感文件

不得直接输出：

- `deploy.env`
- Profile `.env`
- API Key
- Token
- 代理用户名和密码

只允许检查：

- 文件是否存在；
- 权限是否为 `0600`；
- 对应变量是否已配置。

### 17.3 不直接启用外部入口

当前 API Server、Webhook、Telegram、Cron 等外部入口未启用。启用前必须审查：

- 平台实际工具集；
- 身份认证；
- 网络监听地址；
- Prompt Injection 风险；
- 是否允许 Terminal/File；
- 是否会暴露 Dashboard；
- 日志中是否可能出现敏感信息。

### 17.4 不使用 `--yolo`

除隔离测试环境外，不建议使用：

```bash
--yolo
```

该参数会跳过危险命令审批，不适合当前生产型部署。

## 18. 备份

### 18.1 手工备份

```bash
sudo -iu hermes bash -lc '
cd /opt/hermes-multiagent-deploy
./scripts/backup.sh ./deploy.env
'
```

### 18.2 查看备份

```bash
sudo ls -lh /srv/hermes/backups/
```

### 18.3 应备份的时间点

- 修改任何 Profile 配置前；
- 修改 Provider 或模型前；
- 升级 Hermes 前；
- 修改部署脚本前；
- 开启外部消息平台前；
- 进行大规模工作流前；
- 调整 Kanban 数据结构前。

## 19. 升级原则

当前部署已经经过：

- 四 Profile doctor；
- 模型预检；
- Gateway 验证；
- Kanban Smoke Test；
- Worker 隔离验证；
- Orchestrator 最小权限审计。

不要直接执行：

```bash
hermes update
```

推荐升级流程：

1. 备份；
2. 记录当前版本和 Git commit；
3. 检查 GitHub、PyPI 和模型 Endpoint；
4. 执行 `update --check`；
5. 确认变更范围；
6. 正式升级；
7. 运行四个 Profile doctor；
8. 检查 Gateway；
9. 检查 Kanban diagnostics；
10. 重新执行 Smoke Test；
11. 检查 MySQL 状态。

当前部署源码基线：

```text
e589b739ca70eba00aa90fd3d0228bada00dbf8f
```

> [!NOTE]
> 该提交哈希属于本文记录的部署实例。升级前应重新记录实际值，便于出现问题时定位版本差异。

## 20. 日常推荐操作流程

每天首次使用，切换到 `hermes` 用户：

```bash
sudo -iu hermes
```

检查版本和系统：

```bash
hermes --version
cd /opt/hermes-multiagent-deploy
./scripts/status.sh ./deploy.env
```

启动 Orchestrator：

```bash
hermes -p orchestrator chat
```

在第二个终端监控任务：

```bash
sudo -iu hermes hermes -p orchestrator \
  kanban --board my-project watch
```

工作结束后查看任务：

```bash
hermes -p orchestrator kanban \
  --board my-project list
```

确认：

- 没有异常 `running` 任务；
- 没有未处理 `blocked` 任务；
- Reviewer 失败没有被错误标记为接受；
- Builder 没有绕过 Review；
- 输出文件已经保存；
- 项目工作区状态符合预期。

## 21. 常用命令速查表

| 操作 | 命令 |
| --- | --- |
| 启动交互 | `hermes -p orchestrator chat` |
| 单次查询 | `hermes -p orchestrator chat -q "..."` |
| 纯文本查询 | `hermes -p orchestrator -z "..."` |
| 继续最近会话 | `hermes -p orchestrator --continue` |
| 查看会话 | `hermes -p orchestrator sessions` |
| 查看任务 | `hermes -p orchestrator kanban --board my-project list` |
| 监控任务 | `hermes -p orchestrator kanban --board my-project watch` |
| 查看任务详情 | `hermes -p orchestrator kanban --board my-project show <ID>` |
| Kanban 诊断 | `hermes -p orchestrator kanban --board my-project diagnostics` |
| Gateway 状态 | `hermes -p orchestrator gateway status` |
| Hermes 诊断 | `hermes -p orchestrator doctor` |
| 查看日志 | `hermes -p orchestrator logs` |
| Prompt 体积 | `hermes -p orchestrator prompt-size` |
| Token/成本 | `hermes -p orchestrator insights` |
| 部署状态 | `./scripts/status.sh ./deploy.env` |
| 手工备份 | `./scripts/backup.sh ./deploy.env` |
| 提交代码任务 | `./scripts/submit-feature.sh ./deploy.env "任务"` |

## 22. 十条核心使用原则

1. Orchestrator 负责管理，不负责实施。
2. Researcher 只读调查，不能修改项目。
3. Builder 修改代码，Reviewer 独立验收。
4. Reviewer FAIL 时不得直接接受。
5. 大任务必须拆成可独立验证的小任务。
6. 每个技术结论必须有文件、符号、测试或日志证据。
7. 对话用于决策，Kanban 用于长期执行。
8. 不通过命令行临时扩大 Orchestrator 权限。
9. 不因一次失败就重新部署或清理 Docker。
10. 配置变更和版本升级前必须备份。

## 23. 推荐的第一条日常指令

```text
检查 my-project 当前状态。

请按以下格式返回：
1. running 任务；
2. pending 任务；
3. blocked 任务及原因；
4. 最近完成任务；
5. Reviewer FAIL 但尚未整改的任务；
6. 当前 Worker 状态；
7. 建议我优先处理的下一项工作。

只汇总 Kanban 已有证据，不创建新任务，不修改任何配置。
```

## 24. 手册维护规则

以下内容发生变化时，应更新本手册：

- Hermes 版本；
- Git commit；
- Profile 数量或名称；
- Worker 镜像；
- Kanban Board 名称；
- Gateway 启动方式；
- 外部消息平台；
- Profile 工具权限；
- 模型和 Provider；
- 备份目录；
- 标准工作流脚本；
- 项目目录和输出目录。

建议手册版本号采用：

```text
Hermes 使用手册 v1.0
```

每次升级后递增，例如：

```text
v1.1
v1.2
v2.0
```
