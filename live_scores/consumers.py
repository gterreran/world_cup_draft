from __future__ import annotations

from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncJsonWebsocketConsumer

from tournaments.models import Tournament

from .broadcasts import tournament_score_group_name


class LiveScoreConsumer(AsyncJsonWebsocketConsumer):
    """WebSocket consumer for tournament live-score updates."""

    async def connect(self):
        self.tournament_slug = self.scope["url_route"]["kwargs"]["tournament_slug"]
        exists = await self._tournament_exists(self.tournament_slug)
        if not exists:
            await self.close(code=4404)
            return

        self.group_name = tournament_score_group_name(self.tournament_slug)
        await self.channel_layer.group_add(self.group_name, self.channel_name)
        await self.accept()
        await self.send_json(
            {
                "type": "live_scores.connection_accepted",
                "tournament_slug": self.tournament_slug,
            }
        )

    async def disconnect(self, close_code):
        group_name = getattr(self, "group_name", None)
        if group_name:
            await self.channel_layer.group_discard(group_name, self.channel_name)

    async def match_score_changed(self, event):
        await self.send_json(event["payload"])

    @database_sync_to_async
    def _tournament_exists(self, slug: str) -> bool:
        return Tournament.objects.filter(slug=slug).exists()
