#!/usr/bin/env python3
from __future__ import annotations

import os
import re
import stat
import sys
from pathlib import Path
from typing import Any

import yaml


PROFILES = ("orchestrator", "researcher", "builder", "reviewer")

CUSTOM_PROVIDERS: dict[str, dict[str, str]] = {
    "custom:packy-claude": {
        "name": "packy-claude",
        "base_url_env": "PACKY_CLAUDE_BASE_URL",
        "key_env": "PACKY_CLAUDE_API_KEY",
        "api_mode": "anthropic_messages",
    },
    "custom:packy-codex": {
        "name": "packy-codex",
        "base_url_env": "PACKY_CODEX_BASE_URL",
        "key_env": "PACKY_CODEX_API_KEY",
        "api_mode": "codex_responses",
    },
    "custom:packy-deepseek": {
        "name": "packy-deepseek",
        "base_url_env": "PACKY_DEEPSEEK_BASE_URL",
        "key_env": "PACKY_DEEPSEEK_API_KEY",
        "api_mode": "chat_completions",
    },
    "custom:packy-cc-sale": {
        "name": "packy-cc-sale",
        "base_url_env": "PACKY_CC_SALE_BASE_URL",
        "key_env": "PACKY_CC_SALE_API_KEY",
        "api_mode": "anthropic_messages",
    },
}

BUILTIN_PROVIDERS: dict[str, str] = {
    "deepseek": "DEEPSEEK_API_KEY",
}

MODEL_SECRET_KEYS = {
    "OPENROUTER_API_KEY",
    "PACKY_CLAUDE_API_KEY",
    "PACKY_CODEX_API_KEY",
    "PACKY_DEEPSEEK_API_KEY",
    "PACKY_CC_SALE_API_KEY",
    "DEEPSEEK_API_KEY",
}

PLACEHOLDER_FRAGMENTS = (
    "replace-with-",
    "replace-me",
    "your-key",
    "your-token",
)


def load_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, val = line.split("=", 1)
        value = val.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        values[key.strip()] = value
    values.update({k: v for k, v in os.environ.items() if v is not None})
    return values


def is_placeholder(value: str) -> bool:
    lowered = value.strip().lower()
    return not lowered or any(fragment in lowered for fragment in PLACEHOLDER_FRAGMENTS)


def as_int(env: dict[str, str], key: str, default: int) -> int:
    raw = env.get(key, str(default))
    try:
        return int(raw)
    except ValueError as exc:
        raise ValueError(f"{key} 必须为整数") from exc


def validate_env(env_path: Path, env: dict[str, str]) -> list[str]:
    errors: list[str] = []

    required = (
        "HERMES_USER",
        "PROJECT_SLUG",
        "BOARD_SLUG",
        "BOARD_NAME",
        "PROJECT_DIR",
        "OUTPUT_DIR",
        "BACKUP_DIR",
        "DOCKER_IMAGE",
    )
    for key in required:
        if not env.get(key, "").strip():
            errors.append(f"{key}: missing")

    user = env.get("HERMES_USER", "")
    if user and not re.fullmatch(r"[a-z_][a-z0-9_-]*", user):
        errors.append("HERMES_USER: invalid Linux username")

    for key in ("PROJECT_DIR", "OUTPUT_DIR", "BACKUP_DIR"):
        value = env.get(key, "")
        if value and not value.startswith("/"):
            errors.append(f"{key}: must be an absolute path")

    try:
        mode = stat.S_IMODE(env_path.stat().st_mode)
        if mode & 0o077:
            errors.append(
                f"deploy.env: permissions too broad ({oct(mode)}), require 0600"
            )
    except OSError as exc:
        errors.append(f"deploy.env: cannot stat ({exc})")

    allowed = set(CUSTOM_PROVIDERS) | set(BUILTIN_PROVIDERS)

    for profile in PROFILES:
        prefix = profile.upper()
        provider_key = f"{prefix}_PROVIDER"
        model_key = f"{prefix}_MODEL"
        context_key = f"{prefix}_CONTEXT_LENGTH"

        provider = env.get(provider_key, "").strip()
        model = env.get(model_key, "").strip()

        if not provider:
            errors.append(f"{provider_key}: missing")
        elif provider not in allowed:
            errors.append(
                f"{provider_key}: unsupported provider {provider!r}; "
                f"allowed={sorted(allowed)}"
            )

        if is_placeholder(model):
            errors.append(f"{model_key}: missing or placeholder")

        try:
            context = as_int(env, context_key, 0)
            if context < 0:
                errors.append(f"{context_key}: must be >= 0")
        except ValueError as exc:
            errors.append(str(exc))

        if provider in CUSTOM_PROVIDERS:
            spec = CUSTOM_PROVIDERS[provider]
            base_key = spec["base_url_env"]
            secret_key = spec["key_env"]
            if not env.get(base_key, "").strip():
                errors.append(f"{base_key}: missing")
            if is_placeholder(env.get(secret_key, "")):
                errors.append(f"{secret_key}: missing or placeholder")
        elif provider in BUILTIN_PROVIDERS:
            secret_key = BUILTIN_PROVIDERS[provider]
            if is_placeholder(env.get(secret_key, "")):
                errors.append(f"{secret_key}: missing or placeholder")

    return errors


def deep_merge(base: dict[str, Any], patch: dict[str, Any]) -> dict[str, Any]:
    for key, value in patch.items():
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            deep_merge(base[key], value)
        else:
            base[key] = value
    return base


def read_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return data if isinstance(data, dict) else {}


def write_yaml(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".yaml.tmp")
    tmp.write_text(
        yaml.safe_dump(data, sort_keys=False, allow_unicode=True, width=1000),
        encoding="utf-8",
    )
    tmp.replace(path)
    path.chmod(stat.S_IRUSR | stat.S_IWUSR)


def upsert_dotenv(
    path: Path,
    updates: dict[str, str],
    *,
    remove_keys: set[str] | None = None,
) -> None:
    existing: dict[str, str] = {}
    order: list[str] = []

    if path.exists():
        for raw in path.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            existing[key] = value
            order.append(key)

    for key in remove_keys or set():
        existing.pop(key, None)
        if key in order:
            order.remove(key)

    existing.update(updates)
    for key in updates:
        if key not in order:
            order.append(key)

    lines = [f"{key}={existing[key]}" for key in order if key in existing]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    path.chmod(stat.S_IRUSR | stat.S_IWUSR)


def profile_model_config(
    profile: str,
    env: dict[str, str],
) -> tuple[dict[str, Any], list[dict[str, Any]], dict[str, str]]:
    prefix = profile.upper()
    provider = env[f"{prefix}_PROVIDER"].strip()
    model = env[f"{prefix}_MODEL"].strip()
    context_length = as_int(env, f"{prefix}_CONTEXT_LENGTH", 0)

    model_cfg: dict[str, Any] = {
        "provider": provider,
        "default": model,
    }
    if context_length > 0:
        model_cfg["context_length"] = context_length

    custom_entries: list[dict[str, Any]] = []
    secrets: dict[str, str] = {}

    if provider in CUSTOM_PROVIDERS:
        spec = CUSTOM_PROVIDERS[provider]
        custom_entries.append(
            {
                "name": spec["name"],
                "base_url": env[spec["base_url_env"]].strip(),
                "key_env": spec["key_env"],
                "api_mode": spec["api_mode"],
            }
        )
        secrets[spec["key_env"]] = env[spec["key_env"]]
    else:
        secret_key = BUILTIN_PROVIDERS[provider]
        secrets[secret_key] = env[secret_key]

    return model_cfg, custom_entries, secrets


def main() -> int:
    if len(sys.argv) not in {2, 3}:
        print(
            "usage: configure_profiles.py deploy.env [--validate-only]",
            file=sys.stderr,
        )
        return 2

    env_path = Path(sys.argv[1]).expanduser().resolve()
    validate_only = len(sys.argv) == 3 and sys.argv[2] == "--validate-only"

    if not env_path.exists():
        print(f"错误：找不到 {env_path}", file=sys.stderr)
        return 1

    env = load_env_file(env_path)
    errors = validate_env(env_path, env)
    if errors:
        print("CONFIG INVALID", file=sys.stderr)
        for error in errors:
            print(f"- {error}", file=sys.stderr)
        return 1

    print("CONFIG VALID")
    print("- provider/model keys are present")
    print("- secret values were not displayed")
    if validate_only:
        return 0

    home = Path.home()
    root = home / ".hermes"
    project_dir = Path(env["PROJECT_DIR"]).resolve()
    output_dir = Path(env["OUTPUT_DIR"]).resolve()
    kanban_root = root / "kanban"
    docker_image = env["DOCKER_IMAGE"]

    tools_by_profile = {
        "orchestrator": [
            "kanban", "memory", "session_search", "todo", "clarify", "skills"
        ],
        "researcher": [
            "web", "file", "terminal", "skills", "todo", "memory",
            "session_search", "delegation"
        ],
        "builder": [
            "web", "file", "terminal", "skills", "todo", "memory",
            "session_search", "delegation", "code_execution"
        ],
        "reviewer": [
            "web", "file", "terminal", "skills", "todo", "memory",
            "session_search"
        ],
    }

    souls_dir = Path(__file__).resolve().parents[1] / "souls"

    for profile in PROFILES:
        profile_home = root / "profiles" / profile
        config_path = profile_home / "config.yaml"
        data = read_yaml(config_path)
        tools = tools_by_profile[profile]

        # Remove stale endpoint data from the prior OpenRouter-only bundle.
        model_section = data.get("model")
        if isinstance(model_section, dict):
            for stale_key in ("base_url", "api_key", "api_mode"):
                model_section.pop(stale_key, None)
        data.pop("custom_providers", None)

        model_cfg, custom_entries, model_secrets = profile_model_config(profile, env)

        common: dict[str, Any] = {
            "model": model_cfg,
            "platform_toolsets": {"cli": list(tools)},
            # Required by the current Kanban orchestrator tool gate.
            "toolsets": list(tools),
            "approvals": {
                "mode": "smart",
                "timeout": 60,
                "cron_mode": "deny",
                "mcp_reload_confirm": True,
                "destructive_slash_confirm": True,
                "deny": [
                    "git push --force*",
                    "git push -f*",
                    "*curl*|*sh*",
                    "*wget*|*sh*",
                ],
            },
            "updates": {
                "pre_update_backup": True,
                "backup_keep": 3,
                "non_interactive_local_changes": "stash",
            },
            "display": {
                "tool_progress": "all",
                "interim_assistant_messages": True,
                "long_running_notifications": True,
            },
        }
        if custom_entries:
            common["custom_providers"] = custom_entries

        if profile == "orchestrator":
            common["platform_toolsets"]["telegram"] = list(tools)
            common["terminal"] = {
                "backend": "local",
                "cwd": str(project_dir),
                "home_mode": "profile",
                "timeout": 180,
            }
            common["gateway"] = {"multiplex_profiles": False}
            common["kanban"] = {
                "dispatch_in_gateway": True,
                "dispatch_interval_seconds": as_int(
                    env, "DISPATCH_INTERVAL_SECONDS", 15
                ),
                "auto_decompose": False,
                "auto_promote_children": False,
                "orchestrator_profile": "orchestrator",
                "default_assignee": "orchestrator",
                "max_in_progress": as_int(env, "MAX_IN_PROGRESS", 2),
                "max_in_progress_per_profile": as_int(
                    env, "MAX_IN_PROGRESS_PER_PROFILE", 1
                ),
                "failure_limit": 2,
                "dispatch_stale_timeout_seconds": 14400,
            }
            common["delegation"] = {
                "max_iterations": 15,
                "max_concurrent_children": 1,
                "max_spawn_depth": 1,
                "orchestrator_enabled": False,
                "child_timeout_seconds": 900,
                "inherit_mcp_toolsets": False,
            }
        else:
            project_mount = f"{project_dir}:{project_dir}"
            if profile == "researcher":
                project_mount += ":ro"
                memory_mb = as_int(env, "RESEARCHER_MEMORY_MB", 3072)
                max_iterations = 20
            elif profile == "builder":
                memory_mb = as_int(env, "BUILDER_MEMORY_MB", 6144)
                max_iterations = 35
            else:
                memory_mb = as_int(env, "REVIEWER_MEMORY_MB", 4096)
                max_iterations = 25

            common["terminal"] = {
                "backend": "docker",
                "cwd": str(project_dir),
                "home_mode": "profile",
                "timeout": 900,
                "docker_image": docker_image,
                "docker_mount_cwd_to_workspace": False,
                "docker_run_as_host_user": True,
                "docker_network": True,
                "docker_env": {
                    "CI": "1",
                    "PYTHONUNBUFFERED": "1",
                },
                "docker_volumes": [
                    project_mount,
                    f"{kanban_root}:{kanban_root}",
                    f"{output_dir}:{output_dir}",
                ],
                "container_cpu": as_int(env, "WORKER_CPU", 2),
                "container_memory": memory_mb,
                "container_persistent": True,
                "docker_persist_across_processes": True,
                "docker_orphan_reaper": True,
            }
            if profile == "builder":
                common["terminal"]["docker_env"].update(
                    {
                        "GIT_AUTHOR_NAME": "Hermes Builder",
                        "GIT_AUTHOR_EMAIL": "hermes-builder@localhost",
                        "GIT_COMMITTER_NAME": "Hermes Builder",
                        "GIT_COMMITTER_EMAIL": "hermes-builder@localhost",
                    }
                )

            common["delegation"] = {
                "max_iterations": max_iterations,
                "max_concurrent_children": 2,
                "max_spawn_depth": 1,
                "orchestrator_enabled": False,
                "child_timeout_seconds": 1800,
                "subagent_auto_approve": False,
                "inherit_mcp_toolsets": False,
            }

        deep_merge(data, common)
        write_yaml(config_path, data)

        dotenv_updates: dict[str, str] = {
            **model_secrets,
            "HERMES_KANBAN_RATE_LIMIT_COOLDOWN_SECONDS": "120",
            "HERMES_KANBAN_CLAIM_TTL_SECONDS": "1800",
        }

        if profile in {"researcher", "reviewer"}:
            for key in ("EXA_API_KEY", "PARALLEL_API_KEY", "FIRECRAWL_API_KEY"):
                value = env.get(key, "")
                if value:
                    dotenv_updates[key] = value

        if profile == "orchestrator":
            for key in ("TELEGRAM_BOT_TOKEN", "TELEGRAM_ALLOWED_USERS"):
                value = env.get(key, "")
                if value:
                    dotenv_updates[key] = value

        upsert_dotenv(
            profile_home / ".env",
            dotenv_updates,
            remove_keys=MODEL_SECRET_KEYS,
        )

        soul_src = souls_dir / f"{profile}.md"
        if not soul_src.exists():
            raise SystemExit(f"缺少 SOUL 模板：{soul_src}")
        soul_dst = profile_home / "SOUL.md"
        soul_dst.write_text(soul_src.read_text(encoding="utf-8"), encoding="utf-8")
        soul_dst.chmod(stat.S_IRUSR | stat.S_IWUSR)

    print("已写入四个 Profile 的 config.yaml、最小权限 .env 和 SOUL.md。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
