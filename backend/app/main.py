from fastapi import FastAPI, Depends, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
from sqlalchemy import or_, func
from typing import Optional, List
from datetime import datetime
import time
import sentry_sdk
from sentry_sdk.integrations.fastapi import FastApiIntegration
from sentry_sdk.integrations.sqlalchemy import SqlalchemyIntegration

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
from app.models import Base
from app.database import engine, SessionLocal
from app.seed import seed_database
from app.verification import router as verification_router
from app.ratelimit import RateLimitMiddleware

settings = get_settings()

# Initialize Sentry if configured
if settings.sentry_dsn:
    sentry_sdk.init(
        dsn=settings.sentry_dsn,
        integrations=[
            FastApiIntegration(transaction_style="endpoint"),
            SqlalchemyIntegration(),
        ],
        traces_sample_rate=0.1,  # 10% of requests for performance monitoring
        environment="production",
    )

# Run migrations on startup
from alembic.config import Config
from alembic import command
import os

def run_migrations():
    """Run Alembic migrations on startup."""
    try:
        alembic_cfg = Config(os.path.join(os.path.dirname(os.path.dirname(__file__)), "alembic.ini"))
        alembic_cfg.set_main_option("sqlalchemy.url", settings.database_url)
        command.upgrade(alembic_cfg, "head")
    except Exception as e:
        print(f"Migration warning (may be OK on first run): {e}")
        # Fallback: create tables if migrations fail (e.g., fresh DB)
        Base.metadata.create_all(bind=engine)

run_migrations()

# Seed disabled - only real agents now
# db = SessionLocal()
# try:
#     seed_database(db)
# finally:
#     db.close()

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

# Include routers
app.include_router(verification_router)

# Rate limiting (after CORS)
app.add_middleware(RateLimitMiddleware)


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


@app.get("/v1/agents/me", response_model=AgentResponse)
def get_current_agent_info(
    current_agent: Agent = Depends(get_current_agent),
    db: Session = Depends(get_db)
):
    """Get your own agent details (requires API key)."""
    return current_agent


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
    min_trust: float = Query(0.0, description="Minimum trust score"),
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

@app.get("/v1/activity")
def get_activity(
    limit: int = Query(20, ge=1, le=50),
    db: Session = Depends(get_db)
):
    """Get recent activity (registrations and ratings)."""
    
    # Recent agents
    recent_agents = (
        db.query(Agent)
        .order_by(Agent.created_at.desc())
        .limit(limit)
        .all()
    )
    
    # Recent ratings
    recent_ratings = (
        db.query(Rating, Agent.name.label("rater_name"))
        .join(Agent, Rating.rater_id == Agent.id)
        .order_by(Rating.created_at.desc())
        .limit(limit)
        .all()
    )
    
    # Get rated agent names
    rated_ids = [r.Rating.rated_id for r in recent_ratings]
    rated_agents = {str(a.id): a.name for a in db.query(Agent).filter(Agent.id.in_(rated_ids)).all()}
    
    # Combine and sort
    activity = []
    
    for agent in recent_agents:
        activity.append({
            "type": "registration",
            "timestamp": agent.created_at.isoformat() if agent.created_at else None,
            "agent_id": str(agent.id),
            "agent_name": agent.name,
            "description": agent.description
        })
    
    for r in recent_ratings:
        activity.append({
            "type": "rating",
            "timestamp": r.Rating.created_at.isoformat() if r.Rating.created_at else None,
            "rater_name": r.rater_name,
            "rated_id": str(r.Rating.rated_id),
            "rated_name": rated_agents.get(str(r.Rating.rated_id), "Unknown"),
            "score": r.Rating.score,
            "success": r.Rating.success
        })
    
    # Sort by timestamp descending
    activity.sort(key=lambda x: x["timestamp"] or "", reverse=True)
    
    return {"activity": activity[:limit]}


@app.get("/badge/{agent_id}.svg")
def get_agent_badge(agent_id: str, db: Session = Depends(get_db)):
    """Generate SVG badge for agent (for embedding on websites)."""
    from fastapi.responses import Response
    
    agent = db.query(Agent).filter(Agent.id == agent_id).first()
    if not agent:
        # Return a "not found" badge
        svg = '''<svg xmlns="http://www.w3.org/2000/svg" width="120" height="20">
            <rect width="120" height="20" rx="3" fill="#555"/>
            <text x="60" y="14" text-anchor="middle" fill="#fff" font-size="11" font-family="sans-serif">Not Found</text>
        </svg>'''
        return Response(content=svg, media_type="image/svg+xml")
    
    trust = f"{agent.trust_score:.0f}"
    
    # Verified = 30 consecutive days above 80 trust (earned, not paid)
    if getattr(agent, 'is_verified', False):
        # Verified - green with checkmark
        svg = f'''<svg xmlns="http://www.w3.org/2000/svg" width="150" height="20">
            <rect width="70" height="20" rx="3" fill="#555"/>
            <rect x="70" width="80" height="20" rx="3" fill="#10b981"/>
            <text x="35" y="14" text-anchor="middle" fill="#fff" font-size="11" font-family="sans-serif">ClawDir</text>
            <text x="110" y="14" text-anchor="middle" fill="#fff" font-size="11" font-family="sans-serif">✓ Verified {trust}</text>
        </svg>'''
    else:
        # Not verified - gray, shows trust score
        svg = f'''<svg xmlns="http://www.w3.org/2000/svg" width="100" height="20">
            <rect width="100" height="20" rx="3" fill="#6b7280"/>
            <text x="50" y="14" text-anchor="middle" fill="#fff" font-size="11" font-family="sans-serif">ClawDir {trust}</text>
        </svg>'''
    
    return Response(content=svg, media_type="image/svg+xml", headers={"Cache-Control": "max-age=300"})


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


# --- Admin ---

@app.delete("/v1/admin/agents/{agent_id}")
def admin_delete_agent(
    agent_id: str,
    admin_key: str = Query(..., description="Admin key"),
    db: Session = Depends(get_db)
):
    """Delete an agent (admin only)."""
    # Simple admin key check
    if admin_key != settings.secret_key:
        raise HTTPException(status_code=403, detail="Invalid admin key")
    
    agent = db.query(Agent).filter(Agent.id == agent_id).first()
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    
    # Delete capabilities first
    db.query(Capability).filter(Capability.agent_id == agent_id).delete()
    # Delete ratings
    db.query(Rating).filter((Rating.rater_id == agent_id) | (Rating.rated_id == agent_id)).delete()
    # Delete agent
    db.delete(agent)
    db.commit()
    
    return {"status": "deleted", "agent_id": agent_id, "name": agent.name}


# --- Trust Decay (cron job) ---

@app.post("/v1/admin/decay")
def run_trust_decay(
    admin_key: str = Query(..., description="Admin key"),
    db: Session = Depends(get_db)
):
    """
    Run daily trust decay for all agents.
    Call this once per day via cron.
    
    - Trust decays 2% per day without activity
    - Ratings in past 24h counteract decay
    - If trust >= 80, increment days_above_threshold
    - If days_above_threshold >= 30, set is_verified = True
    - If trust drops below 80, reset counter and remove verification
    """
    if admin_key != settings.secret_key:
        raise HTTPException(status_code=403, detail="Invalid admin key")
    
    from datetime import timedelta
    
    now = datetime.utcnow()
    yesterday = now - timedelta(days=1)
    
    agents = db.query(Agent).filter(Agent.is_active == True).all()
    
    results = {"processed": 0, "decayed": 0, "verified": 0, "unverified": 0}
    
    for agent in agents:
        results["processed"] += 1
        
        # Count ratings received in past 24h
        recent_ratings = db.query(Rating).filter(
            Rating.rated_id == agent.id,
            Rating.created_at >= yesterday
        ).count()
        
        # Apply decay if no recent ratings
        if recent_ratings == 0:
            # Decay 0.2 points per day, minimum 0
            agent.trust_score = max(0, agent.trust_score - 0.2)
            results["decayed"] += 1
        
        # Check verification threshold
        if agent.trust_score >= 7:
            agent.days_above_threshold = (agent.days_above_threshold or 0) + 1
            
            # Verify if: hit 30 days OR already earned it before (days >= 30)
            if agent.days_above_threshold >= 30 and not agent.is_verified:
                agent.is_verified = True
                results["verified"] += 1
        else:
            # Below 80 - remove verification but keep the counter
            # Once you've hit 30 days, you only need to go above 80 again to regain badge
            if agent.is_verified:
                agent.is_verified = False
                results["unverified"] += 1
            # Only reset counter if never hit 30 days (still in proving period)
            if (agent.days_above_threshold or 0) < 30:
                agent.days_above_threshold = 0
        
        agent.last_trust_check = now
    
    db.commit()
    
    return {
        "status": "ok",
        "results": results,
        "timestamp": now.isoformat()
    }


# --- Stats ---

@app.get("/v1/stats")
def get_stats(db: Session = Depends(get_db)):
    """Get public stats for the directory."""
    total_agents = db.query(Agent).filter(Agent.is_active == True).count()
    total_ratings = db.query(Rating).count()
    
    return {
        "total_agents": total_agents,
        "total_ratings": total_ratings
    }
# DB persistence test 20260216020938
# force redeploy Mon Feb 16 02:24:01 UTC 2026
