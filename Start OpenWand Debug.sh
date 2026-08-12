#!/usr/bin/env bash
# OpenWand debug launcher - keeps timestamped runtime logs under build_logs.
set -euo pipefail
cd "$(dirname "$0")"
export OPENWAND_RUNTIME_LOG_MODE=debug
exec bash "./Start OpenWand.sh"
