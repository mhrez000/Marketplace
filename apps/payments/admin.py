from django.contrib import admin

from .models import Invoice, Payment, Subscription


@admin.register(Invoice)
class InvoiceAdmin(admin.ModelAdmin):
    list_display = ("invoice_type", "booking", "amount", "status", "due_date")
    list_filter = ("status", "invoice_type")


@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    list_display = ("invoice", "amount", "platform_fee", "provider", "status", "paid_at")
    list_filter = ("status", "provider")


@admin.register(Subscription)
class SubscriptionAdmin(admin.ModelAdmin):
    list_display = ("workspace", "plan", "status", "seats", "period_end")
    list_filter = ("plan", "status")
