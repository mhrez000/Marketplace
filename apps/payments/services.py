"""Payment gateway abstraction.

The rest of the app calls `charge_invoice()` and never touches a vendor SDK
directly (build plan §8 rule). Today it uses a TEST gateway that simulates a
successful charge so the end-to-end booking flow works without Stripe keys.
Swapping in Stripe later means implementing `StripeGateway` and flipping
`get_gateway()` — callers don't change.
"""
import uuid

from django.utils import timezone

from .models import Payment


class TestGateway:
    """Simulates a payment processor. Always succeeds. Clearly marked test-mode."""

    provider = "test"

    def charge(self, invoice, *, save=True):
        payment = Payment(
            invoice=invoice,
            provider=self.provider,
            provider_ref=f"test_{uuid.uuid4().hex[:18]}",
            amount=invoice.amount,
            status=Payment.Status.SUCCEEDED,
            paid_at=timezone.now(),
        )
        if save:
            payment.save()  # platform_fee computed in Payment.save()
        return payment


class StripeGateway:
    """Real Stripe (drop-in). Inert until STRIPE_SECRET_KEY is set and the
    `stripe` package is installed (`pip install stripe`).

    Unlike the test gateway, a Stripe charge settles ASYNCHRONOUSLY: this creates
    a PaymentIntent and returns a PENDING Payment. The booking only advances when
    Stripe calls our webhook (apps/payments/views.stripe_webhook) with
    payment_intent.succeeded — never from the client request (build plan §10).
    """

    provider = "stripe"

    def __init__(self):
        import stripe  # lazy: only required when Stripe is actually enabled
        from django.conf import settings
        stripe.api_key = settings.STRIPE_SECRET_KEY
        self._stripe = stripe

    def charge(self, invoice, *, save=True):
        intent = self._stripe.PaymentIntent.create(
            amount=int(invoice.amount * 100),  # cents
            currency="aud",
            metadata={"invoice_id": invoice.id, "booking_id": str(invoice.booking_id)},
            automatic_payment_methods={"enabled": True},
        )
        payment = Payment(
            invoice=invoice, provider=self.provider, provider_ref=intent.id,
            amount=invoice.amount, status=Payment.Status.PENDING,
        )
        if save:
            payment.save()
        return payment


def get_gateway():
    """Use Stripe when configured, else the built-in test gateway."""
    from django.conf import settings
    if getattr(settings, "STRIPE_SECRET_KEY", ""):
        return StripeGateway()
    return TestGateway()


# ── Refund policy ────────────────────────────────────────────────────────────
# Standard creative policy: the deposit is NON-REFUNDABLE; anything paid beyond
# the deposit is refunded on a sliding scale by how close the cancellation is to
# the event date. (Starting point — validate with a lawyer per the plan.)
REFUND_TIERS = [
    (30, "1.0", "30+ days before the event"),
    (14, "0.5", "14–29 days before the event"),
    (0, "0.0", "less than 14 days before the event"),
]


def compute_refund(booking):
    """Work out what a client would get back if they cancelled now.

    Returns a dict: paid, deposit_forfeited, refundable, forfeited, tier_label.
    """
    from decimal import Decimal

    from django.db.models import Sum
    from django.utils import timezone

    from .models import Invoice, Payment

    paid = Payment.objects.filter(
        invoice__booking=booking, status=Payment.Status.SUCCEEDED
    ).aggregate(t=Sum("amount"))["t"] or Decimal("0")

    deposit_paid = booking.invoices.filter(
        invoice_type=Invoice.Type.DEPOSIT, status=Invoice.Status.PAID).exists()
    deposit = booking.deposit_amount if deposit_paid else Decimal("0")
    beyond_deposit = max(Decimal("0"), paid - deposit)

    days = (booking.event_date - timezone.now().date()).days if booking.event_date else -1
    pct, tier_label = Decimal("0"), "after the event"
    for threshold, factor, label in REFUND_TIERS:
        if days >= threshold:
            pct, tier_label = Decimal(factor), label
            break

    refundable = (beyond_deposit * pct).quantize(Decimal("0.01"))
    return {
        "paid": paid,
        "deposit_forfeited": deposit,
        "refundable": refundable,
        "forfeited": (paid - refundable).quantize(Decimal("0.01")),
        "tier_label": tier_label,
        "days": days,
    }


def mark_overdue_invoices():
    """Flip unpaid invoices past their due date to OVERDUE (idempotent)."""
    from datetime import date

    from django.utils import timezone

    from .models import Invoice
    today = timezone.now().date()
    return Invoice.objects.filter(
        status=Invoice.Status.SENT, due_date__lt=today, due_date__isnull=False
    ).update(status=Invoice.Status.OVERDUE)


def payment_reminders():
    """Remind clients (and creatives) about invoices due soon or overdue.
    Throttled to ~once/20h per invoice via Invoice.reminded_at."""
    from datetime import timedelta

    from django.utils import timezone

    from apps.notifications.models import dispatch, notify

    from .models import Invoice
    now = timezone.now()
    today = now.date()
    count = 0
    unpaid = Invoice.objects.filter(
        status__in=[Invoice.Status.SENT, Invoice.Status.OVERDUE], due_date__isnull=False
    ).select_related("booking", "booking__client", "booking__workspace")

    for inv in unpaid:
        if inv.due_date > today + timedelta(days=3):
            continue
        if inv.reminded_at and (now - inv.reminded_at) < timedelta(hours=20):
            continue
        label = inv.get_invoice_type_display()
        booking = inv.booking
        if inv.due_date < today:
            dispatch("payment_overdue", booking.client,
                     verb=f"Your {label.lower()} of ${inv.amount:.0f} for {booking.title} is overdue.",
                     url=f"/portal/booking/{booking.id}/")
            notify(booking.workspace.owner, f"{booking.client.email}'s {label.lower()} (${inv.amount:.0f}) is overdue",
                   url="/app/bookings/", icon="alert")
        else:
            dispatch("payment_reminder", booking.client,
                     verb=f"Your {label.lower()} of ${inv.amount:.0f} is due {inv.due_date:%d %b}.",
                     url=f"/portal/booking/{booking.id}/")
        inv.reminded_at = now
        inv.save(update_fields=["reminded_at", "updated_at"])
        count += 1
    return count


def charge_invoice(invoice):
    """Charge an invoice, mark it paid, and return the Payment.

    NOTE: with real Stripe this is driven by a verified webhook, never the
    client request (build plan §10). The test gateway settles synchronously.
    """
    from .models import Invoice

    gateway = get_gateway()
    payment = gateway.charge(invoice)
    if payment.status == Payment.Status.SUCCEEDED:
        invoice.status = Invoice.Status.PAID
        invoice.save(update_fields=["status", "updated_at"])
    return payment
