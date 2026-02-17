from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel
from typing import List, Optional, Dict
import json, uuid, datetime, base64, hashlib
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from cryptography.exceptions import InvalidSignature
import jwt

router = APIRouter()

# NOTE: Replace with real secret management in production
JWT_SECRET = "REPLACE_WITH_SECURE_SECRET"
JWT_ALGO = "HS256"
TOKEN_EXP_HOURS = 24

# VERIFICATION & SYBIL PROTECTION
VERIFICATION_REQUIRED = True
STATUS_PENDING = "PENDING"
STATUS_VERIFIED = "VERIFIED"
STATUS_REJECTED = "REJECTED"

# Anti-sybil: cooldown between registrations from the same IP (seconds)
IP_COOLDOWN_SECONDS = 3600  # 1 hour

# In production, replace these with real DB lookups
_registered_keys: Dict[str, dict] = {}      # public_key_hash -> agent record
_ip_last_registered: Dict[str, float] = {}  # ip -> last registration timestamp


def _hash_public_key(pem: str) -> str:
    """Hash the public key PEM to create a unique fingerprint."""
    return hashlib.sha256(pem.strip().encode("utf-8")).hexdigest()


class AgentRegister(BaseModel):
    name: str
    host: str
    version: str
    capabilities: List[str]
    public_key_pem: str
    nonce: str
    signature: str
    organization: Optional[str] = None
    contact_email: Optional[str] = None


@router.post("/api/agents/register")
def register_agent(req: AgentRegister, request: Request):
    # --- SYBIL CHECK 1: Duplicate public key ---
    key_hash = _hash_public_key(req.public_key_pem)
    if key_hash in _registered_keys:
        existing = _registered_keys[key_hash]
        raise HTTPException(
            status_code=409,
            detail=f"This public key is already registered as agent {existing['agent_id']} "
                   f"(status: {existing['status']}). One key = one agent."
        )

    # --- SYBIL CHECK 2: IP cooldown ---
    client_ip = request.client.host if request.client else "unknown"
    now = datetime.datetime.utcnow().timestamp()
    last_reg = _ip_last_registered.get(client_ip, 0)
    if now - last_reg < IP_COOLDOWN_SECONDS:
        remaining = int(IP_COOLDOWN_SECONDS - (now - last_reg))
        raise HTTPException(
            status_code=429,
            detail=f"Too many registrations from this IP. Try again in {remaining} seconds."
        )

    # --- SIGNATURE VERIFICATION ---
    payload = {
        "name": req.name,
        "host": req.host,
        "version": req.version,
        "capabilities": req.capabilities,
        "nonce": req.nonce
    }
    try:
        public_key = serialization.load_pem_public_key(req.public_key_pem.encode("utf-8"))
        if not isinstance(public_key, Ed25519PublicKey):
            raise ValueError("Unsupported key type")
        message = json.dumps(payload, sort_keys=True).encode("utf-8")
        sig = base64.b64decode(req.signature)
        public_key.verify(sig, message)
    except (ValueError, InvalidSignature) as e:
        raise HTTPException(status_code=400, detail=f"Invalid signature or key: {e}")

    # --- REGISTER AGENT ---
    agent_id = uuid.uuid4().hex
    registration_ts = datetime.datetime.utcnow().isoformat() + "Z"

    if VERIFICATION_REQUIRED:
        status = STATUS_PENDING
        token = None
    else:
        status = STATUS_VERIFIED
        expiry = datetime.datetime.utcnow() + datetime.timedelta(hours=TOKEN_EXP_HOURS)
        token = jwt.encode({"agent_id": agent_id, "exp": expiry.timestamp()}, JWT_SECRET, algorithm=JWT_ALGO)

    # Store agent record (replace with real DB in production)
    record = {
        "agent_id": agent_id,
        "name": req.name,
        "host": req.host,
        "version": req.version,
        "capabilities": req.capabilities,
        "public_key_hash": key_hash,
        "organization": req.organization,
        "contact_email": req.contact_email,
        "status": status,
        "registered_at": registration_ts,
        "registered_ip": client_ip,
    }
    _registered_keys[key_hash] = record
    _ip_last_registered[client_ip] = now

    return {
        "agent_id": agent_id,
        "token": token,
        "registered_at": registration_ts,
        "status": status,
        "message": "Registration received. Admin verification required before token is issued."
            if VERIFICATION_REQUIRED else "Registered and verified."
    }
