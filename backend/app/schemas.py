"""Response schemas.

JSON keys are the Silver column names in snake_case (``RequestStatus`` →
``request_status``, ``maxP`` → ``max_p``); the mapping is the
``validation_alias`` of each field.
"""
from __future__ import annotations

from datetime import datetime, timezone

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
    timestamp: datetime | None

    @field_validator("timestamp")
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
