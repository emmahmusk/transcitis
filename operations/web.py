from django.shortcuts import render


def home(request):
    return render(request, "operations/app.html")


def login_page(request):
    return render(request, "operations/login.html")


def logout_page(request):
    return render(request, "operations/login.html")


def invitation_accept_page(request):
    return render(request, "operations/invitation_accept.html", {"token": request.GET.get("token", "")})
