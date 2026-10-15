# Input Orchestration — Airflow DAG

Eigenes Deployment auf der Airflow-Plattform (Airflow 2.10.2, Python 3.11).
Dieser Branch (`dedicated_env/input_orchestration`) enthält nur die Workflow
Orchestration aus `main`, mit der Projektwurzel als Repo-Wurzel; Backend und
Monitoring-App liegen in `dedicated_env/backend_app`. Ein DAG (`dags/grid_connection_requests_import_dag.py`)
mit drei Tasks entlang der Layer aus `solution documentation/Architecture.drawio`:

```
wait_for_source  ──►  raw_to_bronce  ──►  bronce_to_silver
```

1. **`SourceSensor`** (`grid_con_ingestion/operators/source_sensor.py`)
   — wartet auf eine neue Lieferung. Heute: `FileSource` – neueste Datei
   `C4C_GRONOS_*.xlsx` im Quellordner, die fertig geschrieben ist (Größe
   stabil) und sich seit dem letzten erfolgreichen Import geändert hat
   (Marker-Datei `.grid_con_import.last_processed` im Quellordner). Später:
   `ApiSource` – Umschalten per `GRID_CON_SOURCE_TYPE=api`, ohne DAG oder
   Operatoren anzufassen (`grid_con_ingestion/sources.py`).
2. **`RawToBronceOperator`** (`grid_con_ingestion/operators/raw_to_bronce.py`)
   — liest die Lieferung as is mit Polars und hängt sie an die Bronce-Tabelle
   `C4CExports` an (Originalspalten, alle Werte Text, plus `FileSha`,
   `FileName`, `Timestamp`). Gleicher Dateiinhalt (FileSha) wird nicht erneut
   geladen. Quittiert die Lieferung und gibt den FileSha per XCom weiter.
3. **`BronceToSilverOperator`** (`grid_con_ingestion/operators/bronce_to_silver.py`)
   — Upsert der Bronce-Zeilen einer Lieferung gegen `GridConnectionRequests`.
   Übersprungen werden Zeilen ohne passenden Kunden in
   `GridConnectionCustomers` (Warnung im Task-Log, Kunden werden hier nie
   angelegt) und Zeilen mit identischen Werten zum neuesten Eintrag des
   Tickets (Ticketname + Ticket ID). Alle anderen (neues Ticket oder mindestens ein geänderter Wert)
   bekommen zuerst einen Eintrag in `BusinessTransactions` und dann einen
   komplett neuen Eintrag in `GridConnectionRequests` mit neuer UUID.

Alles landet in der zentralen SQLite-Datei **`/data/db/grid_con.db`**
(`writer.py`). Gold (`silver_to_gold`, RequestDocument,
RequestEvaluationChecks, Evaluation*) ist vorerst nicht umgesetzt.

**Kunden-Stammdaten:** siehe „Lokal ausführen“.

## Anpassungen an die Plattform (gegenüber `main`)

| Thema | `main` | dieser Branch |
|---|---|---|
| Airflow | 3.x (`airflow.sdk`) | 2.10.2: `from airflow import DAG`, `airflow.models.baseoperator.BaseOperator`, `airflow.sensors.base.BaseSensorOperator` |
| SQLAlchemy | 2.x | 1.4 (Vorgabe von Airflow 2.10); der Code nutzt nur die 1.4-kompatible API |
| Paketierung | setuptools, `requirements.txt` | Poetry (`pyproject.toml`) mit dem Artifactstore als Quelle; `requirements.txt` zur Info |
| Zusatzpakete | im eigenen venv | `dags/dependency_loader.py` installiert polars, fastexcel und pyarrow beim DAG-Parsen nach `/tmp/airflow_packages` (das Plattform-Image bringt sie nicht mit) |
| Struktur | `input-orchestration/…` | Projektwurzel = Repo-Wurzel; das Repo wird als Ganzes in den DAG-Ordner synchronisiert, der DAG ergänzt die Wurzel im `sys.path` |
| Pfade | `/opt/airflow/data/…` | `/data/source`, `/data/db/grid_con.db` (Volume) |
| Lokaler Runner | `scripts/run_local.sh` | entfällt, siehe unten |

## Struktur

```
pyproject.toml                # Poetry: Airflow 2.10.2, polars, fastexcel, pyarrow, SQLAlchemy 1.4
requirements.txt              # Info, entspricht pyproject.toml
dags/
  grid_connection_requests_import_dag.py
  dependency_loader.py        # Laufzeit-Installation fehlender Pakete
  .airflowignore              # dependency_loader.py ist kein DAG
grid_con_ingestion/
  __init__.py                 # /tmp/airflow_packages in sys.path
  config.py                   # SOURCE_DIR, GRID_CON_DB_PATH etc. aus Env-Variablen
  models.py                   # SQLAlchemy-Modelle = LogicalDataModel.drawio (Bronce + Silver)
  sources.py                  # DataSource-Interface: FileSource, ApiSource (Platzhalter)
  writer.py                   # Bronce/Silver laden, atomarer Datei-Tausch
  migrations/
    customers.py              # Einmal-Migration der Kunden aus dem Export
  transforms/
    normalize.py              # Spaltenmapping, NULL-Handling, Validierung
  operators/
    source_sensor.py
    raw_to_bronce.py
    bronce_to_silver.py
tests/
```

## Lokal ausführen

Airflow 2.10.2 braucht Python 3.11:

```bash
python3.11 -m venv .venv
.venv/bin/pip install "apache-airflow==2.10.2" \
  --constraint "https://raw.githubusercontent.com/apache/airflow/constraints-2.10.2/constraints-3.11.txt"
.venv/bin/pip install "polars>=1.9" "fastexcel>=0.12" "pyarrow>=15" pytest

export AIRFLOW_HOME="$(pwd)/.airflow_home" AIRFLOW__CORE__DAGS_FOLDER="$(pwd)/dags" AIRFLOW__CORE__LOAD_EXAMPLES=false
export SOURCE_DIR="$(pwd)/data/source" GRID_CON_DB_PATH="$(pwd)/data/db/grid_con.db"
.venv/bin/airflow standalone
```

Neue Exporte lokal unter `data/source/` ablegen (gitignored).

Kunden-Stammdaten: vor dem ersten BronceToSilver-Lauf einmalig migrieren
(idempotent, vorhandene IDs bleiben):

```bash
.venv/bin/python -m grid_con_ingestion.migrations.customers data/source/<export>.xlsx data/db/grid_con.db
```

Tests: `.venv/bin/pytest` (laufen ohne Airflow).

## Konfiguration

| Variable | Default (Deployment) |
|---|---|
| `GRID_CON_SOURCE_TYPE` | `file` (später `api`) |
| `SOURCE_DIR` | `/data/source` |
| `SOURCE_FILENAME_GLOB` | `C4C_GRONOS_*.xlsx` |
| `GRID_CON_DB_PATH` | `/data/db/grid_con.db` |

## Schreibstrategie

Input Orchestration ist der einzige Schreiber, das Backend liest nur.
`writer.py` zieht den aktiven Stand per SQLite-Backup-API in eine
Arbeitskopie (`grid_con.new.db`), lädt dort und schaltet sie per atomarem
`os.replace` aktiv – das Backend sieht nie einen halben Stand. Das gilt für
RawToBronce, BronceToSilver und die Kunden-Migration gleichermaßen. Neue
Tabellen und Spalten legt `ensure_schema` in bestehenden Datenbanken an,
ohne vorhandene Zeilen anzufassen.

Alle Primärschlüssel (`ID`) und Fremdschlüssel sind UUIDs (uuid4, als Text), vergeben im Writer.

Bronce ist append-only (eine Zeile je Exportzeile und Lieferung). Silver ist
ebenfalls append-only: Bestehende Einträge in `GridConnectionRequests` werden
nie geändert, je Ticket entsteht eine Historie. Der neueste Eintrag
(`timestamp`) ist der aktuelle Stand; über `BusinessTransactionID` →
`C4CExports` ist nachvollziehbar, aus welcher Lieferung er stammt.

Abweichung vom AI-Cockpit-Referenzprojekt (dort Vollimport in leere Datei):
hier **Upsert** gegen den Bestand. Ein Ticket ist die Kombination aus
`id_gronos_old` (Ticketname) und `id_gronos_new` (Ticket ID); zwei Zeilen mit
derselben Ticket ID, aber verschiedenem Ticketnamen sind verschiedene Tickets.
Innerhalb einer Lieferung wird nicht dedupliziert: jede gültige Zeile, die
nicht identisch zum neuesten Eintrag ihres Tickets ist, wird ein neuer
Eintrag. Kunden werden über Name + Kontakt + E-Mail gefunden.

**Offener Punkt:** Sollen die Bewertungstabellen später von einem anderen
Deployment beschrieben werden, gibt es zwei Schreiber – dann reicht der
Datei-Tausch nicht mehr (Änderungen zwischen Snapshot und Tausch gingen
verloren). Spätestens dann auf eine Server-DB wechseln.

## Mapping Quelle → Datenmodell

Die Spaltenüberschriften im Export sind verschoben (z. B. steht der Status
unter „Official request date“). Bronce übernimmt sie unverändert; beim Schritt
nach Silver wird **positionsbasiert** mit korrigierten Namen gemappt
(`transforms/normalize.py`, `RAW_COLUMNS`).

| Zielspalte | Quelle (Excel-Spalte) | Regel |
|---|---|---|
| `GridConnectionRequests.id_gronos_old` | Ticket (A) | „Projekt-xxxx“ |
| `id_gronos_new` | Ticket ID (B) | Integer |
| `RequestStatus` | Status (C) | |
| `SubstationLocation` | Plant Location Address (AA) | Annahme |
| `GenerationTechnology` | Connection Technology (AD), sonst Anschlusstechnologie (I) | mehrere Werte „ \| “-getrennt |
| `Substation50Hertz` | Anschlusspunkt (K) | Annahme |
| `maxP` | Installed Capacity (AF) | MW, Summe bei mehreren Werten |
| `SwitchCount` | Anschlusslösung (L) | „2 Schaltfelder …“ → 2, „Schaltfeld …“ → 1, sonst NULL |
| `DocumentURL` | ELO-Link (J) | |
| `RequestComment` | Description (AC) | im aktuellen Export leer |
| `GridConnectionCustomers.CustomerName` | Stakeholder (P) | |
| `CustomerContactPerson` | Contact Name (W) | |
| `CustomerContactPersonEmail` | E-Mail (X) | lowercase |

**NULL-Handling:** Werte werden getrimmt; `""`, `"#"` und `"Nicht zugeordnet"`
werden als `NULL` abgelegt (`NULL_TOKENS`).

**Fehlerhafte Zeilen** (im aktuellen Export: Projekt-0250, durch ein Komma im
Ticketnamen verschoben) werden nicht geladen und nur als Warnung im
Task-Log ausgegeben (inkl. Ticketname).

## Verifiziert

`data/db/grid_con.db` am 13.10.2026 neu aufgebaut (Sicherungen unter
`data/db/backup/`): 122 Kunden aus der Migration, 386 Zeilen in `C4CExports`,
249 Anfragen mit je einer BusinessTransaction; 136 Zeilen ohne Kundenangaben
übersprungen, Projekt-0250 aussortiert.

Simulierte Folgelieferung auf einer Kopie (Status von Projekt-0001 geändert,
ein neues Ticket mit bekanntem und eines mit unbekanntem Kunden): 2 neue
Einträge (zweiter Stand von Projekt-0001 und das neue Ticket mit bekanntem
Kunden), 248 unverändert übersprungen, 137 ohne Kunden übersprungen.
Abgedeckt durch `tests/test_ingestion.py`.
