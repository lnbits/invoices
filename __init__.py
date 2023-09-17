import asyncio

from fastapi import APIRouter
from typing import List

from lnbits.db import Database
from lnbits.helpers import template_renderer
from lnbits.tasks import catch_everything_and_restart

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

scheduled_tasks: List[asyncio.Task] = []

def invoices_start():
    loop = asyncio.get_event_loop()
    task = loop.create_task(catch_everything_and_restart(wait_for_paid_invoices))
    scheduled_tasks.append(task)


from .views import *  # noqa: F401,F403
from .views_api import *  # noqa: F401,F403
