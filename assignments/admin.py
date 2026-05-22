from django.contrib import admin

from .models import TeamAssignment


@admin.register(TeamAssignment)
class TeamAssignmentAdmin(admin.ModelAdmin):
    list_display = ("league", "member", "national_team", "assigned_at")
    list_filter = ("league", "national_team__pot")
    search_fields = ("member__display_name", "national_team__name")
