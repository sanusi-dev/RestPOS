# Authentication and Authorization

## Authentication

`AUTH_USER_MODEL` is `users.CustomUser`. django-allauth provides `/accounts/login/`, signup, logout, and related routes. `CustomLoginForm` and `CustomSignupForm` only adjust help text. Email verification defaults to `none`; if enabled, `email_confirmed` sets the confirmed address primary.

## Roles

Roles are Django groups seeded after migrations:

- `RestPOS Admin`
- `RestPOS Manager`
- `RestPOS Cashier`

Cached properties in `CustomUser` derive `is_admin`, `is_manager`, `is_cashier`, `has_backoffice_access`, and `has_staff_role`. `users.signals.clear_role_caches_on_group_change()` invalidates these caches after group changes.

## Route Gates

`BackofficeAccessMiddleware`:

- prefetched groups on `/pos/` and `/backoffice/`;
- redirected non-backoffice users from `/backoffice/` to `web:pos_index`;
- redirected users without any staff role from `/pos/` to `web:pending_approval`.

The middleware does not gate `/admin/`, `/accounts/`, or `/users/`; those paths rely on their own Django/allauth/view checks.

## Explicit View Checks

- Manager/admin/superuser: backoffice order cancel and return; Restaurant and ProductionUnit mutations.
- Superuser only: assigning/removing RestPOS staff roles.
- Manager/admin/superuser: ticket reprint from POS.
- Any authenticated staff-role user: normal POS use, including settlement and retry.

Backoffice order list/detail/KOT views are login-protected but do not repeat `has_backoffice_access`; normally the middleware protects them, but direct invocation/testing should account for that boundary.

## Profile Side Effects

`users.views.upload_profile_image()` validates extension and 5 MB size, saves the avatar, and returns plain success or JSON errors. Avatar replacement/deletion removes old files through signals. Without an uploaded avatar, `CustomUser.avatar_url` returns an external Gravatar URL.

## Access Debugging

Start at `restpos/settings.py` middleware order, then `apps/web/middleware.py`, then cached role properties in `apps/users/models.py`. If a role appears stale after a group change, inspect the m2m signal and prefetched group cache. If a backoffice action is unexpectedly available, inspect whether it relies only on middleware or has an explicit view-level check.
