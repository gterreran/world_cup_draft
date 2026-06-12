from django.urls import path

from .consumers import LiveScoreConsumer

websocket_urlpatterns = [
    path("ws/tournaments/<slug:tournament_slug>/scores/", LiveScoreConsumer.as_asgi()),
]
