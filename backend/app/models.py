## models.py - Add new fields and tables

```python
# Add to Agent class in models.py:

days_above_threshold = Column(Integer, default=0)
trust_tier = Column(String, default="none")  # none, bronze, silver, gold
last_trust_check = Column(DateTime)
last_health_check = Column(DateTime)
last_latency_ms = Column(Float)

# Add new tables:

class Follow(Base):
    __tablename__ = "follows"
    
    id = Column(Integer, primary_key=True)
    follower_id = Column(String, ForeignKey("agents.id"), nullable=False)
    following_id = Column(String, ForeignKey("agents.id"), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    
    __table_args__ = (
        UniqueConstraint('follower_id', 'following_id', name='unique_follow'),
    )


class Category(Base):
    __tablename__ = "categories"
    
    id = Column(Integer, primary_key=True)
    name = Column(String, unique=True, nullable=False)
    description = Column(String)
    created_by = Column(String, ForeignKey("agents.id"))
    created_at = Column(DateTime, default=datetime.utcnow)


class AgentCategory(Base):
    __tablename__ = "agent_categories"
    
    agent_id = Column(String, ForeignKey("agents.id"), primary_key=True)
    category_id = Column(Integer, ForeignKey("categories.id"), primary_key=True)
```

---
