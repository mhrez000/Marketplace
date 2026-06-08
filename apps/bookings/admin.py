from django.contrib import admin

from .models import Booking, CalendarEvent


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
