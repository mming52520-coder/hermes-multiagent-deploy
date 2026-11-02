# Source baseline

This deployment bundle was checked against:

- Repository: `NousResearch/hermes-agent`
- Commit: `aaf5691261f12601db845386d650dce1cdfa30f9`
- Commit date: 2026-07-13
- Deployment model: one Orchestrator gateway plus dispatcher-spawned Profile workers

## P0 reproducibility contract

The supported runtime remains v0.18.2 at the exact commit above. The installation
wrapper now downloads that commit's installer, verifies its SHA-256
`c2e4326c1660bd45f64321996eb15bda35e7a4649e32a310495a61972a2804c8`, and passes
the upstream-supported `--commit` option. An existing installation is checked
before API preflight, configuration generation, or service setup. A version
string alone is insufficient: `scripts/hermes_baseline.py` requires a clean
source checkout at that commit, or verifies every archived source file against
the exact source archive (SHA-256
`34f9eedb7215eb9768b6f8289d0284e01fa467c86228ac7e5b6054fc8698e628`).

The old unpinned `hermes update` path is no longer used. See
`docs/MULTIAGENT_WORKFLOW_P0.md` for explicit reinstall/upgrade/rollback policy.
Neither installer nor upgrade/deployment services were executed during this
offline change. Existing user installations remain unchanged.

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
