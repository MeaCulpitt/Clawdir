from sqlalchemy import Column, String, Text, Float, Integer, Boolean, DateTime, ForeignKey, JSON, Index
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
    verified_endpoint = Column(Boolean, default=False)  # Is endpoint reachable
    last_verification = Column(DateTime)
    last_latency_ms = Column(Integer)
    
    # Earned verification (30 days above 80 trust)
    is_verified = Column(Boolean, default=False)
    days_above_threshold = Column(Integer, default=0)  # Consecutive days above 80
    last_trust_check = Column(DateTime)  # Last daily decay/check
    
    # Relationships
    capabilities = relationship("Capability", back_populates="agent", cascade="all, delete-orphan")
    ratings_given = relationship("Rating", foreign_keys="Rating.rater_id", back_populates="rater")
    ratings_received_rel = relationship("Rating", foreign_keys="Rating.rated_id", back_populates="rated")


class Capability(Base):
    __tablename__ = "capabilities"
    
    id = Column(String(36), primary_key=True, default=gen_uuid)
    agent_id = Column(String(36), ForeignKey("agents.id", ondelete="CASCADE"), nullable=False)
    
    # Structured capability
    category = Column(String(50), nullable=False)  # inference, data, task, domain
    capability_type = Column(String(50), nullable=False)  # text_generation, web_search, etc.
    actions = Column(JSON)  # ["chat", "complete", "summarize"]
    
    # Details
    input_schema = Column(JSON)
    output_schema = Column(JSON)
    pricing = Column(JSON)
    sla = Column(JSON)
    
    created_at = Column(DateTime, server_default=func.now())
    
    # Relationships
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
    
    # Rating
    score = Column(Integer, nullable=False)  # 1-5
    success = Column(Boolean)
    latency_ms = Column(Integer)
    comment = Column(Text)
    
    # Context
    capability_used = Column(String(50))
    transaction_id = Column(String(100))
    
    created_at = Column(DateTime, server_default=func.now())
    
    # Relationships
    rater = relationship("Agent", foreign_keys=[rater_id], back_populates="ratings_given")
    rated = relationship("Agent", foreign_keys=[rated_id], back_populates="ratings_received_rel")
    
    __table_args__ = (
        Index("idx_ratings_rated", "rated_id"),
        Index("idx_ratings_rater", "rater_id"),
    )
