from fastapi import APIRouter
from app.api.v1.endpoints import admin, auth, users, documents, stocks, extractions, screener, stock_pools, institutions

api_router = APIRouter()
api_router.include_router(auth.router, prefix="/auth", tags=["auth"])
api_router.include_router(admin.router, prefix="/admin", tags=["admin"])
api_router.include_router(users.router, prefix="/users", tags=["users"])
api_router.include_router(documents.router, prefix="/documents", tags=["documents"])
api_router.include_router(stocks.router, prefix="/stocks", tags=["stocks"])
api_router.include_router(stock_pools.router, prefix="/stock_pools", tags=["stock_pools"])
api_router.include_router(extractions.router, prefix="/extractions", tags=["extractions"])
api_router.include_router(screener.router, prefix="/screener", tags=["screener"])
api_router.include_router(institutions.router, tags=["institutions"])
