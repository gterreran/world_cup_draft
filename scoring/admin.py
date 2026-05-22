from django.contrib import admin

from .models import StandingEntry


@admin.register(StandingEntry)
class StandingEntryAdmin(admin.ModelAdmin):
    list_display = ("league", "member", "current_rank", "points", "wins", "draws", "losses", "goal_difference", "goals_scored")
    list_filter = ("league",)
    search_fields = ("member__display_name",)
