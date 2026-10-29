# Linux 中文网页接入：保留已安装的 Hermes v0.22.5

用户已确认 Ubuntu/Debian 上 Hermes v0.22.5 的版本和帮助命令通过，无需重复安装或降级。本次适配在云端独立目录验证，尚未连接或修改用户电脑。

中文包首次打开默认使用原生简体中文，之后保留你在语言菜单中的选择。工作流页顶部新增「使用说明与按键」；完整按钮、键盘和状态说明见 [中文操作说明](WORKFLOW_APP_BUTTONS_ZH.md)。命令、路径和原始日志保留原文。

包内前端还补齐了原生「文件、频道、事件回调、设备配对、系统管理、任务看板、成就」导航和页头提示的中文。翻译补丁放在 localization 目录，只用于构建独立前端，不改本机 Hermes 后端或依赖锁文件。

## 验证范围

| 能力 | 结论 |
|---|---|
| 官方 v0.22.5 Dashboard、原生插件加载、前端 SDK | PASS，真实 Chromium 验证 |
| 认证、执行列表、四阶段状态、详情、证据查看 | PASS，真实原生 DB，默认 in-process 插件模式 |
| 默认只读、拒绝创建和执行操作 | PASS，拒绝后没有新增任务 |
| 原 v0.18.2 工作流回归 | PASS，47 tests / 20.604s |
| v0.22.5 提交、授权、Worker、整改、验收写入 | **未适配、未开放**；保留原 v0.18.2 源码门禁 |
| plugins.isolation: host、多 Profile 并行、真实模型和 Docker Worker | NOT_TESTED |

修复了只读路由加载时不必要的 PyYAML 依赖、状态查询对旧连接接口的依赖，补齐原生插件 register 入口。状态查询使用 SQLite mode=ro，不创建或迁移原生 DB。没有更换任务 DB、调度器或 Provider。

不要将 config.json 的 allow_actions 改为 true 强行接入写入。只读模式仅约束本插件；原生 Dashboard 的 Chat、终端和配置仍沿用 Hermes 自己的权限。

## 安装只读插件

从仓库 downloads 目录下载接入包，解压后进入包内目录，使用 Python 3.10 或更新版本。交付包包含本次验证的 v0.22.5 中文前端 web_dist，可直接复用，无需在本机重新运行 npm 构建。安装器只用标准库，不手动给 Hermes 环境装包。源码和接入包随同一分支提供，main 是否已合并以 GitHub 当前分支为准。

以下采用标准 ~/.hermes；自定义安装请使用对应数据根。把示例 PROJECT_DIR 换成本机项目的真实绝对路径，BOARD_SLUG 使用已有看板的 slug。没有工作流 manifest 时显示空列表是正常状态。

```bash
export HERMES_HOME="${HERMES_HOME:-$HOME/.hermes}"

# 仅首次创建；已有文件保留，请编辑它来选择项目与看板。
if [ ! -e workflow-app.env ]; then
  printf 'PROJECT_DIR=%s\nBOARD_SLUG=default\n' /absolute/path/to/project > workflow-app.env
  chmod 600 workflow-app.env
fi

python3 scripts/install-workflow-app.py \
  --home "$HERMES_HOME" --env "$PWD/workflow-app.env"

hermes plugins enable workflow --no-allow-tool-override
export HERMES_WEB_DIST="$PWD/web_dist"
HERMES_DESKTOP=0 hermes dashboard --host 127.0.0.1 --skip-build --no-open
```

打开 Hermes 在终端输出的本机地址，选择「工作流」。安装器保护同名未知插件和本地代码改动、保留 config.json；原生 enable 可能由 Hermes PM 同步受管依赖。不要用裸 pip/uv 改动受管环境。

如已安装旧版，使用原数据根目录重新运行安装器，再将 HERMES_WEB_DIST 指向新中文包。原项目绑定配置的路径会保留，仍在使用的旧绑定文件请保留；安装器不会擅自改写它。

已有 Dashboard 需要在你选择的时机重启该实例加载更新，不需要重启 Gateway，也不要用 --stop 批量停止其他实例。

v0.22.5 缺少默认 web_dist 时，即使带 --skip-build 也可能尝试一次恢复构建。若要严格复用已有前端，请将 HERMES_WEB_DIST 设为本机现成的 v0.22.5 构建目录；自定义目录缺少 index.html 时启动会拒绝。不要复用本工作区 v0.18.2 的前端缓存。

## 模型、Docker 和安全告警

只读查看不需要模型登录或 Docker。使用聊天或以后执行 Worker 时，若模型还未配置，再运行 `hermes setup`；已配置则保留现有设置，不重复登录。不要把 Key 或 token 发到聊天中。

Worker 前可检查：

```bash
docker --version
docker info --format '{{.ServerVersion}}'
```

第二条成功才表示当前用户能访问 Docker daemon。依赖只读诊断可用 `hermes pm doctor`。程序和 Docker 可以在本机运行；原项目的 Packy/DeepSeek 仍通过网络 API 推理。

用户报告的官方 npm 告警，其具体影响范围未在本次确认；未执行 `npm audit fix --force`、未改上游锁文件，也不声称已修复。

不要对已有 v0.22.5 运行本仓库旧版 bootstrap/deploy/upgrade/restore，或放宽版本校验。原 P0 的费用/模型调用硬限额、在途总时限、真实隔离和恢复的限制仍保留。

## 验证依据

- 官方稳定标签 v0.22.5：`bf0203a794a07aac3ff764972ab9087baa4e4f4e`；归档 SHA-256：`0dc2cca54657d162845a77f634e107c61c3fb0bd6c8505212aa2e200591b7cc9`。
- 独立官方 PM / Python 3.14.9 / 数据根 / 工具目录，保留锁文件和 TLS/哈希校验。官方前端经 source_build 构建，未使用旧版静态资源。
- `tests/check_workflow_readonly.py` 覆盖原生插件启用/加载、认证和只读 API；`tests/browser_workflow_readonly.cjs` 覆盖真实新版前端/SDK、四阶段、证据、移动布局和页面错误。
- 初测确认缺少 PyYAML、连接接口移动和缺少 register 入口，修复后复测通过。空测试 home 的 CLI 因没有 PM 安装状态被拒绝；测试改用原生 Dashboard enable helper，没有绕过 PM 保护。
- 云端连接已恢复。可选浏览器工具下载因 cdn.playwright.dev 网络策略被拒绝；未改变策略，网页验证使用现有 Chromium。这不代表可选工具安装成功。
- 验证过程中没有运行真实部署、Worker、模型调用或生产服务变更；代码提交与推送不等于应用已部署到本机或云端。
