from django.contrib import admin

from .models import Deliverable


@admin.register(Deliverable)
class DeliverableAdmin(admin.ModelAdmin):
    list_display = ("title", "booking", "workspace", "due_date", "status", "is_client_facing")
    list_filter = ("status", "kind", "is_client_facing")
    search_fields = ("title", "booking__title", "workspace__business_name")
    date_hierarchy = "due_date"
