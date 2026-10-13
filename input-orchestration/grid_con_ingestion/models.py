"""SQLAlchemy models for the Grid Con Customer Journey data model.

Mirrors `solution documentation/LogicalDataModel.drawio` – column names are
taken 1:1 from the diagram, table names in plural form (e.g. entity
GridConnectionCustomer → table GridConnectionCustomers); class names stay singular. As in the AI Cockpit reference, the
Backend will keep its own hand-maintained copy of these models (separate
deployments/images); keep both in sync with the diagram, never the other way
round.

Layer (siehe `solution documentation/Architecture.drawio`):
  * Bronce: C4CExports – Export as is, plus Metadaten je Lieferung
  * Silver: BusinessTransactions, GridConnectionRequests, GridConnectionCustomers

Gold (RequestDocument, RequestEvaluationChecks, Evaluation*) ist vorerst
nicht umgesetzt.

Primärschlüssel sind UUIDs (uuid4, als Text, vergeben in writer.py).

In Silver werden nicht befüllte Quellwerte als NULL abgelegt (alle
Nicht-Schlüsselspalten nullable).
"""
from __future__ import annotations

from sqlalchemy import Column, DateTime, Float, ForeignKey, Index, Integer, String, Table, text
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


class BusinessTransaction(Base):
    """Silver: ein Vorgang je verarbeiteter Bronce-Zeile (1:1 zu C4CExports)."""

    __tablename__ = "BusinessTransactions"

    ID = Column(String(36), primary_key=True)  # UUID
    C4CExportID = Column(String(36), ForeignKey("C4CExports.ID"), nullable=False, unique=True)

    request = relationship("GridConnectionRequest", back_populates="business_transaction", uselist=False)


class GridConnectionCustomer(Base):
    __tablename__ = "GridConnectionCustomers"

    ID = Column(String(36), primary_key=True)  # UUID
    CustomerName = Column(String, nullable=True)
    CustomerContactPerson = Column(String, nullable=True)
    CustomerContactPersonEmail = Column(String, nullable=True)

    requests = relationship("GridConnectionRequest", back_populates="customer")


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
    id_gronos_old = Column(String, nullable=True)  # C4C "Ticket" (Projekt-xxxx)
    id_gronos_new = Column(Integer, nullable=True)  # C4C "Ticket ID"
    RequestComment = Column(String, nullable=True)
    timestamp = Column(DateTime, nullable=True)  # letzte Änderung durch BronceToSilver (UTC)

    customer = relationship("GridConnectionCustomer", back_populates="requests")
    business_transaction = relationship("BusinessTransaction", back_populates="request")

    __table_args__ = (
        Index("ix_gcr_customer", "CustomerID"),
        Index("ix_gcr_id_gronos_old", "id_gronos_old"),
        Index("ix_gcr_id_gronos_new", "id_gronos_new"),  # mehrere Stände je Ticket
        Index(
            "ux_gcr_business_transaction",
            "BusinessTransactionID",
            unique=True,
            sqlite_where=text("BusinessTransactionID IS NOT NULL"),
        ),
    )
