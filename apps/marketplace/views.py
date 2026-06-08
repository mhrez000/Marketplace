from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse

from apps.bookings.services import create_enquiry
from apps.core.selectors import annotate_ratings
from apps.profiles.models import CATEGORY_CHOICES, CreativeProfile
from apps.workspaces.models import Workspace

CATEGORIES = [
    {"slug": "weddings", "name": "Weddings", "icon": "heart", "blurb": "Photographers & videographers for your day."},
    {"slug": "events", "name": "Events", "icon": "sparkles", "blurb": "Birthdays, engagements, corporate, parties."},
    {"slug": "real-estate", "name": "Real Estate", "icon": "home", "blurb": "Fast-turnaround property shoots & drone."},
    {"slug": "business", "name": "Business & Brand", "icon": "briefcase", "blurb": "Brand films, product, content & reels."},
    {"slug": "family", "name": "Family & Portrait", "icon": "users", "blurb": "Portraits, newborns, milestones."},
    {"slug": "content", "name": "Content & Reels", "icon": "video", "blurb": "Social content for creators & brands."},
]


def _published_profiles():
    return annotate_ratings(
        CreativeProfile.objects.filter(workspace__is_published=True).select_related("workspace")
    )


def home(request):
    featured = list(_published_profiles().order_by("-is_featured", "-avg_rating")[:4])
    return render(request, "marketplace/home.html", {"categories": CATEGORIES, "featured": featured})


def search(request):
    query = request.GET.get("q", "").strip()
    location = request.GET.get("location", "").strip()
    category = request.GET.get("category", "").strip()

    qs = _published_profiles()
    if category:
        qs = qs.filter(primary_category=category)
    if query:
        # Match a category label, or free-text across headline/bio/styles/business name.
        cat_match = next((c[0] for c in CATEGORY_CHOICES if c[1].lower() in query.lower()), None)
        cond = (Q(headline__icontains=query) | Q(bio__icontains=query) |
                Q(styles__icontains=query) | Q(workspace__business_name__icontains=query))
        if cat_match:
            cond |= Q(primary_category=cat_match)
        qs = qs.filter(cond)
    if location:
        qs = qs.filter(Q(suburb__icontains=location) | Q(city__icontains=location))

    # Ranking: featured → rating → completeness proxy (has cover/price).
    qs = qs.order_by("-is_featured", "-avg_rating", "-review_count")

    return render(request, "marketplace/search.html", {
        "query": query, "location": location, "category": category,
        "results": list(qs), "categories": CATEGORIES, "count": qs.count(),
    })


def profile_detail(request, slug):
    workspace = get_object_or_404(
        Workspace.objects.filter(is_published=True).select_related("profile"), slug=slug
    )
    profile = workspace.profile
    services = workspace.services.prefetch_related("packages")
    packages = [p for s in services for p in s.packages.all()]
    reviews = workspace.reviews.select_related("client").order_by("-created_at")[:6]
    rating_agg = annotate_ratings(CreativeProfile.objects.filter(pk=profile.pk)).first()

    return render(request, "marketplace/profile_detail.html", {
        "workspace": workspace, "profile": profile, "packages": packages,
        "reviews": reviews, "categories": CATEGORIES,
        "avg_rating": getattr(rating_agg, "avg_rating", None),
        "review_count": getattr(rating_agg, "review_count", 0),
    })


@login_required
def enquire(request, slug):
    workspace = get_object_or_404(Workspace, slug=slug, is_published=True)
    if request.method == "POST":
        create_enquiry(
            client=request.user, workspace=workspace,
            event_type=request.POST.get("event_type", "weddings"),
            message=request.POST.get("message", "").strip() or "I'd like to enquire about availability.",
            event_date=request.POST.get("event_date") or None,
            location=request.POST.get("location", "").strip(),
            budget_band=request.POST.get("budget_band", "").strip(),
        )
        messages.success(request, f"Enquiry sent to {workspace.business_name}! Track it in your client portal.")
        return redirect(reverse("portal:home"))
    return redirect(workspace.profile and reverse("marketplace:profile", args=[slug]) or "marketplace:home")


# Static marketing pages -----------------------------------------------------
def how_it_works(request):
    return render(request, "marketplace/how_it_works.html")


def pricing(request):
    plans = [
        {"name": "Listed", "price": "0", "cadence": "free forever", "for": "New & casual creatives", "featured": False,
         "features": ["Marketplace profile", "Limited enquiries", "Basic calendar", "Portfolio gallery"]},
        {"name": "Pro", "price": "29", "cadence": "per month", "for": "Solo photographers & videographers", "featured": True,
         "features": ["Everything in Listed", "Full CRM & pipeline", "Quotes, contracts & e-sign",
                      "Invoices & deposits (Stripe)", "Gallery delivery", "Mini-website",
                      "AI quote & email drafting", "Full marketplace visibility"]},
        {"name": "Studio", "price": "79", "cadence": "per month", "for": "Studios & teams", "featured": False,
         "features": ["Everything in Pro", "Team seats & roles", "Collaborator tools",
                      "More storage", "Multi-brand (coming)", "Priority support"]},
    ]
    return render(request, "marketplace/pricing.html", {"plans": plans})


def for_creatives(request):
    return render(request, "marketplace/for_creatives.html")
