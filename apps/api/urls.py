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
    path("bookings/<uuid:pk>/sign/", views.booking_sign, name="booking_sign"),
    path("bookings/<uuid:pk>/pay-deposit/", views.booking_pay_deposit, name="booking_pay_deposit"),
    path("bookings/<uuid:pk>/pay-final/", views.booking_pay_final, name="booking_pay_final"),
    path("quotes/<int:pk>/accept/", views.quote_accept, name="quote_accept"),
    path("quotes/<int:pk>/decline/", views.quote_decline, name="quote_decline"),
    path("galleries/<uuid:pk>/", views.gallery_detail, name="gallery_detail"),
    path("assets/<int:pk>/favourite/", views.asset_favourite, name="asset_favourite"),
    path("messages/", views.threads, name="threads"),
    path("messages/<int:pk>/", views.thread_detail, name="thread_detail"),
]
