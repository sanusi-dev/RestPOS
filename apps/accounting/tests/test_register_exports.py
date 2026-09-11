import csv
import io
from datetime import date
from decimal import Decimal
from unittest.mock import patch

from django.urls import reverse

from apps.accounting.models import GLEntry

from .test_views import AccountingViewTestBase


def read_csv(response):
    return parse_csv(b"".join(response.streaming_content))


def parse_csv(raw):
    return list(csv.reader(io.StringIO(raw.decode("utf-8-sig"))))


class GLEntryExportTest(AccountingViewTestBase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()

        def post(voucher_type, voucher_no):
            GLEntry.post(
                posting_date=date.today(),
                rows=[
                    {"account": cls.sales, "credit": Decimal("1000"), "against": "Cash"},
                    {"account": cls.cash, "debit": Decimal("1000"), "against": "Sales"},
                ],
                voucher_type=voucher_type,
                voucher_no=voucher_no,
            )

        post("Order", "INV-1")
        post("Journal Entry", "JE-1")

    def test_export_returns_bom_header_and_filtered_rows(self):
        url = reverse("accounting:gl_entry_list")
        self.client.force_login(self.admin)
        page = self.client.get(url, {"voucher_type": "Order"})
        response = self.client.get(url, {"voucher_type": "Order", "export": "csv"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "text/csv")
        self.assertIn("voucher-type-Order", response["Content-Disposition"])
        raw = b"".join(response.streaming_content)
        self.assertTrue(raw.startswith(b"\xef\xbb\xbf"))
        rows = parse_csv(raw)
        self.assertEqual(
            rows[0],
            [
                "Posting date",
                "Account",
                "Debit",
                "Credit",
                "Against",
                "Voucher type",
                "Voucher no",
                "Fiscal year",
                "Cancelled",
            ],
        )
        page_vouchers = {(entry.voucher_type, entry.voucher_no) for entry in page.context["entries"]}
        self.assertEqual({(row[5], row[6]) for row in rows[1:]}, page_vouchers)
        self.assertEqual(len(rows), 3)
        debit_row = next(row for row in rows[1:] if row[1] == "Cash")
        self.assertEqual(Decimal(debit_row[2]), Decimal("1000.00"))
        self.assertEqual(Decimal(debit_row[3]), Decimal("0.00"))

    def test_empty_filter_exports_headers_only(self):
        self.client.force_login(self.admin)
        response = self.client.get(
            reverse("accounting:gl_entry_list"), {"voucher_type": "No-Such-Type", "export": "csv"}
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(read_csv(response)), 1)

    def test_row_cap(self):
        url = reverse("accounting:gl_entry_list")
        self.client.force_login(self.admin)
        with patch("apps.utils.csv_export.EXPORT_ROW_CAP", 3):
            self.assertEqual(self.client.get(url, {"export": "csv"}).status_code, 400)
        with patch("apps.utils.csv_export.EXPORT_ROW_CAP", 4):
            response = self.client.get(url, {"export": "csv"})
            self.assertEqual(response.status_code, 200)
            self.assertEqual(len(read_csv(response)), 5)

    def test_permission_gates_match_page(self):
        url = reverse("accounting:gl_entry_list")
        self.client.force_login(self.cashier)
        self.assertEqual(self.client.get(url).status_code, 403)
        self.assertEqual(self.client.get(url, {"export": "csv"}).status_code, 403)
        self.client.logout()
        self.assertEqual(self.client.get(url).status_code, 302)
        self.assertEqual(self.client.get(url, {"export": "csv"}).status_code, 302)
