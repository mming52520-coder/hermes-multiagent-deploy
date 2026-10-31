"""Model onboarding for workflow roles, using Hermes' provider catalog and credential writer."""
from __future__ import annotations

from pathlib import Path

if __package__:
    from .configure_profiles import read_yaml
else:
    from configure_profiles import read_yaml

ROLES = ("researcher", "builder", "reviewer", "orchestrator")


def catalog() -> list[dict]:
    from hermes_cli.auth import PROVIDER_REGISTRY
    from hermes_cli.provider_catalog import provider_catalog
    from hermes_cli.models import get_preferred_silent_default_model, pick_silent_default_model
    from hermes_cli.models_catalog_static import _PROVIDER_MODELS
    from hermes_cli.model_catalog import get_curated_openrouter_models
    from providers import get_provider_profile
    from hermes_cli.providers import get_provider

    rows = []
    for entry in provider_catalog():
        if entry.auth_type != "api_key" or not entry.api_key_env_vars or entry.slug == "custom":
            continue
        profile = get_provider_profile(entry.slug)
        models = list(_PROVIDER_MODELS.get(entry.slug, [])) or list(profile.fallback_models if profile else [])
        if entry.slug == "openrouter":
            curated = get_curated_openrouter_models()
            if curated:
                models = [mid for mid, _ in curated]
            default = get_preferred_silent_default_model("openrouter")
            models = list(dict.fromkeys([default, *models]))
        elif models:
            default = pick_silent_default_model(models, provider=entry.slug)
        else:
            continue
        native = PROVIDER_REGISTRY.get(entry.slug)
        base_url = profile.base_url if profile else native.inference_base_url
        definition = get_provider(entry.slug)
        protocol = profile.api_mode if profile else definition.transport if definition else "native"
        if protocol == "openai_chat":
            protocol = "chat_completions"
        if entry.slug == "gemini":
            protocol = "gemini"
        rows.append({"id": entry.slug, "label": entry.label, "models": models,
                     "default_model": default, "base_url": base_url, "protocol": protocol,
                     "key_env": entry.api_key_env_vars[0], "signup_url": entry.signup_url})
    rows.sort(key=lambda row: (row["id"] != "openrouter", row["label"].casefold()))
    for row in rows:
        if row["id"] == "zai":
            row["regions"] = [{"label": "Z.AI 国际站 API", "base_url": row["base_url"]},
                              {"label": "智谱中国站 API", "base_url": "https://open.bigmodel.cn/api/paas/v4"}]
    rows.append({"id": "custom", "label": "自定义兼容 API", "models": [], "default_model": "",
                 "base_url": "", "protocol": "chat_completions", "key_env": "HERMES_WORKFLOW_API_KEY",
                 "signup_url": ""})
    return rows


def credential_fields(provider: str) -> tuple[str, ...]:
    from hermes_cli.provider_catalog import provider_catalog
    return next((entry.api_key_env_vars for entry in provider_catalog() if entry.slug == provider), ())


def _provider(provider: str) -> dict:
    row = next((item for item in catalog() if item["id"] == provider), None)
    if row is None:
        raise ValueError("请选择当前 Hermes 支持的模型厂商。")
    return row


def _profile_key(profile: str, key_env: str) -> str:
    from hermes_cli.config import load_env
    from hermes_cli.web_server_profiles import _config_profile_scope

    with _config_profile_scope(profile):
        return load_env().get(key_env, "")


def discover(role: str, *, provider: str, api_key: str = "", base_url: str = "",
             protocol: str = "chat_completions") -> dict:
    """Import one role's key, then read its catalog without changing its model assignment."""
    from hermes_cli.config import save_env_value
    from hermes_cli.web_server_profiles import _config_profile_scope
    from hermes_cli.models import fetch_api_models, _get_json
    from hermes_cli.chat_catalog import without_generation_models
    from providers import get_provider_profile

    row = _provider(provider)
    key = api_key.strip() or _profile_key(role, row["key_env"])
    if not key:
        raise ValueError("请填写所选厂商的 API Key；已有同厂商 Key 时可留空沿用。")
    endpoint = base_url.strip() or row["base_url"]
    if not endpoint:
        raise ValueError("自定义 API 需要填写接口地址。")
    with _config_profile_scope(role):
        save_env_value(row["key_env"], key)

    # Explicit credentials keep same-provider roles independent, including discovery.
    if provider == "gemini":
        from agent.gemini_native_adapter import normalize_gemini_base_url
        from urllib.parse import urlencode
        root = normalize_gemini_base_url(endpoint) + "/models"
        url, live = root + "?pageSize=1000", []
        while True:
            page = _get_json(url, timeout=8.0, headers={"x-goog-api-key": key})
            live.extend(item["name"].removeprefix("models/") for item in page.get("models", [])
                        if "generateContent" in item.get("supportedGenerationMethods", []))
            token = page.get("nextPageToken")
            if not token:
                break
            url = root + "?" + urlencode({"pageSize": 1000, "pageToken": token})
    else:
        profile = get_provider_profile(provider)
        live = profile.fetch_models(api_key=key, base_url=endpoint) if profile else fetch_api_models(
            key, endpoint, api_mode=protocol if provider == "custom" else row["protocol"])
    source = "provider" if live is not None else "catalog"
    models = list(dict.fromkeys(without_generation_models(live if live is not None else row["models"])))
    return {"role": role, "provider": provider, "models": models, "source": source, "has_key": True}


def ensure_profiles(workflow, roles: list[str]) -> None:
    from hermes_cli.config import atomic_config_replace
    from hermes_cli.profiles import create_profile, get_profile_dir
    import shutil

    souls = Path(__file__).resolve().parent / "souls"
    if not souls.is_dir():
        souls = Path(__file__).resolve().parents[1] / "souls"
    for role in roles:
        if get_profile_dir(role).is_dir():
            continue
        directory = create_profile(role, no_alias=True)
        config = read_yaml(directory / "config.yaml")
        tools = ["kanban", "memory", "session_search", "todo", "clarify", "skills"] if role == "orchestrator" else [
            "terminal", "file", "web", "skills", "todo", "memory", "session_search"]
        config.update(toolsets=tools, platform_toolsets={"cli": tools}, kanban={"dispatch_in_gateway": False})
        config.setdefault("terminal", {}).update(backend="docker", docker_image=workflow.env["DOCKER_IMAGE"],
                                                  docker_mount_cwd_to_workspace=False)
        atomic_config_replace(directory / "config.yaml", config)
        shutil.copyfile(souls / (role + ".md"), directory / "SOUL.md")


def profile_settings(home: Path, profile: str) -> dict:
    from hermes_cli.config import load_env
    import hermes_constants

    directory = home / "profiles" / profile
    config = read_yaml(directory / "config.yaml")
    model = config.get("model") or {}
    if not isinstance(model, dict):
        model = {"default": str(model)}
    provider = model.get("provider", "")
    fields = (model["key_env"],) if model.get("key_env") else credential_fields(provider)
    token = hermes_constants.set_hermes_home_override(directory)
    try:
        values = load_env()
    finally:
        hermes_constants.reset_hermes_home_override(token)
    return {"profile": profile, "provider": provider, "model": model.get("default", ""),
            "base_url": model.get("base_url", ""), "protocol": model.get("api_mode", ""),
            "has_key": any(bool(values.get(key)) for key in fields)}


def _selection(provider: str, model: str, base_url: str) -> tuple[dict, str, str]:
    row = _provider(provider)
    model = model.strip() or row["default_model"]
    base_url = base_url.strip() or row["base_url"]
    if not model or (provider == "custom" and not base_url):
        raise ValueError("自定义 API 需要填写接口地址和模型名称。")
    return row, model, base_url


def _write(home: Path, profiles: list[str], row: dict, model: str, base_url: str, keys: list[str], protocol: str) -> None:
    from hermes_cli.config import atomic_config_replace, save_env_value
    from hermes_cli.web_server_profiles import _config_profile_scope

    for profile, key in zip(profiles, keys):
        with _config_profile_scope(profile):
            path = home / "profiles" / profile / "config.yaml"
            config = read_yaml(path)
            selected = {"provider": row["id"], "default": model, "key_env": row["key_env"], "base_url": base_url}
            if row["id"] == "custom":
                selected["api_mode"] = protocol
            config["model"] = selected
            # New sessions' auxiliary work uses this same connection; no second provider key is required.
            config["auxiliary"] = {}
            config["fallback_model"] = []
            config["custom_providers"] = [item for item in config.get("custom_providers", [])
                                           if not item.get("name", "").startswith("packy-")]
            save_env_value(row["key_env"], key)
            atomic_config_replace(path, config)


def save(home: Path, profiles: list[str], *, provider: str, model: str = "", api_key: str = "",
         base_url: str = "", protocol: str = "chat_completions") -> list[dict]:
    row, model, base_url = _selection(provider, model, base_url)
    keys = [api_key.strip() or _profile_key(profile, row["key_env"]) for profile in profiles]
    if not all(keys):
        raise ValueError("请填写所选厂商的 API Key；已有同厂商 Key 时可留空沿用。")
    _write(home, profiles, row, model, base_url, keys, protocol)
    return [profile_settings(home, profile) for profile in profiles]


def save_batch(home: Path, targets: dict[str, list[str]], connections: dict[str, dict]) -> list[dict]:
    prepared = []
    for role, values in connections.items():
        row, model, endpoint = _selection(values["provider"], values.get("model", ""), values.get("base_url", ""))
        key = values.get("api_key", "").strip() or _profile_key(role, row["key_env"])
        if not key:
            raise ValueError("请填写所选厂商的 API Key；已有同厂商 Key 时可留空沿用。")
        prepared.append((role, row, model, endpoint, key, values.get("protocol", "chat_completions")))
    for role, row, model, endpoint, key, protocol in prepared:
        _write(home, targets[role], row, model, endpoint, [key] * len(targets[role]), protocol)
    return [profile_settings(home, role) for role in connections]
