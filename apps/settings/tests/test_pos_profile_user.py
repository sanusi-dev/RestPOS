from django.db.models.deletion import ProtectedError
from django.db.utils import IntegrityError
from django.test import TestCase

from apps.inventory.models import Warehouse
from apps.settings.models import Branch, POSProfile, POSProfileUser, Restaurant, Room
from apps.users.models import CustomUser


class POSProfileUserModelTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.branch = Branch.objects.create(name="Main Branch")
        cls.room = Room.objects.create(branch=cls.branch, name="Hall")
        cls.restaurant = Restaurant.objects.create(company="Test Co", branch=cls.branch, default_room=cls.room)
        cls.warehouse = Warehouse.objects.create(name="Kitchen", branch=cls.branch)
        cls.profile = POSProfile.objects.create(name="Main Cashier", warehouse=cls.warehouse)
        cls.user = CustomUser.objects.create_user(username="cashier1", password="testpass123")

    def test_create(self):
        link = POSProfileUser.objects.create(pos_profile=self.profile, user=self.user, is_default=True)
        self.assertIsNotNone(link.pk)

    def test_str(self):
        link = POSProfileUser.objects.create(pos_profile=self.profile, user=self.user)
        self.assertIn("cashier1", str(link))
        self.assertIn("Main Cashier", str(link))

    def test_unique_together_profile_user(self):
        POSProfileUser.objects.create(pos_profile=self.profile, user=self.user)
        with self.assertRaises(IntegrityError):
            POSProfileUser.objects.create(pos_profile=self.profile, user=self.user)

    def test_is_default_false_by_default(self):
        link = POSProfileUser.objects.create(pos_profile=self.profile, user=self.user)
        self.assertFalse(link.is_default)

    def test_is_main_cashier_false_by_default(self):
        link = POSProfileUser.objects.create(pos_profile=self.profile, user=self.user)
        self.assertFalse(link.is_main_cashier)

    def test_cascade_delete_on_profile(self):
        link = POSProfileUser.objects.create(pos_profile=self.profile, user=self.user)
        self.profile.delete()
        self.assertFalse(POSProfileUser.objects.filter(pk=link.pk).exists())

    def test_protect_on_user_delete(self):
        POSProfileUser.objects.create(pos_profile=self.profile, user=self.user)
        with self.assertRaises(ProtectedError):
            self.user.delete()

    def test_ordering_by_username(self):
        user2 = CustomUser.objects.create_user(username="aaa_cashier", password="pass")
        POSProfileUser.objects.create(pos_profile=self.profile, user=user2)
        links = list(POSProfileUser.objects.all())
        self.assertEqual(links[0].user.username, "aaa_cashier")
