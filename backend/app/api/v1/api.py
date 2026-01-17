from fastapi import APIRouter
from app.api.v1.endpoints import users, documents, stocks, extractions, screener

api_router = APIRouter()
api_router.include_router(users.router, prefix="/users", tags=["users"])
api_router.include_router(documents.router, prefix="/documents", tags=["documents"])
api_router.include_router(stocks.router, prefix="/stocks", tags=["stocks"])
api_router.include_router(extractions.router, prefix="/extractions", tags=["extractions"])
api_router.include_router(screener.router, prefix="/screener", tags=["screener"])