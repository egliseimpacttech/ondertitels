"""Stripe Checkout, billing portal, and subscription webhook handling."""
from typing import Any

import stripe

from . import config, tenants


def _require_stripe_configuration() -> None:
    if not config.STRIPE_SECRET_KEY or not config.STRIPE_WEBHOOK_SECRET:
        raise RuntimeError(
            "Stripe is not configured. Set STRIPE_SECRET_KEY and STRIPE_WEBHOOK_SECRET."
        )
    stripe.api_key = config.STRIPE_SECRET_KEY


def create_checkout_session(church: dict[str, Any], email: str) -> str:
    _require_stripe_configuration()
    church_id = str(church["id"])
    base_url = config.APP_BASE_URL.rstrip("/")
    if not base_url:
        raise RuntimeError("APP_BASE_URL must be set to create a Stripe checkout session.")

    customer_id = church.get("stripe_customer_id")
    if not customer_id:
        customer = stripe.Customer.create(
            email=email,
            name=church["name"],
            metadata={"church_id": church_id},
        )
        customer_id = customer.id
        tenants.set_stripe_customer(church_id, customer_id)

    session = stripe.checkout.Session.create(
        mode="subscription",
        customer=customer_id,
        client_reference_id=church_id,
        line_items=[
            {
                "price_data": {
                    "currency": "eur",
                    "unit_amount": 2000,
                    "tax_behavior": "inclusive",
                    "product_data": {"name": "Ondertitels - kerkabonnement"},
                    "recurring": {"interval": "month"},
                },
                "quantity": 1,
            }
        ],
        automatic_tax={"enabled": True},
        billing_address_collection="required",
        customer_update={"address": "auto", "name": "auto"},
        metadata={"church_id": church_id},
        subscription_data={"metadata": {"church_id": church_id}},
        success_url=f"{base_url}/administration?checkout=success",
        cancel_url=f"{base_url}/administration?checkout=cancelled",
    )
    return str(session.url)


def create_portal_session(church: dict[str, Any]) -> str:
    _require_stripe_configuration()
    customer_id = church.get("stripe_customer_id")
    if not customer_id:
        raise ValueError("No Stripe customer is associated with this church yet.")
    base_url = config.APP_BASE_URL.rstrip("/")
    if not base_url:
        raise RuntimeError("APP_BASE_URL must be set to open the billing portal.")
    session = stripe.billing_portal.Session.create(
        customer=customer_id,
        return_url=f"{base_url}/administration",
    )
    return str(session.url)


def process_webhook(payload: bytes, signature: str) -> None:
    _require_stripe_configuration()
    event = stripe.Webhook.construct_event(
        payload,
        signature,
        config.STRIPE_WEBHOOK_SECRET,
    )
    event_type = event["type"]
    obj = event["data"]["object"]

    if event_type == "checkout.session.completed":
        church_id = (obj.get("metadata") or {}).get("church_id") or obj.get(
            "client_reference_id"
        )
        if church_id:
            subscription_id = str(obj.get("subscription") or "") or None
            subscription = (
                stripe.Subscription.retrieve(subscription_id)
                if subscription_id
                else None
            )
            tenants.update_subscription(
                str(church_id),
                customer_id=str(obj.get("customer") or "") or None,
                subscription_id=subscription_id,
                status=str(subscription.status) if subscription else "incomplete",
                event_created=int(event.get("created") or 0),
            )
        return

    if event_type.startswith("customer.subscription."):
        church_id = (obj.get("metadata") or {}).get("church_id")
        if not church_id:
            return
        subscription_id = str(obj.get("id") or "")
        subscription = stripe.Subscription.retrieve(subscription_id)
        status = str(subscription.status or "incomplete")
        tenants.update_subscription(
            str(church_id),
            customer_id=str(subscription.customer or "") or None,
            subscription_id=subscription_id or None,
            status=status,
            event_created=int(event.get("created") or 0),
        )
        return
