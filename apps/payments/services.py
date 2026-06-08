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
