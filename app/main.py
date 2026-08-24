from fastapi import FastAPI,HTTPException,Request,Response


app = FastAPI()




@app.get('health')
def health():
   {'status':'ok'}





