"""The notification channel matrix (build plan §16).

One source of truth: each event → its category, channels, email subject, CTA
label and bell icon. `dispatch()` reads this instead of scattering email flags.

categories:
  transactional — confirmations/receipts/delivery; always sent (no opt-out).
  reminder      — payment due, quote expiring, review nudge; respects prefs.
  digest        — batched (e.g. new messages).
  marketing     — opt-in only.
"""
TRANSACTIONAL = "transactional"
REMINDER = "reminder"
DIGEST = "digest"
MARKETING = "marketing"

# channels: "in_app", "email", "sms" (sms reserved — wired later)
EVENTS = {
    # ── Client-facing ──────────────────────────────────────────────────────
    "quote_received": dict(category=TRANSACTIONAL, channels=["in_app", "email"],
                           subject="You've received a quote", cta="View quote", icon="doc"),
    "contract_to_sign": dict(category=TRANSACTIONAL, channels=["in_app", "email"],
                             subject="Please review & sign your contract", cta="Review contract", icon="doc"),
    "booking_confirmed": dict(category=TRANSACTIONAL, channels=["in_app", "email", "sms"],
                              subject="Your booking is confirmed 🎉", cta="View booking", icon="card"),
    "gallery_delivered": dict(category=TRANSACTIONAL, channels=["in_app", "email"],
                              subject="Your gallery is ready ✨", cta="Open your gallery", icon="image"),
    "payment_reminder": dict(category=REMINDER, channels=["in_app", "email"],
                             subject="Payment reminder", cta="Pay now", icon="clock"),
    "payment_overdue": dict(category=REMINDER, channels=["in_app", "email", "sms"],
                            subject="Payment overdue", cta="Pay now", icon="alert"),
    "review_request": dict(category=TRANSACTIONAL, channels=["in_app", "email"],
                           subject="How was your experience?", cta="Leave a review", icon="bell"),
    "booking_cancelled_client": dict(category=TRANSACTIONAL, channels=["in_app", "email", "sms"],
                                     subject="Your booking was cancelled", cta="View booking", icon="alert"),
    # ── Creative-facing ────────────────────────────────────────────────────
    "new_enquiry": dict(category=TRANSACTIONAL, channels=["in_app", "email"],
                        subject="New enquiry", cta="View lead", icon="inbox"),
    "quote_accepted": dict(category=TRANSACTIONAL, channels=["in_app", "email"],
                           subject="Your quote was accepted", cta="View booking", icon="card"),
    "lead_waiting": dict(category=REMINDER, channels=["in_app", "email"],
                         subject="A lead is waiting", cta="Respond now", icon="alert"),
    "dispute_raised": dict(category=TRANSACTIONAL, channels=["in_app", "email"],
                           subject="A dispute was raised", cta="View details", icon="alert"),
    # ── Creative-to-creative collaboration ─────────────────────────────────
    "collab_invited": dict(category=TRANSACTIONAL, channels=["in_app", "email"],
                           subject="You've been invited to collaborate", cta="View invite", icon="users"),
    "collab_response": dict(category=TRANSACTIONAL, channels=["in_app", "email"],
                            subject="Your collaboration invite was answered", cta="View booking", icon="users"),
    "collab_paid": dict(category=TRANSACTIONAL, channels=["in_app", "email"],
                        subject="You've been paid for a collaboration", cta="View collaboration", icon="card"),
    # ── Digest ─────────────────────────────────────────────────────────────
    "message_digest": dict(category=DIGEST, channels=["in_app", "email"],
                           subject="You have new messages", cta="Open messages", icon="inbox"),
}


def event(key):
    return EVENTS.get(key, dict(category=TRANSACTIONAL, channels=["in_app"], subject=None,
                                cta="View details", icon="bell"))
