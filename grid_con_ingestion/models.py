"""SQLAlchemy models for the Grid Con Customer Journey data model.

Mirrors `solution documentation/LogicalDataModel.drawio` – column names are
taken 1:1 from the diagram, table names in plural form (e.g. entity
GridConnectionCustomer → table GridConnectionCustomers); class names stay singular. As in the AI Cockpit reference, the
Backend will keep its own hand-maintained copy of these models (separate
deployments/images); keep both in sync with the diagram, never the other way
round.

Layer (siehe `solution documentation/Architecture.drawio`):
  * Bronce: GronosExports – Antwort der GRONOS-API as is (JSON) je Abruf
            C4CExports – Excel-Export as is (Übergang, bis der Excel-Import entfällt)
            UserEvaluationInputs – Eingaben der Prüfer:innen (Backend), append-only
  * Silver: BusinessTransactions, GridConnectionRequests, GridConnectionCustomers
  * Gold:   RequestEvaluationChecks – Bewertung je Check, Nutzer:in und Version
  * Config: Users, EvaluationCriteria, EvaluationSubCriteria, EvaluationChecks
            (Framework aus evaluation_framework.py, Nutzer:innen per
            migrations/evaluation.py)

Dokumente (RequestDocument) sind vorerst nicht umgesetzt; die Bewertung ist
nicht assistiert und nicht mit Dokumenten verknüpft.

Primärschlüssel sind UUIDs (uuid4, als Text, vergeben in writer.py).

In Silver werden nicht befüllte Quellwerte als NULL abgelegt (alle
Nicht-Schlüsselspalten nullable).
"""
from __future__ import annotations

from sqlalchemy import Boolean, Column, DateTime, Float, ForeignKey, Index, Integer, String, Table, Text, text
from sqlalchemy.orm import declarative_base, relationship

Base = declarative_base()


# Originale Spaltenüberschriften des C4C-Exports in Quellreihenfolge.
# Bewusst unverändert übernommen, auch wo sie verschoben sind (z. B. steht der
# Status unter "Official request date"); die Korrektur passiert erst in Silver
# (transforms/normalize.py, RAW_COLUMNS).
C4C_EXPORT_COLUMNS: list[str] = [
    "Ticket",
    "Ticket ID",
    "Official request date",
    "Datum des vollständigen Antrags",
    "Nächster Akteur",
    "Grid connection statement issued date",
    "Ablaufdatum netztechnische Stellungnahme",
    "Anschlusstechnologie",
    "ELO-Link",
    "Anschlusspunkt",
    "Anschlusslösung",
    "Spannungsebene",
    "Vorgangsnummer Netzauskunft",
    "Commissioning date",
    "Stakeholder",
    "Zusatzfeld_16",
    "Account ID",
    "GPDB ID",
    "S4 Business Partner",
    "S4 Customer ID",
    "Contact ID",
    "Zusatzfeld_22",
    "Contact Name",
    "Telefon",
    "Mobiltelefon",
    "Plant Location Address",
    "VNB",
    "Description",
    "Connection Technology",
    "Zusatzfeld_30",
    "Connection Technology Code",
    "Installed Capacity",
    "Zusatzfeld_33",
]


class C4CExport(Base):
    """Bronce: eine Zeile je Zeile des C4C-Exports, alle Werte as is als Text.

    FileSha = SHA-256 des Dateiinhalts (erkennt bereits geladene Lieferungen),
    FileName = Name der gelieferten Datei, Timestamp = Ladezeitpunkt (UTC).
    """

    __table__ = Table(
        "C4CExports",
        Base.metadata,
        Column("ID", String(36), primary_key=True),
        Column("FileSha", String, nullable=False, index=True),
        Column("FileName", String, nullable=False),
        Column("Timestamp", DateTime, nullable=False),
        *(Column(name, String, nullable=True) for name in C4C_EXPORT_COLUMNS),
    )


class GronosExport(Base):
    """Bronce: eine Zeile je abgerufener Netzanschlussanfrage der GRONOS-API.

    Content = Antwort des Detail-Endpunkts as is (JSON-Text), Timestamp =
    Zeitpunkt des API-Abrufs (UTC, gleich für alle Zeilen eines Abrufs).
    Append-only: ein neuer Stand einer Anfrage (``updatedAt``) ist eine neue
    Zeile. Die Umwandlung nach Silver passiert erst in BronzeToSilver.
    """

    __tablename__ = "GronosExports"

    ID = Column(String(36), primary_key=True)  # UUID
    Timestamp = Column(DateTime, nullable=False, index=True)
    Content = Column(Text, nullable=False)


class BusinessTransaction(Base):
    """Silver: ein Vorgang je verarbeiteter Bronze-Zeile.

    Genau eine Quell-Spalte ist gesetzt: ``GronosExportID`` (BronzeToSilver),
    ``UserEvaluationInputID`` (BronzeToGold) oder ``C4CExportID`` (Excel-Import).
    ``Timestamp`` = Zeitpunkt der Transformation Bronze → Silver/Gold (UTC),
    ``InputBronzeTimestamp`` = ``Timestamp`` der Bronze-Zeile. Wasserlinie je
    Quelle = ``MAX(InputBronzeTimestamp)`` der Vorgänge dieser Quelle.
    Jede Bronze-Zeile bekommt einen Vorgang, auch unveränderte; ein Vorgang
    ohne Silver-/Gold-Eintrag heißt "verarbeitet, unverändert".
    """

    __tablename__ = "BusinessTransactions"

    ID = Column(String(36), primary_key=True)  # UUID
    C4CExportID = Column(String(36), ForeignKey("C4CExports.ID"), nullable=True, unique=True)
    GronosExportID = Column(String(36), ForeignKey("GronosExports.ID"), nullable=True, unique=True)
    UserEvaluationInputID = Column(
        String(36), ForeignKey("UserEvaluationInputs.ID", use_alter=True), nullable=True, unique=True
    )
    Timestamp = Column(DateTime, nullable=True)
    InputBronzeTimestamp = Column(DateTime, nullable=True, index=True)

    request = relationship("GridConnectionRequest", back_populates="business_transaction", uselist=False)


class GridConnectionCustomer(Base):
    __tablename__ = "GridConnectionCustomers"

    ID = Column(String(36), primary_key=True)  # UUID
    CompanyID = Column(String, nullable=True)  # GRONOS companyId, Schlüssel für den API-Import
    CustomerName = Column(String, nullable=True)
    CustomerContactPerson = Column(String, nullable=True)
    CustomerContactPersonEmail = Column(String, nullable=True)
    VatNumber = Column(String, nullable=True)  # USt-IdNr. (companyInfo.vatNumber)

    requests = relationship("GridConnectionRequest", back_populates="customer")

    __table_args__ = (
        Index(
            "ux_gcc_company_id",
            "CompanyID",
            unique=True,
            sqlite_where=text("CompanyID IS NOT NULL"),
        ),
    )


class GridConnectionRequest(Base):
    """Silver: ein Eintrag je Ticket-Stand. Neues Ticket oder geänderter Wert
    → komplett neuer Eintrag (neue UUID, eigene BusinessTransaction);
    bestehende Einträge werden nie geändert. Neuester Eintrag je Ticket
    (``timestamp``) = aktueller Stand. Nur mit Kunde in GridConnectionCustomers."""

    __tablename__ = "GridConnectionRequests"

    ID = Column(String(36), primary_key=True)  # UUID
    CustomerID = Column(String(36), ForeignKey("GridConnectionCustomers.ID"), nullable=True)
    BusinessTransactionID = Column(String(36), ForeignKey("BusinessTransactions.ID"), nullable=True)
    RequestStatus = Column(String, nullable=True)
    SubstationLocation = Column(String, nullable=True)
    GenerationTechnology = Column(String, nullable=True)
    Substation50Hertz = Column(String, nullable=True)
    maxP = Column(Float, nullable=True)  # MW
    SwitchCount = Column(Integer, nullable=True)
    DocumentURL = Column(String, nullable=True)
    id_gronos_old = Column(String, nullable=True)  # C4C "Ticket" (Projekt-xxxx) / API projectName
    id_gronos_new = Column(Integer, nullable=True)  # C4C "Ticket ID" / API friendlyId
    RequestComment = Column(String, nullable=True)
    timestamp = Column(DateTime, nullable=True)  # Zeitpunkt des Imports nach Silver (UTC)
    # --- nur aus der GRONOS-API
    GronosObjectID = Column(String(32), nullable=True)  # objectId, Schlüssel je Anfrage
    NextActor = Column(String, nullable=True)  # Code
    ProjectPhase = Column(String, nullable=True)  # Code
    DsoContacted = Column(Boolean, nullable=True)
    DsoResponse = Column(String, nullable=True)  # Code
    CommissioningDate = Column(DateTime, nullable=True)  # frühestes startDate der Ausbaustufen
    Latitude = Column(Float, nullable=True)
    Longitude = Column(Float, nullable=True)
    SourceUpdatedAt = Column(DateTime, nullable=True)  # updatedAt in GRONOS

    customer = relationship("GridConnectionCustomer", back_populates="requests")
    business_transaction = relationship("BusinessTransaction", back_populates="request")

    __table_args__ = (
        Index("ix_gcr_customer", "CustomerID"),
        Index("ix_gcr_id_gronos_old", "id_gronos_old"),
        Index("ix_gcr_id_gronos_new", "id_gronos_new"),  # mehrere Stände je Ticket
        Index("ix_gcr_gronos_object_id", "GronosObjectID"),  # mehrere Stände je Anfrage
        Index(
            "ux_gcr_business_transaction",
            "BusinessTransactionID",
            unique=True,
            sqlite_where=text("BusinessTransactionID IS NOT NULL"),
        ),
    )


class User(Base):
    """Config: Nutzer:innen der Applikationen. ``Role`` steuert, wer bewerten
    darf (siehe ROLES) und unter welcher Fachrolle die Bewertung erscheint."""

    __tablename__ = "Users"

    ID = Column(String(36), primary_key=True)  # UUID
    Email = Column(String, nullable=False, unique=True)
    Name = Column(String, nullable=True)
    Role = Column(String, nullable=False)


class EvaluationCriterion(Base):
    """Config: Kriterium des Reifegradverfahrens (A … D) mit Gewicht."""

    __tablename__ = "EvaluationCriteria"

    ID = Column(String(16), primary_key=True)  # Code, z. B. "A"
    Name = Column(String, nullable=False)
    Weight = Column(Float, nullable=False)  # Anteil an der Gesamtpunktzahl (Summe 1.0)
    SortOrder = Column(Integer, nullable=False)


class EvaluationSubCriterion(Base):
    """Config: Sub-Kriterium (A1, A2, …). Sub-Kriterien mit gleicher
    ``ScoringGroup`` werden gemeinsam gepunktet (B1+B2, C1+C2);
    ``MaxScore`` ist die Höchstpunktzahl der Gruppe."""

    __tablename__ = "EvaluationSubCriteria"

    ID = Column(String(16), primary_key=True)  # Code, z. B. "A1"
    EvaluationCriterionID = Column(String(16), ForeignKey("EvaluationCriteria.ID"), nullable=False)
    Name = Column(String, nullable=False)
    ScoringGroup = Column(String(16), nullable=False)
    ScoringGroupName = Column(String, nullable=False)
    MaxScore = Column(Integer, nullable=False)
    Question = Column(String, nullable=True)  # Leitfrage für die Prüfer:innen
    SortOrder = Column(Integer, nullable=False)


class EvaluationCheck(Base):
    """Config: einzelner Check eines Sub-Kriteriums (A1-01, …).

    ``CheckType``:
      * ``minimum`` – Mindestanforderung, muss erfüllt sein, bringt keine Punkte.
        Mit ``AlternativeGroup`` genügt einer der Checks der Gruppe ("oder").
      * ``points``  – bringt bei Erfüllung ``Points`` Punkte; die Gruppe
        bekommt den höchsten erreichten Wert (Alternativen "oder").
        ``Graded``: Prüfer:in wählt 1 … ``Points`` statt fester Punkte.
    """

    __tablename__ = "EvaluationChecks"

    ID = Column(String(16), primary_key=True)  # Code, z. B. "A1-03"
    EvaluationSubCriterionID = Column(String(16), ForeignKey("EvaluationSubCriteria.ID"), nullable=False)
    Description = Column(String, nullable=True)
    CheckType = Column(String(16), nullable=False)
    Points = Column(Integer, nullable=False, default=0)
    Graded = Column(Boolean, nullable=False, default=False)
    AlternativeGroup = Column(String(16), nullable=True)
    DocumentCategory = Column(String, nullable=True)
    SortOrder = Column(Integer, nullable=False)


class UserEvaluationInput(Base):
    """Bronze: eine Zeile je bewertetem Check, wie von der Prüfer:in
    eingegeben (Backend, POST …/evaluation-inputs). Append-only; eine Eingabe
    kann mehrere Checks enthalten, alle Zeilen einer Eingabe teilen sich den
    ``Timestamp``.

    ``EvaluationVerdict``: ``fulfilled`` | ``not_fulfilled`` | ``open``
    (Bewertung zurückgezogen). ``EvaluationScore``: vergebene Punkte.
    ``Comment``: Begründung, optional (nur Kommentar = gleicher Verdict).
    """

    __tablename__ = "UserEvaluationInputs"

    ID = Column(String(36), primary_key=True)  # UUID
    GridConnectionRequestID = Column(String(36), ForeignKey("GridConnectionRequests.ID"), nullable=False)
    EvaluationCheckID = Column(String(16), ForeignKey("EvaluationChecks.ID"), nullable=False)
    UserID = Column(String(36), ForeignKey("Users.ID"), nullable=False)
    EvaluationVerdict = Column(String(16), nullable=False)
    EvaluationScore = Column(Float, nullable=True)
    Comment = Column(Text, nullable=True)
    Timestamp = Column(DateTime, nullable=False, index=True)


class RequestEvaluationCheck(Base):
    """Gold: Bewertung eines Checks durch eine Prüfer:in, append-only.

    Je Eingabe in UserEvaluationInputs entsteht genau ein Eintrag mit
    eigener BusinessTransaction. ``Version`` zählt je Antrag (``id_gronos_new``),
    Nutzer:in und Check hoch (1, 2, …); der Eintrag mit der höchsten Version
    ist der aktuelle Stand. ``GridConnectionRequestID`` zeigt auf den
    Silver-Stand des Antrags zum Zeitpunkt der Eingabe; Bewertungen gelten für
    alle Stände desselben Antrags. ``EvaluationReferenceDocumentID`` bleibt
    vorerst leer (keine Verknüpfung mit Dokumenten, Bewertung nicht assistiert).
    """

    __tablename__ = "RequestEvaluationChecks"

    ID = Column(String(36), primary_key=True)  # UUID
    GridConnectionRequestID = Column(String(36), ForeignKey("GridConnectionRequests.ID"), nullable=False)
    UserID = Column(String(36), ForeignKey("Users.ID"), nullable=False)
    EvaluationCheckID = Column(String(16), ForeignKey("EvaluationChecks.ID"), nullable=False)
    BusinessTransactionID = Column(String(36), ForeignKey("BusinessTransactions.ID"), nullable=False, unique=True)
    EvaluationVerdict = Column(String(16), nullable=False)
    EvaluationScore = Column(Float, nullable=True)
    EvaluationComment = Column(Text, nullable=True)
    EvaluationReferenceDocumentID = Column(String(36), nullable=True)
    Version = Column(Integer, nullable=False)
    Timestamp = Column(DateTime, nullable=False)  # Zeitpunkt der Eingabe (= UserEvaluationInputs.Timestamp)

    __table_args__ = (
        Index("ix_rec_request_user_check", "GridConnectionRequestID", "UserID", "EvaluationCheckID"),
    )


# Rollen in Users.Role. Bewertende Rollen erscheinen in K1 als eigene Spalte.
EVALUATOR_ROLES: dict[str, str] = {
    "netzplanung": "Netzplanung",
    "flaechen_recht": "Flächen & Recht",
    "finanzen": "Finanzen",
}
ROLES: dict[str, str] = {**EVALUATOR_ROLES, "viewer": "Lesend"}

VERDICTS = ("fulfilled", "not_fulfilled", "open")
