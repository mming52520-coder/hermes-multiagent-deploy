# Source baseline

This deployment bundle was checked against:

- Repository: `NousResearch/hermes-agent`
- Commit: `aaf5691261f12601db845386d650dce1cdfa30f9`
- Commit date: 2026-07-13
- Deployment model: one Orchestrator gateway plus dispatcher-spawned Profile workers

Compatibility decisions:

1. `platform_toolsets` is written for current per-platform tool configuration.
2. A top-level `toolsets` list is also written because the current Kanban
   orchestrator gate still checks that key directly.
3. Kanban auto-decomposition and goal mode are disabled in the initial production
   configuration.
4. Every generated task has an explicit runtime limit and retry limit.
5. Dashboard access is localhost-only.


## Provider compatibility supplement

Provider configuration was additionally checked against:

- DeepSeek official API documentation, 2026-07-13:
  - OpenAI base URL: `https://api.deepseek.com`
  - current models: `deepseek-v4-flash`, `deepseek-v4-pro`
  - Hermes setup: provider `DeepSeek`, model `deepseek-v4-pro`
- PackyAPI documentation, updated 2026-07-09:
  - Claude/Hermes endpoint: `https://www.packyapi.com`
  - Claude wire mode: `Anthropic Messages`
  - Codex endpoint: `https://www.packyapi.com/v1`
  - Codex wire mode: `Responses`
- Hermes named custom-provider schema:
  `custom_providers[].{name,base_url,key_env,api_mode}` and
  `model.provider: custom:<name>`.
