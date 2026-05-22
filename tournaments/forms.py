from django import forms

from .models import Match


class MatchResultForm(forms.ModelForm):
    class Meta:
        model = Match
        fields = [
            "home_score",
            "away_score",
            "went_to_extra_time",
            "went_to_penalties",
            "winner",
        ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        match = self.instance
        if match and match.pk:
            self.fields["winner"].queryset = type(match.home_team).objects.filter(
                id__in=[match.home_team_id, match.away_team_id]
            )

            if match.stage == Match.Stage.GROUP:
                self.fields["winner"].disabled = True
                self.fields["went_to_extra_time"].disabled = True
                self.fields["went_to_penalties"].disabled = True