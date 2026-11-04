# 总控台对话 A 阶段验收记录

2026-11-04，唯一对话窗口以「总控台对话」的名称通过 A 阶段验收。新建和已有的项目会话均显示新名称，已有会话的编号、消息和任务关联继续使用。历史任务的自定义标题按原记录展示。

实现分支为 `web/architect-chat`，目标分支为 `web/ui-refresh`，基线为 `e1e5be4`。合并需要单独确认。[依赖的 PR #5](https://github.com/mming52520-coder/hermes-multiagent-deploy/pull/5)

## 行为与边界

- 每个项目和看板只有一条架构师对话，可生成多项待审批任务。同项目已有的 v2 任务在首次写入架构师入口时关联，后续写入也会拾取从原入口新建的任务；原任务、原对话不改写。只读 GET 不创建会话或执行。
- 用户文字只会交给无执行工具的架构师；批准、验收、修改及不做只由卡片按钮生效。服务端核对当前卡片、允许操作、轮次和原因，继续沿用原生会话认证、同源、来源校验及 `allow_actions`。
- 同一张卡片的并发提交有跨进程占用记录；核心方法自行加锁，推荐请求和同步占位调用都在执行锁外。验收再核对候选摘要，拒绝和修复再核对轮次。
- 决策记录保存原卡片快照，使已处理的卡片留在原时间位置；过期按钮返回 409。进展来自持久化状态迁移，平台验证失败与审查阻断分别显示。
- 推荐使用独立 session、禁用执行工具，最长等待 60 秒；结果按轮次和状态缓存。无模型、异常或超时使用规则说明，写回前再次核对轮次和状态。
- 回复进度每 0.5 秒写入 `pending.json`。其他进程持有会话锁时显示运行中，锁已释放且遗留 pending 才提示中断。
- `workflow_feishu.sync_card` 在 A 阶段仅为占位。现有 Webhook 仍为单向通知，链接加入 `card` 和 `execution`。预览中的飞书消息和推荐均为模拟数据。
- 原 v1 操作、确认弹窗及低版本布局保留；未新增终态，未改 Reviewer 工具集，未替换现有下载包。

## 执行前核实

**A1：推荐不会写入架构师会话。** 对照固定 Hermes v0.22.5 源码 `agent/agent_init.py::_init_session_state`：传入的 session_id 被直接采用，session_db 来自调用参数。推荐每次创建独立 UUID，传入 `session_db=None`；不传架构师历史，工具集为空。测试核对 session_id 不同、缓存只请求一次、架构师消息库没有增加记录。这里验证的是源码路径和替身调用，未请求真实模型。

**A2：状态写入和读取开销。** `workflow_control.py` 中 9 处 `workflow_state` 直接赋值均经 `save()` 持久化，执行 manifest 的唯一写入也在 `save()`；未发现绕过该方法改状态的路径。保存只增加一次本地 JSON 读取和解析，同状态不增加迁移记录。用真实隔离 v2 夹具生成的 10,058 字节 manifest，热缓存连续读取 2,000 次：中位 0.0346 ms，P95 0.0411 ms。这只衡量本机热缓存读取开销，不代表冷盘或完整状态推进性能。

GitHub 参照核对了官方 Hermes 的 session 初始化、无工具 Agent 和原生插件测试夹具；依据 MIT 源码了解调用约定，未引入新依赖或复制独立实现。B 类飞书事件与回调核实留到 B 阶段完成，未编写依赖尚未核实行为的入站处理。

## 验证结果

测试按文件分别运行，使用隔离项目、看板、数据根和模拟 Worker / Docker / 模型，不指向现有任务。

| 检查 | 基线 | 本阶段结果 |
|---|---:|---:|
| 前端组件 | 49 | 62 通过 |
| `test_workflow_app` | 21 | 21 通过，原断言未改 |
| `test_workflow_v2` | 19 | 20 通过 |
| `test_workflow_policy` | 11 | 11 通过 |
| `test_workflow_automation` | 4 | 4 通过 |
| `test_workflow_conversation` | 8 | 12 通过 |
| `test_workflow_timeline` | 无 | 16 通过 |
| `test_workflow`，固定 v0.18.2 | — | 47 通过 |
| `check_workflow_writes_v0225` | — | 11 通过 |
| `check_workflow_models` | — | 9 通过 |
| 原生只读发现 / 挂载 / 认证检查 | — | 通过 |

共 151 项 Python 测试、62 项前端测试。另检查 Python 编译、JavaScript 语法、Shell 语法、差异空白和接入包文件及内容清单。前端原 49 项继续走能力开关关闭的旧布局，新增测试覆盖消息与进展顺序、确认弹窗、过期卡、已处理结论、深链、抽屉轮询、待决策定位、自然语言不触发操作、草案编辑、历史只读和新消息滚动。相同内容的轮询保留阅读位置。

改名复验覆盖了中英文标题、消息署名，以及用只读接口打开旧名称的会话。另在隔离项目安装插件，通过认证 API 对已具备测试及审查证据的任务点击验收对应的操作。后端生成操作员验收凭据，原位置的卡片显示结论，重复提交原卡片返回 409。浏览器预览实测输入「可以」后仍有两项待决定，在确认窗口提交后减少为一项。

浏览器预览验证了单一输入框、任务抽屉、确认目标及轮次、证据入口、卡片定位与移动端布局。截图为离线演示，不能当作真实模型、任务执行或飞书联动的证据。

### 测试环境修正

初次直接使用生产 venv 并改 HOME 时触发 Hermes 的环境重新选择，丢失测试路径；最终按固定版本、匹配 Python 环境分别运行，不混用 v0.18.2 和 v0.22.5。

两个原生夹具问题在未修改的基线也可复现，修正范围仅为准备方式：

1. stage-output 测试直接导入源码 API，缺少安装目录中的 operator。改为先用现有安装器安装到临时数据根，再导入安装后的 API，原断言保留。
2. 原生只读测试从未启用的插件开始会触发依赖环境发布及外部下载；改为私有配置预先启用，再核对原生 enable 的 `ok/unchanged`。原发现、认证、四阶段、证据和拒绝写入断言均保留。该检查不覆盖首次插件依赖发布。

固定源码为 v0.22.5 `bf0203a794a07aac3ff764972ab9087baa4e4f4e` 和历史 v0.18.2 `aaf5691261f12601db845386d650dce1cdfa30f9`。当前运行检查通过 Git 固定源码验证；测试用的本地生成归档不作为官方发布归档或归档校验回退通过的证明。

### 复跑

在仓库根目录运行。使用对应固定源码和兼容的 Python，变量换成自己的本地路径；不要把凭据写入命令。

```bash
HERMES_FRONTEND_SOURCE=/path/to/hermes-v0225 node --test tests/workflow_dashboard.test.cjs
PYTHONPATH=/path/to/hermes-v0225:$PWD/tests /path/to/v0225-python -m unittest test_workflow_app
```

同样环境逐文件执行 `test_workflow_v2`、`test_workflow_policy`、`test_workflow_automation`、`test_workflow_conversation`、`test_workflow_timeline`、`check_workflow_writes_v0225` 和 `check_workflow_models`。`test_workflow` 使用 v0.18.2 的源码与 Python，不能用新版结果替代旧版兼容验证。

```bash
PYTHONPATH=/path/to/hermes-v0225 /path/to/v0225-python tests/check_workflow_readonly.py
node --check plugins/workflow/dashboard/app.js
bash -n update-workflow-plugin.sh
git diff --check
```

## 安装与回滚

在本分支或包含本次代码的接入包根目录执行：

```bash
bash update-workflow-plugin.sh
```

默认使用已有 `~/.hermes`，其他数据根可沿用 `HERMES_HOME`。脚本从已安装插件的 config.json 读取原项目绑定，先把插件和绑定 env 备份至该数据根的 `backups/workflow-*`，目录权限 700、env 权限 600。随后复用现有安装器，保留绑定和操作开关，遇到受管代码有本地改动时拒绝覆盖；不修改模型凭据，不自动重启服务。

随后只重启使用此数据根的 Dashboard 与 Gateway。使用前先在原生「模型」页为主模型完成连接配置，架构师与推荐沿用该连接；不要把 Key 发到对话中。四个角色连接继续使用工作流的「模型配置」。真实任务还需要现有执行环境和测试命令就绪。

回滚时停止此数据根对应的服务，保留当前插件目录，复制脚本打印的私有备份中 `plugin` 回原安装位置；只有需要回滚配置时才把备份 env 复制回 config.json 中记录的原绑定路径，并保持权限 600。随后重新启动相同服务。不要删除 workflow 执行记录、原生会话库或看板数据库。

本阶段没有升级用户正在运行的安装，也没有执行真实模型、Gateway Worker、Docker 或飞书端到端测试。验收完成后的 PR 创建、合并以及 B 阶段按实施方案顺序推进。
