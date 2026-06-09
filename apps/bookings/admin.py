from django.contrib import admin
from django.utils import timezone

from .models import Booking, CalendarEvent, Dispute


@admin.register(Booking)
class BookingAdmin(admin.ModelAdmin):
    list_display = ("title", "workspace", "client", "status", "event_date", "total")
    list_filter = ("status", "workspace")
    search_fields = ("title", "client__email", "workspace__business_name")
    readonly_fields = ("id",)


@admin.register(CalendarEvent)
class CalendarEventAdmin(admin.ModelAdmin):
    list_display = ("title", "workspace", "event_type", "start", "assignee")
    list_filter = ("event_type",)


@admin.register(Dispute)
class DisputeAdmin(admin.ModelAdmin):
    """The dispute review queue."""

    list_display = ("booking", "raised_by", "raised_by_role", "reason", "status", "created_at")
    list_filter = ("status", "reason")
    search_fields = ("booking__title", "raised_by__email", "detail")
    actions = ["mark_under_review", "resolve", "reject"]

    @admin.action(description="Mark selected as under review")
    def mark_under_review(self, request, queryset):
        queryset.update(status=Dispute.Status.UNDER_REVIEW)

    @admin.action(description="✓ Resolve selected disputes")
    def resolve(self, request, queryset):
        from .services import resolve_dispute
        for d in queryset:
            resolve_dispute(d, resolved_by=request.user, status=Dispute.Status.RESOLVED,
                            resolution=d.resolution or "Resolved by platform.")
        self.message_user(request, f"Resolved {queryset.count()} dispute(s).")

    @admin.action(description="✕ Reject selected disputes")
    def reject(self, request, queryset):
        from .services import resolve_dispute
        for d in queryset:
            resolve_dispute(d, resolved_by=request.user, status=Dispute.Status.REJECTED,
                            resolution=d.resolution or "Rejected after review.")
