"""Local authenticated bridge to VS Code's supported Extension API."""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Any


@dataclass(frozen=True)
class VSCodeExtensionEndpoint:
    port: int
    token: str


class VSCodeExtensionAPIAdapter:
    def __init__(self, endpoint: VSCodeExtensionEndpoint | None = None) -> None:
        self.endpoint = endpoint or self._from_environment()

    @staticmethod
    def _from_environment() -> VSCodeExtensionEndpoint:
        port = int(os.environ.get("WISP_VSCODE_BRIDGE_PORT", "0") or 0)
        token = os.environ.get("WISP_VSCODE_BRIDGE_TOKEN", "")
        if not (0 < port < 65536 and len(token) >= 16):
            raise RuntimeError("The Wisp VS Code API bridge is not connected.")
        return VSCodeExtensionEndpoint(port=port, token=token)

    def _request(self, path: str, *, method: str = "GET", payload: dict[str, Any] | None = None) -> dict[str, Any]:
        body = None if payload is None else json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(
            f"http://127.0.0.1:{self.endpoint.port}{path}",
            data=body,
            method=method,
            headers={
                "Authorization": f"Bearer {self.endpoint.token}",
                "Content-Type": "application/json",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=5.0) as response:
                result = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"VS Code API rejected the request: {detail}") from exc
        if not isinstance(result, dict):
            raise RuntimeError("VS Code API returned an invalid response.")
        return result

    def health(self) -> dict[str, Any]:
        return self._request("/health")

    def apply_text(self, text: str) -> dict[str, Any]:
        result = self._request("/apply", method="POST", payload={"text": str(text or "")})
        if not result.get("ok") or not result.get("textVerified"):
            raise RuntimeError(str(result.get("error") or "VS Code did not verify the edit."))
        return {
            "ok": True,
            "method": "vscode-extension-api",
            "activated": False,
            "confirmed": True,
            "text_verified": True,
            "document_uri": result.get("documentUri"),
            "document_version_before": result.get("documentVersionBefore"),
            "document_version_after": result.get("documentVersionAfter"),
            "is_untitled": bool(result.get("isUntitled")),
            "selection": result.get("selection") or {},
            "error": "",
        }

    def preview_format_document(self) -> dict[str, Any]:
        """Ask registered formatter providers for exact edits without applying them."""
        return self._verified_preview(self._request("/format/preview", method="POST", payload={}))

    def apply_format_document(
        self, *, preview_token: str, expected_document_version: int, expected_document_sha256: str
    ) -> dict[str, Any]:
        return self._verified_mutation(
            "/format/apply",
            {
                "previewToken": preview_token,
                "expectedDocumentVersion": int(expected_document_version),
                "expectedDocumentSha256": expected_document_sha256,
            },
        )

    def preview_test_file(self, *, relative_path: str, proposed_text: str) -> dict[str, Any]:
        return self._verified_preview(
            self._request(
                "/test-file/preview",
                method="POST",
                payload={"relativePath": self._relative_path(relative_path), "proposedText": str(proposed_text)},
            )
        )

    def apply_test_file(self, *, preview_token: str, relative_path: str, expected_file_sha256: str) -> dict[str, Any]:
        return self._verified_mutation(
            "/test-file/apply",
            {
                "previewToken": preview_token,
                "relativePath": self._relative_path(relative_path),
                "expectedFileSha256": expected_file_sha256,
            },
        )

    def run_registered_task(self, *, task_id: str) -> dict[str, Any]:
        """Run one bridge-enumerated task ID; never accept command text."""
        if not task_id or len(task_id) > 128 or any(character.isspace() for character in task_id):
            raise ValueError("The registered VS Code task ID is invalid.")
        result = self._request("/tasks/run", method="POST", payload={"taskId": task_id})
        if not result.get("ok") or result.get("registeredTask") is not True or result.get("focusUnchanged") is not True:
            raise RuntimeError(str(result.get("error") or "VS Code did not verify the registered task."))
        return result

    def preview_rename_symbol(self, *, new_name: str) -> dict[str, Any]:
        return self._verified_preview(
            self._request("/rename/preview", method="POST", payload={"newName": str(new_name)})
        )

    def apply_rename_symbol(
        self, *, preview_token: str, new_name: str, expected_document_version: int, expected_document_sha256: str
    ) -> dict[str, Any]:
        return self._verified_mutation(
            "/rename/apply",
            {
                "previewToken": preview_token,
                "newName": str(new_name),
                "expectedDocumentVersion": int(expected_document_version),
                "expectedDocumentSha256": expected_document_sha256,
            },
        )

    @staticmethod
    def _relative_path(value: str) -> str:
        text = str(value or "").replace("\\", "/").strip()
        path = PurePosixPath(text)
        if not text or path.is_absolute() or ".." in path.parts or ":" in text or len(text) > 240:
            raise ValueError("The test file must stay inside the current VS Code workspace.")
        return str(path)

    @staticmethod
    def _verified_preview(result: dict[str, Any]) -> dict[str, Any]:
        if not result.get("ok") or not result.get("previewToken") or result.get("applied") is True:
            raise RuntimeError(str(result.get("error") or "VS Code did not return a safe dry-run preview."))
        return result

    def _verified_mutation(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        result = self._request(path, method="POST", payload=payload)
        if not result.get("ok") or result.get("verified") is not True or result.get("focusUnchanged") is not True:
            if result.get("rolledBack") is not True:
                raise RuntimeError(
                    str(result.get("error") or "VS Code verification failed and rollback was not proved.")
                )
            raise RuntimeError(str(result.get("error") or "VS Code rolled back an unverified action."))
        return result
