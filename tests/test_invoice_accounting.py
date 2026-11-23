from pathlib import Path
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio
from fastapi import FastAPI, HTTPException
from httpx import ASGITransport, AsyncClient
from jinja2 import FileSystemLoader
from lnbits import decorators
from lnbits.core.models import KeyType, Payment, Wallet, WalletTypeInfo
from lnbits.db import Database
from lnbits.settings import settings

from .. import crud, invoices_ext, migrations, tasks, views, views_api
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
        await migrations.m004_bind_invoice_payment_requests(conn)
    yield db
    await db.engine.dispose()


@pytest_asyncio.fixture
async def invoice(invoice_db):
    data = CreateInvoiceData(
        status=InvoiceStatusEnum.open,
        currency="USD",
        email="billing@example.com",
        items=[InvoiceItemData(description="Item", amount=10, quantity=1)],
    )
    invoice = await crud.create_invoice_internal("merchant", data)
    await crud.create_invoice_items(invoice.id, data.items)
    return invoice


@pytest.fixture
def payment(invoice):
    return Payment(
        checking_id="checking",
        payment_hash="a" * 64,
        wallet_id="merchant",
        amount=50_000,
        fee=0,
        bolt11="invoice",
        status="success",
        extra={"tag": "invoices", "invoice_id": invoice.id, "famount": 999_999},
    )


@pytest.mark.asyncio
async def test_delete_requires_invoice_wallet(invoice):
    await crud.create_invoice_payment(invoice.id, 1)
    await crud.create_invoice_payment_request(
        invoice.id, "hash", 1, 1_000, wallet_id=invoice.wallet, checking_id="checking"
    )
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
    await tasks.on_invoice_paid(payment.model_copy(update={"amount": 1_000}))
    stored = await crud.get_invoice(invoice.id)
    assert stored is not None
    assert stored.status == "open"
    assert await crud.get_invoice_payments(invoice.id) == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "changes",
    [
        {"wallet_id": "other"},
        {"checking_id": "other"},
        {"payment_hash": "b" * 64},
        {"amount": 1_000},
        {"amount": -50_000},
        {"status": "pending"},
        {"status": "failed"},
        {"extra": {}},
        {"extra": {"tag": "other"}},
        {"extra": {"tag": "invoices", "invoice_id": "other"}},
    ],
)
async def test_recorded_payment_must_match(invoice, payment, changes):
    await crud.create_invoice_payment_request(
        invoice.id,
        payment.payment_hash,
        1_000,
        payment.amount,
        wallet_id=payment.wallet_id,
        checking_id=payment.checking_id,
    )
    await tasks.on_invoice_paid(payment.model_copy(update=changes))
    stored = await crud.get_invoice(invoice.id)
    assert stored is not None
    assert stored.status == "open"
    assert await crud.get_invoice_payments(invoice.id) == []


@pytest.mark.asyncio
async def test_partial_payments_use_recorded_amount_once(invoice, payment):
    await crud.create_invoice_payment_request(
        invoice.id,
        payment.payment_hash,
        500,
        payment.amount,
        wallet_id=payment.wallet_id,
        checking_id=payment.checking_id,
    )
    await tasks.on_invoice_paid(payment)
    await tasks.on_invoice_paid(payment)
    payments = await crud.get_invoice_payments(invoice.id)
    assert await crud.get_payments_total(payments) == 500
    stored = await crud.get_invoice(invoice.id)
    assert stored is not None
    assert stored.status == "open"

    second = payment.model_copy(
        update={"payment_hash": "b" * 64, "checking_id": "second-checking"}
    )
    await crud.create_invoice_payment_request(
        invoice.id,
        second.payment_hash,
        500,
        second.amount,
        wallet_id=second.wallet_id,
        checking_id=second.checking_id,
    )
    await tasks.on_invoice_paid(second)
    await tasks.on_invoice_paid(second)
    payments = await crud.get_invoice_payments(invoice.id)
    assert await crud.get_payments_total(payments) == 1_000
    stored = await crud.get_invoice(invoice.id)
    assert stored is not None
    assert stored.status == "paid"


@pytest.mark.asyncio
async def test_legacy_quote_settles_after_upgrade(
    invoice_db, invoice, payment, monkeypatch
):
    await invoice_db.execute(
        """
        INSERT INTO invoices.payment_requests
            (payment_hash, invoice_id, amount, amount_msat)
        VALUES (:hash, :id, 1000, :amount)
        """,
        {"hash": payment.payment_hash, "id": invoice.id, "amount": payment.amount},
    )
    lookup = AsyncMock(return_value=payment)
    monkeypatch.setattr(tasks, "get_standalone_payment", lookup)
    await tasks.on_invoice_paid(payment.model_copy(update={"checking_id": "wrong"}))
    assert await crud.get_invoice_payments(invoice.id) == []
    await tasks.on_invoice_paid(payment)
    assert (
        await crud.get_payments_total(await crud.get_invoice_payments(invoice.id))
        == 1_000
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["draft", "canceled", "paid"])
async def test_payment_quotes_require_open_invoice(invoice, status, monkeypatch):
    invoice.status = status
    await crud.update_invoice_internal(invoice)
    create = AsyncMock()
    monkeypatch.setattr(views_api, "create_invoice", create)
    with pytest.raises(HTTPException) as error:
        await views_api.api_invoices_create_payment(
            invoice.id, views_api.InvoiceAmountPayment(famount=100)
        )
    assert error.value.status_code == 400
    create.assert_not_awaited()


@pytest.mark.asyncio
async def test_invoice_wallet_isolation_and_public_checkout(
    invoice_db, invoice, payment, monkeypatch
):
    merchant = _key_info(invoice.wallet).wallet
    other_wallet = _key_info("other").wallet
    keys = {wallet.adminkey: wallet for wallet in (merchant, other_wallet)}
    keys[merchant.inkey] = merchant
    monkeypatch.setattr(decorators, "db", invoice_db)
    monkeypatch.setattr(
        decorators,
        "get_wallet_for_key",
        AsyncMock(side_effect=lambda key, **_: keys.get(key)),
    )
    monkeypatch.setattr(decorators, "_check_user_access", AsyncMock())

    renderer = views.invoices_renderer()
    renderer.env.loader = FileSystemLoader(
        [
            Path(__file__).resolve().parents[1] / "templates",
            Path(settings.lnbits_path) / "templates",
        ]
    )
    monkeypatch.setattr(views, "invoices_renderer", lambda: renderer)
    quote = AsyncMock(return_value=50)
    monkeypatch.setattr(views_api, "fiat_amount_as_satoshis", quote)
    payment.wallet_id = "shared-wallet-source"
    create = AsyncMock(return_value=payment)
    monkeypatch.setattr(views_api, "create_invoice", create)
    lookup = AsyncMock(return_value=payment)
    monkeypatch.setattr(views_api, "get_standalone_payment", lookup)

    app = FastAPI()
    app.include_router(invoices_ext)
    owner_key = {"X-Api-Key": merchant.adminkey}
    other_key = {"X-Api-Key": other_wallet.adminkey}
    path = f"/invoices/api/v1/invoice/{invoice.id}"
    items = [{"description": "Another item", "amount": 10, "quantity": 1}]
    body = {"status": "open", "currency": "USD", "items": items}

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        assert (await client.get(path)).status_code == 401
        assert (
            await client.get(path, headers={"X-Api-Key": merchant.inkey})
        ).status_code == 403
        assert (await client.get(path, headers=other_key)).status_code == 403
        assert (await client.put(path, headers=other_key, json=body)).status_code == 403
        assert (await client.delete(path, headers=other_key)).status_code == 403
        assert (await client.get(path, headers=owner_key)).json()[
            "email"
        ] == invoice.email

        response = await client.post(
            "/invoices/api/v1/invoice", headers=other_key, json=body
        )
        assert response.status_code == 201
        other_id = response.json()["id"]
        other_path = f"/invoices/api/v1/invoice/{other_id}"
        original_item = (await crud.get_invoice_items(invoice.id))[0]
        response = await client.put(
            other_path,
            headers=other_key,
            json={
                **body,
                "id": invoice.id,
                "wallet": invoice.wallet,
                "email": "updated@example.com",
                "items": [
                    {**items[0], "id": original_item.id, "invoice_id": invoice.id}
                ],
            },
        )
        assert response.status_code == 200
        assert response.json()["id"] == other_id
        assert response.json()["wallet"] == other_wallet.id
        assert response.json()["email"] == "updated@example.com"
        updated_item = (await crud.get_invoice_items(other_id))[0]
        assert updated_item.invoice_id == other_id
        assert updated_item.id != original_item.id
        assert await crud.get_invoice_items(invoice.id) == [original_item]

        response = await client.get(f"/invoices/pay/{invoice.id}")
        assert response.status_code == 200
        assert "Bill To" in response.text and "billing@example.com" in response.text
        assert '\\"wallet\\"' not in response.text

        response = await client.post(
            f"{path}/payments",
            json={"famount": 100, "wallet": other_wallet.id, "invoice_id": other_id},
        )
        assert response.status_code == 201
        assert response.json() == {
            "bolt11": payment.bolt11,
            "payment_hash": payment.payment_hash,
        }
        quote.assert_awaited_once_with(1, "USD")
        assert create.call_args.kwargs["wallet_id"] == invoice.wallet
        assert create.call_args.kwargs["amount"] == 50
        await tasks.on_invoice_paid(payment)
        await tasks.on_invoice_paid(payment)
        ledger_payments = await crud.get_invoice_payments(invoice.id)
        assert [entry.amount for entry in ledger_payments] == [100]

        status_path = f"{path}/payments/{payment.payment_hash}"
        assert (await client.get(status_path, headers=other_key)).status_code == 403
        response = await client.get(
            f"{other_path}/payments/{payment.payment_hash}", headers=other_key
        )
        assert response.json() == {"paid": False}
        lookup.assert_not_awaited()
        assert (await client.get(status_path, headers=owner_key)).json() == {
            "paid": True
        }
        assert (await client.delete(other_path, headers=other_key)).json() == {
            "status": True
        }


def _key_info(wallet_id: str) -> WalletTypeInfo:
    return WalletTypeInfo(
        key_type=KeyType.admin,
        wallet=Wallet(
            id=wallet_id,
            user=f"{wallet_id}-user",
            name="Test wallet",
            adminkey=f"{wallet_id}-admin-key",
            inkey=f"{wallet_id}-invoice-key",
        ),
    )
