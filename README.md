# Grid Con Customer Journey

Netzanschlussanfragen aus C4C/GRONOS werden eingelesen, in einem zentralen
Datenmodell abgelegt und über eine standardisierte API für verschiedene
Applikationen bereitgestellt. Aufbau analog zum Referenzprojekt *AI Cockpit*.

## Architektur

Drei separate Deployments:

1. **`input-orchestration/`** — Airflow-DAG: Sensor (wartet auf eine neue
   Lieferung, heute Datei, später API), RawToBronce (Export as is in die
   Bronce-Tabelle) und BronceToSilver (BusinessTransactions und Anfragen,
   Polars, SQLite). Details:
   `input-orchestration/README.md`.
2. **`backend/`** — read-only FastAPI-Schnittstelle (`/api/v1`) auf die
   Silver-Tabellen. Details: `backend/README.md`.
3. **`frontend/`** — React-Applikation *(noch offen)*.

Datenmodell: [`solution documentation/LogicalDataModel.drawio`](solution%20documentation/LogicalDataModel.drawio),
umgesetzt in `input-orchestration/grid_con_ingestion/models.py`.

## Datenbank (Interim)

SQLite-Datei im Airflow-Deployment unter **`data/db/grid_con.db`**
(`/opt/airflow/data/db/grid_con.db`, lokal `input-orchestration/data/db/`).
Quell-Exporte liegen daneben unter **`data/source/`** (lokal `input-orchestration/data/source/`).
Input Orchestration ist der einzige Schreiber, das Backend liest nur
(gleiches Muster wie im AI Cockpit: atomarer Datei-Tausch).
