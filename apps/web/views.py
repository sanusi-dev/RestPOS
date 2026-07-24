from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render


def home(request):
    if request.user.is_authenticated:
        if request.user.has_backoffice_access:
            return redirect("web:dashboard")
        if request.user.has_staff_role:
            return redirect("web:pos_index")
        return redirect("web:pending_approval")
    return render(request, "web/landing.html")


@login_required
def dashboard(request):
    return render(request, "backoffice/dashboard.html")


@login_required
def pos_index(request):
    return render(request, "pos/index.html")


@login_required
def pending_approval(request):
    if request.user.has_staff_role:
        return redirect("web:home")
    return render(request, "web/pending_approval.html")
