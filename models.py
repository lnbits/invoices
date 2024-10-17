from datetime import datetime, timezone
from enum import Enum
from typing import List, Optional

from fastapi import Query
from pydantic import BaseModel


class InvoiceStatusEnum(str, Enum):
    draft = "draft"
    open = "open"
    paid = "paid"
    canceled = "canceled"


class InvoiceItemData(BaseModel):
    id: Optional[str] = None
    description: str
    amount: float = Query(..., ge=0.01)


class CreateInvoiceData(BaseModel):
    status: InvoiceStatusEnum = InvoiceStatusEnum.draft
    currency: str
    company_name: Optional[str]
    first_name: Optional[str]
    last_name: Optional[str]
    email: Optional[str]
    phone: Optional[str]
    address: Optional[str]
    items: List[InvoiceItemData]

    class Config:
        use_enum_values = True


class UpdateInvoiceData(BaseModel):
    id: str
    wallet: str
    status: InvoiceStatusEnum = InvoiceStatusEnum.draft
    currency: str
    company_name: Optional[str] = None
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    address: Optional[str] = None
    items: List[InvoiceItemData]


class Invoice(BaseModel):
    id: str
    wallet: str
    status: InvoiceStatusEnum = InvoiceStatusEnum.draft
    currency: str
    company_name: Optional[str] = None
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    address: Optional[str] = None
    time: datetime = datetime.now(timezone.utc)

    class Config:
        use_enum_values = True


class InvoiceItem(BaseModel):
    id: str
    invoice_id: str
    description: str
    amount: int

    class Config:
        orm_mode = True


class Payment(BaseModel):
    id: str
    invoice_id: str
    amount: int
    time: datetime


class CreatePaymentData(BaseModel):
    invoice_id: str
    amount: int


class InvoiceFull(Invoice):
    items: List[InvoiceItem] = []
    payments: int = 0
