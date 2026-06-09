from django.contrib import admin

from .models import Broadcast, Notification, NotificationPreference


@admin.register(Broadcast)
class BroadcastAdmin(admin.ModelAdmin):
    list_display = ("title", "audience", "send_email", "recipient_count", "sent_at", "sender")
    list_filter = ("audience", "send_email")
    search_fields = ("title", "body")


@admin.register(NotificationPreference)
class NotificationPreferenceAdmin(admin.ModelAdmin):
    list_display = ("user", "email_reminders", "email_marketing", "sms_enabled")


@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    list_display = ("user", "verb", "is_read", "created_at")
    list_filter = ("is_read",)
