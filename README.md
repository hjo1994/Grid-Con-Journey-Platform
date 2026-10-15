# Grid Con Customer Journey — Backend und Monitoring-App

Netzanschlussanfragen aus C4C/GRONOS werden eingelesen, in einem zentralen
Datenmodell abgelegt und über eine standardisierte API für verschiedene
Applikationen bereitgestellt. Aufbau analog zum Referenzprojekt *AI Cockpit*.

Dieser Branch (`dedicated_env/backend_app`) enthält die beiden Deployments,
die die Daten ausliefern, angepasst an die Plattform (Anmeldung über
`eg-auth`/`eg-auth-react`, Pakete vom Firmen-Spiegel). Die Workflow
Orchestration liegt in `dedicated_env/input_orchestration`, der
Entwicklungsstand aller Module in `main`.

1. **`backend/`** — read-only FastAPI-Schnittstelle (`/api/v1`) auf die
   Silver-Tabellen, geschützt mit `eg-auth`. Details: `backend/README.md`.
2. **`monitoring-app/`** — React-Applikation, meldet per OIDC an
   (`eg-auth-react`) und ruft das Backend mit Bearer-Token auf. Details:
   `monitoring-app/README.md`.

## Datenbank (Interim)

SQLite-Datei **`/data/db/grid_con.db`**, beschrieben ausschließlich von der
Input Orchestration (atomarer Datei-Tausch), im Backend read-only gemountet.
