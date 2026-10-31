# Linux 中文工作流：Hermes v0.22.5

保留已有 Hermes，不需要降级。接入包包含已构建前端，默认简体中文，页眉「中文 / English」可即时切换并保留选择。模型编号、用户内容、命令、路径和原始日志保留原文。[按钮与按键说明](WORKFLOW_APP_BUTTONS_ZH.md) 解释完整操作。

本版支持「创建研发目标 → 人工审批 → 启动多 Agent」。安装器仍默认只读；操作员显式开放后，创建和审批可以先完成，启动必须通过依赖检查。此前“v0.22.5 写入未适配”的结论仅适用于旧包。

## 安装和启动

取得 downloads 中的 `hermes-workflow-local-v0225-zh-CN.tar.gz` 和 SHA-256，校验后解压。安装器只用标准库，不手动给受管环境装包。以下采用标准数据根；自定义安装选择对应目录。PROJECT_DIR 应是目标项目的干净 Git 副本，BOARD_SLUG 选择对应看板。

```bash
export HERMES_HOME="${HERMES_HOME:-$HOME/.hermes}"
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

打开终端输出的回环地址，选择「工作流」。不分享带会话凭据的 URL。升级插件时重跑安装器：它保护未知同名插件、本地代码修改及 config.json，保留项目绑定。只重启自己的 Dashboard 实例，不批量停止其他服务。

## 开放人工操作

先在绑定文件中设置 OUTPUT_DIR、DOCKER_IMAGE、WORKFLOW_TEST_COMMAND。输出目录与源项目、共享 Kanban、操作员记录必须分离。网页不能提供任意命令。例如：

```dotenv
PROJECT_DIR=/absolute/path/to/clean-project
BOARD_SLUG=default
OUTPUT_DIR=/absolute/path/to/separate-artifacts
DOCKER_IMAGE=your-prepared-project-test-image
WORKFLOW_TEST_COMMAND=python -m unittest discover -s tests
WORKFLOW_MAX_SECONDS=7200
WORKFLOW_MAX_RUNS=12
WORKFLOW_MAX_REPAIR_ROUNDS=2
WORKFLOW_MAX_COST_USD=
```

镜像需预先包含项目测试依赖；验证容器没有网络，也不会自动安装依赖。测试命令应按项目实际情况选择。实际费用硬上限尚未实现，设置 WORKFLOW_MAX_COST_USD 会阻止执行，不把估算当账单。

操作员在 `$HERMES_HOME/plugins/workflow/config.json` 将 `allow_actions` 设为 `true`，保留其他字段。安装源码必须精确匹配已审计提交 `bf0203a794a07aac3ff764972ab9087baa4e4f4e` 且无跟踪文件修改；非 Git 安装需指定 `--archive`，核对归档哈希和全部文件。只改版本字符串或操作开关不能绕过来源检查。

工作流主界面直接显示「四个 Agent · 统一模型配置」，不再逐个打开角色弹窗。在四行内分别选择厂商、粘贴 Key，点击「获取全部模型」（也可单行「获取模型」），从各自列表选择模型后，统一点击「保存模型配置」。每个角色的厂商、Key 和模型独立保存；API 地址与协议自动填入。「快捷操作：一套配置应用全部」可把同一厂商与 Key 填到四行，随后仍可逐行修改。

支持 OpenAI、Anthropic、Google Gemini、阿里云百炼、智谱 GLM、Kimi、MiniMax、OpenRouter 等原生连接；选项随原生目录更新。自定义接口可选择 OpenAI Chat Completions、OpenAI Responses、Anthropic Messages。内置厂商协议交给 Hermes 处理，不增加 LiteLLM 等网关依赖。

不同厂商直连需要各自的 Key。希望一把 Key 选择多家模型时，可使用 OpenRouter 等聚合服务。Key 经宿主认证接口保存到本机对应 Profile 的私有 .env，配置文件只引用 key_env；网页不回传 Key，不写浏览器本地存储，也不挂入 Worker 容器。

导入时把 Key 保存到各自基础角色并读取模型目录，尚不改变所选模型。统一保存才应用模型选择；勾选「同步到当前未启动目标」会同步修改角色的目标快照并撤销旧审批。已启动目标不改连接。首次配置可创建缺少的原生角色。读取目录只发起列表请求；厂商不提供实时列表时明确显示推荐目录，不把它当作供应商已验证 Key。

原生「选择模型」弹窗（主模型、辅助任务、多模型协作）也提供「配置 API / 密钥」：内置厂商只需粘贴 Key，点击底部固定的「导入密钥并获取模型」，随后从主动刷新的目录中选择模型并点「切换」。辅助任务或多模型协作还需在外层弹窗保存对应配置。官方默认地址与请求格式直接显示，智谱国际站 / 中国站使用地区预设切换。完整[地址、格式与官方来源](API_PROVIDER_DEFAULTS_ZH.md)。

「高级设置」保留自定义地址、协议和模型；左侧也可「新增自定义 API」。自定义地址会保存为独立连接。已有同厂商密钥留空时保留。表单顶部显示当前配置档；四个研发角色通过工作流统一配置区管理。ChatGPT / Codex 订阅使用账号授权，弹窗提供账号入口与 OpenAI API Key 接入入口。

页面检查干净源版本、输出与镜像配置、Docker daemon、测试命令、费用策略、四角色和原生 Gateway 接口。没有 Docker 或角色凭据时仍可创建、审批，启动保持禁用。供应商是否接受凭据、镜像测试依赖及真实推理需要实际验证。

## 操作顺序

1. 「新建目标」填写范围和验收标准，建立四个原生待审批任务，不启动 Worker。
2. 查看目标和源版本，点击「人工审批」并勾选确认。弹窗列出目标、版本和轮次；过期轮次确认会被拒绝。审批不释放任务或调用模型。
3. 准备项全部就绪后，点击「启动多 Agent」并再次确认。后端按需连接/启动原生 Gateway，调用原生原子调度器；重复启动不会重复领取同一任务。
4. 调查、开发按依赖执行。开发完成后，人工「准备独立审查」冻结副本，随后执行独立审查、验证和质量验收。新整改轮次需重新审批。

列表、详情和证据每 20 秒同步，也可手动刷新。任务完成不等于验收合格，不自动提交、推送、建 PR 或部署。

## 项目与运行环境

Dashboard 的访问地址以启动终端输出为准，在该地址打开 `/workflow`。建议使用独立数据根，并将项目绑定到已提交版本的干净 Git 副本；模型凭据、目标记录和执行输出保留在自己的运行目录，不放入源代码仓库。

四个角色可在同一主界面分别配置厂商、Key 和模型。按 Docker 官方说明安装并启动 Docker，为项目准备包含测试依赖的镜像，然后创建目标、同步角色配置并人工审批。已启动的目标保留自己的配置快照；新配置可用于后续目标。

## 验证和边界

- 63 项旧版回归、21 项工作流组件测试通过。
- `tests/check_workflow_writes_v0225.py` 的 10 项检查使用真实 v0.22.5 数据库、Profile 和 HTTP 接口，覆盖创建、审批不放行、鉴权/同源/确认、依赖不足不放行、原生领取及防重复、过期轮次确认、绑定数据根和双版本来源门禁。调度测试使用短生命周期进程替代推理 Worker，Gateway 启动使用测试替身。
- 真实本地浏览器已创建一条「界面验证（未启动）」目标，检查四阶段待审批、审批范围与未勾选禁用、启动禁用、准备项双语，以及 1280px / 390px 布局；没有横向溢出或浏览器错误。审批弹窗已取消，未产生真实运行。
- 模型接入更新：63 项旧版回归、20 项组件测试和 4 项原生配置/HTTP 检查通过，覆盖一 Key 应用全部、单角色覆盖、独立凭据存储、Key 留空沿用、目标同步与重新审批、首次创建角色。真实界面已检查四卡片、厂商切换、自定义协议及手机表单；没有用推理调用测试配置功能。
- 原生模型选择弹窗的直接接入：44 项相关前端检查通过，随后仅补跑原生 custom 行的 1 项新增检查；严格 TypeScript / Vite 构建通过。定向 ESLint 无错误，ChatSidebar 原有导出形式仍有 1 项 Fast Refresh 警告。实际浏览器已打开多模型协作选择器，确认 OpenAI Key 表单、自定义协议与中文提示；没有在真实配置中填写密钥或发起推理。
- 原生前端复用上一轮通过 454 项测试、严格 TypeScript/Vite 构建和上游 12 项检查的资源；本轮不改原生前端源码或锁文件。
- 统一模型配置的 6 项原生行为检查覆盖独立凭据、实时目录请求、批量保存、目标同步与重新审批及 Gemini 分页；这些配置检查不调用真实模型推理。
- 接入包使用独立 BUILD_INFO 和 MANIFEST.sha256，排除含构建机路径的原生编译缓存记录，不包含运行目标、业务源码、凭据或用户状态。
- Gateway 服务级恢复和总预算硬停止尚未完成验证；P0 仍 PARTIAL_PASS，P1/P2 未启用。软件流程验证不代替各项目自己的生产验收。原先报告的 npm 告警未通过强制升级处理。

旧版部署/升级/回滚脚本继续锁定 v0.18.2；工作流层支持两个精确审计基线，不能将旧部署流程用于 v0.22.5。本插件的只读开关只约束自身，原生 Chat、终端和配置沿用 Hermes 权限。
