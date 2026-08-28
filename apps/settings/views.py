from typing import cast

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import Group
from django.core.exceptions import PermissionDenied
from django.db import models
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST
from django_htmx.middleware import HtmxDetails

from apps.users.models import CustomUser

from .forms import (
    ProductionUnitForm,
    RestaurantForm,
)
from .models import (
    ProductionUnit,
    Restaurant,
)

RESTPOS_GROUP_NAMES = ["RestPOS Admin", "RestPOS Manager", "RestPOS Cashier"]


class _HtmxRequest(HttpRequest):
    htmx: HtmxDetails


def _authenticated_user(request: HttpRequest) -> CustomUser:
    user = request.user
    if not isinstance(user, CustomUser):
        raise PermissionDenied
    return user


def _is_htmx(request: HttpRequest) -> bool:
    return bool(cast(_HtmxRequest, request).htmx)


def _ensure_restpos_groups():
    """Fetch RestPOS role groups in one query, creating any missing ones. Returns dict keyed by name."""
    groups = {group.name: group for group in Group.objects.filter(name__in=RESTPOS_GROUP_NAMES)}
    for name in RESTPOS_GROUP_NAMES:
        if name not in groups:
            groups[name] = Group.objects.create(name=name)
    return groups


@login_required
def settings_dashboard(request: HttpRequest) -> HttpResponse:
    context = {
        "settings_configured": Restaurant.objects.exists(),
        "staff_count": CustomUser.objects.filter(
            groups__name__in=["RestPOS Admin", "RestPOS Manager", "RestPOS Cashier"]
        )
        .distinct()
        .count(),
        "production_unit_count": ProductionUnit.objects.count(),
    }
    return render(request, "backoffice/settings/dashboard.html", context)


@login_required
def restaurant_settings(request: HttpRequest) -> HttpResponse:
    user = _authenticated_user(request)
    restaurant = Restaurant.load()
    if request.method == "POST":
        if not (user.is_manager or user.is_admin or user.is_superuser):
            return redirect("web:home")
        form = RestaurantForm(request.POST, instance=restaurant)
        if form.is_valid():
            form.save()
            messages.success(request, "Restaurant settings saved.")
            return redirect("settings:restaurant_settings")
    else:
        form = RestaurantForm(instance=restaurant) if restaurant else RestaurantForm()
    return render(request, "backoffice/settings/restaurant_settings.html", {"form": form, "restaurant": restaurant})


@login_required
def staff_list(request: HttpRequest) -> HttpResponse:
    user = _authenticated_user(request)
    if not user.has_backoffice_access:
        return redirect("web:home")

    search = request.GET.get("search", "")

    users = CustomUser.objects.all().order_by("-date_joined")
    if search:
        users = users.filter(
            models.Q(username__icontains=search)
            | models.Q(first_name__icontains=search)
            | models.Q(last_name__icontains=search)
        )
    # Prefetch only RestPOS role groups so role derivation uses the prefetch cache instead of per-row queries.
    users = users.prefetch_related(
        models.Prefetch("groups", queryset=Group.objects.filter(name__in=RESTPOS_GROUP_NAMES))
    )

    staff_data = [_build_staff_entry(user) for user in users]

    context = {
        "staff_data": staff_data,
        "search": search
    }
    if _is_htmx(request) and request.htmx.target == "staff-table-body":
        return render(request, "backoffice/settings/staff_list.html#staff-rows", context)
    return render(request, "backoffice/settings/staff_list.html", context)


@login_required
@require_POST
def staff_assign_role(request: HttpRequest, pk: int, role: str) -> HttpResponse:
    user = _authenticated_user(request)
    if not user.has_backoffice_access:
        return HttpResponse("Unauthorized", status=403)

    if not user.is_superuser:
        return HttpResponse("Unauthorized", status=403)

    user = get_object_or_404(CustomUser, pk=pk)
    groups = _ensure_restpos_groups()
    admin_group = groups["RestPOS Admin"]
    manager_group = groups["RestPOS Manager"]
    cashier_group = groups["RestPOS Cashier"]

    user.groups.remove(admin_group, manager_group, cashier_group)

    if role == "admin":
        user.is_superuser = True
        user.is_staff = True
        user.groups.add(admin_group)
        user.save()
        messages.success(request, f"{user.get_display_name()} is now an Admin.")
    elif role == "manager":
        if user.is_superuser:
            user.is_superuser = False
            user.is_staff = False
        user.save()
        user.groups.add(manager_group)
        messages.success(request, f"{user.get_display_name()} is now a Manager.")
    elif role == "cashier":
        if user.is_superuser:
            user.is_superuser = False
            user.is_staff = False
        user.save()
        user.groups.add(cashier_group)
        messages.success(request, f"{user.get_display_name()} is now a Cashier.")

    if _is_htmx(request) and request.htmx.target == f"staff-row-{pk}":
        return render(request, "backoffice/settings/staff_list.html#staff-row", {"entry": _build_staff_entry(user)})
    return redirect("settings:staff_list")


@login_required
@require_POST
def staff_remove_role(request: HttpRequest, pk: int) -> HttpResponse:
    user = _authenticated_user(request)
    if not user.has_backoffice_access:
        return HttpResponse("Unauthorized", status=403)

    if not user.is_superuser:
        return HttpResponse("Unauthorized", status=403)

    user = get_object_or_404(CustomUser, pk=pk)
    groups = _ensure_restpos_groups()
    admin_group = groups["RestPOS Admin"]
    manager_group = groups["RestPOS Manager"]
    cashier_group = groups["RestPOS Cashier"]

    if user.groups.filter(pk=admin_group.pk).exists():
        messages.error(request, "Cannot remove role from an Admin. Demote them to Manager first.")
        return redirect("settings:staff_list")

    user.groups.remove(admin_group, manager_group, cashier_group)
    messages.success(request, f"Role removed from {user.get_display_name()}.")

    if _is_htmx(request) and request.htmx.target == f"staff-row-{pk}":
        return render(request, "backoffice/settings/staff_list.html#staff-row", {"entry": _build_staff_entry(user)})
    return redirect("settings:staff_list")


def _build_staff_entry(user: CustomUser) -> dict[str, CustomUser | str]:
    # Reads the prefetched/cached group names — no per-row exists() queries.
    user_group_names = set(user._restpos_group_names)
    if user.is_superuser or "RestPOS Admin" in user_group_names:
        role = "admin"
    elif "RestPOS Manager" in user_group_names:
        role = "manager"
    elif "RestPOS Cashier" in user_group_names:
        role = "cashier"
    else:
        role = ""
    return {"user": user, "role": role}


@login_required
def production_unit_list(request: HttpRequest) -> HttpResponse:
    production_units = ProductionUnit.objects.select_related("warehouse").all()
    return render(request, "backoffice/settings/production_unit_list.html", {"production_units": production_units})


@login_required
def production_unit_create(request: HttpRequest) -> HttpResponse:
    user = _authenticated_user(request)
    if not (user.is_manager or user.is_admin or user.is_superuser):
        return redirect("web:home")
    if request.method == "POST":
        form = ProductionUnitForm(request.POST)
        if form.is_valid():
            form.save()
            return redirect("settings:production_unit_list")
    else:
        form = ProductionUnitForm()
    return render(request, "backoffice/settings/production_unit_form.html", {"form": form, "is_create": True})


@login_required
def production_unit_detail(request: HttpRequest, pk: int) -> HttpResponse:
    production_unit = get_object_or_404(ProductionUnit.objects.select_related("warehouse"), pk=pk)
    return render(request, "backoffice/settings/production_unit_detail.html", {"production_unit": production_unit})


@login_required
def production_unit_update(request: HttpRequest, pk: int) -> HttpResponse:
    user = _authenticated_user(request)
    if not (user.is_manager or user.is_admin or user.is_superuser):
        return redirect("web:home")
    production_unit = get_object_or_404(ProductionUnit, pk=pk)
    if request.method == "POST":
        form = ProductionUnitForm(request.POST, instance=production_unit)
        if form.is_valid():
            form.save()
            return redirect("settings:production_unit_detail", pk=production_unit.pk)
    else:
        form = ProductionUnitForm(instance=production_unit)
    return render(
        request,
        "backoffice/settings/production_unit_form.html",
        {"form": form, "is_create": False, "production_unit": production_unit},
    )


@login_required
@require_POST
def production_unit_delete(request: HttpRequest, pk: int) -> HttpResponse:
    user = _authenticated_user(request)
    if not (user.is_manager or user.is_admin or user.is_superuser):
        return redirect("web:home")
    production_unit = get_object_or_404(ProductionUnit, pk=pk)
    production_unit.delete()
    return redirect("settings:production_unit_list")
