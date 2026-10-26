from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from wireup import AsyncContainer
from wireup.integration.fastapi import setup

from stocklock.api.v1.errors import register_error_handlers
from stocklock.api.v1.router import router
from stocklock.project.container import create_container


def create_app(*, container: AsyncContainer | None = None) -> FastAPI:
  app = FastAPI(title="StockLock", docs_url="/api/docs")

  app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
  )

  app.include_router(router)

  register_error_handlers(app)

  setup(container if container is not None else create_container(), app)

  return app
