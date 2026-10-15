# Backend — FastAPI + SQLAlchemy

Eigenes Deployment. Stellt die Silver-Tabellen der zentralen Datenbank über
eine **read-only** REST-API bereit. Die Endpunkte bilden Ressourcen ab, keine
Ansichten einer bestimmten App: Darstellungslogik (Prozessschritt,
C4C-Deeplink, Widget-Zuschnitt) rechnet der jeweilige Konsument. Kein
Schreibpfad.

Interaktive Doku: `/api/docs` (Swagger UI offline aus `swagger-ui-bundle`,
ohne CDN, `app/docs.py`), Schema unter `/api/openapi.json` (OpenAPI 3.0.3).
Beides ohne Anmeldung.

## Endpunkte (`/api/v1`)

| Endpunkt | Zweck |
|---|---|
| `GET /grid-connection-requests` | Liste. Standard: je `id_gronos_new` der neueste Eintrag (spätester `timestamp`), `versions=all` liefert alle Einträge. Filter `q` (Teilstring in Ticket-ID, Projekt, Kundenname), `request_status`, `exclude_status`, `generation_technology`, `customer_id`, `substation_50hertz` (alle mehrfach angebbar); `sort` (`id_gronos_new`, `id_gronos_old`, `request_status`, `generation_technology`, `max_p`, `substation_50hertz`, `customer_name`, `timestamp`), `order`, `limit` (1–500, Default 50), `offset`. Antwort `{items, total, limit, offset, data_as_of}` |
| `GET /grid-connection-requests/{id_gronos_new}` | Aktueller Stand eines Tickets mit allen Silver-Feldern; `expand=customer` bettet den Kunden ein |
| `GET /grid-connection-requests/aggregate` | `group_by=request_status\|generation_technology\|substation_50hertz\|customer_id`, je Gruppe `count` und `sum_max_p` (MW), dieselben Filter wie die Liste. `split_multi=true` (nur Technologie): „A \| B“ zählt bei A und bei B, `max_p` wird gleichmäßig aufgeteilt. `total` = Anzahl Anfragen |
| `GET /grid-connection-customers` | Kunden; `q` (Name, Kontakt, E-Mail), `sort`, `order`, `limit`, `offset` |
| `GET /grid-connection-customers/{id}` | Ein Kunde |
| `GET /grid-connection-customers/{id}/grid-connection-requests` | Anfragen des Kunden, gleiche Parameter wie die Liste |
| `GET /request-statuses` | Status mit `order`, `phase`, `in_process` aus der Backend-Konfiguration, danach Status aus den Daten, die nicht konfiguriert sind (`configured: false`, `order: null`) |
| `GET /meta` | `api_version`, `data_as_of` |
| `GET /api/healthz` | Liveness, ohne Auth, prüft nicht die DB |
| `GET /api/auth/rights` | angemeldeter Nutzer und seine Rechte (für das Frontend) |

**Feldnamen:** die Silver-Spalten in snake_case (`RequestStatus` →
`request_status`, `maxP` → `max_p`, `CustomerID` → `customer_id`). Zeitstempel
als ISO 8601 in UTC (`…Z`).

**Aktueller Stand:** Filter wirken immer *nach* der Auswahl des neuesten
Eintrags. `request_status=Offen` findet also kein Ticket, das früher „Offen“
war und heute „Eingestellt“ ist; dafür `versions=all`.

**Technologie-Filter:** trifft ganze Einzelwerte in „A | B“
(`generation_technology=Batterie` findet „Batterie | Biomasse“, `Wind` findet
weder „Wind Onshore“ noch „Windkraft“).

**Sortierung:** `sort=request_status` folgt der Prozessreihenfolge aus
`/request-statuses`, nicht dem Alphabet. Fehlende Werte stehen in beiden
Richtungen am Ende (portabel über `IS NULL`, kein `NULLS LAST`).

## Authentifizierung

Wie im AI-Cockpit-Backend: `eg-auth` mit `authorizer()` als
Router-Abhängigkeit (`app/auth.py`). Alle Endpunkte unter `/api/v1` und
`/api/auth/rights` verlangen einen angemeldeten Nutzer, `/api/healthz` und
die Doku nicht. Gesteuert über `EG_AUTH_DEV_MODE` und `EG_AUTH_DEV_GROUPS`
(siehe `.env.example`).

- **Im Cluster:** `eg-auth` (Extra `fastapi`, Version 1.0.0) kommt vom
  Firmen-Spiegel (`pyproject.toml`); `EG_AUTH_DEV_MODE=False`. Dann prüft das
  echte Paket das OIDC-Token.
- **Lokal:** `local_stubs/eg_auth` mit `EG_AUTH_DEV_MODE=True`; `app/main.py`
  hängt den Stub nur dann an den `sys.path`. Der Stub kann nur den Dev-Modus
  und antwortet sonst mit 401, siehe `local_stubs/README.md`.
- **Rechte:** Aktuell genügt Anmeldung. `canViewGridConnectionRequests` wird
  aus einer Platzhaltergruppe des AI Cockpit abgeleitet und ist nur
  informativ, bis die Grid-Con-Gruppe feststeht (TODO in `app/auth.py`).
- Getestet gegen den **Stub** (Gating, 401 ohne Anmeldung, Rechte aus
  Gruppen). Das Verhalten des echten `eg-auth` ist nicht geprüft.

## Status-Konfiguration

Reihenfolge und Phasen stehen in `app/config.py` (`PROCESS_PHASES`,
`OUTSIDE_PROCESS`), übernommen aus dem abgestimmten Monitoring-Entwurf:
Eingang (Standortanfrage eingegangen, Standortcheck durchgeführt,
Netzanschlussantrag eingegangen), Prüfung (Netztechnische Prüfung positiv
intern/extern), Reservierung & Umsetzung (Reservierungsangebot angenommen,
AEV-Kick Off erfolgt, Meilenstein 4 erreicht); „Offen“ und „Eingestellt“
außerhalb des Prozesses. **Die fachliche Bestätigung der Reihenfolge steht
noch aus.**

## Verhalten gegenüber der geteilten SQLite-Datei

Wie im AI-Cockpit-Backend:

- Die Datei wird auf SQLite-Ebene `mode=ro` geöffnet (getestet).
- **Kein Connection-Pool** (`NullPool`): Input Orchestration ersetzt die Datei
  per atomarem Rename, jede Anfrage öffnet sie neu (getestet).
- Schlägt das Öffnen fehl, 3 Versuche mit kurzem Backoff, danach `503` +
  `Retry-After` (getestet mit fehlender Datei).

## Struktur

```
backend/
  pyproject.toml           # Poetry-Format (Cluster-Build)
  requirements-local.txt   # nur lokal, ohne Poetry/Spiegel
  app/
    main.py          # get_app(); app = get_app() für uvicorn
    auth.py          # eg-auth: Rights, authorizer(), /api/auth/rights
    docs.py          # Swagger UI offline unter /api/docs
    config.py        # GRID_CON_DB_PATH (Default /data/db/grid_con.db), Status-Katalog
    db.py            # read-only Engine, Session mit Retry
    models.py        # Kopie der Silver-Modelle aus input-orchestration (von Hand synchron halten)
    queries.py       # gemeinsame Filter, "neuester Eintrag je Ticket"
    schemas.py
    api/requests.py, api/customers.py, api/reference.py
  local_stubs/eg_auth/     # Stub von eg-auth, nur lokal
  tests/             # synthetische Test-DB, keine echten Daten
```

`app/models.py` ist eine von Hand gepflegte Kopie des Silver-Teils von
`grid_con_ingestion/models.py` im Branch `dedicated_env/input_orchestration`
(separate Deployments, kein gemeinsames Paket). Bronce (`C4CExports`) liest das Backend nicht.

## Lokal starten

```bash
cd backend
python3 -m venv .venv && .venv/bin/pip install -r requirements-local.txt
EG_AUTH_DEV_MODE=True EG_AUTH_DEV_GROUPS='["app_50hzt_aap_communities_all__x"]' \
GRID_CON_DB_PATH=/pfad/zu/grid_con.db \
  .venv/bin/uvicorn app.main:app --port 8000
.venv/bin/python -m pytest
```

Startkommando im Deployment:
`uvicorn app.main:app --host 0.0.0.0 --port 8000` (ohne `PYTHONPATH`).
ConfigMap: `GRID_CON_DB_PATH` (Volume read-only), `EG_AUTH_DEV_MODE=False`. Die `poetry.lock` fehlt noch
und muss wie beim AI Cockpit im Firmennetz mit Poetry 1.8.5 erzeugt werden.

## Offen

- **Berechtigungsgruppe:** Platzhalter aus dem AI Cockpit, bis Grid Con
  einen eigenen OIDC-Client und eine eigene Gruppe hat.
- **Ticket-Schlüssel:** Die API identifiziert ein Ticket über `id_gronos_new`
  (abgestimmt). Input Orchestration behandelt dagegen Ticketname + Ticket-ID
  als Ticket. In der aktuellen DB hat die Ticket-ID 23322 Einträge unter drei
  Ticketnamen (Projekt-0291, -0001, -0002); die API zeigt davon nur den
  neuesten (Projekt-0002).

## Verifiziert

27 Tests gegen eine synthetische Test-DB (aktueller Stand vs. Historie,
alle Filter, Suche inkl. `%`/`_`-Escaping, Sortierung nach Prozessreihenfolge
und mit NULLs, Paginierung, Detail mit/ohne Kunde, Aggregation inkl.
`split_multi`, Kunden, Status-Katalog, Meta, OpenAPI, Read-only,
Datei-Austausch per Rename, 503, Auth-Gating, Rechte, Offline-Doku). Lauf gegen `grid_con.db` vom 13.10.2026:
249 Anfragen (251 Einträge), 122 Kunden; Stichproben (Anzahl je Status,
MW-Summe, Technologie-Filter, aktive Anfragen) stimmen mit direktem SQL
überein.
