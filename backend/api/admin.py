from fastapi import APIRouter, HTTPException, Header
from pydantic import BaseModel
from typing import Optional
import datetime, jwt

router = APIRouter()

STATUS_VERIFIED = "VERIFIED"
STATUS_PENDING = "PENDING"
STATUS_REJECTED = "REJECTED"

# NOTE: Replace with real secret management in production
ADMIN_TOKEN = "REPLACE_WITH_SECURE_ADMIN_TOKEN"
JWT_SECRET = "REPLACE_WITH_SECURE_SECRET"
JWT_ALGO = "HS256"
TOKEN_EXP_HOURS = 24


class AdminAction(BaseModel):
    action: str  # "approve" or "reject"
    notes: Optional[str] = None


@router.post("/api/agents/{agent_id}/verify")
def verify_agent(agent_id: str, body: AdminAction, x_admin_token: str = Header(..., alias="X-ADMIN-TOKEN")):
    if x_admin_token != ADMIN_TOKEN:
        raise HTTPException(status_code=403, detail="Admin authentication required")

    if body.action not in ("approve", "reject"):
        raise HTTPException(status_code=400, detail="Action must be 'approve' or 'reject'")

    # In production: look up agent_id in DB and update status
    # For MVP, import the in-memory store from agents module
    from .agents import _registered_keys

    # Find agent by agent_id
    agent_record = None
    for key_hash, record in _registered_keys.items():
        if record["agent_id"] == agent_id:
            agent_record = record
            break

    if not agent_record:
        raise HTTPException(status_code=404, detail="Agent not found")

    if agent_record["status"] != STATUS_PENDING:
        raise HTTPException(status_code=400, detail=f"Agent is already {agent_record['status']}")

    now = datetime.datetime.utcnow().isoformat() + "Z"
    token = None

    if body.action == "approve":
        agent_record["status"] = STATUS_VERIFIED
        agent_record["verified_at"] = now
        agent_record["verified_by"] = "admin"
        # Issue token now that agent is verified
        expiry = datetime.datetime.utcnow() + datetime.timedelta(hours=TOKEN_EXP_HOURS)
        token = jwt.encode({"agent_id": agent_id, "exp": expiry.timestamp()}, JWT_SECRET, algorithm=JWT_ALGO)
    else:
        agent_record["status"] = STATUS_REJECTED
        agent_record["rejected_at"] = now
        agent_record["rejected_by"] = "admin"

    return {
        "agent_id": agent_id,
        "status": agent_record["status"],
        "token": token,
        "notes": body.notes
    }


@router.get("/api/agents/pending")
def list_pending(x_admin_token: str = Header(..., alias="X-ADMIN-TOKEN")):
    if x_admin_token != ADMIN_TOKEN:
        raise HTTPException(status_code=403, detail="Admin authentication required")

    from .agents import _registered_keys
    pending = [r for r in _registered_keys.values() if r["status"] == STATUS_PENDING]
    return {"count": len(pending), "agents": pending}
