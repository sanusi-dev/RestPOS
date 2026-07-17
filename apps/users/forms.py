from allauth.account.forms import SignupForm
from django import forms
from django.contrib.auth.forms import UserChangeForm
from django.utils.translation import gettext_lazy as _

from .helpers import validate_profile_picture
from .models import CustomUser


class CustomSignupForm(SignupForm):
    """Custom signup form for RestPOS."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["password1"].help_text = ""


class CustomUserChangeForm(UserChangeForm):
    email = forms.EmailField(label=_("Email"), required=True)

    class Meta:
        model = CustomUser
        fields = ("email", "first_name", "last_name")


class UploadAvatarForm(forms.Form):
    avatar = forms.FileField(validators=[validate_profile_picture])
