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
(`writer.py`). Gold (Bewertung) siehe „Bewertung (`dags/grid_con_bronze_to_gold_dag.py`)“;
RequestDocument ist vorerst nicht umgesetzt.

**Kunden-Stammdaten:** siehe „Lokal ausführen“.

## GRONOS-API (`dags/gronos_import_dags.py`)

Zwei DAGs, Datenmodell siehe `solution documentation/LogicalDataModel.drawio`
(PROPOSAL v3, lokal gepflegt):

```
gronos_raw_to_bronze     (Schedule, Standard alle 30 min)
  raw_to_bronze  -->  trigger_bronze_to_silver  --> gronos_bronze_to_silver
                      (wartet auf das Ende)            bronze_to_silver
```

1. **`raw_to_bronze`** (`grid_con_ingestion/gronos/store.py`) – OAuth-Token
   (Client Credentials), Liste je `companyId`-Präfix (`ConnectionRequest?companyId=<Präfix>*`,
   bei 502/503/504 automatisch in zehn Unterpräfixe geteilt, bis 7 Stellen),
   Duplikate über `objectId` entfernt. Nur neue objectIds und solche mit
   neuerem `updatedAt` als in Bronze werden per Detail-Endpunkt
   (`?id=<objectId>&companyId=<eigene companyId>*`, ca. 4 s je Aufruf) geholt
   und als eine Zeile je Anfrage an **`GronosExports`** angehängt (`ID`,
   `Timestamp` des Abrufs, `Content` = JSON as is). API-Fehler: Task schlägt
   fehl, nichts wird geschrieben.
2. **`bronze_to_silver`** – nach jedem erfolgreichen RawToBronze-Lauf. Liest
   alle `GronosExports` mit `Timestamp` > `MAX(BusinessTransactions.InputBronzeTimestamp)`,
   wandelt `Content` um (`gronos/transform.py`), Kunden über `CompanyID`,
   je Bronze-Zeile eine `BusinessTransactions`-Zeile (`InputBronzeTimestamp`,
   `Timestamp`); neuer Eintrag in `GridConnectionRequests` nur bei
   geänderten Werten.

| Variable | Standard | |
|---|---|---|
| `GRONOS_API_BASE_URL` | – | API-Management-Host des Tenants |
| `GRONOS_API_CLIENT_ID` / `GRONOS_API_CLIENT_SECRET` | – | aus einem OpenShift-Secret |
| `GRONOS_COMPANY_ID_PREFIXES` | `1000-1299` | Bereiche/Einzelwerte, kommagetrennt |
| `GRONOS_DETAIL_MODE` | `auto` | `auto`: Detail-Aufruf nur, wenn der Listeneintrag keine `contacts` hat (ACC: Liste vollständig; dev: Liste ohne `contacts`, also Detail). `always` / `never` erzwingen es. |
| `GRONOS_MAX_PREFIX_LENGTH` | `7` | |
| `GRONOS_API_TIMEOUT` | `150` | Sekunden je Aufruf |
| `GRONOS_API_USE_ENV_PROXY` | `false` | API ist vom Pod ohne Proxy erreichbar |
| `GRONOS_RAW_TO_BRONZE_SCHEDULE` | `*/30 * * * *` | |

`requests` kommt mit Airflow 2.10 mit (keine Änderung an `pyproject.toml`/`poetry.lock`).
Alle DAGs schreiben über `writer.write_transaction` (Alias `atomic_write`) direkt in die Datei, siehe „Schreibstrategie“.

**Bestehende Datenbank:** `BusinessTransactions.C4CExportID` war `NOT NULL`;
SQLite kann das nicht nachträglich ändern. Vor dem ersten GRONOS-Lauf die
Datenbank neu aufbauen (vorher Dump) und den Excel-DAG
`grid_connection_requests_import` pausieren.

Demo-Daten ohne API: `python scripts/seed_demo_gronos.py data/db/grid_con_demo.db`.

## Bewertung (`dags/grid_con_bronze_to_gold_dag.py`)

Kollaborative Reifegradbewertung (K1/K4 in der Monitoring-App,
`dedicated_env/backend_app`):

- **Config:** `Users` (E-Mail, Name, Rolle `netzplanung` | `flaechen_recht` |
  `finanzen` | `viewer`) und das Framework `EvaluationCriteria` →
  `EvaluationSubCriteria` → `EvaluationChecks` (39 Checks, Regeln aus der
  Bewertungs-Excel, `grid_con_ingestion/evaluation_framework.py`).
- **Bronze:** `UserEvaluationInputs` – das Backend hängt je gespeichertem
  Check eine Zeile an (append-only, ein `Timestamp` je Speichern).
- **Gold:** `RequestEvaluationChecks` – je Antrag (`id_gronos_new`, über alle
  Silver-Stände), Nutzer:in und Check fortlaufende `Version`.
- **DAG `grid_con_bronze_to_gold`**, Task `bronze_to_gold`
  (`writer.write_gold`): liest alle Eingaben mit `Timestamp` >
  `MAX(BusinessTransactions.InputBronzeTimestamp)` der Gold-Vorgänge. **Jede**
  Eingabe bekommt eine `BusinessTransactions`-Zeile (`UserEvaluationInputID`,
  `Timestamp` = Transformation, `InputBronzeTimestamp` = Eingabe). Vor dem
  Schreiben vergleicht der DAG mit dem letzten Gold-Eintrag derselben
  Nutzer:in und desselben Checks (`writer.input_unchanged`): ein neuer
  Gold-Eintrag nur bei anderem Verdict/Punktwert oder neuem Kommentar.
  Eingaben, die nicht zum Framework passen, werden übersprungen (Warnung).
  Das Framework wird bei jedem Lauf abgeglichen.
- **Auslösung:** das Backend nach jedem Speichern über die Airflow-REST-API
  (`POST /api/v1/dags/grid_con_bronze_to_gold/dagRuns`); optional zusätzlich
  `GRID_CON_GOLD_SCHEDULE` (empfohlen `*/15 * * * *` als Absicherung).
  `max_active_runs=1`.

Nutzer:innen anlegen bzw. aktualisieren (idempotent über die E-Mail; legt
auch Schema und Framework an):

```bash
python -m grid_con_ingestion.migrations.evaluation /data/db/grid_con.db --users users.csv
```

`users.csv` mit Kopfzeile `email,name,role`. `--demo` legt vier
Beispiel-Nutzer:innen an (nur lokal).

| Variable | Standard | |
|---|---|---|
| `GRID_CON_GOLD_DAG_ID` | `grid_con_bronze_to_gold` | muss zum Backend passen |
| `GRID_CON_GOLD_SCHEDULE` | leer (nur Auslösung) | z. B. `*/15 * * * *` |

Neue DAGs starten auf der Plattform pausiert; alle drei GRONOS-/Gold-DAGs
einschalten.

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
  gronos_import_dags.py       # gronos_raw_to_bronze, gronos_bronze_to_silver
  grid_con_bronze_to_gold_dag.py
  dependency_loader.py        # Laufzeit-Installation fehlender Pakete
  .airflowignore              # dependency_loader.py ist kein DAG
grid_con_ingestion/
  __init__.py                 # /tmp/airflow_packages in sys.path
  config.py                   # SOURCE_DIR, GRID_CON_DB_PATH etc. aus Env-Variablen
  models.py                   # SQLAlchemy-Modelle = LogicalDataModel.drawio (Bronze, Silver, Gold, Config)
  evaluation_framework.py     # Kriterien, Sub-Kriterien, Checks des Reifegradverfahrens
  sources.py                  # DataSource-Interface: FileSource, ApiSource (Platzhalter)
  writer.py                   # Schema, Schreibtransaktion, Excel-Import, Gold (write_gold)
  gronos/                     # GRONOS-API: client, transform, store
  migrations/
    customers.py              # Einmal-Migration der Kunden aus dem Export
    evaluation.py             # Framework + Nutzer:innen (CSV)
  transforms/
    normalize.py              # Spaltenmapping, NULL-Handling, Validierung
  operators/
    source_sensor.py
    raw_to_bronce.py
    bronce_to_silver.py
    gronos_raw_to_bronze.py, gronos_bronze_to_silver.py
    bronze_to_gold.py
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
| `GRID_CON_GOLD_DAG_ID`, `GRID_CON_GOLD_SCHEDULE` | siehe „Bewertung“ |

## Schreibstrategie

Zwei Schreiber: Input Orchestration (Bronze, Silver, Gold, Config) und das
Backend (nur `UserEvaluationInputs`). Deshalb schreibt `writer.write_transaction`
**direkt in die aktive Datei** in einer Transaktion (`BEGIN IMMEDIATE`,
`busy_timeout` 30 s, FK-Prüfung vor dem `COMMIT`, sonst `ROLLBACK`). SQLite
serialisiert die Schreiber über die Dateisperre; Leser sehen nie einen halben
Stand. Der frühere Datei-Tausch (Arbeitskopie + `os.replace`) hätte Eingaben
aus dem Backend zwischen Snapshot und Tausch verloren. Das Volume muss
deshalb auch im Backend **schreibbar** gemountet sein.

Neue Tabellen und Spalten legt `ensure_schema` in bestehenden Datenbanken an,
ohne vorhandene Zeilen anzufassen; `TimestampImportBronze`/`TimestampImportSilver`
werden dabei in `InputBronzeTimestamp`/`Timestamp` umbenannt.

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

**Offener Punkt:** SQLite mit zwei Schreibern auf einem geteilten Volume
ist eine Übergangslösung; bei mehr Last auf eine Server-DB wechseln.

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

05.11.2026: 30 Tests (`tests/`, SQLAlchemy 1.4), darunter Framework gegen die
Excel-Regeln, Nutzer-Upsert, BronzeToGold (Versionen je Nutzer:in und Check,
Delta: unveränderte Eingaben bekommen nur eine BusinessTransaction,
Wasserlinie, neue Silver-Stände), Umbenennung der BT-Spalten. Alle DAGs mit
Airflow 2.10.2 geparst, `airflow dags test grid_con_bronze_to_gold` erfolgreich.

### Früher (13.10.2026)


`data/db/grid_con.db` am 13.10.2026 neu aufgebaut (Sicherungen unter
`data/db/backup/`): 122 Kunden aus der Migration, 386 Zeilen in `C4CExports`,
249 Anfragen mit je einer BusinessTransaction; 136 Zeilen ohne Kundenangaben
übersprungen, Projekt-0250 aussortiert.

Simulierte Folgelieferung auf einer Kopie (Status von Projekt-0001 geändert,
ein neues Ticket mit bekanntem und eines mit unbekanntem Kunden): 2 neue
Einträge (zweiter Stand von Projekt-0001 und das neue Ticket mit bekanntem
Kunden), 248 unverändert übersprungen, 137 ohne Kunden übersprungen.
Abgedeckt durch `tests/test_ingestion.py`.
