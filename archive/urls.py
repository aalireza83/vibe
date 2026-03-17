from django.urls import path

from . import views

urlpatterns = [
    path("", views.chats, name="chats"),
    path("chat/<int:chat_id>/", views.chat_detail, name="chat_detail"),
    path("chat/<int:chat_id>/export/", views.export_chat, name="export_chat"),
    path("chat/<int:chat_id>/media/", views.chat_media, name="chat_media"),
    path("bookmarks/", views.bookmarks, name="bookmarks"),
    path("search/", views.search, name="search"),
    path("api/chat/<int:chat_id>/poll/", views.api_poll_chat, name="api_poll_chat"),
    path("api/chats/list/", views.api_chats_list, name="api_chats_list"),
    path("api/message/<int:message_pk>/bookmark/", views.api_toggle_bookmark, name="api_toggle_bookmark"),
]
