"""Response schemas.

JSON keys are the Silver column names in snake_case (``RequestStatus`` →
``request_status``, ``maxP`` → ``max_p``); the mapping is the
``validation_alias`` of each field.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


def _as_utc(value: datetime | None) -> datetime | None:
    # Silver stores naive UTC timestamps; make that explicit for consumers.
    if value is not None and value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


class _Out(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)


class CustomerOut(_Out):
    id: str = Field(validation_alias="ID")
    customer_name: str | None = Field(validation_alias="CustomerName")
    customer_contact_person: str | None = Field(validation_alias="CustomerContactPerson")
    customer_contact_person_email: str | None = Field(validation_alias="CustomerContactPersonEmail")
    company_id: str | None = Field(default=None, validation_alias="CompanyID", description="GRONOS companyId")
    vat_number: str | None = Field(default=None, validation_alias="VatNumber")


class RequestOut(_Out):
    id: str = Field(validation_alias="ID")
    id_gronos_new: int | None
    id_gronos_old: str | None
    customer_id: str | None = Field(validation_alias="CustomerID")
    business_transaction_id: str | None = Field(validation_alias="BusinessTransactionID")
    request_status: str | None = Field(validation_alias="RequestStatus")
    generation_technology: str | None = Field(validation_alias="GenerationTechnology")
    max_p: float | None = Field(validation_alias="maxP", description="MW")
    substation_50hertz: str | None = Field(validation_alias="Substation50Hertz")
    substation_location: str | None = Field(validation_alias="SubstationLocation")
    switch_count: int | None = Field(validation_alias="SwitchCount")
    document_url: str | None = Field(validation_alias="DocumentURL")
    request_comment: str | None = Field(validation_alias="RequestComment")
    timestamp: datetime | None = Field(description="Time of the import into Silver (UTC)")
    # --- GRONOS API only (null for requests from the Excel import)
    gronos_object_id: str | None = Field(default=None, validation_alias="GronosObjectID")
    next_actor: str | None = Field(default=None, validation_alias="NextActor", description="Code")
    project_phase: str | None = Field(default=None, validation_alias="ProjectPhase", description="Code")
    dso_contacted: bool | None = Field(default=None, validation_alias="DsoContacted")
    dso_response: str | None = Field(default=None, validation_alias="DsoResponse", description="Code")
    commissioning_date: datetime | None = Field(
        default=None, validation_alias="CommissioningDate", description="Earliest start date of the expansion stages"
    )
    latitude: float | None = Field(default=None, validation_alias="Latitude")
    longitude: float | None = Field(default=None, validation_alias="Longitude")
    source_updated_at: datetime | None = Field(
        default=None, validation_alias="SourceUpdatedAt", description="Last change in GRONOS (UTC)"
    )

    @field_validator("timestamp", "commissioning_date", "source_updated_at")
    @classmethod
    def timestamp_utc(cls, value):
        return _as_utc(value)


class RequestWithCustomerOut(RequestOut):
    customer: CustomerOut | None = Field(
        default=None, description="Only present with expand=customer"
    )


class RequestPage(BaseModel):
    items: list[RequestOut]
    total: int
    limit: int
    offset: int
    data_as_of: datetime | None

    @field_validator("data_as_of")
    @classmethod
    def data_as_of_utc(cls, value):
        return _as_utc(value)


class CustomerPage(BaseModel):
    items: list[CustomerOut]
    total: int
    limit: int
    offset: int


class AggregateItem(BaseModel):
    key: str | None
    count: int
    sum_max_p: float


class AggregateResult(BaseModel):
    group_by: str
    split_multi: bool
    total: int = Field(description="Number of requests matching the filters")
    items: list[AggregateItem]
    data_as_of: datetime | None

    @field_validator("data_as_of")
    @classmethod
    def data_as_of_utc(cls, value):
        return _as_utc(value)


class RequestStatusOut(BaseModel):
    name: str
    order: int | None = Field(description="Display order; null for statuses not configured")
    phase: str | None
    in_process: bool
    configured: bool


class Meta(BaseModel):
    api_version: str
    data_as_of: datetime | None

    @field_validator("data_as_of")
    @classmethod
    def data_as_of_utc(cls, value):
        return _as_utc(value)


# --------------------------------------------------------------------------- #
# Collaborative evaluation
# --------------------------------------------------------------------------- #
class UserOut(BaseModel):
    id: str
    email: str
    name: str | None
    role: str
    role_label: str
    can_evaluate: bool


class CheckOut(BaseModel):
    id: str
    description: str | None
    check_type: str = Field(description="minimum = Mindestanforderung, points = bringt Punkte")
    points: int
    graded: bool = Field(description="Prüfer:in wählt 1 … points statt fester Punkte")
    alternative_group: str | None = Field(description="Checks derselben Gruppe sind Alternativen ('oder')")
    document_category: str | None


class SubCriterionOut(BaseModel):
    id: str
    name: str
    scoring_group: str
    scoring_group_name: str
    max_score: int = Field(description="Höchstpunktzahl der Scoring-Gruppe")
    question: str | None
    checks: list[CheckOut]


class CriterionOut(BaseModel):
    id: str
    name: str
    weight: float
    sub_criteria: list[SubCriterionOut]


class EvaluationEntryOut(BaseModel):
    id: str
    user_id: str
    evaluation_check_id: str
    verdict: str = Field(description="fulfilled | not_fulfilled | open")
    score: float | None
    comment: str | None
    version: int
    timestamp: datetime
    pending: bool = Field(description="Eingabe gespeichert, von BronzeToGold noch nicht verarbeitet")

    @field_validator("timestamp")
    @classmethod
    def timestamp_utc(cls, value):
        return _as_utc(value)


class EvaluationState(BaseModel):
    id_gronos_new: int
    grid_connection_request_id: str = Field(description="Aktueller Silver-Stand, auf den neue Eingaben zeigen")
    evaluators: list[UserOut]
    checks: list[EvaluationEntryOut] = Field(description="Aktueller Stand je Nutzer:in und Check")
    last_change: datetime | None

    @field_validator("last_change")
    @classmethod
    def last_change_utc(cls, value):
        return _as_utc(value)


class HistoryEntryOut(EvaluationEntryOut):
    action: str = Field(description="rated | changed | commented")
    previous_verdict: str | None
    previous_score: float | None
    sub_criterion_id: str
    scoring_group: str


class EvaluationHistory(BaseModel):
    id_gronos_new: int
    items: list[HistoryEntryOut] = Field(description="Neueste zuerst")
    total: int


class EvaluationInputItem(BaseModel):
    evaluation_check_id: str
    verdict: Literal["fulfilled", "not_fulfilled", "open"]
    score: float | None = Field(default=None, description="Nur für Checks mit graded=true")
    comment: str | None = Field(default=None, max_length=4000)


class EvaluationInputBody(BaseModel):
    checks: list[EvaluationInputItem] = Field(min_length=1, max_length=100)


class EvaluationInputResult(BaseModel):
    items: list[EvaluationEntryOut] = Field(description="Nur Eingaben, die etwas ändern (Delta)")
    unchanged: int = Field(default=0, description="Eingaben ohne Änderung gegenüber dem aktuellen Stand")
    gold_triggered: bool = Field(description="BronzeToGold wurde über die Airflow-API angestoßen")


class UserEvaluationItem(BaseModel):
    id_gronos_new: int
    id_gronos_old: str | None
    generation_technology: str | None
    max_p: float | None = Field(description="MW")
    request_status: str | None
    checks: list[EvaluationEntryOut] = Field(description="Aktueller Stand der Nutzer:in je Check")
    last_change: datetime
    pending: bool = Field(description="Mindestens eine Eingabe noch nicht von BronzeToGold verarbeitet")

    @field_validator("last_change")
    @classmethod
    def last_change_utc(cls, value):
        return _as_utc(value)


class UserEvaluations(BaseModel):
    user: UserOut
    items: list[UserEvaluationItem] = Field(description="Zuletzt geänderte zuerst")
    total: int


class MeOut(BaseModel):
    """The signed-in user (eg-auth) and, if registered, their Users entry."""

    email: str
    name: str | None
    user: UserOut | None = Field(description="null = not registered in Users: may read, not evaluate")
