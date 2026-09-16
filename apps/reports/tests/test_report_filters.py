"""Fiscal-year vs custom-date resolution for the query reports."""

from datetime import timedelta

from django.test import RequestFactory, TestCase

from apps.accounting.tests.helpers import setup_chart_of_accounts
from apps.reports import report_filters
from apps.settings.models import Restaurant


class ReportPeriodFilterTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.restaurant = Restaurant.objects.create(company="Filter Co")
        cls.fy = setup_chart_of_accounts(cls.restaurant)["fiscal_year"]

    def _get(self, **params):
        return RequestFactory().get("/backoffice/reports/", params)

    def test_monthwise_no_params_defaults_to_current_year(self):
        fy, date_from, date_to = report_filters.monthwise_period(self._get())
        self.assertEqual(fy, self.fy)
        self.assertEqual(date_from, self.fy.year_start_date)
        self.assertEqual(date_to, self.fy.year_end_date)

    def test_monthwise_custom_dates_win_over_selected_year(self):
        custom_from = self.fy.year_start_date
        custom_to = self.fy.year_end_date - timedelta(days=1)
        fy, date_from, date_to = report_filters.monthwise_period(
            self._get(fiscal_year=str(self.fy.pk), **{"from": custom_from.isoformat(), "to": custom_to.isoformat()})
        )
        self.assertIsNone(fy)
        self.assertEqual(date_from, custom_from)
        self.assertEqual(date_to, custom_to)

    def test_monthwise_year_bounds_keep_the_year(self):
        fy, date_from, date_to = report_filters.monthwise_period(
            self._get(
                fiscal_year=str(self.fy.pk),
                **{"from": self.fy.year_start_date.isoformat(), "to": self.fy.year_end_date.isoformat()},
            )
        )
        self.assertEqual(fy, self.fy)
        self.assertEqual((date_from, date_to), (self.fy.year_start_date, self.fy.year_end_date))

    def test_monthwise_year_switch_with_stale_dates_resets_to_year(self):
        stale = (self.fy.year_end_date + timedelta(days=1)).isoformat()
        fy, date_from, date_to = report_filters.monthwise_period(
            self._get(fiscal_year=str(self.fy.pk), **{"from": stale, "to": stale})
        )
        self.assertEqual(fy, self.fy)
        self.assertEqual((date_from, date_to), (self.fy.year_start_date, self.fy.year_end_date))

    def test_accounting_dates_clamp_stale_dates_to_year_bounds(self):
        stale = (self.fy.year_end_date + timedelta(days=1)).isoformat()
        date_from, date_to = report_filters.accounting_dates(
            self._get(fiscal_year=str(self.fy.pk), **{"from": stale, "to": stale}),
            self.fy,
        )
        self.assertEqual((date_from, date_to), (self.fy.year_start_date, self.fy.year_end_date))

    def test_accounting_dates_keep_dates_inside_the_year(self):
        custom_from = self.fy.year_start_date + timedelta(days=1)
        custom_to = self.fy.year_end_date - timedelta(days=1)
        date_from, date_to = report_filters.accounting_dates(
            self._get(fiscal_year=str(self.fy.pk), **{"from": custom_from.isoformat(), "to": custom_to.isoformat()}),
            self.fy,
        )
        self.assertEqual((date_from, date_to), (custom_from, custom_to))
