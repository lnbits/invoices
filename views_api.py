from http import HTTPStatus

from fastapi import APIRouter, Depends, HTTPException, Query
from lnbits.core.crud import get_standalone_payment, get_user
from lnbits.core.models import WalletTypeInfo
from lnbits.core.services import create_invoice
from lnbits.decorators import get_key_type
from lnbits.utils.exchange_rates import fiat_amount_as_satoshis
from loguru import logger

from .crud import (
    create_invoice_internal,
    create_invoice_items,
    delete_invoice,
    get_invoice,
    get_invoice_items,
    get_invoice_payments,
    get_invoice_total,
    get_invoices,
    get_payments_total,
    update_invoice_internal,
    update_invoice_items,
)
from .models import CreateInvoiceData, UpdateInvoiceData

invoices_api_router = APIRouter()


@invoices_api_router.get("/api/v1/invoices", status_code=HTTPStatus.OK)
async def api_invoices(
    all_wallets: bool = Query(None), wallet: WalletTypeInfo = Depends(get_key_type)
):
    wallet_ids = [wallet.wallet.id]
    if all_wallets:
        user = await get_user(wallet.wallet.user)
        wallet_ids = user.wallet_ids if user else []

    return [invoice.dict() for invoice in await get_invoices(wallet_ids)]


@invoices_api_router.get("/api/v1/invoice/{invoice_id}", status_code=HTTPStatus.OK)
async def api_invoice(invoice_id: str):
    invoice = await get_invoice(invoice_id)
    if not invoice:
        raise HTTPException(
            status_code=HTTPStatus.NOT_FOUND, detail="Invoice does not exist."
        )
    invoice_items = await get_invoice_items(invoice_id)

    invoice_payments = await get_invoice_payments(invoice_id)
    payments_total = await get_payments_total(invoice_payments)

    invoice_dict = invoice.dict()
    invoice_dict["items"] = invoice_items
    invoice_dict["payments"] = payments_total
    return invoice_dict


@invoices_api_router.post("/api/v1/invoice", status_code=HTTPStatus.CREATED)
async def api_invoice_create(
    data: CreateInvoiceData, wallet: WalletTypeInfo = Depends(get_key_type)
):
    invoice = await create_invoice_internal(wallet_id=wallet.wallet.id, data=data)
    items = await create_invoice_items(invoice_id=invoice.id, data=data.items)
    invoice_dict = invoice.dict()
    invoice_dict["items"] = items
    return invoice_dict


@invoices_api_router.delete("/api/v1/invoice/{invoice_id}", status_code=HTTPStatus.OK)
async def api_invoice_delete(invoice_id: str):
    try:
        status = await delete_invoice(invoice_id=invoice_id)
        return {"status": status}
    except Exception as exc:
        raise HTTPException(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR, detail=str(exc)
        ) from exc


@invoices_api_router.post("/api/v1/invoice/{invoice_id}", status_code=HTTPStatus.OK)
async def api_invoice_update(
    data: UpdateInvoiceData,
    invoice_id: str,
    wallet: WalletTypeInfo = Depends(get_key_type),
):
    invoice = await update_invoice_internal(wallet_id=wallet.wallet.id, data=data)
    items = await update_invoice_items(invoice_id=invoice_id, data=data.items)
    invoice_dict = invoice.dict()
    invoice_dict["items"] = items
    return invoice_dict


@invoices_api_router.post(
    "/api/v1/invoice/{invoice_id}/payments", status_code=HTTPStatus.CREATED
)
async def api_invoices_create_payment(invoice_id: str, famount: int = Query(..., ge=1)):
    invoice = await get_invoice(invoice_id)
    invoice_items = await get_invoice_items(invoice_id)
    invoice_total = await get_invoice_total(invoice_items)

    invoice_payments = await get_invoice_payments(invoice_id)
    payments_total = await get_payments_total(invoice_payments)

    if payments_total + famount > invoice_total:
        raise HTTPException(
            status_code=HTTPStatus.BAD_REQUEST, detail="Amount exceeds invoice due."
        )

    if not invoice:
        raise HTTPException(
            status_code=HTTPStatus.NOT_FOUND, detail="Invoice does not exist."
        )

    price_in_sats = await fiat_amount_as_satoshis(famount / 100, invoice.currency)

    try:
        payment_hash, payment_request = await create_invoice(
            wallet_id=invoice.wallet,
            amount=price_in_sats,
            memo=f"Payment for invoice {invoice_id}",
            extra={"tag": "invoices", "invoice_id": invoice_id, "famount": famount},
        )
    except Exception as exc:
        raise HTTPException(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR, detail=str(exc)
        ) from exc

    return {"payment_hash": payment_hash, "payment_request": payment_request}


@invoices_api_router.get(
    "/api/v1/invoice/{invoice_id}/payments/{payment_hash}", status_code=HTTPStatus.OK
)
async def api_invoices_check_payment(invoice_id: str, payment_hash: str):
    invoice = await get_invoice(invoice_id)
    if not invoice:
        raise HTTPException(
            status_code=HTTPStatus.NOT_FOUND, detail="Invoice does not exist."
        )
    try:
        payment = await get_standalone_payment(payment_hash)
        assert payment, "Payment not found."
        status = await payment.check_status()
        return {"paid": status.paid}

    except Exception as exc:
        logger.error(exc)
        return {"paid": False}
