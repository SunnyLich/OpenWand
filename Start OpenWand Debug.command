#!/usr/bin/env bash
# OpenWand debug launcher - keeps timestamped runtime logs under build_logs.
set -euo pipefail
cd "$(dirname "$0")"
export OPENWAND_RUNTIME_LOG_MODE=debug
export OPENWAND_KEEP_TERMINAL_ON_EXIT=1
exec bash "./Start OpenWand.command"
