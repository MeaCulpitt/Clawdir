"""Stripe billing integration for ClawDir Pro/Team subscriptions."""
import stripe
from fastapi import APIRouter, HTTPException, Request, Depends
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import Optional

from app.database import get_db
from app.models import Agent
from app.auth import get_current_agent
from app.config import get_settings

settings = get_settings()
router = APIRouter(prefix="/v1/billing", tags=["billing"])

# Configure Stripe
stripe.api_key = settings.stripe_secret_key


class CreateCheckoutRequest(BaseModel):
    tier: str  # "pro" or "team"
    success_url: Optional[str] = None
    cancel_url: Optional[str] = None


class SubscriptionStatus(BaseModel):
    tier: str  # "free", "pro", "team"
    status: str  # "active", "canceled", "past_due", etc.
    current_period_end: Optional[str] = None
    cancel_at_period_end: bool = False


@router.get("/config")
def get_billing_config():
    """Get Stripe publishable key for frontend."""
    return {
        "publishable_key": settings.stripe_publishable_key,
        "prices": {
            "pro": settings.stripe_price_pro,
            "team": settings.stripe_price_team
        }
    }


@router.post("/checkout")
def create_checkout_session(
    request: CreateCheckoutRequest,
    current_agent: Agent = Depends(get_current_agent),
    db: Session = Depends(get_db)
):
    """Create a Stripe Checkout session for subscription."""
    
    if not settings.stripe_secret_key:
        raise HTTPException(status_code=503, detail="Billing not configured")
    
    # Get price ID based on tier
    if request.tier == "pro":
        price_id = settings.stripe_price_pro
    elif request.tier == "team":
        price_id = settings.stripe_price_team
    else:
        raise HTTPException(status_code=400, detail="Invalid tier")
    
    if not price_id:
        raise HTTPException(status_code=503, detail=f"Price not configured for {request.tier}")
    
    success_url = request.success_url or f"{settings.frontend_url}/billing/success?session_id={{CHECKOUT_SESSION_ID}}"
    cancel_url = request.cancel_url or f"{settings.frontend_url}/pricing.html"
    
    try:
        # Create or get Stripe customer
        if not current_agent.stripe_customer_id:
            customer = stripe.Customer.create(
                email=current_agent.owner_email,
                metadata={"agent_id": str(current_agent.id), "agent_name": current_agent.name}
            )
            current_agent.stripe_customer_id = customer.id
            db.commit()
        
        # Create checkout session
        session = stripe.checkout.Session.create(
            customer=current_agent.stripe_customer_id,
            payment_method_types=["card"],
            line_items=[{"price": price_id, "quantity": 1}],
            mode="subscription",
            success_url=success_url,
            cancel_url=cancel_url,
            metadata={"agent_id": str(current_agent.id), "tier": request.tier}
        )
        
        return {"checkout_url": session.url, "session_id": session.id}
        
    except stripe.error.StripeError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/subscription")
def get_subscription(
    current_agent: Agent = Depends(get_current_agent),
    db: Session = Depends(get_db)
):
    """Get current subscription status."""
    
    if not settings.stripe_secret_key:
        return SubscriptionStatus(tier="free", status="active")
    
    if not current_agent.stripe_customer_id:
        return SubscriptionStatus(tier="free", status="active")
    
    try:
        subscriptions = stripe.Subscription.list(
            customer=current_agent.stripe_customer_id,
            status="active",
            limit=1
        )
        
        if not subscriptions.data:
            return SubscriptionStatus(tier="free", status="active")
        
        sub = subscriptions.data[0]
        
        # Determine tier from price
        price_id = sub["items"]["data"][0]["price"]["id"]
        if price_id == settings.stripe_price_pro:
            tier = "pro"
        elif price_id == settings.stripe_price_team:
            tier = "team"
        else:
            tier = "unknown"
        
        return SubscriptionStatus(
            tier=tier,
            status=sub["status"],
            current_period_end=sub["current_period_end"],
            cancel_at_period_end=sub["cancel_at_period_end"]
        )
        
    except stripe.error.StripeError:
        return SubscriptionStatus(tier="free", status="active")


@router.post("/portal")
def create_portal_session(
    current_agent: Agent = Depends(get_current_agent),
    db: Session = Depends(get_db)
):
    """Create a Stripe Customer Portal session for managing subscription."""
    
    if not settings.stripe_secret_key:
        raise HTTPException(status_code=503, detail="Billing not configured")
    
    if not current_agent.stripe_customer_id:
        raise HTTPException(status_code=400, detail="No subscription found")
    
    try:
        session = stripe.billing_portal.Session.create(
            customer=current_agent.stripe_customer_id,
            return_url=f"{settings.frontend_url}/pricing.html"
        )
        return {"portal_url": session.url}
        
    except stripe.error.StripeError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/webhook")
async def stripe_webhook(request: Request, db: Session = Depends(get_db)):
    """Handle Stripe webhook events."""
    
    payload = await request.body()
    sig_header = request.headers.get("stripe-signature")
    
    if not settings.stripe_webhook_secret:
        raise HTTPException(status_code=503, detail="Webhook not configured")
    
    try:
        event = stripe.Webhook.construct_event(
            payload, sig_header, settings.stripe_webhook_secret
        )
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid payload")
    except stripe.error.SignatureVerificationError:
        raise HTTPException(status_code=400, detail="Invalid signature")
    
    # Handle events
    if event["type"] == "checkout.session.completed":
        session = event["data"]["object"]
        agent_id = session.get("metadata", {}).get("agent_id")
        tier = session.get("metadata", {}).get("tier")
        
        if agent_id:
            agent = db.query(Agent).filter(Agent.id == agent_id).first()
            if agent:
                agent.subscription_tier = tier
                agent.stripe_subscription_id = session.get("subscription")
                db.commit()
    
    elif event["type"] == "customer.subscription.deleted":
        subscription = event["data"]["object"]
        customer_id = subscription["customer"]
        
        agent = db.query(Agent).filter(Agent.stripe_customer_id == customer_id).first()
        if agent:
            agent.subscription_tier = "free"
            agent.stripe_subscription_id = None
            db.commit()
    
    elif event["type"] == "customer.subscription.updated":
        subscription = event["data"]["object"]
        customer_id = subscription["customer"]
        
        agent = db.query(Agent).filter(Agent.stripe_customer_id == customer_id).first()
        if agent:
            # Update tier based on new price
            price_id = subscription["items"]["data"][0]["price"]["id"]
            if price_id == settings.stripe_price_pro:
                agent.subscription_tier = "pro"
            elif price_id == settings.stripe_price_team:
                agent.subscription_tier = "team"
            db.commit()
    
    return {"status": "ok"}
