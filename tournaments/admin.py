from django.contrib import admin

from .models import Match, NationalTeam, TeamTournamentStatus, Tournament


@admin.register(Tournament)
class TournamentAdmin(admin.ModelAdmin):
    list_display = ("name", "year", "status")
    prepopulated_fields = {"slug": ("name", "year")}


@admin.register(NationalTeam)
class NationalTeamAdmin(admin.ModelAdmin):
    list_display = ("name", "fifa_code", "tournament", "pot", "group", "fifa_rank")
    list_filter = ("tournament", "pot", "group", "confederation")
    search_fields = ("name", "fifa_code")


@admin.register(Match)
class MatchAdmin(admin.ModelAdmin):
    list_display = (
        "match_number",
        "tournament",
        "stage",
        "group",
        "status",
        "home_team",
        "away_team",
        "home_slot",
        "away_slot",
        "home_score",
        "away_score",
        "winner",
        "kickoff_time",
        "venue",
    )
    list_filter = ("tournament", "stage", "status", "venue", "group")
    search_fields = (
        "home_team__name",
        "away_team__name",
        "home_slot",
        "away_slot",
        "venue",
    )
    ordering = ("kickoff_time", "match_number")

@admin.register(TeamTournamentStatus)
class TeamTournamentStatusAdmin(admin.ModelAdmin):
    list_display = (
        "team",
        "tournament",
        "advanced_from_group",
        "eliminated_stage",
        "finish_rank",
    )
    list_filter = (
        "tournament",
        "advanced_from_group",
        "eliminated_stage",
    )
    search_fields = ("team__name",)