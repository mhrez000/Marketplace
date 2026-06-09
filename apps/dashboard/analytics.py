"""Creative analytics (build plan §17) — computed from the existing spine
(enquiries, quotes, bookings, payments, packages, clients). No new event log."""
from decimal import Decimal

from django.db.models import Avg, Count, Sum
from django.utils import timezone

from apps.bookings.models import Booking
from apps.crm.models import Client
from apps.enquiries.models import Enquiry, Quote
from apps.payments.models import Invoice, Payment
from apps.profiles.models import Package

CONFIRMED = [Booking.Status.CONFIRMED, Booking.Status.PLANNING, Booking.Status.SHOOT_COMPLETED,
             Booking.Status.EDITING, Booking.Status.DELIVERED, Booking.Status.FINAL_PAID,
             Booking.Status.COMPLETED, Booking.Status.ARCHIVED]


def _pct(n, d):
    return round(n / d * 100) if d else 0


def _month_label(y, m):
    return ["", "Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"][m]


def workspace_analytics(ws):
    enquiries = Enquiry.objects.filter(workspace=ws)
    quotes = Quote.objects.filter(enquiry__workspace=ws).exclude(status=Quote.Status.DRAFT)
    bookings = Booking.objects.filter(workspace=ws)
    confirmed = bookings.filter(status__in=CONFIRMED)

    n_enq = enquiries.count()
    n_quote = quotes.count()
    n_book = bookings.count()
    n_conf = confirmed.count()

    funnel = [
        {"label": "Enquiries", "value": n_enq, "rate": None},
        {"label": "Quotes sent", "value": n_quote, "rate": _pct(n_quote, n_enq)},
        {"label": "Bookings", "value": n_book, "rate": _pct(n_book, n_quote)},
        {"label": "Confirmed", "value": n_conf, "rate": _pct(n_conf, n_book)},
    ]

    paid = Payment.objects.filter(invoice__booking__workspace=ws,
                                  status=Payment.Status.SUCCEEDED).aggregate(s=Sum("amount"))["s"] or Decimal("0")
    outstanding = Invoice.objects.filter(
        booking__workspace=ws, status__in=[Invoice.Status.SENT, Invoice.Status.OVERDUE]
    ).aggregate(s=Sum("amount"))["s"] or Decimal("0")
    pipeline = confirmed.exclude(status__in=[Booking.Status.COMPLETED, Booking.Status.ARCHIVED]) \
        .aggregate(s=Sum("total"))["s"] or Decimal("0")
    avg_value = confirmed.aggregate(a=Avg("total"))["a"] or Decimal("0")

    # Most-booked packages (by quotes referencing them).
    popular = list(Package.objects.filter(service__workspace=ws)
                   .annotate(n=Count("quote")).filter(n__gt=0).order_by("-n")[:5])

    sources = list(enquiries.values("source").annotate(n=Count("id")).order_by("-n"))

    repeat_clients = bookings.values("client").annotate(n=Count("id")).filter(n__gt=1).count()
    total_clients = Client.objects.filter(workspace=ws).count()

    # 6-month trend (revenue from payments, new bookings by created month).
    today = timezone.now().date()
    trend = []
    y, m = today.year, today.month
    seq = []
    for _ in range(6):
        seq.append((y, m))
        m -= 1
        if m == 0:
            m, y = 12, y - 1
    for (yy, mm) in reversed(seq):
        rev = Payment.objects.filter(
            invoice__booking__workspace=ws, status=Payment.Status.SUCCEEDED,
            paid_at__year=yy, paid_at__month=mm).aggregate(s=Sum("amount"))["s"] or Decimal("0")
        bk = bookings.filter(created_at__year=yy, created_at__month=mm).count()
        trend.append({"label": _month_label(yy, mm), "revenue": rev, "bookings": bk})
    max_rev = max((t["revenue"] for t in trend), default=Decimal("0")) or Decimal("1")
    for t in trend:
        t["pct"] = int(t["revenue"] / max_rev * 100)

    profile = getattr(ws, "profile", None)
    return {
        "funnel": funnel,
        "paid": paid, "outstanding": outstanding, "pipeline": pipeline, "avg_value": avg_value,
        "popular": popular, "sources": sources,
        "repeat_clients": repeat_clients, "total_clients": total_clients,
        "repeat_pct": _pct(repeat_clients, total_clients),
        "trend": trend, "trend_total": sum((t["revenue"] for t in trend), Decimal("0")),
        "profile_views": getattr(profile, "view_count", 0),
        "view_to_enquiry": _pct(n_enq, getattr(profile, "view_count", 0)),
        "completed": bookings.filter(status=Booking.Status.COMPLETED).count(),
    }
