from django.contrib.auth.decorators import login_required
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from .forms import (
    BranchForm,
    RestaurantForm,
    RoomForm,
    TableForm,
    UserRoomAssignmentForm,
)
from .models import Branch, Restaurant, Room, Table, UserRoomAssignment


@login_required
def settings_dashboard(request: HttpRequest) -> HttpResponse:
    context = {
        "branch_count": Branch.objects.count(),
        "room_count": Room.objects.count(),
        "table_count": Table.objects.count(),
        "restaurant_count": Restaurant.objects.count(),
        "assignment_count": UserRoomAssignment.objects.count(),
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
    return render(request, "backoffice/settings/branch_form.html", {"form": form, "is_create": True})


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
    return render(request, "backoffice/settings/branch_form.html", {"form": form, "is_create": False, "branch": branch})


# ---------------------------------------------------------------------------
# Room
# ---------------------------------------------------------------------------


@login_required
def room_list(request: HttpRequest) -> HttpResponse:
    branch_id = request.GET.get("branch")
    rooms = Room.objects.select_related("branch").all()
    if branch_id:
        rooms = rooms.filter(branch_id=branch_id)
    branches = Branch.objects.all().order_by("name")
    return render(
        request,
        "backoffice/settings/room_list.html",
        {"rooms": rooms, "branches": branches, "selected_branch": branch_id},
    )


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
    room = get_object_or_404(Room.objects.select_related("branch"), pk=pk)
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
    tables = Table.objects.select_related("room", "branch", "room__branch").all()
    if room_id:
        tables = tables.filter(room_id=room_id)
    rooms = Room.objects.select_related("branch").all().order_by("branch__name", "name")
    return render(
        request,
        "backoffice/settings/table_list.html",
        {"tables": tables, "rooms": rooms, "selected_room": room_id},
    )


@login_required
def table_layout(request: HttpRequest) -> HttpResponse:
    room_id = request.GET.get("room")
    tables = Table.objects.select_related("room", "branch", "room__branch").all()
    if room_id:
        tables = tables.filter(room_id=room_id)
    rooms = Room.objects.select_related("branch").all().order_by("branch__name", "name")
    return render(
        request,
        "backoffice/settings/table_layout.html",
        {"tables": tables, "rooms": rooms, "selected_room": room_id},
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
    table = get_object_or_404(Table.objects.select_related("room", "branch", "room__branch"), pk=pk)
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
    table = get_object_or_404(Table, pk=pk)
    try:
        table.layout_x = float(request.POST.get("x", 0))
        table.layout_y = float(request.POST.get("y", 0))
        table.layout_width = float(request.POST.get("width", 100))
        table.layout_height = float(request.POST.get("height", 80))
        table.save(update_fields=["layout_x", "layout_y", "layout_width", "layout_height", "updated_at"])
    except TypeError, ValueError:
        return HttpResponse("Invalid coordinates", status=400)
    return HttpResponse("")


# ---------------------------------------------------------------------------
# Restaurant
# ---------------------------------------------------------------------------


@login_required
def restaurant_detail(request: HttpRequest) -> HttpResponse:
    restaurant = Restaurant.objects.select_related("branch", "default_room", "default_room__branch").first()
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
    restaurant = Restaurant.objects.select_related("branch", "default_room").first()
    if restaurant is None:
        return redirect("settings:restaurant_detail")
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
    assignments = UserRoomAssignment.objects.select_related("user", "room", "room__branch", "branch").all()
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
