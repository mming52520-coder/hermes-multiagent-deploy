# Linux 中文工作流接入包

适用于已经安装 Hermes v0.22.5 的电脑，包含已构建的中文网页前端、工作流插件、安装器、许可证和中文操作说明。新版支持创建研发目标、人工审批、启动入口和四个 Agent 独立的厂商、模型、API 与 Key 配置。安装默认只读，按包内说明绑定项目并显式启用操作；真实执行需要 Docker 和有效模型凭据。

下载本目录的 `.tar.gz` 和对应 `.sha256` 文件，在相同目录执行：

```bash
sha256sum -c hermes-workflow-local-v0225-zh-CN.tar.gz.sha256
tar -xzf hermes-workflow-local-v0225-zh-CN.tar.gz
cd hermes-workflow-local
```

随后按包内 README 安装。保留已有 Hermes 版本、数据根目录和配置；无需在本机重新运行 npm 构建。程序与容器本地运行不代表模型在本地推理。

原 `hermes-workflow-local-readonly-v0225-zh-CN.tar.gz` 为上一版只读包，保留供原安装使用。

源码安装步骤与范围：[本地接入说明](../docs/LOCAL_HERMES_V0225.md)。

界面和按钮：[中文操作说明](../docs/WORKFLOW_APP_BUTTONS_ZH.md)。

包内无 deploy.env、模型凭据、Git 元数据或用户状态。逐文件哈希在包内 MANIFEST.sha256；统计共享选项仍由用户选择，不自动启用。
