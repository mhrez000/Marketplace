"""JSON API for the native apps. Token auth; same business logic as the web
(reuses apps.bookings.services so the three platforms behave identically)."""
from django.contrib.auth import authenticate, get_user_model
from django.db.models import Q
from django.shortcuts import get_object_or_404
from rest_framework import permissions, status
from rest_framework.authtoken.models import Token
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response

from apps.bookings import services as flow
from apps.bookings.models import Booking
from apps.bookings.services import create_enquiry
from apps.core.selectors import annotate_ratings
from apps.enquiries.models import Enquiry
from apps.galleries.models import Asset, Gallery
from apps.messaging.models import Message, Thread
from apps.payments.models import Invoice
from apps.profiles.models import CATEGORY_CHOICES, CreativeProfile
from apps.profiles.services import filter_listable
from apps.workspaces.models import Workspace

from .serializers import (AssetSerializer, BookingSerializer,
                          CreativeDetailSerializer, CreativeListSerializer,
                          EnquirySerializer, GalleryDetailSerializer,
                          GallerySummarySerializer, MessageSerializer,
                          QuoteSerializer, ThreadDetailSerializer,
                          ThreadListSerializer, UserSerializer)

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


def _next_action(b, contract):
    """What the client can do next, so the app shows the right button."""
    S = Booking.Status
    if b.status == S.CONTRACT_SENT and contract and not contract.signed_by_client_at:
        return "sign"
    if b.status == S.CONTRACT_SIGNED:
        return "pay_deposit"
    final = b.invoices.filter(invoice_type=Invoice.Type.FINAL).first()
    if final and not final.is_paid:
        return "pay_final"
    return None


def _booking_payload(b):
    data = BookingSerializer(b).data
    data["quote"] = QuoteSerializer(b.quote).data if b.quote else None
    contract = getattr(b, "contract", None)
    data["contract"] = (
        {"body": contract.body, "signed_by_client": bool(contract.signed_by_client_at)}
        if contract else None
    )
    data["next_action"] = _next_action(b, contract)
    data["galleries"] = GallerySummarySerializer(
        b.galleries.filter(is_delivered=True), many=True).data
    return data


@api_view(["GET"])
def booking_detail(request, pk):
    b = get_object_or_404(
        Booking.objects.filter(Q(client=request.user) | Q(workspace__owner=request.user)), pk=pk)
    return Response(_booking_payload(b))


def _client_booking(request, pk):
    return get_object_or_404(Booking, pk=pk, client=request.user)


@api_view(["POST"])
def booking_sign(request, pk):
    b = _client_booking(request, pk)
    contract = getattr(b, "contract", None)
    if not contract or contract.signed_by_client_at:
        return Response({"detail": "Nothing to sign."}, status=400)
    name = (request.data.get("name") or "").strip()
    if not name:
        return Response({"detail": "Please provide your full name to sign."}, status=400)
    flow.sign_contract_client(contract, name=name, request=request)
    b.refresh_from_db()
    return Response(_booking_payload(b))


@api_view(["POST"])
def booking_pay_deposit(request, pk):
    b = _client_booking(request, pk)
    try:
        flow.pay_deposit(b)
    except flow.DateUnavailable:
        return Response(
            {"detail": "That date was just booked by someone else. Message the creative."},
            status=409)
    b.refresh_from_db()
    return Response(_booking_payload(b))


@api_view(["POST"])
def booking_pay_final(request, pk):
    b = _client_booking(request, pk)
    flow.pay_final(b)
    b.refresh_from_db()
    return Response(_booking_payload(b))


@api_view(["POST"])
def quote_accept(request, pk):
    from apps.enquiries.models import Quote
    quote = get_object_or_404(Quote, pk=pk, enquiry__client=request.user)
    if quote.is_expired:
        return Response({"detail": "This quote has expired — ask for an updated one."}, status=400)
    if quote.status in {Quote.Status.SENT, Quote.Status.DRAFT}:
        booking = flow.accept_quote(quote)
        return Response(_booking_payload(booking), status=201)
    booking = quote.bookings.first()
    if booking:
        return Response(_booking_payload(booking))
    return Response({"detail": "This quote can no longer be accepted."}, status=400)


@api_view(["POST"])
def quote_decline(request, pk):
    from apps.enquiries.models import Quote
    quote = get_object_or_404(Quote, pk=pk, enquiry__client=request.user)
    if quote.status in {Quote.Status.SENT, Quote.Status.DRAFT}:
        quote.status = Quote.Status.DECLINED
        quote.save(update_fields=["status", "updated_at"])
        enquiry = quote.enquiry
        enquiry.status = Enquiry.Status.DECLINED
        enquiry.save(update_fields=["status", "updated_at"])
        from apps.notifications.models import notify
        notify(enquiry.workspace.owner, f"{request.user.email} declined your quote",
               url="/app/leads/", icon="bell")
    return Response({"status": "declined"})


@api_view(["GET"])
def gallery_detail(request, pk):
    gallery = get_object_or_404(
        Gallery.objects.filter(is_delivered=True), pk=pk, booking__client=request.user)
    return Response(GalleryDetailSerializer(gallery, context={"request": request}).data)


@api_view(["POST"])
def asset_favourite(request, pk):
    asset = get_object_or_404(Asset, pk=pk, gallery__booking__client=request.user)
    asset.is_favourite = not asset.is_favourite
    asset.save(update_fields=["is_favourite", "updated_at"])
    return Response(AssetSerializer(asset, context={"request": request}).data)


@api_view(["GET"])
def threads(request):
    qs = (Thread.objects.filter(Q(client=request.user) | Q(workspace__owner=request.user))
          .select_related("workspace", "workspace__owner", "client").prefetch_related("messages"))
    items = [t for t in qs if t.last_message]
    items.sort(key=lambda t: t.last_message.created_at, reverse=True)
    return Response(ThreadListSerializer(items, many=True, context={"request": request}).data)


@api_view(["GET", "POST"])
def thread_detail(request, pk):
    thread = get_object_or_404(
        Thread.objects.select_related("workspace", "workspace__owner", "client", "enquiry"), pk=pk)
    if not thread.is_participant(request.user):
        return Response({"detail": "Not your conversation."}, status=403)
    if request.method == "POST":
        body = (request.data.get("body") or "").strip()
        if not body:
            return Response({"detail": "Message cannot be empty."}, status=400)
        msg = Message.objects.create(thread=thread, sender=request.user, body=body)
        # A creative replying to an enquiry counts as the first response (mirrors web).
        if thread.enquiry and request.user.id == thread.workspace.owner_id:
            thread.enquiry.mark_responded()
        return Response(MessageSerializer(msg, context={"request": request}).data, status=201)
    thread.mark_read_for(request.user)
    return Response(ThreadDetailSerializer(thread, context={"request": request}).data)
