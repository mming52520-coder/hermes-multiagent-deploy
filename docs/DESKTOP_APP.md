# Linux 桌面应用

应用名为「多 Agent 工作流」。点击桌面图标或应用菜单入口，会检查并启动后台网关和工作流网页服务，再在独立窗口中打开总控台。再次点击会唤起已有窗口。关闭窗口后，后台服务和任务继续运行。

此入口适配已有的 Hermes v0.22.5 工作流安装，使用系统 Python 3、GTK 3 与 WebKitGTK 4.1。它保留现有项目绑定、模型、登录、权限和任务数据；不安装或覆盖角色 skill、SOUL、工作流插件或前端。当前是本机 Linux 入口，不是包含 Hermes、模型和依赖的跨平台安装包。

## 安装与启动

前提：`hermes` 已在 `PATH` 中，工作流插件已安装，中文前端已构建，系统 `/usr/bin/python3` 可导入 `gi`、`Gtk 3.0` 和 `WebKit2 4.1`。

从仓库根目录运行，`HERMES_WEB_DIST` 指向当前实际使用的前端目录：

```bash
HERMES_HOME="$HOME/.hermes" HERMES_WEB_DIST="/absolute/path/to/web_dist" \
  /usr/bin/python3 scripts/install-workflow-desktop.py
gtk-launch local.hermes.Workflow
```

安装器复用现有 `HERMES_HOME`、`HERMES_WEB_DIST` 和 PATH 中的 Hermes 启动器，记录在用户配置目录，不新增 Hermes CLI 参数。安装后日常只需点击图标。桌面环境若未接受信任标记，可右键图标选择「允许启动」，应用菜单入口也可直接启动。

- 应用文件：`$XDG_DATA_HOME/hermes-workflow-desktop`，默认 `~/.local/share/hermes-workflow-desktop`。
- 启动配置：`$XDG_CONFIG_HOME/hermes-workflow-desktop/config.json`，默认 `~/.config/hermes-workflow-desktop/config.json`，仅记录三个安装路径。
- 应用菜单：`~/.local/share/applications/local.hermes.Workflow.desktop`（遵循 `XDG_DATA_HOME`）。桌面快捷方式遵循 `xdg-user-dir DESKTOP`。
- 诊断日志：`$XDG_STATE_HOME/hermes-workflow-desktop`，默认 `~/.local/state/hermes-workflow-desktop`。失败页面可打开启动日志；新启动网页服务的输出在同目录 `dashboard.log`。

## 启动契约

1. 使用 `hermes --profile default gateway ensure --json --timeout 60`。由原生运行机制处理进程归属、配置、权限、启动和冲突。不会主动重启运行中的网关。原生 `draining/restart_wait` 仍允许打开界面，供用户处理正在等待的审批。
2. 使用原生 `/api/health` 与 `/api/status`，核对实际运行 commit 及当前数据根的 `install_id`。只有连接被拒绝才视为网页服务未启动。其他程序占用端口、版本不匹配、错误响应都显示诊断，不替换原服务。
3. 缺少网页服务时，用同一 Hermes 启动器执行 `dashboard --host 127.0.0.1 --port 9119 --skip-build --no-open`；沿用安装时记录的前端目录，设 `HERMES_DESKTOP=0`。在最多 60 秒内等待可验证的就绪状态，超时后保留诊断和仍在启动的进程，重试时复用。
4. GTK Application 的会话总线单实例机制处理重复点击。服务在独立进程会话中运行，窗口退出不会终止任务。窗口的「重新连接」按钮重新检查服务；「在浏览器中打开」使用系统浏览器访问同一工作流。

窗口使用独立的用户浏览器存储，保留自己的登录会话。若原服务要求登录，按原页面完成登录，不读取或复制其他浏览器的登录凭据。

## 验证与参考

```bash
python3 -m unittest discover -s tests -p 'test_workflow_desktop.py' -v
desktop-file-validate "$HOME/.local/share/applications/local.hermes.Workflow.desktop"
# 可选真实冷启动：使用临时数据根、独立宿主锁目录和空闲端口；不发送模型任务。
python3 tests/desktop_native_smoke.py
```

针对性测试覆盖已有服务复用、缺少服务时的启动、启动就绪判定、网关失败、旧版本、保留审批、端口冲突、跨数据目录误接入、启动失败诊断、超时重试复用，以及含空格/中文路径的安装。

2026-11-06 在 Ubuntu 24.04 / GNOME X11 / GTK 3 / WebKitGTK 2.52.6 上，10 项针对性测试通过；隔离数据根中的真实 Hermes 网关和网页服务完成冷启动、再次启动复用及清理。原桌面入口通过实际启动与重复点击检查，总控台及已有待审批卡片正常显示。已有网关、网页服务的 PID 保持不变，25 个已安装插件文件和插件配置的散列保持不变。

首轮隔离验证仅改变数据根，原生宿主注册仍发现已有服务并正确拒绝另占端口；复跑增加原生 `HERMES_GATEWAY_LOCK_DIR` 隔离，生产入口不改变此设置。桌面复测发现 GDK 默认选中 4.0，与 GTK 3 冲突，现显式要求 GDK 3.0，并已通过最终入口复测。未验证 Windows/macOS、系统重启登录周期及所有 OAuth 厂商；未重新执行模型交付质量评估。真实冷启动使用最小网页夹具，当前工作流页面另在实际桌面窗口核验。

接口依据：[Hermes v0.22.5 对应提交的原生网关 ensure](https://github.com/NousResearch/hermes-agent/blob/bf0203a794a07aac3ff764972ab9087baa4e4f4e/hermes_cli/gateway_runtime_cli.py) 和 [Dashboard 参数](https://github.com/NousResearch/hermes-agent/blob/bf0203a794a07aac3ff764972ab9087baa4e4f4e/hermes_cli/subcommands/dashboard.py)（MIT）。窗口采用已安装的 GTK 3；异步更新参考 [GNOME PyGObject 的 Application 示例](https://github.com/GNOME/pygobject/blob/63dd29bb3063e165a54da149457efa82004060b6/docs/guide/download_callback.py)（LGPL-2.1，示例是 GTK 4，仅参考主循环更新模式）。未复制第三方实现或新增 Python/npm 依赖。
