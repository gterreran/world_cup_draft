from django.contrib.auth import login
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render

from .forms import SignUpForm
from .services import get_or_create_profile


def signup(request):
    """Create a new user account and log the user in."""
    if request.user.is_authenticated:
        return redirect("league_list")

    if request.method == "POST":
        form = SignUpForm(request.POST)
        if form.is_valid():
            user = form.save()
            get_or_create_profile(user)
            login(request, user)
            return redirect("league_list")
    else:
        form = SignUpForm()

    return render(request, "registration/signup.html", {"form": form})
