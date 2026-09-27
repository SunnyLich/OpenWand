from runtime.supervisor import tool_modes


def test_public_web_is_available_without_personal_context_access():
    caller = {"context_browser_mode": "off", "context_documents_mode": "off",
              "context_memory_mode": "off", "file_access": "off"}
    assert tool_modes.allowed_model_tools(caller) == ["web_search", "retrieve_website"]
    assert tool_modes.pinned_model_tools(caller) == ["web_search", "retrieve_website"]
    caller["tools"] = {"web_search": "off", "retrieve_website": "off"}
    assert tool_modes.allowed_model_tools(caller) == []
    assert tool_modes.pinned_model_tools(caller) == []


def test_local_file_access_mode_expands_to_model_tools():
    caller = {"file_access": "ask", "tools": {}}

    allowed = tool_modes.allowed_model_tools(caller)
    pinned = tool_modes.pinned_model_tools(caller)

    assert {"list_files", "read_file", "create_file", "edit_file", "write_file"} <= set(allowed)
    assert {"delegate_background_task", "background_task_status"} <= set(allowed)
    assert {"list_files", "read_file", "create_file", "edit_file", "write_file"} <= set(pinned)


def test_local_file_access_read_only_excludes_write_tools():
    caller = {"file_access": "read", "tools": {}}

    allowed = tool_modes.allowed_model_tools(caller)

    assert {"list_files", "read_file"} <= set(allowed)
    assert "create_file" not in allowed
    assert "edit_file" not in allowed
    assert "write_file" not in allowed
    assert "delegate_background_task" not in allowed
    assert "background_task_status" not in allowed


def test_mcp_server_group_override_is_not_model_tool_name():
    caller = {"file_access": "off", "tools": {"mcp_server.example": "on"}}

    assert tool_modes.tool_overrides(caller) == {"mcp_server.example": "on"}
    assert "mcp_server.example" not in tool_modes.allowed_model_tools(caller)
    assert "mcp_server.example" not in tool_modes.pinned_model_tools(caller)
