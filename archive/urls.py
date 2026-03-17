from django.urls import path

from . import views

urlpatterns = [
    path("", views.chats, name="chats"),
    path("chat/<int:chat_id>/", views.chat_detail, name="chat_detail"),
    path("search/", views.search, name="search"),
]
