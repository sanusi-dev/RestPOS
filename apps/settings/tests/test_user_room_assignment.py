from django.core.exceptions import ValidationError
from django.db.utils import IntegrityError
from django.test import TestCase

from apps.settings.models import Branch, Room, UserRoomAssignment
from apps.users.models import CustomUser


class UserRoomAssignmentModelTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.branch = Branch.objects.create(name="Main Branch")
        cls.room = Room.objects.create(branch=cls.branch, name="Hall")
        cls.user = CustomUser.objects.create_user(username="cashier1", password="testpass123", email="c1@test.com")
        cls.assignment = UserRoomAssignment.objects.create(user=cls.user, room=cls.room, branch=cls.branch)

    def test_str_returns_user_and_room(self):
        self.assertEqual(str(self.assignment), "cashier1 → Hall")

    def test_unique_together_user_room(self):
        with self.assertRaises(IntegrityError):
            UserRoomAssignment.objects.create(user=self.user, room=self.room, branch=self.branch)

    def test_same_user_different_room(self):
        room2 = Room.objects.create(branch=self.branch, name="Garden")
        a2 = UserRoomAssignment.objects.create(user=self.user, room=room2, branch=self.branch)
        self.assertEqual(a2.room, room2)

    def test_branch_consistency_validation(self):
        other_branch = Branch.objects.create(name="Other Branch")
        room_other = Room.objects.create(branch=other_branch, name="Other Room")
        a = UserRoomAssignment(user=self.user, room=room_other, branch=self.branch)
        with self.assertRaises(ValidationError):
            a.clean()

    def test_valid_branch_consistency(self):
        self.assignment.clean()

    def test_ordering_by_username(self):
        user2 = CustomUser.objects.create_user(username="acashier", password="testpass123", email="a@test.com")
        room2 = Room.objects.create(branch=self.branch, name="Room 2")
        UserRoomAssignment.objects.create(user=user2, room=room2, branch=self.branch)
        first = UserRoomAssignment.objects.first()
        self.assertEqual(first.user, user2)

    def test_update(self):
        self.assignment.branch = self.branch
        self.assignment.save()
        self.assignment.refresh_from_db()
        self.assertEqual(self.assignment.branch, self.branch)

    def test_delete(self):
        pk = self.assignment.pk
        self.assignment.delete()
        self.assertFalse(UserRoomAssignment.objects.filter(pk=pk).exists())

    def test_cascade_delete_user(self):
        pk = self.assignment.pk
        self.user.delete()
        self.assertFalse(UserRoomAssignment.objects.filter(pk=pk).exists())

    def test_cascade_delete_room(self):
        pk = self.assignment.pk
        self.room.delete()
        self.assertFalse(UserRoomAssignment.objects.filter(pk=pk).exists())
