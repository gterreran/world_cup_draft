"""
ASGI config for config project.

It exposes the ASGI callable as a module-level variable named ``application``.

For more information on this file, see
https://docs.djangoproject.com/en/5.2/howto/deployment/asgi/
"""

import os

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

from django.core.asgi import get_asgi_application

# Initialize Django before importing websocket URL patterns whose consumers may
# import ORM models.
django_asgi_app = get_asgi_application()

from channels.auth import AuthMiddlewareStack
from channels.routing import ProtocolTypeRouter, URLRouter

from drafts.routing import websocket_urlpatterns as draft_websocket_urlpatterns
from live_scores.routing import websocket_urlpatterns as live_score_websocket_urlpatterns

application = ProtocolTypeRouter(
    {
        "http": django_asgi_app,
        "websocket": AuthMiddlewareStack(
            URLRouter(draft_websocket_urlpatterns + live_score_websocket_urlpatterns)
        ),
    }
)
