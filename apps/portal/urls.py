from django.urls import path

from . import views

app_name = "portal"

urlpatterns = [
    path("", views.home, name="home"),
    path("booking/<uuid:pk>/", views.booking_detail, name="booking_detail"),
    path("quote/<int:pk>/accept/", views.quote_accept, name="quote_accept"),
    path("gallery/<uuid:pk>/", views.gallery_detail, name="gallery_detail"),
]
