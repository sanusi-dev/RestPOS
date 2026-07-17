from django.shortcuts import redirect


def home(request):
    if request.user.is_authenticated:
        return redirect("settings:dashboard")
    return redirect("account_login")
