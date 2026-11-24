"""Church workspaces and email-based user access stored in Firestore."""
import hashlib
import re
from typing import Any

from firebase_admin import firestore

MINISTRY_TENANT_ID = "ministere-apostolique-impact"
MINISTRY_NAME = "Ministère Apostolique Impact"
MINISTRY_ADMIN_EMAIL = "kaat.dbolle@gmail.com"
PAID_STORAGE_LIMIT_BYTES = 100 * 1_000_000_000


def _db():
    return firestore.client()


def _email_key(email: str) -> str:
    return hashlib.sha256(email.strip().lower().encode("utf-8")).hexdigest()


def _membership_ref(email: str):
    return _db().collection("user_access").document(_email_key(email))


def get_membership(email: str) -> dict[str, Any] | None:
    if not email:
        return None
    snapshot = _membership_ref(email).get()
    return snapshot.to_dict() if snapshot.exists else None


def get_church(church_id: str) -> dict[str, Any] | None:
    snapshot = _db().collection("churches").document(church_id).get()
    if not snapshot.exists:
        return None
    return {"id": snapshot.id, **(snapshot.to_dict() or {})}


def ensure_ministry_membership(email: str, role: str = "member") -> dict[str, Any]:
    """Create the free ministry workspace and its first access record when needed."""
    email = email.strip().lower()
    db = _db()
    access_ref = db.collection("user_access").document(_email_key(email))
    current = access_ref.get()
    if current.exists:
        membership = current.to_dict() or {}
        if email == MINISTRY_ADMIN_EMAIL:
            previous_church_id = membership.get("church_id")
            db.collection("churches").document(MINISTRY_TENANT_ID).set(
                {
                    "name": MINISTRY_NAME,
                    "plan": "free",
                    "subscription_status": "active",
                    "storage_limit_bytes": None,
                    "owner_email": MINISTRY_ADMIN_EMAIL,
                },
                merge=True,
            )
            membership = {
                "church_id": MINISTRY_TENANT_ID,
                "email": email,
                "role": "admin",
            }
            batch = db.batch()
            if previous_church_id and previous_church_id != MINISTRY_TENANT_ID:
                batch.delete(
                    db.collection("churches")
                    .document(str(previous_church_id))
                    .collection("members")
                    .document(_email_key(email))
                )
            batch.set(access_ref, membership)
            batch.set(
                db.collection("churches")
                .document(MINISTRY_TENANT_ID)
                .collection("members")
                .document(_email_key(email)),
                membership,
                merge=True,
            )
            batch.commit()
        return membership

    church_ref = db.collection("churches").document(MINISTRY_TENANT_ID)
    church_ref.set(
        {
            "name": MINISTRY_NAME,
            "plan": "free",
            "subscription_status": "active",
            "storage_limit_bytes": None,
            "owner_email": MINISTRY_ADMIN_EMAIL,
        },
        merge=True,
    )
    membership = {"church_id": MINISTRY_TENANT_ID, "email": email, "role": role}
    batch = db.batch()
    batch.set(access_ref, membership)
    batch.set(
        church_ref.collection("members").document(_email_key(email)),
        membership,
    )
    batch.commit()
    return membership


def create_church(name: str, uid: str, email: str) -> dict[str, Any]:
    name = name.strip()
    email = email.strip().lower()
    if not name or len(name) > 160:
        raise ValueError("Church name must contain 1 to 160 characters.")
    if not uid or not email:
        raise ValueError("A signed-in account with an email address is required.")

    db = _db()
    access_ref = db.collection("user_access").document(_email_key(email))
    if access_ref.get().exists:
        raise ValueError("This email already belongs to a church.")

    church_ref = db.collection("churches").document()
    membership = {"church_id": church_ref.id, "email": email, "role": "admin"}
    church = {
        "name": name,
        "plan": "paid",
        "subscription_status": "incomplete",
        "storage_limit_bytes": PAID_STORAGE_LIMIT_BYTES,
        "owner_email": email,
        "owner_uid": uid,
        "stripe_customer_id": None,
        "stripe_subscription_id": None,
    }
    batch = db.batch()
    batch.set(church_ref, church)
    batch.create(access_ref, membership)
    batch.set(
        church_ref.collection("members").document(_email_key(email)),
        membership,
    )
    try:
        batch.commit()
    except Exception as exc:
        if access_ref.get().exists:
            raise ValueError("This email already belongs to a church.") from exc
        raise
    return {"id": church_ref.id, **church}


def add_member(church_id: str, email: str) -> dict[str, str]:
    email = email.strip().lower()
    if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email):
        raise ValueError("Enter a valid email address.")
    db = _db()
    church_ref = db.collection("churches").document(church_id)
    if not church_ref.get().exists:
        raise ValueError("Church not found.")

    access_ref = db.collection("user_access").document(_email_key(email))
    current = access_ref.get()
    if current.exists:
        existing = current.to_dict() or {}
        if existing.get("church_id") != church_id:
            raise ValueError("This email already belongs to another church.")
        return {"church_id": church_id, "email": email, "role": existing.get("role", "member")}

    membership = {"church_id": church_id, "email": email, "role": "member"}
    batch = db.batch()
    batch.create(access_ref, membership)
    batch.set(church_ref.collection("members").document(_email_key(email)), membership)
    try:
        batch.commit()
    except Exception as exc:
        current = access_ref.get()
        if current.exists and (current.to_dict() or {}).get("church_id") == church_id:
            return {"church_id": church_id, "email": email, "role": "member"}
        raise ValueError("This email already belongs to another church.") from exc
    return membership


def list_members(church_id: str) -> list[dict[str, str]]:
    documents = (
        _db()
        .collection("churches")
        .document(church_id)
        .collection("members")
        .stream()
    )
    members = []
    for document in documents:
        item = document.to_dict() or {}
        members.append(
            {
                "email": str(item.get("email", "")),
                "role": str(item.get("role", "member")),
            }
        )
    return sorted(members, key=lambda member: member["email"])


def remove_member(church_id: str, email: str) -> bool:
    email = email.strip().lower()
    db = _db()
    church_ref = db.collection("churches").document(church_id)
    church_snapshot = church_ref.get()
    if not church_snapshot.exists:
        return False
    church = church_snapshot.to_dict() or {}
    if email == (church.get("owner_email") or "").strip().lower():
        raise ValueError("The church owner cannot be removed.")

    member_ref = church_ref.collection("members").document(_email_key(email))
    if not member_ref.get().exists:
        return False
    access_ref = db.collection("user_access").document(_email_key(email))
    access_snapshot = access_ref.get()
    batch = db.batch()
    batch.delete(member_ref)
    if access_snapshot.exists and (access_snapshot.to_dict() or {}).get("church_id") == church_id:
        batch.delete(access_ref)
    batch.commit()
    return True


def set_stripe_customer(church_id: str, customer_id: str) -> None:
    _db().collection("churches").document(church_id).update(
        {"stripe_customer_id": customer_id}
    )


def update_subscription(
    church_id: str,
    *,
    customer_id: str | None,
    subscription_id: str | None,
    status: str,
    event_created: int,
) -> None:
    church_ref = _db().collection("churches").document(church_id)
    current = church_ref.get()
    if not current.exists:
        raise ValueError("Church workspace for Stripe event was not found.")
    current_data = current.to_dict() or {}
    if int(current_data.get("stripe_event_created", 0) or 0) > event_created:
        return
    updates: dict[str, Any] = {
        "subscription_status": status,
        "stripe_subscription_id": subscription_id,
        "stripe_event_created": event_created,
    }
    if customer_id:
        updates["stripe_customer_id"] = customer_id
    church_ref.update(updates)
