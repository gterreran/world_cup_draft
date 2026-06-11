from django.contrib import admin

from .models import LiveMatchState, ProviderFixtureMapping


@admin.register(ProviderFixtureMapping)
class ProviderFixtureMappingAdmin(admin.ModelAdmin):
    list_display = (
        "provider",
        "provider_fixture_id",
        "match",
        "provider_home_name",
        "provider_away_name",
        "provider_starting_at",
        "confidence",
    )
    list_filter = ("provider",)
    search_fields = (
        "provider_fixture_id",
        "provider_home_name",
        "provider_away_name",
        "match__home_team__name",
        "match__away_team__name",
        "match__home_slot",
        "match__away_slot",
    )
    autocomplete_fields = ("match",)


@admin.register(LiveMatchState)
class LiveMatchStateAdmin(admin.ModelAdmin):
    list_display = (
        "match",
        "provider",
        "provider_fixture_id",
        "status",
        "provider_state_code",
        "home_score",
        "away_score",
        "minute",
        "last_seen_at",
    )
    list_filter = ("provider", "status", "provider_state_code")
    search_fields = (
        "provider_fixture_id",
        "match__home_team__name",
        "match__away_team__name",
        "match__home_slot",
        "match__away_slot",
    )
    autocomplete_fields = ("match",)
