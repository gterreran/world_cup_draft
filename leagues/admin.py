from django.contrib import admin

from .models import League, LeagueMember


class LeagueMemberInline(admin.TabularInline):
    model = LeagueMember
    extra = 0


@admin.register(League)
class LeagueAdmin(admin.ModelAdmin):
    list_display = ("name", "commissioner", "tournament", "teams_per_manager", "assignment_method", "created_at")
    list_filter = ("assignment_method", "use_tiers", "tournament")
    search_fields = ("name", "commissioner__username")
    prepopulated_fields = {"slug": ("name",)}
    inlines = [LeagueMemberInline]


@admin.register(LeagueMember)
class LeagueMemberAdmin(admin.ModelAdmin):
    list_display = ("display_name", "league", "user", "sleeper_user_id", "draft_order")
    list_filter = ("league",)
    search_fields = ("display_name", "sleeper_user_id")
