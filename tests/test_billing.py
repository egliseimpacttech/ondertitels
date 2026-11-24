from types import SimpleNamespace

from backend import billing, config


def test_checkout_uses_eur_monthly_price_with_tax_included(monkeypatch):
    session_parameters = {}
    monkeypatch.setattr(config, "STRIPE_SECRET_KEY", "sk_test_example")
    monkeypatch.setattr(config, "STRIPE_WEBHOOK_SECRET", "whsec_example")
    monkeypatch.setattr(config, "APP_BASE_URL", "https://app.example")
    monkeypatch.setattr(
        billing.stripe.Customer,
        "create",
        lambda **kwargs: SimpleNamespace(id="cus_example"),
    )
    monkeypatch.setattr(
        billing.tenants,
        "set_stripe_customer",
        lambda church_id, customer_id: None,
    )

    def create_session(**kwargs):
        session_parameters.update(kwargs)
        return SimpleNamespace(url="https://checkout.stripe.example/session")

    monkeypatch.setattr(billing.stripe.checkout.Session, "create", create_session)

    url = billing.create_checkout_session(
        {"id": "church-example", "name": "Example church"},
        "admin@example.com",
    )

    assert url == "https://checkout.stripe.example/session"
    price = session_parameters["line_items"][0]["price_data"]
    assert price["currency"] == "eur"
    assert price["unit_amount"] == 2000
    assert price["tax_behavior"] == "inclusive"
    assert price["recurring"]["interval"] == "month"
    assert session_parameters["automatic_tax"] == {"enabled": True}


def test_subscription_webhook_applies_current_stripe_status(monkeypatch):
    updates = []
    monkeypatch.setattr(config, "STRIPE_SECRET_KEY", "sk_test_example")
    monkeypatch.setattr(config, "STRIPE_WEBHOOK_SECRET", "whsec_example")
    monkeypatch.setattr(
        billing.stripe.Webhook,
        "construct_event",
        lambda *args: {
            "type": "customer.subscription.updated",
            "created": 123,
            "data": {
                "object": {
                    "id": "sub_example",
                    "customer": "cus_example",
                    "metadata": {"church_id": "church-example"},
                }
            },
        },
    )
    monkeypatch.setattr(
        billing.stripe.Subscription,
        "retrieve",
        lambda subscription_id: SimpleNamespace(
            id=subscription_id,
            status="active",
            customer="cus_example",
        ),
    )
    monkeypatch.setattr(
        billing.tenants,
        "update_subscription",
        lambda church_id, **kwargs: updates.append((church_id, kwargs)),
    )

    billing.process_webhook(b"payload", "signature")

    assert updates == [
        (
            "church-example",
            {
                "customer_id": "cus_example",
                "subscription_id": "sub_example",
                "status": "active",
                "event_created": 123,
            },
        )
    ]
