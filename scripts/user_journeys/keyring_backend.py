"""Disposable credential-store boundary for hosted CI; never a personal keychain.

The real Settings save and worker reload code uses the normal keyring API. Only
the external credential vault is replaced, explicitly recorded in every report.
"""

from __future__ import annotations

import json
import os
import uuid
from pathlib import Path

from keyring.backend import KeyringBackend
from keyring.errors import PasswordDeleteError


class DisposableKeyring(KeyringBackend):
    """Persist test credentials across actual app restarts in one private run."""

    priority = 1

    @staticmethod
    def _path() -> Path:
        root = Path(os.environ["OPENWAND_E2E_STATE"]).resolve()
        if not (root / ".user-journey-state").is_file():
            raise RuntimeError("The disposable credential store needs a marked E2E directory")
        return root / "credentials.json"

    def get_password(self, service, username):
        path = self._path()
        values = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
        return values.get(service, {}).get(username)

    def set_password(self, service, username, password):
        path = self._path()
        values = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
        values.setdefault(service, {})[username] = password
        temporary = path.with_suffix(f".{uuid.uuid4().hex}.tmp")
        temporary.write_text(json.dumps(values), encoding="utf-8")
        temporary.replace(path)

    def delete_password(self, service, username):
        if self.get_password(service, username) is None:
            raise PasswordDeleteError("No disposable credential exists")
        path = self._path()
        values = json.loads(path.read_text(encoding="utf-8"))
        del values[service][username]
        path.write_text(json.dumps(values), encoding="utf-8")
