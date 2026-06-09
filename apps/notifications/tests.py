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

    def test_preference_suppresses_reminders_not_transactional(self):
        from apps.notifications.models import NotificationPreference
        NotificationPreference.objects.create(user=self.user, email_reminders=False)
        mail.outbox = []
        dispatch("payment_reminder", self.user, verb="due soon", url="/portal/")  # reminder
        self.assertEqual(len(mail.outbox), 0)
        dispatch("gallery_delivered", self.user, verb="ready", url="/portal/")     # transactional
        self.assertEqual(len(mail.outbox), 1)


class SettingsPageTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(email="s@t.com", password="pw")

    def test_settings_page_renders_and_saves(self):
        self.client.force_login(self.user)
        r = self.client.get("/settings/notifications/", SERVER_NAME="localhost")
        self.assertEqual(r.status_code, 200)
        self.client.post("/settings/notifications/",
                         {"email_marketing": "on", "sms_phone": "0400000000"}, SERVER_NAME="localhost")
        self.user.notification_preference.refresh_from_db()
        self.assertFalse(self.user.notification_preference.email_reminders)  # unchecked -> off
        self.assertTrue(self.user.notification_preference.email_marketing)
        self.assertEqual(self.user.notification_preference.sms_phone, "0400000000")

    def test_settings_requires_login(self):
        r = self.client.get("/settings/notifications/", SERVER_NAME="localhost")
        self.assertEqual(r.status_code, 302)
