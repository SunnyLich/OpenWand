#!/usr/bin/env bash
# Regenerates locked requirement files from the shared human-edited manifests.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

if [ ! -s .python-version ]; then
  echo "ERROR: .python-version is required and must contain a Python version like 3.12 or 3.12.13." >&2
  exit 1
fi
WANT="$(tr -d '[:space:]' < .python-version)"
if [[ ! "$WANT" =~ ^[0-9]+\.[0-9]+(\.[0-9]+)?$ ]]; then
  echo "ERROR: .python-version must contain a Python version like 3.12 or 3.12.13." >&2
  exit 1
fi
WANT_MM="$(printf '%s' "$WANT" | cut -d. -f1,2)"

require_input() {
  local path="$1"
  if [ ! -s "$path" ]; then
    echo "ERROR: $path is required to compile dependency locks." >&2
    exit 1
  fi
}

if ! command -v uv >/dev/null 2>&1; then
  echo "uv is required to compile dependency lock files." >&2
  echo "Install it from https://docs.astral.sh/uv/ and rerun this script." >&2
  exit 1
fi

require_input requirements/requirements.txt
require_input requirements/requirements-dev.txt
require_input requirements/requirements-build.txt

compile_runtime_lock() {
  local platform="$1"
  local output="$2"
  uv pip compile requirements/requirements.txt \
    --upgrade \
    --no-header \
    --python-version "$WANT_MM" \
    --python-platform "$platform" \
    --output-file "$output"
  echo "Updated $output for $platform / Python $WANT_MM."
}

compile_universal_lock() {
  local input="$1"
  local output="$2"
  uv pip compile "$input" \
    --upgrade \
    --universal \
    --no-header \
    --python-version "$WANT_MM" \
    --output-file "$output"
  echo "Updated $output for Python $WANT_MM."
}

compile_optional_lock() {
  local platform="$1"
  local constraint="$2"
  local input="$3"
  local output="$4"
  mkdir -p "$(dirname "$output")"
  local extra=()
  if [[ "$input" == *kokoro-gpu.in ]]; then
    extra=(--index-strategy unsafe-best-match)
  fi
  uv pip compile "$input" \
    --upgrade \
    --no-header \
    --emit-index-url \
    --python-version "$WANT_MM" \
    --python-platform "$platform" \
    --constraint "$constraint" \
    --output-file "$output" \
    "${extra[@]}"
  echo "Updated $output for $platform / Python $WANT_MM."
}

compile_optional_target() {
  local name="$1"
  local platform="$2"
  local constraint="$3"
  shift 3
  local variants=("$@")
  local kind variant input_variant
  for kind in source release; do
    for variant in "${variants[@]}"; do
      input_variant="$variant"
      if [[ "$kind" == source && "$variant" == stt-cuda ]]; then
        input_variant=stt-cpu
      fi
      compile_optional_lock \
        "$platform" \
        "$constraint" \
        "requirements/optional/inputs/$input_variant.in" \
        "requirements/optional/$kind/$name/$variant.lock"
    done
  done
}

compile_optional_locks() {
  compile_optional_target windows-x64 x86_64-pc-windows-msvc requirements/requirements-windows.lock \
    stt-cpu stt-cuda kokoro-cpu kokoro-gpu elevenlabs live-voice
  compile_optional_target linux-x64 x86_64-manylinux_2_34 requirements/requirements-linux.lock \
    stt-cpu kokoro-cpu kokoro-gpu elevenlabs live-voice
  compile_optional_target macos-arm64 aarch64-apple-darwin requirements/requirements-macos.lock \
    stt-cpu kokoro-cpu elevenlabs live-voice
}

targets=("$@")
if [ "${#targets[@]}" -eq 0 ]; then
  targets=(all)
fi

for target in "${targets[@]}"; do
  case "$target" in
    all)
      compile_runtime_lock x86_64-pc-windows-msvc requirements/requirements-windows.lock
      compile_runtime_lock x86_64-manylinux_2_34 requirements/requirements-linux.lock
      compile_runtime_lock aarch64-apple-darwin requirements/requirements-macos.lock
      compile_universal_lock requirements/requirements-dev.txt requirements/requirements-dev.lock
      compile_universal_lock requirements/requirements-build.txt requirements/requirements-build.lock
      compile_optional_locks
      ;;
    windows)
      compile_runtime_lock x86_64-pc-windows-msvc requirements/requirements-windows.lock
      ;;
    linux)
      compile_runtime_lock x86_64-manylinux_2_34 requirements/requirements-linux.lock
      ;;
    macos)
      compile_runtime_lock aarch64-apple-darwin requirements/requirements-macos.lock
      ;;
    dev)
      compile_universal_lock requirements/requirements-dev.txt requirements/requirements-dev.lock
      ;;
    build)
      compile_universal_lock requirements/requirements-build.txt requirements/requirements-build.lock
      ;;
    optional)
      compile_optional_locks
      ;;
    *)
      echo "ERROR: unknown lock target '$target'. Use all, windows, linux, macos, dev, build, or optional." >&2
      exit 1
      ;;
  esac
done
