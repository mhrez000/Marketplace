from django.urls import path

from . import views

app_name = "api"

urlpatterns = [
    path("auth/register/", views.register, name="register"),
    path("auth/login/", views.login, name="login"),
    path("auth/me/", views.me, name="me"),
    path("creatives/", views.creatives, name="creatives"),
    path("creatives/<slug:slug>/", views.creative_detail, name="creative_detail"),
    path("enquiries/", views.enquiries, name="enquiries"),
    path("bookings/", views.bookings, name="bookings"),
    path("bookings/<uuid:pk>/", views.booking_detail, name="booking_detail"),
]
