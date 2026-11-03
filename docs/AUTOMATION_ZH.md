# 自动化与决策：少点按钮，只做关键判断

网页「工作流」现在以单一项目架构师对话作为入口。一个会话可关联多个任务，系统进展、建议与决策卡显示在同一时间线上；任务列表及证据位于右侧抽屉。旧会话只读保留。决策必须在卡片按钮及确认窗口中生效，自然语言不能触发授权、验收、整改或拒绝。

通知链接携带卡片编号，打开后定位当前或历史卡片。处理结果会原位显示，旧按钮被后端拒绝。已有的自动验收策略保持原范围，不因架构师建议而扩大。

飞书双向联动尚待下一阶段；当前的自定义机器人 Webhook 仍只发送通知。应用机器人、群及审批人配置完成后，才进行真实飞书验证。

默认行为不变：每轮执行都要你批准，交付也要你确认。下面三项设置能把你从流水线中间撤出来，只在需要拍板时出现。三项都写在项目绑定的 `deploy.env` 里，改完后重启 Dashboard 和 Gateway。

## 1. 授权范围内自动验收

```bash
WORKFLOW_AUTO_ACCEPT=true
WORKFLOW_AUTO_ACCEPT_MAX_FILES=20
WORKFLOW_DECISION_PATHS=billing/*,src/payments/*
```

开启后，一轮执行同时满足以下条件时，直接记为 `ACCEPTED`，不再等你点击：

- 平台在断网容器里跑完项目测试和独立测试，全部通过；
- Reviewer 没有报告阻断问题（`blocker`）；
- 改动没有碰到下表中的任何一类。

下表中的改动始终交给你决定，卡片和网页会列出具体文件：

| 类别 | 匹配示例 |
|---|---|
| 数据库结构或迁移 | `migrations/`、`*.sql`、`schema.prisma`、`alembic/` |
| CI、部署或权限配置 | `.github/`、`Dockerfile`、`docker-compose*`、`deploy/`、`k8s/`、`*.tf`、`CODEOWNERS` |
| 密钥或凭据 | `.env*`、`*.pem`、`*.key`、`*secret*`、`*credential*` |
| 新增或升级依赖 | `package.json`、各类 lock 文件、`requirements*.txt`、`pyproject.toml`、`go.mod`、`Cargo.toml` |
| 删除文件 | 任何被删除的文件 |
| 操作员指定的路径 | `WORKFLOW_DECISION_PATHS` 中的 glob |
| 改动过多 | 改动文件数超过 `WORKFLOW_AUTO_ACCEPT_MAX_FILES` |

自动验收和人工验收走同一套校验。候选版本、内容摘要、平台测试回执和日志哈希都必须一致，否则不会验收。验收记录里的 `accepted_by` 会写明是 `policy` 还是 `operator`。

这些设置在创建任务时就固定到该任务上，之后改 `deploy.env` 不会扩大已有任务的授权范围。

开始执行前的那次批准仍然保留，去掉的只是交付时的确认。

## 2. 飞书决策卡片

```bash
FEISHU_WEBHOOK_URL=https://open.feishu.cn/open-apis/bot/v2/hook/xxxx
FEISHU_WEBHOOK_SECRET=        # 机器人开启签名校验时填写
WORKFLOW_DASHBOARD_URL=http://127.0.0.1:9119
```

在飞书群里添加自定义机器人，把它的 Webhook 地址填进来。只有以下三种情况会推送卡片：

- 等待你确认交付，卡片会列出需要你决定的改动；
- 审查发现阻断问题，需要你批准修复；
- 有角色被阻塞，或执行环境未就绪。

每个决策点只推一次。卡片上有 Agent 的建议和“去工作台处理”按钮，点击后直接打开对应任务。你在工作台里批准、修改或点“不做了”之后，Agent 会接着往下执行。

推送失败只记在执行记录的 `notifications` 字段里，不会阻塞工作流。Webhook 地址相当于密钥，不要提交到 Git；它也不会出现在日志里。

目前的卡片只负责通知和跳转，决定仍要在 Dashboard 里做，因为那里有登录校验。如果要在卡片里直接点按钮，需要一个公网能访问的飞书应用回调地址，这和本项目“不开放网络端口”的原则冲突，所以没有做。

## 3. 决策记录：同样的问题不问第二遍

你做过的决定会连同原话和日期，追加到这两份文件：

```text
$HERMES_HOME/workflow/decisions/<board>/approved.md   已定的事
$HERMES_HOME/workflow/decisions/<board>/rejected.md   定了不做的事
```

- 确认交付时填的备注、你批准的敏感改动、“提出修改”时写的意见，会写入 `approved.md`。
- 点“不做了”并写下原因后，任务会停止，原因写入 `rejected.md`。

总控对话和每个新任务的方案卡都会读取这两份文件。遇到已经定过的问题，Agent 直接按记录处理。如果新需求和“定了不做”的记录冲突，Agent 会引用你当时的原话，请你确认是否推翻。

两份文件都可以直接编辑。它们放在操作员目录下，不在项目仓库里，因为工作流要求源项目保持干净。

## 审查严重度

Reviewer 的每条问题都要标注 `blocker` 或 `minor`：

- `blocker`：会出错、违反验收标准、丢数据或暴露密钥。只有这一类会打回修改。
- `minor`：真实存在但不阻断的问题，只记录在案。

代码风格和“可以写得更好”的建议不算问题，不会上报。平台按严重度判定审查结论：如果 Reviewer 自己写的 `verdict` 和严重度对不上，以严重度为准。判断“同一问题是否重复出现”时只比较阻断问题，所以改改次要问题的措辞绕不过整改上限。旧格式的纯文本问题没有严重度，沿用 Reviewer 报告的结论。

Reviewer 保留 web 工具，工具集没有变化。

## 接入包

`downloads/` 里的接入包是在这次改动之前构建的，不包含以上功能。可以用源码安装器更新插件，或者重新打包：

```bash
python3 scripts/install-workflow-app.py --home "$HERMES_HOME" --env ./deploy.env
python3 scripts/package-local-app.py --help
```
