from django.contrib import admin
from django.utils import timezone

from .models import Member, Workspace


class MemberInline(admin.TabularInline):
    model = Member
    extra = 0


@admin.register(Workspace)
class WorkspaceAdmin(admin.ModelAdmin):
    list_display = ("business_name", "type", "owner", "is_verified", "is_published", "created_at")
    list_filter = ("type", "is_published", "verified_at")
    search_fields = ("business_name", "owner__email", "abn")
    prepopulated_fields = {"slug": ("business_name",)}
    inlines = [MemberInline]
    actions = ["approve_and_publish", "unpublish"]

    @admin.display(boolean=True, description="Verified")
    def is_verified(self, obj):
        return obj.is_verified

    @admin.action(description="✓ Approve, verify & publish selected workspaces")
    def approve_and_publish(self, request, queryset):
        n = 0
        for ws in queryset:
            ws.verified_at = timezone.now()
            ws.is_published = True
            ws.save(update_fields=["verified_at", "is_published", "updated_at"])
            n += 1
        self.message_user(request, f"Approved & published {n} workspace(s).")

    @admin.action(description="Unpublish selected workspaces")
    def unpublish(self, request, queryset):
        queryset.update(is_published=False)


@admin.register(Member)
class MemberAdmin(admin.ModelAdmin):
    list_display = ("user", "workspace", "role")
    list_filter = ("role",)
    search_fields = ("user__email", "workspace__business_name")
