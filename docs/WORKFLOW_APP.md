# Hermes Workflow 网页应用

CLI 已封装为原生 Hermes Dashboard 的「工作流」页面。它使用宿主的 React SDK、登录认证和插件路由，后端复用 `workflow_control.py`；没有新增任务数据库、调度器或独立管理后台。CLI 仍可使用。

中文接入包首次使用默认简体中文；工作流页内有「使用说明与按键」，也可查看 [中文按钮与键盘操作说明](WORKFLOW_APP_BUTTONS_ZH.md)。原始命令、路径和日志保留原文。

## 当前版：创建、审批、启动

v0.4.0 在主界面直接展示四行模型配置：选择各自厂商、填写 Key，点「获取全部模型」，从各自目录选模型，最后一次保存全部修改。支持单行获取、自定义 API、手动模型编号，以及将一套连接填入全部角色；不再逐个打开配置弹窗。原生默认地址与协议自动填入，智谱国际 / 中国站提供地区选项。

认证接口 `GET /api/plugins/workflow/model-connection` 返回厂商目录和基础角色状态。`POST /model-connections/models` 接收 `connections` 映射（角色名到 provider/api_key/base_url/protocol），逐角色保存 Key 并读取目录，响应包含 models、source 和错误，不改变模型配置。`PUT /model-connections` 接收相同映射及选定 model、可选 execution，统一应用修改并在同步目标时撤销旧审批。相对路径均在 `/api/plugins/workflow` 下；原单数 `PUT /model-connection` 保持兼容。

列表查询显式传入各角色自己的 Key 和地址，不借用其他角色或主配置档的凭据；Gemini 按原生响应格式与分页读取可生成文本的模型。厂商不提供实时目录时标明推荐目录。凭据使用原生写入器保存，响应不含 Key。模型配置只作用于基础角色及用户选择同步的未启动目标，已运行目标保持原连接。接口沿用宿主会话、同源、明确操作请求和来源门禁；默认只读安装不开启配置功能。

v0.22.5 精确审计基线已支持工作流写入。使用真实原生 Dashboard 和独立持久化数据根，绑定已提交版本的干净项目副本；安装后由操作员显式开放人工操作。访问地址以 Dashboard 启动输出为准。

「新建目标」只建立四个 triage 任务；「人工审批」保存当前版本和轮次授权，仍不放行任务；另行确认「启动多 Agent」才调用原生 Gateway 和原子调度器。启动依赖不足时不放行，重复启动不重复领取。独立审查、验证、验收与整改仍沿用原 P0 控制层。旧 HTTP start 路径是 launch 的兼容别名，同样要求先审批及依赖检查；原 CLI 参数不变。

页面显示源版本、Docker、测试命令、预算策略和四角色准备状态。缺少 Docker 或角色凭据时，创建和审批仍可用，启动被阻止。详见 [v0.22.5 安装与操作说明](LOCAL_HERMES_V0225.md)。以下云端路径、只读实例及早期验证记录为历史记录，实际配置以自己的安装为准。

本轮验证：63 项旧版回归、10 项 v0.22.5 写入/调度检查、18 项组件测试以及新版原生只读检查通过。浏览器在真实服务创建了标注为验证用途的目标，四阶段均待审批；核对了双语准备清单、审批范围和手机布局。未调用真实模型或 Docker Worker，调度进程仅在独立测试中使用替身。

## 启动模板

激活对应 Hermes 的 Python 环境并完成插件安装后，在仓库目录启动。示例路径需替换为自己的目录。

```bash
cd /path/to/hermes-multiagent-deploy
export HERMES_HOME=/path/to/hermes-home
bash scripts/workflow-app.sh
```

打开启动信息指向的 Hermes Dashboard，选择左侧「工作流」。不要把带会话凭据的启动 URL 发到聊天或工单。启动脚本默认监听回环地址，使用已准备的前端资源、显式跳过自动前端构建，并将 HERMES_DESKTOP 设为 0，因此不会启用 Desktop 专属 Cron ticker。它不会安装插件、重写配置或启动 Gateway。

插件安装位置：`$HERMES_HOME/plugins/workflow`。`config.json` 只保存 Hermes home、服务器绑定的 deploy.env 路径、基线归档路径和 `allow_actions: false`；不保存密钥值。安装器使用原生插件启用流程，并显式拒绝 built-in tool override 权限。

## 可以操作什么

- 浏览当前配置绑定项目与 Board 的执行目标，搜索并筛选阻塞任务。
- 查看 Research → Build → Review → Gate 依赖、各角色状态、原生 task ID 和运行结果。
- 区分普通任务完成、待验收、有效已验收，查看不满足门禁的原因。
- 查看当前候选版本、内容 digest、真实变更清单、两份操作员验证 receipt 和日志 hash；日志展示限制为最近 16 KB。
- 查看整改原因、轮次和预算，实际 API 费用未知时显示「未获取」。
- 操作员开放后，可通过表单创建目标、独立审批、启动原生多 Agent、准备审查副本、分别验证、提交质量验收和整改。

新目标仍默认生成 triage 卡。应用不会自动 commit、push、创建 PR 或部署。默认只读模式由后端强制执行，修改浏览器按钮状态不能绕过它。列表、选中详情与打开的证据页每 20 秒同步一次；「刷新」可立即重读。迟到的旧请求不会覆盖新选择，慢请求不会叠加轮询。失败时保留该目标最近的成功数据并标记，暂停操作按钮，恢复同步后继续使用。

概览提供四阶段进度及「下一步」指引，区分待审批、已审批待启动、执行中、阻塞、任务完成和交付验收。混合运行/阻塞和缺失记录计入「需要关注」。可定位阻塞卡片、查看证据，或继续未完成的放行操作；派发需明确点击启动。

## 人工受控操作与 P0 边界

服务器插件的 `config.json` 中只有操作员可以把 `allow_actions` 改为 `true`。刷新页面后显示「人工受控」。这是启用手动按钮，不是启用自主规划或无人值守运行。每次有副作用的操作都要在界面确认；后端要求宿主登录态、明确的操作请求、同源检查和固定版本来源校验，随后仍调用原来的质量/预算门禁。

服务器的 env_file 固定绑定目标项目与 Board；HTTP 请求不能更换该文件、项目路径、测试命令或注入任意 shell 命令。模型通过上述明确的配置接口管理。测试命令只能由操作员在部署配置中预先设置。

**原 P0 限制没有被界面解决：**实际费用/模型调用次数硬限额、在途执行级总时限仍未完整实现；Gateway 服务级恢复与生产部署仍需专门验证。设置有限费用上限时，旧版后端仍拒绝继续。Chief/PM、Playbook 和长期自治仍未启用。

只读开关仅约束本插件；Hermes 原生 Dashboard 的 Chat、终端、配置等其他功能仍沿用其原权限。宿主登录目前是操作员级信任，不是新增多租户或分角色权限系统。不要把 operator receipt 目录挂入 Worker。

## 已安装 v0.22.5 的 Linux 电脑

默认 in-process 模式支持只读与受控写入；安装步骤和范围见 [本地 v0.22.5 接入](LOCAL_HERMES_V0225.md)。部署、升级、回滚脚本仍锁定 v0.18.2，不能直接套用到 v0.22.5。

## 在另一套 Hermes v0.18.2 安装中使用

前提是已验证的 Hermes v0.18.2 固定基线，并具备该安装的原生 Dashboard 前端与 FastAPI 依赖。使用那套 Hermes 的 Python：

```bash
"$hermes_python" scripts/install-workflow-app.py \
  --home /path/to/hermes-home \
  --env /path/to/deploy.env \
  --enable
```

非 Git 安装可加 `--archive /path/to/verified-baseline.tar.gz`，供后端沿用原来的逐文件来源校验。安装器复制插件与现有 P0 控制模块，使用原生 enable 并保留其他设置；不运行部署、升级、模型或 Docker。再次安装会保留 config.json，检测到本地修改过的受管代码时拒绝覆盖。未知插件目录也不会被替换。

从相同 HERMES_HOME 启动原生 Dashboard；如果它已在运行，在你选择的时机重新启动**该 Dashboard 进程**以加载新的 API，不需要为此重启 Gateway。原始四角色、模型配置、干净目标项目和已有 Board 仍是提交/执行的前提。文档中的示意截图来自隔离测试数据。

## 从源码准备前端资源

固定源码归档未包含 `hermes_cli/web_dist` 时，先建立独立源码副本并切换到副本目录，再执行：

```bash
npm ci --workspace web --include-workspace-root=false --no-audit --no-fund --cache /path/to/npm-cache
npm run build --workspace web
```

npm ci 使用上游 package-lock，保留 TLS 与 integrity 校验；TypeScript 和 Vite 生产构建均通过。输出位于独立副本的 `hermes_cli/web_dist`，通过官方 HERMES_WEB_DIST 运行时覆盖使用，未改实际 Hermes 源文件或锁文件。

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

# 复用固定官方源码中已经准备好的 React/jsdom 开发依赖，无需给本项目另装一套。
HERMES_FRONTEND_SOURCE=/path/to/pinned-hermes-source node --test tests/workflow_dashboard.test.cjs
```

2026-10-30 本轮工作流优化：16 项组件回归通过，63 项 Python 回归通过。真实本地 Dashboard 验证了中英文、阻塞定位、1/4 与 4/4 进度、验收证据、轮询保留页签，以及 1280px / 390px 布局；两种宽度均未发现横向溢出。并发和网络失败由组件测试注入；未执行真实 Worker、模型调用或 Docker。

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
