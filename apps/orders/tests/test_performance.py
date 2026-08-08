from decimal import Decimal

from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone

from apps.orders.models import SUBMITTED, Order

from .test_pos_views import POSViewTestBase


class POSReadQueryPerformanceTest(POSViewTestBase):
    def setUp(self):
        super().setUp()
        self.shift = self._open_shift()
        self.order = Order.objects.create(opening_entry=self.shift)
        self.order.add_item(
            self.food_item,
            qty=1,
            rate=Decimal("1500"),
            menu_item=self.menu_item,
            item_name=self.menu_item.item_name,
        )

    @staticmethod
    def _queries_for(table_name, captured_queries):
        return [query for query in captured_queries if table_name in query["sql"]]

    def test_cart_render_reuses_loaded_items_and_skips_catalog_oob(self):
        with CaptureQueriesContext(connection) as captured:
            response = self.client.post(
                reverse("pos:pos_customer_card_activate", kwargs={"pk": self.order.pk, "idx": 1})
            )

        self.assertEqual(response.status_code, 200)
        self.assertLessEqual(len(self._queries_for('FROM "orders_orderitem"', captured.captured_queries)), 1)
        self.assertNotIn('id="catalog-grid"', response.content.decode())

    def test_payment_dialog_does_not_build_catalog_context(self):
        with CaptureQueriesContext(connection) as captured:
            response = self.client.get(reverse("pos:pos_order_settle", kwargs={"pk": self.order.pk}))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(self._queries_for('FROM "orders_orderitem"', captured.captured_queries), [])
        self.assertEqual(self._queries_for("menu_menuitem", captured.captured_queries), [])

    def test_history_uses_annotated_item_count(self):
        history_order = Order.objects.create(
            opening_entry=self.shift,
            posting_date=timezone.localdate(),
            grand_total=Decimal("1500"),
        )
        history_order.items.create(
            item=self.food_item,
            item_name=self.food_item.item_name,
            qty=1,
            rate=Decimal("1500"),
            department="FOOD",
        )
        Order.objects.filter(pk=history_order.pk).update(status=SUBMITTED, is_paid=True)

        with CaptureQueriesContext(connection) as captured:
            response = self.client.get(reverse("pos:pos_order_history"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(
            response,
            '<td class="px-4 py-3 text-center font-mono text-sm font-bold tabular-nums text-slate-600">1</td>',
        )
        self.assertEqual(self._queries_for('FROM "orders_orderitem"', captured.captured_queries), [])
