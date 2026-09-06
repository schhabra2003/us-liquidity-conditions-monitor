#!/bin/zsh
set -euo pipefail

project_dir="${0:A:h}"
cd "$project_dir"

if [[ ! -x .venv/bin/python ]]; then
  python3.12 -m venv .venv 2>/dev/null || python3 -m venv .venv
  .venv/bin/python -m pip install --upgrade pip
  .venv/bin/python -m pip install -r requirements.txt
fi

exec .venv/bin/python -m streamlit run pages/Liquidity_Conditions_Monitor.py

