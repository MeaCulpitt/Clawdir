from pydantic import BaseModel, EmailStr, Field
from typing import Optional, List, Dict, Any
from datetime import datetime
from uuid import UUID


# --- Capability Schemas ---

class CapabilityBase(BaseModel):
    category: str = Field(..., description="Category: inference, data, task, domain")
    capability_type: str = Field(..., description="Type: text_generation, web_search, etc.")
    actions: Optional[List[str]] = None
    input_schema: Optional[Dict[str, Any]] = None
    output_schema: Optional[Dict[str, Any]] = None
    pricing: Optional[Dict[str, Any]] = None
    sla: Optional[Dict[str, Any]] = None


class CapabilityCreate(CapabilityBase):
    pass


class CapabilityResponse(CapabilityBase):
    id: UUID
    
    class Config:
        from_attributes = True


# --- Agent Schemas ---

class AgentCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    endpoint: str = Field(..., min_length=1, max_length=500)
    description: Optional[str] = None
    owner_email: Optional[EmailStr] = None
    capabilities: List[CapabilityCreate] = []


class AgentUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=100)
    endpoint: Optional[str] = Field(None, min_length=1, max_length=500)
    description: Optional[str] = None
    is_active: Optional[bool] = None


class AgentResponse(BaseModel):
    id: UUID
    name: str
    endpoint: str
    description: Optional[str]
    trust_score: float
    ratings_received: int
    capabilities: List[CapabilityResponse]
    is_active: bool
    verified_endpoint: bool
    created_at: datetime
    last_seen: Optional[datetime]
    
    class Config:
        from_attributes = True


class AgentCreateResponse(BaseModel):
    id: UUID
    api_key: str  # Only shown once at creation
    name: str
    trust_score: float
    status: str = "active"


class AgentListResponse(BaseModel):
    id: UUID
    name: str
    endpoint: str
    description: Optional[str]
    trust_score: float
    ratings_received: int
    capabilities: List[CapabilityResponse]
    relevance_score: Optional[float] = None
    
    class Config:
        from_attributes = True


# --- Rating Schemas ---

class RatingCreate(BaseModel):
    agent_id: UUID
    score: int = Field(..., ge=1, le=5)
    success: Optional[bool] = None
    latency_ms: Optional[int] = None
    capability_used: Optional[str] = None
    comment: Optional[str] = None
    transaction_id: Optional[str] = None


class RatingResponse(BaseModel):
    id: UUID
    recorded: bool = True
    agent_new_trust: float


class RatingDetail(BaseModel):
    id: UUID
    rater_id: UUID
    rater_name: Optional[str] = None
    rater_trust: Optional[float] = None
    score: int
    success: Optional[bool]
    comment: Optional[str]
    capability_used: Optional[str]
    created_at: datetime
    
    class Config:
        from_attributes = True


# --- Discovery Schemas ---

class DiscoverQuery(BaseModel):
    q: Optional[str] = None  # Natural language query
    capability: Optional[str] = None  # Exact capability type
    category: Optional[str] = None  # Category filter
    min_trust: float = 20.0
    max_price: Optional[float] = None
    limit: int = Field(10, ge=1, le=100)


class DiscoverResponse(BaseModel):
    agents: List[AgentListResponse]
    total: int
    query_ms: int
