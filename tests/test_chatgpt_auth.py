"""Tests for ChatGPT OAuth callback and credential contracts."""

import base64
import http.server
import json
import logging
import os
import socket
import threading
import urllib.error
import urllib.request
import uuid
import webbrowser
from urllib.parse import parse_qs, urlparse

import pytest

from core.auth import chatgpt as chatgpt_auth

_ASYNC_OAUTH_TEST_TIMEOUT = 15


@pytest.fixture(autouse=True)
def _isolate_native_codex_login(monkeypatch):
    """Unit tests must not inherit the developer machine's Codex session."""
    monkeypatch.setenv("OPENWAND_SHARE_CODEX_LOGIN", "false")


def _jwt_with_expiry(expiry_seconds: int) -> str:
    payload = base64.urlsafe_b64encode(
        json.dumps({"exp": expiry_seconds}).encode("utf-8")
    ).rstrip(b"=").decode("ascii")
    return f"header.{payload}.signature"


def test_native_codex_login_is_reused_without_copying_tokens(tmp_path, monkeypatch):
    """A fresh Codex ChatGPT cache becomes OpenWand's preferred login source."""
    auth_file = tmp_path / "auth.json"
    access = _jwt_with_expiry(int(chatgpt_auth.time.time()) + 3600)
    auth_file.write_text(
        json.dumps(
            {
                "auth_mode": "chatgpt",
                "tokens": {
                    "access_token": access,
                    "refresh_token": "must-not-be-copied",
                    "account_id": "account-codex",
                },
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("OPENWAND_SHARE_CODEX_LOGIN", "true")
    monkeypatch.setattr(chatgpt_auth, "_codex_auth_path", lambda: auth_file)
    monkeypatch.setattr(
        chatgpt_auth,
        "_get_tokens_unlocked",
        lambda: {"access": "openwand-access", "account_id": "account-openwand"},
    )

    tokens = chatgpt_auth.get_tokens()

    assert tokens == {
        "access": access,
        "expires": (int(chatgpt_auth.time.time()) + 3600) * 1000,
        "account_id": "account-codex",
        "_source": "codex",
    }
    assert "refresh" not in tokens
    assert chatgpt_auth.credential_source(tokens) == "codex"
    assert chatgpt_auth.get_valid_access_token() == access


def test_expired_codex_login_falls_back_to_openwand_oauth(tmp_path, monkeypatch):
    """OpenWand never spends or rewrites Codex's rotating refresh token."""
    auth_file = tmp_path / "auth.json"
    auth_file.write_text(
        json.dumps(
            {
                "auth_mode": "chatgpt",
                "tokens": {
                    "access_token": _jwt_with_expiry(int(chatgpt_auth.time.time()) - 1),
                    "refresh_token": "codex-refresh",
                    "account_id": "account-codex",
                },
            }
        ),
        encoding="utf-8",
    )
    fallback = {
        "access": "openwand-access",
        "refresh": "openwand-refresh",
        "expires": int((chatgpt_auth.time.time() + 3600) * 1000),
        "account_id": "account-openwand",
    }
    monkeypatch.setenv("OPENWAND_SHARE_CODEX_LOGIN", "true")
    monkeypatch.setattr(chatgpt_auth, "_codex_auth_path", lambda: auth_file)
    monkeypatch.setattr(chatgpt_auth, "_get_tokens_unlocked", lambda: fallback)

    assert chatgpt_auth.get_tokens() == fallback
    assert chatgpt_auth.credential_source() == "openwand"


def test_validate_login_checks_authenticated_catalog_without_model_call(monkeypatch):
    """The green status requires a successful authenticated server request."""
    seen: dict[str, object] = {}

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self, size):
            seen["read_size"] = size
            return b"{"

    def open_request(request, timeout):
        seen["url"] = request.full_url
        seen["authorization"] = request.get_header("Authorization")
        seen["account"] = request.get_header("Chatgpt-account-id")
        seen["originator"] = request.get_header("Originator")
        seen["user_agent"] = request.get_header("User-agent")
        seen["timeout"] = timeout
        return Response()

    monkeypatch.setattr(chatgpt_auth, "get_tokens", lambda: {"access": "stored"})
    monkeypatch.setattr(chatgpt_auth, "get_valid_access_token", lambda: "live-access")
    monkeypatch.setattr(chatgpt_auth, "get_account_id", lambda: "acct-123")
    monkeypatch.setattr(urllib.request, "urlopen", open_request)

    assert chatgpt_auth.validate_login(timeout_seconds=3) == (True, "acct-123")
    assert "/backend-api/codex/models?client_version=0.11.0" in str(seen["url"])
    assert seen["authorization"] == "Bearer live-access"
    assert seen["account"] == "acct-123"
    assert seen["originator"] == "codex_cli_rs"
    assert seen["user_agent"] == "OpenWand/0.11.0"
    assert seen["timeout"] == 3
    assert seen["read_size"] == 1


@pytest.mark.parametrize(
    ("version", "expected"),
    [("0.11", "0.11.0"), ("1", "1.0.0"), ("1.2.3", "1.2.3")],
)
def test_codex_client_version_is_three_part(version, expected):
    assert chatgpt_auth._codex_client_version(version) == expected


def test_validate_login_rejects_saved_chatgpt_token_after_remote_401(monkeypatch):
    monkeypatch.setattr(chatgpt_auth, "get_tokens", lambda: {"access": "stored"})
    monkeypatch.setattr(chatgpt_auth, "get_valid_access_token", lambda: "revoked-access")
    monkeypatch.setattr(chatgpt_auth, "get_account_id", lambda: "acct-123")
    monkeypatch.setattr(
        urllib.request,
        "urlopen",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            urllib.error.HTTPError("https://chatgpt.com", 401, "Unauthorized", {}, None)
        ),
    )

    with pytest.raises(RuntimeError, match="rejected"):
        chatgpt_auth.validate_login()


def test_oauth_success_page_uses_openwand_copy(monkeypatch):
    """Verify the browser callback success page uses the branded OpenWand message."""
    monkeypatch.setattr(chatgpt_auth, "_app_icon_data_uri", lambda: "data:image/x-icon;base64,icon")

    html = chatgpt_auth._html_success()

    assert "OpenWand - Authorization Complete" in html
    assert 'alt="OpenWand"' in html
    assert "Authorization completed successfully." in html
    assert "You can close this window and return to OpenWand." in html
    assert "Authorization Successful" not in html
    assert "return to the app" not in html


def test_oauth_error_page_escapes_error_message(monkeypatch):
    """Verify OAuth errors cannot inject markup into the callback page."""
    monkeypatch.setattr(chatgpt_auth, "_app_icon_data_uri", lambda: "")

    html = chatgpt_auth._html_error('<script>alert("x")</script>')

    assert "Authorization failed." in html
    assert "Return to OpenWand and try signing in again." in html
    assert "&lt;script&gt;" in html
    assert '<script>alert("x")</script>' not in html


def _free_local_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def test_oauth_callback_server_does_not_resolve_fqdn(monkeypatch):
    """Starting the local callback must not depend on reverse DNS."""
    monkeypatch.setattr(
        http.server.socket,
        "getfqdn",
        lambda *_args: pytest.fail("OAuth callback startup must not resolve an FQDN"),
    )

    server = chatgpt_auth._OAuthCallbackServer(
        (chatgpt_auth._OAUTH_BIND_HOST, 0),
        http.server.BaseHTTPRequestHandler,
    )
    try:
        assert server.server_name == chatgpt_auth._OAUTH_BIND_HOST
    finally:
        server.server_close()


def test_browser_oauth_reports_when_system_browser_cannot_open(monkeypatch):
    """A false/failed browser launch ends the flow instead of waiting five minutes."""
    errors: list[str] = []
    finished = threading.Event()

    class FakeServer:
        def __init__(self, *_args, **_kwargs):
            self.closed = False

        def server_close(self):
            self.closed = True

    monkeypatch.setattr(chatgpt_auth, "_OAuthCallbackServer", FakeServer)
    monkeypatch.setattr(webbrowser, "open", lambda _url: False)
    chatgpt_auth.start_browser_login(
        lambda _tokens: pytest.fail("browser failure must not authenticate"),
        lambda message: (errors.append(message), finished.set()),
    )
    assert finished.wait(_ASYNC_OAUTH_TEST_TIMEOUT)
    assert errors == ["The browser cannot open the ChatGPT sign-in page."]


def test_browser_oauth_rejects_mismatched_state_without_leaking_code(monkeypatch, caplog):
    """The real localhost callback rejects CSRF state before token exchange."""
    port = _free_local_port()
    opened = []
    browser_ready = threading.Event()
    errors = []
    finished = threading.Event()

    monkeypatch.setattr(chatgpt_auth, "_OAUTH_PORT", port)
    monkeypatch.setattr(chatgpt_auth, "_REDIRECT_URI", f"http://localhost:{port}/auth/callback")
    monkeypatch.setattr(chatgpt_auth, "_generate_state", lambda: "expected-state")
    monkeypatch.setattr(chatgpt_auth, "_generate_code_verifier", lambda: "contract-verifier")
    monkeypatch.setattr(
        chatgpt_auth,
        "_exchange_code",
        lambda *_args: pytest.fail("state mismatch must not exchange the authorization code"),
    )

    def open_browser(url):
        opened.append(url)
        browser_ready.set()
        return True

    monkeypatch.setattr(webbrowser, "open", open_browser)
    with caplog.at_level(logging.INFO, logger="openwand.chatgpt_auth"):
        chatgpt_auth.start_browser_login(
            lambda _tokens: pytest.fail("state mismatch must not authenticate"),
            lambda message: (errors.append(message), finished.set()),
        )
        assert browser_ready.wait(_ASYNC_OAUTH_TEST_TIMEOUT)
        secret_code = "authorization-code-must-not-be-logged"
        with urllib.request.urlopen(
            f"http://localhost:{port}/auth/callback?code={secret_code}&state=wrong-state",
            timeout=5,
        ) as response:
            body = response.read().decode("utf-8")
        assert finished.wait(_ASYNC_OAUTH_TEST_TIMEOUT)

    assert "OAuth state mismatch" in body
    assert errors and "state did not match" in errors[0]
    assert secret_code not in caplog.text
    query = parse_qs(urlparse(opened[0]).query)
    assert query["state"] == ["expected-state"]
    assert query["code_challenge_method"] == ["S256"]
    assert query["code_challenge"] == [chatgpt_auth._generate_code_challenge("contract-verifier")]


def test_browser_oauth_valid_callback_uses_pkce_and_persists_tokens(monkeypatch):
    """A valid localhost callback exchanges with its verifier and saves tokens."""
    port = _free_local_port()
    opened = []
    browser_ready = threading.Event()
    finished = threading.Event()
    exchanges = []
    saved = []
    successes = []

    monkeypatch.setattr(chatgpt_auth, "_OAUTH_PORT", port)
    monkeypatch.setattr(chatgpt_auth, "_REDIRECT_URI", f"http://localhost:{port}/auth/callback")
    monkeypatch.setattr(chatgpt_auth, "_generate_state", lambda: "valid-state")
    monkeypatch.setattr(chatgpt_auth, "_generate_code_verifier", lambda: "valid-verifier")
    monkeypatch.setattr(
        webbrowser,
        "open",
        lambda url: (opened.append(url), browser_ready.set(), True)[-1],
    )

    def exchange(code, verifier, redirect_uri):
        exchanges.append((code, verifier, redirect_uri))
        return {"access_token": "access-value", "refresh_token": "refresh-value", "expires_in": 3600}

    monkeypatch.setattr(chatgpt_auth, "_exchange_code", exchange)
    monkeypatch.setattr(chatgpt_auth, "save_tokens", lambda tokens: saved.append(dict(tokens)))
    chatgpt_auth.start_browser_login(
        lambda tokens: (successes.append(tokens), finished.set()),
        lambda error: pytest.fail(f"unexpected OAuth error: {error}"),
    )
    assert browser_ready.wait(_ASYNC_OAUTH_TEST_TIMEOUT)
    with urllib.request.urlopen(
        f"http://localhost:{port}/auth/callback?code=valid-code&state=valid-state",
        timeout=5,
    ) as response:
        assert response.status == 200
    assert finished.wait(_ASYNC_OAUTH_TEST_TIMEOUT)

    assert exchanges == [("valid-code", "valid-verifier", f"http://localhost:{port}/auth/callback")]
    assert successes == saved
    assert saved[0]["access"] == "access-value"
    assert saved[0]["refresh"] == "refresh-value"
    query = parse_qs(urlparse(opened[0]).query)
    assert query["code_challenge"] == [chatgpt_auth._generate_code_challenge("valid-verifier")]


def test_token_storage_fails_closed_when_keyring_is_unavailable(tmp_path, monkeypatch):
    """Reusable OAuth tokens are never written to a plaintext fallback file."""
    token_file = tmp_path / "private" / "tokens.json"
    monkeypatch.setattr(chatgpt_auth, "_TOKEN_FILE", token_file)
    monkeypatch.setattr(chatgpt_auth, "_USE_CHUNKED_KEYRING", True)
    monkeypatch.setattr(chatgpt_auth, "_keyring_get", lambda _account=chatgpt_auth._KEYRING_ACCOUNT: None)
    monkeypatch.setattr(chatgpt_auth, "_keyring_set", lambda _value, _account=chatgpt_auth._KEYRING_ACCOUNT: False)
    monkeypatch.setattr(chatgpt_auth, "_keyring_delete", lambda _account=chatgpt_auth._KEYRING_ACCOUNT: None)

    with pytest.raises(chatgpt_auth.OAuthTokenStorageError, match="not stored"):
        chatgpt_auth.save_tokens({"access": "old", "refresh": "refresh-old", "expires": 1})
    assert not token_file.exists()


def test_legacy_plaintext_tokens_migrate_to_keyring_and_are_removed(tmp_path, monkeypatch):
    token_file = tmp_path / "private" / "tokens.json"
    token_file.parent.mkdir(parents=True)
    tokens = {"access": "old", "refresh": "refresh-old", "expires": 1}
    token_file.write_text(json.dumps(tokens), encoding="utf-8")
    stored: dict[str, str] = {}
    monkeypatch.setattr(chatgpt_auth, "_TOKEN_FILE", token_file)
    monkeypatch.setattr(chatgpt_auth, "_USE_CHUNKED_KEYRING", True)
    monkeypatch.setattr(
        chatgpt_auth,
        "_keyring_get",
        lambda account=chatgpt_auth._KEYRING_ACCOUNT: stored.get(account),
    )
    monkeypatch.setattr(
        chatgpt_auth,
        "_keyring_set",
        lambda value, account=chatgpt_auth._KEYRING_ACCOUNT: stored.__setitem__(account, value) or True,
    )

    assert chatgpt_auth.get_tokens() == tokens
    assert not token_file.exists()


def test_chunked_token_roundtrip_rewrite_and_clear(tmp_path, monkeypatch):
    """Large OAuth payloads are chunked, rewritten, reassembled, and fully removed."""
    stored: dict[str, str] = {}
    deleted: list[str] = []
    monkeypatch.setattr(chatgpt_auth, "_TOKEN_FILE", tmp_path / "must-not-exist.json")
    monkeypatch.setattr(chatgpt_auth, "_USE_CHUNKED_KEYRING", True)
    monkeypatch.setattr(
        chatgpt_auth,
        "_keyring_get",
        lambda account=chatgpt_auth._KEYRING_ACCOUNT: stored.get(account),
    )
    monkeypatch.setattr(
        chatgpt_auth,
        "_keyring_set",
        lambda value, account=chatgpt_auth._KEYRING_ACCOUNT: stored.__setitem__(account, value) or True,
    )

    def delete(account=chatgpt_auth._KEYRING_ACCOUNT):
        deleted.append(account)
        stored.pop(account, None)

    monkeypatch.setattr(chatgpt_auth, "_keyring_delete", delete)

    large = {
        "access": "access-" + "a" * 2400,
        "refresh": "refresh-" + "r" * 1200,
        "expires": 123456789,
        "account_id": "account-1",
    }
    chatgpt_auth.save_tokens(large)
    first_manifest = json.loads(stored[chatgpt_auth._KEYRING_ACCOUNT])
    assert first_manifest[chatgpt_auth._CHUNK_MANIFEST_KEY] == 1
    assert first_manifest["count"] >= 4
    assert chatgpt_auth.get_tokens() == large

    smaller = {
        "access": "new-access-" + "b" * 1000,
        "refresh": "new-refresh",
        "expires": 987654321,
        "account_id": "account-1",
    }
    chatgpt_auth.save_tokens(smaller)
    second_manifest = json.loads(stored[chatgpt_auth._KEYRING_ACCOUNT])
    assert second_manifest["count"] < first_manifest["count"]
    assert chatgpt_auth.get_tokens() == smaller
    for index in range(second_manifest["count"], first_manifest["count"]):
        assert chatgpt_auth._chunk_account(index) not in stored

    chatgpt_auth.clear_tokens()
    assert chatgpt_auth.get_tokens() is None
    assert chatgpt_auth._KEYRING_ACCOUNT not in stored
    assert all(not account.startswith(f"{chatgpt_auth._KEYRING_ACCOUNT}-chunk-") for account in stored)
    assert chatgpt_auth._chunk_account(0) in deleted


def test_chunked_refresh_rewrites_rotating_credentials(tmp_path, monkeypatch):
    """Automatic refresh replaces a large expired chunk set with the rotated tokens."""
    stored: dict[str, str] = {}
    monkeypatch.setattr(chatgpt_auth, "_TOKEN_FILE", tmp_path / "must-not-exist.json")
    monkeypatch.setattr(chatgpt_auth, "_USE_CHUNKED_KEYRING", True)
    monkeypatch.setattr(
        chatgpt_auth,
        "_keyring_get",
        lambda account=chatgpt_auth._KEYRING_ACCOUNT: stored.get(account),
    )
    monkeypatch.setattr(
        chatgpt_auth,
        "_keyring_set",
        lambda value, account=chatgpt_auth._KEYRING_ACCOUNT: stored.__setitem__(account, value) or True,
    )
    monkeypatch.setattr(
        chatgpt_auth,
        "_keyring_delete",
        lambda account=chatgpt_auth._KEYRING_ACCOUNT: stored.pop(account, None),
    )

    expired = {
        "access": "expired-access-" + "a" * 2400,
        "refresh": "rotating-refresh-" + "r" * 1200,
        "expires": 1,
        "account_id": "account-1",
    }
    chatgpt_auth.save_tokens(expired)
    old_count = json.loads(stored[chatgpt_auth._KEYRING_ACCOUNT])["count"]

    def refresh(refresh_token):
        assert refresh_token == expired["refresh"]
        return {
            "access_token": "fresh-access",
            "refresh_token": "fresh-refresh",
            "expires_in": 3600,
        }

    monkeypatch.setattr(chatgpt_auth, "_do_refresh", refresh)

    assert chatgpt_auth.get_valid_access_token() == "fresh-access"
    refreshed = chatgpt_auth.get_tokens()
    assert refreshed["refresh"] == "fresh-refresh"
    assert refreshed["account_id"] == "account-1"
    new_count = json.loads(stored[chatgpt_auth._KEYRING_ACCOUNT])["count"]
    assert new_count < old_count
    for index in range(new_count, old_count):
        assert chatgpt_auth._chunk_account(index) not in stored


def test_device_login_reports_secure_storage_failure(monkeypatch):
    """A completed device login must not poll forever when the keychain rejects tokens."""
    responses = iter(
        [
            {"device_auth_id": "device", "user_code": "CODE", "interval": 1},
            {"authorization_code": "auth-code", "code_verifier": "verifier"},
        ]
    )
    errors: list[str] = []

    class ImmediateThread:
        def __init__(self, *, target, **_kwargs):
            self._target = target

        def start(self):
            self._target()

    monkeypatch.setattr(chatgpt_auth.threading, "Thread", ImmediateThread)
    monkeypatch.setattr(chatgpt_auth.time, "sleep", lambda _seconds: None)
    monkeypatch.setattr(chatgpt_auth, "_post_json", lambda *_args, **_kwargs: next(responses))
    monkeypatch.setattr(
        chatgpt_auth,
        "_exchange_code",
        lambda *_args: {"access_token": "access", "refresh_token": "refresh", "expires_in": 3600},
    )
    monkeypatch.setattr(
        chatgpt_auth,
        "save_tokens",
        lambda _tokens: (_ for _ in ()).throw(chatgpt_auth.OAuthTokenStorageError("keychain unavailable")),
    )

    chatgpt_auth.start_device_login(
        lambda _url, _code: None,
        lambda _tokens: pytest.fail("storage failure must not authenticate"),
        errors.append,
    )

    assert errors == ["keychain unavailable"]


@pytest.mark.real_host
@pytest.mark.skipif(
    os.environ.get("OPENWAND_RUN_REAL_KEYRING_TESTS") != "1",
    reason="set OPENWAND_RUN_REAL_KEYRING_TESTS=1 to use the real OS credential store",
)
def test_real_os_keyring_roundtrip_uses_disposable_account(tmp_path, monkeypatch):
    """The active OS keyring can store, retrieve, and clear a disposable token."""
    account = f"chatgpt-oauth-contract-{uuid.uuid4()}"
    monkeypatch.setattr(chatgpt_auth, "_KEYRING_ACCOUNT", account)
    monkeypatch.setattr(chatgpt_auth, "_TOKEN_FILE", tmp_path / "must-not-exist.json")
    tokens = {
        "access": "disposable-contract-token-" + "a" * 2400,
        "refresh": "disposable-refresh-token-" + "r" * 1200,
        "expires": 123456789,
        "account_id": "disposable-account",
    }
    try:
        chatgpt_auth.save_tokens(tokens)
        assert chatgpt_auth.get_tokens() == tokens
        assert not chatgpt_auth._TOKEN_FILE.exists()
    finally:
        chatgpt_auth.clear_tokens()
    assert chatgpt_auth.get_tokens() is None
