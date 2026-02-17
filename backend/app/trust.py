---

## backend/app/trust.py

```python
from sqlalchemy.orm import Session
from sqlalchemy import func
from datetime import datetime, timedelta
from math import sqrt
from app.models import Agent, Rating
from app.config import get_settings

settings = get_settings()


def calculate_weighted_rating(ratings: list) -> float:
    """Calculate weighted average based on rater's trust."""
    if not ratings:
        return 10.0
    
    total_weight = 0.0
    weighted_sum = 0.0
    
    for rating in ratings:
        rater_trust = rating.rater.trust_score
        # Weight = sqrt(trust) - gives more weight to trusted raters
        weight = (rater_trust / 10.0) ** 0.5
        
        if rating.success is True or rating.success is None:
            contribution = rating.score * weight
        else:
            contribution = -((6 - rating.score) * weight)
        
        weighted_sum += contribution
        total_weight += weight
    
    if total_weight == 0:
        return 10.0
    
    return weighted_sum / total_weight


def calculate_trust_score(db: Session, agent_id: str) -> float:
    """
    Calculate trust score for an agent based on weighted ratings.
    
    PageRank-inspired: trust flows from raters to rated,
    weighted by rater's own trust score (sqrt weighted).
    """
    agent = db.query(Agent).filter(Agent.id == agent_id).first()
    if not agent:
        return settings.default_trust_score
    
    # Get ratings from last 30 days
    cutoff = datetime.utcnow() - timedelta(days=30)
    
    ratings = (
        db.query(Rating)
        .join(Agent, Rating.rater_id == Agent.id)
        .filter(Rating.rated_id == agent_id)
        .filter(Rating.created_at > cutoff)
        .all()
    )
    
    base_score = settings.default_trust_score
    
    # Endpoint reachable bonus
    if agent.verified_endpoint:
        base_score += 0.2
    
    if not ratings:
        return base_score
    
    # Use weighted rating calculation
    weighted_score = calculate_weighted_rating(ratings)
    
    # Blend with historical (70% new, 30% historical)
    historical_cutoff = datetime.utcnow() - timedelta(days=90)
    historical = (
        db.query(Rating)
        .join(Agent, Rating.rater_id == Agent.id)
        .filter(Rating.rated_id == agent_id)
        .filter(Rating.created_at > historical_cutoff)
        .filter(Rating.created_at <= cutoff)
        .all()
    )
    
    if historical:
        historical_score = calculate_weighted_rating(historical)
        raw_score = (weighted_score * 0.7) + (historical_score * 0.3)
    else:
        raw_score = weighted_score
    
    # Dampen by sqrt of count
    raw_score = base_score + (raw_score / max(1, sqrt(len(ratings))))
    
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


def update_verification_tiers(db: Session):
    """Update verification tiers based on consecutive days above threshold."""
    threshold = 7.0
    now = datetime.utcnow()
    yesterday = now - timedelta(days=1)
    
    agents = db.query(Agent).filter(Agent.is_active == True).all()
    updated = 0
    
    for agent in agents:
        # Check if had recent ratings yesterday
        recent_ratings = db.query(Rating).filter(
            Rating.rated_id == agent.id,
            Rating.created_at >= yesterday
        ).count()
        
        above_threshold = agent.trust_score >= threshold
        
        if above_threshold and recent_ratings > 0:
            agent.days_above_threshold = (agent.days_above_threshold or 0) + 1
        else:
            agent.days_above_threshold = 0
        
        days = agent.days_above_threshold or 0
        
        # Update tier
        if days >= 180:
            agent.trust_tier = "gold"
            agent.is_verified = True
        elif days >= 90:
            agent.trust_tier = "silver"
            agent.is_verified = True
        elif days >= 30:
            agent.trust_tier = "bronze"
            agent.is_verified = True
        else:
            agent.trust_tier = "none"
            agent.is_verified = False
        
        agent.last_trust_check = now
        updated += 1
    
    db.commit()
    return {"updated": updated}
```

---
