from http import HTTPStatus

from fastapi import APIRouter, Depends, HTTPException, Query
from lnbits.core.crud import get_standalone_payment, get_user
from lnbits.core.models import WalletTypeInfo
from lnbits.core.services import create_invoice
from lnbits.decorators import require_admin_key
from lnbits.utils.exchange_rates import fiat_amount_as_satoshis
from loguru import logger
from pydantic import BaseModel

from .crud import (
    create_invoice_internal,
    create_invoice_items,
    create_invoice_payment_request,
    delete_invoice,
    delete_invoice_items,
    get_invoice,
    get_invoice_items,
    get_invoice_payment_request,
    get_invoice_payments,
    get_invoice_total,
    get_invoices,
    get_payments_total,
    update_invoice_internal,
)
from .models import (
    CreateInvoiceData,
    Invoice,
    InvoiceFull,
    InvoiceStatusEnum,
    UpdateInvoiceData,
)

invoices_api_router = APIRouter()


@invoices_api_router.get("/api/v1/invoices")
async def api_invoices(
    all_wallets: bool = Query(None),
    key_info: WalletTypeInfo = Depends(require_admin_key),
) -> list[Invoice]:
    wallet_ids = [key_info.wallet.id]
    if all_wallets:
        user = await get_user(key_info.wallet.user)
        wallet_ids = user.wallet_ids if user else []
    invoices = await get_invoices(wallet_ids)

    return invoices


@invoices_api_router.get("/api/v1/invoice/{invoice_id}")
async def api_invoice(
    invoice_id: str, key_info: WalletTypeInfo = Depends(require_admin_key)
) -> InvoiceFull:
    invoice = await get_invoice(invoice_id)
    if not invoice:
        raise HTTPException(
            status_code=HTTPStatus.NOT_FOUND, detail="Invoice does not exist."
        )
    if invoice.wallet != key_info.wallet.id:
        raise HTTPException(
            status_code=HTTPStatus.FORBIDDEN,
            detail="You do not have permission to read this invoice.",
        )
    invoice_items = await get_invoice_items(invoice_id)

    invoice_payments = await get_invoice_payments(invoice_id)
    payments_total = await get_payments_total(invoice_payments)

    invoice = InvoiceFull(
        **invoice.model_dump(), items=invoice_items, payments=payments_total
    )
    return invoice


@invoices_api_router.post("/api/v1/invoice", status_code=HTTPStatus.CREATED)
async def api_invoice_create(
    data: CreateInvoiceData, key_info: WalletTypeInfo = Depends(require_admin_key)
) -> Invoice:
    invoice = await create_invoice_internal(wallet_id=key_info.wallet.id, data=data)
    await create_invoice_items(invoice_id=invoice.id, data=data.items)
    return invoice


@invoices_api_router.delete("/api/v1/invoice/{invoice_id}")
async def api_invoice_delete(
    invoice_id: str, key_info: WalletTypeInfo = Depends(require_admin_key)
):
    invoice = await get_invoice(invoice_id)
    if not invoice:
        raise HTTPException(
            status_code=HTTPStatus.NOT_FOUND, detail="Invoice does not exist."
        )
    if invoice.wallet != key_info.wallet.id:
        raise HTTPException(
            status_code=HTTPStatus.FORBIDDEN,
            detail="You do not have permission to delete this invoice.",
        )
    try:
        status = await delete_invoice(invoice_id=invoice_id)
        return {"status": status}
    except Exception as exc:
        raise HTTPException(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR, detail=str(exc)
        ) from exc


@invoices_api_router.put("/api/v1/invoice/{invoice_id}")
async def api_invoice_update(
    data: UpdateInvoiceData,
    invoice_id: str,
    key_info: WalletTypeInfo = Depends(require_admin_key),
) -> Invoice:
    invoice = await get_invoice(invoice_id)
    if not invoice:
        raise HTTPException(
            status_code=HTTPStatus.NOT_FOUND, detail="Invoice does not exist."
        )
    if invoice.wallet != key_info.wallet.id:
        raise HTTPException(
            status_code=HTTPStatus.FORBIDDEN,
            detail="You do not have permission to update this invoice.",
        )

    for key, value in data.model_dump(exclude={"items"}).items():
        setattr(invoice, key, value)

    await delete_invoice_items(invoice_id=invoice_id)
    await create_invoice_items(invoice_id=invoice_id, data=data.items)

    await update_invoice_internal(invoice)

    return invoice


class InvoiceAmountPayment(BaseModel):
    famount: int = Query(..., ge=1, description="Amount to pay in fiat currency.")


class InvoicePaymentResponse(BaseModel):
    bolt11: str
    payment_hash: str


@invoices_api_router.post(
    "/api/v1/invoice/{invoice_id}/payments", status_code=HTTPStatus.CREATED
)
async def api_invoices_create_payment(
    invoice_id: str, data: InvoiceAmountPayment
) -> InvoicePaymentResponse:
    invoice = await get_invoice(invoice_id)
    if not invoice:
        raise HTTPException(
            status_code=HTTPStatus.NOT_FOUND, detail="Invoice does not exist."
        )
    if invoice.status != InvoiceStatusEnum.open:
        raise HTTPException(
            status_code=HTTPStatus.BAD_REQUEST, detail="Invoice is not open."
        )

    invoice_items = await get_invoice_items(invoice_id)
    invoice_total = await get_invoice_total(invoice_items)

    invoice_payments = await get_invoice_payments(invoice_id)
    payments_total = await get_payments_total(invoice_payments)

    if payments_total + data.famount > invoice_total:
        raise HTTPException(
            status_code=HTTPStatus.BAD_REQUEST, detail="Amount exceeds invoice due."
        )

    if invoice.currency != "sats":
        price_in_sats = await fiat_amount_as_satoshis(
            data.famount / 100, invoice.currency
        )
    else:
        price_in_sats = data.famount

    try:
        payment = await create_invoice(
            wallet_id=invoice.wallet,
            amount=price_in_sats,
            memo=f"Payment for invoice {invoice_id}",
            extra={
                "tag": "invoices",
                "invoice_id": invoice_id,
            },
        )
        await create_invoice_payment_request(
            invoice_id=invoice.id,
            payment_hash=payment.payment_hash,
            amount=data.famount,
            amount_msat=payment.amount,
            wallet_id=payment.wallet_id,
            checking_id=payment.checking_id,
        )
    except Exception as exc:
        logger.error("Could not create invoice payment: {}", exc)
        raise HTTPException(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
            detail="Could not create invoice payment.",
        ) from exc

    return InvoicePaymentResponse(
        bolt11=payment.bolt11, payment_hash=payment.payment_hash
    )


@invoices_api_router.get("/api/v1/invoice/{invoice_id}/payments/{payment_hash}")
async def api_invoices_check_payment(
    invoice_id: str,
    payment_hash: str,
    key_info: WalletTypeInfo = Depends(require_admin_key),
):
    invoice = await get_invoice(invoice_id)
    if not invoice:
        raise HTTPException(
            status_code=HTTPStatus.NOT_FOUND, detail="Invoice does not exist."
        )
    if invoice.wallet != key_info.wallet.id:
        raise HTTPException(
            status_code=HTTPStatus.FORBIDDEN,
            detail="You do not have permission to check payments for this invoice.",
        )
    try:
        quote = await get_invoice_payment_request(payment_hash)
        if not quote or quote.invoice_id != invoice_id:
            return {"paid": False}

        payment = await get_standalone_payment(
            quote.checking_id or payment_hash, incoming=True
        )
        return {
            "paid": bool(
                payment
                and payment.success
                and payment.payment_hash == quote.payment_hash
                and payment.wallet_id == (quote.wallet_id or invoice.wallet)
                and payment.amount == quote.amount_msat
                and (
                    quote.checking_id is None
                    or payment.checking_id == quote.checking_id
                )
            )
        }

    except Exception as exc:
        logger.error(exc)
        return {"paid": False}
