import asyncio

from lnbits.core.crud import get_standalone_payment
from lnbits.core.models import Payment
from lnbits.settings import settings
from lnbits.tasks import register_invoice_listener

from .crud import (
    create_invoice_payment,
    get_invoice,
    get_invoice_items,
    get_invoice_payment_request,
    get_invoice_payments,
    get_invoice_total,
    get_payments_total,
    mark_invoice_paid,
)


async def wait_for_paid_invoices():
    invoice_queue = asyncio.Queue()
    register_invoice_listener(invoice_queue, "ext_invoices")

    while settings.lnbits_running:
        payment = await invoice_queue.get()
        await on_invoice_paid(payment)


async def on_invoice_paid(payment: Payment) -> None:
    if not payment.extra or payment.extra.get("tag") != "invoices":
        return
    if not payment.is_in or not payment.success:
        return

    request = await get_invoice_payment_request(payment.payment_hash)
    if not request or payment.extra.get("invoice_id") != request.invoice_id:
        return
    invoice_id = request.invoice_id
    invoice = await get_invoice(invoice_id)
    if (
        not invoice
        or payment.wallet_id != (request.wallet_id or invoice.wallet)
        or payment.amount != request.amount_msat
    ):
        return

    checking_id = request.checking_id
    if checking_id is None:
        # Quotes issued before m004 only recorded the core payment hash.
        original = await get_standalone_payment(
            request.payment_hash, incoming=True, wallet_id=invoice.wallet
        )
        if not original or original.payment_hash != request.payment_hash:
            return
        checking_id = original.checking_id
    if payment.checking_id != checking_id:
        return

    # The quote is in invoice currency; the exact payment amount is in msat.
    await create_invoice_payment(
        invoice_id=invoice_id, amount=request.amount, payment_id=payment.payment_hash
    )

    invoice_items = await get_invoice_items(invoice_id)
    invoice_total = await get_invoice_total(invoice_items)

    invoice_payments = await get_invoice_payments(invoice_id)
    payments_total = await get_payments_total(invoice_payments)

    if payments_total >= invoice_total:
        await mark_invoice_paid(invoice)
