from django.db.utils import IntegrityError
from django.test import TestCase

from apps.settings.models import Branch, Room, Table


class TableModelTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.branch = Branch.objects.create(name="Main Branch")
        cls.room = Room.objects.create(branch=cls.branch, name="Hall")
        cls.table = Table.objects.create(
            room=cls.room,
            branch=cls.branch,
            name="T1",
            no_of_seats=4,
            table_shape="RECTANGLE",
        )

    def test_str_returns_name(self):
        self.assertEqual(str(self.table), "T1")

    def test_branch_derived_from_room(self):
        t = Table.objects.create(room=self.room, name="T-auto")
        self.assertEqual(t.branch_id, self.room.branch_id)

    def test_default_values(self):
        self.assertFalse(self.table.is_take_away)
        self.assertFalse(self.table.occupied)
        self.assertIsNone(self.table.latest_invoice_time)

    def test_occupied_is_not_editable(self):
        field = Table._meta.get_field("occupied")
        self.assertFalse(field.editable)

    def test_latest_invoice_time_is_not_editable(self):
        field = Table._meta.get_field("latest_invoice_time")
        self.assertFalse(field.editable)

    def test_shape_choices(self):
        self.assertEqual(self.table.get_table_shape_display(), "Rectangle")
        t2 = Table.objects.create(room=self.room, branch=self.branch, name="T2", table_shape="CIRCLE")
        self.assertEqual(t2.get_table_shape_display(), "Circle")

    def test_take_away_flag(self):
        t = Table.objects.create(room=self.room, branch=self.branch, name="TA1", is_take_away=True)
        self.assertTrue(t.is_take_away)

    def test_layout_coords_default_none(self):
        self.assertIsNone(self.table.layout_x)
        self.assertIsNone(self.table.layout_y)
        self.assertIsNone(self.table.layout_width)
        self.assertIsNone(self.table.layout_height)

    def test_layout_coords_set(self):
        self.table.layout_x = 10.5
        self.table.layout_y = 20.0
        self.table.layout_width = 120.0
        self.table.layout_height = 80.0
        self.table.save()
        self.table.refresh_from_db()
        self.assertEqual(self.table.layout_x, 10.5)
        self.assertEqual(self.table.layout_y, 20.0)

    def test_unique_together_room_name(self):
        with self.assertRaises(IntegrityError):
            Table.objects.create(room=self.room, branch=self.branch, name="T1")

    def test_minimum_seating_nullable(self):
        t = Table.objects.create(room=self.room, branch=self.branch, name="T3", minimum_seating=2)
        self.assertEqual(t.minimum_seating, 2)

    def test_update(self):
        self.table.no_of_seats = 6
        self.table.save()
        self.table.refresh_from_db()
        self.assertEqual(self.table.no_of_seats, 6)

    def test_delete(self):
        pk = self.table.pk
        self.table.delete()
        self.assertFalse(Table.objects.filter(pk=pk).exists())
