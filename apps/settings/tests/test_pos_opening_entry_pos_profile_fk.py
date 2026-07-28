from django.db.models.deletion import ProtectedError
from django.test import TestCase

from apps.inventory.models import Warehouse
from apps.settings.models import Branch, POSProfile, Restaurant, Room
from apps.staff.models import POSOpeningEntry
from apps.users.models import CustomUser


class POSOpeningEntryPosProfileFKTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.branch = Branch.objects.create(name="Main Branch")
        cls.room = Room.objects.create(branch=cls.branch, name="Hall")
        cls.restaurant = Restaurant.objects.create(company="Test Co", branch=cls.branch, default_room=cls.room)
        cls.warehouse = Warehouse.objects.create(name="Kitchen", branch=cls.branch)
        cls.user = CustomUser.objects.create_user(username="cashier1", password="testpass123")
        cls.profile = POSProfile.objects.create(name="Main Cashier", warehouse=cls.warehouse)

    def test_opening_entry_without_pos_profile(self):
        entry = POSOpeningEntry.objects.create(branch=self.branch, cashier=self.user)
        self.assertIsNone(entry.pos_profile)

    def test_opening_entry_with_pos_profile(self):
        entry = POSOpeningEntry.objects.create(branch=self.branch, cashier=self.user, pos_profile=self.profile)
        self.assertEqual(entry.pos_profile_id, self.profile.pk)

    def test_pos_profile_related_name(self):
        entry = POSOpeningEntry.objects.create(branch=self.branch, cashier=self.user, pos_profile=self.profile)
        self.assertIn(entry, self.profile.opening_entries.all())

    def test_protect_on_profile_delete(self):
        POSOpeningEntry.objects.create(branch=self.branch, cashier=self.user, pos_profile=self.profile)
        with self.assertRaises(ProtectedError):
            self.profile.delete()
