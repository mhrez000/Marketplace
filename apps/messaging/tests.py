from django.contrib.auth import get_user_model
from django.test import TestCase

from apps.messaging.models import Message, Thread
from apps.workspaces.models import Workspace

User = get_user_model()


class MessagingInboxTests(TestCase):
    def setUp(self):
        self.creative = User.objects.create_user(email="cr@t.com", password="x", first_name="Cara")
        self.client_user = User.objects.create_user(email="cl@t.com", password="x", first_name="Cleo")
        self.outsider = User.objects.create_user(email="out@t.com", password="x")
        self.ws = Workspace.objects.create(owner=self.creative, business_name="Cara Studio")
        self.thread = Thread.objects.create(workspace=self.ws, client=self.client_user, subject="Wedding")
        Message.objects.create(thread=self.thread, sender=self.client_user, body="Hi, are you free?")

    def test_inbox_lists_conversation(self):
        self.client.force_login(self.creative)
        r = self.client.get("/messages/", SERVER_NAME="localhost")
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "Cleo")  # the client name (other party for the creative)

    def test_other_label_is_business_for_client(self):
        self.assertEqual(self.thread.other_label(self.client_user), "Cara Studio")
        self.assertEqual(self.thread.other_label(self.creative), "Cleo")

    def test_opening_thread_marks_read(self):
        self.assertEqual(self.thread.unread_for(self.creative), 1)
        self.client.force_login(self.creative)
        self.client.get(f"/messages/{self.thread.pk}/", SERVER_NAME="localhost")
        self.assertEqual(self.thread.unread_for(self.creative), 0)

    def test_reply_posts_message(self):
        self.client.force_login(self.creative)
        self.client.post(f"/messages/{self.thread.pk}/", {"body": "Yes! What date?"}, SERVER_NAME="localhost")
        self.assertTrue(self.thread.messages.filter(sender=self.creative, body="Yes! What date?").exists())

    def test_outsider_cannot_view_thread(self):
        self.client.force_login(self.outsider)
        r = self.client.get(f"/messages/{self.thread.pk}/", SERVER_NAME="localhost")
        self.assertEqual(r.status_code, 404)

    def test_inbox_requires_login(self):
        r = self.client.get("/messages/", SERVER_NAME="localhost")
        self.assertEqual(r.status_code, 302)
