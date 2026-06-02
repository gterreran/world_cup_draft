from channels.generic.websocket import AsyncJsonWebsocketConsumer
from collections import defaultdict

ROOM_COUNTS = defaultdict(set)

class DraftConsumer(AsyncJsonWebsocketConsumer):
    """WebSocket consumer for live draft updates."""

    async def connect(self):
        self.slug = self.scope["url_route"]["kwargs"]["slug"]
        self.group_name = f"draft_{self.slug}"

        await self.channel_layer.group_add(
            self.group_name,
            self.channel_name,
        )

        ROOM_COUNTS[self.group_name].add(self.channel_name)

        await self.accept()

        await self.send_json(
            {
                "type": "connection.accepted",
                "slug": self.slug,
            }
        )

        await self.broadcast_viewer_count()

    async def disconnect(self, close_code):
        await self.channel_layer.group_discard(
            self.group_name,
            self.channel_name,
        )

        ROOM_COUNTS[self.group_name].discard(self.channel_name)

        await self.broadcast_viewer_count()

    async def draft_state_changed(self, event):
        await self.send_json(
            {
                "type": "draft.state_changed",
            }
        )

    async def broadcast_viewer_count(self):
        await self.channel_layer.group_send(
            self.group_name,
            {
                "type": "draft.viewer_count_changed",
                "viewer_count": len(ROOM_COUNTS[self.group_name]),
            },
        )

    async def draft_viewer_count_changed(self, event):
        await self.send_json({
            "type": "draft.viewer_count_changed",
            "viewer_count": event["viewer_count"],
        })