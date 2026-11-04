"""RawToBronze: holt neue und geänderte Netzanschlussanträge aus der
GRONOS-API und legt sie as is in Bronze (GronosExports) ab.

    import_GRONOS_requests  ──(Asset GronosExports)──►  grid_con_bronze_to_silver

Zeitplan: GRONOS_SCHEDULE (Default alle 30 Minuten). Single writer je DAG:
max_active_runs=1.
"""
from __future__ import annotations

import datetime

from airflow.sdk import DAG, Asset

from grid_con_ingestion import config
from grid_con_ingestion.operators.gronos_raw_to_bronze import GronosRawToBronzeOperator

with DAG(
    dag_id="grid_con_raw_to_bronze",
    schedule=config.GRONOS_SCHEDULE,
    start_date=datetime.datetime(2026, 1, 1),
    catchup=False,
    max_active_runs=1,
    tags=["grid-con", "input-orchestration", "bronze"],
) as dag:
    GronosRawToBronzeOperator(
        task_id="import_GRONOS_requests",
        db_path=str(config.DB_PATH),
        conn_id=config.GRONOS_CONN_ID,
        prefixes=config.GRONOS_COMPANY_PREFIXES,
        outlets=[Asset(config.GRONOS_BRONZE_ASSET_URI)],
        retries=2,
        retry_delay=datetime.timedelta(minutes=2),
    )
