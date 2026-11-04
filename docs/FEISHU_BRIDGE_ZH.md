# 总控台对话的飞书双向联动

适用环境为同机、同一 Hermes 数据根的 v0.22.5 Dashboard 和原生 Gateway，插件按默认 in-process 模式加载。一个应用机器人绑定一个项目群。群里和网页共享当前项目及看板的「总控台对话」。成员可以讨论，审批人可以在原决策卡上提交决定。

## 在本机接入

1. 创建企业自建应用，启用机器人能力。准备应用的 App ID、App Secret、测试群的 `oc_…` 群 ID，以及在该应用下取得的 `ou_…` 人员 open_id。先用测试项目和群做验收。[飞书开发者后台](https://open.feishu.cn/app)
2. 为应用申请接收群内 @ 机器人的消息、以应用身份发消息、更新本应用消息所需权限。接收群内所有消息取决于应用另获的权限和 Hermes 的群策略，使用默认设置时请在群里 @ 机器人。[消息权限与事件](https://open.feishu.cn/document/uAjLw4CM/ukTMukTMukTM/reference/im-v1)
3. 在安装了 B 阶段代码的分支或接入包根目录执行以下命令。使用运行 Dashboard 与 Gateway 的同一个 `HERMES_HOME`。第一条命令更新已有工作流插件并备份旧插件。首次安装见本项目的本地 v0.22.5 安装说明。

   ```bash
   bash update-workflow-plugin.sh
   hermes pm install --extra feishu
   bash scripts/configure-feishu-bridge.sh
   hermes gateway restart
   ```

4. 配置脚本会在本机终端隐藏 App Secret 的输入。最后可以选择发送一张无任务操作的测试卡，默认跳过发送。已通过 Hermes 配置好同一应用时可回车沿用。工作台地址填能从飞书客户端打开的 Dashboard 基址，例如在同一台电脑上使用 `http://127.0.0.1:9119`。手机的回环地址指向手机自身，应填手机已能访问的工作台地址。最后按原方式重启同一数据根的 Dashboard，保留原端口、前端资源及认证配置。
5. 在应用后台将**事件订阅**与**回调订阅**都配置为长连接，分别订阅 `im.message.receive_v1` 和 `card.action.trigger`。保存配置、发布版本，再将应用机器人加入绑定群。若控制台要求先检测到长连接，先按上一步启动已配置凭据的 Gateway，再回到控制台保存。首次配置时若机器人尚未入群，先跳过测试卡。入群后可重运行配置脚本，重新填入需要的对话成员，最后选 `y` 发送。[长连接回调说明](https://open.feishu.cn/document/event-subscription-guide/callback-subscription/receive-and-handle-callbacks)

原生 `.env` 保存 `FEISHU_APP_ID`、`FEISHU_APP_SECRET`、`FEISHU_CONNECTION_MODE=websocket`。脚本将本次成员和审批人并入原生 `FEISHU_ALLOWED_USERS`。项目群、人员权限和工作台地址从插件 `config.json` 指定的 env 文件读取。

| 配置 | 用途 |
|---|---|
| `WORKFLOW_FEISHU_CHAT_ID` | 接管的唯一项目群 |
| `WORKFLOW_FEISHU_APPROVERS` | 可点决策按钮的 open_id，以逗号分隔 |
| `WORKFLOW_FEISHU_MEMBERS` | 可发起讨论的 open_id，以逗号分隔。留空时等于审批人列表 |
| `WORKFLOW_DASHBOARD_URL` | 飞书卡片上的网页跳转基址 |

两个配置文件及备份文件的权限为 600，备份目录权限为 700。配置脚本会打印私有备份目录。需要换群或更换应用时，先停止对应 Gateway、Dashboard，再重配并启动。若已有部署使用自定义信任策略，确保该群及测试成员已通过原生准入。应用和工作流两层权限都必须允许。

网页的受控操作开关 `allow_actions`、原生会话认证、固定 Hermes 来源校验和预算仍生效。讨论需要可用的 Hermes 主模型。要走完真实研发和交付，请先在工作台确认四个角色的模型连接、项目输出位置、测试用 Docker 镜像和固定测试命令均已就绪。

## 本机验收

| 操作 | 两端应看到的结果 |
|---|---|
| 已发布应用且启用操作后，审批人点击可选测试卡的「测试按钮」 | 机器人引用原测试卡回复「联动正常」。这一步不创建任务、不调用模型 |
| 成员在绑定群 @ 机器人发送一条新需求 | 网页出现「飞书 · 姓名」消息，群里收到一次总控台回复。群里原消息不再回发 |
| 在网页继续提问 | 群里出现「你（网页）」和总控台回复。网页仍在同一会话讨论 |
| 在网页核对草案，点击「生成任务卡」 | 新任务处于待审批。群里出现一张进度卡及一张决策卡。点击「在网页中打开」能定位原卡 |
| 输入「可以」或手打 `/card button …` | 普通聊天和粘贴命令均不会批准任何工作。请从卡片按钮操作 |
| 用非成员 @ 机器人，再用非审批人点击决策按钮 | 非成员消息不触发模型。非审批人点击收到无权限提示，任务仍待审批 |
| 审批人在卡片点「批准并开始」并确认 | 网页原卡变为飞书决定，记录姓名、时间和动作。任务推进后同一条进度消息原位更新 |
| 等待测试与审查通过，选择一项需要手动验收的交付，在飞书点「确认验收」 | 网页显示已验收的结论，能在抽屉核对原有验收凭据。AI 回复引用了卡片且该卡片已送达时，群里回复会引用该条消息 |
| 对另一个待决定任务在网页「提出修改」或「不做了」并填写原因 | 飞书原卡移除决策按钮并显示网页结论和原话。飞书卡片上的修改、修复和拒绝也要求原因 |
| 两端同时点一张卡，或从旧客户端再次点击 | 同一决定只执行一次。重复决定提示「已处理」，过期决定提示刷新，旧卡保留结论或显示已过期 |
| 在隔离测试环境断开飞书网络，再从网页处理一张卡 | 网页操作和凭据正常完成。恢复网络且原生 owner 后台推进启用时，后续 tick 重试未完成的卡片同步 |

飞书断网时，讨论记录仍可在网页会话库中查看。单条聊天转发失败会记录诊断，恢复后可从网页继续讨论。卡片同步另有持久回执及重试。飞书只接受 14 天内的消息 PATCH，返回 230031 后会记下该消息已关闭更新，实时状态以网页为准。已有 Webhook 的安装在未绑定应用或未提供应用凭据时继续按原规则发送单向通知。[飞书卡片更新限制](https://open.feishu.cn/document/server-docs/im-v1/message-card/patch)

## 实施前核实与验证范围

- 核对固定版本的 `gateway/run_startup.py`、`hermes_cli/plugins.py`、`plugins_dispatch.py` 与 `gateway/run_inbound_hooks.py`。Gateway 会加载插件，`pre_gateway_dispatch` 接受异步和同步钩子，返回 skip 会消费该事件。此钩子位于原生授权之前，因此桥接会另行核对成员、审批人、原生准入和暂停状态。[Hermes 固定源码](https://github.com/NousResearch/hermes-agent/tree/bf0203a794a07aac3ff764972ab9087baa4e4f4e)
- 固定的 FeishuAdapter 将通用按钮合成为 COMMAND，保留原始 SDK 对象、操作人 open_id、原消息及群 ID。普通群消息可能以 tenant user_id 为主身份，权限检查使用原始消息中应用范围的 open_id。适配器会处理首尾的机器人提及。在无法确认逐条发送人的共享话题合并消息中，工作流提示成员重发单条消息。[适配器](https://github.com/NousResearch/hermes-agent/blob/bf0203a794a07aac3ff764972ab9087baa4e4f4e/plugins/platforms/feishu/adapter.py)
- 核对官方 `lark-oapi==1.6.8` 发行包与 SHA-256。按钮的 `action.value` 提供工作流卡号和动作，`action.form_value["reason"]` 提供表单原话。原始卡片消息必须匹配已保存的发送回执。文本内容无法伪装成回调。[SDK](https://pypi.org/project/lark-oapi/1.6.8/) · [回调字段](https://open.feishu.cn/document/feishu-cards/card-callback-communication)
- 通用按钮由适配器立即返回空响应对象，SDK 的 WebSocket 通道以成功响应序列化。飞书协议允许保留当前卡片，toast 和 card 均为可选字段。本实现待决定完成后 PATCH 共享卡片。是否在实际客户端出现超时或错误提示，由上表的本机按钮步骤验证。[回调响应](https://open.feishu.cn/document/feishu-cards/card-callback-communication)
- 固定 `pyproject.toml` 的 feishu extra 指定 `lark-oapi==1.6.8`。安装命令来自 Hermes 自带的 `pm.extras.install_hint`。REST 客户端使用 Python 标准库，令牌提前五分钟刷新，凭据只发送给选定的飞书或 Lark 官方域名。
- 飞书要求更新前后的卡片都显式设置 `update_multi: true`。新建消息使用确定的投递 UUID，服务端对相同 UUID 的创建请求提供一小时去重窗口。[发送消息](https://open.feishu.cn/document/server-docs/im-v1/message/create) · [更新消息卡片](https://open.feishu.cn/document/server-docs/im-v1/message-card/patch)

本地通过 174 项 Python 回归（含 23 项飞书专项）、62 项前端测试和独立的原生只读挂载检查。在隔离项目中，测试经 Hermes 原生飞书适配器和已注册的 Gateway 钩子进入审批，用原生会话库、看板与验收逻辑核对两端结果。另用真实终端验证了 App Secret 不回显及备份权限。测试中的飞书网络和模型由替身提供。真实企业应用的订阅、群权限、客户端交互和网络地址由上述本机步骤验收。

## 回滚

停止对应 Gateway 和 Dashboard。要仅关闭双向联动，在绑定 env 中移除 `WORKFLOW_FEISHU_CHAT_ID` 再启动服务。需还原配置时，使用配置脚本打印的同一次私有备份，将 `workflow-app.env` 和存在的 `hermes.env` 恢复至各自原路径，权限保持 600。若配置前没有原生 `.env`，仅移除本次新加的飞书项。需要回滚插件时，恢复更新脚本备份的插件目录。保留任务 manifest、原生数据库、决定记录和会话历史。
