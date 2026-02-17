from fastapi import FastAPI
from .api import agents

app = FastAPI()
app.include_router(agents.router)
