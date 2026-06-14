"""JSON API for the native apps. Token auth; same business logic as the web
(reuses apps.bookings.services so the three platforms behave identically)."""
from django.contrib.auth import authenticate, get_user_model
from django.db.models import Q
from django.shortcuts import get_object_or_404
from rest_framework import permissions, status
from rest_framework.authtoken.models import Token
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response

from apps.bookings.models import Booking
from apps.bookings.services import create_enquiry
from apps.core.selectors import annotate_ratings
from apps.enquiries.models import Enquiry
from apps.profiles.models import CATEGORY_CHOICES, CreativeProfile
from apps.profiles.services import filter_listable
from apps.workspaces.models import Workspace

from .serializers import (BookingSerializer, CreativeDetailSerializer,
                          CreativeListSerializer, EnquirySerializer,
                          QuoteSerializer, UserSerializer)

User = get_user_model()


def _token_payload(user):
    token, _ = Token.objects.get_or_create(user=user)
    return {"token": token.key, "user": UserSerializer(user).data}


@api_view(["POST"])
@permission_classes([permissions.AllowAny])
def register(request):
    email = (request.data.get("email") or "").strip().lower()
    password = request.data.get("password") or ""
    if not email or not password:
        return Response({"detail": "Email and password are required."}, status=400)
    if User.objects.filter(email__iexact=email).exists():
        return Response({"detail": "An account with that email already exists."}, status=400)
    name = (request.data.get("name") or "").strip()
    first, _, last = name.partition(" ")
    user = User.objects.create_user(email=email, password=password, first_name=first, last_name=last,
                                    role_type=User.RoleType.CLIENT)
    return Response(_token_payload(user), status=201)


@api_view(["POST"])
@permission_classes([permissions.AllowAny])
def login(request):
    email = (request.data.get("email") or "").strip().lower()
    password = request.data.get("password") or ""
    user = authenticate(request, username=email, password=password)
    if not user:
        return Response({"detail": "Invalid email or password."}, status=400)
    return Response(_token_payload(user))


@api_view(["GET"])
def me(request):
    return Response(UserSerializer(request.user).data)


@api_view(["GET"])
@permission_classes([permissions.AllowAny])
def creatives(request):
    qs = filter_listable(
        CreativeProfile.objects.filter(workspace__is_published=True).select_related("workspace"))
    q = request.GET.get("q", "").strip()
    category = request.GET.get("category", "").strip()
    location = request.GET.get("location", "").strip()
    if category:
        qs = qs.filter(primary_category=category)
    if q:
        cat = next((c[0] for c in CATEGORY_CHOICES if c[1].lower() in q.lower()), None)
        cond = (Q(headline__icontains=q) | Q(bio__icontains=q) | Q(styles__icontains=q) |
                Q(workspace__business_name__icontains=q))
        if cat:
            cond |= Q(primary_category=cat)
        qs = qs.filter(cond)
    if location:
        qs = qs.filter(Q(suburb__icontains=location) | Q(city__icontains=location))
    qs = annotate_ratings(qs).order_by("-is_featured", "-avg_rating", "-review_count")
    return Response(CreativeListSerializer(qs, many=True).data)


@api_view(["GET"])
@permission_classes([permissions.AllowAny])
def creative_detail(request, slug):
    ws = get_object_or_404(Workspace.objects.filter(is_published=True), slug=slug)
    profile = annotate_ratings(CreativeProfile.objects.filter(pk=ws.profile.pk)).first()
    return Response(CreativeDetailSerializer(profile).data)


@api_view(["GET", "POST"])
def enquiries(request):
    if request.method == "POST":
        ws = get_object_or_404(Workspace, slug=request.data.get("workspace"), is_published=True)
        enquiry = create_enquiry(
            client=request.user, workspace=ws,
            event_type=request.data.get("event_type", "weddings"),
            message=(request.data.get("message") or "").strip() or "I'd like to enquire about availability.",
            event_date=request.data.get("event_date") or None,
            location=request.data.get("location", "").strip(),
            budget_band=request.data.get("budget_band", "").strip(),
        )
        return Response(EnquirySerializer(enquiry).data, status=201)
    qs = (Enquiry.objects.filter(client=request.user)
          .select_related("workspace").order_by("-created_at"))
    return Response(EnquirySerializer(qs, many=True).data)


@api_view(["GET"])
def bookings(request):
    qs = (Booking.objects.filter(Q(client=request.user) | Q(workspace__owner=request.user))
          .select_related("workspace", "client").order_by("-created_at"))
    return Response(BookingSerializer(qs, many=True).data)


@api_view(["GET"])
def booking_detail(request, pk):
    b = get_object_or_404(
        Booking.objects.filter(Q(client=request.user) | Q(workspace__owner=request.user)), pk=pk)
    data = BookingSerializer(b).data
    quote = b.quote
    data["quote"] = QuoteSerializer(quote).data if quote else None
    return Response(data)
