"""Tests for macos py brain test handler addons."""

from __future__ import annotations

import sys
import threading
import types

from openwand_brain import handlers


def test_addons_list_handler_registered():
    """Verify addons list handler registered behavior."""
    assert "brain.addons.list" in handlers.HANDLERS
    assert "brain.addons.ready" in handlers.HANDLERS
    assert "brain.addons.run_action" in handlers.HANDLERS
    assert "brain.addons.run_intent" in handlers.HANDLERS
    assert "brain.addons.set_action_enabled" in handlers.HANDLERS
    assert "brain.addons.approve" in handlers.HANDLERS
    assert "brain.addons.repair_environment" in handlers.HANDLERS
    assert "brain.addons.install_archive" in handlers.HANDLERS
    assert "brain.addons.install_folder" in handlers.HANDLERS
    assert "brain.addons.run_hotkey" in handlers.HANDLERS
    assert "brain.addons.llm_call" in handlers.HANDLERS


def test_addons_list_returns_discovered_addon_folder(tmp_path, monkeypatch):
    """Verify addons list returns discovered addon folder behavior."""
    addon_dir = tmp_path / "addons"
    example = addon_dir / "example"
    example.mkdir(parents=True)
    (example / "addon.toml").write_text(
        "[addon]\nid = 'example'\nname = 'Example'\nentry = '__init__.py'\n",
        encoding="utf-8",
    )
    (example / "__init__.py").write_text(
        "def before_query(prompt, context):\n"
        "    return prompt, context\n\n"
        "def get_tools():\n"
        "    return []\n",
        encoding="utf-8",
    )

    import core.addon_manager as addon_manager
    import core.system.paths as paths

    monkeypatch.setattr(paths, "ADDONS_DIR", addon_dir)
    monkeypatch.setattr(addon_manager, "_manager", None)

    result = handlers.HANDLERS["brain.addons.list"]()

    assert result["addons_dir"] == str(addon_dir)
    assert result["addons"][0]["id"] == "example"
    assert result["addons"][0]["name"] == "Example"
    assert result["addons"][0]["hooks"] == ["before_query", "get_tools"]

    addon_manager.get_manager().on_shutdown()


def test_addons_list_creates_missing_addons_folder(tmp_path, monkeypatch):
    """Addon Manager creates the install location on first open."""
    addon_dir = tmp_path / "addons"

    import core.addon_manager as addon_manager
    import core.system.paths as paths

    monkeypatch.setattr(paths, "ADDONS_DIR", addon_dir)
    monkeypatch.setattr(addon_manager, "_manager", None)

    result = handlers.HANDLERS["brain.addons.list"]()

    assert result["addons_dir"] == str(addon_dir)
    assert result["addons"] == []
    assert addon_dir.is_dir()


def test_addons_list_initializes_shared_manager_and_action_can_run(tmp_path, monkeypatch):
    """Verify addons list initializes shared manager and action can run behavior."""
    addon_dir = tmp_path / "addons"
    example = addon_dir / "native_action"
    marker = tmp_path / "ran.txt"
    example.mkdir(parents=True)
    (example / "addon.toml").write_text(
        "[addon]\nid = 'native-action'\nname = 'native_action'\nentry = '__init__.py'\n\n"
        "[permissions]\nui = ['tray']\n",
        encoding="utf-8",
    )
    (example / "__init__.py").write_text(
        "from pathlib import Path\n\n"
        "def _run():\n"
        f"    Path({str(marker)!r}).write_text('ran', encoding='utf-8')\n\n"
        "def get_tray_actions():\n"
        "    return [{'label': 'Do Native Thing', 'callback': _run}]\n",
        encoding="utf-8",
    )

    import core.addon_manager as addon_manager
    import core.system.paths as paths

    monkeypatch.setattr(paths, "ADDONS_DIR", addon_dir)
    monkeypatch.setattr(addon_manager, "_manager", None)

    result = handlers.HANDLERS["brain.addons.list"]()

    assert result["addons"][0]["id"] == "native-action"
    assert result["addons"][0]["tray_actions"] == ["Do Native Thing"]

    action_result = handlers.HANDLERS["brain.addons.run_action"](
        addon_id="native-action",
        label="Do Native Thing",
    )

    assert action_result == {
        "ok": True,
        "message": "Ran addon action: native-action / Do Native Thing",
    }
    assert marker.read_text(encoding="utf-8") == "ran"
    addon_manager.get_manager().on_shutdown()


def test_addons_list_prefers_loaded_manager(monkeypatch, tmp_path):
    """Verify addons list prefers loaded manager behavior."""
    manager = types.SimpleNamespace(
        summaries=lambda: [
            {
                "id": "loaded",
                "name": "loaded",
                "path": str(tmp_path / "addons" / "loaded"),
                "status": "loaded",
                "enabled": True,
                "hooks": ["get_tools", "get_tray_actions"],
                "tray_actions": ["Do Thing"],
                "tools": ["loaded_tool"],
                "settings": [],
                "permissions": {},
                "description": "",
                "error": "",
            }
        ]
    )
    fake_addon_manager = types.ModuleType("core.addon_manager")
    fake_addon_manager.get_manager = lambda: manager
    monkeypatch.setitem(sys.modules, "core.addon_manager", fake_addon_manager)

    import core.system.paths as paths

    monkeypatch.setattr(paths, "ADDONS_DIR", tmp_path / "addons")

    result = handlers.HANDLERS["brain.addons.list"]()

    assert result["addons"] == manager.summaries()


def test_addons_list_uses_cached_snapshot_without_refreshing_hosts(monkeypatch, tmp_path):
    calls = []

    class Manager:
        def summaries(self, **kwargs):
            calls.append(kwargs)
            return []

    fake_addon_manager = types.ModuleType("core.addon_manager")
    fake_addon_manager.get_manager = lambda: Manager()
    monkeypatch.setitem(sys.modules, "core.addon_manager", fake_addon_manager)
    import core.system.paths as paths

    monkeypatch.setattr(paths, "ADDONS_DIR", tmp_path / "addons")

    handlers.HANDLERS["brain.addons.list"]()

    assert calls == [{"refresh_host": False, "resolve_dynamic_options": False}]


def test_addons_ready_returns_background_snapshot(monkeypatch, tmp_path):
    ready = threading.Event()
    ready.set()
    monkeypatch.setattr(handlers, "_ADDON_BOOTSTRAP_READY", ready)
    monkeypatch.setattr(handlers, "_ADDON_BOOTSTRAP_ERROR", "")
    monkeypatch.setattr(handlers, "start_addon_bootstrap", lambda: None)
    monkeypatch.setattr(handlers, "_addon_summaries", lambda _path: [{"id": "ready"}])
    import core.system.paths as paths

    monkeypatch.setattr(paths, "ADDONS_DIR", tmp_path / "addons")

    result = handlers.HANDLERS["brain.addons.ready"](timeout_seconds=0.01)

    assert result["ready"] is True
    assert result["addons"] == [{"id": "ready"}]


def test_addon_bootstrap_snapshot_publishes_when_emitter_arrives_late(monkeypatch, tmp_path):
    ready = threading.Event()
    ready.set()
    events = []
    monkeypatch.setattr(handlers, "_ADDON_BOOTSTRAP_READY", ready)
    monkeypatch.setattr(handlers, "_ADDON_BOOTSTRAP_ERROR", "")
    monkeypatch.setattr(handlers, "_ADDON_BOOTSTRAP_EVENT_PUBLISHED", False)
    monkeypatch.setattr(handlers, "_RUNTIME_EVENT_EMITTER", None)
    monkeypatch.setattr(handlers, "_addon_summaries", lambda _path: [{"id": "ready"}])
    import core.system.paths as paths

    monkeypatch.setattr(paths, "ADDONS_DIR", tmp_path / "addons")

    handlers.set_runtime_event_emitter(lambda name, data: events.append((name, data)))
    handlers.set_runtime_event_emitter(lambda name, data: events.append((name, data)))

    assert len(events) == 1
    assert events[0][0] == "addons.changed"
    assert events[0][1]["reason"] == "loaded"
    assert events[0][1]["addons"] == [{"id": "ready"}]


def test_addon_enable_publishes_authoritative_changed_snapshot(monkeypatch, tmp_path):
    class Manager:
        def set_enabled(self, addon_id, enabled):
            assert addon_id == "virtual-workspace"
            return bool(enabled)

    events = []
    monkeypatch.setattr(handlers, "_loaded_addon_manager", lambda _path: Manager())
    monkeypatch.setattr(
        handlers,
        "_addon_summaries",
        lambda _path: [{
            "id": "virtual-workspace",
            "enabled": True,
            "tray_actions": ["Open Virtual Workspace"],
        }],
    )
    monkeypatch.setattr(handlers, "_RUNTIME_EVENT_EMITTER", lambda name, data: events.append((name, data)))
    import core.system.paths as paths

    monkeypatch.setattr(paths, "ADDONS_DIR", tmp_path / "addons")

    result = handlers.HANDLERS["brain.addons.set_enabled"](
        addon_id="virtual-workspace",
        enabled=True,
    )

    assert result["enabled"] is True
    assert events[0][0] == "addons.changed"
    assert events[0][1]["reason"] == "enabled"
    assert events[0][1]["addon_id"] == "virtual-workspace"
    assert events[0][1]["addons"][0]["tray_actions"] == ["Open Virtual Workspace"]


def test_addons_run_action_invokes_loaded_tray_action(monkeypatch):
    """Verify addons run action invokes loaded tray action behavior."""
    calls: list[tuple[str, str]] = []
    startup_calls: list[bool] = []
    monkeypatch.setattr(handlers, "run_addon_startup", lambda: startup_calls.append(True))

    class FakeManager:
        """Coordinate fake manager behavior."""
        def run_tray_action(self, name: str, label: str) -> dict[str, str]:
            """Verify run tray action behavior."""
            calls.append((name, label))
            return {
                "message": "opened",
                "virtual_workspace_url": "http://127.0.0.1:8765/?token=test",
            }

    fake_addon_manager = types.ModuleType("core.addon_manager")
    fake_addon_manager.get_manager = lambda: FakeManager()
    monkeypatch.setitem(sys.modules, "core.addon_manager", fake_addon_manager)

    result = handlers.HANDLERS["brain.addons.run_action"](
        addon_id="loaded",
        label="Do Thing",
    )

    assert result == {
        "ok": True,
        "message": "opened",
        "virtual_workspace_url": "http://127.0.0.1:8765/?token=test",
    }
    assert startup_calls == [True]
    assert calls == [("loaded", "Do Thing")]


def test_run_addon_startup_runs_once_with_app_context(monkeypatch):
    """Verify run addon startup runs once with app context behavior."""
    import core.llm_clients.client as client

    sentinel_registry = object()
    monkeypatch.setattr(client, "get_tool_registry", lambda: sentinel_registry)

    class AppContext:
        """Represent app context behavior."""
        def __init__(self, *, signals, model_tool_registry, config):
            """Initialize the app context instance."""
            self.signals = signals
            self.model_tool_registry = model_tool_registry
            self.config = config

    class FakeManager:
        """Coordinate fake manager behavior."""
        def __init__(self):
            """Initialize the fake manager instance."""
            self.startups = []

        def on_startup(self, ctx):
            """Verify on startup behavior."""
            self.startups.append(ctx)

    manager = FakeManager()
    fake_am = types.ModuleType("core.addon_manager")
    fake_am.AppContext = AppContext
    fake_am.get_manager = lambda: manager
    fake_am.init = lambda _dir: manager
    monkeypatch.setitem(sys.modules, "core.addon_manager", fake_am)
    monkeypatch.setattr(handlers, "_addon_startup_done", False)

    handlers.run_addon_startup()
    handlers.run_addon_startup()

    assert len(manager.startups) == 1
    ctx = manager.startups[0]
    assert ctx.signals is None
    assert ctx.model_tool_registry is sentinel_registry

    import config as cfg

    assert ctx.config is cfg


def test_addons_run_action_validates_inputs():
    """Verify addons run action validates inputs behavior."""
    import pytest

    with pytest.raises(ValueError, match="addon_id"):
        handlers.HANDLERS["brain.addons.run_action"](addon_id="", label="Do Thing")
    with pytest.raises(ValueError, match="label"):
        handlers.HANDLERS["brain.addons.run_action"](addon_id="loaded", label="")


def test_addons_run_action_reports_missing_action(monkeypatch):
    """Verify addons run action reports missing action behavior."""
    class FakeManager:
        """Coordinate fake manager behavior."""
        def run_tray_action(self, name: str, label: str) -> None:
            """Verify run tray action behavior."""
            raise ValueError(f"Addon action not found: {name} / {label}")

    fake_addon_manager = types.ModuleType("core.addon_manager")
    fake_addon_manager.get_manager = lambda: FakeManager()
    monkeypatch.setitem(sys.modules, "core.addon_manager", fake_addon_manager)

    import pytest

    with pytest.raises(ValueError, match="Addon action not found"):
        handlers.HANDLERS["brain.addons.run_action"](
            addon_id="loaded",
            label="Do Thing",
        )


def test_addon_llm_call_applies_permission_cap_privacy_and_request_limits(tmp_path, monkeypatch):
    """A permitted add-on gets one private capped model call, then hits its quota."""
    from types import SimpleNamespace

    from core import addon_store, privacy_gateway
    from core.llm_clients import client as llm_client

    addon = SimpleNamespace(
        id="demo-llm",
        enabled=True,
        manifest=SimpleNamespace(permissions={"llm": True}),
    )
    manager = SimpleNamespace(_find=lambda addon_id: addon if addon_id == "demo-llm" else None)
    monkeypatch.setattr(handlers, "_loaded_addon_manager", lambda _path: manager)

    quota = iter(((True, 4), (False, 0)))
    monkeypatch.setattr(
        addon_store,
        "record_llm_call",
        lambda addon_id, *, limit, window_seconds: next(quota),
    )

    class PrivacySession:
        def restore(self, text):
            return str(text).replace("EMAIL_1", "alice@example.test")

    session = PrivacySession()
    monkeypatch.setattr(
        privacy_gateway,
        "scrub_cloud_fields",
        lambda fields, session_id: (
            session,
            {"addon_prompt": "Summarize EMAIL_1"},
            {"count": 1, "ai_enabled": False, "categories": {"email": 1}},
        ),
    )
    privacy_contexts = []
    requests = []
    monkeypatch.setattr(
        llm_client,
        "set_live_privacy_context",
        lambda value, **kwargs: privacy_contexts.append((value, kwargs)),
    )

    def stream_response(prompt, **kwargs):
        requests.append((prompt, kwargs))
        return iter(("Reply for ", "EMAIL_1"))

    monkeypatch.setattr(llm_client, "stream_response", stream_response)

    result = handlers.HANDLERS["brain.addons.llm_call"](
        addon_id="demo-llm",
        prompt="Summarize alice@example.test",
        max_tokens=99999,
        temperature=0.25,
    )

    assert result["text"] == "Reply for alice@example.test"
    assert result["remaining"] == 4
    assert result["privacy_report"]["categories"] == {"email": 1}
    assert requests == [(
        "Summarize EMAIL_1",
        {"use_tools": False, "max_tokens": 2048, "temperature": 0.25},
    )]
    assert privacy_contexts == [
        (session, {"ai_enabled": False}),
        (None, {}),
    ]

    import pytest

    with pytest.raises(PermissionError, match="call cap reached"):
        handlers.HANDLERS["brain.addons.llm_call"](
            addon_id="demo-llm",
            prompt="Try again",
        )

    addon.manifest.permissions["llm"] = False
    with pytest.raises(PermissionError, match="missing llm permission"):
        handlers.HANDLERS["brain.addons.llm_call"](
            addon_id="demo-llm",
            prompt="Not allowed",
        )


def test_addon_message_action_runs_bounded_chat_route_and_resumes(monkeypatch):
    """A message action can request the configured Chat route without seeing credentials."""
    calls = []

    class FakeManager:
        def run_message_action(self, addon_id, action_id, payload):
            calls.append(("run", addon_id, action_id, payload))
            return {
                "status": "Formatting…",
                "llm": {
                    "prompt": "Format canonical text",
                    "max_tokens": 777,
                    "temperature": 0.2,
                    "route": "chat",
                },
                "state": {"canonical": payload["text"]},
            }

        def resume_message_action(self, addon_id, action_id, payload):
            calls.append(("resume", addon_id, action_id, payload))
            return {
                "status": "Formatted",
                "presentation": {
                    "format": "restricted_html",
                    "html": '<article class="formatted-reply"><p>Done.</p></article>',
                },
            }

    manager = FakeManager()
    monkeypatch.setattr(handlers, "_loaded_addon_manager", lambda _path: manager)
    model_calls = []

    def run_llm(**kwargs):
        model_calls.append(kwargs)
        return {
            "text": '<article class="formatted-reply"><p>Done.</p></article>',
            "input_tokens_estimate": 30,
            "output_tokens_estimate": 12,
        }

    monkeypatch.setattr(handlers, "_run_addon_llm_call", run_llm)
    result = handlers.HANDLERS["brain.addons.run_message_action"](
        addon_id="formatted-replies",
        action_id="format-reply",
        payload={"text": "Canonical reply"},
    )

    assert result["status"] == "Formatted"
    assert model_calls == [{
        "addon_id": "formatted-replies",
        "prompt": "Format canonical text",
        "max_tokens": 777,
        "temperature": 0.2,
        "limit": 30,
        "route": "chat",
        "max_cap": 4096,
        "route_model_hint": "",
    }]
    assert calls[1][3]["state"]["canonical"] == "Canonical reply"
    assert calls[1][3]["input_tokens_estimate"] == 30


def test_addon_message_action_returns_after_exactly_three_llm_operations(monkeypatch):
    """A format repair plus meaning check may consume all three bounded calls."""
    resumes = []

    class FakeManager:
        def run_message_action(self, _addon_id, _action_id, _payload):
            return {"llm": {"prompt": "format", "route": "llm"}, "state": {"step": 0}}

        def resume_message_action(self, _addon_id, _action_id, payload):
            resumes.append(payload)
            step = len(resumes)
            if step < 3:
                return {
                    "llm": {"prompt": "repair" if step == 1 else "verify", "route": "llm"},
                    "state": {"step": step},
                }
            return {"status": "Formatted Â· meaning checked", "presentation": {"html": "ok"}}

    monkeypatch.setattr(handlers, "_loaded_addon_manager", lambda _path: FakeManager())
    model_prompts = []

    def run_llm(**kwargs):
        model_prompts.append(kwargs["prompt"])
        return {"text": "result", "input_tokens_estimate": 1, "output_tokens_estimate": 1}

    monkeypatch.setattr(handlers, "_run_addon_llm_call", run_llm)
    result = handlers.HANDLERS["brain.addons.run_message_action"](
        addon_id="formatted-replies",
        action_id="format-reply",
        payload={"text": "Canonical"},
    )

    assert model_prompts == ["format", "repair", "verify"]
    assert len(resumes) == 3
    assert result["status"].startswith("Formatted")


def test_addon_llm_chat_route_uses_configured_chat_provider(monkeypatch):
    """The host maps the narrow chat route name to OpenWand's configured Chat model."""
    from types import SimpleNamespace

    import config
    from core import addon_store, privacy_gateway
    from core.llm_clients import client as llm_client

    addon = SimpleNamespace(
        id="formatted-replies",
        enabled=True,
        manifest=SimpleNamespace(permissions={"llm": True}),
    )
    manager = SimpleNamespace(_find=lambda addon_id: addon if addon_id == addon.id else None)
    monkeypatch.setattr(handlers, "_loaded_addon_manager", lambda _path: manager)
    monkeypatch.setattr(addon_store, "record_llm_call", lambda *_args, **_kwargs: (True, 29))
    monkeypatch.setattr(
        privacy_gateway,
        "scrub_cloud_fields",
        lambda fields, session_id: (None, fields, {"count": 0, "ai_enabled": True}),
    )
    monkeypatch.setattr(llm_client, "set_live_privacy_context", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(config, "CHAT_LLM_PROVIDER", "anthropic")
    monkeypatch.setattr(config, "CHAT_LLM_MODEL", "claude-test")
    monkeypatch.setattr(config, "CHAT_LLM_FALLBACKS", "ollama:local-test")
    requests = []

    def stream_response(prompt, **kwargs):
        requests.append((prompt, kwargs))
        return iter(("formatted",))

    monkeypatch.setattr(llm_client, "stream_response", stream_response)
    result = handlers._run_addon_llm_call(
        addon_id="formatted-replies",
        prompt="Format this",
        max_tokens=900,
        temperature=0.2,
        limit=30,
        route="chat",
    )

    assert result["route"] == "chat"
    assert requests == [(
        "Format this",
        {
            "use_tools": False,
            "max_tokens": 900,
            "temperature": 0.2,
            "route_provider": "anthropic",
            "route_model": "claude-test",
            "route_fallbacks": "ollama:local-test",
        },
    )]


def test_addon_llm_mini_route_uses_lower_cost_chatgpt_model(monkeypatch):
    """The formatter can use a host-approved small model without changing OpenWand's writer."""
    from types import SimpleNamespace

    from core import addon_store, privacy_gateway
    from core.llm_clients import client as llm_client

    addon = SimpleNamespace(
        id="formatted-replies",
        enabled=True,
        manifest=SimpleNamespace(permissions={"llm": True}),
    )
    manager = SimpleNamespace(_find=lambda addon_id: addon if addon_id == addon.id else None)
    monkeypatch.setattr(handlers, "_loaded_addon_manager", lambda _path: manager)
    monkeypatch.setattr(addon_store, "record_llm_call", lambda *_args, **_kwargs: (True, 29))
    monkeypatch.setattr(
        privacy_gateway,
        "scrub_cloud_fields",
        lambda fields, session_id: (None, fields, {"count": 0, "ai_enabled": True}),
    )
    monkeypatch.setattr(llm_client, "set_live_privacy_context", lambda *_args, **_kwargs: None)
    requests = []

    def stream_response(prompt, **kwargs):
        requests.append((prompt, kwargs))
        return iter(("formatted",))

    monkeypatch.setattr(llm_client, "stream_response", stream_response)
    result = handlers._run_addon_llm_call(
        addon_id="formatted-replies",
        prompt="Format this",
        max_tokens=4096,
        temperature=0.2,
        limit=30,
        route="chatgpt-mini",
        max_cap=4096,
    )

    assert result["route"] == "chatgpt-mini"
    assert requests[0][1]["route_provider"] == "chatgpt"
    assert requests[0][1]["route_model"] == "gpt-5.4-mini"
    assert requests[0][1]["max_tokens"] == 4096


def test_addon_llm_local_route_discovers_ollama_and_has_no_cloud_fallback(monkeypatch):
    """Local formatting chooses an installed model and never leaks into a paid fallback."""
    from types import SimpleNamespace

    from core import addon_store, privacy_gateway
    from core.llm_clients import client as llm_client

    addon = SimpleNamespace(
        id="formatted-replies",
        enabled=True,
        manifest=SimpleNamespace(permissions={"llm": True}),
    )
    manager = SimpleNamespace(_find=lambda addon_id: addon if addon_id == addon.id else None)
    monkeypatch.setattr(handlers, "_loaded_addon_manager", lambda _path: manager)
    monkeypatch.setattr(addon_store, "record_llm_call", lambda *_args, **_kwargs: (True, 29))
    monkeypatch.setattr(
        privacy_gateway,
        "scrub_cloud_fields",
        lambda fields, session_id: (None, fields, {"count": 0, "ai_enabled": True}),
    )
    monkeypatch.setattr(llm_client, "set_live_privacy_context", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(llm_client, "safe_list_models", lambda _provider: (["qwen3:8b"], ""))
    requests = []

    def stream_response(prompt, **kwargs):
        requests.append((prompt, kwargs))
        return iter(("formatted",))

    monkeypatch.setattr(llm_client, "stream_response", stream_response)
    result = handlers._run_addon_llm_call(
        addon_id="formatted-replies",
        prompt="Format this locally",
        max_tokens=4096,
        temperature=0.2,
        limit=30,
        route="ollama-local",
        max_cap=4096,
    )

    assert result["route"] == "ollama-local"
    assert result["model"] == "qwen3:8b"
    assert requests[0][1]["route_provider"] == "ollama"
    assert requests[0][1]["route_model"] == "qwen3:8b"
    assert requests[0][1]["route_fallbacks"] == ""
