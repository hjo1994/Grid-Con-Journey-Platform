"""BronzeToGold: Eingaben der Prüfer:innen (UserEvaluationInputs) →
RequestEvaluationChecks.

Ausgelöst vom Backend nach jeder gespeicherten Bewertung
(``POST /api/v2/dags/grid_con_bronze_to_gold/dagRuns``), optional zusätzlich
per GRID_CON_GOLD_SCHEDULE. Verarbeitet alle Eingaben nach dem
InputBronzeTimestamp des vorherigen Laufs; max_active_runs=1 reiht
Auslösungen hintereinander ein.
"""
from __future__ import annotations

import datetime

from airflow.sdk import DAG

from grid_con_ingestion import config
from grid_con_ingestion.operators.bronze_to_gold import BronzeToGoldOperator

with DAG(
    dag_id="grid_con_bronze_to_gold",
    schedule=config.GOLD_SCHEDULE,
    start_date=datetime.datetime(2026, 1, 1),
    catchup=False,
    max_active_runs=1,
    tags=["grid-con", "input-orchestration", "gold"],
) as dag:
    BronzeToGoldOperator(task_id="evaluate_requests", db_path=str(config.DB_PATH))
