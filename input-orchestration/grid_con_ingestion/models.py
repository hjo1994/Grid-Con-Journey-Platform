"""SQLAlchemy models for the Grid Con Customer Journey data model.

Mirrors `solution documentation/LogicalDataModel.drawio` – column names are
taken 1:1 from the diagram, table names in plural form (e.g. entity
GridConnectionCustomer → table GridConnectionCustomers, EvaluationCriterion →
EvaluationCriteria); class names stay singular. As in the AI Cockpit
reference, the Backend keeps its own hand-maintained copy of these models
(separate deployments/images); keep both in sync with the diagram, never the
other way round.

Layer (siehe `solution documentation/Architecture.drawio`):
  * Bronze: GronosExports – eine Zeile je abgerufenem GRONOS-Antrag (JSON as is)
            UserEvaluationInputs – Eingaben der Prüfer:innen (append-only)
            C4CExports – Legacy: Excel-Export as is (bis die API produktiv ist)
  * Silver: BusinessTransactions, GridConnectionRequests, GridConnectionCustomers
  * Gold:   RequestEvaluationChecks – versionierte Bewertung je Prüfer:in und Check
  * Config: Users, EvaluationCriteria, EvaluationSubCriteria, EvaluationChecks
            (Bewertungs-Framework, befüllt aus evaluation_framework.py)

BusinessTransactions verbinden jede verarbeitete Bronze-Zeile mit ihrem
Ergebnis in Silver bzw. Gold:
  * ``Timestamp`` – Zeitpunkt der Transformation (Bronze → Silver bzw. Gold)
  * ``InputBronzeTimestamp`` – Timestamp der verarbeiteten Bronze-Zeile; der
    höchste Wert je Quelle ist die Wasserlinie für den nächsten Lauf.

Primärschlüssel sind UUIDs (uuid4, als Text, vergeben in writer.py bzw. im
Backend für UserEvaluationInputs). Config-Tabellen haben sprechende
Schlüssel (Code des Kriteriums/Checks), damit Bewertungen über
Framework-Updates hinweg stabil bleiben.

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
    """Bronze (Legacy): eine Zeile je Zeile des C4C-Exports, alle Werte as is als Text.

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
    """Bronze: eine Zeile je abgerufenem GRONOS-Antrag (Detail-Endpunkt).

    ``Content`` ist die API-Antwort des Antrags as is (JSON), ``Timestamp``
    der Zeitpunkt des Abrufs (UTC, ein Wert je Lauf). Append-only.
    """

    __tablename__ = "GronosExports"

    ID = Column(String(36), primary_key=True)  # UUID
    Timestamp = Column(DateTime, nullable=False, index=True)
    Content = Column(Text, nullable=False)


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


class BusinessTransaction(Base):
    """Silver: ein Vorgang je verarbeiteter Bronze-Zeile.

    Genau eine der Quell-Spalten ist gesetzt: ``GronosExportID`` (BronzeToSilver),
    ``UserEvaluationInputID`` (BronzeToGold) oder ``C4CExportID`` (Legacy).
    """

    __tablename__ = "BusinessTransactions"

    ID = Column(String(36), primary_key=True)  # UUID
    C4CExportID = Column(String(36), ForeignKey("C4CExports.ID"), nullable=True, unique=True)
    GronosExportID = Column(String(36), ForeignKey("GronosExports.ID"), nullable=True, unique=True)
    UserEvaluationInputID = Column(
        String(36), ForeignKey("UserEvaluationInputs.ID", use_alter=True), nullable=True, unique=True
    )
    Timestamp = Column(DateTime, nullable=True)  # Transformation Bronze → Silver/Gold (UTC)
    InputBronzeTimestamp = Column(DateTime, nullable=True)  # Timestamp der Bronze-Zeile

    request = relationship("GridConnectionRequest", back_populates="business_transaction", uselist=False)

    __table_args__ = (
        Index("ix_bt_input_bronze_timestamp", "InputBronzeTimestamp"),
    )


class GridConnectionCustomer(Base):
    __tablename__ = "GridConnectionCustomers"

    ID = Column(String(36), primary_key=True)  # UUID
    CompanyID = Column(String, nullable=True)  # GRONOS companyId; NULL bei Legacy-Kunden
    CustomerName = Column(String, nullable=True)
    CustomerContactPerson = Column(String, nullable=True)
    CustomerContactPersonEmail = Column(String, nullable=True)
    VatNumber = Column(String, nullable=True)

    requests = relationship("GridConnectionRequest", back_populates="customer")

    __table_args__ = (Index("ux_customer_company_id", "CompanyID", unique=True),)


class GridConnectionRequest(Base):
    """Silver: ein Eintrag je Antrags-Stand. Neuer Antrag oder geänderter Wert
    → komplett neuer Eintrag (neue UUID, eigene BusinessTransaction);
    bestehende Einträge werden nie geändert. Neuester Eintrag je Antrag
    (``timestamp``) = aktueller Stand. Schlüssel eines Antrags: ``GronosObjectID``
    (GRONOS-API) bzw. ``id_gronos_old`` + ``id_gronos_new`` (Legacy C4C)."""

    __tablename__ = "GridConnectionRequests"

    ID = Column(String(36), primary_key=True)  # UUID
    CustomerID = Column(String(36), ForeignKey("GridConnectionCustomers.ID"), nullable=True)
    BusinessTransactionID = Column(String(36), ForeignKey("BusinessTransactions.ID"), nullable=True)
    GronosObjectID = Column(String, nullable=True)  # GRONOS objectId
    RequestStatus = Column(String, nullable=True)
    NextActor = Column(String, nullable=True)
    ProjectPhase = Column(String, nullable=True)
    DsoContacted = Column(Boolean, nullable=True)
    DsoResponse = Column(String, nullable=True)
    SubstationLocation = Column(String, nullable=True)
    GenerationTechnology = Column(String, nullable=True)
    Substation50Hertz = Column(String, nullable=True)
    maxP = Column(Float, nullable=True)  # MW
    CommissioningDate = Column(DateTime, nullable=True)
    Latitude = Column(Float, nullable=True)
    Longitude = Column(Float, nullable=True)
    SwitchCount = Column(Integer, nullable=True)
    DocumentURL = Column(String, nullable=True)
    id_gronos_old = Column(String, nullable=True)  # C4C "Ticket" (Projekt-xxxx) bzw. GRONOS projectName
    id_gronos_new = Column(Integer, nullable=True)  # C4C "Ticket ID" bzw. GRONOS friendlyId
    RequestComment = Column(String, nullable=True)
    SourceUpdatedAt = Column(DateTime, nullable=True)  # GRONOS updatedAt
    timestamp = Column(DateTime, nullable=True)  # Zeitpunkt des Silver-Imports (UTC)

    customer = relationship("GridConnectionCustomer", back_populates="requests")
    business_transaction = relationship("BusinessTransaction", back_populates="request")

    __table_args__ = (
        Index("ix_gcr_customer", "CustomerID"),
        Index("ix_gcr_id_gronos_old", "id_gronos_old"),
        Index("ix_gcr_id_gronos_new", "id_gronos_new"),  # mehrere Stände je Ticket
        Index("ix_gcr_gronos_object_id", "GronosObjectID"),
        Index(
            "ux_gcr_business_transaction",
            "BusinessTransactionID",
            unique=True,
            sqlite_where=text("BusinessTransactionID IS NOT NULL"),
        ),
    )


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
