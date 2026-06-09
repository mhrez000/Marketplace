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


@override_settings(CELERY_TASK_ALWAYS_EAGER=True,
                   EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
class SmsAndDigestTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(email="u@t.com", password="x")

    def test_sms_inert_without_config(self):
        from apps.notifications.sms import send_sms
        self.assertFalse(send_sms("0400000000", "hi"))  # SMS_ENABLED defaults False

    def test_sms_only_for_opted_in_users(self):
        from unittest.mock import patch
        from apps.notifications.models import NotificationPreference
        # No preference -> no SMS attempted on an SMS-channel event.
        with patch("apps.notifications.sms.send_sms") as m:
            dispatch("booking_confirmed", self.user, verb="confirmed", url="/portal/")
            self.assertFalse(m.called)
        # Opted in with a phone -> SMS attempted.
        NotificationPreference.objects.create(user=self.user, sms_enabled=True, sms_phone="0400000000")
        with patch("apps.notifications.sms.send_sms") as m:
            dispatch("booking_confirmed", self.user, verb="confirmed", url="/portal/")
            self.assertTrue(m.called)

    def test_message_digest_emails_recipient(self):
        from apps.messaging.models import Message, Thread
        from apps.notifications.tasks import message_digest
        from apps.workspaces.models import Workspace
        creative = User.objects.create_user(email="cr@t.com", password="x")
        ws = Workspace.objects.create(owner=creative, business_name="S")
        thread = Thread.objects.create(workspace=ws, client=self.user)
        Message.objects.create(thread=thread, sender=self.user, body="Hi, any update?")
        mail.outbox = []
        result = message_digest()
        self.assertIn("1 digest", result)            # the creative (recipient) gets it
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("cr@t.com", mail.outbox[0].to)


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
