"""API endpoint tests for ClawDir."""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.main import app
from app.models import Base
from app.database import get_db


# Test database setup
SQLALCHEMY_DATABASE_URL = "sqlite:///:memory:"
engine = create_engine(
    SQLALCHEMY_DATABASE_URL,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def override_get_db():
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()


app.dependency_overrides[get_db] = override_get_db


@pytest.fixture(autouse=True)
def setup_database():
    """Create tables before each test, drop after."""
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)


client = TestClient(app)


class TestHealth:
    def test_health_check(self):
        response = client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"
        assert "clawdir" in data["service"].lower()

    def test_root_redirects_to_docs(self):
        response = client.get("/", follow_redirects=False)
        # Root should return something (either redirect or content)
        assert response.status_code in [200, 307, 308]


class TestAgentRegistration:
    def test_register_agent_success(self):
        response = client.post("/v1/agents", json={
            "name": "TestAgent",
            "endpoint": "https://api.example.com/test",
            "description": "A test agent",
            "owner_email": "test@example.com",
            "capabilities": []
        })
        assert response.status_code == 200
        data = response.json()
        assert data["name"] == "TestAgent"
        assert "id" in data
        assert "api_key" in data
        assert data["api_key"].startswith("claw_")
        assert data["trust_score"] == 10.0

    def test_register_agent_missing_name(self):
        response = client.post("/v1/agents", json={
            "endpoint": "https://api.example.com/test",
            "owner_email": "test@example.com"
        })
        assert response.status_code == 422  # Validation error

    def test_register_agent_invalid_email(self):
        response = client.post("/v1/agents", json={
            "name": "TestAgent",
            "endpoint": "https://api.example.com/test",
            "owner_email": "not-an-email",
            "capabilities": []
        })
        assert response.status_code == 422

    def test_register_agent_duplicate_name(self):
        # First registration
        client.post("/v1/agents", json={
            "name": "UniqueAgent",
            "endpoint": "https://api.example.com/test1",
            "owner_email": "test@example.com",
            "capabilities": []
        })
        # Duplicate
        response = client.post("/v1/agents", json={
            "name": "UniqueAgent",
            "endpoint": "https://api.example.com/test2",
            "owner_email": "test2@example.com",
            "capabilities": []
        })
        assert response.status_code == 400
        assert "already exists" in response.json()["detail"].lower()


class TestAgentDiscovery:
    def test_discover_empty(self):
        response = client.get("/v1/discover")
        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 0
        assert data["agents"] == []

    def test_discover_with_agents(self):
        # Register an agent
        client.post("/v1/agents", json={
            "name": "DiscoverableAgent",
            "endpoint": "https://api.example.com/test",
            "description": "Test agent",
            "owner_email": "test@example.com",
            "capabilities": []
        })
        
        response = client.get("/v1/discover")
        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 1
        assert len(data["agents"]) == 1
        assert data["agents"][0]["name"] == "DiscoverableAgent"

    def test_discover_filter_by_capability(self):
        # Register agent with capability
        client.post("/v1/agents", json={
            "name": "InferenceAgent",
            "endpoint": "https://api.example.com/test",
            "owner_email": "test@example.com",
            "capabilities": [
                {"category": "inference", "capability_type": "text_generation", "actions": ["generate"]}
            ]
        })
        
        # Search for inference
        response = client.get("/v1/discover?capability=inference")
        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 1
        
        # Search for non-existent capability
        response = client.get("/v1/discover?capability=robotics")
        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 0

    def test_discover_min_trust_filter(self):
        # Register agent (default trust = 10)
        client.post("/v1/agents", json={
            "name": "TrustedAgent",
            "endpoint": "https://api.example.com/test",
            "owner_email": "test@example.com",
            "capabilities": []
        })
        
        # Should find with min_trust <= 10
        response = client.get("/v1/discover?min_trust=5")
        assert response.status_code == 200
        assert response.json()["total"] == 1
        
        # Should not find with min_trust > 10
        response = client.get("/v1/discover?min_trust=50")
        assert response.status_code == 200
        assert response.json()["total"] == 0


class TestAgentRetrieval:
    def test_get_agent_by_id(self):
        # Register
        reg_response = client.post("/v1/agents", json={
            "name": "GetMeAgent",
            "endpoint": "https://api.example.com/test",
            "owner_email": "test@example.com",
            "capabilities": []
        })
        agent_id = reg_response.json()["id"]
        
        # Get
        response = client.get(f"/v1/agents/{agent_id}")
        assert response.status_code == 200
        data = response.json()
        assert data["name"] == "GetMeAgent"
        assert data["id"] == agent_id

    def test_get_agent_not_found(self):
        response = client.get("/v1/agents/00000000-0000-0000-0000-000000000000")
        assert response.status_code == 404


class TestActivity:
    def test_activity_feed(self):
        # Register an agent
        client.post("/v1/agents", json={
            "name": "ActivityAgent",
            "endpoint": "https://api.example.com/test",
            "owner_email": "test@example.com",
            "capabilities": []
        })
        
        response = client.get("/v1/activity")
        assert response.status_code == 200
        data = response.json()
        assert "activity" in data
        assert len(data["activity"]) >= 1
        assert data["activity"][0]["type"] == "registration"
        assert data["activity"][0]["agent_name"] == "ActivityAgent"


class TestBadge:
    def test_badge_svg(self):
        # Register
        reg_response = client.post("/v1/agents", json={
            "name": "BadgeAgent",
            "endpoint": "https://api.example.com/test",
            "owner_email": "test@example.com",
            "capabilities": []
        })
        agent_id = reg_response.json()["id"]
        
        # Get badge
        response = client.get(f"/badge/{agent_id}.svg")
        assert response.status_code == 200
        assert response.headers["content-type"] == "image/svg+xml"
        assert "ClawDir" in response.text
        assert "svg" in response.text

    def test_badge_not_found(self):
        response = client.get("/badge/00000000-0000-0000-0000-000000000000.svg")
        assert response.status_code == 200  # Returns a "not found" badge
        assert "Not Found" in response.text


class TestRatings:
    def test_rate_agent(self):
        # Register two agents
        rater = client.post("/v1/agents", json={
            "name": "RaterAgent",
            "endpoint": "https://api.example.com/rater",
            "owner_email": "rater@example.com",
            "capabilities": []
        }).json()
        
        rated = client.post("/v1/agents", json={
            "name": "RatedAgent",
            "endpoint": "https://api.example.com/rated",
            "owner_email": "rated@example.com",
            "capabilities": []
        }).json()
        
        # Rate
        response = client.post("/v1/ratings", 
            json={
                "rated_id": rated["id"],
                "score": 5,
                "success": True,
                "notes": "Great agent!"
            },
            headers={"Authorization": f"Bearer {rater['api_key']}"}
        )
        assert response.status_code == 200
        data = response.json()
        assert data["success"] == True
        
        # Check trust score increased
        updated = client.get(f"/v1/agents/{rated['id']}").json()
        assert updated["trust_score"] > 10.0  # Should have increased
        assert updated["ratings_received"] == 1
