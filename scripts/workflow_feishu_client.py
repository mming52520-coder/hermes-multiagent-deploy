"""Feishu application REST calls for the workflow. No gateway SDK dependency."""

from __future__ import annotations

from http.client import HTTPException
import hashlib
import json
import logging
import threading
import time
from urllib import error, request
from urllib.parse import quote

_log = logging.getLogger(__name__)
_hosts = {"feishu": "open.feishu.cn", "lark": "open.larksuite.com"}
_tokens: dict[tuple, tuple[float, str]] = {}
_token_lock = threading.Lock()


class _NoRedirect(request.HTTPRedirectHandler):
    # urllib otherwise forwards Authorization to a redirect destination.
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _open(req, *, timeout):
    return request.build_opener(_NoRedirect()).open(req, timeout=timeout)


class FeishuClient:
    def __init__(self, app_id, secret, domain="feishu", *, opener=None):
        if domain not in _hosts:
            raise ValueError("不支持的飞书服务域。")
        self.host = _hosts[domain]
        self.app_id = app_id
        self._secret = secret
        self._cache_key = (self.host, app_id, hashlib.sha256(secret.encode()).digest())
        self.opener = opener
        self.last_error_code = None

    def _request(self, method, path, body, *, token=None):
        self.last_error_code = None
        headers = {"Content-Type": "application/json; charset=utf-8"}
        if token:
            headers["Authorization"] = "Bearer " + token
        req = request.Request(
            "https://" + self.host + "/open-apis/" + path,
            method=method,
            headers=headers,
            data=json.dumps(body, ensure_ascii=False).encode(),
        )
        status = None
        try:
            try:
                response = (self.opener or _open)(req, timeout=10)
            except error.HTTPError as exc:
                # Feishu returns its API error code in the JSON body of HTTP 4xx responses.
                response, status = exc, exc.code
            with response:
                result = json.load(response)
            code = result.get("code") if isinstance(result, dict) else None
            if status is not None or code != 0:
                self.last_error_code = code if isinstance(code, int) else None
                _log.warning(
                    "Feishu %s failed (HTTP %s, API code %s)", method, status or 200, self.last_error_code
                )
                return None
            return result
        except (ValueError, OSError, HTTPException) as exc:
            _log.warning("Feishu %s failed (HTTP %s, %s)", method, status or "unknown", type(exc).__name__)
        return None

    def tenant_token(self):
        now = time.monotonic()
        with _token_lock:
            deadline, token = _tokens.get(self._cache_key, (0, ""))
        if now < deadline:
            return token
        result = self._request(
            "POST", "auth/v3/tenant_access_token/internal", {"app_id": self.app_id, "app_secret": self._secret}
        )
        if not result:
            return False
        token, expiry = result.get("tenant_access_token"), result.get("expire")
        if not isinstance(token, str) or not token or not isinstance(expiry, (float, int)):
            _log.warning("Feishu returned an incomplete tenant token response")
            return False
        with _token_lock:
            _tokens[self._cache_key] = (now + expiry - 300, token)
        return token

    def _send(self, chat_id, kind, content, reply_to, delivery_id):
        token = self.tenant_token()
        if not token:
            return False
        body = {"msg_type": kind, "content": json.dumps(content, ensure_ascii=False)}
        if delivery_id:
            body["uuid"] = delivery_id
        if reply_to:
            path = f"im/v1/messages/{quote(reply_to, safe='')}/reply"
        else:
            path = "im/v1/messages?receive_id_type=chat_id"
            body["receive_id"] = chat_id
        result = self._request("POST", path, body, token=token)
        data = (result or {}).get("data")
        return (data.get("message_id") or False) if isinstance(data, dict) else False

    def send_card(self, chat_id, card, *, delivery_id=None):
        return self._send(chat_id, "interactive", card, None, delivery_id)

    def patch_card(self, message_id, card):
        token = self.tenant_token()
        if not token:
            return False
        return (
            self._request(
                "PATCH",
                "im/v1/messages/" + quote(message_id, safe=""),
                {"content": json.dumps(card, ensure_ascii=False)},
                token=token,
            )
            is not None
        )

    def send_text(self, chat_id, text, reply_to=None, *, delivery_id=None):
        return self._send(chat_id, "text", {"text": text}, reply_to, delivery_id)


def client_for(workflow):
    if not workflow.env.get("WORKFLOW_FEISHU_CHAT_ID", "").strip():
        return None
    from hermes_cli.config import get_env_value_prefer_dotenv

    if __package__:
        from .workflow_runtime import home_scope
    else:
        from workflow_runtime import home_scope
    with home_scope(workflow.root):
        app = get_env_value_prefer_dotenv("FEISHU_APP_ID")
        secret = get_env_value_prefer_dotenv("FEISHU_APP_SECRET")
        if not app or not secret:
            return None
        domain = (get_env_value_prefer_dotenv("FEISHU_DOMAIN") or "feishu").strip().lower()
        return FeishuClient(app, secret, domain)
