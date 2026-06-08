from django.contrib import admin

from .models import Asset, Gallery


class AssetInline(admin.TabularInline):
    model = Asset
    extra = 0


@admin.register(Gallery)
class GalleryAdmin(admin.ModelAdmin):
    list_display = ("title", "booking", "gallery_type", "is_delivered", "delivered_at")
    list_filter = ("gallery_type", "is_delivered")
    inlines = [AssetInline]
