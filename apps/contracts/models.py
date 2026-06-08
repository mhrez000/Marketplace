from django.db import models

from apps.bookings.models import Booking
from apps.core.models import TimeStampedModel


class ContractTemplate(TimeStampedModel):
    class Type(models.TextChoices):
        WEDDING = "wedding", "Wedding"
        EVENTS = "events", "Events"
        REAL_ESTATE = "real_estate", "Real estate"
        COMMERCIAL = "commercial", "Commercial"
        MODEL_RELEASE = "model_release", "Model release"

    name = models.CharField(max_length=120)
    contract_type = models.CharField(max_length=16, choices=Type.choices, default=Type.WEDDING)
    body = models.TextField(help_text="May contain {{client_name}}, {{business_name}}, {{event_date}}, {{total}}")

    def __str__(self):
        return self.name


class Contract(TimeStampedModel):
    """A booking's contract with click-to-sign + audit log (build plan §8.9)."""

    booking = models.OneToOneField(Booking, on_delete=models.CASCADE, related_name="contract")
    template = models.ForeignKey(ContractTemplate, on_delete=models.SET_NULL, null=True, blank=True)
    title = models.CharField(max_length=180)
    body = models.TextField()

    client_signature_name = models.CharField(max_length=160, blank=True)
    signed_by_client_at = models.DateTimeField(null=True, blank=True)
    creative_signature_name = models.CharField(max_length=160, blank=True)
    signed_by_creative_at = models.DateTimeField(null=True, blank=True)
    # Audit: list of {"party","name","ip","ua","at"}
    audit = models.JSONField(default=list, blank=True)

    def __str__(self):
        return self.title

    @property
    def is_signed(self):
        return bool(self.signed_by_client_at and self.signed_by_creative_at)

    @property
    def is_client_signed(self):
        return bool(self.signed_by_client_at)
