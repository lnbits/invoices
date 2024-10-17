from typing import List, Optional, Union

from lnbits.db import Database
from lnbits.helpers import urlsafe_short_hash

from .models import (
    CreateInvoiceData,
    Invoice,
    InvoiceItem,
    InvoiceItemData,
    Payment,
)

db = Database("ext_invoices")


async def get_invoice(invoice_id: str) -> Optional[Invoice]:
    return await db.fetchone(
        "SELECT * FROM invoices.invoices WHERE id = :id",
        {"id": invoice_id},
        Invoice,
    )


async def get_invoice_items(invoice_id: str) -> List[InvoiceItem]:
    return await db.fetchall(
        "SELECT * FROM invoices.invoice_items WHERE invoice_id = :id",
        {"id": invoice_id},
        InvoiceItem,
    )


async def get_invoice_item(item_id: str) -> Optional[InvoiceItem]:
    return await db.fetchone(
        "SELECT * FROM invoices.invoice_items WHERE id = :id",
        {"id": item_id},
        InvoiceItem,
    )


async def get_invoice_total(items: List[InvoiceItem]) -> int:
    return sum(item.amount for item in items)


async def get_invoices(wallet_ids: Union[str, List[str]]) -> List[Invoice]:
    if isinstance(wallet_ids, str):
        wallet_ids = [wallet_ids]

    q = ",".join([f"'{wallet_id}'" for wallet_id in wallet_ids])
    return await db.fetchall(
        f"SELECT * FROM invoices.invoices WHERE wallet IN ({q})",
        model=Invoice,
    )


async def get_invoice_payments(invoice_id: str) -> List[Payment]:
    return await db.fetchall(
        "SELECT * FROM invoices.payments WHERE invoice_id = :id",
        {"id": invoice_id},
        Payment,
    )


async def get_invoice_payment(payment_id: str) -> Optional[Payment]:
    return await db.fetchone(
        "SELECT * FROM invoices.payments WHERE id = :id",
        {"id": payment_id},
        Payment,
    )


async def get_payments_total(payments: List[Payment]) -> int:
    return sum(item.amount for item in payments)


async def create_invoice_internal(wallet_id: str, data: CreateInvoiceData) -> Invoice:
    invoice_id = urlsafe_short_hash()
    invoice = Invoice(
        id=invoice_id,
        wallet=wallet_id,
        status=data.status,
        currency=data.currency,
        company_name=data.company_name,
        first_name=data.first_name,
        last_name=data.last_name,
        email=data.email,
        phone=data.phone,
        address=data.address,
    )
    await db.insert("invoices.invoices", invoice)
    return invoice


async def create_invoice_items(
    invoice_id: str, data: List[InvoiceItemData]
) -> List[InvoiceItem]:
    invoice_items = []
    for item in data:
        item_id = urlsafe_short_hash()
        invoice_item = InvoiceItem(
            id=item_id,
            invoice_id=invoice_id,
            description=item.description,
            amount=int(item.amount * 100),
        )
        invoice_items.append(invoice_item)
        await db.insert("invoices.invoice_items", invoice_item)
    return invoice_items


async def update_invoice_internal(invoice: Invoice) -> Invoice:
    await db.update("invoices.invoices", invoice)
    return invoice


async def delete_invoice(
    invoice_id: str,
) -> bool:
    await db.execute(
        "DELETE FROM invoices.payments WHERE invoice_id = :id",
        {"id": invoice_id},
    )
    await db.execute(
        "DELETE FROM invoices.invoice_items WHERE invoice_id = :id",
        {"id": invoice_id},
    )
    await db.execute(
        "DELETE FROM invoices.invoices WHERE id = :id",
        {"id": invoice_id},
    )
    return True


async def delete_invoice_items(
    invoice_id: str,
) -> bool:
    await db.execute(
        "DELETE FROM invoices.invoice_items WHERE invoice_id = :id",
        {"id": invoice_id},
    )
    return True


async def create_invoice_payment(invoice_id: str, amount: int) -> Payment:
    payment_id = urlsafe_short_hash()
    await db.execute(
        """
        INSERT INTO invoices.payments (id, invoice_id, amount)
        VALUES (:id, :invoice_id, :amount)
        """,
        {"id": payment_id, "invoice_id": invoice_id, "amount": amount},
    )

    payment = await get_invoice_payment(payment_id)
    assert payment, "Newly created payment couldn't be retrieved"
    return payment
