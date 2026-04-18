from fastapi import APIRouter

from src.trailgoods.api.v1.endpoints.assets import router as assets_router
from src.trailgoods.api.v1.endpoints.auth import router as auth_router
from src.trailgoods.api.v1.endpoints.catalog import router as catalog_router
from src.trailgoods.api.v1.endpoints.inventory import router as inventory_router
from src.trailgoods.api.v1.endpoints.reviews import router as reviews_router
from src.trailgoods.api.v1.endpoints.verification import router as verification_router

api_router = APIRouter()
api_router.include_router(auth_router)
api_router.include_router(assets_router)
api_router.include_router(catalog_router)
api_router.include_router(inventory_router)
api_router.include_router(reviews_router)
api_router.include_router(verification_router)
