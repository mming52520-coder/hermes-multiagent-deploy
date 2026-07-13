#!/usr/bin/env python3
from __future__ import annotations

import json
import re
import ssl
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from configure_profiles import PROFILES, load_env_file, validate_env


def redact(text: str) -> str:
    text = re.sub(r"sk-[A-Za-z0-9_-]{6,}", "sk-***REDACTED***", text)
    text = re.sub(
        r'(?i)("?(?:api[_-]?key|authorization|token)"?\s*[:=]\s*")[^"]+(")',
        r"\1***REDACTED***\2",
        text,
    )
    return text[:500]


def post_json(
    url: str,
    headers: dict[str, str],
    payload: dict[str, Any],
    timeout: int = 90,
) -> tuple[int, str]:
    req = urllib.request.Request(
        url=url,
        data=json.dumps(payload).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    try:
        with urllib.request.urlopen(
            req,
            timeout=timeout,
            context=ssl.create_default_context(),
        ) as response:
            body = response.read(2048).decode("utf-8", errors="replace")
            return int(response.status), body
    except urllib.error.HTTPError as exc:
        body = exc.read(2048).decode("utf-8", errors="replace")
        return int(exc.code), body
    except Exception as exc:
        return 0, str(exc)


def endpoint(base: str, suffix: str) -> str:
    return base.rstrip("/") + "/" + suffix.lstrip("/")


def test_pair(provider: str, model: str, env: dict[str, str]) -> tuple[int, str]:
    if provider == "custom:packy-claude":
        return post_json(
            endpoint(env["PACKY_CLAUDE_BASE_URL"], "/v1/messages"),
            {
                "content-type": "application/json",
                "x-api-key": env["PACKY_CLAUDE_API_KEY"],
                "anthropic-version": "2023-06-01",
            },
            {
                "model": model,
                "max_tokens": 16,
                "messages": [{"role": "user", "content": "Reply only: OK"}],
            },
        )

    if provider == "custom:packy-cc-sale":
        return post_json(
            endpoint(env["PACKY_CC_SALE_BASE_URL"], "/v1/messages"),
            {
                "content-type": "application/json",
                "x-api-key": env["PACKY_CC_SALE_API_KEY"],
                "anthropic-version": "2023-06-01",
            },
            {
                "model": model,
                "max_tokens": 16,
                "messages": [{"role": "user", "content": "Reply only: OK"}],
            },
        )

    if provider == "custom:packy-codex":
        return post_json(
            endpoint(env["PACKY_CODEX_BASE_URL"], "/responses"),
            {
                "content-type": "application/json",
                "authorization": f"Bearer {env['PACKY_CODEX_API_KEY']}",
            },
            {
                "model": model,
                "input": [{"role": "user", "content": "Reply only: OK"}],
                "max_output_tokens": 32,
                "store": False,
                "stream": False,
            },
        )

    if provider == "custom:packy-deepseek":
        return post_json(
            endpoint(env["PACKY_DEEPSEEK_BASE_URL"], "/chat/completions"),
            {
                "content-type": "application/json",
                "authorization": f"Bearer {env['PACKY_DEEPSEEK_API_KEY']}",
            },
            {
                "model": model,
                "messages": [{"role": "user", "content": "Reply only: OK"}],
                "max_tokens": 16,
                "stream": False,
            },
        )

    if provider == "deepseek":
        return post_json(
            "https://api.deepseek.com/chat/completions",
            {
                "content-type": "application/json",
                "authorization": f"Bearer {env['DEEPSEEK_API_KEY']}",
            },
            {
                "model": model,
                "messages": [{"role": "user", "content": "Reply only: OK"}],
                "max_tokens": 16,
                "stream": False,
            },
        )

    return 0, f"unsupported provider {provider}"


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: check-model-apis.py deploy.env", file=sys.stderr)
        return 2

    env_path = Path(sys.argv[1]).expanduser().resolve()
    env = load_env_file(env_path)
    errors = validate_env(env_path, env)
    if errors:
        print("配置校验失败；未发出 API 请求。", file=sys.stderr)
        for error in errors:
            print(f"- {error}", file=sys.stderr)
        return 1

    seen: set[tuple[str, str]] = set()
    failures = 0

    for profile in PROFILES:
        prefix = profile.upper()
        provider = env[f"{prefix}_PROVIDER"]
        model = env[f"{prefix}_MODEL"]
        pair = (provider, model)
        if pair in seen:
            print(f"[SKIP] {profile}: 复用已验证的 {provider} / {model}")
            continue
        seen.add(pair)

        print(f"[TEST] {profile}: {provider} / {model}")
        status, body = test_pair(provider, model, env)
        if 200 <= status < 300:
            print(f"[PASS] HTTP {status}")
        else:
            failures += 1
            print(f"[FAIL] HTTP {status}", file=sys.stderr)
            print(redact(body), file=sys.stderr)

    if failures:
        print(
            f"接口预检失败：{failures} 个 provider/model 组合不可用。"
            "请检查 Token 分组、Endpoint 和模型广场中的准确模型 ID。",
            file=sys.stderr,
        )
        return 1

    print("全部模型接口预检通过；未显示任何密钥或模型回复正文。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
