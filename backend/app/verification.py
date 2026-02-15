"""Agent endpoint verification service."""
import httpx
import secrets
from fastapi import APIRouter, HTTPException, Depends, BackgroundTasks
from sqlalchemy.orm import Session
from datetime import datetime, timedelta
from typing import Optional
from pydantic import BaseModel

from app.database import get_db
from app.models import Agent
from app.auth import get_current_agent
from app.config import get_settings

settings = get_settings()
router = APIRouter(prefix="/v1/verify", tags=["verification"])

# Verification timeout
VERIFY_TIMEOUT = 10.0  # seconds

# In-memory challenge store (use Redis in production for multi-instance)
# {agent_id: {"token": str, "expires": datetime}}
pending_challenges = {}


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
                "healthy": 200 <= response.status_code < 500,  # Not a server error
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


async def verify_agent_endpoint(agent_id: str, db: Session):
    """Background task to verify an agent's endpoint."""
    agent = db.query(Agent).filter(Agent.id == agent_id).first()
    if not agent:
        return
    
    result = await check_endpoint_health(agent.endpoint)
    
    agent.verified_endpoint = result["healthy"]
    agent.last_verification = datetime.utcnow()
    agent.last_latency_ms = result.get("latency_ms")
    
    db.commit()


@router.post("/endpoint")
async def verify_my_endpoint(
    background_tasks: BackgroundTasks,
    current_agent: Agent = Depends(get_current_agent),
    db: Session = Depends(get_db)
):
    """Verify your agent's endpoint is reachable (basic health check)."""
    
    result = await check_endpoint_health(current_agent.endpoint)
    
    # Update verification status
    current_agent.verified_endpoint = result["healthy"]
    current_agent.last_verification = datetime.utcnow()
    current_agent.last_latency_ms = result.get("latency_ms")
    db.commit()
    
    return {
        "agent_id": str(current_agent.id),
        "endpoint": current_agent.endpoint,
        "verified": result["healthy"],
        **result
    }


# ============================================================
# Challenge-Response Verification (proves endpoint ownership)
# ============================================================

@router.post("/challenge")
async def request_challenge(
    current_agent: Agent = Depends(get_current_agent),
    db: Session = Depends(get_db)
):
    """
    Request a verification challenge token.
    
    Returns a token that must be served at:
    GET {endpoint}/.well-known/clawdir-verify?token={token}
    
    Your endpoint should return: {"token": "{token}"}
    """
    agent_id = str(current_agent.id)
    token = secrets.token_urlsafe(32)
    
    # Store challenge (expires in 10 minutes)
    pending_challenges[agent_id] = {
        "token": token,
        "expires": datetime.utcnow() + timedelta(minutes=10)
    }
    
    return {
        "agent_id": agent_id,
        "token": token,
        "expires_in_seconds": 600,
        "verification_url": f"{current_agent.endpoint}/.well-known/clawdir-verify?token={token}",
        "instructions": {
            "step1": "Add an endpoint that responds to the verification URL",
            "step2": f"Return JSON: {{\"token\": \"{token}\"}}",
            "step3": "Call POST /v1/verify/confirm within 10 minutes"
        }
    }


@router.post("/confirm")
async def confirm_challenge(
    current_agent: Agent = Depends(get_current_agent),
    db: Session = Depends(get_db)
):
    """
    Confirm ownership by completing the challenge.
    
    ClawDir will call your endpoint to verify the token is served correctly.
    """
    agent_id = str(current_agent.id)
    
    # Check for pending challenge
    challenge = pending_challenges.get(agent_id)
    if not challenge:
        raise HTTPException(
            status_code=400, 
            detail="No pending challenge. Call POST /v1/verify/challenge first."
        )
    
    # Check expiry
    if datetime.utcnow() > challenge["expires"]:
        del pending_challenges[agent_id]
        raise HTTPException(
            status_code=400,
            detail="Challenge expired. Request a new one."
        )
    
    token = challenge["token"]
    verify_url = f"{current_agent.endpoint}/.well-known/clawdir-verify"
    
    # Call the agent's endpoint
    try:
        async with httpx.AsyncClient(timeout=VERIFY_TIMEOUT) as client:
            response = await client.get(verify_url, params={"token": token})
            
            if response.status_code != 200:
                raise HTTPException(
                    status_code=400,
                    detail=f"Endpoint returned {response.status_code}, expected 200"
                )
            
            try:
                data = response.json()
            except:
                raise HTTPException(
                    status_code=400,
                    detail="Endpoint did not return valid JSON"
                )
            
            # Check token matches
            returned_token = data.get("token")
            if returned_token != token:
                raise HTTPException(
                    status_code=400,
                    detail=f"Token mismatch. Expected '{token}', got '{returned_token}'"
                )
            
    except httpx.TimeoutException:
        raise HTTPException(status_code=400, detail="Endpoint timed out")
    except httpx.ConnectError:
        raise HTTPException(status_code=400, detail="Could not connect to endpoint")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Verification failed: {str(e)[:100]}")
    
    # Success! Mark as verified
    del pending_challenges[agent_id]
    
    current_agent.verified_endpoint = True
    current_agent.verified_ownership = True
    current_agent.ownership_verified_at = datetime.utcnow()
    current_agent.last_verification = datetime.utcnow()
    db.commit()
    
    return {
        "agent_id": agent_id,
        "verified": True,
        "verified_at": current_agent.ownership_verified_at.isoformat(),
        "message": "🎉 Endpoint ownership verified! Your agent now has a verified badge."
    }


@router.get("/endpoint/{agent_id}")
async def check_agent_endpoint(
    agent_id: str,
    db: Session = Depends(get_db)
):
    """Check if an agent's endpoint is reachable (public, rate limited)."""
    
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
                "verified": agent.verified_endpoint,
                "cached": True,
                "last_check": agent.last_verification.isoformat(),
                "latency_ms": agent.last_latency_ms
            }
    
    # Fresh check
    result = await check_endpoint_health(agent.endpoint)
    
    # Update cache
    agent.verified_endpoint = result["healthy"]
    agent.last_verification = datetime.utcnow()
    agent.last_latency_ms = result.get("latency_ms")
    db.commit()
    
    return {
        "agent_id": str(agent.id),
        "endpoint": agent.endpoint,
        "verified": result["healthy"],
        "cached": False,
        **result
    }


@router.get("/status/{agent_id}")
def get_verification_status(
    agent_id: str,
    db: Session = Depends(get_db)
):
    """Get cached verification status for an agent."""
    
    agent = db.query(Agent).filter(Agent.id == agent_id).first()
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    
    return {
        "agent_id": str(agent.id),
        "verified_endpoint": agent.verified_endpoint,
        "verified_ownership": agent.verified_ownership,
        "ownership_verified_at": agent.ownership_verified_at.isoformat() if agent.ownership_verified_at else None,
        "verified_email": agent.verified_email,
        "last_verification": agent.last_verification.isoformat() if agent.last_verification else None,
        "last_latency_ms": agent.last_latency_ms,
        "last_seen": agent.last_seen.isoformat() if agent.last_seen else None
    }
