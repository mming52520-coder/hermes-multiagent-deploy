> **当前版本已改为 PackyAPI + DeepSeek 官方混合路由。**
>
> 先阅读 [`PACKY_DEEPSEEK_SETUP.md`](PACKY_DEEPSEEK_SETUP.md)，然后在
> `deploy.env` 中填写三个完整密钥。不要再配置 `OPENROUTER_API_KEY`。

# Hermes 多 Agent 可落地部署包

## 目标拓扑

```text
CLI / Telegram
      │
      ▼
orchestrator Profile
  - 唯一 Gateway
  - Kanban Dispatcher
  - 只拆解、路由、验收
      │
      ├─────────────┬─────────────┐
      ▼             ▼             ▼
 researcher       builder       reviewer
 Docker Worker   Docker Worker  Docker Worker
 只读研究        实现与测试      独立审查
```

四个 Profile 拥有独立的模型、配置、记忆、技能和凭证作用域。只有
`orchestrator` 常驻；其 Gateway 内的 Dispatcher 根据 Kanban 卡片按需启动另外
三个 Worker。

## 主机要求

- Ubuntu 22.04/24.04 或兼容 Debian 系统
- 最低 4 vCPU / 8 GB RAM；建议 8 vCPU / 16 GB RAM
- 80 GB 以上可用 SSD
- 能访问模型供应商、Docker Hub、GitHub 和 Hermes 安装站
- PackyAPI `claude-officially` 与 `codex` 分组的 Token
- 一个 DeepSeek 官方 API Key
- 可选 Telegram Bot token

## 部署

### 1. 准备参数

```bash
unzip hermes-multiagent-deploy.zip
cd hermes-multiagent-deploy
cp deploy.env.example deploy.env
nano deploy.env
```

至少填写：

```bash
PACKY_CLAUDE_API_KEY=...
PACKY_CODEX_API_KEY=...
DEEPSEEK_API_KEY=...

# 推荐至少填写一个：
EXA_API_KEY=...
# 或 FIRECRAWL_API_KEY / PARALLEL_API_KEY
```

如果部署真实项目，填写：

```bash
PROJECT_GIT_URL=git@github.com:org/repo.git
PROJECT_GIT_REF=main
PROJECT_DIR=/srv/hermes/projects/my-project
```

私有仓库需要先给 `hermes` 系统用户配置只具备目标仓库权限的 deploy key。
不要把个人主 SSH Key 或宽权限 PAT 暴露给 Worker。

### 2. 初始化主机

```bash
sudo ./00-bootstrap-root.sh ./deploy.env
```

该步骤会：

- 安装 Docker、Git、jq、Python、SQLite 等依赖；
- 创建专用 `hermes` 系统用户；
- 创建项目、输出和备份目录；
- 开启 Docker；
- 开启 systemd user lingering；
- 将部署包复制到 `/opt/hermes-multiagent-deploy`。

### 3. 安装 Hermes 并创建 Agent

```bash
sudo -iu hermes bash -lc \
  'cd /opt/hermes-multiagent-deploy && ./10-deploy.sh ./deploy.env'
```

该步骤会：

- 使用官方安装器安装 Hermes；
- 创建 `orchestrator/researcher/builder/reviewer` 四个 Profile；
- 写入最小工具权限、Docker 隔离、模型和 SOUL；
- 创建项目 Board；
- 安装并启动 `hermes-gateway-orchestrator.service`；
- 安装每日状态备份 timer；
- 执行端到端 Smoke Test。

## 提交第一项真实工作

```bash
sudo -iu hermes bash -lc \
  'cd /opt/hermes-multiagent-deploy && \
   ./scripts/submit-feature.sh ./deploy.env \
   "为 API 增加基于用户 ID 的令牌桶限流，并补充单元测试"'
```

脚本会创建以下依赖图：

```text
researcher: Research
        │
        ▼
builder: Build
        │
        ▼
reviewer: Review
        │
        ▼
orchestrator: Gate
```

Git 项目使用 `worktree`；非 Git 项目使用项目目录。Builder 必须生成本地 commit，
Reviewer 根据父任务 handoff 中的 branch/commit 独立审查。审查失败时，Orchestrator 会创建 repair → re-review → 新 Gate 链。脚本不会 push 或 merge。

## 运维命令

```bash
cd /opt/hermes-multiagent-deploy

./scripts/status.sh ./deploy.env
./scripts/smoke-test.sh ./deploy.env
./scripts/backup.sh ./deploy.env
./scripts/upgrade.sh ./deploy.env

journalctl --user -u hermes-gateway-orchestrator.service -f

hermes -p orchestrator kanban --board my-project list
hermes -p orchestrator kanban --board my-project watch
hermes -p orchestrator kanban --board my-project diagnostics
```

## Dashboard

只允许监听环回地址：

```bash
./scripts/dashboard.sh ./deploy.env
```

远程机器通过 SSH 隧道访问，不要把 Dashboard 直接绑定到 `0.0.0.0`：

```bash
ssh -L 8080:127.0.0.1:8080 hermes@server
```

## Telegram

在 `deploy.env` 中填写：

```bash
TELEGRAM_BOT_TOKEN=123456:...
TELEGRAM_ALLOWED_USERS=123456789
```

重新运行 `10-deploy.sh`，随后给 Bot 发送消息并执行 `/sethome`。只有
Orchestrator 对外；Worker 不运行自己的 Bot/Gateway。

## 安全边界

- Profile 隔离 Hermes 状态，但不是操作系统沙箱。
- Worker 在 Docker 中运行，只挂载项目、Kanban workspace 和输出目录。
- Researcher 的项目挂载为只读。
- Orchestrator 没有 file/terminal 工具。
- Worker 不持有 Telegram token。
- 外部 Web Search Key 只在配置后启用；至少选择 Exa、Parallel 或 Firecrawl 之一。
- 脚本只向各 Profile 写入其实际使用的模型密钥，不会将全部密钥复制给所有
  Agent；模型调用发生在 Hermes 主进程。
- `git push --force` 和 `curl|sh` 等命令被显式 deny。
- Docker group 具有高权限，因此必须使用专用系统用户，不要在该账户存放其他生产凭证。

## 并发策略

默认：

```yaml
max_in_progress: 2
max_in_progress_per_profile: 1
auto_decompose: false
auto_promote_children: false
```

先稳定运行一周再考虑提高并发。不要在初始部署中开启递归 Orchestrator、
无限 fan-out 或自动拆解后立即执行。

## 备份与恢复

每日 03:15 创建状态备份，保留最近 7 份：

```bash
systemctl --user status hermes-state-backup.timer
```

手工恢复：

```bash
./scripts/restore-state.sh ./deploy.env \
  /srv/hermes/backups/hermes-state-YYYYMMDDTHHMMSSZ.tar.gz
```

状态备份包含 API Key 和 Bot token，文件权限为 `0600`。项目 Git 仓库不在该备份中，
应由远端仓库和独立仓库备份负责。
