from django.core.exceptions import ValidationError
from django.db import models

from apps.inventory.models import UOM, Item
from apps.utils.models import BaseModel


class Menu(BaseModel):
    """A named menu for the restaurant. Owns a synced PriceList."""

    name = models.CharField(max_length=100, unique=True)
    enabled = models.BooleanField(default=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        self.sync_price_list()

    def sync_price_list(self):
        """Keep the menu's PriceList and ItemPrice rows in sync with its MenuItems."""
        price_list, created = PriceList.objects.get_or_create(
            menu=self,
            defaults={"name": self.name, "selling": True, "enabled": self.enabled},
        )
        if not created:
            price_list.name = self.name
            price_list.enabled = self.enabled
        price_list.prices.all().delete()
        menu_items = self.items.filter(disabled=False).select_related("item", "item__stock_uom")
        # Build rows in memory and bulk-insert instead of issuing one INSERT per item.
        item_prices = [
            ItemPrice(
                price_list=price_list,
                item=menu_item.item,
                price_list_rate=menu_item.rate,
                uom=menu_item.item.stock_uom,
            )
            for menu_item in menu_items
        ]
        if item_prices:
            ItemPrice.objects.bulk_create(item_prices)
        price_list.save()


class MenuItem(BaseModel):
    """A line on a menu: an Item sold at a specific rate."""

    menu = models.ForeignKey(Menu, on_delete=models.CASCADE, related_name="items")
    item = models.ForeignKey(Item, on_delete=models.PROTECT, related_name="menu_items")
    item_name = models.CharField(max_length=200)
    rate = models.DecimalField(max_digits=10, decimal_places=2)
    special_dish = models.BooleanField(default=False)
    disabled = models.BooleanField(default=False)

    class Meta:
        unique_together = [("menu", "item")]
        ordering = ["item_name"]

    def __str__(self):
        return self.item_name or self.item.item_code

    def save(self, *args, **kwargs):
        if not self.item_name and self.item:
            self.item_name = self.item.item_name
        super().save(*args, **kwargs)
        if self.menu:
            self.menu.sync_price_list()

    def clean(self):
        super().clean()
        if self.item_id:
            if self.item.has_variants:
                raise ValidationError(
                    {"item": "Template items cannot be added to a menu — add the size variants instead."}
                )
            if not self.item.is_sales_item:
                raise ValidationError({"item": "Only sellable items can be added to a menu."})
            if self.item.disabled:
                raise ValidationError({"item": "Disabled items cannot be added to a menu."})
        if not self.rate and self.item and self.item.last_purchase_rate:
            self.rate = self.item.last_purchase_rate


class PriceList(BaseModel):
    """A named price list for selling items at specific rates."""

    name = models.CharField(max_length=100)
    enabled = models.BooleanField(default=True)
    selling = models.BooleanField(default=True)
    buying = models.BooleanField(default=False)
    menu = models.ForeignKey(
        Menu,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="price_lists",
    )

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class ItemPrice(BaseModel):
    """The rate at which an item sells in a specific PriceList."""

    item = models.ForeignKey(Item, on_delete=models.CASCADE, related_name="prices")
    price_list = models.ForeignKey(PriceList, on_delete=models.CASCADE, related_name="prices")
    price_list_rate = models.DecimalField(max_digits=10, decimal_places=2)
    uom = models.ForeignKey(UOM, on_delete=models.PROTECT, related_name="prices")

    class Meta:
        unique_together = [("item", "price_list", "uom")]
        ordering = ["item__item_name"]

    def __str__(self):
        return f"{self.item.item_code}: {self.price_list_rate}"


class ItemAddOn(BaseModel):
    """An add-on that can be upsold alongside a parent item."""

    parent_item = models.ForeignKey(Item, on_delete=models.CASCADE, related_name="add_ons")
    add_on_item = models.ForeignKey(Item, on_delete=models.PROTECT, related_name="add_on_for")

    class Meta:
        unique_together = [("parent_item", "add_on_item")]

    def __str__(self):
        return f"{self.parent_item.item_name} + {self.add_on_item.item_name}"

    def clean(self):
        super().clean()
        if not self.add_on_item_id:
            return
        add_on = self.add_on_item
        if add_on.has_variants:
            raise ValidationError(
                {"add_on_item": "Template items cannot be used as add-ons — use a sellable size variant."}
            )
        if not add_on.is_sales_item:
            raise ValidationError({"add_on_item": "Only sellable items can be used as add-ons."})
        if add_on.disabled:
            raise ValidationError({"add_on_item": "Disabled items cannot be used as add-ons."})
        if not MenuItem.objects.filter(item=add_on, disabled=False).exists():
            raise ValidationError(
                {"add_on_item": "Add-on item must be on an enabled menu line to have a resolvable POS price."}
            )


class ItemVariant(BaseModel):
    """A POS-level variant of a parent item (e.g. small / large size)."""

    parent_item = models.ForeignKey(Item, on_delete=models.CASCADE, related_name="pos_variants")
    variant_item = models.ForeignKey(Item, on_delete=models.PROTECT, related_name="pos_variant_of")

    class Meta:
        unique_together = [("parent_item", "variant_item")]

    def __str__(self):
        return f"{self.parent_item.item_name} → {self.variant_item.item_name}"

    def clean(self):
        super().clean()
        if not MenuItem.objects.filter(item=self.variant_item).exists():
            raise ValidationError("Variant item must be a member of at least one menu to have a resolvable POS price.")
