from django.contrib import admin

from .models import Deliverable, DeliverableTemplate


@admin.register(DeliverableTemplate)
class DeliverableTemplateAdmin(admin.ModelAdmin):
    list_display = ("label", "workspace", "day_offset", "is_client_facing", "sort_order")
    search_fields = ("label", "workspace__business_name")


@admin.register(Deliverable)
class DeliverableAdmin(admin.ModelAdmin):
    list_display = ("title", "booking", "workspace", "due_date", "status", "is_client_facing")
    list_filter = ("status", "kind", "is_client_facing")
    search_fields = ("title", "booking__title", "workspace__business_name")
    date_hierarchy = "due_date"
