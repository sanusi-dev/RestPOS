import csv
import io
from decimal import Decimal
from unittest.mock import patch

from django.urls import reverse

from apps.orders.services import add_order_line, settle_order

from .test_backoffice_views import BackofficeViewTestBase


def read_csv(response):
    return parse_csv(b"".join(response.streaming_content))


def parse_csv(raw):
    return list(csv.reader(io.StringIO(raw.decode("utf-8-sig"))))


class OrderRegisterExportTest(BackofficeViewTestBase):
    def _settled(self, qty=2, rate="1500"):
        order = self._create_order()
        add_order_line(order, self.food_item, qty=qty, rate=Decimal(rate))
        settle_order(order, [{"mode_of_payment": self.cash.pk, "amount": str(qty * int(rate))}])
        return order

    def test_export_returns_bom_header_and_filtered_rows(self):
        first = self._settled(qty=2)
        self._settled(qty=1)
        self._create_order()
        url = reverse("orders:order_list")
        page = self.client.get(url, {"status": "SUBMITTED"})
        response = self.client.get(url, {"status": "SUBMITTED", "export": "csv"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "text/csv")
        self.assertIn("attachment", response["Content-Disposition"])
        self.assertIn("status-SUBMITTED", response["Content-Disposition"])
        raw = b"".join(response.streaming_content)
        self.assertTrue(raw.startswith(b"\xef\xbb\xbf"))
        rows = parse_csv(raw)
        self.assertEqual(
            rows[0],
            [
                "Invoice",
                "Order no",
                "Date",
                "Time",
                "Cashier",
                "Type",
                "Customer",
                "Status",
                "Net",
                "Grand",
                "Paid",
                "Change",
            ],
        )
        page_invoices = {order.invoice_number for order in page.context["orders"]}
        self.assertEqual({row[0] for row in rows[1:]}, page_invoices)
        self.assertEqual(len(rows), 3)
        first_row = next(row for row in rows[1:] if row[0] == first.invoice_number)
        self.assertEqual(Decimal(first_row[8]), Decimal("3000.00"))
        self.assertEqual(Decimal(first_row[9]), Decimal("3000.00"))
        self.assertEqual(Decimal(first_row[10]), Decimal("3000.00"))
        self.assertEqual(Decimal(first_row[11]), Decimal("0.00"))

    def test_empty_filter_exports_headers_only(self):
        response = self.client.get(reverse("orders:order_list"), {"status": "CANCELLED", "export": "csv"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(read_csv(response)), 1)

    def test_row_cap(self):
        self._settled()
        self._settled()
        self._settled()
        url = reverse("orders:order_list")
        with patch("apps.utils.csv_export.EXPORT_ROW_CAP", 2):
            self.assertEqual(self.client.get(url, {"export": "csv"}).status_code, 400)
        with patch("apps.utils.csv_export.EXPORT_ROW_CAP", 3):
            response = self.client.get(url, {"export": "csv"})
            self.assertEqual(response.status_code, 200)
            self.assertEqual(len(read_csv(response)), 4)

    def test_permission_gates_match_page(self):
        url = reverse("orders:order_list")
        self.client.force_login(self.cashier_user)
        self.assertEqual(self.client.get(url).status_code, 403)
        self.assertEqual(self.client.get(url, {"export": "csv"}).status_code, 403)
        self.client.logout()
        self.assertEqual(self.client.get(url).status_code, 302)
        self.assertEqual(self.client.get(url, {"export": "csv"}).status_code, 302)
