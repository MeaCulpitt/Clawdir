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
    DiscoverResponse,
    PaginatedResponse, FollowResponse, FollowingResponse, FollowersResponse,
    CategoryCreate, CategoryResponse, AgentCategoryResponse,
    HealthResponse, RecommendationResponse, SimilarAgentsResponse
)
from app.auth import generate_api_key, hash_api_key, get_current_agent, get_optional_agent
from app.trust import update_agent_trust, update_verification_tiers
from app.config import get_settings
from app.models import Base, Follow, Category, AgentCategory
from app.database import engine, SessionLocal
from app.seed import seed_database
from app.verification import router as verification_router
from app.ratelimit import RateLimitMiddleware
from contextlib import asynccontextmanager
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

settings = get_settings()

# Initialize Sentry if configured
if settings.sentry_dsn:
    sentry_sdk.init(
        dsn=settings.sentry_dsn,
        integrations=[
            FastApiIntegration(transaction_style="endpoint"),
            SqlalchemyIntegration(),
        ],
        traces_sample_rate=0.1,
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
    
    print("Ensuring tables exist via create_all...")
    Base.metadata.create_all(bind=engine)
    print("create_all complete")

run_migrations()


# --- Background Trust Decay ---

def run_daily_trust_decay():
    """Background job: run trust decay and verification tiers daily at midnight UTC."""
    from datetime import timedelta
    
    db = SessionLocal()
    try:
        now = datetime.utcnow()
        yesterday = now - timedelta(days=1)
        
        agents = db.query(Agent).filter(Agent.is_active == True).all()
        decayed = 0
        
        for agent in agents:
            recent_ratings = db.query(Rating).filter(
                Rating.rated_id == agent.id,
                Rating.created_at >= yesterday
            ).count()
            
            if recent_ratings == 0:
                agent.trust_score = max(0, agent.trust_score - 0.2)
                decayed += 1
            
            agent.last_trust_check = now
        
        db.commit()
        print(f"[Trust Decay] {len(agents)} agents processed, {decayed} decayed")
        
        # Update verification tiers
        update_verification_tiers(db)
        print("[Trust Decay] Verification tiers updated")
        
    except Exception as e:
        print(f"[Trust Decay] Error: {e}")
        db.rollback()
    finally:
        db.close()


scheduler = BackgroundScheduler()
scheduler.add_job(
    run_daily_trust_decay,
    trigger=CronTrigger(hour=0, minute=0, timezone="UTC"),
    id="trust_decay",
    name="Daily Trust Decay",
    replace_existing=True,
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    scheduler.start()
    print("[Scheduler] Started - trust decay runs daily at 00:00 UTC")
    yield
    scheduler.shutdown()
    print("[Scheduler] Stopped")


app = FastAPI(
    title="ClawDir",
    description="AI Agent Directory - Discover and rate AI agents",
    version="0.1.0",
    lifespan=lifespan,
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
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


@app.post("/v1/admin/reset-db")
def reset_database(admin_key: str = Query(...)):
    """Drop all tables and recreate. DESTRUCTIVE."""
    if admin_key != settings.secret_key:
        raise HTTPException(status_code=403, detail="Invalid admin key")
    
    try:
        Base.metadata.drop_all(bind=engine)
        Base.metadata.create_all(bind=engine)
        
        from sqlalchemy import inspect
        inspector = inspect(engine)
        tables = inspector.get_table_names()
        cols = [c["name"] for c in inspector.get_columns("agents")]
        
        return {"status": "ok", "message": "Database reset", "tables": tables, "agent_columns": cols}
    except Exception as e:
        import traceback
        return {"status": "error", "message": str(e), "traceback": traceback.format_exc()}


@app.post("/v1/admin/init-db")
def init_database(admin_key: str = Query(...)):
    """Manually initialize database tables."""
    if admin_key != settings.secret_key:
        raise HTTPException(status_code=403, detail="Invalid admin key")
    
    try:
        from sqlalchemy import inspect
        inspector = inspect(engine)
        before = inspector.get_table_names()
        
        Base.metadata.create_all(bind=engine)
        
        inspector = inspect(engine)
        after = inspector.get_table_names()
        
        cols = inspector.get_columns("agents")
        col_names = [c["name"] for c in cols]
        
        return {"status": "ok", "tables_before": before, "tables_after": after, "models": list(Base.metadata.tables.keys()), "agent_columns": col_names}
    except Exception as e:
        import traceback
        return {"status": "error", "message": str(e), "traceback": traceback.format_exc()}


@app.get("/health")
def health(db: Session = Depends(get_db)):
    """Health check with DB debug info."""
    import os
    from sqlalchemy import text
    
    db_url = settings.database_url
    db_type = "postgresql" if "postgresql" in db_url else "sqlite"
    
    try:
        result = db.execute(text("SELECT 1"))
        db_ok = True
        db_error = None
    except Exception as e:
        db_ok = False
        db_error = str(e)[:200]
    
    try:
        version_result = db.execute(text("SELECT version_num FROM alembic_version"))
        alembic_version = version_result.scalar()
    except:
        alembic_version = "none"
    
    try:
        tables_result = db.execute(text("SELECT table_name FROM information_schema.tables WHERE table_schema = 'public'"))
        tables = [row[0] for row in tables_result.fetchall()]
    except:
        tables = []
    
    try:
        cols_result = db.execute(text("SELECT column_name FROM information_schema.columns WHERE table_name = 'agents'"))
        agent_cols = [row[0] for row in cols_result.fetchall()]
    except:
        agent_cols = []
    
    return {
        "status": "healthy" if db_ok else "unhealthy",
        "database": db_type,
        "db_connected": db_ok,
        "db_error": db_error,
        "alembic_version": alembic_version,
        "env_url_set": os.environ.get("DATABASE_URL") is not None,
        "tables": tables,
        "agent_columns": agent_cols
    }


# --- Agents ---

@app.post("/v1/agents", response_model=AgentCreateResponse)
def create_agent(agent_data: AgentCreate, db: Session = Depends(get_db)):
    """Register a new agent."""
    
    api_key = generate_api_key()
    api_key_hash = hash_api_key(api_key)
    
    agent = Agent(
        name=agent_data.name,
        endpoint=agent_data.endpoint,
        description=agent_data.description,
        owner_email=agent_data.owner_email,
        api_key_hash=api_key_hash,
        trust_score=settings.default_trust_score,
    )
    db.add(agent)
    db.flush()
    
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
        api_key=api_key,
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
    
    if capability or category:
        query = query.join(Capability)
        if capability:
            query = query.filter(Capability.capability_type.ilike(f"%{capability}%"))
        if category:
            query = query.filter(Capability.category == category)
    
    if q:
        search_term = f"%{q}%"
        query = query.filter(
            or_(
                Agent.name.ilike(search_term),
                Agent.description.ilike(search_term)
            )
        )
    
    total = query.distinct().count()
    
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


# === PAGINATION ENDPOINT ===

@app.get("/v1/agents", response_model=PaginatedResponse)
def list_agents(
    cursor: Optional[str] = Query(None),
    limit: int = Query(20, ge=1, le=100),
    sort_by: str = Query("trust_score", regex="^(trust_score|created_at)$"),
    db: Session = Depends(get_db)
):
    """List agents with cursor-based pagination."""
    import base64
    
    total = db.query(Agent).filter(Agent.is_active == True).count()
    query = db.query(Agent).filter(Agent.is_active == True)
    
    if cursor:
        try:
            cursor_id = base64.b64decode(cursor).decode()
            if sort_by == "trust_score":
                score, uid = cursor_id.split(":")
                query = query.filter(
                    (Agent.trust_score < float(score)) | 
                    ((Agent.trust_score == float(score)) & (Agent.id < uid))
                )
            else:
                query = query.filter(Agent.id < cursor_id)
        except:
            pass
    
    agents = query.order_by(
        Agent.trust_score.desc(), Agent.id.desc()
    ).limit(limit + 1).all()
    
    has_more = len(agents) > limit
    if has_more:
        agents = agents[:limit]
    
    next_cursor = None
    if has_more and agents:
        last = agents[-1]
        cursor_str = f"{last.trust_score}:{last.id}"
        next_cursor = base64.b64encode(cursor_str.encode()).decode()
    
    return PaginatedResponse(
        items=[AgentListResponse.model_validate(a) for a in agents],
        next_cursor=next_cursor,
        has_more=has_more,
        total=total
    )


# === FOLLOW ENDPOINTS ===

@app.post("/v1/agents/{agent_id}/follow")
def follow_agent(
    agent_id: str,
    current_agent: Agent = Depends(get_current_agent),
    db: Session = Depends(get_db)
):
    """Follow an agent."""
    if str(current_agent.id) == agent_id:
        raise HTTPException(status_code=400, detail="Cannot follow yourself")
    
    target = db.query(Agent).filter(Agent.id == agent_id).first()
    if not target:
        raise HTTPException(status_code=404, detail="Agent not found")
    
    existing = db.query(Follow).filter(
        Follow.follower_id == str(current_agent.id),
        Follow.following_id == agent_id
    ).first()
    
    if existing:
        return {"status": "already_following", "agent_id": agent_id}
    
    follow = Follow(follower_id=str(current_agent.id), following_id=agent_id)
    db.add(follow)
    db.commit()
    
    return {"status": "following", "agent_id": agent_id}


@app.delete("/v1/agents/{agent_id}/follow")
def unfollow_agent(
    agent_id: str,
    current_agent: Agent = Depends(get_current_agent),
    db: Session = Depends(get_db)
):
    """Unfollow an agent."""
    db.query(Follow).filter(
        Follow.follower_id == str(current_agent.id),
        Follow.following_id == agent_id
    ).delete()
    db.commit()
    return {"status": "unfollowed", "agent_id": agent_id}


@app.get("/v1/agents/{agent_id}/followers", response_model=FollowersResponse)
def get_followers(
    agent_id: str,
    limit: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db)
):
    follows = db.query(Follow, Agent).join(
        Agent, Follow.follower_id == Agent.id
    ).filter(Follow.following_id == agent_id).limit(limit).all()
    
    followers = [
        FollowResponse(
            agent_id=str(f.Agent.id),
            name=f.Agent.name,
            trust_score=f.Agent.trust_score,
            trust_tier=f.Agent.trust_tier or "none"
        ) for f in follows
    ]
    
    return FollowersResponse(followers=followers, total=len(followers))


@app.get("/v1/agents/{agent_id}/following", response_model=FollowingResponse)
def get_following(
    agent_id: str,
    limit: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db)
):
    follows = db.query(Follow, Agent).join(
        Agent, Follow.following_id == Agent.id
    ).filter(Follow.follower_id == agent_id).limit(limit).all()
    
    following = [
        FollowResponse(
            agent_id=str(f.Agent.id),
            name=f.Agent.name,
            trust_score=f.Agent.trust_score,
            trust_tier=f.Agent.trust_tier or "none"
        ) for f in follows
    ]
    
    return FollowingResponse(following=following, total=len(following))


# === CATEGORY ENDPOINTS ===

@app.post("/v1/categories", response_model=CategoryResponse)
def create_category(
    category_data: CategoryCreate,
    current_agent: Agent = Depends(get_current_agent),
    db: Session = Depends(get_db)
):
    """Create a category."""
    existing = db.query(Category).filter(Category.name == category_data.name).first()
    if existing:
        raise HTTPException(status_code=400, detail="Category already exists")
    
    category = Category(
        name=category_data.name,
        description=category_data.description,
        created_by=str(current_agent.id)
    )
    db.add(category)
    db.commit()
    db.refresh(category)
    
    return category


@app.get("/v1/categories", response_model=List[CategoryResponse])
def list_categories(db: Session = Depends(get_db)):
    """List all categories."""
    return db.query(Category).order_by(Category.name).all()


@app.post("/v1/agents/{agent_id}/categories/{category_id}")
def add_agent_to_category(
    agent_id: str,
    category_id: int,
    current_agent: Agent = Depends(get_current_agent),
    db: Session = Depends(get_db)
):
    """Add agent to category."""
    if str(current_agent.id) != agent_id:
        raise HTTPException(status_code=403, detail="Can only modify your own agent")
    
    category = db.query(Category).filter(Category.id == category_id).first()
    if not category:
        raise HTTPException(status_code=404, detail="Category not found")
    
    rel = AgentCategory(agent_id=agent_id, category_id=category_id)
    db.merge(rel)
    db.commit()
    
    return {"status": "added", "category": category.name}


@app.get("/v1/categories/{category_id}/agents", response_model=List[AgentListResponse])
def get_category_agents(
    category_id: int,
    limit: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db)
):
    agents = db.query(Agent).join(AgentCategory).filter(
        AgentCategory.category_id == category_id,
        Agent.is_active == True
    ).order_by(Agent.trust_score.desc()).limit(limit).all()
    
    return [AgentListResponse.model_validate(a) for a in agents]


# === HEALTH CHECK ENDPOINT ===

@app.post("/v1/agents/{agent_id}/check-health")
async def check_agent_health(
    agent_id: str,
    current_agent: Agent = Depends(get_current_agent),
    db: Session = Depends(get_db)
):
    """Manually trigger health check for an agent."""
    import httpx
    
    target = db.query(Agent).filter(Agent.id == agent_id).first()
    if not target:
        raise HTTPException(status_code=404)
    
    start = time.time()
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(f"{target.endpoint}/health")
            latency_ms = (time.time() - start) * 1000
            status = "healthy" if response.status_code < 500 else "degraded"
    except httpx.TimeoutException:
        status = "down"
        latency_ms = None
    except Exception:
        status = "degraded"
        latency_ms = (time.time() - start) * 1000 if 'start' in locals() else None
    
    target.last_health_check = datetime.utcnow()
    target.last_latency_ms = int(latency_ms) if latency_ms else None
    db.commit()
    
    return {"status": status, "latency_ms": latency_ms}


@app.get("/v1/agents/{agent_id}/health", response_model=HealthResponse)
def get_agent_health(agent_id: str, db: Session = Depends(get_db)):
    """Get agent health metrics."""
    agent = db.query(Agent).filter(Agent.id == agent_id).first()
    if not agent:
        raise HTTPException(status_code=404)
    
    uptime = 100.0
    if agent.last_seen:
        time_since_seen = (datetime.utcnow() - agent.last_seen).total_seconds()
        if time_since_seen > 300:
            uptime = max(0, 100 - (time_since_seen / 60))
    
    return HealthResponse(
        agent_id=agent_id,
        status="healthy",
        last_seen=agent.last_seen,
        last_health_check=agent.last_health_check,
        latency_ms=agent.last_latency_ms,
        uptime_percent=uptime
    )


# === RECOMMENDATION ENDPOINTS ===

@app.get("/v1/recommendations", response_model=RecommendationResponse)
def get_recommendations(
    current_agent: Agent = Depends(get_current_agent),
    limit: int = Query(10, ge=1, le=50),
    db: Session = Depends(get_db)
):
    """Get agent recommendations based on what you rated highly."""
    highly_rated = db.query(Rating).filter(
        Rating.rater_id == current_agent.id,
        Rating.score >= 4
    ).all()
    
    if not highly_rated:
        agents = db.query(Agent).filter(
            Agent.is_active == True,
            Agent.id != str(current_agent.id)
        ).order_by(Agent.trust_score.desc()).limit(limit).all()
    else:
        rated_ids = [r.rated_id for r in highly_rated]
        caps = db.query(Capability).filter(
            Capability.agent_id.in_(rated_ids)
        ).all()
        
        cap_types = set(c.capability_type for c in caps)
        
        agents = db.query(Agent).join(Capability).filter(
            Agent.is_active == True,
            Agent.id != str(current_agent.id),
            Capability.capability_type.in_(cap_types)
        ).distinct().order_by(Agent.trust_score.desc()).limit(limit).all()
    
    return RecommendationResponse(
        agents=[AgentListResponse.model_validate(a) for a in agents],
        total=len(agents)
    )


@app.get("/v1/agents/{agent_id}/similar", response_model=SimilarAgentsResponse)
def get_similar_agents(
    agent_id: str,
    limit: int = Query(10, ge=1, le=50),
    db: Session = Depends(get_db)
):
    """Find agents similar to a given agent."""
    agent = db.query(Agent).filter(Agent.id == agent_id).first()
    if not agent:
        raise HTTPException(status_code=404)
    
    caps = db.query(Capability).filter(Capability.agent_id == agent_id).all()
    cap_types = [c.capability_type for c in caps]
    
    similar = db.query(Agent).join(Capability).filter(
        Agent.is_active == True,
        Agent.id != agent_id,
        Capability.capability_type.in_(cap_types)
    ).distinct().order_by(Agent.trust_score.desc()).limit(limit).all()
    
    return SimilarAgentsResponse(
        agent_id=agent_id,
        similar=[AgentListResponse.model_validate(a) for a in similar],
        total=len(similar)
    )


# --- Ratings ---

@app.post("/v1/ratings", response_model=RatingResponse)
def create_rating(
    rating_data: RatingCreate,
    current_agent: Agent = Depends(get_current_agent),
    db: Session = Depends(get_db)
):
    """Submit a rating for another agent."""
    
    target_id = str(rating_data.agent_id)
    if str(current_agent.id) == target_id:
        raise HTTPException(status_code=400, detail="Cannot rate yourself")
    
    rated_agent = db.query(Agent).filter(Agent.id == target_id).first()
    if not rated_agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    
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
    
    recent_agents = (
        db.query(Agent)
        .order_by(Agent.created_at.desc())
        .limit(limit)
        .all()
    )
    
    recent_ratings = (
        db.query(Rating, Agent.name.label("rater_name"))
        .join(Agent, Rating.rater_id == Agent.id)
        .order_by(Rating.created_at.desc())
        .limit(limit)
        .all()
    )
    
    rated_ids = [r.Rating.rated_id for r in recent_ratings]
    rated_agents = {str(a.id): a.name for a in db.query(Agent).filter(Agent.id.in_(rated_ids)).all()}
    
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
    
    activity.sort(key=lambda x: x["timestamp"] or "", reverse=True)
    
    return {"activity": activity[:limit]}


@app.get("/badge/{agent_id}.svg")
def get_agent_badge(agent_id: str, db: Session = Depends(get_db)):
    """Generate SVG badge for agent."""
    from fastapi.responses import Response
    
    agent = db.query(Agent).filter(Agent.id == agent_id).first()
    if not agent:
        svg = '''<svg xmlns="http://www.w3.org/2000/svg" width="120" height="20">
            <rect width="120" height="20" rx="3" fill="#555"/>
            <text x="60" y="14" text-anchor="middle" fill="#fff" font-size="11" font-family="sans-serif">Not Found</text>
        </svg>'''
        return Response(content=svg, media_type="image/svg+xml")
    
    trust = f"{agent.trust_score:.0f}"
    tier = getattr(agent, 'trust_tier', 'none') or 'none'
    
    # Tier colors
    tier_colors = {
        "bronze": "#cd7f32",
        "silver": "#c0c0c0",
        "gold": "#ffd700",
        "none": "#6b7280"
    }
    color = tier_colors.get(tier, "#6b7280")
    
    if tier != "none":
        svg = f'''<svg xmlns="http://www.w3.org/2000/svg" width="150" height="20">
            <rect width="70" height="20" rx="3" fill="#555"/>
            <rect x="70" width="80" height="20" rx="3" fill="{color}"/>
            <text x="35" y="14" text-anchor="middle" fill="#fff" font-size="11" font-family="sans-serif">ClawDir</text>
            <text x="110" y="14" text-anchor="middle" fill="#000" font-size="10" font-family="sans-serif" font-weight="bold">{tier.upper()}</text>
        </svg>'''
    else:
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
    if admin_key != settings.secret_key:
        raise HTTPException(status_code=403, detail="Invalid admin key")
    
    agent = db.query(Agent).filter(Agent.id == agent_id).first()
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    
    db.query(Capability).filter(Capability.agent_id == agent_id).delete()
    db.query(Rating).filter((Rating.rater_id == agent_id) | (Rating.rated_id == agent_id)).delete()
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
        
        recent_ratings = db.query(Rating).filter(
            Rating.rated_id == agent.id,
            Rating.created_at >= yesterday
        ).count()
        
        if recent_ratings == 0:
            agent.trust_score = max(0, agent.trust_score - 0.2)
            results["decayed"] += 1
        
        if agent.trust_score >= 7:
            agent.days_above_threshold = (agent.days_above_threshold or 0) + 1
            
            if agent.days_above_threshold >= 30 and not agent.is_verified:
                agent.is_verified = True
                results["verified"] += 1
        else:
            if agent.is_verified:
                agent.is_verified = False
                results["unverified"] += 1
            if (agent.days_above_threshold or 0) < 30:
                agent.days_above_threshold = 0
        
        agent.last_trust_check = now
    
    db.commit()
    
    # Update tiers
    tier_results = update_verification_tiers(db)
    results["tiers_updated"] = tier_results["updated"]
    
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
```

---
