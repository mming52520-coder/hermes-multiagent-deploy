# PackyAPI + DeepSeek 官方配置

## 默认路由

| Profile | 渠道 | Hermes provider | API 模式 | 模型 |
|---|---|---|---|---|
| orchestrator | PackyAPI `claude-officially` | `custom:packy-claude` | `anthropic_messages` | `claude-sonnet-4-6` |
| researcher | DeepSeek 官方 | `deepseek` | OpenAI 兼容 Chat Completions | `deepseek-v4-pro` |
| builder | PackyAPI `codex` | `custom:packy-codex` | `codex_responses` | `gpt-5.2` |
| reviewer | PackyAPI `claude-officially` | `custom:packy-claude` | `anthropic_messages` | `claude-sonnet-4-6` |

## 为什么没有默认使用另外两个 Packy Token

- `deepseek-officially`：你已有 DeepSeek 官方 Key，直接连接官方接口更简单，
  少一层中转。
- `cc-sale`：PackyAPI 文档提示该分组缓存可能异常，所以只保留为备用入口。

## 只需填写三个完整密钥

编辑 `deploy.env`：

```bash
PACKY_CLAUDE_API_KEY=完整的 claude-officially Token
PACKY_CODEX_API_KEY=完整的 codex Token
DEEPSEEK_API_KEY=完整的 DeepSeek 官方 Key
```

截图中的密钥经过掩码，无法从截图恢复。不要把完整密钥发到聊天中。

## 模型 ID 的最终核对

PackyAPI 的分组决定可用模型。部署前打开“模型广场”：

1. 选择 `claude-officially`，确认 `claude-sonnet-4-6` 存在；
2. 选择 `codex`，确认 `gpt-5.2` 存在；
3. 若实际 ID 不同，只修改 `deploy.env` 中对应 `*_MODEL`。

DeepSeek 官方当前推荐：

```text
deepseek-v4-flash
deepseek-v4-pro
```

旧的 `deepseek-chat` 和 `deepseek-reasoner` 将在 2026-07-24 弃用。

## 先独立验证接口

填写密钥并执行：

```bash
chmod 600 deploy.env
python3 scripts/configure_profiles.py deploy.env --validate-only
python3 scripts/check-model-apis.py deploy.env
```

预检对每个唯一 provider/model 发送一个极小请求，会产生极少量费用；
成功时不打印模型回复，失败时输出已脱敏的错误。

## 生成后的关键配置

Orchestrator / Reviewer：

```yaml
custom_providers:
  - name: packy-claude
    base_url: https://www.packyapi.com
    key_env: PACKY_CLAUDE_API_KEY
    api_mode: anthropic_messages

model:
  provider: custom:packy-claude
  default: claude-sonnet-4-6
  context_length: 200000
```

Builder：

```yaml
custom_providers:
  - name: packy-codex
    base_url: https://www.packyapi.com/v1
    key_env: PACKY_CODEX_API_KEY
    api_mode: codex_responses

model:
  provider: custom:packy-codex
  default: gpt-5.2
```

Researcher：

```yaml
model:
  provider: deepseek
  default: deepseek-v4-pro
  context_length: 1000000
```

对应 Profile 的 `.env` 只会获得它实际使用的模型密钥，不会把全部密钥复制给所有
Agent。
