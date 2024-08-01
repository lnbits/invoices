import asyncio

from fastapi import APIRouter
from loguru import logger

from .crud import db
from .tasks import wait_for_paid_invoices
from .views import invoices_generic_router
from .views_api import invoices_api_router

invoices_static_files = [
    {
        "path": "/invoices/static",
        "name": "invoices_static",
    }
]
invoices_ext: APIRouter = APIRouter(prefix="/invoices", tags=["invoices"])
invoices_ext.include_router(invoices_generic_router)
invoices_ext.include_router(invoices_api_router)

scheduled_tasks: list[asyncio.Task] = []


def invoices_stop():
    for task in scheduled_tasks:
        try:
            task.cancel()
        except Exception as ex:
            logger.warning(ex)


def invoices_start():
    from lnbits.tasks import create_permanent_unique_task

    task = create_permanent_unique_task("ext_invoices", wait_for_paid_invoices)
    scheduled_tasks.append(task)


__all__ = [
    "db",
    "invoices_static_files",
    "invoices_ext",
    "invoices_stop",
    "invoices_start",
]
