"""core/copilot_client.py - GitHub Copilot SDK bridge."""
from __future__ import annotations

import asyncio
import importlib.util
import inspect
import os
import time
from collections.abc import Iterable

from core.llm_clients.adapter_protocol import (
    AdapterCapabilityError,
    ToolContinuationError,
    result_text,
    tool_call,
    value,
)


def _options_call(function, options):
    """Support legacy option dictionaries and current keyword-only SDK APIs.

    Inspect before invoking: retrying a TypeError after creating a session can
    create duplicate remote sessions and hide an exception from inside the SDK.
    """
    parameters = inspect.signature(function).parameters
    positional = [p for p in parameters.values() if p.kind in (p.POSITIONAL_ONLY, p.POSITIONAL_OR_KEYWORD)]
    if len(positional) == 1 and positional[0].name in {"options", "config"}:
        return function(options)
    unknown = set(options) - set(parameters)
    if unknown and not any(p.kind == p.VAR_KEYWORD for p in parameters.values()):
        raise AdapterCapabilityError(f"Installed Copilot SDK does not support options: {', '.join(sorted(unknown))}")
    return function(**options)

_SDK_MODULE = "copilot"
_COPILOT_STATE_HOME = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "private", "copilot-state")
)


def _available_sdk_module() -> str | None:
    """Handle available sdk module for auth copilot client."""
    return _SDK_MODULE if importlib.util.find_spec(_SDK_MODULE) else None


def _extract_content(response) -> str:
    """Extract content."""
    data = getattr(response, "data", None)
    content = getattr(data, "content", None) if data is not None else None
    if content is None and isinstance(data, dict):
        content = data.get("content")
    if content is None and isinstance(response, dict):
        data = response.get("data")
        content = data.get("content") if isinstance(data, dict) else response.get("content")
    return str(content or "")


def _client_options(token: str) -> dict:
    """Handle client options for auth copilot client."""
    import config

    env = dict(os.environ)
    env["COPILOT_GITHUB_TOKEN"] = token
    env.setdefault("XDG_STATE_HOME", _COPILOT_STATE_HOME)

    options: dict = {
        "github_token": token,
        "use_logged_in_user": False,
        "env": env,
    }
    cli_url = getattr(config, "COPILOT_CLI_URL", "").strip()
    cli_path = getattr(config, "COPILOT_CLI_PATH", "").strip()
    if cli_url:
        options["cli_url"] = cli_url
    if cli_path:
        options["cli_path"] = cli_path
    return options


def _deny_permission(_request, _context) -> dict:
    """Handle deny permission for auth copilot client."""
    return {"kind": "denied-by-rules", "rules": []}


def _approve_permission(_request, _context) -> dict:
    """Handle approve permission for auth copilot client."""
    return {"kind": "approved", "rules": []}


async def _ask_async(
    prompt: str,
    model: str,
    system: str = "",
    session_id: str | None = None,
    allow_tools: bool = False,
    *, tool_request=None, tool_executor=None, max_tool_calls: int = 4,
) -> str:
    """Handle ask async for auth copilot client."""
    from copilot import CopilotClient  # type: ignore

    from core.auth import copilot_auth

    token = copilot_auth.get_effective_token()
    if not token:
        raise RuntimeError(
            "No Copilot token is stored and you are not signed in to GitHub."
        )

    ok, message = copilot_auth.validate_token_format(token)
    if not ok:
        raise RuntimeError(message)

    client = _options_call(CopilotClient, _client_options(token))
    guard = None
    failures = []
    try:
        await client.start()
        session_options: dict = {
            "model": model or "gpt-4.1",
            "session_id": session_id or f"openwand-{int(time.time() * 1000)}",
            "on_permission_request": _approve_permission if allow_tools else _deny_permission,
        }
        if not allow_tools:
            session_options["available_tools"] = []
        if tool_request is not None:
            from copilot import Tool, ToolResult

            from core.llm_clients.chat_tool_loop import ToolExecutionGuard

            if tool_executor is None:
                raise AdapterCapabilityError("OpenWand tools require an explicit OpenWand executor")
            guard = ToolExecutionGuard(tool_request, tool_executor, max_tool_calls)

            def handler(name):
                def invoke(invocation):
                    try:
                        if value(invocation, "tool_name", name) != name:
                            raise AdapterCapabilityError("Copilot tool invocation does not match its registered handler")
                        call = tool_call(value(invocation, "tool_call_id"), name, value(invocation, "arguments", {}))
                        result = guard.execute(call)
                        return ToolResult(
                            text_result_for_llm=result_text(result.content),
                            result_type="success" if result.ok else "failure",
                        )
                    except Exception as exc:
                        failures.append(exc)
                        raise
                return invoke

            native_tools = []
            for schema in tool_request.tools:
                definition = schema.get("function", schema)
                name = definition["name"]
                if tool_request.allowed_tools is not None and name not in tool_request.allowed_tools:
                    continue
                native_tools.append(Tool(
                    name=name, description=definition.get("description", ""),
                    parameters=definition.get("parameters", definition.get("input_schema", {})),
                    handler=handler(name), overrides_built_in_tool=True,
                    # The SDK only delegates to OpenWand's guarded executor.
                    # OpenWand retains its own file/action approval checks.
                    skip_permission=True,
                ))
            session_options.update({
                "tools": native_tools, "available_tools": [tool.name for tool in native_tools],
                "on_permission_request": _deny_permission,
            })
        if system:
            session_options["system_message"] = {
                "mode": "replace",
                "content": system,
            }
        session = await _options_call(client.create_session, session_options)
        send_parameters = inspect.signature(session.send_and_wait).parameters
        pending = session.send_and_wait(prompt) if "prompt" in send_parameters else session.send_and_wait({"prompt": prompt})
        response = await asyncio.wait_for(pending, timeout=120)
        if failures:
            raise failures[0]
        text = _extract_content(response)
        if guard is not None and guard.invoked and not text:
            raise ToolContinuationError("Copilot returned no answer after tool execution; automatic replay was stopped.")
        return text
    except Exception as exc:
        if guard is not None and guard.invoked:
            raise ToolContinuationError("Copilot failed after OpenWand tool execution; automatic replay was stopped.") from exc
        raise
    finally:
        try:
            await client.stop()
        except Exception as exc:
            if guard is not None and guard.invoked:
                raise ToolContinuationError("Copilot cleanup failed after tool execution; automatic replay was stopped.") from exc
            raise


def _ask_sync(
    prompt: str,
    model: str,
    system: str = "",
    session_id: str | None = None,
    allow_tools: bool = False,
    **kwargs,
) -> str:
    """Handle ask sync for auth copilot client."""
    return asyncio.run(_ask_async(prompt, model, system, session_id, allow_tools, **kwargs))


def ask(
    prompt: str,
    model: str,
    system: str = "",
    session_id: str | None = None,
    allow_tools: bool = False,
    **kwargs,
) -> str:
    """Handle ask for auth copilot client."""
    try:
        asyncio.get_running_loop()
    except RuntimeError as exc:
        if "no running event loop" in str(exc):
            return _ask_sync(prompt, model, system, session_id, allow_tools, **kwargs)
        raise
    raise RuntimeError("Copilot calls cannot run inside an existing asyncio event loop yet.")


def stream(
    prompt: str,
    model: str,
    system: str = "",
    session_id: str | None = None,
    allow_tools: bool = False,
    **kwargs,
) -> Iterable[str]:
    """Yield the Copilot reply as a single chunk (non-streaming shim)."""
    text = ask(prompt, model, system, session_id, allow_tools, **kwargs)
    if text:
        yield text


def test_copilot_token() -> tuple[bool, str]:
    """Verify copilot token behavior."""
    from core.auth import copilot_auth

    token = copilot_auth.get_effective_token()
    if not token:
        return False, "No Copilot token is stored and you are not signed in to GitHub."

    ok, message = copilot_auth.validate_token_format(token)
    if not ok:
        return False, message

    sdk_module = _available_sdk_module()
    if not sdk_module:
        return False, (
            "Token is stored and the format looks usable, but github-copilot-sdk "
            "is not installed yet. Install requirements before using Copilot."
        )

    return True, (
        f"Token is stored and SDK module '{sdk_module}' is available. "
        "Select provider 'copilot' to route text requests through it."
    )
