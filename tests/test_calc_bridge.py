from __future__ import annotations

from pathlib import Path

from core.actions.adapters.calc.bridge import (
    configure_calc_connection,
    configured_calc_connection_pipe,
)


def test_calc_connection_configuration_preserves_existing_settings(tmp_path: Path) -> None:
    registry = tmp_path / "registrymodifications.xcu"
    registry.write_text(
        """<?xml version="1.0" encoding="UTF-8"?>
<oor:items xmlns:oor="http://openoffice.org/2001/registry">
<item oor:path="/org.openoffice.Office.Common/Misc"><prop oor:name="FirstRun"><value>false</value></prop></item>
</oor:items>
""",
        encoding="utf-8",
    )

    first = configure_calc_connection("openwand_calc_0123456789abcdef", tmp_path)
    second = configure_calc_connection("openwand_calc_0123456789abcdef", tmp_path)

    content = registry.read_text(encoding="utf-8")
    assert 'oor:name="FirstRun"' in content
    assert content.count('oor:name="ooSetupConnectionURL"') == 1
    assert configured_calc_connection_pipe(tmp_path) == "openwand_calc_0123456789abcdef"
    assert first["changed"] is True
    assert second["changed"] is False


def test_calc_connection_configuration_updates_only_openwands_endpoint(tmp_path: Path) -> None:
    configure_calc_connection("openwand_calc_0123456789abcdef", tmp_path)

    result = configure_calc_connection("openwand_calc_fedcba9876543210", tmp_path)

    content = (tmp_path / "registrymodifications.xcu").read_text(encoding="utf-8")
    assert "openwand_calc_0123456789abcdef" not in content
    assert "openwand_calc_fedcba9876543210" in content
    assert result["pipe_name"] == "openwand_calc_fedcba9876543210"


def test_calc_connection_configuration_generates_and_reuses_private_pipe(tmp_path: Path) -> None:
    first = configure_calc_connection(profile=tmp_path)
    second = configure_calc_connection(profile=tmp_path)

    pipe_name = str(first["pipe_name"])
    assert pipe_name.startswith("openwand_calc_")
    assert len(pipe_name) == len("openwand_calc_") + 32
    assert second["pipe_name"] == pipe_name
    assert second["changed"] is False
