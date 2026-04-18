import logging

from fastapi import FastAPI

from src.trailgoods.api.v1.router import api_router
from src.trailgoods.middleware.logging import RequestLoggingMiddleware
from src.trailgoods.middleware.request_id import RequestIDMiddleware

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)


def create_app() -> FastAPI:
    application = FastAPI(title="TrailGoods Commerce & Logistics API", version="1.0.0")
    application.add_middleware(RequestLoggingMiddleware)
    application.add_middleware(RequestIDMiddleware)
    application.include_router(api_router)
    return application


app = create_app()
