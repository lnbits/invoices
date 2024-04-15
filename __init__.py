import asyncio

from fastapi import APIRouter
from loguru import logger
from typing import List

from lnbits.db import Database
from lnbits.helpers import template_renderer
from lnbits.tasks import create_permanent_unique_task

db = Database("ext_invoices")


invoices_static_files = [
    {
        "path": "/invoices/static",
        "name": "invoices_static",
    }
]

invoices_ext: APIRouter = APIRouter(prefix="/invoices", tags=["invoices"])


def invoices_renderer():
    return template_renderer(["invoices/templates"])


from .tasks import wait_for_paid_invoices
from .views import *  # noqa: F401,F403
from .views_api import *  # noqa: F401,F403


scheduled_tasks: list[asyncio.Task] = []

def invoices_stop():
    for task in scheduled_tasks:
        try:
            task.cancel()
        except Exception as ex:
            logger.warning(ex)

def invoices_start():
    task = create_permanent_unique_task("ext_invoices", wait_for_paid_invoices)
    scheduled_tasks.append(task)
