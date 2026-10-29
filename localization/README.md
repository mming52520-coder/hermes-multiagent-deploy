# 原生网页的简体中文补充

`dashboard-zh.patch` 基于 Hermes v0.22.5 官方提交 `bf0203a794a07aac3ff764972ab9087baa4e4f4e`，补充原生翻译中缺少的导航、页头提示和配对等名称，以及手机端提示正文的换行。工作流页面本身的中文在 plugins/workflow 中。

本次未在用户或已验证的后端安装上打补丁。构建使用独立源码副本，保留原生 API、认证、统计共享选择、插件流程和版本门禁。页头共享选项仅翻译文字，仍由用户选择，不自动启用。

重新构建时：

1. 从该固定提交准备独立源码副本，保留原始安装。
2. 在副本根目录执行 `patch -p1 < /path/to/dashboard-zh.patch`。
3. 使用 Hermes PM 准备受管 Python/Node/npm，并通过原生 `source_build.prepare_source_dependencies` 准备 web 工作区的冻结依赖；依赖既可能位于根 node_modules，也可能位于 web/node_modules，不能只复制根目录。
4. 通过原生 `source_build.build_source_web` 构建，它会强制执行 TypeScript 检查与受限并行构建；不跳过错误、不修改锁文件、不执行 audit fix --force。
5. 用本项目的 `scripts/package-local-app.py --hermes-source /path/to/translated-copy --output /path/to/new-package.tar.gz` 打包。输出路径必须不存在。脚本添加中文标题和首次语言初始化，其余内容来自白名单；不打包凭据、部署环境文件或用户状态。

交付包已含构建结果，本机使用者无需执行以上开发步骤。首次加载默认简体中文，之后保留原生语言菜单中的选择；如果浏览器禁止本地存储，可在原生语言菜单手动选中文。
