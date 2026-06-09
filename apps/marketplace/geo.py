"""Suburb + service data and geo helpers for programmatic SEO pages and
distance-aware search.

Works on SQLite today via a Python Haversine; swap to PostGIS `ST_DWithin`
later without changing callers (build plan §14, §19).
"""
from math import asin, cos, radians, sin, sqrt

# Melbourne suburbs (name, slug, lat, lng). Expand to all of VIC/AU over time.
SUBURBS = [
    ("Melbourne CBD", "melbourne-cbd", -37.8136, 144.9631),
    ("Fitzroy", "fitzroy", -37.7980, 144.9784),
    ("Richmond", "richmond", -37.8230, 144.9980),
    ("Brunswick", "brunswick", -37.7670, 144.9600),
    ("St Kilda", "st-kilda", -37.8675, 144.9810),
    ("Carlton", "carlton", -37.8000, 144.9670),
    ("South Yarra", "south-yarra", -37.8380, 144.9920),
    ("Prahran", "prahran", -37.8510, 144.9920),
    ("Footscray", "footscray", -37.8000, 144.9000),
    ("Williamstown", "williamstown", -37.8600, 144.8970),
    ("Northcote", "northcote", -37.7700, 145.0000),
    ("Preston", "preston", -37.7400, 145.0000),
    ("Hawthorn", "hawthorn", -37.8220, 145.0350),
    ("Camberwell", "camberwell", -37.8260, 145.0580),
    ("Box Hill", "box-hill", -37.8190, 145.1210),
    ("Doncaster", "doncaster", -37.7870, 145.1250),
    ("Essendon", "essendon", -37.7530, 144.9070),
    ("Moonee Ponds", "moonee-ponds", -37.7660, 144.9190),
    ("Yarraville", "yarraville", -37.8160, 144.8900),
    ("Brighton", "brighton", -37.9060, 144.9990),
    ("Glen Waverley", "glen-waverley", -37.8780, 145.1640),
    ("Coburg", "coburg", -37.7440, 144.9650),
    ("Geelong", "geelong", -38.1499, 144.3617),
    ("Werribee", "werribee", -37.9000, 144.6600),
]
SUBURBS_BY_SLUG = {s[1]: {"name": s[0], "slug": s[1], "lat": s[2], "lng": s[3]} for s in SUBURBS}

# Service slug -> category + display copy. We don't split photo/video at the data
# layer, so both wedding-photographer and wedding-videographer surface weddings.
SERVICES = {
    "wedding-photographer": {"category": "weddings", "label": "Wedding Photographers", "noun": "wedding photographer"},
    "wedding-videographer": {"category": "weddings", "label": "Wedding Videographers", "noun": "wedding videographer"},
    "event-photographer": {"category": "events", "label": "Event Photographers", "noun": "event photographer"},
    "real-estate-photographer": {"category": "real-estate", "label": "Real Estate Photographers", "noun": "real estate photographer"},
    "brand-photographer": {"category": "business", "label": "Brand & Content Creators", "noun": "brand photographer"},
    "family-photographer": {"category": "family", "label": "Family Photographers", "noun": "family photographer"},
    "content-creator": {"category": "content", "label": "Content & Reels Creators", "noun": "content creator"},
}


def haversine_km(lat1, lng1, lat2, lng2):
    r = 6371.0
    dlat, dlng = radians(lat2 - lat1), radians(lng2 - lng1)
    a = sin(dlat / 2) ** 2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlng / 2) ** 2
    return 2 * r * asin(sqrt(a))


def creatives_serving(suburb_slug, *, category=None):
    """Listed creatives whose service area covers `suburb_slug` (within their
    radius of their base), ranked featured → rating → distance."""
    from django.utils.text import slugify

    from apps.core.selectors import annotate_ratings
    from apps.profiles.models import CreativeProfile
    from apps.profiles.services import filter_listable

    s = SUBURBS_BY_SLUG.get(suburb_slug)
    qs = filter_listable(
        CreativeProfile.objects.filter(workspace__is_published=True).select_related("workspace"))
    if category:
        qs = qs.filter(primary_category=category)
    qs = annotate_ratings(qs)

    out = []
    for p in qs:
        if s and p.latitude is not None and p.longitude is not None:
            dist = haversine_km(s["lat"], s["lng"], p.latitude, p.longitude)
            if dist <= (p.service_radius_km or 40):
                out.append((dist, p))
        elif s and slugify(p.suburb) == suburb_slug:
            out.append((0.0, p))
    out.sort(key=lambda t: (not t[1].is_featured, -(t[1].avg_rating or 0), t[0]))
    return [p for _, p in out]


def nearby_suburbs(slug, *, limit=6):
    s = SUBURBS_BY_SLUG.get(slug)
    if not s:
        return []
    ranked = sorted(
        (o for o in SUBURBS_BY_SLUG.values() if o["slug"] != slug),
        key=lambda o: haversine_km(s["lat"], s["lng"], o["lat"], o["lng"]),
    )
    return ranked[:limit]
