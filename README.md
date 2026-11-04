# Grid Con Customer Journey

Netzanschlussanfragen aus C4C/GRONOS werden eingelesen, in einem zentralen
Datenmodell abgelegt und über eine standardisierte API für verschiedene
Applikationen bereitgestellt. Aufbau analog zum Referenzprojekt *AI Cockpit*.

## Architektur

Drei separate Deployments:

1. **`input-orchestration/`** — drei Airflow-DAGs:
   *RawToBronze* (GRONOS-API-Abzug as is nach `GronosExports`),
   *BronzeToSilver* (per Asset ausgelöst, Anfragen und Kunden versioniert nach
   Silver) und *BronzeToGold* (übernimmt Bewertungseingaben aus
   `UserEvaluationInputs` nach `RequestEvaluationChecks`). Wasserlinie ist
   jeweils der `InputBronzeTimestamp` der letzten BusinessTransaction.
   Details: `input-orchestration/README.md`.
2. **`backend/`** — FastAPI (`/api/v1`): liest Silver/Gold/Config und schreibt
   als einzigen Schreibpfad Bewertungseingaben nach Bronze
   (`UserEvaluationInputs`), danach stößt es BronzeToGold an. Details:
   `backend/README.md`.
3. **`monitoring-app/`** — React-Applikation: Antragsübersicht, K1
   (Reifegradbewertung, eine Spalte je Prüfer:in, live) und K4 (Verlauf).
   Details: `monitoring-app/README.md`.

Datenmodell: [`solution documentation/LogicalDataModel.drawio`](solution%20documentation/LogicalDataModel.drawio),
umgesetzt in `input-orchestration/grid_con_ingestion/models.py`.

## Datenbank (Interim)

SQLite-Datei im Airflow-Deployment unter **`data/db/grid_con.db`**
(`/opt/airflow/data/db/grid_con.db`, lokal `input-orchestration/data/db/`).
Quell-Exporte liegen daneben unter **`data/source/`** (lokal `input-orchestration/data/source/`).
Zwei Schreiber: Input Orchestration (Bronze, Silver, Gold, Config) und das
Backend (nur `UserEvaluationInputs`). Deshalb wird nicht mehr per atomarem
Datei-Tausch geschrieben, sondern in place in kurzen Transaktionen
(`BEGIN IMMEDIATE`, `busy_timeout`); das Volume muss für das Backend
schreibbar gemountet sein. Lesende Zugriffe bleiben `mode=ro`.
