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
    path("calendar/", views.calendar, name="calendar"),
    path("deliveries/", views.deliveries, name="deliveries"),
    path("clients/", views.clients, name="clients"),
    path("profile/", views.profile, name="profile"),
    path("notifications/read/", views.notifications_read, name="notifications_read"),
]
