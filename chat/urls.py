from django.urls import path

from chat import views

urlpatterns = [
    path("health", views.health, name="health"),
    path("health/", views.health, name="health_slash"),
    path("", views.index, name="index"),
    path("api/bootstrap/", views.bootstrap, name="bootstrap"),
    path("api/messages/", views.proxy_messages, name="proxy_messages"),
    path("api/send/", views.proxy_send, name="proxy_send"),
    path("api/seen/", views.proxy_seen, name="proxy_seen"),
]
