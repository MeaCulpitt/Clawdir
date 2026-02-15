"""Stripe billing integration."""
import stripe
from fastapi import APIRouter, HTTPException, Depends, Request, Header
from sqlalchemy.orm import Session
from typing import Optional

from app.database import get_db
from app.models import Agent
from app.auth import get_current_agent
from app.config import get_settings

settings = get_settings()
router = APIRouter(prefix="/v1/stripe", tags=["billing"])

# Initialize Stripe
stripe.api_key = settings.stripe_secret_key

# Price IDs
PRICE_IDS = {
    "pro": "price_1T1EhdDRliyRLSovvyiSIswf",
    "enterprise": "price_1T1EiKDRliyRLSov9E2onPhk",
}


@router.post("/checkout")
async def create_checkout_session(
    tier: str,
    current_agent: Agent = Depends(get_current_agent),
    db: Session = Depends(get_db)
):
    """
    Create a Stripe Checkout session for subscription.
    
    tier: "pro" or "enterprise"
    Returns: checkout URL to redirect user to
    """
    if not settings.stripe_secret_key:
        raise HTTPException(status_code=503, detail="Stripe not configured")
    
    if tier not in PRICE_IDS:
        raise HTTPException(status_code=400, detail=f"Invalid tier. Choose: {list(PRICE_IDS.keys())}")
    
    # Check if already subscribed
    if current_agent.subscription_tier == tier:
        raise HTTPException(status_code=400, detail=f"Already subscribed to {tier}")
    
    try:
        # Create or get Stripe customer
        if current_agent.stripe_customer_id:
            customer_id = current_agent.stripe_customer_id
        else:
            customer = stripe.Customer.create(
                email=current_agent.owner_email,
                metadata={
                    "agent_id": str(current_agent.id),
                    "agent_name": current_agent.name,
                }
            )
            customer_id = customer.id
            current_agent.stripe_customer_id = customer_id
            db.commit()
        
        # Create checkout session
        session = stripe.checkout.Session.create(
            customer=customer_id,
            payment_method_types=["card"],
            line_items=[{
                "price": PRICE_IDS[tier],
                "quantity": 1,
            }],
            mode="subscription",
            success_url=f"https://clawdir.xyz/dashboard.html?upgraded={tier}",
            cancel_url="https://clawdir.xyz/pricing.html?cancelled=true",
            metadata={
                "agent_id": str(current_agent.id),
                "tier": tier,
            }
        )
        
        return {
            "checkout_url": session.url,
            "session_id": session.id,
        }
        
    except stripe.error.StripeError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/webhook")
async def stripe_webhook(
    request: Request,
    stripe_signature: Optional[str] = Header(None, alias="Stripe-Signature"),
    db: Session = Depends(get_db)
):
    """
    Handle Stripe webhook events.
    
    Events handled:
    - checkout.session.completed: Activate subscription
    - customer.subscription.updated: Handle plan changes
    - customer.subscription.deleted: Downgrade to free
    """
    if not settings.stripe_webhook_secret:
        raise HTTPException(status_code=503, detail="Webhook not configured")
    
    payload = await request.body()
    
    try:
        event = stripe.Webhook.construct_event(
            payload, stripe_signature, settings.stripe_webhook_secret
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
        subscription_id = session.get("subscription")
        
        if agent_id and tier:
            agent = db.query(Agent).filter(Agent.id == agent_id).first()
            if agent:
                agent.subscription_tier = tier
                agent.stripe_subscription_id = subscription_id
                db.commit()
                print(f"✅ Agent {agent.name} upgraded to {tier}")
    
    elif event["type"] == "customer.subscription.updated":
        subscription = event["data"]["object"]
        subscription_id = subscription["id"]
        
        agent = db.query(Agent).filter(Agent.stripe_subscription_id == subscription_id).first()
        if agent:
            # Check if subscription is still active
            if subscription["status"] in ("active", "trialing"):
                # Could update tier based on price ID here
                pass
            else:
                agent.subscription_tier = "free"
                db.commit()
                print(f"⚠️ Agent {agent.name} subscription inactive")
    
    elif event["type"] == "customer.subscription.deleted":
        subscription = event["data"]["object"]
        subscription_id = subscription["id"]
        
        agent = db.query(Agent).filter(Agent.stripe_subscription_id == subscription_id).first()
        if agent:
            agent.subscription_tier = "free"
            agent.stripe_subscription_id = None
            db.commit()
            print(f"❌ Agent {agent.name} downgraded to free (cancelled)")
    
    return {"status": "ok"}


@router.post("/portal")
async def create_portal_session(
    current_agent: Agent = Depends(get_current_agent),
):
    """
    Create a Stripe Customer Portal session for managing subscription.
    """
    if not settings.stripe_secret_key:
        raise HTTPException(status_code=503, detail="Stripe not configured")
    
    if not current_agent.stripe_customer_id:
        raise HTTPException(status_code=400, detail="No billing account. Subscribe first.")
    
    try:
        session = stripe.billing_portal.Session.create(
            customer=current_agent.stripe_customer_id,
            return_url="https://clawdir.xyz/dashboard.html",
        )
        
        return {"portal_url": session.url}
        
    except stripe.error.StripeError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/status")
async def billing_status(
    current_agent: Agent = Depends(get_current_agent),
):
    """Get current billing status."""
    return {
        "agent_id": str(current_agent.id),
        "subscription_tier": current_agent.subscription_tier or "free",
        "stripe_customer_id": current_agent.stripe_customer_id,
        "has_subscription": current_agent.stripe_subscription_id is not None,
    }
