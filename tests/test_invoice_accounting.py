from unittest.mock import AsyncMock

import pytest
import pytest_asyncio
from fastapi import HTTPException
from lnbits.core.models import KeyType, Payment, Wallet, WalletTypeInfo
from lnbits.db import Database
from lnbits.settings import settings

from .. import crud, migrations, tasks, views_api
from ..models import CreateInvoiceData, InvoiceItemData, InvoiceStatusEnum


@pytest_asyncio.fixture
async def invoice_db(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "lnbits_data_folder", str(tmp_path))
    db = Database("ext_invoices")
    monkeypatch.setattr(crud, "db", db)
    async with db.connect() as conn:
        await migrations.m001_initial_invoices(conn)
        await migrations.m002_invoices_add_quantity(conn)
        await migrations.m003_invoice_payment_requests(conn)
    yield db
    await db.engine.dispose()


@pytest_asyncio.fixture
async def invoice(invoice_db):
    data = CreateInvoiceData(
        status=InvoiceStatusEnum.open,
        currency="USD",
        items=[InvoiceItemData(description="Item", amount=10, quantity=1)],
    )
    invoice = await crud.create_invoice_internal("merchant", data)
    await crud.create_invoice_items(invoice.id, data.items)
    return invoice


@pytest.fixture
def payment():
    return Payment(
        checking_id="checking",
        payment_hash="a" * 64,
        wallet_id="merchant",
        amount=50_000,
        fee=0,
        bolt11="invoice",
        status="success",
        extra={"tag": "invoices", "invoice_id": "other", "famount": 999_999},
    )


@pytest.mark.asyncio
async def test_delete_requires_invoice_wallet(invoice):
    await crud.create_invoice_payment(invoice.id, 1)
    await crud.create_invoice_payment_request(invoice.id, "hash", 1, 1_000)
    with pytest.raises(HTTPException) as error:
        await views_api.api_invoice_delete(invoice.id, _key_info("other"))
    assert error.value.status_code == 403
    assert await crud.get_invoice(invoice.id)
    assert await crud.get_invoice_items(invoice.id)
    assert await crud.get_invoice_payments(invoice.id)
    assert await crud.get_invoice_payment_request("hash")

    result = await views_api.api_invoice_delete(invoice.id, _key_info("merchant"))
    assert result == {"status": True}
    assert await crud.get_invoice(invoice.id) is None
    assert await crud.get_invoice_items(invoice.id) == []
    assert await crud.get_invoice_payments(invoice.id) == []
    assert await crud.get_invoice_payment_request("hash") is None

    with pytest.raises(HTTPException) as error:
        await views_api.api_invoice_delete(invoice.id, _key_info("merchant"))
    assert error.value.status_code == 404


@pytest.mark.asyncio
async def test_unrecorded_payment_is_ignored(invoice, payment):
    payment.extra.update(invoice_id=invoice.id, famount=1_000)
    await tasks.on_invoice_paid(payment)
    stored = await crud.get_invoice(invoice.id)
    assert stored is not None
    assert stored.status == "open"
    assert await crud.get_invoice_payments(invoice.id) == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "changes",
    [
        {"wallet_id": "other"},
        {"amount": 1_000},
        {"amount": -50_000},
        {"status": "pending"},
        {"status": "failed"},
    ],
)
async def test_recorded_payment_must_match(invoice, payment, changes):
    await crud.create_invoice_payment_request(
        invoice.id, payment.payment_hash, 1_000, payment.amount
    )
    await tasks.on_invoice_paid(payment.model_copy(update=changes))
    stored = await crud.get_invoice(invoice.id)
    assert stored is not None
    assert stored.status == "open"
    assert await crud.get_invoice_payments(invoice.id) == []


@pytest.mark.asyncio
async def test_partial_payments_use_recorded_amount_once(invoice, payment):
    await crud.create_invoice_payment_request(
        invoice.id, payment.payment_hash, 500, payment.amount
    )
    await tasks.on_invoice_paid(payment)
    await tasks.on_invoice_paid(payment)
    payments = await crud.get_invoice_payments(invoice.id)
    assert await crud.get_payments_total(payments) == 500
    stored = await crud.get_invoice(invoice.id)
    assert stored is not None
    assert stored.status == "open"

    second = payment.model_copy(update={"payment_hash": "b" * 64, "extra": {}})
    await crud.create_invoice_payment_request(
        invoice.id, second.payment_hash, 500, second.amount
    )
    await tasks.on_invoice_paid(second)
    payments = await crud.get_invoice_payments(invoice.id)
    assert await crud.get_payments_total(payments) == 1_000
    stored = await crud.get_invoice(invoice.id)
    assert stored is not None
    assert stored.status == "paid"


@pytest.mark.asyncio
async def test_payer_endpoint_records_quote(invoice, payment, monkeypatch):
    quote = AsyncMock(return_value=50)
    create = AsyncMock(return_value=payment)
    monkeypatch.setattr(views_api, "fiat_amount_as_satoshis", quote)
    monkeypatch.setattr(views_api, "create_invoice", create)
    await views_api.api_invoices_create_payment(
        invoice.id, views_api.InvoiceAmountPayment(famount=1_000)
    )
    quote.assert_awaited_once_with(10, "USD")
    assert create.call_args.kwargs["wallet_id"] == invoice.wallet
    assert create.call_args.kwargs["amount"] == 50
    request = await crud.get_invoice_payment_request(payment.payment_hash)
    assert request is not None
    assert request.invoice_id == invoice.id
    assert request.amount == 1_000
    assert request.amount_msat == 50_000


def _key_info(wallet_id: str) -> WalletTypeInfo:
    return WalletTypeInfo(
        key_type=KeyType.admin,
        wallet=Wallet(
            id=wallet_id,
            user="user",
            name="Test wallet",
            adminkey="admin-key",
            inkey="invoice-key",
        ),
    )
