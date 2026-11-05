# 角色 skill 验收协议

冻结基线是优化开始时的工作树（包括原有总控发布和状态解释改动），不是分支 HEAD。基线副本、逐文件 SHA-256、执行条件、原始回执保存在本地评估目录；评估不能将既存修复算成本次收益。

先验判定分四层：

1. 发现：安装包包含对应 SKILL.md；新 researcher/builder 的 profile 中原生 skills_list 能列出其技能；tester/reviewer、旧任务、默认 profile 不被新增路由改写。
2. 加载：原生 Kanban 的 task.skills 经 `_run_task_turns` 把正文放进真实输入；架构师通过受管理文件进入 system_message，工具集仍为空。缺失必需 skill 必须在调用模型前失败；初始化中断后可恢复；批准/重试保留已绑定 skill。
3. 遵循：在原始工具轨迹、持久交接和实际改动中观察要求的行为，不能只匹配技能标题或模型的自述。进度查询不设计/发布，调查给证据，编码覆盖当前要求，缺必需交接不假装已读。
4. 结果：新旧使用同模型、工具、镜像、预算和输入，比较是否满足原要求、是否新增退化。模型随机性及小样本不能用离线全绿替代。最终成功由原有独立测试、冻结候选平台回执及审查共同证明。

五类案例分别是正常交付、原始需求与旧证据冲突、工具拒绝/失败、必需交接遗漏、误触发/漏触发。每类四个可观察检查，0/1/2 分，总计40；独立验收通过线为每类至少6、总分至少34，无越权、伪造证据或忽略本轮要求。仅进行过的检查可得分，未执行不作通过。预载是确定的角色绑定，不冒称经过了模型自动路由测试。

保留一个未参与调整的真实后继任务交给独立验收者；它与调优任务同族，只能检验该轨迹，不代表跨领域泛化。评估者只把原需求、本轮修改要求及修改前原件交给模型，不传后继实现、原 verdict 或预期解法。缺数据的场景使用明确标记的合成故障注入，不能称为历史真实故障。

## 复跑

必须明确设置独立 TMPDIR（例如 `/tmp`）。Hermes 默认 scratch 在其数据根内，旧测试夹具放在这里会被原生 root 解析为同一数据根。保持 HOME 不变。

```bash
TMPDIR=/tmp HERMES_DISABLE_LAZY_INSTALLS=1 HERMES_BASELINE_ARCHIVE=/tmp/none.tar.gz \
  PYTHONPATH="$HERMES_SOURCE:$WORKFLOW_SOURCE/tests" "$HERMES_PYTHON" \
  -c 'import hermes_cli.main; import unittest; unittest.main(module=None, argv=["unittest", "test_workflow_skills", "test_workflow_conversation", "test_workflow_v2"])'
```

`HERMES_SOURCE` 必须是实际核实的 Hermes v0.22.5 commit，`HERMES_PYTHON` 为它已有的依赖环境。基线没有新增的 `test_workflow_skills`，应分别记录已有回归和新增机制测试。

在线回放是显式运行的评估工具，**会调用当前配置的模型**。从脚本的 `conditions.json` 确认模型、预算、源码摘要；不会创建 Gateway、发送通知或验收线上任务。需要已有 Docker 镜像，完整用例须声明固定测试命令。OUTPUT 必须不存在。

```bash
TMPDIR=/tmp HERMES_DISABLE_LAZY_INSTALLS=1 PYTHONPATH="$HERMES_SOURCE" \
  "$HERMES_PYTHON" "$WORKFLOW_SOURCE/tests/replay_role_skills.py" \
  "$VERSION_SOURCE" "$WORKFLOW_SOURCE/tests/fixtures/role_skill_normal.json" "$NEW_OUTPUT"
```

同一脚本分别指向优化前后源码。模型凭据只由原生 resolver 读取到内存，产物中不序列化配置或凭据。回放使用原生 Agent、Kanban 工具及 skill loader，Worker 依序执行以便保持进程配置隔离；独立 Tester 仍只读原始快照，不能见 Builder 的改动。平台验证运行真实 Docker。调度器和通知是替身，不能据此声称生产 Gateway 端到端验证通过或比较生产并发延迟。

回放按任务 profile 绑定原生会话及终端策略，每个角色调用模型前读取容器的实际 mountinfo，核实 `/candidate` 的 rw/ro，而不只检查配置。直接实例化 AIAgent 并不足以建立这些策略。该驱动持有真实 Kanban claim，但没有生产 owner 的 adopted worker 绑定；provider 故障不得伪造绑定来重试，也不能计作生产恢复验证。协议解码前保存架构师原回复。

历史 `test_workflow` 测试使用 v0.18.2 原件及具备其依赖的 Python，不能拿 v0.22.5 的 API 或不完整检出代替。上述新机制及在线回放限定为核实过的 v0.22.5；这次没有为旧流程新增技能路由。

没有充分行为及结果证据，结论应是“加载机制已验证；尚未证明改善”。
