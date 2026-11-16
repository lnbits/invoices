import asyncio

from lnbits.core.models import Payment
from lnbits.tasks import register_invoice_listener

from .crud import (
    create_invoice_payment,
    get_invoice,
    get_invoice_items,
    get_invoice_payment_request,
    get_invoice_payments,
    get_invoice_total,
    get_payments_total,
    update_invoice_internal,
)
from .models import InvoiceStatusEnum


async def wait_for_paid_invoices():
    invoice_queue = asyncio.Queue()
    register_invoice_listener(invoice_queue, "ext_invoices")

    while True:
        payment = await invoice_queue.get()
        await on_invoice_paid(payment)


async def on_invoice_paid(payment: Payment) -> None:
    if not payment.is_in or not payment.success:
        return

    request = await get_invoice_payment_request(payment.payment_hash)
    if not request:
        return
    invoice_id = request.invoice_id
    invoice = await get_invoice(invoice_id)
    if (
        not invoice
        or payment.wallet_id != invoice.wallet
        or payment.amount != request.amount_msat
    ):
        return

    await create_invoice_payment(
        invoice_id=invoice_id, amount=request.amount, payment_id=payment.payment_hash
    )

    invoice_items = await get_invoice_items(invoice_id)
    invoice_total = await get_invoice_total(invoice_items)

    invoice_payments = await get_invoice_payments(invoice_id)
    payments_total = await get_payments_total(invoice_payments)

    if payments_total >= invoice_total:
        invoice.status = InvoiceStatusEnum.paid
        await update_invoice_internal(invoice)

    return
