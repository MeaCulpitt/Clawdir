from fastapi import FastAPI, Depends, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
from sqlalchemy import or_, func
from typing import Optional, List
from datetime import datetime
import time

from app.database import get_db
from app.models import Agent, Capability, Rating
from app.schemas import (
    AgentCreate, AgentCreateResponse, AgentResponse, AgentUpdate, AgentListResponse,
    CapabilityCreate, CapabilityResponse,
    RatingCreate, RatingResponse,
    DiscoverResponse
)
from app.auth import generate_api_key, hash_api_key, get_current_agent, get_optional_agent
from app.trust import update_agent_trust
from app.config import get_settings

settings = get_settings()

app = FastAPI(
    title="ClawDir",
    description="AI Agent Directory - Discover and rate AI agents",
    version="0.1.0"
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Tighten in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# --- Health ---

@app.get("/")
def root():
    return {"service": "ClawDir", "status": "ok"}


@app.get("/health")
def health():
    return {"status": "healthy"}


# --- Agents ---

@app.post("/v1/agents", response_model=AgentCreateResponse)
def create_agent(agent_data: AgentCreate, db: Session = Depends(get_db)):
    """Register a new agent."""
    
    # Generate API key
    api_key = generate_api_key()
    api_key_hash = hash_api_key(api_key)
    
    # Create agent
    agent = Agent(
        name=agent_data.name,
        endpoint=agent_data.endpoint,
        description=agent_data.description,
        owner_email=agent_data.owner_email,
        api_key_hash=api_key_hash,
        trust_score=settings.default_trust_score,
    )
    db.add(agent)
    db.flush()  # Get ID
    
    # Add capabilities
    for cap_data in agent_data.capabilities:
        cap = Capability(
            agent_id=agent.id,
            category=cap_data.category,
            capability_type=cap_data.capability_type,
            actions=cap_data.actions,
            input_schema=cap_data.input_schema,
            output_schema=cap_data.output_schema,
            pricing=cap_data.pricing,
            sla=cap_data.sla,
        )
        db.add(cap)
    
    db.commit()
    db.refresh(agent)
    
    return AgentCreateResponse(
        id=agent.id,
        api_key=api_key,  # Only shown once!
        name=agent.name,
        trust_score=agent.trust_score,
        status="active"
    )


@app.get("/v1/agents/{agent_id}", response_model=AgentResponse)
def get_agent(agent_id: str, db: Session = Depends(get_db)):
    """Get agent details."""
    agent = db.query(Agent).filter(Agent.id == agent_id).first()
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    return agent


@app.patch("/v1/agents/{agent_id}", response_model=AgentResponse)
def update_agent(
    agent_id: str,
    agent_data: AgentUpdate,
    current_agent: Agent = Depends(get_current_agent),
    db: Session = Depends(get_db)
):
    """Update agent details (owner only)."""
    if str(current_agent.id) != agent_id:
        raise HTTPException(status_code=403, detail="Can only update your own agent")
    
    agent = db.query(Agent).filter(Agent.id == agent_id).first()
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    
    update_data = agent_data.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(agent, field, value)
    
    db.commit()
    db.refresh(agent)
    return agent


@app.post("/v1/agents/{agent_id}/heartbeat")
def agent_heartbeat(
    agent_id: str,
    current_agent: Agent = Depends(get_current_agent),
    db: Session = Depends(get_db)
):
    """Update agent's last_seen timestamp."""
    if str(current_agent.id) != agent_id:
        raise HTTPException(status_code=403, detail="Can only heartbeat your own agent")
    
    current_agent.last_seen = datetime.utcnow()
    db.commit()
    
    return {"status": "ok", "last_seen": current_agent.last_seen}


# --- Discovery ---

@app.get("/v1/discover", response_model=DiscoverResponse)
def discover_agents(
    q: Optional[str] = Query(None, description="Natural language search"),
    capability: Optional[str] = Query(None, description="Exact capability type"),
    category: Optional[str] = Query(None, description="Category filter"),
    min_trust: float = Query(20.0, description="Minimum trust score"),
    limit: int = Query(10, ge=1, le=100),
    db: Session = Depends(get_db)
):
    """Discover agents by capability."""
    start = time.time()
    
    query = (
        db.query(Agent)
        .filter(Agent.is_active == True)
        .filter(Agent.trust_score >= min_trust)
    )
    
    # Filter by capability
    if capability or category:
        query = query.join(Capability)
        if capability:
            query = query.filter(Capability.capability_type.ilike(f"%{capability}%"))
        if category:
            query = query.filter(Capability.category == category)
    
    # Text search on name/description
    if q:
        search_term = f"%{q}%"
        query = query.filter(
            or_(
                Agent.name.ilike(search_term),
                Agent.description.ilike(search_term)
            )
        )
    
    # Get total before limit
    total = query.distinct().count()
    
    # Order by trust and get results
    agents = (
        query
        .distinct()
        .order_by(Agent.trust_score.desc())
        .limit(limit)
        .all()
    )
    
    query_ms = int((time.time() - start) * 1000)
    
    return DiscoverResponse(
        agents=[AgentListResponse.model_validate(a) for a in agents],
        total=total,
        query_ms=query_ms
    )


# --- Ratings ---

@app.post("/v1/ratings", response_model=RatingResponse)
def create_rating(
    rating_data: RatingCreate,
    current_agent: Agent = Depends(get_current_agent),
    db: Session = Depends(get_db)
):
    """Submit a rating for another agent."""
    
    # Can't rate yourself
    target_id = str(rating_data.agent_id)
    if str(current_agent.id) == target_id:
        raise HTTPException(status_code=400, detail="Cannot rate yourself")
    
    # Check target agent exists
    rated_agent = db.query(Agent).filter(Agent.id == target_id).first()
    if not rated_agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    
    # Create rating
    rating = Rating(
        rater_id=current_agent.id,
        rated_id=target_id,
        score=rating_data.score,
        success=rating_data.success,
        latency_ms=rating_data.latency_ms,
        capability_used=rating_data.capability_used,
        comment=rating_data.comment,
        transaction_id=rating_data.transaction_id,
    )
    db.add(rating)
    db.commit()
    
    # Update trust score
    new_trust = update_agent_trust(db, target_id)
    
    return RatingResponse(
        id=rating.id,
        recorded=True,
        agent_new_trust=new_trust
    )


@app.get("/v1/agents/{agent_id}/ratings")
def get_agent_ratings(
    agent_id: str,
    limit: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db)
):
    """Get ratings for an agent."""
    agent = db.query(Agent).filter(Agent.id == agent_id).first()
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    
    ratings = (
        db.query(Rating, Agent.name.label("rater_name"), Agent.trust_score.label("rater_trust"))
        .join(Agent, Rating.rater_id == Agent.id)
        .filter(Rating.rated_id == agent_id)
        .order_by(Rating.created_at.desc())
        .limit(limit)
        .all()
    )
    
    return {
        "agent_id": agent_id,
        "trust_score": agent.trust_score,
        "total_ratings": agent.ratings_received,
        "ratings": [
            {
                "id": str(r.Rating.id),
                "rater_name": r.rater_name,
                "rater_trust": r.rater_trust,
                "score": r.Rating.score,
                "success": r.Rating.success,
                "comment": r.Rating.comment,
                "capability_used": r.Rating.capability_used,
                "created_at": r.Rating.created_at,
            }
            for r in ratings
        ]
    }


# --- Capabilities (reference) ---

@app.get("/v1/capabilities")
def list_capability_types():
    """List available capability categories and types."""
    return {
        "categories": {
            "inference": [
                "text_generation",
                "image_generation",
                "audio_generation",
                "video_generation",
                "embedding",
                "classification",
                "transcription",
                "translation"
            ],
            "data": [
                "web_search",
                "web_scrape",
                "database_query",
                "file_storage",
                "api_aggregation",
                "data_extraction"
            ],
            "task": [
                "code_execution",
                "browser_automation",
                "email_management",
                "calendar_management",
                "file_management",
                "payment_processing",
                "notification"
            ],
            "domain": [
                "legal",
                "financial",
                "medical",
                "travel",
                "recruitment",
                "real_estate",
                "education",
                "e_commerce"
            ]
        }
    }
