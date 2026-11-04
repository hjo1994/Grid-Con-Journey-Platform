"""BronzeToSilver: GronosExports → GridConnectionRequests / -Customers.

Ausgelöst durch RawToBronze (Asset GronosExports). Verarbeitet alle
Bronze-Zeilen nach dem InputBronzeTimestamp des vorherigen Laufs.
"""
from __future__ import annotations

import datetime

from airflow.sdk import DAG, Asset

from grid_con_ingestion import config
from grid_con_ingestion.operators.gronos_bronze_to_silver import GronosBronzeToSilverOperator

with DAG(
    dag_id="grid_con_bronze_to_silver",
    schedule=[Asset(config.GRONOS_BRONZE_ASSET_URI)],
    start_date=datetime.datetime(2026, 1, 1),
    catchup=False,
    max_active_runs=1,
    tags=["grid-con", "input-orchestration", "silver"],
) as dag:
    GronosBronzeToSilverOperator(task_id="import_requests", db_path=str(config.DB_PATH))
