from django.urls import path
from orders.apis.views import (
    CreatePaymentIntentView,
    ConfirmOrderView,
    OrderDetailView,
    StripeWebhookView,
)

urlpatterns = [
    # Payment Intent Creation
    path(
        'orders/create-payment-intent/',
        CreatePaymentIntentView.as_view(),
        name='create-payment-intent'
    ),

    # Order Confirmation
    path(
        'orders/confirm/',
        ConfirmOrderView.as_view(),
        name='confirm-order'
    ),

    # Order Detail
    path(
        'orders/<str:order_number>/',
        OrderDetailView.as_view(),
        name='order-detail'
    ),

    # Stripe Webhook
    path(
        'orders/webhook/',
        StripeWebhookView.as_view(),
        name='stripe-webhook'
    ),
]