from sqlalchemy.orm import Session
from sqlalchemy import func
from datetime import datetime, timedelta
from math import sqrt
from app.models import Agent, Rating
from app.config import get_settings

settings = get_settings()


def calculate_trust_score(db: Session, agent_id: str) -> float:
    """
    Calculate trust score for an agent based on ratings.
    
    PageRank-inspired: trust flows from raters to rated,
    weighted by rater's own trust score.
    
    Bonuses:
    - Endpoint reachable: +2 trust
    """
    agent = db.query(Agent).filter(Agent.id == agent_id).first()
    if not agent:
        return settings.default_trust_score
    
    # Get ratings from last 90 days
    cutoff = datetime.utcnow() - timedelta(days=90)
    
    ratings = (
        db.query(Rating, Agent.trust_score.label("rater_trust"))
        .join(Agent, Rating.rater_id == Agent.id)
        .filter(Rating.rated_id == agent_id)
        .filter(Rating.created_at > cutoff)
        .all()
    )
    
    base_score = settings.default_trust_score
    
    # Endpoint reachable bonus (0.2 on 0-10 scale)
    if agent.verified_endpoint:
        base_score += 0.2
    
    if not ratings:
        return base_score
    
    weighted_sum = 0.0
    
    for rating, rater_trust in ratings:
        rater_weight = rater_trust
        
        if rating.success is True or rating.success is None:
            contribution = rater_weight * (rating.score / 5.0)
        else:
            contribution = -rater_weight * ((6 - rating.score) / 5.0)
        
        weighted_sum += contribution
    
    # Dampen by sqrt of count (more ratings = more stable score)
    raw_score = base_score + (weighted_sum / max(1, sqrt(len(ratings))))
    
    # Clamp to valid range
    return max(settings.min_trust_score, min(settings.max_trust_score, raw_score))


def update_agent_trust(db: Session, agent_id: str) -> float:
    """Recalculate and update an agent's trust score."""
    new_score = calculate_trust_score(db, agent_id)
    
    agent = db.query(Agent).filter(Agent.id == agent_id).first()
    if agent:
        agent.trust_score = new_score
        agent.ratings_received = (
            db.query(func.count(Rating.id))
            .filter(Rating.rated_id == agent_id)
            .scalar()
        )
        db.commit()
    
    return new_score
