from django.contrib.auth import get_user_model
from django.core import mail
from django.test import TestCase, override_settings

from apps.notifications.models import Notification, dispatch

User = get_user_model()


@override_settings(CELERY_TASK_ALWAYS_EAGER=True,
                   EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
class DispatchMatrixTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(email="u@t.com", password="x", first_name="Sam")

    def test_email_event_creates_inapp_and_branded_email(self):
        mail.outbox = []
        dispatch("gallery_delivered", self.user, verb="Your gallery is ready", url="/portal/gallery/1/")
        # in-app record
        self.assertTrue(Notification.objects.filter(user=self.user, icon="image").exists())
        # branded multipart email
        self.assertEqual(len(mail.outbox), 1)
        m = mail.outbox[0]
        self.assertTrue(m.alternatives and m.alternatives[0][1] == "text/html")
        self.assertIn("Open your gallery", m.alternatives[0][0])  # event-specific CTA

    def test_inapp_only_event_sends_no_email(self):
        # An unknown event falls back to in_app-only.
        mail.outbox = []
        dispatch("some_unmapped_event", self.user, verb="FYI", url="")
        self.assertEqual(len(mail.outbox), 0)
        self.assertTrue(Notification.objects.filter(user=self.user).exists())

    def test_subject_and_cta_come_from_matrix(self):
        mail.outbox = []
        dispatch("payment_overdue", self.user, verb="Your balance is overdue", url="/portal/")
        m = mail.outbox[0]
        self.assertIn("Payment overdue", m.subject)            # matrix subject
        self.assertIn("Pay now", m.alternatives[0][0])         # matrix CTA
