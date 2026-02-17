from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import List
import json, uuid, datetime, base64
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from cryptography.exceptions import InvalidSignature
import jwt

router = APIRouter()

# NOTE: Replace with a real secret management mechanism in production
JWT_SECRET = "REPLACE_WITH_SECURE_SECRET"
JWT_ALGO = "HS256"
TOKEN_EXP_HOURS = 24

class AgentRegister(BaseModel):
    name: str
    host: str
    version: str
    capabilities: List[str]
    public_key_pem: str        # PEM string of Ed25519 public key
    nonce: str
    signature: str               # base64-encoded signature over canonical payload

@router.post("/api/agents/register")
def register_agent(req: AgentRegister):
    # Canonical payload to sign/verify
    payload = {
        "name": req.name,
        "host": req.host,
        "version": req.version,
        "capabilities": req.capabilities,
        "nonce": req.nonce
    }
    # Verify signature against public key
    try:
        public_key = serialization.load_pem_public_key(req.public_key_pem.encode("utf-8"))
        if not isinstance(public_key, Ed25519PublicKey):
            raise ValueError("Unsupported key type")
        message = json.dumps(payload, sort_keys=True).encode("utf-8")
        sig = base64.b64decode(req.signature)
        public_key.verify(sig, message)  # raises InvalidSignature on fail
    except (ValueError, InvalidSignature) as e:
        raise HTTPException(status_code=400, detail=f"Invalid signature or key: {e}")

    # Persist agent (replace with real DB logic)
    agent_id = uuid.uuid4().hex
    registration_ts = datetime.datetime.utcnow().isoformat() + "Z"

    # Issue a short-lived token for future API calls
    expiry = datetime.datetime.utcnow() + datetime.timedelta(hours=TOKEN_EXP_HOURS)
    token_payload = {"agent_id": agent_id, "exp": expiry.timestamp()}
    token = jwt.encode(token_payload, JWT_SECRET, algorithm=JWT_ALGO)

    # NOTE: In production, save agent_id, name, host, public_key_pem, capabilities, version,
    # nonce, and registration_ts to a real DB here. Could add "pending"/"verified" status.

    return {
        "agent_id": agent_id,
        "token": token,
        "registered_at": registration_ts,
        "status": "registered"
    }
