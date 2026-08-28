from datetime import date
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.test import TestCase

from apps.inventory.forms import StockReconciliationForm
from apps.inventory.models import (
    UOM,
    Bin,
    Item,
    ItemGroup,
    StockLedgerEntry,
    StockReconciliation,
    StockReconciliationItem,
    Warehouse,
)
from apps.inventory.services import cancel_stock_reconciliation, submit_stock_reconciliation
from apps.settings.models import ProductionUnit


class StockReconciliationTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.uom = UOM.objects.create(name="Nos")
        cls.group = ItemGroup.objects.create(name="Food")
        cls.kitchen = Warehouse.objects.create(name="Kitchen")
        ProductionUnit.objects.create(name="Kitchen", department="FOOD", warehouse=cls.kitchen)
        cls.item = Item.objects.create(
            item_name="Rice", item_group=cls.group, stock_uom=cls.uom, department="FOOD", is_stock_item=True
        )

    def make_reconciliation(self, **kwargs):
        defaults = {"warehouse": self.kitchen, "reason": "PHYSICAL_COUNT"}
        defaults.update(kwargs)
        return StockReconciliation.objects.create(**defaults)

    def test_all_reason_choices_exist_and_remarks_date_are_flexible(self):
        choices = {value for value, _label in StockReconciliation._meta.get_field("reason").choices}
        self.assertEqual(choices, {"PHYSICAL_COUNT", "CONSUMPTION", "WASTE_DAMAGE", "CORRECTION"})
        rec = self.make_reconciliation(posting_date=date(2024, 2, 3), remarks="")
        self.assertEqual(rec.posting_date, date(2024, 2, 3))

    def test_form_requires_explicit_reason(self):
        form = StockReconciliationForm(
            data={"purpose": "RECONCILIATION", "posting_date": "2024-02-03", "warehouse": self.kitchen.pk}
        )
        self.assertFalse(form.is_valid())
        self.assertIn("reason", form.errors)

    def test_submit_rereads_locked_current_qty(self):
        rec = self.make_reconciliation()
        line = StockReconciliationItem.objects.create(reconciliation=rec, item=self.item, qty=Decimal("8"))
        StockLedgerEntry.create_entry(self.item, self.kitchen, Decimal("5"), "Receipt", "1", unit_rate=Decimal("100"))
        # The line snapshot is intentionally stale; submit must lock and re-read the current Bin.
        self.assertEqual(line.current_qty, Decimal("0"))
        submit_stock_reconciliation(rec)
        line.refresh_from_db()
        self.assertEqual(line.current_qty, Decimal("5"))
        self.assertEqual(Bin.objects.get(item=self.item, warehouse=self.kitchen).actual_qty, Decimal("8"))

    def test_non_opening_count_cannot_be_below_reserved_qty(self):
        bin_obj = Bin.objects.create(item=self.item, warehouse=self.kitchen, actual_qty=10, reserved_qty=4)
        rec = self.make_reconciliation()
        StockReconciliationItem.objects.create(reconciliation=rec, item=self.item, qty=Decimal("3"))
        with self.assertRaisesMessage(ValidationError, "reserved quantity"):
            submit_stock_reconciliation(rec)
        bin_obj.refresh_from_db()
        self.assertEqual(bin_obj.actual_qty, Decimal("10"))

    def test_consumption_requires_kitchen_and_food(self):
        other = Warehouse.objects.create(name="Other")
        rec = self.make_reconciliation(reason="CONSUMPTION", warehouse=other)
        StockReconciliationItem.objects.create(reconciliation=rec, item=self.item, qty=0)
        with self.assertRaisesMessage(ValidationError, "configured Kitchen"):
            submit_stock_reconciliation(rec)

    def test_disabled_or_non_stock_item_rejected(self):
        self.item.disabled = True
        self.item.save()
        rec = self.make_reconciliation()
        StockReconciliationItem.objects.create(reconciliation=rec, item=self.item, qty=0)
        with self.assertRaisesMessage(ValidationError, "enabled stock item"):
            submit_stock_reconciliation(rec)

    def test_cancel_reverses_atomically_and_is_idempotent(self):
        StockLedgerEntry.create_entry(self.item, self.kitchen, Decimal("5"), "Receipt", "1", unit_rate=Decimal("100"))
        rec = self.make_reconciliation()
        StockReconciliationItem.objects.create(reconciliation=rec, item=self.item, qty=Decimal("8"))
        submit_stock_reconciliation(rec)
        cancel_stock_reconciliation(rec)
        cancel_stock_reconciliation(rec)
        self.assertEqual(Bin.objects.get(item=self.item, warehouse=self.kitchen).actual_qty, Decimal("5"))
