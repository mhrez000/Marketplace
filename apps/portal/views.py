"""Client-facing portal: view bookings, accept quotes, sign, pay, message,
view galleries, leave reviews. Scoped strictly to the logged-in client."""
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render

from apps.bookings import services as flow
from apps.bookings.models import Booking
from apps.enquiries.models import Enquiry, Quote
from apps.galleries.models import Gallery
from apps.messaging.models import Message


@login_required
def home(request):
    enquiries = (Enquiry.objects.filter(client=request.user)
                 .select_related("workspace").prefetch_related("quotes").order_by("-created_at"))
    bookings = (Booking.objects.filter(client=request.user)
                .select_related("workspace").order_by("-created_at"))
    return render(request, "portal/home.html", {"enquiries": enquiries, "bookings": bookings})


@login_required
def booking_detail(request, pk):
    booking = get_object_or_404(
        Booking.objects.select_related("workspace", "quote"), pk=pk, client=request.user
    )
    contract = getattr(booking, "contract", None)
    invoices = booking.invoices.all()
    galleries = booking.galleries.filter(is_delivered=True)
    thread = booking.threads.first() or (booking.enquiry.threads.first() if booking.enquiry else None)
    review = getattr(booking, "review", None)

    if request.method == "POST":
        _handle_client_action(request, booking, contract)
        return redirect("portal:booking_detail", pk=booking.pk)

    return render(request, "portal/booking_detail.html", {
        "booking": booking, "contract": contract, "invoices": invoices,
        "galleries": galleries, "thread": thread, "review": review,
        "messages_list": thread.messages.select_related("sender") if thread else [],
        "S": Booking.Status,
    })


def _handle_client_action(request, booking, contract):
    action = request.POST.get("action")
    if action == "accept_quote" and booking.quote:
        booking.quote.status = Quote.Status.ACCEPTED
        booking.quote.save(update_fields=["status", "updated_at"])
        messages.success(request, "Quote accepted! Please review and sign your contract.")
    elif action == "sign_contract" and contract and not contract.signed_by_client_at:
        name = request.POST.get("signature_name", "").strip()
        if not name:
            messages.error(request, "Please type your full name to sign.")
        else:
            flow.sign_contract_client(contract, name=name, request=request)
            messages.success(request, "Contract signed. You can now pay your deposit.")
    elif action == "pay_deposit":
        try:
            flow.pay_deposit(booking)
            messages.success(request, "Deposit paid (test gateway) — your booking is confirmed! 🎉")
        except flow.DateUnavailable:
            messages.error(request, "Sorry — that date was just booked by someone else. "
                                    "Message the creative to find another date.")
    elif action == "cancel":
        flow.cancel_booking(booking, by="client", reason=request.POST.get("reason", "").strip())
        messages.success(request, "Your booking has been cancelled.")
    elif action == "pay_final":
        flow.pay_final(booking)
        messages.success(request, "Final payment complete. Thank you!")
    elif action == "leave_review":
        rating = int(request.POST.get("rating", 5))
        flow.create_review(booking=booking, rating=rating,
                           title=request.POST.get("title", "").strip(),
                           body=request.POST.get("body", "").strip())
        messages.success(request, "Thanks for your review!")
    elif action == "send_message":
        body = request.POST.get("body", "").strip()
        thread = booking.threads.first() or (booking.enquiry.threads.first() if booking.enquiry else None)
        if thread and body:
            Message.objects.create(thread=thread, sender=request.user, body=body)


@login_required
def quote_accept(request, pk):
    """Accept a quote straight from the portal home — creates the booking."""
    quote = get_object_or_404(Quote, pk=pk, enquiry__client=request.user)
    if quote.status in {Quote.Status.SENT, Quote.Status.DRAFT}:
        booking = flow.accept_quote(quote)
        messages.success(request, "Quote accepted! Review and sign your contract.")
        return redirect("portal:booking_detail", pk=booking.pk)
    # Already accepted — go to its booking if any.
    booking = quote.bookings.first()
    if booking:
        return redirect("portal:booking_detail", pk=booking.pk)
    return redirect("portal:home")


@login_required
def quote_decline(request, pk):
    quote = get_object_or_404(Quote, pk=pk, enquiry__client=request.user)
    if quote.status in {Quote.Status.SENT, Quote.Status.DRAFT}:
        quote.status = Quote.Status.DECLINED
        quote.save(update_fields=["status", "updated_at"])
        enquiry = quote.enquiry
        enquiry.status = Enquiry.Status.DECLINED
        enquiry.save(update_fields=["status", "updated_at"])
        from apps.notifications.models import notify
        notify(quote.enquiry.workspace.owner,
               f"{request.user.email} declined your quote", url="/app/leads/", icon="bell")
        messages.success(request, "Quote declined.")
    return redirect("portal:home")


@login_required
def gallery_detail(request, pk):
    gallery = get_object_or_404(
        Gallery.objects.select_related("booking"), pk=pk, booking__client=request.user
    )
    if request.method == "POST":
        asset_id = request.POST.get("favourite")
        if asset_id:
            asset = gallery.assets.filter(pk=asset_id).first()
            if asset:
                asset.is_favourite = not asset.is_favourite
                asset.save(update_fields=["is_favourite", "updated_at"])
        return redirect("portal:gallery_detail", pk=gallery.pk)
    return render(request, "portal/gallery_detail.html", {
        "gallery": gallery, "assets": gallery.assets.all(),
    })
