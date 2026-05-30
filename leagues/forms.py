from django import forms

from .models import League, LeagueMember
from scoring.defaults import (
    TIEBREAKER_CHOICES,
    default_scoring_config,
    default_tiebreaker_config,
)


class LeagueCreateForm(forms.ModelForm):
    class Meta:
        model = League
        fields = [
            "name",
            "tournament",
            "teams_per_manager",
            "assignment_method",
            "sleeper_league_id",
        ]

        widgets = {
            "name": forms.TextInput(attrs={"placeholder": "e.g. The Most Chaotic League"}),
            "teams_per_manager": forms.NumberInput(attrs={"min": 1, "max": 8}),
            "sleeper_league_id": forms.TextInput(
                attrs={"placeholder": "Optional Sleeper league ID"}
            ),
        }


class LeagueMemberCreateForm(forms.ModelForm):
    class Meta:
        model = LeagueMember
        fields = ["display_name"]

        widgets = {
            "display_name": forms.TextInput(
                attrs={"placeholder": "e.g. Giacomo, The Commish, Team Chaos"}
            ),
        }


class LeagueSettingsForm(forms.ModelForm):
    class Meta:
        model = League
        fields = [
            "name",
            "teams_per_manager",
            "assignment_method",
            "sleeper_league_id",
        ]

        widgets = {
            "name": forms.TextInput(),
            "teams_per_manager": forms.NumberInput(attrs={"min": 1, "max": 8}),
            "sleeper_league_id": forms.TextInput(
                attrs={"placeholder": "Optional Sleeper league ID"}
            ),
        }


    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        league = self.instance
        if league and league.pk and league.is_setup_locked:
            for field_name in (
                "teams_per_manager",
                "assignment_method",
                "sleeper_league_id",
            ):
                self.fields[field_name].disabled = True
                self.fields[field_name].help_text = (
                    "Unlock the league before changing setup/assignment settings."
                )

    def save(self, commit=True):
        league = super().save(commit=False)

        if commit:
            league.save()

        return league


class LeagueScoringSettingsForm(forms.Form):
    group_win = forms.DecimalField(label="Group win", min_value=0, initial=3)
    group_draw = forms.DecimalField(label="Group draw", min_value=0, initial=1)
    group_loss = forms.DecimalField(label="Group loss", min_value=0, initial=0)

    qualify_knockout = forms.DecimalField(
        label="Advance from group stage",
        min_value=0,
        initial=3,
    )

    knockout_win_regulation = forms.DecimalField(
        label="Knockout win in regulation",
        min_value=0,
        initial=4,
    )
    knockout_win_extra_time = forms.DecimalField(
        label="Knockout win after extra time",
        min_value=0,
        initial=3,
    )
    knockout_win_penalties = forms.DecimalField(
        label="Knockout win on penalties",
        min_value=0,
        initial=2,
    )
    knockout_loss_extra_time = forms.DecimalField(
        label="Knockout loss after extra time",
        min_value=0,
        initial=1,
    )
    knockout_loss_penalties = forms.DecimalField(
        label="Knockout loss on penalties",
        min_value=0,
        initial=1,
    )

    champion_bonus = forms.DecimalField(label="Champion bonus", min_value=0, initial=8)
    runner_up_bonus = forms.DecimalField(label="Runner-up bonus", min_value=0, initial=5)
    third_place_bonus = forms.DecimalField(label="Third-place bonus", min_value=0, initial=3)
    fourth_place_bonus = forms.DecimalField(label="Fourth-place bonus", min_value=0, initial=2)

    tiebreakers = forms.MultipleChoiceField(
        choices=TIEBREAKER_CHOICES,
        widget=forms.CheckboxSelectMultiple,
        required=False,
        label="Standings tiebreakers",
        help_text="Applied in order after total fantasy points.",
    )

    def __init__(self, *args, league=None, **kwargs):
        super().__init__(*args, **kwargs)

        self.league = league

        if league is None:
            return

        scoring_config = default_scoring_config() | league.scoring_config
        tiebreaker_config = league.tiebreaker_config or default_tiebreaker_config()

        for key in default_scoring_config():
            self.fields[key].initial = scoring_config[key]

        self.fields["tiebreakers"].initial = tiebreaker_config

    def save(self):
        if self.league is None:
            raise ValueError("LeagueScoringSettingsForm requires a league.")

        scoring_keys = default_scoring_config().keys()

        self.league.scoring_config = {
            key: float(self.cleaned_data[key])
            for key in scoring_keys
        }
        self.league.tiebreaker_config = self.cleaned_data["tiebreakers"]
        self.league.save(
            update_fields=[
                "scoring_config",
                "tiebreaker_config",
                "updated_at",
            ]
        )

        return self.league

