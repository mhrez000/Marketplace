from django.urls import path

from . import views

app_name = "dashboard"

urlpatterns = [
    path("", views.overview, name="overview"),
    path("onboarding/", views.onboarding, name="onboarding"),
    path("leads/", views.leads, name="leads"),
    path("leads/<int:pk>/", views.lead_detail, name="lead_detail"),
    path("bookings/", views.bookings_list, name="bookings"),
    path("bookings/<uuid:pk>/", views.booking_detail, name="booking_detail"),
    path("hire/", views.hire, name="hire"),
    path("calendar/", views.calendar, name="calendar"),
    path("calendar/events/", views.calendar_events, name="calendar_events"),
    path("deliveries/", views.deliveries, name="deliveries"),
    path("checklist/", views.checklist, name="checklist"),
    path("clients/", views.clients, name="clients"),
    path("analytics/", views.analytics, name="analytics"),
    path("profile/", views.profile, name="profile"),
    path("search/", views.search, name="search"),
    path("ops/", views.ops, name="ops"),
    path("broadcast/", views.broadcast, name="broadcast"),
    path("notifications/read/", views.notifications_read, name="notifications_read"),
]
