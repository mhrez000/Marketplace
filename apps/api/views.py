"""JSON API for the native apps. Token auth; same business logic as the web
(reuses apps.bookings.services so the three platforms behave identically)."""
from decimal import Decimal, InvalidOperation

from django.contrib.auth import authenticate, get_user_model
from django.db.models import Q
from django.shortcuts import get_object_or_404
from rest_framework import permissions, status
from rest_framework.authtoken.models import Token
from rest_framework.decorators import (api_view, parser_classes,
                                        permission_classes)
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.response import Response

from apps.bookings import services as flow
from apps.bookings.models import Booking
from apps.bookings.services import create_enquiry
from apps.core.selectors import annotate_ratings, get_active_workspace
from apps.enquiries.models import Enquiry
from apps.galleries.models import Asset, Gallery
from apps.messaging.models import Message, Thread
from apps.payments.models import Invoice
from apps.profiles.models import (CATEGORY_CHOICES, CreativeProfile, Package,
                                  Service)
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


@api_view(["POST", "DELETE"])
def devices(request):
    """Register (or remove) a mobile push token for the signed-in user."""
    from apps.notifications.models import DeviceToken
    token = (request.data.get("token") or "").strip()
    if not token:
        return Response({"detail": "A device token is required."}, status=400)
    if request.method == "DELETE":
        DeviceToken.objects.filter(user=request.user, token=token).delete()
        return Response(status=204)
    platform = request.data.get("platform", "android")
    DeviceToken.objects.update_or_create(
        token=token, defaults={"user": request.user, "platform": platform})
    return Response({"registered": True}, status=201)


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
    return Response(CreativeDetailSerializer(profile, context={"request": request}).data)


@api_view(["POST"])
def creative_favourite(request, slug):
    from apps.marketplace.models import Favourite
    ws = get_object_or_404(Workspace.objects.filter(is_published=True), slug=slug)
    fav = Favourite.objects.filter(client=request.user, workspace=ws).first()
    if fav:
        fav.delete()
        return Response({"is_favourited": False})
    Favourite.objects.create(client=request.user, workspace=ws)
    return Response({"is_favourited": True})


@api_view(["GET"])
def favourites(request):
    from apps.marketplace.models import Favourite
    ws_ids = Favourite.objects.filter(client=request.user).values_list("workspace_id", flat=True)
    qs = annotate_ratings(
        CreativeProfile.objects.filter(workspace_id__in=ws_ids, workspace__is_published=True)
        .select_related("workspace")).order_by("-is_featured", "-avg_rating")
    return Response(CreativeListSerializer(qs, many=True).data)


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


def _booking_payload(request, b):
    data = BookingSerializer(b).data
    data["quote"] = QuoteSerializer(b.quote).data if b.quote else None
    contract = getattr(b, "contract", None)
    data["contract"] = (
        {"body": contract.body, "signed_by_client": bool(contract.signed_by_client_at)}
        if contract else None
    )
    viewer_is_client = b.client_id == request.user.id
    data["viewer_is_client"] = viewer_is_client
    # next_action is the client's call-to-action; only meaningful for the client.
    data["next_action"] = _next_action(b, contract) if viewer_is_client else None
    data["creative_step"] = None if viewer_is_client else _creative_step(b)
    data["galleries"] = GallerySummarySerializer(
        b.galleries.filter(is_delivered=True), many=True).data

    review = getattr(b, "review", None)
    data["review"] = (
        {"rating": review.rating, "title": review.title, "body": review.body} if review else None)
    data["awaiting_review"] = bool(b.awaiting_review and viewer_is_client)

    from apps.bookings.models import Dispute
    dispute = b.disputes.order_by("-created_at").first()
    data["dispute"] = (
        {"status": dispute.status, "status_display": dispute.get_status_display(),
         "reason": dispute.get_reason_display()} if dispute else None)
    data["dispute_reasons"] = [{"value": v, "label": l} for v, l in Dispute.Reason.choices]
    data["key_dates"] = _key_dates(b)
    return data


def _key_dates(b):
    """The booking's shoot + deadlines, mirrored from the web calendar so the
    apps can show the same shoots-vs-deadlines treatment. icon/category match
    the dashboard calendar feed."""
    from apps.bookings.models import CalendarEvent
    T = CalendarEvent.Type
    icons = {T.SHOOT: "📷", T.EDITING_DUE: "🖼", T.PAYMENT_DUE: "💰", T.CONTRACT_DUE: "📄"}
    category = {T.SHOOT: "shoot", T.EDITING_DUE: "task", T.PAYMENT_DUE: "task",
                T.CONTRACT_DUE: "task"}
    out = []
    for e in b.events.exclude(event_type__in=[T.BLOCKED, T.CUSTOM]).order_by("start"):
        out.append({
            "type": e.event_type,
            "kind": e.get_event_type_display(),
            "title": e.title,
            "icon": icons.get(e.event_type, "📅"),
            "category": category.get(e.event_type, "task"),
            "date": e.start.isoformat(),
            "overdue": e.is_overdue,
        })
    return out


def _creative_step(b):
    """The production step a creative can take next on this booking."""
    S = Booking.Status
    if b.status in {S.CONFIRMED, S.PLANNING}:
        return "shoot_completed"
    if b.status == S.SHOOT_COMPLETED:
        return "start_editing"
    return None


@api_view(["GET"])
def booking_detail(request, pk):
    b = get_object_or_404(
        Booking.objects.filter(Q(client=request.user) | Q(workspace__owner=request.user)), pk=pk)
    return Response(_booking_payload(request, b))


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
    return Response(_booking_payload(request, b))


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
    return Response(_booking_payload(request, b))


@api_view(["POST"])
def booking_pay_final(request, pk):
    b = _client_booking(request, pk)
    flow.pay_final(b)
    b.refresh_from_db()
    return Response(_booking_payload(request, b))


@api_view(["POST"])
def booking_review(request, pk):
    b = _client_booking(request, pk)
    if not b.is_complete:
        return Response({"detail": "You can review once the booking is complete."}, status=400)
    try:
        rating = max(1, min(5, int(request.data.get("rating", 5))))
    except (TypeError, ValueError):
        rating = 5
    flow.create_review(booking=b, rating=rating,
                       title=(request.data.get("title") or "").strip(),
                       body=(request.data.get("body") or "").strip())
    b.refresh_from_db()
    return Response(_booking_payload(request, b))


@api_view(["POST"])
def booking_dispute(request, pk):
    b = get_object_or_404(
        Booking.objects.filter(Q(client=request.user) | Q(workspace__owner=request.user)), pk=pk)
    role = "client" if b.client_id == request.user.id else "creative"
    flow.raise_dispute(b, user=request.user, role=role,
                       reason=request.data.get("reason", "other"),
                       detail=(request.data.get("detail") or "").strip())
    b.refresh_from_db()
    return Response(_booking_payload(request, b))


def _blocked_payload(ws):
    from django.conf import settings
    from apps.profiles import services as av
    return {
        "blocked": [d.date.isoformat() for d in av.blocked_dates(ws)],
        "ical_url": f"{settings.SITE_URL}/calendar/{ws.ical_token}.ics",
    }


@api_view(["GET"])
def availability(request):
    ws = get_active_workspace(request.user)
    if not ws:
        return Response({"detail": "You don't have a creative profile."}, status=403)
    return Response(_blocked_payload(ws))


@api_view(["POST"])
def availability_block(request):
    from apps.profiles import services as av
    ws = get_active_workspace(request.user)
    if not ws:
        return Response({"detail": "You don't have a creative profile."}, status=403)
    if av.block(ws, request.data.get("date")) is None:
        return Response({"detail": "That date is already booked — it can't be blocked."}, status=400)
    return Response(_blocked_payload(ws))


@api_view(["POST"])
def availability_unblock(request):
    from apps.profiles import services as av
    ws = get_active_workspace(request.user)
    if not ws:
        return Response({"detail": "You don't have a creative profile."}, status=403)
    av.unblock(ws, request.data.get("date"))
    return Response(_blocked_payload(ws))


@api_view(["POST"])
def booking_advance(request, pk):
    """Creative moves a booking through production (shoot done / start editing)."""
    ws = get_active_workspace(request.user)
    if not ws:
        return Response({"detail": "Only creatives can update production status."}, status=403)
    b = get_object_or_404(Booking, pk=pk, workspace=ws)
    step = request.data.get("step")
    if step == "shoot_completed":
        b.transition(Booking.Status.SHOOT_COMPLETED, force=True)
    elif step == "start_editing":
        b.transition(Booking.Status.EDITING, force=True)
    else:
        return Response({"detail": "Unknown step."}, status=400)
    b.refresh_from_db()
    return Response(_booking_payload(request, b))


@api_view(["GET"])
def analytics(request):
    ws = get_active_workspace(request.user)
    if not ws:
        return Response({"detail": "You don't have a creative profile."}, status=403)
    from apps.dashboard.analytics import workspace_analytics
    a = workspace_analytics(ws)
    return Response({
        "paid": str(a["paid"]),
        "outstanding": str(a["outstanding"]),
        "pipeline": str(a["pipeline"]),
        "avg_value": str(a["avg_value"]),
        "completed": a["completed"],
        "repeat_clients": a["repeat_clients"],
        "repeat_pct": a["repeat_pct"],
        "profile_views": a["profile_views"],
        "view_to_enquiry": a["view_to_enquiry"],
        "funnel": [{"label": f["label"], "value": f["value"]} for f in a["funnel"]],
        "trend": [str(x) for x in a["trend"]],
    })


@api_view(["POST"])
def booking_deliver(request, pk):
    """Creative delivers a gallery link (Drive/Dropbox/Pixieset/etc.)."""
    from django.core.exceptions import ValidationError
    from django.core.validators import URLValidator

    ws = get_active_workspace(request.user)
    if not ws:
        return Response({"detail": "Only creatives can deliver galleries."}, status=403)
    b = get_object_or_404(Booking, pk=pk, workspace=ws)
    url = (request.data.get("url") or "").strip()
    try:
        URLValidator(schemes=["http", "https"])(url)
    except ValidationError:
        return Response({"detail": "Paste a valid link starting with https://."}, status=400)
    title = (request.data.get("title") or "").strip() or f"{b.title} — Gallery"
    gallery = Gallery.objects.create(
        booking=b, title=title, delivery_url=url,
        gallery_type=Gallery.Type.PHOTO, visibility=Gallery.Visibility.PRIVATE)
    flow.deliver_gallery(gallery)
    b.refresh_from_db()
    return Response(_booking_payload(request, b))


@api_view(["POST"])
def quote_accept(request, pk):
    from apps.enquiries.models import Quote
    quote = get_object_or_404(Quote, pk=pk, enquiry__client=request.user)
    if quote.is_expired:
        return Response({"detail": "This quote has expired — ask for an updated one."}, status=400)
    if quote.status in {Quote.Status.SENT, Quote.Status.DRAFT}:
        booking = flow.accept_quote(quote)
        return Response(_booking_payload(request, booking), status=201)
    booking = quote.bookings.first()
    if booking:
        return Response(_booking_payload(request, booking))
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


def _package_dict(pkg):
    return {
        "id": pkg.id, "name": pkg.name, "base_price": f"{pkg.base_price:.2f}",
        "description": pkg.description, "inclusions": pkg.inclusion_list,
    }


def _inclusions_to_text(val):
    if isinstance(val, list):
        return "\n".join(str(s).strip() for s in val if str(s).strip())
    return (val or "").strip()


def _profile_payload(p):
    return {
        "business_name": p.workspace.business_name,
        "primary_category": p.primary_category,
        "primary_category_display": p.get_primary_category_display(),
        "location": p.location_label,
        "headline": p.headline,
        "bio": p.bio,
        "styles": p.style_list,
        "starting_price": f"{p.starting_price:.2f}" if p.starting_price is not None else None,
        "packages": [_package_dict(pk) for pk in
                     Package.objects.filter(service__workspace=p.workspace).select_related("service")],
    }


@api_view(["POST"])
def packages(request):
    ws = get_active_workspace(request.user)
    if not ws:
        return Response({"detail": "Only creatives can manage packages."}, status=403)
    name = (request.data.get("name") or "").strip()
    try:
        price = Decimal(str(request.data.get("base_price")))
    except (TypeError, ValueError, InvalidOperation):
        price = None
    if not name or price is None:
        return Response({"detail": "A package needs a name and a valid price."}, status=400)
    service = ws.services.first() or Service.objects.create(
        workspace=ws, category=ws.profile.primary_category, title=ws.business_name)
    pkg = Package.objects.create(
        service=service, name=name, base_price=price,
        description=(request.data.get("description") or "").strip(),
        inclusions=_inclusions_to_text(request.data.get("inclusions")))
    return Response(_package_dict(pkg), status=201)


@api_view(["PUT", "DELETE"])
def package_detail(request, pk):
    ws = get_active_workspace(request.user)
    if not ws:
        return Response({"detail": "Only creatives can manage packages."}, status=403)
    pkg = get_object_or_404(Package, pk=pk, service__workspace=ws)
    if request.method == "DELETE":
        pkg.delete()
        return Response(status=204)
    if request.data.get("name"):
        pkg.name = request.data["name"].strip()
    if "base_price" in request.data:
        try:
            pkg.base_price = Decimal(str(request.data["base_price"]))
        except (TypeError, ValueError, InvalidOperation):
            return Response({"detail": "Enter a valid price."}, status=400)
    if "description" in request.data:
        pkg.description = (request.data.get("description") or "").strip()
    if "inclusions" in request.data:
        pkg.inclusions = _inclusions_to_text(request.data.get("inclusions"))
    pkg.save()
    return Response(_package_dict(pkg))


@api_view(["GET", "PUT"])
def my_profile(request):
    ws = get_active_workspace(request.user)
    if not ws:
        return Response({"detail": "You don't have a creative profile."}, status=403)
    p = ws.profile
    if request.method == "PUT":
        if "headline" in request.data:
            p.headline = (request.data.get("headline") or "").strip()
        if "bio" in request.data:
            p.bio = (request.data.get("bio") or "").strip()
        if "styles" in request.data:
            styles = request.data.get("styles")
            if isinstance(styles, list):
                p.styles = ", ".join(s.strip() for s in styles if str(s).strip())
            else:
                p.styles = (styles or "").strip()
        if "starting_price" in request.data:
            sp = request.data.get("starting_price")
            if sp in (None, ""):
                p.starting_price = None
            else:
                try:
                    p.starting_price = Decimal(str(sp))
                except (InvalidOperation, ValueError):
                    return Response({"detail": "Enter a valid starting price."}, status=400)
        p.save()
    return Response(_profile_payload(p))


@api_view(["GET"])
def leads(request):
    """The creative's incoming enquiries (workspaces they own)."""
    ws = get_active_workspace(request.user)
    if not ws:
        return Response([])
    qs = (Enquiry.objects.filter(workspace=ws)
          .select_related("client", "workspace").prefetch_related("quotes").order_by("-created_at"))
    return Response(EnquirySerializer(qs, many=True).data)


@api_view(["POST"])
def lead_send_quote(request, pk):
    ws = get_active_workspace(request.user)
    if not ws:
        return Response({"detail": "Only creatives can send quotes."}, status=403)
    enquiry = get_object_or_404(Enquiry, pk=pk, workspace=ws)
    title = (request.data.get("title") or "").strip() or f"Quote — {enquiry.get_event_type_display()}"
    try:
        amount = float(request.data.get("amount"))
    except (TypeError, ValueError):
        return Response({"detail": "Enter a valid quote amount."}, status=400)
    if amount <= 0:
        return Response({"detail": "Quote amount must be greater than zero."}, status=400)
    try:
        deposit_pct = Decimal(str(request.data.get("deposit_pct", "25"))) / 100
    except (InvalidOperation, ValueError):
        deposit_pct = Decimal("0.25")
    quote = flow.send_quote(enquiry=enquiry, title=title,
                            line_items=[{"label": title, "amount": amount}],
                            deposit_pct=deposit_pct)
    return Response(QuoteSerializer(quote).data, status=201)


@api_view(["POST"])
@parser_classes([MultiPartParser, FormParser])
def gallery_upload(request, pk):
    """Creative uploads photo files to a booking — creates/extends an in-app
    (non-link) gallery instead of pasting a Drive/Dropbox link."""
    ws = get_active_workspace(request.user)
    if not ws:
        return Response({"detail": "Only creatives can upload galleries."}, status=403)
    b = get_object_or_404(Booking, pk=pk, workspace=ws)
    images = request.FILES.getlist("images")
    if not images and "image" in request.FILES:
        images = [request.FILES["image"]]
    if not images:
        return Response({"detail": "Attach at least one photo."}, status=400)

    gallery = b.galleries.filter(delivery_url="").first()
    if not gallery:
        gallery = Gallery.objects.create(
            booking=b, title=(request.data.get("title") or "").strip() or f"{b.title} — Gallery",
            gallery_type=Gallery.Type.PHOTO, visibility=Gallery.Visibility.PRIVATE)
        flow.deliver_gallery(gallery)
    for img in images:
        Asset.objects.create(gallery=gallery, image=img, asset_type=Asset.Type.PHOTO)
    return Response(GalleryDetailSerializer(gallery, context={"request": request}).data, status=201)


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
