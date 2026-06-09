from django.contrib.auth import get_user_model
from django.test import TestCase

from apps.marketplace.models import Favourite
from apps.profiles.models import CreativeProfile
from apps.workspaces.models import Workspace

User = get_user_model()


class FavouriteTests(TestCase):
    def setUp(self):
        creative = User.objects.create_user(email="c@t.com", password="x")
        self.client_user = User.objects.create_user(email="cl@t.com", password="pw")
        self.ws = Workspace.objects.create(owner=creative, business_name="Saved Studio", is_published=True)
        CreativeProfile.objects.create(workspace=self.ws, primary_category="events")

    def test_toggle_favourite_adds_then_removes(self):
        self.client.force_login(self.client_user)
        url = f"/p/{self.ws.slug}/favourite/"
        self.client.post(url, SERVER_NAME="localhost")
        self.assertTrue(Favourite.objects.filter(client=self.client_user, workspace=self.ws).exists())
        self.client.post(url, SERVER_NAME="localhost")
        self.assertFalse(Favourite.objects.filter(client=self.client_user, workspace=self.ws).exists())

    def test_favourite_requires_login(self):
        r = self.client.post(f"/p/{self.ws.slug}/favourite/", SERVER_NAME="localhost")
        self.assertEqual(r.status_code, 302)  # redirected to login
        self.assertFalse(Favourite.objects.exists())
