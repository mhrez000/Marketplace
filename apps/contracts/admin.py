from django.contrib import admin

from .models import Contract, ContractTemplate


@admin.register(ContractTemplate)
class ContractTemplateAdmin(admin.ModelAdmin):
    list_display = ("name", "contract_type")
    list_filter = ("contract_type",)


@admin.register(Contract)
class ContractAdmin(admin.ModelAdmin):
    list_display = ("title", "booking", "is_signed")
    readonly_fields = ("audit",)
