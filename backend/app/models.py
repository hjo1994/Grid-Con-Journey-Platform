"""Silver models, read-only view for the Backend.

Hand-maintained copy of the Silver part of
`input-orchestration/grid_con_ingestion/models.py` (separate deployments,
no shared package – same pattern as the AI Cockpit). Source of truth is
`solution documentation/LogicalDataModel.drawio`; keep both copies in sync
with the diagram. Bronce (C4CExports) is not read by the Backend and
therefore not copied; BusinessTransactions only as FK target.
"""
from __future__ import annotations

from sqlalchemy import Column, DateTime, Float, ForeignKey, Integer, String
from sqlalchemy.orm import declarative_base, relationship

Base = declarative_base()


class BusinessTransaction(Base):
    __tablename__ = "BusinessTransactions"

    ID = Column(String(36), primary_key=True)  # UUID
    C4CExportID = Column(String(36), nullable=False, unique=True)


class GridConnectionCustomer(Base):
    __tablename__ = "GridConnectionCustomers"

    ID = Column(String(36), primary_key=True)  # UUID
    CustomerName = Column(String, nullable=True)
    CustomerContactPerson = Column(String, nullable=True)
    CustomerContactPersonEmail = Column(String, nullable=True)

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
    id_gronos_old = Column(String, nullable=True)  # C4C "Ticket" (Projekt-xxxx)
    id_gronos_new = Column(Integer, nullable=True)  # C4C "Ticket ID"
    RequestComment = Column(String, nullable=True)
    timestamp = Column(DateTime, nullable=True)  # UTC

    customer = relationship("GridConnectionCustomer", back_populates="requests")
