from http import HTTPStatus

from fastapi import APIRouter, Depends, HTTPException, Request
from lnbits.core.models import User
from lnbits.decorators import check_user_exists
from lnbits.helpers import template_renderer
from starlette.responses import HTMLResponse

from .crud import (
    get_invoice,
    get_invoice_items,
    get_invoice_payments,
    get_invoice_total,
    get_payments_total,
)

invoices_generic_router = APIRouter()


def invoices_renderer():
    return template_renderer(["invoices/templates"])


@invoices_generic_router.get("/", response_class=HTMLResponse)
async def index(request: Request, user: User = Depends(check_user_exists)):
    return invoices_renderer().TemplateResponse(
        "invoices/index.html", {"request": request, "user": user.json()}
    )


@invoices_generic_router.get("/pay/{invoice_id}", response_class=HTMLResponse)
async def pay(request: Request, invoice_id: str):
    invoice = await get_invoice(invoice_id)

    if not invoice:
        raise HTTPException(
            status_code=HTTPStatus.NOT_FOUND, detail="Invoice does not exist."
        )

    invoice_items = await get_invoice_items(invoice_id)
    invoice_total = await get_invoice_total(invoice_items)

    invoice_payments = await get_invoice_payments(invoice_id)
    payments_total = await get_payments_total(invoice_payments)

    return invoices_renderer().TemplateResponse(
        "invoices/display.html",
        {
            "request": request,
            "invoice_id": invoice_id,
            "invoice": invoice.json(),
            "invoice_items": [item.json() for item in invoice_items],
            "invoice_total": invoice_total,
            "invoice_payments": [payment.json() for payment in invoice_payments],
            "payments_total": payments_total,
        },
    )
