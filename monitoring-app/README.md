# Monitoring-App — React

Eigenes Deployment, eigene Anwendung. Konsumiert ausschließlich die
Backend-API (`/api/v1`, siehe `backend/README.md`); kein eigener Datenzugriff.
Stack wie das AI-Cockpit-Frontend: React 18 + Vite + TypeScript, gleiche
Versionen, Schrift (IBM Plex) als Dateien im Repo (`src/fonts/`, OFL-Lizenzen
liegen bei), keine externen Requests zur Laufzeit. Oberfläche auf Deutsch.

## Ansicht (abgestimmter Entwurf, Variante A)

- **Kopfzeile** mit Datenstand (`data_as_of` aus den API-Antworten, in
  lokaler Zeit).
- **Antragsliste**: aktueller Stand je Ticket (`id_gronos_new`), Spalten
  Ticket, Projekt, Kunde, Technologie, MW, Status. Suche, Sortierung und
  Paginierung (20 pro Seite) laufen im Backend (`q`, `sort`, `order`,
  `limit`, `offset`).
- **Detailbereich** nur mit Silver-Feldern: Prozessfortschritt, Dokumente und
  Links (ELO-Referenz, C4C-Ticket), Netzanschluss, Ansprechpartner,
  Kommentar, Stand.
  Für Anfragen aus der GRONOS-API (`gronos_object_id` gesetzt) zusätzlich:
  Dokument-Dateinamen, „Verfahren in GRONOS“ (Projektphase, nächster Akteur,
  VNB kontaktiert, VNB-Rückmeldung, als Code bis die Code-Listen da sind),
  Inbetriebnahme, Koordinaten (Link auf OpenStreetMap, erst beim Klick),
  Firmen-ID und USt-IdNr. des Kunden, „Geändert in GRONOS“ und die
  GRONOS-ID. Bei Anfragen aus dem Excel-Import bleiben diese Zeilen weg.
- **Widgets**: *Status der Anfragen* nach Phase
  (`/aggregate?group_by=request_status`) und *Aktive Leistung nach
  Technologie* (`/aggregate?group_by=generation_technology&exclude_status=Eingestellt&split_multi=true`;
  die fünf größten nach MW, Rest als „Übrige“).

## Bewertung: K1 und K4

Hash-Routen: ohne Hash bzw. `#/meine-bewertungen` „Meine Bewertungen“
(Startseite), `#/` Übersicht, `#/antraege/<id>/bewertung` (K1),
`#/antraege/<id>/verlauf` (K4). Im Detailbereich führen „Reifegrad bewerten“
und „Verlauf“ dorthin.

- **Nutzer:in = Anmeldung (OIDC):** die App fragt `GET /users/me`; das
  Backend ordnet die E-Mail aus dem Token einem Eintrag in `Users` zu (Rolle).
  Nur Prüfer-Rollen (Netzplanung, Flächen & Recht, Finanzen) können bewerten,
  alle anderen lesen. Nach der Anmeldung öffnet sich „Meine Bewertungen“.
  Lokal mit Dev-Bypass: Backend mit `EG_AUTH_DEV_EMAIL=<E-Mail aus Users>`.
- **Meine Bewertungen** (`src/components/MyEvaluationsView.tsx`): alle
  Anträge, die die Nutzer:in bewertet hat, zuletzt geändert zuerst, mit dem
  eigenen zuletzt gespeicherten Reifegrad, Zahl der bewerteten Checks und
  letzter Änderung; ein Klick öffnet K1.
- **K1 – Spalte je Prüfer:in:** je Bewertungsgruppe (A1, A2, B1+B2, …) eine
  Spalte pro Prüfer:in. Die eigene Spalte ist bearbeitbar (Checks aufklappen,
  erfüllt / nicht erfüllt / offen, bei D1 abgestufte Punkte), die anderen sind
  read-only. Abweichende Punktzahlen werden markiert. Begründungen je
  Unterkriterium im Seitenpanel. Fußzeile: Reifegrad je Prüfer:in und
  Spannweite.
- **Speichern:** Klicks und Kommentare („Kommentar vormerken“) ändern nur
  einen Entwurf; die Punktzahl rechnet sofort mit. Am Ende der Bewertung
  stehen die Zahl der ungespeicherten Änderungen, „Verwerfen“ und
  „Bewertung speichern“. Erst dieser Knopf sendet alle Checks, die sich vom
  gespeicherten Stand unterscheiden, in einem Aufruf. Wer mit
  ungespeicherten Änderungen die Seite oder die Nutzer:in wechselt, wird
  gefragt. Der Entwurf übersteht kein Neuladen.
- **K4 – Verlauf:** links aktueller Stand je Nutzer:in und Gruppe, rechts das
  Änderungsprotokoll (Alles / Nur Bewertungen / Nur Begründungen), mit
  Punktzahl vorher → nachher.
- **Live:** der Stand wird alle 4 s neu geladen, der eigene Entwurf liegt
  darüber und wird dabei nicht überschrieben (`src/domain/useEvaluation.ts`).
- **Punktzahl** (`src/domain/scoring.ts`), Regeln aus der Bewertungs-Excel:
  Mindestanforderungen müssen erfüllt sein (Alternativen: eine reicht), sonst
  0; Punkte-Checks geben den höchsten erreichten Wert, gedeckelt auf das
  Gruppenmaximum; Reifegrad = Σ Gewicht × Punkte/Max.

## Logik in der App (bewusst nicht im Backend)

- **Prozessschritt und Phase** werden aus `/request-statuses` abgeleitet
  (`src/domain/status.ts`): Schritt = Position unter den Status mit
  `in_process`. Status außerhalb des Prozesses oder ohne Konfiguration landen
  im Widget unter „Außerhalb des Prozesses“. Farbe der Status-Pille nach
  Position der Phase, „Eingestellt“ rot.
- **Kundenname**: Die Liste liefert nur `customer_id`. Die App lädt einmal alle
  Kunden (`/grid-connection-customers`, ca. 120) und ordnet im Browser zu;
  Ansprechpartner im Detail kommen aus demselben Datensatz.
- **C4C-Link**: aus `VITE_C4C_TICKET_URL` (siehe unten). Ohne Wert zeigt das
  Detail „nicht konfiguriert“.
- **ELO**: `document_url` enthält heute eine Referenz („Referenz-0001“), keine
  URL. Ein Link entsteht nur, wenn der Wert mit `http(s)://` beginnt.

## Anmeldung

Wie im AI-Cockpit-Frontend über `eg-auth-react` (internes Paket vom
Firmen-Spiegel):

- `src/main.tsx` lädt `AuthApp.tsx` (Routen `/login`, `/logout`, Rest hinter
  `AuthGate`). Nicht angemeldete Nutzer landen auf `/login`, die Anmeldung
  läuft per OIDC-Redirect. In der Kopfzeile steht dann „Abmelden“.
- `src/api/client.ts` bleibt bei `fetch` (Abbruch per `AbortSignal`,
  wiederholte Query-Parameter) und hängt das Access-Token als
  `Authorization: Bearer …` an (`src/shared/auth/accessToken.ts`). 401 und
  403 haben eigene Meldungen.
- OIDC-Werte in `.env.development` / `.env.production` (`VITE_OIDC_CLIENT_ID`,
  `VITE_OIDC_AUTHORITY`, `VITE_OIDC_REQUEST_GROUPS`), im Repo leer.
- **Außerhalb des Firmennetzes:** `VITE_AUTH_DEV_BYPASS="true"` in
  `.env.development.local` und Backend mit `EG_AUTH_DEV_MODE=True`. Der
  Bypass greift nur im Dev-Server, nie im Production-Build.

## Konfiguration (Build-Zeit)

Siehe `.env.example`. Lokal in `.env.local` (gitignored):

| Variable | Default | Zweck |
|---|---|---|
| `VITE_API_BASE` | `/api/v1` | Basis der Backend-API |
| `VITE_C4C_TICKET_URL` | leer | C4C-Ticket-Link; `{id}` wird durch `id_gronos_new` ersetzt, sonst wird die ID angehängt |

## Lokal starten

```bash
cd monitoring-app
npm install            # .npmrc zeigt auf den Firmen-Spiegel, siehe unten
npm run dev            # http://localhost:5174, /api -> http://localhost:8000
npm test               # Vitest
npm run lint           # tsc (der Build prüft keine Typen)
npm run build          # build/
```

Port 5174, weil 5173 das AI-Cockpit-Frontend belegt. Anderes Backend:
`VITE_DEV_API_TARGET=http://host:port npm run dev`. Wie `/api` im Cluster
zum Backend geroutet wird, ist wie beim AI Cockpit eine offene
Deployment-Entscheidung; das Backend hat keine CORS-Freigaben.

`.npmrc` zeigt wie im AI Cockpit auf den Firmen-Spiegel. `package-lock.json`
ist gitignored und muss im Firmennetz erzeugt werden.

## Offen

- **OIDC-Client**: Grid Con braucht einen eigenen Client beim
  AAP-Authenticator; bis dahin sind `VITE_OIDC_*` leer und die Gruppe ist der
  Platzhalter aus dem AI Cockpit.
- **C4C-URL-Schema** und ob `document_url` künftig echte ELO-Links enthält.

## Verifiziert

34 Tests (05.11.2026, mit eg-auth: Nutzer:in aus `GET /users/me`), zusätzlich: Punkteregeln (Mindestanforderungen,
Alternativen, Deckelung, abgestufte Punkte, Reifegrad), Abweichungen,
Verlaufs-Replay, K1 (eigene Spalte bearbeitbar, fremde read-only, Entwurf,
nur Delta mit Kommentaren in einem Aufruf, Verwerfen), „Meine Bewertungen“,
Routen und Rückfrage beim Verlassen.
Im Browser gegen eine Demo-DB mit drei Prüfer:innen geprüft.

### Früherer Stand (13.10.2026)

16 Tests (Prozessschritt, Phasen-Gruppierung inkl. unbekannter Status,
Status-Farben, Top-5-Technologien, C4C-/ELO-Links, Query-Parameter, Liste mit
Kundennamen, Detail, Auswahl, Widget-Aufrufe, Suche/Sortierung ans Backend,
503-Meldung). Im Browser gegen `grid_con.db` vom 13.10.2026: 249 Anfragen,
Statuszahlen und MW-Summen wie im Backend, Suche, Sortierung, Paginierung.
