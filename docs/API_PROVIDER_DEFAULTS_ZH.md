# 主流模型 API 地址与格式

核对日期：2026-10-30。地址与协议依据下列厂商官方文档；实际推理由 Hermes 原生适配器完成。模型编号从原生模型目录刷新，不在网页另建模型白名单。

## 直接使用

1. 在模型选择弹窗中选择厂商。
2. 粘贴 API Key，点击底部固定的「导入密钥并获取模型」。内置厂商不必填写模型名称或 API 地址。
3. 从刷新后的列表选择模型，点击「切换」。辅助任务、多模型协作还需保存外层配置。

「高级设置」保留自定义地址、协议和模型入口。已有同厂商密钥可留空沿用。保存 Key 后使用主动刷新接口，避免新凭据仍读到旧缓存的空模型列表。读取模型目录不发起推理；原生目录可能包含厂商推荐候选，不能把候选展示当作供应商已验证账户权限。

## 内置默认值

| 厂商 / 接入地区 | API 基础地址 | 请求格式 | 官方依据 |
| --- | --- | --- | --- |
| OpenAI API | `https://api.openai.com/v1` | Responses | [OpenAI Docs](https://developers.openai.com/api/docs/quickstart) |
| Anthropic / Claude | `https://api.anthropic.com` | Anthropic Messages | [Claude API](https://platform.claude.com/docs/en/api/overview) |
| Google Gemini | `https://generativelanguage.googleapis.com/v1beta` | Gemini generateContent | [Gemini API](https://ai.google.dev/api/models) |
| OpenRouter | `https://openrouter.ai/api/v1` | OpenAI Chat Completions | [OpenRouter](https://openrouter.ai/docs/quickstart) |
| DeepSeek | `https://api.deepseek.com/v1` | OpenAI Chat Completions | [DeepSeek](https://api-docs.deepseek.com/en/) |
| 通义千问：海外 | `https://dashscope-intl.aliyuncs.com/compatible-mode/v1` | OpenAI Chat Completions | [阿里云百炼](https://help.aliyun.com/zh/model-studio/compatibility-of-openai-with-dashscope) |
| 通义千问：中国 | `https://dashscope.aliyuncs.com/compatible-mode/v1` | OpenAI Chat Completions | [阿里云百炼](https://help.aliyun.com/zh/model-studio/compatibility-of-openai-with-dashscope) |
| Kimi 开放平台：海外 | `https://api.moonshot.ai/v1` | OpenAI Chat Completions | [Kimi 接入区别](https://www.kimi.com/en/help/kimi-code/faq) |
| Kimi 开放平台：中国 | `https://api.moonshot.cn/v1` | OpenAI Chat Completions | [Kimi 接入区别](https://www.kimi.com/en/help/kimi-code/faq) |
| Z.AI：国际站 | `https://api.z.ai/api/paas/v4` | OpenAI Chat Completions | [Z.AI API](https://docs.z.ai/api-reference/introduction) |
| 智谱：中国站 | `https://open.bigmodel.cn/api/paas/v4` | OpenAI Chat Completions | [智谱 HTTP API](https://docs.bigmodel.cn/cn/guide/develop/http/introduction) |
| MiniMax：海外 | `https://api.minimax.io/anthropic` | Anthropic Messages | [MiniMax](https://platform.minimax.io/docs/api-reference/text-anthropic-api) |
| MiniMax：中国 | `https://api.minimaxi.com/anthropic` | Anthropic Messages | Hermes 原生中国站配置；[MiniMax 格式](https://platform.minimax.io/docs/api-reference/text-anthropic-api) |
| xAI / Grok | `https://api.x.ai/v1` | OpenAI Responses | [xAI Responses](https://docs.x.ai/developers/rest-api-reference/inference/responses) |

智谱提供「Z.AI 国际站 / 智谱中国站」预设，使用原生 `GLM_BASE_URL` 配置，无需创建自定义连接或先填写模型编号。通义、Kimi、MiniMax 的地区通过各自厂商项选择。百炼官方同时提供业务空间专属域名，现有 DashScope 域名仍可使用；Key 需与地域匹配。专属域名可在高级设置填写。[阿里云说明](https://help.aliyun.com/zh/model-studio/compatibility-of-openai-with-dashscope)

Kimi 开放平台 Key 与 Kimi Code 会员 Key 对应不同接口。Code 的 OpenAI 兼容地址为中国 `https://api.kimi.com/coding/v1`、海外 `https://api.kimi.ai/coding/v1`，可经自定义连接接入。[Kimi 官方模型配置](https://www.kimi.com/en/help/kimi-code/models)

## 请求格式

以下是接口形状说明，`MODEL_ID` 使用目录返回的编号。认证、流式事件和工具调用继续由原生运行时处理。

| 格式 | HTTP 路径（相对基础地址） | 最小 JSON 形状 |
| --- | --- | --- |
| OpenAI Responses | `POST /responses` | `{"model":"MODEL_ID","input":"你好"}` |
| OpenAI Chat Completions | `POST /chat/completions` | `{"model":"MODEL_ID","messages":[{"role":"user","content":"你好"}]}` |
| Anthropic Messages | `POST /v1/messages` | `{"model":"MODEL_ID","max_tokens":1024,"messages":[{"role":"user","content":"你好"}]}` |
| Gemini generateContent | `POST /models/MODEL_ID:generateContent` | `{"contents":[{"parts":[{"text":"你好"}]}]}` |

OpenAI 兼容接口使用 Bearer Key。Claude 支持 Bearer Key，也继续支持原生适配器使用的 `x-api-key`，并要求 API 版本头；Gemini 由原生 Google SDK 注入 Key。协议不是同一个请求体，选择厂商后由其适配器处理。[OpenAI 认证](https://developers.openai.com/api/reference/overview)、[Claude 认证](https://platform.claude.com/docs/en/api/overview)、[Gemini 模型接口](https://ai.google.dev/api/models)

本轮已完成配置流程、主动刷新、模型选择和构建检查；未使用用户密钥发起真实模型推理。
