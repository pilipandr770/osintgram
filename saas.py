"""SaaS helpers: subscription gating and admin checks."""

from __future__ import annotations

import os
from datetime import datetime
from functools import wraps
from typing import Optional

from flask import redirect, url_for, flash, request
from flask_login import current_user

from models import BillingAccount


def _env_truthy(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return str(raw).strip().lower() in {"1", "true", "yes", "y", "on"}


def saas_require_subscription() -> bool:
    return _env_truthy("SAAS_REQUIRE_SUBSCRIPTION", default=False)


def get_admin_emails() -> set[str]:
    raw = (os.environ.get("ADMIN_EMAILS") or "").strip()
    if not raw:
        return set()
    parts = [p.strip().lower() for p in raw.split(",")]
    return {p for p in parts if p}


def is_admin_email(email: Optional[str]) -> bool:
    if not email:
        return False
    return email.strip().lower() in get_admin_emails()


def get_billing_account(user_id: str) -> Optional[BillingAccount]:
    return BillingAccount.query.filter_by(user_id=user_id).first()


def is_subscription_active(user_id: str, now: Optional[datetime] = None) -> bool:
    acct = get_billing_account(user_id)
    if not acct:
        return False

    status = (acct.subscription_status or "").lower().strip()
    if status not in {"active", "trialing"}:
        return False

    if acct.current_period_end is None:
        return True

    now = now or datetime.utcnow()
    return acct.current_period_end >= now


def subscription_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if not current_user.is_authenticated:
            return redirect(url_for("auth.login", next=request.path))

        if not saas_require_subscription():
            return f(*args, **kwargs)

        if is_admin_email(getattr(current_user, "email", None)):
            return f(*args, **kwargs)

        if is_subscription_active(current_user.id):
            return f(*args, **kwargs)

        flash("Потрібна активна підписка для доступу до цієї функції.", "warning")
        return redirect(url_for("billing.billing_home", next=request.path))

    return wrapper


def admin_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if not current_user.is_authenticated:
            return redirect(url_for("auth.login", next=request.path))

        if not is_admin_email(getattr(current_user, "email", None)):
            flash("Доступ заборонено.", "error")
            return redirect(url_for("dashboard"))

        return f(*args, **kwargs)

    return wrapper
