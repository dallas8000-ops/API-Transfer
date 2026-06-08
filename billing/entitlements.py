from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

from django.db.models import Sum
from django.utils import timezone
from rest_framework.response import Response

from .models import Customer, UsageEvent, Workspace, WorkspaceMember
from .stripe_config import PLAN_BY_SLUG


ACTION_TO_LIMIT = {
    "migration": "migrationsPerMonth",
    "live_deployment": "liveDeployments",
}


@dataclass(frozen=True)
class EntitlementContext:
    workspace: Workspace
    customer: Customer
    plan_slug: str

    @property
    def plan(self):
        return PLAN_BY_SLUG.get(self.plan_slug) or PLAN_BY_SLUG["free"]


def account_email_from_request(request) -> str:
    email = request.headers.get("X-Account-Email", "").strip()
    if not email:
        email = str(request.data.get("accountEmail") or request.data.get("requestedBy") or "").strip()
    return email if "@" in email else "demo@apitransfer.local"


def get_or_create_workspace(email: str) -> EntitlementContext:
    customer, _ = Customer.objects.get_or_create(email=email)
    workspace = customer.default_workspace
    if workspace is None:
        workspace = Workspace.objects.create(name=f"{email} workspace", owner_email=email)
        WorkspaceMember.objects.get_or_create(
            workspace=workspace, email=email, defaults={"role": "owner"}
        )
        customer.default_workspace = workspace
        customer.save(update_fields=["default_workspace"])

    active_sub = (
        customer.subscriptions.filter(status__in=["active", "trialing"])
        .order_by("-created_at")
        .first()
    )
    plan_slug = active_sub.plan_slug if active_sub else workspace.plan_slug or "free"
    if workspace.plan_slug != plan_slug:
        workspace.plan_slug = plan_slug
        workspace.save(update_fields=["plan_slug"])
    return EntitlementContext(workspace=workspace, customer=customer, plan_slug=plan_slug)


def usage_for_month(workspace: Workspace, kind: str) -> int:
    since = timezone.now() - timedelta(days=30)
    total = (
        UsageEvent.objects.filter(workspace=workspace, kind=kind, created_at__gte=since)
        .aggregate(total=Sum("quantity"))
        .get("total")
    )
    return int(total or 0)


def check_limit(ctx: EntitlementContext, action: str) -> Response | None:
    limit_key = ACTION_TO_LIMIT.get(action)
    if not limit_key:
        return None
    limit = ctx.plan.limits.get(limit_key)
    if limit is None:
        return None
    used = usage_for_month(ctx.workspace, action)
    if used < limit:
        return None
    return Response(
        {
            "error": f"{ctx.plan.name} plan limit reached for {limit_key}.",
            "planSlug": ctx.plan_slug,
            "limit": limit,
            "used": used,
            "upgradeRecommended": True,
        },
        status=402,
    )


def record_usage(ctx: EntitlementContext, action: str, reference: str = "") -> None:
    UsageEvent.objects.create(workspace=ctx.workspace, kind=action, reference=reference)


def entitlements_payload(ctx: EntitlementContext) -> dict:
    usage = {
        "migrationsThisMonth": usage_for_month(ctx.workspace, "migration"),
        "liveDeploymentsThisMonth": usage_for_month(ctx.workspace, "live_deployment"),
    }
    return {
        "workspace": {
            "id": ctx.workspace.id,
            "name": ctx.workspace.name,
            "ownerEmail": ctx.workspace.owner_email,
        },
        "accountEmail": ctx.customer.email,
        "planSlug": ctx.plan_slug,
        "plan": ctx.plan.to_public_dict(),
        "usage": usage,
    }
