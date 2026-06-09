from django.urls import path

from . import views

app_name = "marketplace"

urlpatterns = [
    path("", views.home, name="home"),
    path("search/", views.search, name="search"),
    path("how-it-works/", views.how_it_works, name="how_it_works"),
    path("pricing/", views.pricing, name="pricing"),
    path("for-creatives/", views.for_creatives, name="for_creatives"),
    path("p/<slug:slug>/", views.profile_detail, name="profile"),
    path("p/<slug:slug>/enquire/", views.enquire, name="enquire"),
    path("p/<slug:slug>/favourite/", views.toggle_favourite, name="favourite"),
    path("browse/", views.browse, name="browse"),
    # Programmatic SEO — keep LAST (generic two-segment match).
    path("<slug:service>/<slug:suburb>/", views.suburb_service, name="suburb_service"),
]
