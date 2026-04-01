#!/usr/bin/env bash
set -euo pipefail

MINERU_RUNTIME_ROOT="${MINERU_RUNTIME_ROOT:-/opt/mineru-runtime}"
MINERU_VERSION="${MINERU_VERSION:-3.0.1}"
MINERU_BUILD_MODEL_SOURCE="${MINERU_BUILD_MODEL_SOURCE:-modelscope}"
MINERU_BUILD_MODEL_TYPE="${MINERU_BUILD_MODEL_TYPE:-pipeline}"
MINERU_BUILD_MODEL_TREE_SHA256="${MINERU_BUILD_MODEL_TREE_SHA256:-}"

export MINERU_TOOLS_CONFIG_JSON="${MINERU_TOOLS_CONFIG_JSON:-${MINERU_RUNTIME_ROOT}/config/mineru.json}"
export HF_HOME="${HF_HOME:-${MINERU_RUNTIME_ROOT}/cache/huggingface}"
export MODELSCOPE_CACHE="${MODELSCOPE_CACHE:-${MINERU_RUNTIME_ROOT}/cache/modelscope}"
export XDG_CACHE_HOME="${XDG_CACHE_HOME:-${MINERU_RUNTIME_ROOT}/cache}"
export MINERU_BUILD_MODEL_TYPE

mkdir -p \
  "${MINERU_RUNTIME_ROOT}" \
  "$(dirname "${MINERU_TOOLS_CONFIG_JSON}")" \
  "${HF_HOME}" \
  "${MODELSCOPE_CACHE}" \
  "${XDG_CACHE_HOME}"

python -m venv "${MINERU_RUNTIME_ROOT}"
"${MINERU_RUNTIME_ROOT}/bin/pip" install --no-cache-dir --upgrade pip setuptools wheel
"${MINERU_RUNTIME_ROOT}/bin/pip" install --no-cache-dir "mineru[core]==${MINERU_VERSION}"
# MinerU 3.0.1 pipeline runtime imports albumentations dynamically.
# Install it explicitly so the runtime image stays self-contained.
"${MINERU_RUNTIME_ROOT}/bin/pip" install --no-cache-dir "albumentations==2.0.8"

export MINERU_MODEL_SOURCE="${MINERU_BUILD_MODEL_SOURCE}"
"${MINERU_RUNTIME_ROOT}/bin/mineru-models-download" \
  -s "${MINERU_BUILD_MODEL_SOURCE}" \
  -m "${MINERU_BUILD_MODEL_TYPE}"

if [ -n "${MINERU_BUILD_MODEL_TREE_SHA256}" ]; then
  ACTUAL_MODEL_TREE_SHA256="$(
    "${MINERU_RUNTIME_ROOT}/bin/python" - <<'PY'
import hashlib
import json
import os
from pathlib import Path

config_path = Path(os.environ["MINERU_TOOLS_CONFIG_JSON"])
with config_path.open("r", encoding="utf-8") as handle:
    config = json.load(handle)

model_dirs = config.get("models-dir", {})
model_type = os.environ.get("MINERU_BUILD_MODEL_TYPE", "pipeline")
selected_dirs = []
if model_type == "all":
    selected_dirs = [Path(path) for _name, path in sorted(model_dirs.items()) if path]
else:
    selected_path = model_dirs.get(model_type)
    if selected_path:
        selected_dirs = [Path(selected_path)]

hasher = hashlib.sha256()
for model_dir in selected_dirs:
    for path in sorted(model_dir.rglob("*")):
        if not path.is_file():
            continue
        hasher.update(f"{model_dir.name}/{path.relative_to(model_dir)}".encode("utf-8"))
        hasher.update(b"\0")
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                hasher.update(chunk)

print(hasher.hexdigest())
PY
  )"

  if [ "${ACTUAL_MODEL_TREE_SHA256}" != "${MINERU_BUILD_MODEL_TREE_SHA256}" ]; then
    echo "MinerU model tree hash mismatch: expected ${MINERU_BUILD_MODEL_TREE_SHA256}, got ${ACTUAL_MODEL_TREE_SHA256}" >&2
    exit 1
  fi
fi
