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

