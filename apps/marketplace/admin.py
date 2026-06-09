from django.contrib import admin

from .models import Favourite


@admin.register(Favourite)
class FavouriteAdmin(admin.ModelAdmin):
    list_display = ("client", "workspace", "created_at")
    search_fields = ("client__email", "workspace__business_name")
