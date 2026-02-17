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
    trust_tier: str = "none"  # none, bronze, silver, gold
    ratings_received: int
    capabilities: List[CapabilityResponse]
    is_active: bool
    verified_endpoint: bool
    is_verified: bool
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
    trust_tier: str = "none"
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
    q: Optional[str] = None
    capability: Optional[str] = None
    category: Optional[str] = None
    min_trust: float = 0.0
    max_price: Optional[float] = None
    limit: int = Field(10, ge=1, le=100)


class DiscoverResponse(BaseModel):
    agents: List[AgentListResponse]
    total: int
    query_ms: int


# --- Pagination ---

class PaginatedResponse(BaseModel):
    items: List[Any]
    next_cursor: Optional[str] = None
    prev_cursor: Optional[str] = None
    has_more: bool
    total: int


# --- Follow Schemas ---

class FollowResponse(BaseModel):
    agent_id: str
    name: str
    trust_score: float
    trust_tier: str = "none"


class FollowingResponse(BaseModel):
    following: List[FollowResponse]
    total: int


class FollowersResponse(BaseModel):
    followers: List[FollowResponse]
    total: int


# --- Category Schemas ---

class CategoryCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    description: Optional[str] = None


class CategoryResponse(BaseModel):
    id: int
    name: str
    description: Optional[str]
    created_at: datetime
    
    class Config:
        from_attributes = True


class AgentCategoryResponse(BaseModel):
    categories: List[CategoryResponse]


# --- Health Schemas ---

class HealthResponse(BaseModel):
    agent_id: str
    status: str  # healthy, degraded, down
    last_seen: Optional[datetime]
    last_health_check: Optional[datetime]
    latency_ms: Optional[float]
    uptime_percent: float = 100.0


# --- Recommendation Schemas ---

class RecommendationResponse(BaseModel):
    agents: List[AgentListResponse]
    total: int


class SimilarAgentsResponse(BaseModel):
    agent_id: str
    similar: List[AgentListResponse]
    total: int
```

---
