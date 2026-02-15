"""Seed the database with demo agents if empty."""
from sqlalchemy.orm import Session
from app.models import Agent, Capability
import secrets


DEMO_AGENTS = [
    {
        "name": "Molt_Seavers",
        "endpoint": "https://openclaw.ai/agents/molt",
        "description": "TAO subnet mining assistant - monitors miners, writes analysis, manages Bittensor operations",
        "owner_email": "hello@clawdir.xyz",
        "capabilities": [
            {"category": "task", "capability_type": "monitoring", "actions": ["health_check", "restart", "diagnose"]},
            {"category": "data", "capability_type": "research", "actions": ["subnet_analysis", "market_data", "sentiment"]}
        ]
    },
    {
        "name": "WebScraper_Pro",
        "endpoint": "https://api.example.com/scraper",
        "description": "High-performance web scraping and data extraction. Handles JS-rendered pages, rate limiting, and proxy rotation.",
        "owner_email": "demo@clawdir.xyz",
        "capabilities": [
            {"category": "data", "capability_type": "web_scrape", "actions": ["scrape", "extract", "crawl"]},
            {"category": "data", "capability_type": "data_extraction", "actions": ["parse_html", "extract_json", "pdf_to_text"]}
        ]
    },
    {
        "name": "CodeReviewer",
        "endpoint": "https://api.example.com/review",
        "description": "Automated code review and security analysis. Supports Python, JavaScript, Go, and Rust.",
        "owner_email": "demo@clawdir.xyz",
        "capabilities": [
            {"category": "task", "capability_type": "code_execution", "actions": ["review", "lint", "security_scan"]},
            {"category": "inference", "capability_type": "text_generation", "actions": ["explain", "suggest_fix"]}
        ]
    },
    {
        "name": "ImageGen_Studio",
        "endpoint": "https://api.example.com/imagegen",
        "description": "AI image generation with multiple models. SDXL, DALL-E, Midjourney-style outputs.",
        "owner_email": "demo@clawdir.xyz",
        "capabilities": [
            {"category": "inference", "capability_type": "image_generation", "actions": ["generate", "inpaint", "upscale"]},
            {"category": "inference", "capability_type": "embedding", "actions": ["image_embed"]}
        ]
    },
    {
        "name": "TranslatorBot",
        "endpoint": "https://api.example.com/translate",
        "description": "Real-time translation across 100+ languages. Specialized in technical and legal documents.",
        "owner_email": "demo@clawdir.xyz",
        "capabilities": [
            {"category": "inference", "capability_type": "translation", "actions": ["translate", "detect_language"]},
            {"category": "inference", "capability_type": "text_generation", "actions": ["summarize", "localize"]}
        ]
    },
    {
        "name": "CalendarAgent",
        "endpoint": "https://api.example.com/calendar",
        "description": "Smart calendar management. Schedule meetings, find optimal times, send reminders.",
        "owner_email": "demo@clawdir.xyz",
        "capabilities": [
            {"category": "task", "capability_type": "calendar_management", "actions": ["schedule", "reschedule", "find_time"]},
            {"category": "task", "capability_type": "notification", "actions": ["remind", "alert"]}
        ]
    },
    {
        "name": "DataExtractor",
        "endpoint": "https://api.example.com/extract",
        "description": "Extract structured data from documents, PDFs, and images. OCR and table parsing included.",
        "owner_email": "demo@clawdir.xyz",
        "capabilities": [
            {"category": "data", "capability_type": "data_extraction", "actions": ["extract_text", "parse_tables", "ocr"]},
            {"category": "inference", "capability_type": "classification", "actions": ["classify_document"]}
        ]
    },
    {
        "name": "LegalAdvisor",
        "endpoint": "https://api.example.com/legal",
        "description": "Contract analysis and legal document review. NDA checking, clause extraction, risk assessment.",
        "owner_email": "demo@clawdir.xyz",
        "capabilities": [
            {"category": "domain", "capability_type": "legal", "actions": ["review_contract", "extract_clauses", "assess_risk"]},
            {"category": "inference", "capability_type": "text_generation", "actions": ["summarize", "explain"]}
        ]
    },
    {
        "name": "SentimentAnalyzer",
        "endpoint": "https://api.example.com/sentiment",
        "description": "Real-time sentiment analysis for social media, reviews, and customer feedback. Supports 20+ languages.",
        "owner_email": "demo@clawdir.xyz",
        "capabilities": [
            {"category": "inference", "capability_type": "classification", "actions": ["analyze", "batch_analyze", "stream"]}
        ]
    },
    {
        "name": "PDFWizard",
        "endpoint": "https://api.example.com/pdf",
        "description": "PDF manipulation and extraction. Merge, split, OCR, form filling, and digital signatures.",
        "owner_email": "demo@clawdir.xyz",
        "capabilities": [
            {"category": "task", "capability_type": "file_management", "actions": ["merge", "split", "compress", "sign"]}
        ]
    },
    {
        "name": "EmailComposer",
        "endpoint": "https://api.example.com/email",
        "description": "AI-powered email drafting and management. Professional tone adjustment, follow-up scheduling.",
        "owner_email": "demo@clawdir.xyz",
        "capabilities": [
            {"category": "task", "capability_type": "email_management", "actions": ["compose", "reply", "schedule"]}
        ]
    },
    {
        "name": "StockResearcher",
        "endpoint": "https://api.example.com/stocks",
        "description": "Financial research and analysis. SEC filings, earnings reports, technical indicators.",
        "owner_email": "demo@clawdir.xyz",
        "capabilities": [
            {"category": "domain", "capability_type": "financial", "actions": ["analyze_stock", "screen", "alert"]}
        ]
    },
    {
        "name": "MeetingAssistant",
        "endpoint": "https://api.example.com/meetings",
        "description": "Meeting transcription, summarization, and action item extraction. Zoom, Teams, Meet.",
        "owner_email": "demo@clawdir.xyz",
        "capabilities": [
            {"category": "inference", "capability_type": "transcription", "actions": ["transcribe", "summarize"]}
        ]
    },
    {
        "name": "APIConnector",
        "endpoint": "https://api.example.com/connect",
        "description": "Universal API integration layer. Connect any REST/GraphQL API with automatic schema detection.",
        "owner_email": "demo@clawdir.xyz",
        "capabilities": [
            {"category": "data", "capability_type": "api_aggregation", "actions": ["connect", "transform", "cache"]}
        ]
    }
]


def seed_database(db: Session):
    """Seed demo agents if database is empty."""
    existing = db.query(Agent).count()
    if existing > 0:
        print(f"Database has {existing} agents, skipping seed")
        return
    
    print("Database empty, seeding demo agents...")
    
    for agent_data in DEMO_AGENTS:
        caps_data = agent_data.pop("capabilities")
        
        agent = Agent(
            name=agent_data["name"],
            endpoint=agent_data["endpoint"],
            description=agent_data["description"],
            owner_email=agent_data["owner_email"],
            api_key_hash=secrets.token_hex(32),  # Dummy hash, these are demo agents
            trust_score=10.0,
            is_active=True
        )
        db.add(agent)
        db.flush()
        
        for cap in caps_data:
            capability = Capability(
                agent_id=agent.id,
                category=cap["category"],
                capability_type=cap["capability_type"],
                actions=cap.get("actions", [])
            )
            db.add(capability)
    
    db.commit()
    print(f"Seeded {len(DEMO_AGENTS)} demo agents")
