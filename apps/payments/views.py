"""Stripe webhook — the source of truth for real payments.

Inert until STRIPE_WEBHOOK_SECRET is set and the `stripe` package is installed.
On payment_intent.succeeded it marks the invoice paid and advances the booking
via the same settle_invoice() the test gateway uses. Idempotent (Stripe retries).
"""
from django.conf import settings
from django.http import HttpResponse, HttpResponseBadRequest
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt

from .models import Invoice, Payment


@csrf_exempt
def stripe_webhook(request):
    if not settings.STRIPE_WEBHOOK_SECRET:
        return HttpResponse(status=503)  # Stripe not configured

    payload = request.body
    sig = request.META.get("HTTP_STRIPE_SIGNATURE", "")
    try:
        import stripe
        event = stripe.Webhook.construct_event(payload, sig, settings.STRIPE_WEBHOOK_SECRET)
    except Exception:
        return HttpResponseBadRequest("Invalid signature")

    if event["type"] == "payment_intent.succeeded":
        intent = event["data"]["object"]
        ref = intent["id"]
        invoice_id = intent.get("metadata", {}).get("invoice_id")
        invoice = Invoice.objects.filter(id=invoice_id).first()
        if invoice:
            # Idempotency: ignore if we've already settled this PaymentIntent.
            already = Payment.objects.filter(provider_ref=ref, status=Payment.Status.SUCCEEDED).exists()
            if not already:
                Payment.objects.filter(invoice=invoice, provider_ref=ref).update(
                    status=Payment.Status.SUCCEEDED, paid_at=timezone.now())
                from apps.bookings.services import settle_invoice
                settle_invoice(invoice)

    return HttpResponse(status=200)
