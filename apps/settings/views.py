from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import Group
from django.db import models
from django.db.models.functions import Now
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from apps.users.models import CustomUser

from .forms import (
    BranchForm,
    POSProfileForm,
    ProductionUnitForm,
    RestaurantForm,
    RoomForm,
    TableForm,
    TaxTemplateForm,
    UserRoomAssignmentForm,
)
from .models import (
    Branch,
    POSProfile,
    ProductionUnit,
    Restaurant,
    Room,
    Table,
    TaxTemplate,
    UserRoomAssignment,
)

RESTPOS_GROUP_NAMES = ["RestPOS Admin", "RestPOS Manager", "RestPOS Cashier"]


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
        "branch_count": Branch.objects.count(),
        "room_count": Room.objects.count(),
        "table_count": Table.objects.count(),
        "restaurant_count": Restaurant.objects.count(),
        "assignment_count": UserRoomAssignment.objects.count(),
        "staff_count": CustomUser.objects.filter(
            groups__name__in=["RestPOS Admin", "RestPOS Manager", "RestPOS Cashier"]
        )
        .distinct()
        .count(),
        "pos_profile_count": POSProfile.objects.count(),
        "production_unit_count": ProductionUnit.objects.count(),
        "tax_template_count": TaxTemplate.objects.count(),
    }
    return render(request, "backoffice/settings/dashboard.html", context)


# ---------------------------------------------------------------------------
# Branch
# ---------------------------------------------------------------------------


@login_required
def branch_list(request: HttpRequest) -> HttpResponse:
    branches = Branch.objects.all().order_by("name")
    return render(request, "backoffice/settings/branch_list.html", {"branches": branches})


@login_required
def branch_create(request: HttpRequest) -> HttpResponse:
    if request.method == "POST":
        form = BranchForm(request.POST)
        if form.is_valid():
            form.save()
            return redirect("settings:branch_list")
    else:
        form = BranchForm()
    return render(request, "backoffice/settings/branch_form.html", {"form": form, "title": "Branch"})


@login_required
def branch_detail(request: HttpRequest, pk: int) -> HttpResponse:
    branch = get_object_or_404(Branch, pk=pk)
    rooms = branch.rooms.all()
    return render(request, "backoffice/settings/branch_detail.html", {"branch": branch, "rooms": rooms})


@login_required
def branch_update(request: HttpRequest, pk: int) -> HttpResponse:
    branch = get_object_or_404(Branch, pk=pk)
    if request.method == "POST":
        form = BranchForm(request.POST, instance=branch)
        if form.is_valid():
            form.save()
            return redirect("settings:branch_detail", pk=branch.pk)
    else:
        form = BranchForm(instance=branch)
    return render(request, "backoffice/settings/branch_form.html", {"form": form, "title": "Branch", "branch": branch})


# ---------------------------------------------------------------------------
# Room
# ---------------------------------------------------------------------------


@login_required
def room_list(request: HttpRequest) -> HttpResponse:
    rooms = Room.objects.all()
    return render(request, "backoffice/settings/room_list.html", {"rooms": rooms})


@login_required
def room_create(request: HttpRequest) -> HttpResponse:
    if request.method == "POST":
        form = RoomForm(request.POST)
        if form.is_valid():
            form.save()
            return redirect("settings:room_list")
    else:
        form = RoomForm()
    return render(request, "backoffice/settings/room_form.html", {"form": form, "is_create": True})


@login_required
def room_detail(request: HttpRequest, pk: int) -> HttpResponse:
    room = get_object_or_404(Room, pk=pk)
    tables = room.tables.all()
    return render(request, "backoffice/settings/room_detail.html", {"room": room, "tables": tables})


@login_required
def room_update(request: HttpRequest, pk: int) -> HttpResponse:
    room = get_object_or_404(Room, pk=pk)
    if request.method == "POST":
        form = RoomForm(request.POST, instance=room)
        if form.is_valid():
            form.save()
            return redirect("settings:room_detail", pk=room.pk)
    else:
        form = RoomForm(instance=room)
    return render(request, "backoffice/settings/room_form.html", {"form": form, "is_create": False, "room": room})


# ---------------------------------------------------------------------------
# Table
# ---------------------------------------------------------------------------


@login_required
def table_list(request: HttpRequest) -> HttpResponse:
    room_id = request.GET.get("room")
    tables = Table.objects.select_related("room").all()
    if room_id:
        tables = tables.filter(room_id=room_id)
    rooms = Room.objects.all().order_by("name")
    return render(
        request,
        "backoffice/settings/table_list.html",
        {"tables": tables, "rooms": rooms, "selected_room": room_id},
    )


@login_required
def table_layout(request: HttpRequest) -> HttpResponse:
    room_id = request.GET.get("room")
    # Template/JS read pk/name/layout_*/occupied only — no need to JOIN room.
    tables = Table.objects.all()
    if room_id:
        tables = tables.filter(room_id=room_id)
    rooms = Room.objects.all().order_by("name")
    tables_data = [
        {
            "id": table.pk,
            "name": table.name,
            "x": table.layout_x or 0,
            "y": table.layout_y or 0,
            "width": table.layout_width or 120,
            "height": table.layout_height or 80,
            "occupied": table.occupied,
        }
        for table in tables
    ]
    return render(
        request,
        "backoffice/settings/table_layout.html",
        {"tables": tables, "tables_data": tables_data, "rooms": rooms, "selected_room": room_id},
    )


@login_required
def table_create(request: HttpRequest) -> HttpResponse:
    if request.method == "POST":
        form = TableForm(request.POST)
        if form.is_valid():
            form.save()
            return redirect("settings:table_list")
    else:
        form = TableForm()
    return render(request, "backoffice/settings/table_form.html", {"form": form, "is_create": True})


@login_required
def table_detail(request: HttpRequest, pk: int) -> HttpResponse:
    table = get_object_or_404(Table.objects.select_related("room"), pk=pk)
    return render(request, "backoffice/settings/table_detail.html", {"table": table})


@login_required
def table_update(request: HttpRequest, pk: int) -> HttpResponse:
    table = get_object_or_404(Table, pk=pk)
    if request.method == "POST":
        form = TableForm(request.POST, instance=table)
        if form.is_valid():
            form.save()
            return redirect("settings:table_detail", pk=table.pk)
    else:
        form = TableForm(instance=table)
    return render(request, "backoffice/settings/table_form.html", {"form": form, "is_create": False, "table": table})


@login_required
@require_POST
def table_update_layout(request: HttpRequest, pk: int) -> HttpResponse:
    # Single UPDATE, no SELECT, no FK fetch. Bypasses Table.save's room→branch
    # resync — fine for layout-only autosaves (room is never changed by this endpoint).
    try:
        layout_x = float(request.POST.get("x", 0))
        layout_y = float(request.POST.get("y", 0))
        layout_width = float(request.POST.get("width", 100))
        layout_height = float(request.POST.get("height", 80))
    except TypeError, ValueError:
        return HttpResponse("Invalid coordinates", status=400)
    Table.objects.filter(pk=pk).update(
        layout_x=layout_x,
        layout_y=layout_y,
        layout_width=layout_width,
        layout_height=layout_height,
        updated_at=Now(),
    )
    return HttpResponse("")


# ---------------------------------------------------------------------------
# Restaurant
# ---------------------------------------------------------------------------


@login_required
def restaurant_detail(request: HttpRequest) -> HttpResponse:
    restaurant = Restaurant.objects.select_related("default_room").first()
    if restaurant is None:
        return render(request, "backoffice/settings/restaurant_detail.html", {"restaurant": None})
    if request.method == "POST":
        form = RestaurantForm(request.POST, instance=restaurant)
        if form.is_valid():
            form.save()
            return redirect("settings:restaurant_detail")
    else:
        form = RestaurantForm(instance=restaurant)
    return render(
        request,
        "backoffice/settings/restaurant_detail.html",
        {"restaurant": restaurant, "form": form},
    )


@login_required
def restaurant_update(request: HttpRequest) -> HttpResponse:
    restaurant = Restaurant.objects.select_related("default_room").first()
    if request.method == "POST":
        form = RestaurantForm(request.POST, instance=restaurant)
        if form.is_valid():
            form.save()
            return redirect("settings:restaurant_detail")
    else:
        form = RestaurantForm(instance=restaurant)
    return render(
        request,
        "backoffice/settings/restaurant_form.html",
        {"form": form, "restaurant": restaurant},
    )


# ---------------------------------------------------------------------------
# UserRoomAssignment
# ---------------------------------------------------------------------------


@login_required
def user_room_list(request: HttpRequest) -> HttpResponse:
    assignments = UserRoomAssignment.objects.select_related("user", "room").all()
    return render(
        request,
        "backoffice/settings/user_room_list.html",
        {"assignments": assignments},
    )


@login_required
def user_room_create(request: HttpRequest) -> HttpResponse:
    if request.method == "POST":
        form = UserRoomAssignmentForm(request.POST)
        if form.is_valid():
            form.save()
            return redirect("settings:user_room_list")
    else:
        form = UserRoomAssignmentForm()
    return render(
        request,
        "backoffice/settings/user_room_form.html",
        {"form": form, "is_create": True},
    )


@login_required
def user_room_update(request: HttpRequest, pk: int) -> HttpResponse:
    assignment = get_object_or_404(UserRoomAssignment, pk=pk)
    if request.method == "POST":
        form = UserRoomAssignmentForm(request.POST, instance=assignment)
        if form.is_valid():
            form.save()
            return redirect("settings:user_room_list")
    else:
        form = UserRoomAssignmentForm(instance=assignment)
    return render(
        request,
        "backoffice/settings/user_room_form.html",
        {"form": form, "is_create": False, "assignment": assignment},
    )


@login_required
@require_POST
def user_room_delete(request: HttpRequest, pk: int) -> HttpResponse:
    assignment = get_object_or_404(UserRoomAssignment, pk=pk)
    assignment.delete()
    return redirect("settings:user_room_list")


# ---------------------------------------------------------------------------
# Staff Management
# ---------------------------------------------------------------------------


@login_required
def staff_list(request: HttpRequest) -> HttpResponse:
    if not request.user.has_backoffice_access:
        return redirect("web:home")

    search = request.GET.get("search", "")
    page = int(request.GET.get("page", 1))
    per_page = 20

    users = CustomUser.objects.all().order_by("-date_joined")
    if search:
        users = users.filter(
            models.Q(username__icontains=search)
            | models.Q(first_name__icontains=search)
            | models.Q(last_name__icontains=search)
        )
    # Prefetch only RestPOS role groups so role derivation uses the prefetch cache
    # (one group-membership query for the whole page rather than ~3 per user).
    users = users.prefetch_related(
        models.Prefetch("groups", queryset=Group.objects.filter(name__in=RESTPOS_GROUP_NAMES))
    )

    total = users.count()
    users = users[(page - 1) * per_page : page * per_page]
    total_pages = (total + per_page - 1) // per_page

    staff_data = [_build_staff_entry(user) for user in users]

    context = {
        "staff_data": staff_data,
        "search": search,
        "page": page,
        "total_pages": total_pages,
        "total": total,
    }
    if request.htmx:
        return render(request, "backoffice/settings/staff_list.html#staff-rows", context)
    return render(request, "backoffice/settings/staff_list.html", context)


@login_required
@require_POST
def staff_assign_role(request: HttpRequest, pk: int, role: str) -> HttpResponse:
    if not request.user.has_backoffice_access:
        return HttpResponse("Unauthorized", status=403)

    if not request.user.is_superuser:
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

    if request.htmx:
        response = render(
            request,
            "backoffice/settings/staff_list.html#staff-row",
            {"entry": _build_staff_entry(user)},
        )
        return response
    return redirect("settings:staff_list")


@login_required
@require_POST
def staff_remove_role(request: HttpRequest, pk: int) -> HttpResponse:
    if not request.user.has_backoffice_access:
        return HttpResponse("Unauthorized", status=403)

    if not request.user.is_superuser:
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

    if request.htmx:
        response = render(
            request,
            "backoffice/settings/staff_list.html#staff-row",
            {"entry": _build_staff_entry(user)},
        )
        return response
    return redirect("settings:staff_list")


def _build_staff_entry(user):
    # Uses the user's prefetched groups (from staff_list) or cached role lookups;
    # one query total per user rather than up to three per-row exists() checks.
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


# ---------------------------------------------------------------------------
# Phase 6 — POS Profile
# ---------------------------------------------------------------------------


@login_required
def pos_profile_settings(request: HttpRequest) -> HttpResponse:
    pos_profile = POSProfile.objects.select_related("branch", "warehouse", "restaurant").first()
    if request.method == "POST":
        if not (request.user.is_manager or request.user.is_admin or request.user.is_superuser):
            return redirect("web:home")
        form = POSProfileForm(request.POST, instance=pos_profile)
        if form.is_valid():
            form.save()
            messages.success(request, "POS profile settings saved.")
            return redirect("settings:pos_profile_settings")
    else:
        form = POSProfileForm(instance=pos_profile) if pos_profile else POSProfileForm()
    return render(
        request,
        "backoffice/settings/pos_profile_form.html",
        {"form": form, "pos_profile": pos_profile},
    )


# ---------------------------------------------------------------------------
# Phase 6 — Production Unit
# ---------------------------------------------------------------------------


@login_required
def production_unit_list(request: HttpRequest) -> HttpResponse:
    department = request.GET.get("department")
    production_units = ProductionUnit.objects.select_related("branch", "warehouse", "pos_profile").all()
    if department:
        production_units = production_units.filter(department=department)
    return render(
        request,
        "backoffice/settings/production_unit_list.html",
        {"production_units": production_units, "selected_department": department},
    )


@login_required
def production_unit_create(request: HttpRequest) -> HttpResponse:
    if not (request.user.is_manager or request.user.is_admin or request.user.is_superuser):
        return redirect("web:home")
    if request.method == "POST":
        form = ProductionUnitForm(request.POST)
        if form.is_valid():
            form.save()
            return redirect("settings:production_unit_list")
    else:
        form = ProductionUnitForm()
    return render(
        request,
        "backoffice/settings/production_unit_form.html",
        {"form": form, "is_create": True},
    )


@login_required
def production_unit_detail(request: HttpRequest, pk: int) -> HttpResponse:
    production_unit = get_object_or_404(
        ProductionUnit.objects.select_related("branch", "warehouse", "pos_profile"),
        pk=pk,
    )
    return render(
        request,
        "backoffice/settings/production_unit_detail.html",
        {"production_unit": production_unit},
    )


@login_required
def production_unit_update(request: HttpRequest, pk: int) -> HttpResponse:
    if not (request.user.is_manager or request.user.is_admin or request.user.is_superuser):
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
    if not (request.user.is_manager or request.user.is_admin or request.user.is_superuser):
        return redirect("web:home")
    production_unit = get_object_or_404(ProductionUnit, pk=pk)
    production_unit.delete()
    return redirect("settings:production_unit_list")


# ---------------------------------------------------------------------------
# Phase 6 — Tax Template
# ---------------------------------------------------------------------------


@login_required
def tax_template_list(request: HttpRequest) -> HttpResponse:
    tax_templates = TaxTemplate.objects.all().order_by("title")
    return render(
        request,
        "backoffice/settings/tax_template_list.html",
        {"tax_templates": tax_templates},
    )


@login_required
def tax_template_create(request: HttpRequest) -> HttpResponse:
    if not (request.user.is_manager or request.user.is_admin or request.user.is_superuser):
        return redirect("web:home")
    if request.method == "POST":
        form = TaxTemplateForm(request.POST)
        if form.is_valid():
            form.save()
            return redirect("settings:tax_template_list")
    else:
        form = TaxTemplateForm()
    return render(
        request,
        "backoffice/settings/tax_template_form.html",
        {"form": form, "title": "Tax Template", "is_create": True},
    )


@login_required
def tax_template_detail(request: HttpRequest, pk: int) -> HttpResponse:
    tax_template = get_object_or_404(TaxTemplate.objects.prefetch_related("rates"), pk=pk)
    return render(
        request,
        "backoffice/settings/tax_template_detail.html",
        {"tax_template": tax_template},
    )


@login_required
def tax_template_update(request: HttpRequest, pk: int) -> HttpResponse:
    if not (request.user.is_manager or request.user.is_admin or request.user.is_superuser):
        return redirect("web:home")
    tax_template = get_object_or_404(TaxTemplate, pk=pk)
    if request.method == "POST":
        form = TaxTemplateForm(request.POST, instance=tax_template)
        if form.is_valid():
            form.save()
            return redirect("settings:tax_template_detail", pk=tax_template.pk)
    else:
        form = TaxTemplateForm(instance=tax_template)
    return render(
        request,
        "backoffice/settings/tax_template_form.html",
        {"form": form, "title": "Tax Template", "is_create": False, "tax_template": tax_template},
    )


@login_required
@require_POST
def tax_template_delete(request: HttpRequest, pk: int) -> HttpResponse:
    if not (request.user.is_manager or request.user.is_admin or request.user.is_superuser):
        return redirect("web:home")
    tax_template = get_object_or_404(TaxTemplate, pk=pk)
    tax_template.delete()
    return redirect("settings:tax_template_list")
