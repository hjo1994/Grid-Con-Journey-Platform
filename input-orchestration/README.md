# Input Orchestration — Airflow DAGs

Eigenes Deployment. Drei DAGs entlang der Layer aus
`solution documentation/Architecture.drawio`:

```
grid_con_raw_to_bronze      import_GRONOS_requests   GRONOS-API → Bronze GronosExports
        │ Asset grid-con://bronze/GronosExports
        ▼
grid_con_bronze_to_silver   import_requests          GronosExports → BusinessTransactions,
                                                     GridConnectionRequests, -Customers
grid_con_bronze_to_gold     evaluate_requests        UserEvaluationInputs → BusinessTransactions,
        ▲                                            RequestEvaluationChecks
        └─ ausgelöst vom Backend (Airflow REST API), sobald eine Bewertung gespeichert wird
```

1. **RawToBronze** (`operators/gronos_raw_to_bronze.py`, `gronos.py`) — alle
   `GRONOS_SCHEDULE` (Default 30 min): OAuth-Token, Liste über
   companyId-Präfixe (bei 502/503/504 automatisch verfeinert, Duplikate über
   `objectId`), Delta gegen den neuesten `updatedAt` je `objectId` in Bronze,
   Detail je neuem/geändertem Antrag. Alles eines Laufs landet in **einer**
   Transaktion mit **einem** `Timestamp` in `GronosExports` (`Content` =
   Detail-JSON as is). Ohne Änderungen wird der Task übersprungen, dann gibt
   es kein Asset-Event. Fehler (außer 401 → neuer Token) brechen den Lauf ab,
   bevor etwas geschrieben wird.
2. **BronzeToSilver** (`operators/gronos_bronze_to_silver.py`,
   `writer.write_gronos_silver`) — ausgelöst durch das Asset-Event von
   RawToBronze. Verarbeitet alle `GronosExports` mit `Timestamp` >
   **InputBronzeTimestamp des vorherigen Laufs** (höchster Wert der
   BusinessTransactions mit `GronosExportID`). Je Bronze-Zeile eine
   BusinessTransaction; Kunde per `CompanyID` anlegen/aktualisieren; neuer
   Eintrag in `GridConnectionRequests` nur bei geänderten Werten gegenüber dem
   neuesten Eintrag derselben `GronosObjectID`. Mapping:
   `api-zugriff/proposal-bronze-gronosexport.md`, Abschnitt 2 (in `gronos.derive_*`).
3. **BronzeToGold** (`operators/bronze_to_gold.py`, `writer.write_gold`) —
   ausgelöst vom Backend nach jeder gespeicherten Bewertung, optional
   zusätzlich per `GRID_CON_GOLD_SCHEDULE`. Gleicht zuerst das
   Bewertungs-Framework ab (`evaluation_framework.py`, idempotent),
   verarbeitet dann alle `UserEvaluationInputs` mit `Timestamp` > dem
   InputBronzeTimestamp des vorherigen Laufs. Jede Eingabe bekommt eine
   BusinessTransaction. Vor dem Schreiben prüft der DAG das **Delta** gegen
   den neuesten Gold-Eintrag derselben Nutzer:in und desselben Checks
   (`writer.input_unchanged`): Nur wenn sich Verdict oder Punkte ändern oder
   ein neuer Kommentar dabei ist, entsteht ein Eintrag in
   `RequestEvaluationChecks` mit fortlaufender `Version` je Antrag
   (`id_gronos_new`), Nutzer:in und Check. Eine BusinessTransaction ohne
   Gold-Eintrag heißt „verarbeitet, unverändert“ (`rows_unchanged` in den
   Laufstatistiken). Eingaben, die nicht zum Framework passen, bekommen
   ebenfalls eine BusinessTransaction und werden mit Warnung übersprungen
   (`rows_rejected`); so rückt die Wasserlinie immer vor. Bronze bleibt
   vollständig (append-only).

**BusinessTransactions:** `Timestamp` = Zeitpunkt der Transformation Bronze →
Silver bzw. Gold, `InputBronzeTimestamp` = Timestamp der verarbeiteten
Bronze-Zeile. Genau eine Quelle ist gesetzt: `GronosExportID`,
`UserEvaluationInputID` oder `C4CExportID` (Legacy).

**Legacy:** Der bisherige DAG `grid_connection_requests_import` (Sensor auf
den C4C-Excel-Export → `C4CExports` → Silver) bleibt für lokale Läufe mit dem
anonymisierten Export erhalten. Die GRONOS-API ist nur aus dem Cluster
erreichbar.

**Einrichtung Bewertung** (Framework + Nutzer:innen, idempotent):

```bash
.venv/bin/python -m grid_con_ingestion.migrations.evaluation data/db/grid_con.db --users users.csv   # email,name,role
.venv/bin/python -m grid_con_ingestion.migrations.evaluation data/db/grid_con.db --demo              # nur lokal: 3 Prüfer:innen + 1 lesend
```

Rollen (`Users.Role`): `netzplanung`, `flaechen_recht`, `finanzen` (bewerten,
je eine Spalte in K1) und `viewer` (nur lesen).

**Kunden-Stammdaten (Legacy C4C):** Vor dem ersten BronceToSilver-Lauf des
C4C-Pfads einmalig die Kunden aus einem Export migrieren (idempotent):

```bash
.venv/bin/python -m grid_con_ingestion.migrations.customers data/source/<export>.xlsx data/db/grid_con.db
```

## Struktur

```
input-orchestration/
  pyproject.toml              # macht grid_con_ingestion im Airflow-Image importierbar
  requirements.txt            # apache-airflow>=3.0
  scripts/
    run_local.sh              # lokaler Airflow-Lauf ohne Docker/K8s
  dags/
    grid_con_raw_to_bronze_dag.py      # GRONOS-API → Bronze
    grid_con_bronze_to_silver_dag.py   # Bronze → Silver (Asset-getriggert)
    grid_con_bronze_to_gold_dag.py     # Bewertungen → Gold (vom Backend getriggert)
    grid_connection_requests_import_dag.py   # Legacy C4C-Excel
  grid_con_ingestion/
    config.py                 # SOURCE_DIR, GRID_CON_DB_PATH etc. aus Env-Variablen
    models.py                 # SQLAlchemy-Modelle = LogicalDataModel.drawio (Bronze, Silver, Gold, Config)
    gronos.py                 # GRONOS-API-Client, Ableitung Bronze-JSON → Silver
    evaluation_framework.py   # Kriterien, Sub-Kriterien, Checks des Reifegradverfahrens
    sources.py                # DataSource-Interface: FileSource, ApiSource (Platzhalter)
    writer.py                 # Bronce/Silver laden, atomarer Datei-Tausch
    migrations/
      customers.py            # Einmal-Migration der Kunden aus dem Export (Legacy)
      evaluation.py           # Framework + Nutzer:innen anlegen
    transforms/
      normalize.py            # Spaltenmapping, NULL-Handling, Validierung
    operators/
      gronos_raw_to_bronze.py
      gronos_bronze_to_silver.py
      bronze_to_gold.py
      source_sensor.py, raw_to_bronce.py, bronce_to_silver.py   # Legacy C4C
  tests/
```

## Lokal ausführen

```bash
./scripts/run_local.sh standalone          # einmalig: legt .venv + .airflow_home an, startet Airflow
./scripts/run_local.sh dags unpause grid_con_bronze_to_gold
./scripts/run_local.sh dags trigger grid_con_bronze_to_gold          # verarbeitet offene Bewertungen
./scripts/run_local.sh dags trigger grid_connection_requests_import  # Legacy: Excel-Export
```

Lokal liegen Quelle und Datenbank im Deployment-Ordner unter `data/`:
`input-orchestration/data/source/` (neue Exporte hier ablegen) und
`input-orchestration/data/db/grid_con.db` – das spiegelt `/opt/airflow/data/source`
und `/opt/airflow/data/db` im Deployment. Beides per Env-Variable überschreibbar.

Tests: `.venv/bin/pytest`

## Konfiguration

| Variable | Default (Deployment) |
|---|---|
| `GRID_CON_SOURCE_TYPE` | `file` (später `api`) |
| `SOURCE_DIR` | `/opt/airflow/data/source` |
| `SOURCE_FILENAME_GLOB` | `C4C_GRONOS_*.xlsx` |
| `GRID_CON_DB_PATH` | `/opt/airflow/data/db/grid_con.db` |
| `GRONOS_CONN_ID` | `grid_con_gronos_api` (Airflow Connection: host = Basis-URL, login = Client ID, password = Secret) |
| `GRONOS_BASE_URL`, `GRONOS_CLIENT_ID`, `GRONOS_CLIENT_SECRET` | leer; Fallback ohne Connection (lokal) |
| `GRONOS_COMPANY_PREFIXES` | `0 1 2 3 4 5 6 7 8 9` |
| `GRONOS_SCHEDULE` | `*/30 * * * *` |
| `GRID_CON_GOLD_SCHEDULE` | leer (nur ausgelöst); z. B. `*/5 * * * *` als Sicherheitsnetz |

## Schreibstrategie

Es gibt zwei Schreiber: Input Orchestration (alle Layer) und das Backend
(nur die Bronze-Tabelle `UserEvaluationInputs`). Der frühere atomare
Datei-Tausch (Arbeitskopie + `os.replace`) hätte Eingaben des Backends
zwischen Snapshot und Tausch verloren; deshalb schreibt `writer.py` jetzt
direkt in die aktive Datei, je Lauf in einer SQLite-Transaktion
(`BEGIN IMMEDIATE`, `busy_timeout` 30 s, FK-Prüfung vor dem COMMIT). SQLite
serialisiert die Schreiber über die Dateisperre, Leser sehen nie einen halben
Stand. Voraussetzung: ein Volume mit funktionierender Dateisperre (kein NFS
ohne Locking). Für mehr Last bleibt der Wechsel auf eine Server-DB der
nächste Schritt.

`ensure_schema` legt neue Tabellen/Spalten an und baut einmalig um: leere
Bewertungstabellen des früheren Entwurfs (INTEGER-IDs) werden entfernt,
`BusinessTransactions` wird auf das neue Schema umgebaut (IDs bleiben,
`Timestamp`/`InputBronzeTimestamp` werden für die C4C-Zeilen nachgetragen).

Alle Primärschlüssel (`ID`) und Fremdschlüssel sind UUIDs (uuid4, als Text);
Config-Tabellen haben sprechende Codes (`A`, `B3`, `B3-04`).

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


## Mapping Quelle → Datenmodell (Legacy C4C-Export)

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

## Verifiziert (04.11.2026)

22 Tests (`tests/`): Ableitung GRONOS-JSON → Silver, Präfix-Verfeinerung bei
504 inkl. Abbruch, Token-Erneuerung bei 401, Delta gegen Bronze, ein
Timestamp je Abruf, Wasserlinie BronzeToSilver/BronzeToGold, Änderungsprüfung,
Versionierung je Nutzer:in und Check (auch über neue Silver-Stände hinweg),
Delta in BronzeToGold (BusinessTransaction je Eingabe, Gold nur bei Änderung),
Framework gegen die Excel-Regeln, Umbau einer C4C-Datenbank. Alle vier DAGs
mit Airflow 3.1 geparst; `airflow dags test` für RawToBronze → BronzeToSilver
(gegen eine GRONOS-Attrappe) und BronzeToGold. Migration auf einer Kopie von
`grid_con.db`: 251 BusinessTransactions umgebaut, keine FK-Verletzungen.

### Früherer Stand (13.10.2026, C4C)

`data/db/grid_con.db` am 13.10.2026 neu aufgebaut (Sicherungen unter
`data/db/backup/`): 122 Kunden aus der Migration, 386 Zeilen in `C4CExports`,
249 Anfragen mit je einer BusinessTransaction; 136 Zeilen ohne Kundenangaben
übersprungen, Projekt-0250 aussortiert.

Simulierte Folgelieferung auf einer Kopie (Status von Projekt-0001 geändert,
ein neues Ticket mit bekanntem und eines mit unbekanntem Kunden): 2 neue
Einträge (zweiter Stand von Projekt-0001 und das neue Ticket mit bekanntem
Kunden), 248 unverändert übersprungen, 137 ohne Kunden übersprungen.
Abgedeckt durch `tests/test_ingestion.py`.
