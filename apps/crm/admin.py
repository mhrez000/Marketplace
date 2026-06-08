from django.contrib import admin

from .models import Client, Task


@admin.register(Client)
class ClientAdmin(admin.ModelAdmin):
    list_display = ("name", "workspace", "email", "lead_source")
    search_fields = ("name", "email")


@admin.register(Task)
class TaskAdmin(admin.ModelAdmin):
    list_display = ("title", "workspace", "due_date", "status")
    list_filter = ("status",)
