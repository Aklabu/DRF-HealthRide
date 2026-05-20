from django.urls import path
from .views import (
    StripeConnectView,
    StripeStatusView,
    StripeWebhookView,
    BankAccountView,
    InvoiceListCreateView,
    InvoiceDetailView,
    InvoiceStatusUpdateView,
    InvoiceTemplateView,
    LateFeeConfigView,
)

urlpatterns = [
    # Stripe Connect
    path('stripe/connect/', StripeConnectView.as_view(), name='stripe-connect'),
    path('stripe/status/', StripeStatusView.as_view(), name='stripe-status'),
    path('stripe/webhook/', StripeWebhookView.as_view(), name='stripe-webhook'),

    # Bank account
    path('bank-account/', BankAccountView.as_view(), name='bank-account'),

    # Invoices
    path('invoices/', InvoiceListCreateView.as_view(), name='invoice-list-create'),
    path('invoices/<uuid:id>/', InvoiceDetailView.as_view(), name='invoice-detail'),
    path('invoices/<uuid:id>/status/', InvoiceStatusUpdateView.as_view(), name='invoice-status'),

    # Invoice template
    path('invoice-template/', InvoiceTemplateView.as_view(), name='invoice-template'),

    # Late fee config
    path('late-fee-config/', LateFeeConfigView.as_view(), name='late-fee-config'),
]
