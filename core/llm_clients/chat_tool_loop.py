"""Provider-neutral chat tool loop contracts.

These types are intentionally small and behavior-light. They give OpenWand one
internal shape for chat tool calls/results before provider-specific adapters
translate to or from OpenAI Responses, Anthropic, or OpenAI-compatible payloads.
"""
from __future__ import annotations

import json
import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Any, Protocol

from core.llm_clients.adapter_protocol import (
    AdapterProtocolError,
    ToolContinuationError,
    argument_error,
    validate_call_ids,
)


@dataclass(frozen=True)
class ChatToolRequest:
    """Input needed by a provider-neutral chat tool loop."""

    messages: list[dict[str, Any]]
    system_prompt: str
    model_route: dict[str, Any]
    tools: list[dict[str, Any]]
    allowed_tools: list[str] | None
    pinned_tools: list[str] | None
    permissions: dict[str, Any]
    budgets: dict[str, Any]
    ambient_context: str = ""
    memory_context: str = ""
    screenshot_b64: str | None = None


@dataclass(frozen=True)
class OpenWandToolCall:
    """One normalized tool call requested by a model."""

    id: str
    name: str
    arguments: dict[str, Any] = field(default_factory=dict)
    provider_payload: dict[str, Any] | None = None
    validation_error: str = ""


@dataclass(frozen=True)
class OpenWandToolResult:
    """One normalized tool result returned to a model."""

    call_id: str
    name: str
    ok: bool
    content: str | list[dict[str, Any]]
    clipped: bool = False
    metadata: dict[str, Any] | None = None


@dataclass(frozen=True)
class OpenWandObservation:
    """A compact observation generated after one or more tool calls."""

    tool_results: list[OpenWandToolResult]
    summary: str
    remaining_budget: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ChatLoopFinal:
    """Final output and trace metadata from a chat tool loop."""

    text: str
    status: str
    observations: list[OpenWandObservation] = field(default_factory=list)
    tool_calls: list[OpenWandToolCall] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ChatModelTurn:
    """One normalized model turn returned to the neutral loop."""

    tool_calls: list[OpenWandToolCall] = field(default_factory=list)
    final_text: str = ""
    status: str = "continue"
    progress: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ChatToolLoopConfig:
    """Budgets and policy switches for the provider-neutral loop."""

    max_rounds: int = 7
    max_tool_calls: int = 4
    completion_gate: bool = True


class ChatLoopModel(Protocol):
    """Provider adapter/model interface consumed by the neutral loop."""

    def next_turn(
        self,
        request: ChatToolRequest,
        observations: list[OpenWandObservation],
        tool_calls: list[OpenWandToolCall],
    ) -> ChatModelTurn:
        """Return the next normalized model turn."""


class ChatToolExecutor(Protocol):
    """Tool executor interface consumed by the neutral loop."""

    def execute(self, call: OpenWandToolCall) -> OpenWandToolResult:
        """Execute one normalized tool call."""


class ToolExecutionGuard:
    """Apply the same allowlist, schema, identity, and budget rules to every SDK."""

    def __init__(self, request: ChatToolRequest, executor: ChatToolExecutor, max_calls: int):
        self.request, self.executor = request, executor
        self.max_calls = max(0, max_calls)
        self.invoked = 0
        self.seen: set[str] = set()
        self.schemas: dict[str, dict] = {}
        for tool in request.tools:
            definition = tool.get("function", tool)
            if definition.get("name"):
                self.schemas[definition["name"]] = definition.get("parameters", definition.get("input_schema", {}))

    def check_batch(self, calls: list[OpenWandToolCall]) -> None:
        try:
            validate_call_ids(calls, self.seen)
        except AdapterProtocolError as exc:
            if self.invoked:
                raise ToolContinuationError("Provider reused a tool-call ID after execution; replay was stopped.") from exc
            raise

    def execute(self, call: OpenWandToolCall) -> OpenWandToolResult:
        self.check_batch([call])
        self.seen.add(call.id)
        error = call.validation_error
        kind = "invalid_tool_arguments"
        if call.name not in self.schemas or (
            call.name not in _available_tool_names(self.request)
        ):
            error, kind = "Tool was not offered or is disabled for this request.", "tool_not_allowed"
        if not error:
            error = argument_error(call.arguments, self.schemas.get(call.name, {}))
        if not error and self.invoked >= self.max_calls:
            error = "Tool call skipped: this reply's tool-call budget is exhausted."
            kind = "tool_budget_exhausted"
        if error:
            return OpenWandToolResult(
                call_id=call.id, name=call.name, ok=False, content=error,
                metadata={"error_type": kind},
            )
        self.invoked += 1
        try:
            result = self.executor.execute(call)
            if result.call_id != call.id or result.name != call.name:
                raise AdapterProtocolError("Executor returned a result for a different tool call")
            return result
        except Exception as exc:
            raise ToolContinuationError(
                "Tool execution failed with an uncertain outcome; automatic route replay was stopped."
            ) from exc


class ChatToolLoop:
    """Provider-neutral observe-act-observe loop for chat tools."""

    def __init__(
        self,
        config: ChatToolLoopConfig | None = None,
        *,
        on_progress: Callable[[str], None] | None = None,
    ):
        """Initialize the chat tool loop."""
        self.config = config or ChatToolLoopConfig()
        self.on_progress = on_progress

    def _progress(self, text: str) -> None:
        if self.on_progress:
            try:
                self.on_progress(text)
            except Exception:
                # A disconnected activity display must not repeat model work.
                pass

    def run(
        self,
        request: ChatToolRequest,
        model: ChatLoopModel,
        executor: ChatToolExecutor,
    ) -> ChatLoopFinal:
        """Run the neutral tool loop until final text, block, or budget exhaustion."""
        observations: list[OpenWandObservation] = []
        tool_calls: list[OpenWandToolCall] = []
        progress_chunks: list[str] = []
        metadata: dict[str, Any] = {"completion_gate_missed": False}
        gate_nudges: set[str] = set()
        tool_call_count = 0
        guard = ToolExecutionGuard(request, executor, self.config.max_tool_calls)

        for _round in range(max(1, self.config.max_rounds)):
            if self.on_progress:
                self._progress("Waiting for model...")
            try:
                turn = model.next_turn(request, observations, tool_calls)
            except Exception as exc:
                if guard.invoked:
                    # Preserve SDK/auth/rate-limit/budget exception types for
                    # diagnostics while preventing another route from replaying.
                    exc.tools_executed = True
                    exc.add_note("Automatic route replay blocked because tools already executed.")
                raise
            if turn.progress:
                progress_chunks.append(turn.progress)
                if self.on_progress:
                    self._progress(turn.progress)
            if turn.tool_calls:
                guard.check_batch(turn.tool_calls)
                results: list[OpenWandToolResult] = []
                for call in turn.tool_calls:
                    tool_calls.append(call)
                    results.append(guard.execute(call))
                tool_call_count = guard.invoked
                observations.append(
                    OpenWandObservation(
                        tool_results=results,
                        summary=self._observation_summary(results),
                        remaining_budget={
                            "tool_calls": max(0, self.config.max_tool_calls - tool_call_count),
                        },
                    )
                )
                continue
            if turn.final_text:
                final_text = turn.final_text
                if _disabled_file_tool_text(request, final_text):
                    final_text = "File access is disabled, so the saved file was not changed."
                    metadata["disabled_file_call_blocked"] = True
                gate_message = self._completion_gate_message(request, tool_calls, observations, final_text)
                if self.config.completion_gate and gate_message and gate_message not in gate_nudges:
                    gate_nudges.add(gate_message)
                    observations.append(
                        OpenWandObservation(
                            tool_results=[],
                            summary=gate_message,
                            remaining_budget={
                                "tool_calls": max(0, self.config.max_tool_calls - tool_call_count),
                                "completion_gate": "nudged",
                            },
                        )
                    )
                    continue
                if self.config.completion_gate and gate_message and gate_message in gate_nudges:
                    metadata["completion_gate_missed"] = True
                    metadata["completion_gate_message"] = gate_message
                    if gate_message.startswith(("web_search is enabled", "Cite an exact URL")):
                        sources = _web_source_urls(observations)
                        final_text = (
                            "Search returned these sources, but I couldn't verify the model's proposed answer:\n"
                            + "\n".join(sources)
                            if sources else "The model did not complete a successful web search. No current information was retrieved."
                        )
                    elif _looks_like_file_mutation_request(_request_user_text(request).lower()):
                        final_text = "I couldn't complete the requested file change. No successful file change was confirmed."
                metadata["completion_gate_nudges"] = list(gate_nudges)
                metadata["progress_chunks"] = progress_chunks
                metadata.update(turn.metadata)
                return ChatLoopFinal(
                    text=final_text,
                    status=turn.status or "final",
                    observations=observations,
                    tool_calls=tool_calls,
                    metadata=metadata,
                )

        metadata["progress_chunks"] = progress_chunks
        metadata["completion_gate_nudges"] = list(gate_nudges)
        metadata["tool_budget_exhausted"] = tool_call_count >= max(0, self.config.max_tool_calls)
        return ChatLoopFinal(
            text="Chat tool loop stopped before a final answer because the round budget was exhausted.",
            status="round_budget_exhausted",
            observations=observations,
            tool_calls=tool_calls,
            metadata=metadata,
        )

    @staticmethod
    def _observation_summary(results: Sequence[OpenWandToolResult]) -> str:
        """Build a compact observation summary."""
        if not results:
            return "No tool results."
        parts = []
        for result in results:
            status = "ok" if result.ok else "failed"
            parts.append(f"{result.name}: {status}")
        return "; ".join(parts)

    def _completion_gate_message(
        self,
        request: ChatToolRequest,
        tool_calls: list[OpenWandToolCall],
        observations: list[OpenWandObservation],
        final_text: str = "",
    ) -> str:
        """Return a completion nudge when final text skipped obvious available work."""
        prompt = _request_user_text(request).lower()
        called = {call.name for call in tool_calls}
        succeeded = _successful_tool_names(observations)
        available = _available_tool_names(request)
        if (
            _latest_result_hit_tool_budget(observations)
            and _has_successful_evidence(prompt, observations)
            and _looks_like_budget_or_retry_answer(final_text)
        ):
            return (
                "The answer is not complete yet. A later tool call hit the tool budget, but successful "
                "tool results are already available. Answer from the successful observations instead "
                "of asking the user to retry, or explain the concrete missing evidence."
            )
        if _looks_like_memory_request(prompt) and "memory_search" in available and "memory_search" not in called:
            return _gate_nudge("memory_search")
        if _looks_like_screen_request(prompt) and available.intersection({"capture_screen", "get_context"}).isdisjoint(called):
            return _gate_nudge("screen or context")
        if _looks_like_file_mutation_request(prompt):
            mutation_tools = available.intersection({"create_file", "edit_file", "write_file", "delete_file"})
            if mutation_tools and mutation_tools.isdisjoint(succeeded):
                if "read_file" in available and "read_file" not in succeeded:
                    return (
                        "The requested file change is not complete. Do not claim it succeeded. "
                        "First call read_file on the file referenced by the latest user request "
                        "to obtain its exact current contents. Then use edit_file: an empty old "
                        "string appends new text safely; for replacement, copy an exact old substring."
                    )
                if succeeded.intersection({"read_file", "list_files"}):
                    return (
                        "Continue the file operation requested by the user. You have only gathered "
                        "file context so far; if the requested change is possible inside the allowed "
                        "folder, call the appropriate create_file, edit_file, or write_file tool "
                        "before giving the final answer. For edit_file, copy a nonempty exact "
                        "old substring from the read_file result and supply the replacement as new. "
                        "Preserve all other content. Do not ask the user for text already read."
                    )
                return _gate_nudge("file mutation")
        failed_names = _failed_tool_names(observations)
        if "read_file" in failed_names and "list_files" in available and "list_files" not in called:
            return (
                "The answer is not complete yet. read_file failed, and list_files is available. "
                "Try discovering the correct path before finalizing, or explain the concrete "
                "permission or capability boundary."
            )
        if (
            "read_file" in failed_names
            and "list_files" in _successful_tool_names(observations)
            and not _successful_read_after_latest_list(observations)
        ):
            return (
                "The answer is not complete yet. read_file failed, then list_files succeeded. "
                "Use the discovered file list to choose and inspect a relevant evidence source before finalizing, "
                "or explain the concrete permission or capability boundary."
            )
        if _looks_like_verification_request(prompt) and "run_command" in available and "run_command" not in called:
            return _gate_nudge("verification")
        mutation_finished = (
            _looks_like_file_mutation_request(prompt)
            and bool(succeeded.intersection({"create_file", "edit_file", "write_file", "delete_file"}))
            and not re.search(r"\b(?:read|inspect|verify|check)\b", prompt)
        )
        if _looks_like_file_context_request(prompt) and not mutation_finished:
            context_tools = available.intersection({"list_files", "read_file"})
            if context_tools and context_tools.isdisjoint(called):
                return _gate_nudge("file context")
            if "list_files" in succeeded and "read_file" in available and "read_file" not in succeeded:
                return (
                    "The answer is not complete yet. list_files is a discovery tool, not an evidence source. "
                    "Inspect relevant file contents with read_file before finalizing, or explain "
                    "the concrete permission or capability boundary."
                )
        # Anthropic runs its server search inside the API request. It does not
        # produce an OpenWand client-tool call to dispatch or grade here.
        server_search = any(
            tool.get("name") == "web_search" and str(tool.get("type", "")).startswith("web_search_")
            for tool in request.tools
        )
        if _explicit_web_search(prompt) and "web_search" in available and not server_search:
            if "web_search" not in called:
                return "web_search is enabled for this request. Call it to perform the user's requested live search before answering."
            sources = _web_source_urls(observations)
            if sources and re.search(r"\b(?:url|link|source|citation)s?\b", prompt):
                cited = set(re.findall(r"https?://[^\s<>\"\[\]]+|\[URL_\d+\]", final_text))
                normalized = set()
                for url in cited:
                    while url not in sources and url and url[-1] in ".,;:)":
                        url = url[:-1]
                    normalized.add(url)
                cited = normalized
                if not cited or cited.difference(sources):
                    return (
                        "Cite an exact URL from the successful web_search result. Copy privacy URL placeholders "
                        "verbatim so OpenWand can restore them. Do not replace them with a URL from memory. "
                        "Use a value already retrieved below; do not search for these instructions: "
                        + json.dumps(sources, ensure_ascii=False)
                    )
        return ""


def _explicit_web_search(prompt: str) -> bool:
    """Recognize explicit search requests without triggering on ordinary greetings."""
    prefix = r"(?:(?:please|can you|could you|would you|(?:but )?try to)\s+)*"
    action = (
        r"(?:search\s+(?:the\s+)?(?:web|internet|online)\b|look\s+up\b|"
        r"(?:use|perform|run|do)\s+(?:a\s+)?(?:live\s+)?web\s+search\b)"
    )
    return bool(re.match(prefix + action, prompt.strip(), re.IGNORECASE))


def _web_source_urls(observations: list[OpenWandObservation]) -> list[str]:
    """Read source URLs from successful search observations, including privacy tokens."""
    sources = []
    for observation in observations:
        for result in observation.tool_results:
            if result.name != "web_search" or not result.ok:
                continue
            raw = str(result.content).rpartition("Raw JSON:\n")[2]
            try:
                rows = json.loads(raw)
            except (ValueError, TypeError):
                continue
            if isinstance(rows, list):
                for row in rows:
                    url = row.get("url") if isinstance(row, dict) else None
                    if isinstance(url, str) and url and url not in sources:
                        sources.append(url)
    return sources


def _gate_nudge(kind: str) -> str:
    """Build a conservative completion-gate nudge."""
    return (
        "The answer is not complete yet. Available tools look relevant to the user's "
        f"request ({kind}). Continue the tool loop or explain the concrete permission "
        "or capability boundary."
    )


def _disabled_file_tool_text(request: ChatToolRequest, text: str) -> bool:
    """Recognize an attempted disabled file call without executing assistant text."""
    if request.permissions.get("file_access_mode") != "off":
        return False
    candidate = text.strip()
    if candidate.startswith("```json") and candidate.endswith("```"):
        candidate = candidate[7:-3].strip()
    try:
        payload = json.loads(candidate)
    except (ValueError, TypeError):
        return False
    if not isinstance(payload, dict):
        return False
    function = payload.get("function", payload)
    return (
        isinstance(function, dict)
        and function.get("name") in {"file", "create_file", "edit_file", "write_file", "read_file", "list_files"}
        and ("parameters" in function or "arguments" in function)
    )


def _request_user_text(request: ChatToolRequest) -> str:
    """Extract the latest user text from a request."""
    for message in reversed(request.messages):
        if str(message.get("role") or "").lower() != "user":
            continue
        content = message.get("content")
        if isinstance(content, str):
            # Context wrapped by build_contextual_user_text is evidence, not a
            # second user request. Do not demand tools mentioned only there.
            if content.startswith("<context>\n") and "\n</context>\n\n<request>\n" in content and content.endswith("\n</request>"):
                return content.rsplit("\n</context>\n\n<request>\n", 1)[1][:-len("\n</request>")]
            return content
        if isinstance(content, list):
            parts = []
            for item in content:
                if isinstance(item, dict):
                    parts.append(str(item.get("text") or ""))
            return " ".join(part for part in parts if part)
    return ""


def _available_tool_names(request: ChatToolRequest) -> set[str]:
    """Return tool names made available to the neutral loop."""
    if request.allowed_tools is not None:
        names = set(request.allowed_tools)
    else:
        names: set[str] = set()
        for tool in request.tools:
            name = str(tool.get("name") or "")
            if not name and isinstance(tool.get("function"), dict):
                name = str(tool["function"].get("name") or "")
            if name:
                names.add(name)
    mode = request.permissions.get("file_access_mode")
    if mode == "off":
        names -= {"list_files", "read_file", "create_file", "edit_file", "write_file"}
    elif mode == "read":
        names -= {"create_file", "edit_file", "write_file"}
    return names


def _successful_tool_names(observations: list[OpenWandObservation]) -> set[str]:
    """Return tool names with at least one successful result."""
    names: set[str] = set()
    for observation in observations:
        for result in observation.tool_results:
            if result.ok:
                names.add(result.name)
    return names


def _failed_tool_names(observations: list[OpenWandObservation]) -> set[str]:
    """Return tool names with at least one failed result."""
    names: set[str] = set()
    for observation in observations:
        for result in observation.tool_results:
            if not result.ok:
                names.add(result.name)
    return names


def _latest_result_hit_tool_budget(observations: list[OpenWandObservation]) -> bool:
    """Return whether the latest tool observation includes a budget-skipped call."""
    for observation in reversed(observations):
        if not observation.tool_results:
            continue
        return any(
            result.metadata and result.metadata.get("error_type") == "tool_budget_exhausted"
            for result in observation.tool_results
        )
    return False


def _has_successful_evidence(prompt: str, observations: list[OpenWandObservation]) -> bool:
    """Return whether previous successful tool output likely contains answer evidence."""
    if _looks_like_file_context_request(prompt):
        return "read_file" in _successful_tool_names(observations)
    if _looks_like_memory_request(prompt):
        return "memory_search" in _successful_tool_names(observations)
    if _looks_like_screen_request(prompt):
        return bool({"capture_screen", "get_context"}.intersection(_successful_tool_names(observations)))
    return bool(_successful_tool_names(observations))


def _looks_like_budget_or_retry_answer(text: str) -> bool:
    """Return whether final text mainly asks the user to retry because tools stopped."""
    lowered = text.lower()
    return any(
        phrase in lowered
        for phrase in (
            "budget",
            "exhausted",
            "ask again",
            "try again",
            "retry",
            "narrower",
            "couldn't access",
            "could not access",
            "unable to access",
        )
    )


def _successful_read_after_latest_list(observations: list[OpenWandObservation]) -> bool:
    """Return whether read_file succeeded after the latest successful list_files."""
    latest_list_index = -1
    for index, observation in enumerate(observations):
        for result in observation.tool_results:
            if result.name == "list_files" and result.ok:
                latest_list_index = index
    if latest_list_index < 0:
        return False
    for observation in observations[latest_list_index + 1:]:
        for result in observation.tool_results:
            if result.name == "read_file" and result.ok:
                return True
    return False


def _looks_like_file_context_request(prompt: str) -> bool:
    """Return whether the prompt likely needs file/project context."""
    return any(word in prompt for word in ("file", "project", "repo", "code", "settings", "storage"))


def _looks_like_file_mutation_request(prompt: str) -> bool:
    """Return whether the prompt likely asks for a file change."""
    if re.search(r"\b(?:change|fix|update|edit|write|create|delete)\b", prompt):
        return True
    return bool(
        re.search(r"\b(?:add|append|comment)\b", prompt)
        and re.search(r"\b(?:file|folder|directory|workspace)\b|\.[a-z0-9]{1,8}\b", prompt)
    )


def _looks_like_verification_request(prompt: str) -> bool:
    """Return whether the prompt likely asks for verification."""
    return any(word in prompt for word in ("verify", "test", "syntax", "run"))


def _looks_like_memory_request(prompt: str) -> bool:
    """Return whether the prompt likely needs memory search."""
    return "remember" in prompt or "what do you know about" in prompt or "my preferences" in prompt


def _looks_like_screen_request(prompt: str) -> bool:
    """Return whether the prompt likely needs screen or app context."""
    return any(phrase in prompt for phrase in ("what am i looking at", "on my screen", "this screen", "this app"))
