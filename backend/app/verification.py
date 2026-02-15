"""Agent endpoint health check service."""
import httpx
from fastapi import APIRouter, HTTPException, Depends, BackgroundTasks
from sqlalchemy.orm import Session
from datetime import datetime, timedelta

from app.database import get_db
from app.models import Agent
from app.auth import get_current_agent
from app.config import get_settings

settings = get_settings()
router = APIRouter(prefix="/v1/verify", tags=["verification"])

# Health check timeout
VERIFY_TIMEOUT = 10.0  # seconds


async def check_endpoint_health(endpoint: str) -> dict:
    """
    Check if an endpoint is reachable and responds.
    Returns health status and response time.
    """
    try:
        async with httpx.AsyncClient(timeout=VERIFY_TIMEOUT) as client:
            start = datetime.utcnow()
            
            # Try HEAD first (lighter), fall back to GET
            try:
                response = await client.head(endpoint)
            except:
                response = await client.get(endpoint)
            
            latency_ms = int((datetime.utcnow() - start).total_seconds() * 1000)
            
            return {
                "reachable": True,
                "status_code": response.status_code,
                "latency_ms": latency_ms,
                "healthy": 200 <= response.status_code < 500,
                "error": None
            }
    except httpx.TimeoutException:
        return {
            "reachable": False,
            "status_code": None,
            "latency_ms": None,
            "healthy": False,
            "error": "timeout"
        }
    except httpx.ConnectError:
        return {
            "reachable": False,
            "status_code": None,
            "latency_ms": None,
            "healthy": False,
            "error": "connection_failed"
        }
    except Exception as e:
        return {
            "reachable": False,
            "status_code": None,
            "latency_ms": None,
            "healthy": False,
            "error": str(e)[:100]
        }


def is_verified(agent: Agent) -> bool:
    """Check if agent is verified (paid tier)."""
    return agent.subscription_tier in ("pro", "enterprise")


@router.post("/endpoint")
async def verify_my_endpoint(
    background_tasks: BackgroundTasks,
    current_agent: Agent = Depends(get_current_agent),
    db: Session = Depends(get_db)
):
    """Check your agent's endpoint is reachable (health check)."""
    
    result = await check_endpoint_health(current_agent.endpoint)
    
    current_agent.verified_endpoint = result["healthy"]
    current_agent.last_verification = datetime.utcnow()
    current_agent.last_latency_ms = result.get("latency_ms")
    db.commit()
    
    return {
        "agent_id": str(current_agent.id),
        "endpoint": current_agent.endpoint,
        "reachable": result["healthy"],
        **result
    }


@router.get("/endpoint/{agent_id}")
async def check_agent_endpoint(
    agent_id: str,
    db: Session = Depends(get_db)
):
    """Check if an agent's endpoint is reachable (public, cached 5 min)."""
    
    agent = db.query(Agent).filter(Agent.id == agent_id).first()
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    
    # Return cached result if recent (within 5 minutes)
    if agent.last_verification:
        age = datetime.utcnow() - agent.last_verification
        if age < timedelta(minutes=5):
            return {
                "agent_id": str(agent.id),
                "endpoint": agent.endpoint,
                "reachable": agent.verified_endpoint,
                "cached": True,
                "last_check": agent.last_verification.isoformat(),
                "latency_ms": agent.last_latency_ms
            }
    
    # Fresh check
    result = await check_endpoint_health(agent.endpoint)
    
    agent.verified_endpoint = result["healthy"]
    agent.last_verification = datetime.utcnow()
    agent.last_latency_ms = result.get("latency_ms")
    db.commit()
    
    return {
        "agent_id": str(agent.id),
        "endpoint": agent.endpoint,
        "reachable": result["healthy"],
        "cached": False,
        **result
    }


@router.get("/status/{agent_id}")
def get_verification_status(
    agent_id: str,
    db: Session = Depends(get_db)
):
    """Get verification status for an agent."""
    
    agent = db.query(Agent).filter(Agent.id == agent_id).first()
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    
    return {
        "agent_id": str(agent.id),
        "subscription_tier": agent.subscription_tier or "free",
        "verified": is_verified(agent),
        "endpoint_reachable": agent.verified_endpoint,
        "last_health_check": agent.last_verification.isoformat() if agent.last_verification else None,
        "last_latency_ms": agent.last_latency_ms,
        "last_seen": agent.last_seen.isoformat() if agent.last_seen else None
    }
