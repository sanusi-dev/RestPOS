from decimal import Decimal

from django.contrib.auth.models import Group
from django.test import TestCase
from django.urls import reverse

from apps.inventory.models import UOM, Item, ItemGroup
from apps.menu.models import ItemAddOn, ItemVariant, Menu, MenuItem
from apps.users.models import CustomUser


class MenuViewTestBase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = CustomUser.objects.create_user(
            username="admin@test.com", password="testpass123", email="admin@test.com"
        )
        mgr, _ = Group.objects.get_or_create(name="RestPOS Manager")
        cls.user.groups.add(mgr)
        cls.uom = UOM.objects.create(name="Nos")
        cls.group = ItemGroup.objects.create(name="Food")
        cls.item_food = Item.objects.create(
            item_code="RICE001",
            item_name="Jollof Rice",
            item_group=cls.group,
            stock_uom=cls.uom,
            department="FOOD",
            is_sales_item=True,
        )
        cls.item_drink = Item.objects.create(
            item_code="DRINK001",
            item_name="Coke",
            item_group=cls.group,
            stock_uom=cls.uom,
            department="DRINKS",
            is_sales_item=True,
        )
        cls.menu = Menu.objects.create(name="Lunch Menu")
        cls.menu_item = MenuItem.objects.create(menu=cls.menu, item=cls.item_food, rate=Decimal("1500"))
        MenuItem.objects.create(menu=cls.menu, item=cls.item_drink, rate=Decimal("500"))

    def setUp(self):
        self.client.login(username="admin@test.com", password="testpass123")


class TestLoginRequired(TestCase):
    def test_dashboard_requires_login(self):
        response = self.client.get(reverse("menu:dashboard"))
        self.assertEqual(response.status_code, 302)

    def test_menu_list_requires_login(self):
        response = self.client.get(reverse("menu:menu_list"))
        self.assertEqual(response.status_code, 302)


class TestDashboardView(MenuViewTestBase):
    def test_dashboard_200(self):
        response = self.client.get(reverse("menu:dashboard"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Menu")


class TestMenuViews(MenuViewTestBase):
    def test_menu_list_200(self):
        response = self.client.get(reverse("menu:menu_list"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Lunch Menu")

    def test_menu_create_get(self):
        response = self.client.get(reverse("menu:menu_create"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'name="name"')

    def test_menu_create_post(self):
        response = self.client.post(
            reverse("menu:menu_create"),
            {"name": "Dinner Menu", "enabled": "on"},
        )
        self.assertRedirects(response, reverse("menu:menu_list"))
        menu = Menu.objects.get(name="Dinner Menu")
        self.assertEqual(menu.name, "Dinner Menu")

    def test_menu_detail_200(self):
        response = self.client.get(reverse("menu:menu_detail", kwargs={"pk": self.menu.pk}))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Jollof Rice")

    def test_menu_detail_404(self):
        response = self.client.get(reverse("menu:menu_detail", kwargs={"pk": 9999}))
        self.assertEqual(response.status_code, 404)

    def test_menu_update_post(self):
        response = self.client.post(
            reverse("menu:menu_update", kwargs={"pk": self.menu.pk}),
            {"name": "Updated Menu", "enabled": "on"},
        )
        self.assertRedirects(response, reverse("menu:menu_detail", kwargs={"pk": self.menu.pk}))
        self.menu.refresh_from_db()
        self.assertEqual(self.menu.name, "Updated Menu")
        self.assertEqual(self.menu.name, "Updated Menu")


class TestMenuItemViews(MenuViewTestBase):
    def test_menu_item_list_200(self):
        response = self.client.get(reverse("menu:menu_item_list"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Jollof Rice")

    def test_menu_item_list_filter_by_menu(self):
        response = self.client.get(reverse("menu:menu_item_list"), {"menu": str(self.menu.pk)})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Jollof Rice")

    def test_menu_item_create_get(self):
        response = self.client.get(reverse("menu:menu_item_create"))
        self.assertEqual(response.status_code, 200)

    def test_menu_item_create_post(self):
        item3 = Item.objects.create(
            item_code="CHICK001",
            item_name="Fried Chicken",
            item_group=self.group,
            stock_uom=self.uom,
            department="FOOD",
            is_sales_item=True,
        )
        response = self.client.post(
            reverse("menu:menu_item_create"),
            {
                "menu": self.menu.pk,
                "item": item3.pk,
                "item_name": "Fried Chicken",
                "rate": "2500",
                "special_dish": "",
                "disabled": "",
            },
        )
        self.assertRedirects(response, reverse("menu:menu_detail", kwargs={"pk": self.menu.pk}))
        self.assertTrue(MenuItem.objects.filter(item=item3).exists())

    def test_menu_item_update_post(self):
        response = self.client.post(
            reverse("menu:menu_item_update", kwargs={"pk": self.menu_item.pk}),
            {
                "menu": self.menu.pk,
                "item": self.item_food.pk,
                "item_name": "Jollof Rice",
                "rate": "1800",
                "special_dish": "on",
                "disabled": "",
            },
        )
        self.assertRedirects(response, reverse("menu:menu_detail", kwargs={"pk": self.menu.pk}))
        self.menu_item.refresh_from_db()
        self.assertEqual(self.menu_item.rate, Decimal("1800"))
        self.assertTrue(self.menu_item.special_dish)

    def test_menu_item_delete_post(self):
        pk = self.menu_item.pk
        response = self.client.post(reverse("menu:menu_item_delete", kwargs={"pk": pk}))
        self.assertRedirects(response, reverse("menu:menu_detail", kwargs={"pk": self.menu.pk}))
        self.assertFalse(MenuItem.objects.filter(pk=pk).exists())

    def test_menu_item_delete_requires_post(self):
        response = self.client.get(reverse("menu:menu_item_delete", kwargs={"pk": self.menu_item.pk}))
        self.assertEqual(response.status_code, 405)


class TestItemAddOnViews(MenuViewTestBase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.add_on_item = Item.objects.create(
            item_code="EXTRA001",
            item_name="Extra Sauce",
            item_group=cls.group,
            stock_uom=cls.uom,
            department="FOOD",
            is_sales_item=True,
        )
        MenuItem.objects.create(menu=cls.menu, item=cls.add_on_item, rate=Decimal("100"))
        cls.add_on = ItemAddOn.objects.create(parent_item=cls.item_food, add_on_item=cls.add_on_item)

    def test_add_on_list_200(self):
        response = self.client.get(reverse("menu:add_on_list"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Extra Sauce")

    def test_add_on_list_filter_by_parent(self):
        response = self.client.get(reverse("menu:add_on_list"), {"parent_item": str(self.item_food.pk)})
        self.assertEqual(response.status_code, 200)

    def test_add_on_create_post(self):
        item_new = Item.objects.create(
            item_code="NEW001",
            item_name="New Add-on Item",
            item_group=self.group,
            stock_uom=self.uom,
            department="FOOD",
            is_sales_item=True,
        )
        MenuItem.objects.create(menu=self.menu, item=item_new, rate=Decimal("50"))
        response = self.client.post(
            reverse("menu:add_on_create"),
            {"parent_item": self.item_food.pk, "add_on_item": item_new.pk},
        )
        self.assertRedirects(response, reverse("menu:add_on_list"))
        self.assertTrue(ItemAddOn.objects.filter(parent_item=self.item_food, add_on_item=item_new).exists())

    def test_add_on_update_post(self):
        item_new = Item.objects.create(
            item_code="NEW002",
            item_name="Another Add-on",
            item_group=self.group,
            stock_uom=self.uom,
            department="FOOD",
            is_sales_item=True,
        )
        MenuItem.objects.create(menu=self.menu, item=item_new, rate=Decimal("75"))
        response = self.client.post(
            reverse("menu:add_on_update", kwargs={"pk": self.add_on.pk}),
            {"parent_item": self.item_food.pk, "add_on_item": item_new.pk},
        )
        self.assertRedirects(response, reverse("menu:add_on_list"))
        self.add_on.refresh_from_db()
        self.assertEqual(self.add_on.add_on_item, item_new)

    def test_add_on_delete_post(self):
        pk = self.add_on.pk
        response = self.client.post(reverse("menu:add_on_delete", kwargs={"pk": pk}))
        self.assertRedirects(response, reverse("menu:add_on_list"))
        self.assertFalse(ItemAddOn.objects.filter(pk=pk).exists())

    def test_add_on_delete_requires_post(self):
        response = self.client.get(reverse("menu:add_on_delete", kwargs={"pk": self.add_on.pk}))
        self.assertEqual(response.status_code, 405)


class TestItemVariantViews(MenuViewTestBase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.variant_item = Item.objects.create(
            item_code="COKE-L",
            item_name="Large Coke",
            item_group=cls.group,
            stock_uom=cls.uom,
            department="DRINKS",
            is_sales_item=True,
        )
        MenuItem.objects.create(menu=cls.menu, item=cls.variant_item, rate=Decimal("700"))
        cls.variant = ItemVariant.objects.create(parent_item=cls.item_drink, variant_item=cls.variant_item)

    def test_variant_list_200(self):
        response = self.client.get(reverse("menu:variant_list"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Large Coke")

    def test_variant_list_filter_by_parent(self):
        response = self.client.get(reverse("menu:variant_list"), {"parent_item": str(self.item_drink.pk)})
        self.assertEqual(response.status_code, 200)

    def test_variant_create_post(self):
        item_new = Item.objects.create(
            item_code="COKE-Z",
            item_name="Zero Coke",
            item_group=self.group,
            stock_uom=self.uom,
            department="DRINKS",
            is_sales_item=True,
        )
        MenuItem.objects.create(menu=self.menu, item=item_new, rate=Decimal("600"))
        response = self.client.post(
            reverse("menu:variant_create"),
            {"parent_item": self.item_drink.pk, "variant_item": item_new.pk},
        )
        self.assertRedirects(response, reverse("menu:variant_list"))
        self.assertTrue(ItemVariant.objects.filter(parent_item=self.item_drink, variant_item=item_new).exists())

    def test_variant_update_post(self):
        item_new = Item.objects.create(
            item_code="COKE-D",
            item_name="Diet Coke",
            item_group=self.group,
            stock_uom=self.uom,
            department="DRINKS",
            is_sales_item=True,
        )
        MenuItem.objects.create(menu=self.menu, item=item_new, rate=Decimal("650"))
        response = self.client.post(
            reverse("menu:variant_update", kwargs={"pk": self.variant.pk}),
            {"parent_item": self.item_drink.pk, "variant_item": item_new.pk},
        )
        self.assertRedirects(response, reverse("menu:variant_list"))
        self.variant.refresh_from_db()
        self.assertEqual(self.variant.variant_item, item_new)

    def test_variant_delete_post(self):
        pk = self.variant.pk
        response = self.client.post(reverse("menu:variant_delete", kwargs={"pk": pk}))
        self.assertRedirects(response, reverse("menu:variant_list"))
        self.assertFalse(ItemVariant.objects.filter(pk=pk).exists())

    def test_variant_delete_requires_post(self):
        response = self.client.get(reverse("menu:variant_delete", kwargs={"pk": self.variant.pk}))
        self.assertEqual(response.status_code, 405)
