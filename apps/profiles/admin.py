from django.contrib import admin
from django.utils import timezone

from .models import Availability, CreativeProfile, Package, Service, VerificationDocument


class PackageInline(admin.TabularInline):
    model = Package
    extra = 0


@admin.register(CreativeProfile)
class CreativeProfileAdmin(admin.ModelAdmin):
    list_display = ("workspace", "primary_category", "suburb", "starting_price", "is_featured")
    list_filter = ("primary_category", "is_featured", "accent")
    search_fields = ("workspace__business_name", "headline", "suburb")


@admin.register(Service)
class ServiceAdmin(admin.ModelAdmin):
    list_display = ("title", "workspace", "category")
    list_filter = ("category",)
    inlines = [PackageInline]


@admin.register(Package)
class PackageAdmin(admin.ModelAdmin):
    list_display = ("name", "service", "base_price")


@admin.register(Availability)
class AvailabilityAdmin(admin.ModelAdmin):
    list_display = ("workspace", "date", "status")
    list_filter = ("status",)


@admin.register(VerificationDocument)
class VerificationDocumentAdmin(admin.ModelAdmin):
    """The verification queue — approve/reject uploaded ABN/insurance/WWCC docs."""

    list_display = ("workspace", "doc_type", "status", "reference", "reviewed_by", "created_at")
    list_filter = ("status", "doc_type")
    search_fields = ("workspace__business_name", "reference")
    actions = ["approve_docs", "reject_docs"]

    @admin.action(description="✓ Approve selected documents")
    def approve_docs(self, request, queryset):
        queryset.update(status=VerificationDocument.Status.APPROVED, reviewed_by=request.user)
        self.message_user(request, f"Approved {queryset.count()} document(s).")

    @admin.action(description="✕ Reject selected documents")
    def reject_docs(self, request, queryset):
        queryset.update(status=VerificationDocument.Status.REJECTED, reviewed_by=request.user)
