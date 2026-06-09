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


def get_gateway():
    # When STRIPE_SECRET_KEY is configured, return StripeGateway() here instead.
    return TestGateway()


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

    from apps.notifications.models import notify

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
            notify(booking.client, f"Payment overdue — {label} ${inv.amount:.0f} for {booking.title}",
                   url=f"/portal/booking/{booking.id}/", icon="alert", email=True)
            notify(booking.workspace.owner, f"{booking.client.email}'s {label.lower()} (${inv.amount:.0f}) is overdue",
                   url="/app/bookings/", icon="alert")
        else:
            notify(booking.client, f"Reminder — {label} ${inv.amount:.0f} due {inv.due_date:%d %b}",
                   url=f"/portal/booking/{booking.id}/", icon="clock", email=True)
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
