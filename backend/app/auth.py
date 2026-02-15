import secrets
import hashlib
from typing import Optional
from fastapi import Header, HTTPException, Depends
from sqlalchemy.orm import Session
from app.database import get_db
from app.models import Agent
from app.config import get_settings

settings = get_settings()


def generate_api_key() -> str:
    """Generate a new API key."""
    random_bytes = secrets.token_hex(24)
    return f"{settings.api_key_prefix}{random_bytes}"


def hash_api_key(api_key: str) -> str:
    """Hash an API key for storage."""
    return hashlib.sha256(api_key.encode()).hexdigest()


def get_current_agent(
    authorization: Optional[str] = Header(None),
    db: Session = Depends(get_db)
) -> Agent:
    """Get the current agent from the API key."""
    if not authorization:
        raise HTTPException(status_code=401, detail="Missing authorization header")
    
    # Support "Bearer <key>" or just "<key>"
    api_key = authorization
    if authorization.startswith("Bearer "):
        api_key = authorization[7:]
    
    key_hash = hash_api_key(api_key)
    agent = db.query(Agent).filter(Agent.api_key_hash == key_hash).first()
    
    if not agent:
        raise HTTPException(status_code=401, detail="Invalid API key")
    
    if not agent.is_active:
        raise HTTPException(status_code=403, detail="Agent is deactivated")
    
    return agent


def get_optional_agent(
    authorization: Optional[str] = Header(None),
    db: Session = Depends(get_db)
) -> Optional[Agent]:
    """Get the current agent if authenticated, None otherwise."""
    if not authorization:
        return None
    
    try:
        return get_current_agent(authorization, db)
    except HTTPException:
        return None
