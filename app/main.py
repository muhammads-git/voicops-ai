from fastapi import FastAPI,HTTPException,Request,Response
from app.routers.route import router

app = FastAPI()

app.include_router(router)


@app.get('health')
def health():
   {'status':'ok'}





