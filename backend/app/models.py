from sqlalchemy import Column, String, Text, Float, Integer, Boolean, DateTime, ForeignKey, JSON, Index, UniqueConstraint
from sqlalchemy.orm import relationship, declarative_base
from sqlalchemy.sql import func
import uuid

Base = declarative_base()


def gen_uuid():
    return str(uuid.uuid4())


class Agent(Base):
    __tablename__ = "agents"
    
    id = Column(String(36), primary_key=True, default=gen_uuid)
    name = Column(String(100), nullable=False)
    endpoint = Column(String(500), nullable=False)
    description = Column(Text)
    owner_email = Column(String(255))
    api_key_hash = Column(String(128), nullable=False)
    
    # Trust
    trust_score = Column(Float, default=10.0)
    ratings_received = Column(Integer, default=0)
    
    # Metadata
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())
    last_seen = Column(DateTime)
    is_active = Column(Boolean, default=True)
    
    # Verification (endpoint health check)
    verified_endpoint = Column(Boolean, default=False)
    last_verification = Column(DateTime)
    last_latency_ms = Column(Integer)
    
    # Earned verification tiers (Bronze 30d, Silver 90d, Gold 180d)
    is_verified = Column(Boolean, default=False)
    trust_tier = Column(String(20), default="none")  # none, bronze, silver, gold
    days_above_threshold = Column(Integer, default=0)
    last_trust_check = Column(DateTime)
    
    # Health tracking
    last_health_check = Column(DateTime)
    
    # Relationships
    capabilities = relationship("Capability", back_populates="agent", cascade="all, delete-orphan")
    ratings_given = relationship("Rating", foreign_keys="Rating.rater_id", back_populates="rater")
    ratings_received_rel = relationship("Rating", foreign_keys="Rating.rated_id", back_populates="rated")


class Capability(Base):
    __tablename__ = "capabilities"
    
    id = Column(String(36), primary_key=True, default=gen_uuid)
    agent_id = Column(String(36), ForeignKey("agents.id", ondelete="CASCADE"), nullable=False)
    
    category = Column(String(50), nullable=False)
    capability_type = Column(String(50), nullable=False)
    actions = Column(JSON)
    
    input_schema = Column(JSON)
    output_schema = Column(JSON)
    pricing = Column(JSON)
    sla = Column(JSON)
    
    created_at = Column(DateTime, server_default=func.now())
    
    agent = relationship("Agent", back_populates="capabilities")
    
    __table_args__ = (
        Index("idx_capabilities_type", "category", "capability_type"),
        Index("idx_capabilities_agent", "agent_id"),
    )


class Rating(Base):
    __tablename__ = "ratings"
    
    id = Column(String(36), primary_key=True, default=gen_uuid)
    rater_id = Column(String(36), ForeignKey("agents.id", ondelete="CASCADE"), nullable=False)
    rated_id = Column(String(36), ForeignKey("agents.id", ondelete="CASCADE"), nullable=False)
    
    score = Column(Integer, nullable=False)
    success = Column(Boolean)
    latency_ms = Column(Integer)
    comment = Column(Text)
    
    capability_used = Column(String(50))
    transaction_id = Column(String(100))
    
    created_at = Column(DateTime, server_default=func.now())
    
    rater = relationship("Agent", foreign_keys=[rater_id], back_populates="ratings_given")
    rated = relationship("Agent", foreign_keys=[rated_id], back_populates="ratings_received_rel")
    
    __table_args__ = (
        Index("idx_ratings_rated", "rated_id"),
        Index("idx_ratings_rater", "rater_id"),
    )


class Follow(Base):
    __tablename__ = "follows"
    
    id = Column(Integer, primary_key=True)
    follower_id = Column(String(36), ForeignKey("agents.id", ondelete="CASCADE"), nullable=False)
    following_id = Column(String(36), ForeignKey("agents.id", ondelete="CASCADE"), nullable=False)
    created_at = Column(DateTime, server_default=func.now())
    
    __table_args__ = (
        UniqueConstraint('follower_id', 'following_id', name='unique_follow'),
    )


class Category(Base):
    __tablename__ = "categories"
    
    id = Column(Integer, primary_key=True)
    name = Column(String(100), unique=True, nullable=False)
    description = Column(Text)
    created_by = Column(String(36), ForeignKey("agents.id", ondelete="SET NULL"))
    created_at = Column(DateTime, server_default=func.now())


class AgentCategory(Base):
    __tablename__ = "agent_categories"
    
    agent_id = Column(String(36), ForeignKey("agents.id", ondelete="CASCADE"), primary_key=True)
    category_id = Column(Integer, ForeignKey("categories.id", ondelete="CASCADE"), primary_key=True)
```

---
