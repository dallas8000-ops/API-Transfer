from django.urls import path

from .views import (
    AccountView,
    BillingPortalView,
    CreateCheckoutSessionView,
    PaystackWebhookView,
    PlansView,
    StripeWebhookView,
    SubscriptionStatusView,
)

urlpatterns = [
    path("account", AccountView.as_view(), name="billing-account"),
    path("plans", PlansView.as_view(), name="billing-plans"),
    path("checkout", CreateCheckoutSessionView.as_view(), name="billing-checkout"),
    path("portal", BillingPortalView.as_view(), name="billing-portal"),
    path("subscription", SubscriptionStatusView.as_view(), name="billing-subscription"),
    path("webhook", StripeWebhookView.as_view(), name="billing-webhook"),
    path("webhook/paystack", PaystackWebhookView.as_view(), name="billing-paystack-webhook"),
]
