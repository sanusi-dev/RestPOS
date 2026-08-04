from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth.models import Group
from django.test import TestCase
from django.urls import reverse

from apps.inventory.models import (
    UOM,
    Item,
    ItemGroup,
    PurchaseReceipt,
    PurchaseReceiptItem,
    StockEntry,
    StockEntryDetail,
    Warehouse,
)
from apps.settings.models import Restaurant
from apps.users.models import CustomUser


class InventoryViewTestBase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = CustomUser.objects.create_user(
            username="admin@test.com", password="testpass123", email="admin@test.com"
        )
        mgr, _ = Group.objects.get_or_create(name="RestPOS Manager")
        cls.user.groups.add(mgr)
        cls.uom = UOM.objects.create(name="Nos")
        cls.group = ItemGroup.objects.create(name="Food")
        cls.warehouse = Warehouse.objects.create(name="Main Store")
        Restaurant.objects.create(company="Test Restaurant", store_warehouse=cls.warehouse)
        cls.item = Item.objects.create(
            item_name="Jollof Rice",
            item_group=cls.group,
            stock_uom=cls.uom,
            department="FOOD",
            is_purchase_item=True,
        )

    def setUp(self):
        self.client.login(username="admin@test.com", password="testpass123")


class TestLoginRequired(TestCase):
    def test_dashboard_requires_login(self):
        response = self.client.get(reverse("inventory:dashboard"))
        self.assertEqual(response.status_code, 302)

    def test_uom_list_requires_login(self):
        response = self.client.get(reverse("inventory:uom_list"))
        self.assertEqual(response.status_code, 302)

    def test_item_list_requires_login(self):
        response = self.client.get(reverse("inventory:item_list"))
        self.assertEqual(response.status_code, 302)

    def test_stock_entry_list_requires_login(self):
        response = self.client.get(reverse("inventory:stock_entry_list"))
        self.assertEqual(response.status_code, 302)

    def test_purchase_receipt_list_requires_login(self):
        response = self.client.get(reverse("inventory:purchase_receipt_list"))
        self.assertEqual(response.status_code, 302)


class TestDashboardView(InventoryViewTestBase):
    def test_dashboard_200(self):
        response = self.client.get(reverse("inventory:dashboard"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Inventory")


class TestUOMViews(InventoryViewTestBase):
    def test_uom_list_200(self):
        response = self.client.get(reverse("inventory:uom_list"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Nos")

    def test_uom_create_get(self):
        response = self.client.get(reverse("inventory:uom_create"))
        self.assertEqual(response.status_code, 200)

    def test_uom_create_post(self):
        response = self.client.post(reverse("inventory:uom_create"), {"name": "TestUnit"})
        self.assertRedirects(response, reverse("inventory:uom_list"))
        self.assertTrue(UOM.objects.filter(name="TestUnit").exists())

    def test_uom_update_get(self):
        response = self.client.get(reverse("inventory:uom_update", kwargs={"pk": self.uom.pk}))
        self.assertEqual(response.status_code, 200)

    def test_uom_update_post(self):
        response = self.client.post(
            reverse("inventory:uom_update", kwargs={"pk": self.uom.pk}),
            {"name": "Pieces"},
        )
        self.assertRedirects(response, reverse("inventory:uom_list"))
        self.uom.refresh_from_db()
        self.assertEqual(self.uom.name, "Pieces")


class TestItemGroupViews(InventoryViewTestBase):
    def test_item_group_list_200(self):
        response = self.client.get(reverse("inventory:item_group_list"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Food")

    def test_item_group_create_post(self):
        response = self.client.post(
            reverse("inventory:item_group_create"),
            {"name": "Beverages", "description": ""},
        )
        self.assertRedirects(response, reverse("inventory:item_group_list"))
        self.assertTrue(ItemGroup.objects.filter(name="Beverages").exists())

    def test_item_group_detail_200(self):
        response = self.client.get(reverse("inventory:item_group_detail", kwargs={"pk": self.group.pk}))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Food")


class TestWarehouseViews(InventoryViewTestBase):
    def test_warehouse_list_200(self):
        response = self.client.get(reverse("inventory:warehouse_list"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Main Store")

    def test_warehouse_create_get(self):
        response = self.client.get(reverse("inventory:warehouse_create"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'name="name"')

    def test_warehouse_create_post(self):
        response = self.client.post(
            reverse("inventory:warehouse_create"),
            {
                "name": "Bar Store",
                "disabled": "",
            },
        )
        self.assertRedirects(response, reverse("inventory:warehouse_list"))
        wh = Warehouse.objects.get(name="Bar Store")
        self.assertEqual(wh.name, "Bar Store")

    def test_warehouse_detail_200(self):
        response = self.client.get(reverse("inventory:warehouse_detail", kwargs={"pk": self.warehouse.pk}))
        self.assertEqual(response.status_code, 200)


class TestItemViews(InventoryViewTestBase):
    def test_item_list_200(self):
        response = self.client.get(reverse("inventory:item_list"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Jollof Rice")

    def test_item_list_filter_by_department(self):
        response = self.client.get(reverse("inventory:item_list"), {"department": "FOOD"})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Jollof Rice")

    def test_item_list_filter_sellable(self):
        self.item.is_sales_item = True
        self.item.save()
        response = self.client.get(reverse("inventory:item_list"), {"sellable": "1"})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Jollof Rice")

    def test_item_list_search(self):
        response = self.client.get(reverse("inventory:item_list"), {"q": "Jollof"})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Jollof Rice")

    def test_item_detail_200(self):
        response = self.client.get(reverse("inventory:item_detail", kwargs={"pk": self.item.pk}))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Jollof Rice")

    def test_item_detail_shows_variants(self):
        template = Item.objects.create(
            item_name="Chicken Template",
            item_group=self.item.item_group,
            stock_uom=self.item.stock_uom,
            department="FOOD",
            has_variants=True,
            is_stock_item=False,
        )
        Item.objects.create(
            item_name="Quarter Chicken Test",
            item_group=self.item.item_group,
            stock_uom=self.item.stock_uom,
            department="FOOD",
            variant_of=template,
            is_sales_item=True,
        )
        response = self.client.get(reverse("inventory:item_detail", kwargs={"pk": template.pk}))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Quarter Chicken Test")
        self.assertContains(response, "Variants")

    def test_item_detail_404(self):
        response = self.client.get(reverse("inventory:item_detail", kwargs={"pk": 9999}))
        self.assertEqual(response.status_code, 404)


class TestStockEntryViews(InventoryViewTestBase):
    def test_stock_entry_list_200(self):
        response = self.client.get(reverse("inventory:stock_entry_list"))
        self.assertEqual(response.status_code, 200)

    def test_stock_entry_create_post(self):
        response = self.client.post(
            reverse("inventory:stock_entry_create"),
            {
                "purpose": "MATERIAL_RECEIPT",
                "posting_date": "2025-01-15",
                "remarks": "",
                "items-TOTAL_FORMS": "0",
                "items-INITIAL_FORMS": "0",
                "items-MIN_NUM_FORMS": "0",
                "items-MAX_NUM_FORMS": "1000",
            },
        )
        entry = StockEntry.objects.filter(purpose="MATERIAL_RECEIPT").first()
        self.assertIsNotNone(entry)
        self.assertRedirects(response, reverse("inventory:stock_entry_detail", kwargs={"pk": entry.pk}))

    def test_stock_entry_create_rolls_back_parent_when_formset_save_fails(self):
        with (
            patch("apps.inventory.views.StockEntryDetailFormSet.save", side_effect=RuntimeError("failed")),
            self.assertRaisesMessage(RuntimeError, "failed"),
        ):
            self.client.post(
                reverse("inventory:stock_entry_create"),
                {
                    "purpose": "MATERIAL_RECEIPT",
                    "posting_date": "2025-01-15",
                    "remarks": "atomic failure",
                    "items-TOTAL_FORMS": "0",
                    "items-INITIAL_FORMS": "0",
                    "items-MIN_NUM_FORMS": "0",
                    "items-MAX_NUM_FORMS": "1000",
                },
            )
        self.assertFalse(StockEntry.objects.filter(remarks="atomic failure").exists())

    def test_stock_entry_detail_200(self):
        entry = StockEntry.objects.create(purpose="MATERIAL_RECEIPT")
        StockEntryDetail.objects.create(
            stock_entry=entry,
            item=self.item,
            target_warehouse=self.warehouse,
            qty=Decimal("10"),
            basic_rate=Decimal("100"),
        )
        response = self.client.get(reverse("inventory:stock_entry_detail", kwargs={"pk": entry.pk}))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Submit")

    def test_stock_entry_submit_post(self):
        entry = StockEntry.objects.create(purpose="MATERIAL_RECEIPT")
        StockEntryDetail.objects.create(
            stock_entry=entry,
            item=self.item,
            target_warehouse=self.warehouse,
            qty=Decimal("10"),
            basic_rate=Decimal("100"),
        )
        response = self.client.post(reverse("inventory:stock_entry_submit", kwargs={"pk": entry.pk}))
        self.assertRedirects(response, reverse("inventory:stock_entry_detail", kwargs={"pk": entry.pk}))
        entry.refresh_from_db()
        self.assertEqual(entry.status, "SUBMITTED")

    def test_stock_entry_submit_requires_post(self):
        entry = StockEntry.objects.create(purpose="MATERIAL_RECEIPT")
        response = self.client.get(reverse("inventory:stock_entry_submit", kwargs={"pk": entry.pk}))
        self.assertEqual(response.status_code, 405)

    def test_stock_entry_submit_validation_error_is_visible(self):
        entry = StockEntry.objects.create(purpose="MATERIAL_TRANSFER")
        StockEntryDetail.objects.create(stock_entry=entry, item=self.item, qty=Decimal("10"))
        response = self.client.post(reverse("inventory:stock_entry_submit", kwargs={"pk": entry.pk}), follow=True)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Bar / POS sales warehouse")
        entry.refresh_from_db()
        self.assertEqual(entry.status, "DRAFT")

    def test_stock_entry_cancel_post(self):
        entry = StockEntry.objects.create(purpose="MATERIAL_RECEIPT")
        StockEntryDetail.objects.create(
            stock_entry=entry,
            item=self.item,
            target_warehouse=self.warehouse,
            qty=Decimal("10"),
            basic_rate=Decimal("100"),
        )
        entry.submit()
        response = self.client.post(reverse("inventory:stock_entry_cancel", kwargs={"pk": entry.pk}))
        self.assertRedirects(response, reverse("inventory:stock_entry_detail", kwargs={"pk": entry.pk}))
        entry.refresh_from_db()
        self.assertEqual(entry.status, "CANCELLED")

    def test_stock_entry_cancel_requires_post(self):
        entry = StockEntry.objects.create(purpose="MATERIAL_RECEIPT")
        response = self.client.get(reverse("inventory:stock_entry_cancel", kwargs={"pk": entry.pk}))
        self.assertEqual(response.status_code, 405)


class TestReconciliationViews(InventoryViewTestBase):
    def test_reconciliation_list_200(self):
        response = self.client.get(reverse("inventory:reconciliation_list"))
        self.assertEqual(response.status_code, 200)

    def test_reconciliation_create_rolls_back_parent_when_formset_save_fails(self):
        from apps.inventory.models import StockReconciliation

        with (
            patch("apps.inventory.views.StockReconciliationItemFormSet.save", side_effect=RuntimeError("failed")),
            self.assertRaisesMessage(RuntimeError, "failed"),
        ):
            self.client.post(
                reverse("inventory:reconciliation_create"),
                {
                    "purpose": "RECONCILIATION",
                    "reason": "PHYSICAL_COUNT",
                    "posting_date": "2025-01-15",
                    "warehouse": self.warehouse.pk,
                    "remarks": "atomic failure",
                    "items-TOTAL_FORMS": "0",
                    "items-INITIAL_FORMS": "0",
                    "items-MIN_NUM_FORMS": "0",
                    "items-MAX_NUM_FORMS": "1000",
                },
            )
        self.assertFalse(StockReconciliation.objects.filter(remarks="atomic failure").exists())

    def test_reconciliation_detail_200(self):
        from apps.inventory.models import StockReconciliation

        rec = StockReconciliation.objects.create(warehouse=self.warehouse)
        response = self.client.get(reverse("inventory:reconciliation_detail", kwargs={"pk": rec.pk}))
        self.assertEqual(response.status_code, 200)

    def test_reconciliation_submit_requires_post(self):
        from apps.inventory.models import StockReconciliation

        rec = StockReconciliation.objects.create(warehouse=self.warehouse)
        response = self.client.get(reverse("inventory:reconciliation_submit", kwargs={"pk": rec.pk}))
        self.assertEqual(response.status_code, 405)

    def test_reconciliation_submit_validation_error_is_visible(self):
        from apps.inventory.models import StockReconciliation

        rec = StockReconciliation.objects.create(warehouse=self.warehouse, reason="PHYSICAL_COUNT")
        response = self.client.post(reverse("inventory:reconciliation_submit", kwargs={"pk": rec.pk}), follow=True)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Add at least one item")

    def test_reconciliation_filters_by_reason(self):
        from apps.inventory.models import StockReconciliation

        physical = StockReconciliation.objects.create(warehouse=self.warehouse, reason="PHYSICAL_COUNT")
        correction = StockReconciliation.objects.create(warehouse=self.warehouse, reason="CORRECTION")
        response = self.client.get(reverse("inventory:reconciliation_list"), {"reason": "CORRECTION"})
        self.assertContains(response, reverse("inventory:reconciliation_detail", kwargs={"pk": correction.pk}))
        self.assertNotContains(response, reverse("inventory:reconciliation_detail", kwargs={"pk": physical.pk}))


class TestReportViews(InventoryViewTestBase):
    def test_stock_ledger_list_200(self):
        response = self.client.get(reverse("inventory:stock_ledger_list"))
        self.assertEqual(response.status_code, 200)

    def test_stock_ledger_list_filter_by_item(self):
        response = self.client.get(reverse("inventory:stock_ledger_list"), {"item": str(self.item.pk)})
        self.assertEqual(response.status_code, 200)

    def test_stock_balance_list_200(self):
        response = self.client.get(reverse("inventory:stock_balance_list"))
        self.assertEqual(response.status_code, 200)

    def test_stock_balance_list_filter_by_warehouse(self):
        response = self.client.get(reverse("inventory:stock_balance_list"), {"warehouse": str(self.warehouse.pk)})
        self.assertEqual(response.status_code, 200)


class TestPurchaseReceiptViews(InventoryViewTestBase):
    def test_purchase_receipt_list_200(self):
        response = self.client.get(reverse("inventory:purchase_receipt_list"))
        self.assertEqual(response.status_code, 200)

    def test_purchase_receipt_create_get(self):
        response = self.client.get(reverse("inventory:purchase_receipt_create"))
        self.assertEqual(response.status_code, 200)

    def test_purchase_receipt_create_post(self):
        response = self.client.post(
            reverse("inventory:purchase_receipt_create"),
            {
                "supplier_name": "ABC Suppliers",
                "supplier_delivery_note": "DN-001",
                "posting_date": "2025-01-15",
                "remarks": "",
                "items-TOTAL_FORMS": "0",
                "items-INITIAL_FORMS": "0",
                "items-MIN_NUM_FORMS": "0",
                "items-MAX_NUM_FORMS": "1000",
            },
        )
        receipt = PurchaseReceipt.objects.filter(supplier_name="ABC Suppliers").first()
        self.assertIsNotNone(receipt)
        self.assertRedirects(response, reverse("inventory:purchase_receipt_detail", kwargs={"pk": receipt.pk}))

    def test_purchase_receipt_create_rolls_back_parent_when_formset_save_fails(self):
        with (
            patch("apps.inventory.views.PurchaseReceiptItemFormSet.save", side_effect=RuntimeError("failed")),
            self.assertRaisesMessage(RuntimeError, "failed"),
        ):
            self.client.post(
                reverse("inventory:purchase_receipt_create"),
                {
                    "supplier_name": "Atomic Failure",
                    "supplier_delivery_note": "",
                    "posting_date": "2025-01-15",
                    "remarks": "",
                    "items-TOTAL_FORMS": "0",
                    "items-INITIAL_FORMS": "0",
                    "items-MIN_NUM_FORMS": "0",
                    "items-MAX_NUM_FORMS": "1000",
                },
            )
        self.assertFalse(PurchaseReceipt.objects.filter(supplier_name="Atomic Failure").exists())

    def test_purchase_receipt_detail_200(self):
        receipt = PurchaseReceipt.objects.create(
            supplier_name="ABC Suppliers",
            warehouse=self.warehouse,
        )
        PurchaseReceiptItem.objects.create(
            purchase_receipt=receipt,
            item=self.item,
            received_qty=Decimal("10"),
            rate=Decimal("100"),
        )
        response = self.client.get(reverse("inventory:purchase_receipt_detail", kwargs={"pk": receipt.pk}))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Submit")

    def test_purchase_receipt_submit_post(self):
        receipt = PurchaseReceipt.objects.create(
            supplier_name="ABC Suppliers",
            warehouse=self.warehouse,
        )
        PurchaseReceiptItem.objects.create(
            purchase_receipt=receipt,
            item=self.item,
            received_qty=Decimal("10"),
            rate=Decimal("100"),
        )
        response = self.client.post(reverse("inventory:purchase_receipt_submit", kwargs={"pk": receipt.pk}))
        self.assertRedirects(response, reverse("inventory:purchase_receipt_detail", kwargs={"pk": receipt.pk}))
        receipt.refresh_from_db()
        self.assertEqual(receipt.status, "SUBMITTED")

    def test_purchase_receipt_submit_requires_post(self):
        receipt = PurchaseReceipt.objects.create(
            supplier_name="ABC Suppliers",
            warehouse=self.warehouse,
        )
        response = self.client.get(reverse("inventory:purchase_receipt_submit", kwargs={"pk": receipt.pk}))
        self.assertEqual(response.status_code, 405)

    def test_purchase_receipt_submit_validation_error_is_visible(self):
        receipt = PurchaseReceipt.objects.create(supplier_name="ABC Suppliers", warehouse=self.warehouse)
        response = self.client.post(
            reverse("inventory:purchase_receipt_submit", kwargs={"pk": receipt.pk}), follow=True
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Add at least one item")
        receipt.refresh_from_db()
        self.assertEqual(receipt.status, "DRAFT")

    def test_purchase_receipt_cancel_post(self):
        receipt = PurchaseReceipt.objects.create(
            supplier_name="ABC Suppliers",
            warehouse=self.warehouse,
        )
        PurchaseReceiptItem.objects.create(
            purchase_receipt=receipt,
            item=self.item,
            received_qty=Decimal("10"),
            rate=Decimal("100"),
        )
        receipt.submit()
        response = self.client.post(reverse("inventory:purchase_receipt_cancel", kwargs={"pk": receipt.pk}))
        self.assertRedirects(response, reverse("inventory:purchase_receipt_detail", kwargs={"pk": receipt.pk}))
        receipt.refresh_from_db()
        self.assertEqual(receipt.status, "CANCELLED")

    def test_purchase_receipt_cancel_requires_post(self):
        receipt = PurchaseReceipt.objects.create(
            supplier_name="ABC Suppliers",
            warehouse=self.warehouse,
        )
        response = self.client.get(reverse("inventory:purchase_receipt_cancel", kwargs={"pk": receipt.pk}))
        self.assertEqual(response.status_code, 405)
