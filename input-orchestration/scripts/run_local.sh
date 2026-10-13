#!/usr/bin/env bash
# Local dev runner for the Input Orchestration DAG — no Kubernetes, no
# Docker, just this folder's venv. Sets up an isolated AIRFLOW_HOME under
# this folder and execs whatever `airflow` subcommand is passed through,
# e.g.:
#   ./scripts/run_local.sh standalone
#   ./scripts/run_local.sh dags trigger grid_connection_requests_import
set -euo pipefail
cd "$(dirname "$0")/.."

if [ ! -d .venv ]; then
  python3 -m venv .venv
  .venv/bin/pip install -q --upgrade pip
  .venv/bin/pip install -q apache-airflow
  .venv/bin/pip install -q -e ".[test]"
fi
# shellcheck disable=SC1091
source .venv/bin/activate

export AIRFLOW_HOME="$(pwd)/.airflow_home"
export AIRFLOW__CORE__DAGS_FOLDER="$(pwd)/dags"
export AIRFLOW__CORE__LOAD_EXAMPLES=false
# Watched source folder and database, both under data/ in this deployment folder
# — mirrors /opt/airflow/data/source and /opt/airflow/data/db in
# the deployment.
export SOURCE_DIR="${SOURCE_DIR:-$(pwd)/data/source}"
export GRID_CON_DB_PATH="${GRID_CON_DB_PATH:-$(pwd)/data/db/grid_con.db}"

exec airflow "$@"
