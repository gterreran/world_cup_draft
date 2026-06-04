from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth import get_user_model


class SignUpForm(UserCreationForm):
    """Basic account creation form for public signup."""

    class Meta(UserCreationForm.Meta):
        model = get_user_model()
        fields = ("username",)
