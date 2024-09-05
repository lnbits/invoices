import time
from typing import List, Optional, Union

from lnbits.db import Database
from lnbits.helpers import insert_query, update_query, urlsafe_short_hash

from .models import (
    CreateInvoiceData,
    CreateInvoiceItemData,
    Invoice,
    InvoiceItem,
    Payment,
    UpdateInvoiceItemData,
)

db = Database("ext_invoices")


async def get_invoice(invoice_id: str) -> Optional[Invoice]:
    row = await db.fetchone(
        "SELECT * FROM invoices.invoices WHERE id = :id", {"id": invoice_id}
    )
    return Invoice(**row) if row else None


async def get_invoice_items(invoice_id: str) -> List[InvoiceItem]:
    rows = await db.fetchall(
        "SELECT * FROM invoices.invoice_items WHERE invoice_id = :id",
        {"id": invoice_id},
    )
    return [InvoiceItem(**row) for row in rows]


async def get_invoice_item(item_id: str) -> Optional[InvoiceItem]:
    row = await db.fetchone(
        "SELECT * FROM invoices.invoice_items WHERE id = :id", {"id": item_id}
    )
    return InvoiceItem(**row) if row else None


async def get_invoice_total(items: List[InvoiceItem]) -> int:
    return sum(item.amount for item in items)


async def get_invoices(wallet_ids: Union[str, List[str]]) -> List[Invoice]:
    if isinstance(wallet_ids, str):
        wallet_ids = [wallet_ids]

    q = ",".join([f"'{wallet_id}'" for wallet_id in wallet_ids])
    rows = await db.fetchall(f"SELECT * FROM invoices.invoices WHERE wallet IN ({q})")

    return [Invoice(**row) for row in rows]


async def get_invoice_payments(invoice_id: str) -> List[Payment]:
    rows = await db.fetchall(
        "SELECT * FROM invoices.payments WHERE invoice_id = :id", {"id": invoice_id}
    )

    return [Payment(**row) for row in rows]


async def get_invoice_payment(payment_id: str) -> Optional[Payment]:
    row = await db.fetchone(
        "SELECT * FROM invoices.payments WHERE id = :id", {"id": payment_id}
    )
    return Payment(**row) if row else None


async def get_payments_total(payments: List[Payment]) -> int:
    return sum(item.amount for item in payments)


async def create_invoice_internal(wallet_id: str, data: CreateInvoiceData) -> Invoice:
    invoice_id = urlsafe_short_hash()
    invoice = Invoice(
        id=invoice_id,
        wallet=wallet_id,
        time=int(time.time()),
        status=data.status,
        currency=data.currency,
        company_name=data.company_name,
        first_name=data.first_name,
        last_name=data.last_name,
        email=data.email,
        phone=data.phone,
        address=data.address,
    )
    await db.execute(
        insert_query("invoices.invoices", invoice),
        invoice.dict(),
    )
    return invoice


async def create_invoice_items(
    invoice_id: str, data: List[CreateInvoiceItemData]
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
        await db.execute(
            insert_query("invoices.invoice_items", invoice_item),
            invoice_item.dict(),
        )
    return invoice_items


async def update_invoice_internal(invoice: Invoice) -> Invoice:
    await db.execute(
        update_query("invoices.invoices", invoice),
        invoice.dict(),
    )
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


async def update_invoice_items(
    invoice_id: str, data: List[UpdateInvoiceItemData]
) -> List[InvoiceItem]:
    updated_items = []
    for item in data:
        updated_items.append(item.id)
        await db.execute(
            """
            UPDATE invoices.invoice_items
            SET description = :desc, amount = :amount
            WHERE id = :id
            """,
            {
                "id": item.id,
                "desc": item.description,
                "amount": int(item.amount * 100),
            },
        )

    if len(updated_items) == 0:
        updated_items = ["skip"]

    updated = ",".join([f"'{item}'" for item in updated_items])
    await db.execute(
        f"""
        DELETE FROM invoices.invoice_items
        WHERE invoice_id = :id
        AND id NOT IN ({updated})
        """,
        {"id": invoice_id},
    )

    for item in data:
        if not item:
            await create_invoice_items(
                invoice_id=invoice_id,
                data=[CreateInvoiceItemData(description=item.description)],
            )

    invoice_items = await get_invoice_items(invoice_id)
    return invoice_items


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
