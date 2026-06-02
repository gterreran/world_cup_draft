from django.contrib import admin

from .models import DraftState


@admin.register(DraftState)
class DraftStateAdmin(admin.ModelAdmin):
    list_display = (
        "league",
        "status",
        "current_pick_index",
        "reveal_phase",
        "autoplay",
        "updated_at",
    )
    list_filter = ("status", "reveal_phase", "autoplay")
    search_fields = ("league__name", "league__slug")
