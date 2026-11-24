from lnbits.db import Database
from lnbits.helpers import urlsafe_short_hash

from .models import (
    CreateInvoiceData,
    Invoice,
    InvoiceItem,
    InvoiceItemData,
    InvoicePaymentRequest,
    InvoiceStatusEnum,
    Payment,
)

db = Database("ext_invoices")


async def get_invoice(invoice_id: str) -> Invoice | None:
    return await db.fetchone(
        "SELECT * FROM invoices.invoices WHERE id = :id",
        {"id": invoice_id},
        Invoice,
    )


async def get_invoice_items(invoice_id: str) -> list[InvoiceItem]:
    return await db.fetchall(
        "SELECT * FROM invoices.invoice_items WHERE invoice_id = :id",
        {"id": invoice_id},
        InvoiceItem,
    )


async def get_invoice_item(item_id: str) -> InvoiceItem | None:
    return await db.fetchone(
        "SELECT * FROM invoices.invoice_items WHERE id = :id",
        {"id": item_id},
        InvoiceItem,
    )


async def get_invoice_total(items: list[InvoiceItem]) -> int:
    return sum((item.amount * item.quantity) for item in items)


async def get_invoices(wallet_ids: str | list[str]) -> list[Invoice]:
    if isinstance(wallet_ids, str):
        wallet_ids = [wallet_ids]

    q = ",".join([f"'{wallet_id}'" for wallet_id in wallet_ids])
    return await db.fetchall(
        f"SELECT * FROM invoices.invoices WHERE wallet IN ({q})",
        model=Invoice,
    )


async def get_invoice_payments(invoice_id: str) -> list[Payment]:
    return await db.fetchall(
        "SELECT * FROM invoices.payments WHERE invoice_id = :id",
        {"id": invoice_id},
        Payment,
    )


async def get_invoice_payment(payment_id: str) -> Payment | None:
    return await db.fetchone(
        "SELECT * FROM invoices.payments WHERE id = :id",
        {"id": payment_id},
        Payment,
    )


async def get_payments_total(payments: list[Payment]) -> int:
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
    invoice_id: str, data: list[InvoiceItemData]
) -> list[InvoiceItem]:
    invoice_items = []
    for item in data:
        item_id = urlsafe_short_hash()
        invoice_item = InvoiceItem(
            id=item_id,
            invoice_id=invoice_id,
            description=item.description,
            amount=int(item.amount * 100),
            quantity=item.quantity,
        )
        invoice_items.append(invoice_item)
        await db.insert("invoices.invoice_items", invoice_item)
    return invoice_items


async def update_invoice_internal(invoice: Invoice) -> Invoice:
    await db.update("invoices.invoices", invoice, "WHERE id = :id AND wallet = :wallet")
    return invoice


async def mark_invoice_paid(invoice: Invoice) -> None:
    await db.execute(
        """
        UPDATE invoices.invoices SET status = :paid
        WHERE id = :id AND wallet = :wallet AND status = :open
        """,
        {
            "paid": InvoiceStatusEnum.paid.value,
            "id": invoice.id,
            "wallet": invoice.wallet,
            "open": InvoiceStatusEnum.open.value,
        },
    )


async def delete_invoice(
    invoice_id: str,
) -> bool:
    await db.execute(
        "DELETE FROM invoices.payment_requests WHERE invoice_id = :id",
        {"id": invoice_id},
    )
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


async def create_invoice_payment(
    invoice_id: str, amount: int, payment_id: str | None = None
) -> Payment:
    payment_id = payment_id or urlsafe_short_hash()
    await db.execute(
        """
        INSERT INTO invoices.payments (id, invoice_id, amount)
        VALUES (:id, :invoice_id, :amount)
        ON CONFLICT (id) DO NOTHING
        """,
        {"id": payment_id, "invoice_id": invoice_id, "amount": amount},
    )

    payment = await get_invoice_payment(payment_id)
    if not payment:
        raise ValueError("Newly created payment couldn't be retrieved")
    return payment


async def create_invoice_payment_request(
    invoice_id: str,
    payment_hash: str,
    amount: int,
    amount_msat: int,
    *,
    wallet_id: str,
    checking_id: str,
) -> None:
    await db.insert(
        "invoices.payment_requests",
        InvoicePaymentRequest(
            payment_hash=payment_hash,
            invoice_id=invoice_id,
            amount=amount,
            amount_msat=amount_msat,
            wallet_id=wallet_id,
            checking_id=checking_id,
        ),
    )


async def get_invoice_payment_request(
    payment_hash: str,
) -> InvoicePaymentRequest | None:
    return await db.fetchone(
        "SELECT * FROM invoices.payment_requests WHERE payment_hash = :payment_hash",
        {"payment_hash": payment_hash},
        InvoicePaymentRequest,
    )
