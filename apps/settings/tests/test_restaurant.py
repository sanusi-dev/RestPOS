from django.core.exceptions import ValidationError
from django.test import TestCase

from apps.inventory.models import PurchaseReceipt, StockEntry, Warehouse
from apps.orders.models import Order
from apps.settings.models import Restaurant


class RestaurantModelTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.restaurant = Restaurant.objects.create(company="Test Restaurant Ltd")

    def test_str_returns_company(self):
        self.assertEqual(str(self.restaurant), "Test Restaurant Ltd")

    def test_invoice_series_prefix_default(self):
        self.assertEqual(self.restaurant.invoice_series_prefix, "REST-")

    def test_singleton_rejects_second_record(self):
        r2 = Restaurant(company="Other")
        with self.assertRaises(ValidationError):
            r2.clean()

    def test_singleton_allows_update_of_same_record(self):
        self.restaurant.company = "Updated"
        self.restaurant.clean()

    def test_load_returns_the_singleton(self):
        self.assertEqual(Restaurant.load(), self.restaurant)

    def test_load_returns_none_when_empty(self):
        Restaurant.objects.all().delete()
        self.assertIsNone(Restaurant.load())

    def test_update(self):
        self.restaurant.company = "New Name"
        self.restaurant.save()
        self.restaurant.refresh_from_db()
        self.assertEqual(self.restaurant.company, "New Name")

    def test_delete(self):
        pk = self.restaurant.pk
        self.restaurant.delete()
        self.assertFalse(Restaurant.objects.filter(pk=pk).exists())

    def test_store_and_bar_warehouses_must_be_enabled_and_distinct(self):
        store = Warehouse.objects.create(name="Store")
        disabled = Warehouse.objects.create(name="Disabled", disabled=True)
        self.restaurant.store_warehouse = store
        self.restaurant.default_warehouse = store
        with self.assertRaises(ValidationError):
            self.restaurant.full_clean()
        self.restaurant.default_warehouse = disabled
        with self.assertRaises(ValidationError):
            self.restaurant.full_clean()

    def test_bar_change_rejected_with_snapshotted_normal_draft(self):
        old_bar = Warehouse.objects.create(name="Old Bar")
        new_bar = Warehouse.objects.create(name="New Bar")
        self.restaurant.default_warehouse = old_bar
        self.restaurant.save(update_fields=["default_warehouse"])
        Order.objects.create(stock_warehouse=old_bar)

        self.restaurant.default_warehouse = new_bar
        with self.assertRaisesMessage(ValidationError, "open POS orders"):
            self.restaurant.full_clean()

    def test_bar_change_ignores_returns_and_unsnapshotted_drafts(self):
        old_bar = Warehouse.objects.create(name="Old Bar")
        new_bar = Warehouse.objects.create(name="New Bar")
        self.restaurant.default_warehouse = old_bar
        self.restaurant.save(update_fields=["default_warehouse"])
        Order.objects.create()
        Order.objects.create(is_return=True, stock_warehouse=old_bar)

        self.restaurant.default_warehouse = new_bar
        self.restaurant.full_clean()

    def test_store_change_rejected_with_draft_stock_documents(self):
        old_store = Warehouse.objects.create(name="Old Store")
        new_store = Warehouse.objects.create(name="New Store")
        self.restaurant.store_warehouse = old_store
        self.restaurant.save(update_fields=["store_warehouse"])

        for document in (
            StockEntry.objects.create(purpose="MATERIAL_RECEIPT"),
            PurchaseReceipt.objects.create(supplier_name="Supplier", warehouse=old_store),
        ):
            with self.subTest(document=document):
                self.restaurant.store_warehouse = new_store
                with self.assertRaisesMessage(ValidationError, "draft stock documents"):
                    self.restaurant.full_clean()
                document.delete()
