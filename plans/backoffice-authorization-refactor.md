# Backoffice Authorization Refactor — Implementation Plan

**Django version:** 6.0+ (decorators `login_required`, `user_passes_test`, `permission_required`; middleware `LoginRequiredMiddleware` + `login_not_required`)  
**Status:** Approved for implementation

---

## 1. Objective

Replace the custom `BackofficeAccessMiddleware` path-prefix gate with explicit per-view decorators. After this change every `/backoffice/*` and `/pos/*` view declares its own role requirement. No view relies on URL prefix to be secure.

Failure mode is `403 PermissionDenied`, not a silent `302` redirect.

---

## 2. Django 6.0 Approach

Django 6.0 docs (`topics/auth/default`) define two authorization layers:

- **Site-wide login:** `django.contrib.auth.middleware.LoginRequiredMiddleware`. When installed, every view requires authentication. Public views opt out with `@login_not_required`. Use this to replace the hand-rolled "must be logged in" part.
- **Per-view authorization:** `login_required`, `user_passes_test`, `permission_required` (FBV) and `LoginRequiredMixin`, `UserPassesTestMixin`, `PermissionRequiredMixin` (CBV). Each protected view declares its own test. `raise_exception=True` → `403`.

RestPOS uses function-based views, so the fix uses `user_passes_test` wrappers. Roles stay as Django `Group` membership (`RestPOS Admin`, `RestPOS Manager`, `RestPOS Cashier`) read via `CustomUser` properties. No new `Permission` objects, no `django-guardian`, no object-level permissions. That would be overengineering for three coarse roles.

---

## 3. What Gets Created

### 3.1 New file: `apps/users/decorators.py`

This is the only new file. Every backoffice and POS view imports from it.

```python
from functools import wraps

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied


def _role_required(test_func):
    def decorator(view_func):
        @wraps(view_func)
        @login_required
        def _wrapped(request, *args, **kwargs):
            if not test_func(request.user):
                raise PermissionDenied
            return view_func(request, *args, **kwargs)
        return _wrapped
    return decorator


backoffice_required = _role_required(lambda u: u.has_backoffice_access)
manager_required = _role_required(lambda u: u.is_superuser or u.is_admin or u.is_manager)
staff_required = _role_required(lambda u: u.has_staff_role)
admin_required = _role_required(lambda u: u.is_superuser or u.is_admin)
```

Rules for this file:

- `login_required` runs first. Anonymous users go to `settings.LOGIN_URL?next=...`.
- Authenticated users who fail the role test get `403`, not a redirect.
- `admin_required` is for staff role assignment only. Do not use it elsewhere.
- `manager_required` includes superuser and admin. Do not write `is_manager` alone in views.

For class-based views, use `UserPassesTestMixin` with `raise_exception = True` and the same `test_func`. RestPOS has no CBVs today, so this is not needed now.

---

## 4. What Gets Deleted

### 4.1 Delete `BackofficeAccessMiddleware`

File: `apps/web/middleware.py`

- Delete the entire `BackofficeAccessMiddleware` class (lines 8–24).
- Keep `MessagesMiddleware` untouched.
- Delete the `prefetch_related_objects([request.user], "groups")` call inside it.
- Keep imports `json`, `django_messages`, `redirect` only if `MessagesMiddleware` still needs them. Remove `prefetch_related_objects` import.

### 4.2 Remove from `MIDDLEWARE`

File: `restpos/settings.py`

- Remove the line `"apps.web.middleware.BackofficeAccessMiddleware",` from `MIDDLEWARE`.
- Add `"django.contrib.auth.middleware.LoginRequiredMiddleware",` immediately after `"django.contrib.auth.middleware.AuthenticationMiddleware",`.

### 4.3 Public views

File: `apps/web/views.py`

- Add `from django.contrib.auth.decorators import login_not_required` at the top.
- Add `@login_not_required` to `home` (line 5). This is the only public page when `LoginRequiredMiddleware` is active. Without this decorator, anonymous users would redirect-loop to login.

All other views stay protected by the role decorators. They do not need `@login_not_required`.

---

## 5. What Gets Simplified

### 5.1 `apps/users/models.py`

Change the five role helpers from `@cached_property` to plain `@property`:

- `is_admin`, `is_manager`, `is_cashier`, `has_backoffice_access`, `has_staff_role` → `@property`.
- Each property does `self.groups.filter(name__in=[...]).exists()` or delegates to the other properties. No caching.
- Delete `_restpos_group_names` cached property.

Why: the `cached_property` + prefetch + signal exists only to make string-name checks fast. Plain `exists()` is one indexed query and needs no invalidation. `LoginRequiredMiddleware` does not prefetch groups, so the prefetch optimization has no home after the middleware is deleted.

### 5.2 `apps/users/signals.py`

- Delete `clear_role_caches_on_group_change` (the `m2m_changed` handler) and `_ROLE_CACHE_ATTRS`.
- Keep `handle_sign_up`, `update_user_email`, `remove_old_profile_picture_on_change`, `remove_profile_picture_on_delete` untouched.
- Remove the `m2m_changed` import if nothing else uses it.

---

## 6. View Changes — Every File

Apply decorators exactly as listed. Replace every inline `if not (is_manager or is_admin or is_superuser): redirect(...)` or `raise PermissionDenied` block with the decorator. Delete the inline block after adding the decorator.

### 6.1 `apps/inventory/views.py` — 33 views

Add at top: `from apps.users.decorators import backoffice_required`

| View | Decorator |
|---|---|
| `inventory_dashboard` | `@backoffice_required` |
| `uom_list` | `@backoffice_required` |
| `uom_create` | `@backoffice_required` |
| `uom_update` | `@backoffice_required` |
| `item_group_list` | `@backoffice_required` |
| `item_group_create` | `@backoffice_required` |
| `item_group_detail` | `@backoffice_required` |
| `item_group_update` | `@backoffice_required` |
| `warehouse_list` | `@backoffice_required` |
| `warehouse_create` | `@backoffice_required` |
| `warehouse_detail` | `@backoffice_required` |
| `warehouse_update` | `@backoffice_required` |
| `item_list` | `@backoffice_required` |
| `item_create` | `@backoffice_required` |
| `item_detail` | `@backoffice_required` |
| `item_update` | `@backoffice_required` |
| `stock_entry_list` | `@backoffice_required` |
| `stock_entry_create` | `@backoffice_required` |
| `stock_entry_item_add` | `@backoffice_required` |
| `stock_entry_item_remove` | `@backoffice_required` |
| `stock_entry_detail` | `@backoffice_required` |
| `stock_entry_submit` | `@backoffice_required` |
| `stock_entry_cancel` | `@backoffice_required` |
| `reconciliation_list` | `@backoffice_required` |
| `reconciliation_create` | `@backoffice_required` |
| `reconciliation_item_add` | `@backoffice_required` |
| `reconciliation_item_remove` | `@backoffice_required` |
| `reconciliation_detail` | `@backoffice_required` |
| `reconciliation_submit` | `@backoffice_required` |
| `reconciliation_cancel` | `@backoffice_required` |
| `purchase_receipt_list` | `@backoffice_required` |
| `purchase_receipt_create` | `@backoffice_required` |
| `purchase_receipt_item_add` | `@backoffice_required` |
| `purchase_receipt_item_remove` | `@backoffice_required` |
| `purchase_receipt_detail` | `@backoffice_required` |
| `purchase_receipt_submit` | `@backoffice_required` |
| `purchase_receipt_cancel` | `@backoffice_required` |
| `stock_ledger_list` | `@backoffice_required` |
| `stock_balance_list` | `@backoffice_required` |

Remove `@login_required` from each. Replace with `@backoffice_required` alone (it already includes `login_required`).

### 6.2 `apps/menu/views.py` — 18 views

Add at top: `from apps.users.decorators import backoffice_required`

Every view in this file gets `@backoffice_required` replacing `@login_required`:

`menu_dashboard`, `menu_list`, `menu_create`, `menu_detail`, `menu_update`, `menu_item_list`, `menu_item_create`, `menu_item_detail`, `menu_item_update`, `add_on_list`, `add_on_create`, `add_on_detail`, `add_on_update`, plus the variant views.

### 6.3 `apps/payments/views.py` — 9 views

Add at top: `from apps.users.decorators import backoffice_required, manager_required`

| View | Decorator |
|---|---|
| `payments_dashboard` | `@backoffice_required` |
| `mode_list` | `@backoffice_required` |
| `mode_create` | `@manager_required` |
| `mode_detail` | `@backoffice_required` |
| `mode_update` | `@manager_required` |
| `gl_mapping_list` | `@backoffice_required` |
| `gl_mapping_create` | `@manager_required` |
| `gl_mapping_update` | `@manager_required` |
| `gl_mapping_delete` | `@manager_required` |

Reads are backoffice, writes are manager. This matches how `apps/accounting` already gates GL config.

### 6.4 `apps/staff/views.py` — 9 views

Add at top: `from apps.users.decorators import staff_required`

Every view in this file gets `@staff_required` replacing `@login_required`:

`staff_dashboard`, `opening_entry_list`, `opening_entry_create`, `opening_entry_detail`, `opening_entry_submit`, `opening_entry_cancel`, `closing_entry_list`, `closing_entry_create`, `closing_entry_detail`, `closing_entry_submit`, `closing_entry_cancel`.

Shift open and close is done by cashiers on the POS. It is not manager-only, so `staff_required` is correct. Do not use `backoffice_required` here.

### 6.5 `apps/orders/views.py` — 11 views

Add at top: `from apps.users.decorators import backoffice_required, manager_required`

| View | Decorator | Action |
|---|---|---|
| `orders_dashboard` | `@backoffice_required` | Replace `@login_required` |
| `order_list` | `@backoffice_required` | Replace `@login_required` |
| `order_detail` | `@backoffice_required` | Replace `@login_required` |
| `kot_list` | `@backoffice_required` | Replace `@login_required` |
| `kot_detail` | `@backoffice_required` | Replace `@login_required` |
| `order_cancel` | `@manager_required` | Replace `@login_required` + delete `if not (is_manager or is_admin ...): messages.error + redirect` block |
| `order_return` | `@manager_required` | Same — delete inline check |
| `order_return_submit` | `@manager_required` | Same — delete inline check |
| `order_return_line_update` | `@manager_required` | Same — delete inline check |
| `order_delete` | `@manager_required` | Same — delete inline check |
| `order_return` (second) | `@manager_required` | Same |

### 6.6 `apps/orders/views_pos.py` — 15 views

Add at top: `from apps.users.decorators import staff_required, manager_required`

All 15 views get `@staff_required` replacing `@login_required`. The `reprint` action inside `pos_order_action` (around line 949) already has `if action == "reprint" and not (is_manager or is_admin or is_superuser):` — keep that in-view capability check. It is a row-level permission inside a staff view, not a view-level gate.

### 6.7 `apps/settings/views.py` — 10 views

Add at top: `from apps.users.decorators import backoffice_required, manager_required, admin_required`

| View | Decorator | Action |
|---|---|---|
| `settings_dashboard` | `@backoffice_required` | Replace `@login_required` |
| `restaurant_settings` | `@manager_required` | Replace `@login_required` + delete `if not (is_manager or is_admin ...): redirect("web:home")` |
| `staff_list` | `@backoffice_required` | Replace `@login_required` + delete `if not has_backoffice_access: redirect` |
| `staff_assign_role` | `@admin_required` | Replace `@login_required` + delete both `if not has_backoffice_access` and `if not is_superuser` blocks |
| `staff_remove_role` | `@admin_required` | Same |
| `production_unit_list` | `@backoffice_required` | Replace `@login_required` |
| `production_unit_create` | `@manager_required` | Replace + delete inline check |
| `production_unit_detail` | `@backoffice_required` | Replace `@login_required` |
| `production_unit_update` | `@manager_required` | Replace + delete inline check |
| `production_unit_delete` | `@manager_required` | Replace + delete inline check |

Also fix the bug on lines 91–95: delete the `for pk in users.values_list...: print(pk)` debug loop.

### 6.8 `apps/accounting/views.py` and `apps/accounting/payables_views.py` — 35 views

Add at top: `from apps.users.decorators import manager_required`

Every view already calls `_require_manager(request)` which raises `403`. Replace that call with the decorator:

- Delete the `_require_manager` and `_authenticated_user` helper functions in both files.
- Replace `@login_required` + `_require_manager(request)` at the top of each view with a single `@manager_required`.
- Example: `accounting_dashboard`, `chart_of_accounts`, `journal_entry_create`, `supplier_list`, `supplier_invoice_submit`, etc. — all 35 views.

### 6.9 `apps/reports/views.py` — 13 views

Add at top: `from apps.users.decorators import manager_required`

Same as accounting: delete `_require_manager` and `_authenticated_user`, replace `@login_required` + `_require_manager(request)` with `@manager_required` on every view: `pnl_settings`, `daily_pnl_list`, `daily_pnl_create`, `daily_pnl_update`, `daily_pnl_detail`, `daily_pnl_preview`, `daily_pnl_submit`, `daily_pnl_cancel`, `daily_pnl_amend`, `daily_pnl_material_add`, `daily_pnl_material_remove`, `daily_pnl_adhoc_add`, `daily_pnl_adhoc_remove`.

### 6.10 `apps/web/views.py` — 3 views

Add at top: `from django.contrib.auth.decorators import login_not_required` and `from apps.users.decorators import backoffice_required, staff_required`

| View | Decorator | Action |
|---|---|---|
| `home` | `@login_not_required` | Add. Keep the role-based `redirect("web:dashboard")` / `redirect("web:pos_index")` / `redirect("web:pending_approval")` body — that is routing, not authorization. |
| `dashboard` | `@backoffice_required` | Replace `@login_required` |
| `pos_index` | `@staff_required` | Replace `@login_required` |
| `pending_approval` | Keep `@login_required` | Keep the `if has_staff_role: redirect("web:home")` body. This page is for users with no role. |

### 6.11 `apps/users/views.py` — no change

`profile` and `upload_profile_image` stay `@login_required`. They are self-service, not role-gated.

---

## 7. Implementation Order

Do the work in this order. Do not skip or reorder.

**Step 1 — Create the decorator module**

Create `apps/users/decorators.py` exactly as in section 3.1. Run `make ruff` and `make test` — nothing should break yet.

**Step 2 — Normalize already-gated views**

Edit `apps/accounting/views.py`, `apps/accounting/payables_views.py`, `apps/reports/views.py`, `apps/settings/views.py`, `apps/orders/views.py`. Replace inline checks with decorators as listed in sections 6.7–6.9. Run `make test` — these views already returned `403`, so tests should stay green.

**Step 3 — Gate the open surface**

Edit `apps/inventory/views.py`, `apps/menu/views.py`, `apps/payments/views.py`, `apps/staff/views.py`, `apps/orders/views_pos.py`, `apps/web/views.py` as listed in sections 6.1–6.6 and 6.10. This is the privilege fix. Run `make test` — cashier and anonymous tests should now get `403` instead of `302` or `200`.

**Step 4 — Delete the middleware**

Edit `apps/web/middleware.py` and `restpos/settings.py` as in section 4. Add `@login_not_required` to `apps/web/views.py:home`. Run `make test` again.

**Step 5 — Simplify the role source**

Edit `apps/users/models.py` and `apps/users/signals.py` as in section 5. Run `make test`. Also delete the `print(pk)` debug loop in `apps/settings/views.py`.

**Step 6 — Fix tests**

- `apps/web/tests/test_auth_flow.py` — change every `assertRedirects(response, reverse("web:dashboard"))` that tested middleware `302` into `assertEqual(response.status_code, 403)` for cashier hitting `/backoffice/dashboard/`. Change `assertRedirects(response, reverse("web:pending_approval"))` for no-role hitting `/pos/` into `assertEqual(response.status_code, 403)`.
- `apps/users/tests/test_role_perf.py` — change `test_pos_page_issues_at_most_one_group_query` and `test_backoffice_redirect_for_cashier_issues_at_most_one_group_query` to assert `403` with bounded `auth_group` queries. The perf assertion stays but the expected status changes.

**Step 7 — Add `403.html`**

Ensure `templates/403.html` exists. Django renders it on `PermissionDenied` when `DEBUG=False`. Without it, users see the default plain 403 page.

---

## 8. Post-Implementation Verification

After all steps, the implementer must run these checks before marking the task done. If any check fails, the implementation is incomplete.

**8.1 No view relies on middleware**

Run:

```
grep -rn "path.startswith" --include="*.py" apps/
grep -rn "BackofficeAccessMiddleware" --include="*.py" apps/ restpos/
grep -rn "prefetch_related_objects" --include="*.py" apps/
```

All three must return zero results.

**8.2 Every backoffice and POS view has an explicit role decorator**

Run:

```
grep -rn "@login_required" --include="*.py" apps/
```

The only allowed hits are `apps/users/views.py` (`profile`, `upload_profile_image`) and `apps/web/views.py:pending_approval`. Every other hit must be `@backoffice_required`, `@manager_required`, `@staff_required`, or `@admin_required`. If any `@login_required` remains in `apps/inventory`, `apps/menu`, `apps/payments`, `apps/staff`, `apps/orders`, `apps/accounting`, or `apps/reports`, the file was missed.

Run:

```
grep -rn "is_manager or is_admin" --include="*.py" apps/
grep -rn "has_backoffice_access" --include="*.py" apps/
```

The only hits should be inside `apps/users/decorators.py` and `apps/users/models.py`. No inline `if not (is_manager or ...)` should remain in any `views.py`.

**8.3 Anonymous and wrong-role users get correct status**

- Anonymous hitting any `/backoffice/*` or `/pos/*` → `302` to `settings.LOGIN_URL` (because of `LoginRequiredMiddleware` / `login_required` inside the decorator).
- Authenticated cashier hitting `/backoffice/dashboard/` → `403`.
- Authenticated user with no role hitting `/pos/` → `403`.
- Manager hitting `/backoffice/dashboard/` → `200`.

Verify by running `make test` and by manually hitting those URLs with the test users.

**8.4 No debug code**

Run:

```
grep -rn "print(" --include="*.py" apps/
```

Must return zero results.

**8.5 Docs**

Update in the same task:

- `docs/workflows/auth.md` — replace the "Route Gates — BackofficeAccessMiddleware" section with "Per-view decorators — `apps/users/decorators.py`" and the table of which decorator covers which surface.
- `docs/workflows/backoffice.md` — change the Access Model paragraph from "Most backoffice views add only `@login_required`; the middleware supplies the route gate" to the decorator table.
- `docs/architecture/side-effects.md` — remove the `BackofficeAccessMiddleware` row from the Request and Middleware Effects table. Add `LoginRequiredMiddleware` if kept.

---

## 9. Files Changed Summary

| File | Action |
|---|---|
| `apps/users/decorators.py` | **Create** |
| `apps/web/middleware.py` | **Modify** — delete `BackofficeAccessMiddleware`, keep `MessagesMiddleware` |
| `restpos/settings.py` | **Modify** — remove `BackofficeAccessMiddleware` from `MIDDLEWARE`, add `LoginRequiredMiddleware` |
| `apps/users/models.py` | **Modify** — `@cached_property` → `@property`, delete `_restpos_group_names` cache |
| `apps/users/signals.py` | **Modify** — delete `clear_role_caches_on_group_change` and `_ROLE_CACHE_ATTRS` |
| `apps/settings/views.py` | **Modify** — decorators + delete `print(pk)` loop |
| `apps/inventory/views.py` | **Modify** — 33 views → `@backoffice_required` |
| `apps/menu/views.py` | **Modify** — 18 views → `@backoffice_required` |
| `apps/payments/views.py` | **Modify** — 9 views → `@backoffice_required` / `@manager_required` |
| `apps/staff/views.py` | **Modify** — 9 views → `@staff_required` |
| `apps/orders/views.py` | **Modify** — 11 views → `@backoffice_required` / `@manager_required` |
| `apps/orders/views_pos.py` | **Modify** — 15 views → `@staff_required` |
| `apps/web/views.py` | **Modify** — `@login_not_required` on `home`, `@backoffice_required` on `dashboard`, `@staff_required` on `pos_index` |
| `apps/accounting/views.py` | **Modify** — 22 views → `@manager_required` |
| `apps/accounting/payables_views.py` | **Modify** — 13 views → `@manager_required` |
| `apps/reports/views.py` | **Modify** — 13 views → `@manager_required` |
| `apps/web/tests/test_auth_flow.py` | **Modify** — 302 → 403 assertions |
| `apps/users/tests/test_role_perf.py` | **Modify** — status + query assertions |
| `templates/403.html` | **Create** if missing |
| `docs/workflows/auth.md` | **Modify** |
| `docs/workflows/backoffice.md` | **Modify** |
| `docs/architecture/side-effects.md` | **Modify** |

Total: 1 new Python file, 1 new template, 15 Python files modified, 2 test files modified, 3 docs modified.

---

## 10. References

- Django 6.0 `topics/auth/default` — `login_required`, `user_passes_test`, `permission_required`, `LoginRequiredMiddleware`, `login_not_required`, `UserPassesTestMixin`, `PermissionRequiredMixin`.
- Django 6.0 `releases/6.0` — no auth/permission breaking changes; PBKDF2 iteration increase only.
- RestPOS code — `apps/users/models.py:46-68`, `apps/web/middleware.py:8-24`, `apps/users/signals.py:20-26`, `apps/settings/views.py:70`, `apps/reports/views.py:35`, `apps/orders/views.py:148`, `apps/inventory/views.py`, `apps/menu/views.py`, `restpos/settings.py:60-73`, `restpos/urls.py`.
