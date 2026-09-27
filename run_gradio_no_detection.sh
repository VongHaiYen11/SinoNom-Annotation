#!/usr/bin/env bash
set -euo pipefail

repo_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
python_bin="$repo_dir/.venv/bin/python"

if [[ ! -x "$python_bin" ]]; then
  echo "Missing $python_bin"
  echo "Create the repository virtual environment and install gradio/requirements.txt first."
  exit 1
fi

exec "$python_bin" "$repo_dir/gradio/app.py" \
  --config "$repo_dir/configs/tap_1.json" \
  --skip-detection \
  "$@"
