from django.urls import path

from .consumers import DraftConsumer

websocket_urlpatterns = [
    path("ws/draft/<slug:slug>/", DraftConsumer.as_asgi()),
]