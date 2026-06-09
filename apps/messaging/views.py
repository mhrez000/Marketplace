"""Unified Messages inbox — one place for clients and creatives to see every
conversation, instead of digging into each booking."""
from django.contrib.auth.decorators import login_required
from django.db.models import Q
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render

from .models import Message, Thread


@login_required
def inbox(request):
    user = request.user
    threads = (Thread.objects.filter(Q(client=user) | Q(workspace__owner=user))
               .select_related("workspace", "workspace__owner", "client", "booking")
               .prefetch_related("messages"))
    items = []
    for t in threads:
        last = t.last_message
        if not last:
            continue
        items.append({"thread": t, "last": last, "unread": t.unread_for(user),
                      "other": t.other_label(user)})
    items.sort(key=lambda i: i["last"].created_at, reverse=True)
    return render(request, "messaging/inbox.html", {"items": items})


@login_required
def thread_detail(request, pk):
    thread = get_object_or_404(
        Thread.objects.select_related("workspace", "workspace__owner", "client", "booking"), pk=pk)
    if not thread.is_participant(request.user):
        raise Http404("Not your conversation")

    if request.method == "POST":
        body = request.POST.get("body", "").strip()
        if body:
            Message.objects.create(thread=thread, sender=request.user, body=body)
            # A creative replying to an enquiry counts as the first response.
            if thread.enquiry and request.user.id == thread.workspace.owner_id:
                thread.enquiry.mark_responded()
        return redirect("messaging:thread", pk=thread.pk)

    thread.mark_read_for(request.user)
    return render(request, "messaging/thread.html", {
        "thread": thread,
        "messages_list": thread.messages.select_related("sender"),
        "other": thread.other_label(request.user),
        "is_creative": request.user.id == thread.workspace.owner_id,
    })
