"""FastAPI entrypoint (Vercel loads ``coach.main:app``): the Telegram webhook and a health check."""

import hmac
import logging
from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from typing import Annotated

from fastapi import FastAPI, Header, HTTPException, Request, status

from coach.core.config import get_settings
from coach.core.deps import Deps, build_deps
from coach.core.handler import handle_update
from coach.core.telegram import Update

logging.basicConfig(level=logging.INFO)
# httpx logs request URLs at INFO, and Telegram URLs contain the bot token.
logging.getLogger("httpx").setLevel(logging.WARNING)
logger = logging.getLogger(__name__)

type DepsFactory = Callable[[], AbstractAsyncContextManager[Deps]]


def _default_deps() -> AbstractAsyncContextManager[Deps]:
    return build_deps(get_settings())


def create_app(deps_factory: DepsFactory = _default_deps) -> FastAPI:
    """Build the app; tests pass their own ``deps_factory``."""

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        async with deps_factory() as deps:
            app.state.deps = deps
            yield

    app = FastAPI(title="Hybrid Athlete Coach", lifespan=lifespan)

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/telegram")
    async def telegram_webhook(
        update: Update,
        request: Request,
        x_telegram_bot_api_secret_token: Annotated[str | None, Header()] = None,
    ) -> dict[str, bool]:
        deps: Deps = request.app.state.deps
        expected = deps.settings.telegram_webhook_secret.get_secret_value()
        if x_telegram_bot_api_secret_token is None or not hmac.compare_digest(
            x_telegram_bot_api_secret_token, expected
        ):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid secret")
        try:
            await handle_update(deps, update)
        except Exception:
            logger.exception("update %s failed", update.update_id)
        return {"ok": True}

    return app


app = create_app()
