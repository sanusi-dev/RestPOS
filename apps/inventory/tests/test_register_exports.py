import csv
import io
from decimal import Decimal
from unittest.mock import patch

from django.urls import reverse

from apps.inventory.models import StockLedgerEntry
from apps.users.models import CustomUser

from .test_views import InventoryViewTestBase


def read_csv(response):
    return parse_csv(b"".join(response.streaming_content))


def parse_csv(raw):
    return list(csv.reader(io.StringIO(raw.decode("utf-8-sig"))))


class StockLedgerExportTest(InventoryViewTestBase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.plain_user = CustomUser.objects.create_user(username="plain", password="testpass123")

    def _receive(self, qty, rate, **kwargs):
        return StockLedgerEntry.create_entry(
            self.item,
            self.warehouse,
            quantity=qty,
            unit_rate=Decimal(rate),
            voucher_type="Purchase Receipt",
            voucher_no="PR-1",
            **kwargs,
        )

    def test_export_returns_bom_header_and_filtered_rows(self):
        self._receive(Decimal("5"), "100")
        self._receive(Decimal("3"), "120")
        url = reverse("inventory:stock_ledger_list")
        page = self.client.get(url, {"item": str(self.item.pk)})
        response = self.client.get(url, {"item": str(self.item.pk), "export": "csv"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "text/csv")
        self.assertIn("attachment", response["Content-Disposition"])
        self.assertIn(f"item-{self.item.pk}", response["Content-Disposition"])
        raw = b"".join(response.streaming_content)
        self.assertTrue(raw.startswith(b"\xef\xbb\xbf"))
        rows = parse_csv(raw)
        self.assertEqual(
            rows[0],
            [
                "Posting date",
                "Item",
                "Warehouse",
                "Voucher type",
                "Voucher no",
                "Qty",
                "Unit rate",
                "Value change",
                "Variance type",
                "Variance amount",
            ],
        )
        page_ids = {str(entry.pk) for entry in page.context["entries"]}
        self.assertEqual(len(rows), len(page_ids) + 1)
        quantities = sorted(Decimal(row[5]) for row in rows[1:])
        self.assertEqual(quantities, [Decimal("3.00"), Decimal("5.00")])
        value_row = next(row for row in rows[1:] if Decimal(row[5]) == Decimal("5.00"))
        self.assertEqual(Decimal(value_row[7]), Decimal("500.00"))

    def test_empty_filter_exports_headers_only(self):
        response = self.client.get(reverse("inventory:stock_ledger_list"), {"item": "999999", "export": "csv"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(read_csv(response)), 1)

    def test_row_cap(self):
        for _ in range(3):
            self._receive(Decimal("1"), "100")
        url = reverse("inventory:stock_ledger_list")
        with patch("apps.utils.csv_export.EXPORT_ROW_CAP", 2):
            self.assertEqual(self.client.get(url, {"export": "csv"}).status_code, 400)
        with patch("apps.utils.csv_export.EXPORT_ROW_CAP", 3):
            response = self.client.get(url, {"export": "csv"})
            self.assertEqual(response.status_code, 200)
            self.assertEqual(len(read_csv(response)), 4)

    def test_permission_gates_match_page(self):
        url = reverse("inventory:stock_ledger_list")
        self.client.force_login(self.plain_user)
        self.assertEqual(self.client.get(url).status_code, 403)
        self.assertEqual(self.client.get(url, {"export": "csv"}).status_code, 403)
        self.client.logout()
        self.assertEqual(self.client.get(url).status_code, 302)
        self.assertEqual(self.client.get(url, {"export": "csv"}).status_code, 302)
