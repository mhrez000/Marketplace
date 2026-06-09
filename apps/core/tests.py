from django.contrib.auth import get_user_model
from django.core import mail
from django.test import TestCase, override_settings

User = get_user_model()


@override_settings(CELERY_TASK_ALWAYS_EAGER=True,
                   EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
class CeleryEagerTests(TestCase):
    def test_notify_email_runs_inline_via_task(self):
        u = User.objects.create_user(email="x@t.com", password="x", first_name="X")
        from apps.notifications.models import notify
        mail.outbox = []
        notify(u, "Hello", url="/portal/", email=True)
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("Lens", mail.outbox[0].subject)

    def test_notify_without_email_flag_sends_nothing(self):
        u = User.objects.create_user(email="y@t.com", password="x")
        from apps.notifications.models import notify
        mail.outbox = []
        notify(u, "Hello", email=False)
        self.assertEqual(len(mail.outbox), 0)

    def test_housekeeping_task_returns_summary(self):
        from apps.core.tasks import run_housekeeping
        summary = run_housekeeping()
        self.assertIn("reminder", summary)
