from contextlib import asynccontextmanager
from fastapi import FastAPI
from app.routers.route import router
from app.database import init_db


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    yield


app = FastAPI(lifespan=lifespan)
app.include_router(router)


@app.get('/health')
def health():
    return {'status': 'ok'}





