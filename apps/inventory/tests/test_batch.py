from datetime import date, timedelta
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.test import TestCase

from apps.inventory.models import UOM, Batch, Item, ItemGroup, StockLedgerEntry, Warehouse
from apps.settings.models import Branch


class BatchTestBase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.uom = UOM.objects.create(name="Nos")
        cls.group = ItemGroup.objects.create(name="Food")
        cls.item = Item.objects.create(
            item_code="MILK001",
            item_name="Milk",
            item_group=cls.group,
            stock_uom=cls.uom,
            department="FOOD",
            has_batch_no=True,
            has_expiry_date=True,
            shelf_life_in_days=30,
        )


class BatchModelTest(BatchTestBase):
    def test_str_returns_batch_id(self):
        batch = Batch.objects.create(batch_id="BATCH001", item=self.item)
        self.assertEqual(str(batch), "BATCH001")

    def test_batch_id_unique(self):
        from django.db.utils import IntegrityError

        Batch.objects.create(batch_id="BATCH001", item=self.item)
        with self.assertRaises(IntegrityError):
            Batch.objects.create(batch_id="BATCH001", item=self.item)

    def test_default_batch_qty(self):
        batch = Batch.objects.create(batch_id="B002", item=self.item)
        self.assertEqual(batch.batch_qty, Decimal("0"))

    def test_batch_qty_not_editable(self):
        batch = Batch.objects.create(batch_id="B003", item=self.item)
        self.assertFalse(batch._meta.get_field("batch_qty").editable)

    def test_create_with_dates(self):
        mfg = date(2025, 1, 1)
        exp = date(2025, 1, 31)
        batch = Batch.objects.create(batch_id="B004", item=self.item, manufacturing_date=mfg, expiry_date=exp)
        self.assertEqual(batch.manufacturing_date, mfg)
        self.assertEqual(batch.expiry_date, exp)

    def test_update(self):
        batch = Batch.objects.create(batch_id="B005", item=self.item)
        batch.expiry_date = date(2025, 12, 31)
        batch.save()
        batch.refresh_from_db()
        self.assertEqual(batch.expiry_date, date(2025, 12, 31))

    def test_delete(self):
        batch = Batch.objects.create(batch_id="B006", item=self.item)
        pk = batch.pk
        batch.delete()
        self.assertFalse(Batch.objects.filter(pk=pk).exists())


class BatchValidationTest(BatchTestBase):
    def test_non_batch_item_raises(self):
        non_batch_item = Item.objects.create(
            item_code="SUGAR001",
            item_name="Sugar",
            item_group=self.group,
            stock_uom=self.uom,
            department="FOOD",
            has_batch_no=False,
        )
        batch = Batch(batch_id="B010", item=non_batch_item)
        with self.assertRaises(ValidationError):
            batch.full_clean()

    def test_batch_item_ok(self):
        batch = Batch(batch_id="B011", item=self.item)
        batch.full_clean()


class BatchExpiryAutoCalcTest(BatchTestBase):
    def test_expiry_auto_computed_from_mfg_and_shelf_life(self):
        mfg = date(2025, 6, 1)
        batch = Batch(batch_id="B020", item=self.item, manufacturing_date=mfg)
        batch.full_clean()
        batch.save()
        expected = mfg + timedelta(days=30)
        self.assertEqual(batch.expiry_date, expected)

    def test_existing_expiry_not_overwritten(self):
        mfg = date(2025, 6, 1)
        explicit = date(2025, 12, 31)
        batch = Batch(batch_id="B021", item=self.item, manufacturing_date=mfg, expiry_date=explicit)
        batch.full_clean()
        batch.save()
        self.assertEqual(batch.expiry_date, explicit)


class BatchQtyRecalcTest(BatchTestBase):
    def test_recalculate_qty_from_ledger(self):
        branch = Branch.objects.create(name="Branch B")
        wh = Warehouse.objects.create(name="Store B", branch=branch)
        batch = Batch.objects.create(batch_id="B030", item=self.item)

        StockLedgerEntry.create_entry(
            item=self.item,
            warehouse=wh,
            actual_qty=Decimal("10"),
            voucher_type="Stock Entry",
            voucher_no="SE1",
            voucher_detail_no=batch.batch_id,
        )
        batch.recalculate_qty()
        self.assertEqual(batch.batch_qty, Decimal("10"))

        StockLedgerEntry.create_entry(
            item=self.item,
            warehouse=wh,
            actual_qty=Decimal("-4"),
            voucher_type="Stock Entry",
            voucher_no="SE2",
            voucher_detail_no=batch.batch_id,
        )
        batch.recalculate_qty()
        self.assertEqual(batch.batch_qty, Decimal("6"))
