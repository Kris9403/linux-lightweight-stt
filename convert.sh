#!/usr/bin/env bash
# One-off: export openai/whisper-small to an INT8 OpenVINO model in
# whisper-small-ov/. Uses a throwaway venv so optimum/nncf/torch never touch
# the runtime environment.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
OUT="$HERE/whisper-small-ov"

if [ -d "$OUT" ] && [ -n "$(ls -A "$OUT" 2>/dev/null)" ]; then
  echo "$OUT is already populated; delete it to re-export."
  exit 0
fi

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

python3 -m venv "$TMP/venv"
"$TMP/venv/bin/pip" install --upgrade pip
"$TMP/venv/bin/pip" install "optimum[openvino]" nncf

"$TMP/venv/bin/optimum-cli" export openvino \
  --model openai/whisper-small \
  --task automatic-speech-recognition-with-past \
  --weight-format int8 \
  "$OUT"

echo "Exported to $OUT"
