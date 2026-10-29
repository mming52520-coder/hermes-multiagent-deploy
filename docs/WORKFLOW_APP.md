# Hermes Workflow 网页应用

CLI 已封装为原生 Hermes Dashboard 的「工作流」页面。它使用宿主的 React SDK、登录认证和插件路由，后端复用 `workflow_control.py`；没有新增任务数据库、调度器或独立管理后台。CLI 仍可使用。

中文接入包首次使用默认简体中文；工作流页内有「使用说明与按键」，也可查看 [中文按钮与键盘操作说明](WORKFLOW_APP_BUTTONS_ZH.md)。原始命令、路径和日志保留原文。

## 当前环境的启动方式

应用已经安装并启用在当前环境的本地 Hermes 配置，模式为**只读**；真实执行记录为 0。当前没有常驻网页测试服务，也没有 Gateway/Worker 被启动。

```bash
cd /workspace/hermes-multiagent-deploy
source /workspace/.local/share/hermes-onboarding/activate.sh
bash scripts/workflow-app.sh
```

打开启动信息指向的 Hermes Dashboard，选择左侧「工作流」。不要把带会话凭据的启动 URL 发到聊天或工单。启动脚本默认监听回环地址，使用已准备的前端资源、显式跳过自动前端构建，并将 HERMES_DESKTOP 设为 0，因此不会启用 Desktop 专属 Cron ticker。它不会安装插件、重写配置或启动 Gateway。

当前安装位置：`/workspace/.local/share/hermes-onboarding/state/plugins/workflow`。`config.json` 只保存 Hermes home、服务器绑定的 deploy.env 路径、基线归档路径和 `allow_actions: false`；不保存密钥值。安装器使用原生插件启用流程，并显式拒绝 built-in tool override 权限。

## 可以操作什么

- 浏览当前配置绑定项目与 Board 的执行目标，搜索并筛选阻塞任务。
- 查看 Research → Build → Review → Gate 依赖、各角色状态、原生 task ID 和运行结果。
- 区分普通任务完成、待验收、有效已验收，查看不满足门禁的原因。
- 查看当前候选版本、内容 digest、真实变更清单、两份操作员验证 receipt 和日志 hash；日志展示限制为最近 16 KB。
- 查看整改原因、轮次和预算，实际 API 费用未知时显示「未获取」。
- 操作员在服务器启用操作后，可通过表单提交目标、授权执行、准备审查副本、分别运行验证、提交质量验收和发起整改。

新目标仍默认生成 triage 卡。应用不会自动 commit、push、创建 PR 或部署。默认只读模式由后端强制执行，修改浏览器按钮状态不能绕过它。执行列表每 20 秒读取一次；选中执行时重新核验状态与证据，「刷新」可再次核验。

## 人工受控操作与 P0 边界

服务器插件的 `config.json` 中只有操作员可以把 `allow_actions` 改为 `true`。刷新页面后显示「人工受控」。这是启用手动按钮，不是启用自主规划或无人值守运行。每次有副作用的操作都要在界面确认；后端要求宿主登录态、明确的操作请求、同源检查和固定版本来源校验，随后仍调用原来的质量/预算门禁。

服务器的 env_file 固定绑定目标项目与 Board；HTTP 请求不能更换该文件、项目路径、模型、测试命令或任意 shell 命令。测试命令只能由操作员在部署配置中预先设置。

**原 P0 限制没有被界面解决：**实际费用/模型调用次数硬限额、在途执行级总时限仍未完整实现；真实 Worker、模型协作与 Gateway 服务级恢复仍为 NOT_TESTED。设置有限费用上限时，旧版后端仍拒绝继续。Chief/PM、Playbook 和长期自治仍未启用。

只读开关仅约束本插件；Hermes 原生 Dashboard 的 Chat、终端、配置等其他功能仍沿用其原权限。宿主登录目前是操作员级信任，不是新增多租户或分角色权限系统。不要把 operator receipt 目录挂入 Worker。

## 已安装 v0.22.5 的 Linux 电脑

已增加默认 in-process 模式的只读接入验证；安装步骤和范围见 [本地 v0.22.5 接入](LOCAL_HERMES_V0225.md)。后文的 v0.18.2 部署与写入步骤不能直接套用到 v0.22.5。

## 在另一套 Hermes v0.18.2 安装中使用

前提是已验证的 Hermes v0.18.2 固定基线，并具备该安装的原生 Dashboard 前端与 FastAPI 依赖。使用那套 Hermes 的 Python：

```bash
"$hermes_python" scripts/install-workflow-app.py \
  --home /path/to/hermes-home \
  --env /path/to/deploy.env \
  --enable
```

非 Git 安装可加 `--archive /path/to/verified-baseline.tar.gz`，供后端沿用原来的逐文件来源校验。安装器复制插件与现有 P0 控制模块，使用原生 enable 并保留其他设置；不运行部署、升级、模型或 Docker。再次安装会保留 config.json，检测到本地修改过的受管代码时拒绝覆盖。未知插件目录也不会被替换。

从相同 HERMES_HOME 启动原生 Dashboard；如果它已在运行，在你选择的时机重新启动**该 Dashboard 进程**以加载新的 API，不需要为此重启 Gateway。原始四角色、模型配置、干净目标项目和已有 Board 仍是提交/执行的前提。本环境尚无真实任务，示意截图均来自隔离测试数据。

## 本环境缺失的前端资源如何准备的

固定源码归档原本没有 `hermes_cli/web_dist`。本次在 `/workspace/.cache/hermes-workflow-dashboard-build` 建立独立源码副本，并执行：

```bash
npm ci --workspace web --include-workspace-root=false --no-audit --no-fund --cache /workspace/.cache/npm
npm run build --workspace web
```

npm ci 使用上游 package-lock，保留 TLS 与 integrity 校验；TypeScript 和 Vite 生产构建均通过。输出位于独立副本的 `hermes_cli/web_dist`，通过官方 HERMES_WEB_DIST 运行时覆盖使用，未改实际 Hermes 源文件或锁文件。构建命令最初误指向原上游目录；已停止并将仅由该命令新增的 node_modules 移到独立构建目录。后续浏览器真实提交再次通过原上游源码逐文件校验，原目录没有遗留这些依赖目录。

首次在其他机器准备时，可以对**独立副本**执行上述命令；若发行版已带 web_dist，无需构建。不要在维护中的源码安装上盲目 npm ci。

## 验证证据

| 检查 | 结果 | 范围 |
|---|---|---|
| 原 P0 + 第一版应用完整回归 | PASS：45 tests / 23.527s | 32 个原测试 + 当时 13 个应用测试 |
| 最终应用套件 | PASS：14 tests / 4.586s | 增加项目绑定检查；认证、只读拒绝、同源/确认、固定参数、证据、缺失 DB、安装保护、原生插件加载 |
| 安装器禁止工具覆盖的针对性复验 | PASS | 使用 --no-allow-tool-override，不弹额外权限提示 |
| 浏览器 | PASS：6 组 | 真实 Chromium + 原生 Dashboard SDK/认证/路由；不是独立模拟页面 |
| 前端构建 | PASS | 上游冻结依赖安装、tsc、Vite；原生大 bundle 警告未修改上游来压制 |
| 本地实际安装 | PASS | 原生发现插件、已认证 API、JS 资源均返回成功；只读、0 条真实执行 |
| 实际模型 / Worker / 部署 | NOT_TESTED | 没有调用或启动，也没有发布公网入口 |

浏览器验证了：默认按钮禁用、4 阶段状态、验收 receipt/日志查看、搜索与阻塞筛选、390px 移动端无横向溢出、隔离环境提交并保持 triage、目标文本的 XSS 转义、审批勾选、Esc 取消且没有发送执行 action。浏览器没有页面错误。提交验证使用真实后端与来源检查；Worker/模型仍是测试替身。

测试命令：

```bash
/workspace/.venvs/hermes-agent/bin/python -m unittest discover -s tests -v
/workspace/.venvs/hermes-agent/bin/python -m unittest discover -s tests -p test_workflow_app.py -v
node --check plugins/workflow/dashboard/app.js
node --check tests/browser_workflow_app.cjs
```

浏览器可在单独终端运行 `tests/browser_app_fixture.py --assets <built-web-dist> --info <temporary-info.json>`，再以 Playwright/Chromium 执行 `node tests/browser_workflow_app.cjs <temporary-info.json> <artifact-directory>`。夹具创建自己的临时项目、Profile、Board 和 token；不要把测试指向真实部署。测试结束停止自己的夹具进程。

桌面与移动截图在本环境的 `/workspace/artifacts/workflow-app/desktop.png`、`mobile.png`；都是明确标记「离线演示」的数据。后端原始输出见 [应用测试记录](WORKFLOW_APP_TEST_RESULTS.txt)。

## 文件与兼容性

- `plugins/workflow/plugin.yaml`、`dashboard/manifest.json`：原生 Dashboard 插件注册。
- `dashboard/app.js`、`app.css`：中文响应式界面，直接复用 SDK，无第二份 React 或前端构建配置。
- `dashboard/plugin_api.py`：认证 API，只允许固定操作、绑定项目和固定证据路径。
- `scripts/install-workflow-app.py`：可重复且保护本地修改的安装器。
- `scripts/workflow-app.sh`：原生 Dashboard 启动入口，不自动安装或改配置。
- `scripts/workflow_control.py`：只调整导入方式，使相同核心既可独立 CLI 运行也可作为插件私有包导入；原 CLI 回归通过。
- `tests/test_workflow_app.py`、`browser_app_fixture.py`、`browser_workflow_app.cjs`：接口与实际浏览器测试。

已有 P0 改动保留，源码、中文接入包和说明随同一分支提供；main 合并状态以 GitHub 为准。项目工作记忆继续追加到同一文件，未新建另一套任务状态或自治系统。
