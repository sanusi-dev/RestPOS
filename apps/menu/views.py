from typing import cast

from django.contrib.auth.decorators import login_required
from django.db.models import Count
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from apps.inventory.models import Item

from .forms import (
    ItemAddOnForm,
    ItemVariantForm,
    MenuForm,
    MenuItemForm,
)
from .models import ItemAddOn, ItemVariant, Menu, MenuItem


@login_required
def menu_dashboard(request: HttpRequest) -> HttpResponse:
    context = {
        "menu_count": Menu.objects.count(),
        "menu_item_count": MenuItem.objects.count(),
        "add_on_count": ItemAddOn.objects.count(),
        "variant_count": ItemVariant.objects.count(),
    }
    return render(request, "backoffice/menu/dashboard.html", context)


# ---------------------------------------------------------------------------
# Menu
# ---------------------------------------------------------------------------


@login_required
def menu_list(request: HttpRequest) -> HttpResponse:
    # annotate Avoids per-row COUNT query in template ({ menu.items.count }).
    menus = Menu.objects.annotate(item_count=Count("items"))
    return render(request, "backoffice/menu/menu_list.html", {"menus": menus})


@login_required
def menu_create(request: HttpRequest) -> HttpResponse:
    if request.method == "POST":
        form = MenuForm(request.POST)
        if form.is_valid():
            form.save()
            return redirect("menu:menu_list")
    else:
        form = MenuForm()
    return render(request, "backoffice/menu/menu_form.html", {"form": form, "is_create": True})


@login_required
def menu_detail(request: HttpRequest, pk: int) -> HttpResponse:
    menu = get_object_or_404(Menu, pk=pk)
    # Template reads denormalized mi.item_name only — no need to JOIN item.
    menu_items = menu.items.all()
    return render(
        request,
        "backoffice/menu/menu_detail.html",
        {"menu": menu, "menu_items": menu_items},
    )


@login_required
def menu_update(request: HttpRequest, pk: int) -> HttpResponse:
    menu = get_object_or_404(Menu, pk=pk)
    if request.method == "POST":
        form = MenuForm(request.POST, instance=menu)
        if form.is_valid():
            form.save()
            return redirect("menu:menu_detail", pk=menu.pk)
    else:
        form = MenuForm(instance=menu)
    return render(
        request,
        "backoffice/menu/menu_form.html",
        {"form": form, "is_create": False, "menu": menu},
    )


# ---------------------------------------------------------------------------
# MenuItem
# ---------------------------------------------------------------------------


@login_required
def menu_item_list(request: HttpRequest) -> HttpResponse:
    menu_id = request.GET.get("menu")
    # Template reads mi.item_name (denormalized) + mi.menu.name — no need to JOIN item.
    menu_items = MenuItem.objects.select_related("menu").all()
    if menu_id:
        menu_items = menu_items.filter(menu_id=menu_id)
    menus = Menu.objects.all().order_by("name")
    return render(
        request,
        "backoffice/menu/menu_item_list.html",
        {"menu_items": menu_items, "menus": menus, "selected_menu": menu_id},
    )


@login_required
def menu_item_create(request: HttpRequest) -> HttpResponse:
    menu_id = request.GET.get("menu")
    if request.method == "POST":
        form = MenuItemForm(request.POST)
        if form.is_valid():
            menu_item = form.save()
            return redirect("menu:menu_detail", pk=menu_item.menu_id)
    else:
        form = MenuItemForm(initial={"menu": menu_id} if menu_id else None)
    return render(
        request,
        "backoffice/menu/menu_item_form.html",
        {"form": form, "is_create": True, "menu_id": menu_id},
    )


@login_required
def menu_item_update(request: HttpRequest, pk: int) -> HttpResponse:
    menu_item = get_object_or_404(MenuItem, pk=pk)
    if request.method == "POST":
        form = MenuItemForm(request.POST, instance=menu_item)
        if form.is_valid():
            menu_item = form.save()
            return redirect("menu:menu_detail", pk=menu_item.menu_id)
    else:
        form = MenuItemForm(instance=menu_item)
    return render(
        request,
        "backoffice/menu/menu_item_form.html",
        {"form": form, "is_create": False, "menu_item": menu_item},
    )


@login_required
@require_POST
def menu_item_delete(request: HttpRequest, pk: int) -> HttpResponse:
    menu_item = get_object_or_404(MenuItem, pk=pk)
    menu_id = menu_item.menu_id
    menu_item.delete()
    return redirect("menu:menu_detail", pk=menu_id)


# ---------------------------------------------------------------------------
# ItemAddOn
# ---------------------------------------------------------------------------


@login_required
def add_on_list(request: HttpRequest) -> HttpResponse:
    parent_id = request.GET.get("parent_item")
    add_ons = ItemAddOn.objects.select_related("parent_item", "add_on_item").all()
    if parent_id:
        add_ons = add_ons.filter(parent_item_id=cast(int, parent_id))
    parent_items = Item.objects.filter(add_ons__isnull=False).distinct().order_by("item_name").only("item_name")
    return render(
        request,
        "backoffice/menu/add_on_list.html",
        {"add_ons": add_ons, "parent_items": parent_items, "selected_parent": parent_id},
    )


@login_required
def add_on_create(request: HttpRequest) -> HttpResponse:
    if request.method == "POST":
        form = ItemAddOnForm(request.POST)
        if form.is_valid():
            form.save()
            return redirect("menu:add_on_list")
    else:
        form = ItemAddOnForm()
    return render(request, "backoffice/menu/add_on_form.html", {"form": form, "is_create": True})


@login_required
def add_on_update(request: HttpRequest, pk: int) -> HttpResponse:
    add_on = get_object_or_404(ItemAddOn, pk=pk)
    if request.method == "POST":
        form = ItemAddOnForm(request.POST, instance=add_on)
        if form.is_valid():
            form.save()
            return redirect("menu:add_on_list")
    else:
        form = ItemAddOnForm(instance=add_on)
    return render(
        request,
        "backoffice/menu/add_on_form.html",
        {"form": form, "is_create": False, "add_on": add_on},
    )


@login_required
@require_POST
def add_on_delete(request: HttpRequest, pk: int) -> HttpResponse:
    add_on = get_object_or_404(ItemAddOn, pk=pk)
    add_on.delete()
    return redirect("menu:add_on_list")


# ---------------------------------------------------------------------------
# ItemVariant
# ---------------------------------------------------------------------------


@login_required
def variant_list(request: HttpRequest) -> HttpResponse:
    parent_id = request.GET.get("parent_item")
    variants = ItemVariant.objects.select_related("parent_item", "variant_item").all()
    if parent_id:
        variants = variants.filter(parent_item_id=cast(int, parent_id))
    parent_items = Item.objects.filter(pos_variants__isnull=False).distinct().order_by("item_name").only("item_name")
    return render(
        request,
        "backoffice/menu/variant_list.html",
        {"variants": variants, "parent_items": parent_items, "selected_parent": parent_id},
    )


@login_required
def variant_create(request: HttpRequest) -> HttpResponse:
    if request.method == "POST":
        form = ItemVariantForm(request.POST)
        if form.is_valid():
            form.save()
            return redirect("menu:variant_list")
    else:
        form = ItemVariantForm()
    return render(request, "backoffice/menu/variant_form.html", {"form": form, "is_create": True})


@login_required
def variant_update(request: HttpRequest, pk: int) -> HttpResponse:
    variant = get_object_or_404(ItemVariant, pk=pk)
    if request.method == "POST":
        form = ItemVariantForm(request.POST, instance=variant)
        if form.is_valid():
            form.save()
            return redirect("menu:variant_list")
    else:
        form = ItemVariantForm(instance=variant)
    return render(
        request,
        "backoffice/menu/variant_form.html",
        {"form": form, "is_create": False, "variant": variant},
    )


@login_required
@require_POST
def variant_delete(request: HttpRequest, pk: int) -> HttpResponse:
    variant = get_object_or_404(ItemVariant, pk=pk)
    variant.delete()
    return redirect("menu:variant_list")
