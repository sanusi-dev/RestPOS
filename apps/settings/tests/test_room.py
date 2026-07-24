from django.db.utils import IntegrityError
from django.test import TestCase

from apps.settings.models import Branch, Room


class RoomModelTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.branch = Branch.objects.create(name="Main Branch")
        cls.room = Room.objects.create(branch=cls.branch, name="Hall")

    def test_str_returns_name(self):
        self.assertEqual(str(self.room), "Hall")

    def test_branch_relationship(self):
        self.assertEqual(self.room.branch, self.branch)

    def test_auto_assigns_default_branch(self):
        room = Room.objects.create(name="Patio")
        self.assertEqual(room.branch_id, self.branch.pk)

    def test_unique_together_branch_name(self):
        with self.assertRaises(IntegrityError):
            Room.objects.create(branch=self.branch, name="Hall")

    def test_same_name_different_branch(self):
        other = Branch.objects.create(name="Other Branch")
        room = Room.objects.create(branch=other, name="Hall")
        self.assertEqual(room.name, "Hall")

    def test_ordering(self):
        Room.objects.create(branch=self.branch, name="AAA")
        rooms = list(Room.objects.filter(branch=self.branch))
        self.assertEqual(rooms[0].name, "AAA")

    def test_update(self):
        self.room.name = "Main Hall"
        self.room.save()
        self.room.refresh_from_db()
        self.assertEqual(self.room.name, "Main Hall")

    def test_delete(self):
        pk = self.room.pk
        self.room.delete()
        self.assertFalse(Room.objects.filter(pk=pk).exists())
