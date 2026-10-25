"""Keep recovered suites offline and independent of saved provider settings."""

import socket

import pytest


@pytest.fixture(autouse=True)
def offline_provider_state(monkeypatch, tmp_path):
    from core.llm_clients import client as llm
    from core.tool_registry import ToolRegistry

    def blocked(*_args, **_kwargs):
        raise AssertionError("Offline adapter test attempted network or real tool execution")

    monkeypatch.setattr(socket.socket, "connect", blocked)
    monkeypatch.setattr(socket.socket, "connect_ex", blocked)
    monkeypatch.setattr(socket, "create_connection", blocked)
    registry = ToolRegistry(plugin_dir=tmp_path / "no-plugins")
    registry._scripts = {}
    monkeypatch.setattr(llm, "_TOOL_REGISTRY", registry)
    monkeypatch.setattr(llm, "_route_capabilities", {})
    monkeypatch.setattr(llm, "_log_context", lambda *_a, **_kw: None)
    monkeypatch.setattr(llm, "_log_offered_model_tools", lambda *_a, **_kw: None)
    monkeypatch.setattr(llm, "_use_macos_openai_compat_non_streaming", lambda *_a: False)
    monkeypatch.setattr(llm.macos_safety, "openai_compat_tools_enabled", lambda: True)
