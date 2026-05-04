"""Entrypoint — connects DB, then runs dispatcher loop + /health side-by-side."""
import asyncio
import logging
import signal

import structlog

from oms_dispatcher import dispatcher, health
from oms_dispatcher.db import db
from oms_dispatcher.settings import settings


def _configure_logging() -> None:
    logging.basicConfig(level=getattr(logging, settings.log_level), format="%(message)s")
    # httpx logs request URLs at INFO; the adapter URLs we call don't carry
    # secrets, but mute anyway for consistency with the rest of the stack.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(
            getattr(logging, settings.log_level)
        ),
        logger_factory=structlog.PrintLoggerFactory(),
    )


async def _run() -> None:
    log = structlog.get_logger("oms_dispatcher.main")
    log.info("starting", version="0.1.0")

    await db.connect()

    tasks = [
        asyncio.create_task(dispatcher.loop(), name="dispatcher"),
        asyncio.create_task(health.serve(), name="health"),
    ]

    loop = asyncio.get_running_loop()
    stop = asyncio.Event()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, stop.set)

    log.info("started", tasks=[t.get_name() for t in tasks])

    done, _pending = await asyncio.wait(
        [*tasks, asyncio.create_task(stop.wait(), name="stop")],
        return_when=asyncio.FIRST_COMPLETED,
    )
    for t in done:
        if t.get_name() != "stop":
            log.error("task.exited", name=t.get_name(), result=t.exception())

    log.info("shutting_down")
    for t in tasks:
        t.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)
    await db.close()
    log.info("stopped")


def main() -> None:
    _configure_logging()
    asyncio.run(_run())


if __name__ == "__main__":
    main()
