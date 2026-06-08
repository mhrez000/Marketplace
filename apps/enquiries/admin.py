from django.contrib import admin

from .models import Enquiry, Quote


@admin.register(Enquiry)
class EnquiryAdmin(admin.ModelAdmin):
    list_display = ("client", "workspace", "event_type", "event_date", "status", "created_at")
    list_filter = ("status", "event_type")
    search_fields = ("client__email", "workspace__business_name")


@admin.register(Quote)
class QuoteAdmin(admin.ModelAdmin):
    list_display = ("title", "enquiry", "total", "deposit_amount", "status")
    list_filter = ("status",)
