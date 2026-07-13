# Hermes 多 Agent（Packy + DeepSeek）一键部署手册

> 版本：v1.0 · 日期：2026-07-13
> 原始 Word 版：[下载 Hermes多Agent_Packy_DeepSeek_一键部署操作手册_v1.0.docx](docs/Hermes多Agent_Packy_DeepSeek_一键部署操作手册_v1.0.docx)
> 配套文档：[Hermes 多 Agent 使用手册](docs/Hermes多Agent_使用手册.md)

> [!WARNING]
> 本手册包含 `sudo`、`rm -rf`、`rsync --delete` 等高影响命令。执行前必须核对路径、备份数据，并遵守文末停止规则。

> [!WARNING]
> **适用前提**
> 本手册按已验证的 hermes-multiagent-deploy-packy-deepseek.zip 结构编写。压缩包应包含 00-bootstrap-root.sh、10-deploy.sh、deploy.env.example、scripts/ 和 Profile/SOUL 配置。若结构不同，应停止并以压缩包内 README 为准。

部署对象：研发同事个人 Ubuntu 工作站 / 受控服务器

部署方式：CLI + Gateway + Docker Worker + Kanban

## 0. 交付前安全检查（提供压缩包的人执行）

1. 压缩包内不得包含填写过密钥的 deploy.env。

2. 只保留 deploy.env.example 或空白模板。

3. Packy、DeepSeek、OpenAI/Claude 等 API Key 由每位同事自行填写。

4. 生成 SHA-256 校验文件，并与 zip 一起发送。

```bash
zipfile="hermes-multiagent-deploy-packy-deepseek.zip"
unzip -l "$zipfile" | grep -E '(^|/)deploy\.env$' \
&& echo "STOP: 压缩包包含 deploy.env" || true
sha256sum "$zipfile" > "$zipfile.sha256"
```

> [!WARNING]
> **判定标准**
> 如果压缩包中出现 deploy.env、真实 API Key、Token、代理密码或私有证书，必须重新打包，不能直接发送。

## 1. 已验证基线与硬件建议

| 项目 | 已验证/建议值 | 说明 |
| --- | --- | --- |
| 操作系统 | Ubuntu 20.04.6 LTS | 当前部署验证基线 |
| 架构 | x86_64 / amd64 | Worker 镜像按 linux/amd64 拉取 |
| Docker | 26.1.3 已验证 | daemon 必须 active/enabled |
| Hermes | v0.18.2 | 部署后应保持版本一致 |
| CPU | 建议 8 核以上 | 多 Worker 并行需要余量 |
| 内存 | 建议 16 GB | 低于 8 GB 不建议并行 |
| 磁盘 | 总容量 ≥80 GB；可用 ≥40 GB | 镜像、源码、缓存和输出均占空间 |
| Worker 镜像 | nikolaik/python-nodejs:python3.11-nodejs20 | 保持模板值 |
| 权限 | 本地 sudo | 仅 bootstrap、安装和 docker load 需要 |

> [!WARNING]
> **业务容器保护**
> 机器上已有 MySQL、ROS、摄像头或其他业务容器时，必须在部署前记录状态，部署后逐项对比。禁止执行 docker system prune。

## 2. 部署总流程

1. 验证压缩包 SHA-256。

2. 解压到短路径目录。

3. 检查系统、磁盘、Docker 和现有容器。

4. 复制并填写 deploy.env。

5. 执行模型接口预检。

6. 执行 00-bootstrap-root.sh。

7. 执行 10-deploy.sh。

8. 运行完整验收。

9. 同步真实项目代码。

10. 启动 Orchestrator 并执行只读首个工作流。

## 3. 收到压缩包后的部署命令

### 3.1 校验与解压

```bash
cd ~
sha256sum -c hermes-multiagent-deploy-packy-deepseek.zip.sha256
rm -rf ~/hermes-multiagent-deploy
mkdir -p ~/hermes-multiagent-deploy
unzip -q hermes-multiagent-deploy-packy-deepseek.zip \
-d ~/hermes-multiagent-deploy
cd ~/hermes-multiagent-deploy
find . -maxdepth 2 -type f -printf '%p\n' | sort
```

必须看到以下关键文件：

- `00-bootstrap-root.sh`
- `10-deploy.sh`
- `deploy.env.example`
- `scripts/configure_profiles.py`
- `scripts/check-model-apis.py`

### 3.2 修复执行权限

```bash
cd ~/hermes-multiagent-deploy
chmod 0700 00-bootstrap-root.sh 10-deploy.sh
find scripts -maxdepth 1 -type f -name '*.sh' \
-exec chmod 0700 {} +
chmod 0700 scripts/*.py 2>/dev/null || true
```

### 3.3 系统与 Docker 基线

```bash
echo '== OS =='
grep -E '^(PRETTY_NAME|VERSION_ID)=' /etc/os-release
uname -m
echo '== CPU / MEM / DISK =='
nproc
free -h
df -h /
echo '== Docker =='
systemctl is-active docker
systemctl is-enabled docker
docker --version
docker ps -a \
--format 'table {{.Names}}\t{{.Status}}\t{{.Image}}'
```

> [!NOTE]
> **通过条件**
> Docker 必须 active/enabled，架构必须是 x86_64；根分区可用空间建议不低于 40 GB。关键业务容器状态必须先保存。

## 4. 配置 deploy.env

```bash
cd ~/hermes-multiagent-deploy
cp -n deploy.env.example deploy.env
chmod 0600 deploy.env
nano deploy.env
```

| 配置类别 | 建议 | 禁止 |
| --- | --- | --- |
| API Key | 每位同事使用自己的 Packy/DeepSeek 凭据 | 复制他人的生产密钥 |
| PROJECT_DIR | /srv/hermes/projects/my-project | 直接指向含敏感或未备份的生产目录 |
| OUTPUT_DIR | /srv/hermes/outputs | 放入项目源码目录 |
| BOARD_SLUG | my-project | 使用包含空格或特殊字符的名称 |
| DOCKER_IMAGE | 保持模板镜像 | 随意改成 latest 或未知镜像 |
| 模型/Endpoint | 以模板和预检脚本为准 | 根据名称猜测接口格式 |

只列出变量名，不显示值：

```bash
awk -F= '/^[A-Z_][A-Z0-9_]*=/{print $1}' deploy.env
```

检查空值和占位符：

```bash
grep -nE 'CHANGE_ME|REPLACE_ME|TODO|^[A-Z_][A-Z0-9_]*=$' deploy.env || true
```

> [!WARNING]
> **密钥文件权限**
> deploy.env 必须保持 0600。不要通过聊天、截图、工单或 Git 仓库传递其内容。

## 5. 模型接口预检

```bash
cd ~/hermes-multiagent-deploy
python3 scripts/check-model-apis.py ./deploy.env
```

若脚本提示用法不同：

```bash
python3 scripts/check-model-apis.py --help
```

- Packy Claude、DeepSeek、Packy Codex/gpt-5.2 等已配置接口应全部成功。
- Packy Codex Responses 接口的 `input` 必须为消息列表，而不是纯字符串。
- 任何模型预检失败都应停止部署，先修复密钥、Endpoint、模型名或请求格式。

## 6. 执行根级引导

```bash
cd ~/hermes-multiagent-deploy
sudo ./00-bootstrap-root.sh ./deploy.env
```

若出现“找不到命令”：

```bash
sudo bash ./00-bootstrap-root.sh ./deploy.env
```

完成后验证：

```bash
id hermes
sudo test -d /opt/hermes-multiagent-deploy && echo OK
sudo stat -c '%U:%G %a %n' \
/opt/hermes-multiagent-deploy/deploy.env
```

> [!NOTE]
> **预期**
> 系统存在 hermes 用户；部署副本位于 /opt/hermes-multiagent-deploy；deploy.env 为 hermes:hermes 600。

## 7. 正式部署

```bash
sudo -iu hermes bash -lc \
'cd /opt/hermes-multiagent-deploy && \
./10-deploy.sh ./deploy.env'
```

部署脚本应完成：

- 安装或配置 Hermes；
- 创建 `orchestrator`、`researcher`、`builder`、`reviewer` 四个 Profile；
- 拉取或使用本地 Worker 镜像；
- 启动 Gateway 和 Backup Timer；
- 创建 Kanban Board；
- 启动 Worker；
- 执行 Smoke Test。

> [!WARNING]
> **失败处理**
> 失败时立即停止并保存完整错误。不要自动重跑 bootstrap、删除容器、清理 Docker、修改密钥或放宽权限。

## 8. 完整验收

### 8.1 总体状态

```bash
sudo -iu hermes bash -lc '
cd /opt/hermes-multiagent-deploy
./scripts/status.sh ./deploy.env
'
```

### 8.2 Hermes、Gateway、Kanban

```bash
sudo -iu hermes hermes --version
sudo -iu hermes hermes -p orchestrator gateway status
sudo -iu hermes hermes -p orchestrator \
kanban --board my-project diagnostics
sudo -iu hermes hermes -p orchestrator \
kanban --board my-project list
```

### 8.3 四 Profile doctor

```bash
for p in orchestrator researcher builder reviewer; do
echo "===== $p ====="
sudo -iu hermes hermes -p "$p" doctor
done
```

### 8.4 Docker 与挂载

```bash
docker ps -a \
--format 'table {{.Names}}\t{{.Status}}\t{{.Image}}'
docker image inspect \
nikolaik/python-nodejs:python3.11-nodejs20 \
--format 'ID={{.Id}} ARCH={{.Architecture}} OS={{.Os}}'
```

Researcher 项目挂载必须只读：

```bash
docker inspect \
$(docker ps -q --filter 'name=researcher' | head -n 1) \
--format '{{range .Mounts}}{{println .Source .Destination .RW}}{{end}}'
```

敏感文件权限：

```bash
sudo find /opt/hermes-multiagent-deploy /home/hermes/.hermes \
-type f \( -name 'deploy.env' -o -name '.env' \) \
-printf '%m %u:%g %p\n'
```

| 验收项 | 通过标准 |
| --- | --- |
| Hermes | v0.18.2 |
| Gateway | active、enabled |
| Backup Timer | active |
| Kanban | diagnostics 无阻断；Smoke task done |
| Worker | 两个容器运行；linux/amd64；非 privileged；bridge 网络 |
| Researcher | 项目挂载 RW=false |
| Orchestrator | 实际无 terminal/file/code_execution 等 forbidden tools |
| Dashboard | 未监听 0.0.0.0 |
| 敏感文件 | deploy.env 与 Profile .env 均为 0600 |
| 业务容器 | 与部署前状态完全一致 |

## 9. 同步真实项目

> [!WARNING]
> **注意**
> 默认 /srv/hermes/projects/my-project 可能为空。不要在空目录上做真实架构审查。

```bash
sudo mkdir -p /srv/hermes/projects/my-project
sudo rsync -a \
--delete \
--exclude build/ \
--exclude devel/ \
--exclude log/ \
--exclude logs/ \
--exclude .cache/ \
'/真实项目绝对路径/' \
/srv/hermes/projects/my-project/
sudo chown -R hermes:hermes \
/srv/hermes/projects/my-project
```

验证目录非空：

```bash
sudo -iu hermes bash -lc '
find /srv/hermes/projects/my-project \
-mindepth 1 -maxdepth 2 \
-printf "%y %p\n" | head -n 30
'
```

若为 Git 仓库：

```bash
sudo -iu hermes git -C \
/srv/hermes/projects/my-project rev-parse HEAD
sudo -iu hermes git -C \
/srv/hermes/projects/my-project status --short
```

## 10. 启动与首个工作流

```bash
sudo -iu hermes hermes -p orchestrator chat
```

建议首条指令：

> [!NOTE]
> **首个工作流提示词**
> 检查 /srv/hermes/projects/my-project 是否包含真实代码。先建立只读架构审查工作流：researcher 调查、builder 生成报告、reviewer 独立抽查、orchestrator 最终 Gate。禁止修改项目源码。创建任务前先展示任务拆分、依赖和验收标准。

监控任务：

```bash
sudo -iu hermes hermes -p orchestrator kanban --board my-project watch
```

## 11. 常用运维命令

| 用途 | 命令 |
| --- | --- |
| 总体状态 | sudo -iu hermes bash -lc 'cd /opt/hermes-multiagent-deploy && ./scripts/status.sh ./deploy.env' |
| Gateway 日志 | sudo -iu hermes journalctl --user -u hermes-gateway-orchestrator.service -f |
| 任务列表 | sudo -iu hermes hermes -p orchestrator kanban --board my-project list |
| Kanban 诊断 | sudo -iu hermes hermes -p orchestrator kanban --board my-project diagnostics |
| 交互启动 | sudo -iu hermes hermes -p orchestrator chat |
| 手工备份 | sudo -iu hermes bash -lc 'cd /opt/hermes-multiagent-deploy && ./scripts/backup.sh ./deploy.env' |

## 12. 已知网络故障与在线备用路径

### 12.1 Docker Hub pull 超时

```bash
curl -4I --connect-timeout 15 --max-time 30 \
https://registry-1.docker.io/v2/
```

返回 401 Unauthorized 表示网络和 TLS 可达。如果 docker pull 仍超时且不能重启 Docker，可使用 Crane 在当前机器在线拉取，再导入本机 Docker。

```bash
set -Eeuo pipefail
tmp="$(mktemp -d /tmp/crane-install.XXXXXX)"
trap 'rm -rf -- "$tmp"' EXIT
version='v0.21.7'
asset='go-containerregistry_Linux_x86_64.tar.gz'
base="https://github.com/google/go-containerregistry/releases/download/$version"
curl --http1.1 -4 --fail --show-error --location \
--retry 5 --retry-delay 3 --retry-connrefused \
--connect-timeout 20 --max-time 900 \
"$base/$asset" -o "$tmp/$asset"
curl --http1.1 -4 --fail --show-error --location \
--retry 5 --retry-delay 3 --retry-connrefused \
--connect-timeout 20 --max-time 300 \
"$base/checksums.txt" -o "$tmp/checksums.txt"
expected="$(awk -v file="$asset" \
'$2==file || $2=="*"file {print $1; exit}' \
"$tmp/checksums.txt")"
actual="$(sha256sum "$tmp/$asset" | awk '{print $1}')"
test -n "$expected" && test "$expected" = "$actual"
tar -xzf "$tmp/$asset" -C "$tmp"
sudo install -o root -g root -m 0755 \
"$tmp/crane" /usr/local/bin/crane
crane version
```

在线拉取并导入：

```bash
mkdir -p ~/.cache/hermes-images
chmod 0700 ~/.cache/hermes-images
crane pull --platform linux/amd64 \
docker.io/nikolaik/python-nodejs:python3.11-nodejs20 \
~/.cache/hermes-images/hermes-worker.tar
sudo docker load -i \
~/.cache/hermes-images/hermes-worker.tar
```

> [!WARNING]
> **重要**
> 包内 10-deploy.sh 应已包含“本地镜像存在时跳过 docker pull”的判断。导入后只重新执行一次 10-deploy.sh。

### 12.2 Ubuntu 20.04 找不到 skopeo

不要继续添加不明 PPA。Focal 环境直接使用 Crane。

### 12.3 curl 不支持 --retry-all-errors

Ubuntu 20.04 的旧版 curl 不使用该参数，改用：

```bash
--retry 5 --retry-delay 3 --retry-connrefused
```

### 12.4 GitHub API 返回 403

通常是匿名 API rate limit。固定版本 Release 下载不需要调用 /releases/latest API。

## 13. 安全边界

| 禁止行为 | 原因 |
| --- | --- |
| 发送填写过密钥的 deploy.env | 直接泄露模型和服务凭据 |
| 给 Orchestrator 启用 terminal/file/code_execution | 破坏编排器最小权限 |
| 使用 --yolo | 跳过危险命令审批 |
| 使用未知 Registry mirror | 供应链与镜像篡改风险 |
| 关闭 TLS 校验 | 失去服务端身份校验 |
| privileged / host network | 扩大容器权限和攻击面 |
| docker system prune | 可能删除业务镜像、卷和缓存 |
| 未备份直接 hermes update | 版本变化后难以恢复 |
| 依据 Doctor 环境可用性判断实际权限 | Doctor 不是实际有效工具集审计 |

> [!NOTE]
> **Orchestrator 允许工具集**
> kanban、memory、session_search、todo、clarify、skills。

## 14. 交付验收清单

☐ 压缩包 SHA-256 验证通过

☐ 压缩包不含填写过的 deploy.env

☐ deploy.env 权限 0600

☐ Docker active/enabled

☐ 原有容器状态已记录

☐ 模型接口预检通过

☐ bootstrap 成功

☐ Hermes v0.18.2 可运行

☐ 四 Profile 创建并 doctor 基础通过

☐ Worker 镜像 linux/amd64

☐ Gateway active/enabled

☐ Backup Timer active

☐ Kanban diagnostics 无阻断

☐ Smoke Test done

☐ Researcher 项目挂载 RW=false

☐ Orchestrator 实际无 forbidden tools

☐ Dashboard 未监听 0.0.0.0

☐ 原有 MySQL/业务容器状态不变

☐ 真实项目已同步且目录非空

☐ 首个只读工作流通过

## 15. 停止规则

出现以下任一情况应停止，不得继续自动尝试：

- SHA-256 不一致；
- 压缩包包含真实密钥；
- 根分区可用空间低于 40 GB；
- Docker daemon 异常；
- 现有关键容器状态发生变化；
- 模型接口预检失败；
- Worker 镜像架构不是 amd64；
- Gateway、Timer 或 Smoke Test 失败；
- Researcher 对项目挂载为可写；
- Orchestrator 实际启用 `terminal`、`file`、`code_execution`；
- 部署要求关闭 TLS、使用不明镜像源或提高容器权限。

> [!NOTE]
> **最终原则**
> 失败时保留证据、停止扩大权限、先定位阻断点。不要把“脚本完成”当作“部署验收通过”。

— 手册结束 —
