from fastapi import FastAPI
from .api import agents
from .api import admin
from .middleware.rate_limit import RateLimitMiddleware

app = FastAPI()
app.add_middleware(RateLimitMiddleware)
app.include_router(agents.router)
app.include_router(admin.router)
