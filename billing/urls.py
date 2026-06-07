from django.urls import path

from .views import (
    BillingPortalView,
    CreateCheckoutSessionView,
    PlansView,
    StripeWebhookView,
    SubscriptionStatusView,
)

urlpatterns = [
    path("plans", PlansView.as_view(), name="billing-plans"),
    path("checkout", CreateCheckoutSessionView.as_view(), name="billing-checkout"),
    path("portal", BillingPortalView.as_view(), name="billing-portal"),
    path("subscription", SubscriptionStatusView.as_view(), name="billing-subscription"),
    path("webhook", StripeWebhookView.as_view(), name="billing-webhook"),
]
