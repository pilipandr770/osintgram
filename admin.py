"""Minimal admin pages for SaaS operations."""

from __future__ import annotations

from flask import Blueprint, render_template

from database import db
from models import User, BillingAccount
from saas import admin_required


admin_bp = Blueprint("admin", __name__, url_prefix="/admin")


@admin_bp.route("", methods=["GET"])
@admin_required
def admin_home():
    # left join users -> billing
    rows = (
        db.session.query(User, BillingAccount)
        .outerjoin(BillingAccount, BillingAccount.user_id == User.id)
        .order_by(User.created_at.desc())
        .limit(500)
        .all()
    )
    return render_template("admin.html", rows=rows)
