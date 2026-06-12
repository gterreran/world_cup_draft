from django import forms

from .models import Match, NationalTeam


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
    def clean(self):
        cleaned_data = super().clean()

        # Manual result edits represent a completed result. Set the instance
        # status before ModelForm runs model-level validation, otherwise
        # Match.clean() rejects score fields on a scheduled match.
        if cleaned_data.get("home_score") is not None and cleaned_data.get("away_score") is not None:
            self.instance.status = Match.Status.FINAL

        if self.instance.stage == Match.Stage.GROUP:
            cleaned_data["winner"] = None
            cleaned_data["went_to_extra_time"] = False
            cleaned_data["went_to_penalties"] = False

        if cleaned_data.get("went_to_penalties"):
            cleaned_data["went_to_extra_time"] = True

        return cleaned_data
