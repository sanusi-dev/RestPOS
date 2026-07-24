from allauth.account.signals import email_confirmed, user_signed_up
from django.conf import settings
from django.core.files.storage import default_storage
from django.core.mail import mail_admins
from django.db.models.signals import m2m_changed, post_delete, pre_save
from django.dispatch import receiver

from apps.users.models import CustomUser

# cached_property role attributes that must be invalidated when groups change.
# Cache them once so users.groups.add/.remove/.clear properly trigger fresh state.
_ROLE_CACHE_ATTRS = (
    "_restpos_group_names",
    "is_admin",
    "is_manager",
    "is_cashier",
    "has_backoffice_access",
    "has_staff_role",
)


@receiver(m2m_changed, sender=CustomUser.groups.through)
def clear_role_caches_on_group_change(sender, instance, action, **kwargs):
    """Invalidate cached_property role checks when a user's groups are mutated.

    is_admin / is_manager / is_cashier / has_backoffice_access / has_staff_role use
    @cached_property + a prefetched groups relation. Mutating groups via
    user.groups.add/remove/clear leaves the cached values stale. Pop them here so
    the next access re-computes from current group membership.
    """
    if action in ("post_add", "post_remove", "post_clear"):
        for attr in _ROLE_CACHE_ATTRS:
            instance.__dict__.pop(attr, None)


@receiver(user_signed_up)
def handle_sign_up(request, user, **kwargs):
    # customize this function to do custom logic on sign up, e.g. send a welcome email
    # or subscribe them to your mailing list.
    # This example notifies the admins, in case you want to keep track of sign ups
    _notify_admins_of_signup(user)


@receiver(email_confirmed)
def update_user_email(sender, request, email_address, **kwargs):
    """
    When an email address is confirmed make it the primary email.
    """
    # This also sets user.email to the new email address.
    # hat tip: https://stackoverflow.com/a/29661871/8207
    email_address.set_as_primary()


def _notify_admins_of_signup(user):
    mail_admins(
        f"Yowsers, someone signed up for {settings.PROJECT_METADATA['NAME']}!",
        f"Email: {user.email}",
        fail_silently=True,
    )


@receiver(pre_save, sender=CustomUser)
def remove_old_profile_picture_on_change(sender, instance, **kwargs):
    if not instance.pk:
        return False

    # Read one column instead of fetching the whole CustomUser row on every save.
    old_avatar = sender.objects.filter(pk=instance.pk).values_list("avatar", flat=True).first()
    if not old_avatar:
        return False

    if old_avatar != instance.avatar.name and default_storage.exists(old_avatar):
        default_storage.delete(old_avatar)


@receiver(post_delete, sender=CustomUser)
def remove_profile_picture_on_delete(sender, instance, **kwargs):
    if instance.avatar and default_storage.exists(instance.avatar.name):
        default_storage.delete(instance.avatar.name)
