import csv
import io
from datetime import date, timedelta
from decimal import Decimal
from unittest.mock import patch

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.reports.models import DailyPnL

from .helpers import DailyPnLTestMixin


def read_csv(response):
    return parse_csv(b"".join(response.streaming_content))


def parse_csv(raw):
    return list(csv.reader(io.StringIO(raw.decode("utf-8-sig"))))


class DailyPnLExportTest(DailyPnLTestMixin, TestCase):
    @classmethod
    def setUpTestData(cls):
        cls._setup_pnl_world()

    def _create_pnl(self, day_offset, status, food="10000", drinks="5000", net="15000", gp="9000", np_="4000"):
        return DailyPnL.objects.create(
            business_date=date.today() - timedelta(days=day_offset),
            period_start=timezone.now() - timedelta(days=day_offset + 1),
            period_end=timezone.now() - timedelta(days=day_offset),
            status=status,
            gross_sales_food=Decimal(food),
            gross_sales_drinks=Decimal(drinks),
            net_sales=Decimal(net),
            gross_profit=Decimal(gp),
            net_profit=Decimal(np_),
        )

    def test_export_returns_bom_header_and_filtered_rows(self):
        self._create_pnl(1, DailyPnL.SUBMITTED)
        self._create_pnl(2, DailyPnL.SUBMITTED, food="20000", net="25000", gp="15000", np_="8000")
        self._create_pnl(3, DailyPnL.DRAFT)
        url = reverse("reports:daily_pnl_list")
        self.client.force_login(self.manager)
        page = self.client.get(url, {"status": "SUBMITTED"})
        response = self.client.get(url, {"status": "SUBMITTED", "export": "csv"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "text/csv")
        self.assertIn("status-SUBMITTED", response["Content-Disposition"])
        raw = b"".join(response.streaming_content)
        self.assertTrue(raw.startswith(b"\xef\xbb\xbf"))
        rows = parse_csv(raw)
        self.assertEqual(
            rows[0],
            ["Business date", "Status", "Food sales", "Drinks sales", "Net sales", "Gross profit", "Net profit"],
        )
        page_dates = {entry.business_date.isoformat() for entry in page.context["entries"]}
        self.assertEqual({row[0] for row in rows[1:]}, page_dates)
        self.assertEqual(len(rows), 3)
        for row in rows[1:]:
            for cell in row[2:]:
                Decimal(cell)

    def test_empty_filter_exports_headers_only(self):
        self.client.force_login(self.manager)
        response = self.client.get(reverse("reports:daily_pnl_list"), {"status": "CANCELLED", "export": "csv"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(read_csv(response)), 1)

    def test_row_cap(self):
        for offset in range(1, 4):
            self._create_pnl(offset, DailyPnL.SUBMITTED)
        url = reverse("reports:daily_pnl_list")
        self.client.force_login(self.manager)
        with patch("apps.utils.csv_export.EXPORT_ROW_CAP", 2):
            self.assertEqual(self.client.get(url, {"export": "csv"}).status_code, 400)
        with patch("apps.utils.csv_export.EXPORT_ROW_CAP", 3):
            response = self.client.get(url, {"export": "csv"})
            self.assertEqual(response.status_code, 200)
            self.assertEqual(len(read_csv(response)), 4)

    def test_permission_gates_match_page(self):
        url = reverse("reports:daily_pnl_list")
        self.client.force_login(self.user)
        self.assertIn(self.client.get(url).status_code, (302, 403))
        self.assertIn(self.client.get(url, {"export": "csv"}).status_code, (302, 403))
        self.client.logout()
        self.assertEqual(self.client.get(url).status_code, 302)
        self.assertEqual(self.client.get(url, {"export": "csv"}).status_code, 302)
