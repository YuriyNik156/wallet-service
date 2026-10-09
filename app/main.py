from fastapi import FastAPI

from app.wallets import router as wallets_router

app = FastAPI(title="Wallet Service")
app.include_router(wallets_router)
