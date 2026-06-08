from django.contrib import admin

from .models import Review


@admin.register(Review)
class ReviewAdmin(admin.ModelAdmin):
    list_display = ("workspace", "client", "rating", "verified", "created_at")
    list_filter = ("rating", "verified")
