from django.urls import path
from . import web

urlpatterns = [
    path("", web.home, name="home"),
    path("login/", web.login_page, name="login"),
    path("logout/", web.logout_page, name="logout"),
    path("invite/accept/", web.invitation_accept_page, name="invitation-accept"),
]
