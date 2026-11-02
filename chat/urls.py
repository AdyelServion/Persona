from django.urls import path

from chat import views

urlpatterns = [
    path("health", views.health, name="health"),
    path("health/", views.health, name="health_slash"),
    path("", views.index, name="index"),
    path("api/users/", views.users_list, name="users_list"),
    path("api/users/new/", views.users_new, name="users_new"),
    path("api/users/resume/", views.users_resume, name="users_resume"),
    path("api/users/switch/", views.users_switch, name="users_switch"),
    path("api/bootstrap/", views.bootstrap, name="bootstrap"),
    path("api/messages/", views.proxy_messages, name="proxy_messages"),
    path("api/send/", views.proxy_send, name="proxy_send"),
    path("api/seen/", views.proxy_seen, name="proxy_seen"),
    path("api/proactive-settings/", views.proactive_settings, name="proactive_settings"),
]
