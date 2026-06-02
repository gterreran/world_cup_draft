import json

from channels.generic.websocket import AsyncWebsocketConsumer


class DraftConsumer(AsyncWebsocketConsumer):
    """WebSocket consumer for live draft updates."""

    async def connect(self):
        self.slug = self.scope["url_route"]["kwargs"]["slug"]
        self.group_name = f"draft_{self.slug}"

        await self.channel_layer.group_add(
            self.group_name,
            self.channel_name,
        )

        await self.accept()

        await self.send(
            text_data=json.dumps(
                {
                    "type": "connection.accepted",
                    "slug": self.slug,
                }
            )
        )

    async def disconnect(self, close_code):
        await self.channel_layer.group_discard(
            self.group_name,
            self.channel_name,
        )