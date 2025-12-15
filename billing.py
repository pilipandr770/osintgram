"""Stripe billing blueprint (subscriptions).

Env vars:
- STRIPE_SECRET_KEY
- STRIPE_PUBLISHABLE_KEY
- STRIPE_WEBHOOK_SECRET
- STRIPE_PRICE_ID (subscription price)
- STRIPE_SUCCESS_URL (optional)
- STRIPE_CANCEL_URL (optional)

SaaS gating controlled by SAAS_REQUIRE_SUBSCRIPTION=true/false.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone as dt_timezone

from flask import Blueprint, current_app, flash, redirect, render_template, request, url_for
from flask_login import login_required, current_user

from database import db
from models import BillingAccount, BillingEvent

try:
    import stripe  # type: ignore
except Exception:  # pragma: no cover
    stripe = None


billing_bp = Blueprint("billing", __name__, url_prefix="/billing")


def _get_stripe():
    if stripe is None:
        raise RuntimeError("stripe SDK is not installed")

    secret = (os.environ.get("STRIPE_SECRET_KEY") or "").strip()
    if not secret:
        raise RuntimeError("STRIPE_SECRET_KEY is not set")

    stripe.api_key = secret
    return stripe


def _absolute_url(path: str) -> str:
    # request.url_root already ends with '/'
    root = request.url_root.rstrip("/")
    if not path.startswith("/"):
        path = "/" + path
    return root + path


def _get_or_create_billing_account(user_id: str) -> BillingAccount:
    acct = BillingAccount.query.filter_by(user_id=user_id).first()
    if acct:
        return acct
    acct = BillingAccount(user_id=user_id, subscription_status="none")
    db.session.add(acct)
    db.session.commit()
    return acct


def _upsert_from_subscription(user_id: str | None, subscription: dict, price_id: str | None = None):
    if not user_id:
        return

    acct = _get_or_create_billing_account(user_id)
    acct.stripe_customer_id = subscription.get("customer")
    acct.stripe_subscription_id = subscription.get("id")
    acct.subscription_status = subscription.get("status") or acct.subscription_status
    acct.cancel_at_period_end = bool(subscription.get("cancel_at_period_end") or False)

    cpe = subscription.get("current_period_end")
    if cpe:
        acct.current_period_end = datetime.fromtimestamp(int(cpe), tz=dt_timezone.utc).replace(tzinfo=None)

    if price_id:
        acct.price_id = price_id

    db.session.commit()


@billing_bp.route("", methods=["GET"])
@login_required
def billing_home():
    acct = BillingAccount.query.filter_by(user_id=current_user.id).first()

    publishable_key = (os.environ.get("STRIPE_PUBLISHABLE_KEY") or "").strip()
    price_id = (os.environ.get("STRIPE_PRICE_ID") or "").strip()

    next_path = request.args.get("next")

    return render_template(
        "billing.html",
        billing_account=acct,
        stripe_publishable_key=publishable_key,
        stripe_price_id=price_id,
        next_path=next_path,
    )


@billing_bp.route("/checkout", methods=["POST"])
@login_required
def create_checkout_session():
    price_id = (os.environ.get("STRIPE_PRICE_ID") or "").strip()
    if not price_id:
        flash("Stripe не налаштований: відсутній STRIPE_PRICE_ID", "error")
        return redirect(url_for("billing.billing_home"))

    try:
        st = _get_stripe()
    except Exception as e:
        flash(f"Stripe не готовий: {e}", "error")
        return redirect(url_for("billing.billing_home"))

    acct = _get_or_create_billing_account(current_user.id)

    success_url = (os.environ.get("STRIPE_SUCCESS_URL") or "").strip() or _absolute_url("/billing")
    cancel_url = (os.environ.get("STRIPE_CANCEL_URL") or "").strip() or _absolute_url("/billing")

    # Preserve optional redirect target after successful payment
    next_path = (request.form.get("next") or request.args.get("next") or "").strip()

    params: dict = {
        "mode": "subscription",
        "line_items": [{"price": price_id, "quantity": 1}],
        "success_url": success_url,
        "cancel_url": cancel_url,
        "client_reference_id": current_user.id,
        "metadata": {"user_id": current_user.id, "next": next_path},
        "allow_promotion_codes": True,
    }

    if acct.stripe_customer_id:
        params["customer"] = acct.stripe_customer_id
    else:
        params["customer_email"] = current_user.email

    try:
        session = st.checkout.Session.create(**params)
    except Exception as e:
        flash(f"Не вдалося створити оплату: {e}", "error")
        return redirect(url_for("billing.billing_home"))

    return redirect(session.url, code=303)


@billing_bp.route("/portal", methods=["POST"])
@login_required
def create_portal_session():
    try:
        st = _get_stripe()
    except Exception as e:
        flash(f"Stripe не готовий: {e}", "error")
        return redirect(url_for("billing.billing_home"))

    acct = BillingAccount.query.filter_by(user_id=current_user.id).first()
    if not acct or not acct.stripe_customer_id:
        flash("Спочатку оформіть підписку.", "warning")
        return redirect(url_for("billing.billing_home"))

    return_url = _absolute_url("/billing")

    try:
        session = st.billing_portal.Session.create(customer=acct.stripe_customer_id, return_url=return_url)
    except Exception as e:
        flash(f"Не вдалося відкрити кабінет Stripe: {e}", "error")
        return redirect(url_for("billing.billing_home"))

    return redirect(session.url, code=303)


@billing_bp.route("/webhook", methods=["POST"])
def stripe_webhook():
    webhook_secret = (os.environ.get("STRIPE_WEBHOOK_SECRET") or "").strip()
    if not webhook_secret:
        return ("missing STRIPE_WEBHOOK_SECRET", 400)

    if stripe is None:
        return ("stripe SDK not installed", 500)

    payload = request.get_data(as_text=False)
    sig_header = request.headers.get("Stripe-Signature", "")

    try:
        event = stripe.Webhook.construct_event(payload=payload, sig_header=sig_header, secret=webhook_secret)
    except Exception as e:
        return (f"invalid signature: {e}", 400)

    event_id = event.get("id")
    event_type = event.get("type")

    # Idempotency guard
    if event_id:
        existing = BillingEvent.query.filter_by(stripe_event_id=event_id).first()
        if existing:
            return ("ok", 200)

    user_id = None

    try:
        data_obj = (event.get("data") or {}).get("object") or {}

        if event_type == "checkout.session.completed":
            user_id = (data_obj.get("metadata") or {}).get("user_id") or data_obj.get("client_reference_id")
            customer_id = data_obj.get("customer")
            subscription_id = data_obj.get("subscription")

            if user_id:
                acct = _get_or_create_billing_account(user_id)
                acct.stripe_customer_id = customer_id
                acct.stripe_subscription_id = subscription_id
                acct.subscription_status = "active"  # will be corrected on subscription.updated
                db.session.commit()

        elif event_type in {"customer.subscription.created", "customer.subscription.updated", "customer.subscription.deleted"}:
            sub = data_obj
            user_id = (sub.get("metadata") or {}).get("user_id")

            # Try to infer user_id by subscription id
            if not user_id:
                sub_id = sub.get("id")
                if sub_id:
                    acct = BillingAccount.query.filter_by(stripe_subscription_id=sub_id).first()
                    if acct:
                        user_id = acct.user_id

            # Capture price_id from subscription items if present
            price_id = None
            try:
                items = (((sub.get("items") or {}).get("data")) or [])
                if items and (items[0].get("price") or {}).get("id"):
                    price_id = (items[0].get("price") or {}).get("id")
            except Exception:
                price_id = None

            _upsert_from_subscription(user_id, sub, price_id=price_id)

        # Record event
        if event_id:
            db.session.add(
                BillingEvent(
                    user_id=user_id,
                    stripe_event_id=event_id,
                    event_type=event_type,
                    payload=event,
                )
            )
            db.session.commit()

    except Exception as e:
        db.session.rollback()
        current_app.logger.exception("Stripe webhook processing failed")
        return (f"error: {e}", 500)

    return ("ok", 200)
