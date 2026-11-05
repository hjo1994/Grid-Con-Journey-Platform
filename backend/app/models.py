"""Models, Backend view.

Hand-maintained copy of `grid_con_ingestion/models.py` (branch
dedicated_env/input_orchestration; separate deployments, no shared package –
same pattern as the AI Cockpit). Source of truth is
`solution documentation/LogicalDataModel.drawio`; keep both copies in sync
with the diagram.

The Backend reads Silver, Gold and the Config tables and writes exactly one
table: the Bronze table UserEvaluationInputs (evaluators' input). Bronze
GronosExports / C4CExports are not read and therefore not copied;
BusinessTransactions only as FK target and for the Gold watermark.
"""
from __future__ import annotations

from sqlalchemy import Boolean, Column, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import declarative_base, relationship

Base = declarative_base()


class BusinessTransaction(Base):
    __tablename__ = "BusinessTransactions"

    ID = Column(String(36), primary_key=True)  # UUID
    C4CExportID = Column(String(36), nullable=True, unique=True)  # Excel import
    GronosExportID = Column(String(36), nullable=True, unique=True)  # GRONOS API import
    UserEvaluationInputID = Column(String(36), nullable=True, unique=True)  # evaluation (BronzeToGold)
    Timestamp = Column(DateTime, nullable=True)  # transformation Bronze → Silver/Gold (UTC)
    InputBronzeTimestamp = Column(DateTime, nullable=True)  # timestamp of the Bronze row


class GridConnectionCustomer(Base):
    __tablename__ = "GridConnectionCustomers"

    ID = Column(String(36), primary_key=True)  # UUID
    CompanyID = Column(String, nullable=True)  # GRONOS companyId
    CustomerName = Column(String, nullable=True)
    CustomerContactPerson = Column(String, nullable=True)
    CustomerContactPersonEmail = Column(String, nullable=True)
    VatNumber = Column(String, nullable=True)

    requests = relationship("GridConnectionRequest", back_populates="customer")


class GridConnectionRequest(Base):
    """One entry per ticket state; the newest entry (``timestamp``) per
    ticket is the current state."""

    __tablename__ = "GridConnectionRequests"

    ID = Column(String(36), primary_key=True)  # UUID
    CustomerID = Column(String(36), ForeignKey("GridConnectionCustomers.ID"), nullable=True)
    BusinessTransactionID = Column(String(36), ForeignKey("BusinessTransactions.ID"), nullable=True)
    RequestStatus = Column(String, nullable=True)
    SubstationLocation = Column(String, nullable=True)
    GenerationTechnology = Column(String, nullable=True)  # several values " | "-separated
    Substation50Hertz = Column(String, nullable=True)
    maxP = Column(Float, nullable=True)  # MW
    SwitchCount = Column(Integer, nullable=True)
    DocumentURL = Column(String, nullable=True)
    id_gronos_old = Column(String, nullable=True)  # C4C "Ticket" (Projekt-xxxx) / API projectName
    id_gronos_new = Column(Integer, nullable=True)  # C4C "Ticket ID" / API friendlyId
    RequestComment = Column(String, nullable=True)
    timestamp = Column(DateTime, nullable=True)  # time of the Silver import, UTC
    # --- GRONOS API only
    GronosObjectID = Column(String(32), nullable=True)
    NextActor = Column(String, nullable=True)
    ProjectPhase = Column(String, nullable=True)
    DsoContacted = Column(Boolean, nullable=True)
    DsoResponse = Column(String, nullable=True)
    CommissioningDate = Column(DateTime, nullable=True)
    Latitude = Column(Float, nullable=True)
    Longitude = Column(Float, nullable=True)
    SourceUpdatedAt = Column(DateTime, nullable=True)

    customer = relationship("GridConnectionCustomer", back_populates="requests")


class User(Base):
    __tablename__ = "Users"

    ID = Column(String(36), primary_key=True)
    Email = Column(String, nullable=False)
    Name = Column(String, nullable=True)
    Role = Column(String, nullable=False)


class EvaluationCriterion(Base):
    __tablename__ = "EvaluationCriteria"

    ID = Column(String(16), primary_key=True)
    Name = Column(String, nullable=False)
    Weight = Column(Float, nullable=False)
    SortOrder = Column(Integer, nullable=False)


class EvaluationSubCriterion(Base):
    __tablename__ = "EvaluationSubCriteria"

    ID = Column(String(16), primary_key=True)
    EvaluationCriterionID = Column(String(16), ForeignKey("EvaluationCriteria.ID"), nullable=False)
    Name = Column(String, nullable=False)
    ScoringGroup = Column(String(16), nullable=False)
    ScoringGroupName = Column(String, nullable=False)
    MaxScore = Column(Integer, nullable=False)
    Question = Column(String, nullable=True)
    SortOrder = Column(Integer, nullable=False)


class EvaluationCheck(Base):
    __tablename__ = "EvaluationChecks"

    ID = Column(String(16), primary_key=True)
    EvaluationSubCriterionID = Column(String(16), ForeignKey("EvaluationSubCriteria.ID"), nullable=False)
    Description = Column(String, nullable=True)
    CheckType = Column(String(16), nullable=False)  # minimum | points
    Points = Column(Integer, nullable=False)
    Graded = Column(Boolean, nullable=False)
    AlternativeGroup = Column(String(16), nullable=True)
    DocumentCategory = Column(String, nullable=True)
    SortOrder = Column(Integer, nullable=False)


class UserEvaluationInput(Base):
    """Bronze, written by the Backend (append-only)."""

    __tablename__ = "UserEvaluationInputs"

    ID = Column(String(36), primary_key=True)
    GridConnectionRequestID = Column(String(36), ForeignKey("GridConnectionRequests.ID"), nullable=False)
    EvaluationCheckID = Column(String(16), ForeignKey("EvaluationChecks.ID"), nullable=False)
    UserID = Column(String(36), ForeignKey("Users.ID"), nullable=False)
    EvaluationVerdict = Column(String(16), nullable=False)
    EvaluationScore = Column(Float, nullable=True)
    Comment = Column(Text, nullable=True)
    Timestamp = Column(DateTime, nullable=False)


class RequestEvaluationCheck(Base):
    """Gold, written by BronzeToGold."""

    __tablename__ = "RequestEvaluationChecks"

    ID = Column(String(36), primary_key=True)
    GridConnectionRequestID = Column(String(36), ForeignKey("GridConnectionRequests.ID"), nullable=False)
    UserID = Column(String(36), ForeignKey("Users.ID"), nullable=False)
    EvaluationCheckID = Column(String(16), ForeignKey("EvaluationChecks.ID"), nullable=False)
    BusinessTransactionID = Column(String(36), ForeignKey("BusinessTransactions.ID"), nullable=False)
    EvaluationVerdict = Column(String(16), nullable=False)
    EvaluationScore = Column(Float, nullable=True)
    EvaluationComment = Column(Text, nullable=True)
    EvaluationReferenceDocumentID = Column(String(36), nullable=True)
    Version = Column(Integer, nullable=False)
    Timestamp = Column(DateTime, nullable=False)


# Users.Role; evaluator roles get their own column in the evaluation view (K1).
EVALUATOR_ROLES: dict[str, str] = {
    "netzplanung": "Netzplanung",
    "flaechen_recht": "Flächen & Recht",
    "finanzen": "Finanzen",
}
ROLES: dict[str, str] = {**EVALUATOR_ROLES, "viewer": "Lesend"}
VERDICTS = ("fulfilled", "not_fulfilled", "open")
