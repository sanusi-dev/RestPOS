"""Daily P&L model guards."""

from datetime import date
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.test import TestCase

from apps.reports.models import DailyPnL, PnLConfiguration

from .helpers import DailyPnLTestMixin


class DailyPnLModelTest(DailyPnLTestMixin, TestCase):
    @classmethod
    def setUpTestData(cls):
        cls._setup_pnl_world()

    def test_one_sided_electricity_rejected(self):
        with self.assertRaises(ValidationError):
            DailyPnL.objects.create(business_date=date.today(), electricity_opening=Decimal("1"))

    def test_closing_below_opening_rejected(self):
        with self.assertRaises(ValidationError):
            DailyPnL.objects.create(
                business_date=date.today(),
                electricity_opening=Decimal("10"),
                electricity_closing=Decimal("5"),
            )

    def test_cannot_edit_submitted(self):
        pnl = DailyPnL.objects.create(business_date=date.today())
        pnl.submit(actor=self.manager)
        pnl.remarks = "nope"
        with self.assertRaises(ValidationError):
            pnl.save()

    def test_config_load_creates_singleton(self):
        PnLConfiguration.objects.all().delete()
        config = PnLConfiguration.load()
        self.assertEqual(config.business_day_start_hour, 0)
        self.assertTrue(config.include_cash_variance)
        self.assertEqual(PnLConfiguration.objects.count(), 1)
