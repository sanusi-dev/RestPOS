# RestPOS — Agent Guidelines

## Project Overview

RestPOS is a restaurant POS and management system for a Nigerian restaurant, built with Django + HTMX.

**Client context:**
- Three thermal printers: cashier receipt, kitchen ticket, bar ticket
- Bar is a separate business entity sharing the same cashier — sales tracked separately per department (food vs drinks)

**Build philosophy:**
- Carbon copy of how ERPNext and URY implement each feature, ported to Django
- Do not invent architecture — always check the reference codebase first
- Deviations from reference must be justified and documented in `PLAN.md`

**Never agree with the user's claims based on confidence alone.** Verify against `references/erpnext-develop/`, `references/ury-develop/`, `FEATURES.md`, `PLAN.md`, and ERPNext/URY accounting logic. Push back when mistaken — even if the user says you previously agreed. If the user explicitly says "I know this isn't best practice but I want it anyway", respect the decision, proceed, and document the deviation in `PLAN.md §6.x Deviations from reference`.

## Tech Stack

| Layer | Technology |
|---|---|
| Backend | Django (latest stable), Python 3.14 |
| Frontend | Django templates + HTMX + Tailwind CSS v4 + Alpine.js + SweetAlerts |
| Database | PostgreSQL |
| Package manager | uv (pyproject.toml) — never use bare `pip install` |
| JS build | Vite + django-vite (sources in `/assets/`, loaded via `{% vite_asset %}`) |
| Task queue | Celery + Redis (periodic background tasks) |
| Cache / broker | Redis |
| Thermal printing | Local Python print agent (ESC/POS over LAN) |
| Auth | django-allauth |

The system runs on the local network only. Django runs on the cashier desktop. All operations work on the local network — no internet required. Owner accesses back office from any device on the same WiFi.

**Explicitly NOT used:** Django REST Framework, Vue, React, Socket.io, QZ Tray, DaisyUI. Do not introduce any of these.

## Workspace Structure

```text
RestPOS/
├── AGENTS.md                         ← this file
├── PLAN.md                           ← feature implementation plans
├── FEATURES.md                       ← feature spec from URY/ERPNext
├── references/                       ← READ ONLY — never modify
│   ├── erpnext-develop/              ← ERPNext source (main branch)
│   └── ury-develop/                  ← URY source (main branch)
├── .venv/                            ← virtual environment
├── pyproject.toml                    ← dependencies (uv)
├── manage.py
└── restpos/
    ├── apps/
    │   ├── menu/           ← menu items, categories, courses, pricing
    │   ├── orders/         ← orders, order items, customer cards, KOT dispatch
    │   ├── payments/       ← payment entries, modes, shift closing
    │   ├── inventory/      ← stock ledger, ingredients, movements
    │   ├── printing/       ← print agent client, ticket formatting, config
    │   ├── reports/        ← daily P&L, sales reports, department split
    │   ├── staff/          ← users, roles, shifts, cashier sessions
    │   └── settings/      ← restaurant settings (singleton), production units, printer config
    └── templates/
        ├── pos/            ← cashier-facing POS screen
        └── backoffice/     ← manager/owner back office
```

Each app maps to a URY module. When creating a new app, check for a corresponding URY doctype folder first.

## Commands

A `Makefile` centralises commands. Run `make` to list them.

| Task | Command |
|---|---|
| First-time setup | `make init` |
| Start app (foreground) | `make dev` |
| Start background services | `make start-bg` (or `make start` for foreground) |
| Stop services | `make stop` |
| Django shell | `make shell` |
| Postgres shell | `make dbshell` |
| Run management command | `make manage ARGS='command'` |
| Create migrations | `make migrations` |
| Apply migrations | `make migrate` |
| Run all tests | `make test` |
| Run specific test | `make test ARGS='apps.module.tests.test_file'` |
| Format code | `make ruff-format` |
| Lint + autofix | `make ruff-lint` |
| Both | `make ruff` |
| Add package | `make uv add '<package>'` |
| Run Python cmd | `make uv run '<command> <args>'` |
| Install npm packages | `make npm-install` (or `make npm-install package-name`) |
| Uninstall npm package | `make npm-uninstall package-name` |
| Vite dev server | `make npm-dev` (auto-runs with `make dev`) |
| Build for prod | `make npm-build` |
| TypeScript check | `make npm-type-check` |
| New Django app | `make uv run 'pegasus startapp <app_name> [<Model1> <Model2Name>]'` |

App runs at http://localhost:8000

**Vite dev vs build:** while the Vite dev server (`make npm-dev`) is running, it serves assets directly with HMR — no `make npm-build` needed. Only run `make npm-build` when serving without the dev server (django-vite falls back to the built manifest in `static/`), e.g. after a fresh deploy/restart.

**Important:** Never run `npm build` as part of normal development while the Vite dev server is running. Use the dev server's HMR assets; build only for production or when Django must serve compiled assets without Vite.

## Reference Codebase Navigation

`references/` is READ ONLY: never write, edit, create, delete, or import from it. Use it only to read and port logic into Django. Always check the reference before implementing any feature.

**Step 1 — Find the ERPNext doctype:**
- `references/erpnext-develop/erpnext/accounts/doctype/` — financial documents
- `references/erpnext-develop/erpnext/stock/doctype/` — inventory
- `references/erpnext-develop/erpnext/selling/doctype/` — sales

Read the `.json` (the `fields` array is the data model) and the `.py` (business logic: `validate`, `before_insert`, `on_submit`).

**Step 2 — Find the URY adaptation:**
- `references/ury-develop/ury/ury/doctype/` — URY custom doctypes
- `references/ury-develop/ury/ury_pos/api.py` — POS API (read fully before any POS endpoint)
- `references/ury-develop/ury/ury/hooks/` — document event handlers
- `references/ury-develop/pos/src/` — React POS frontend (UI logic reference)
- `references/ury-develop/URYMosaic/src/` — Vue kitchen display (reference only)

**Step 3 — Port to Django:** Translate doctype fields to a Django model. Apply URY restaurant logic as model methods or signals. Document deviations.

### Key Reference Files (read first)

| File | Why |
|---|---|
| `references/ury-develop/ury/ury_pos/api.py` | Complete POS API — every endpoint the frontend needs |
| `references/erpnext-develop/erpnext/stock/doctype/stock_ledger_entry/stock_ledger_entry.json` | Core inventory model |
| `references/erpnext-develop/erpnext/accounts/doctype/pos_invoice/pos_invoice.json` | Order/invoice model |
| `references/erpnext-develop/erpnext/accounts/doctype/payment_entry/payment_entry.json` | Payment model |
| `references/ury-develop/ury/ury/doctype/ury_order/ury_order.json` | URY order model |
| `references/ury-develop/ury/ury/doctype/ury_kot/ury_kot.json` | Kitchen ticket model |
| `references/ury-develop/ury/ury/doctype/ury_printer_settings/ury_printer_settings.json` | Printer config model |
| `references/ury-develop/ury/ury/hooks/ury_pos_invoice.py` | Order event logic |

## PLAN.md and FEATURES.md Protocol

`FEATURES.md` — feature spec from URY/ERPNext, by backend and frontend (UI/UX).
`PLAN.md` — implementation plan per feature.

Before implementing:
1. Confirm the feature is in `FEATURES.md`.
2. Read the plan in `PLAN.md`.
3. Read the reference files the plan lists.
4. Implement exactly as the plan describes.
5. If the plan is missing or incomplete, stop and flag it — do not guess.

When writing a `PLAN.md` entry for a new feature, include: ERPNext reference file(s) consulted, URY reference file(s) consulted, Django model fields (translated from doctype JSON), business logic rules (translated from doctype Python), HTMX frontend behaviour, and any deviations with reasons.

Keep `PLAN.md` synchronized in the same task whenever a change affects:

- Feature scope, including in-scope, deferred, or out-of-scope decisions
- Phase status, completion evidence, dependencies, or the next planned phase
- Application architecture, cross-app dependencies, or implementation decisions
- Deviations from the ERPNext or URY reference behavior
- The planned next action or assumptions recorded in a detailed phase plan

Do not update `PLAN.md` for every minor code edit when none of these planning details change. The `/docs` documentation rules below still apply whenever the implemented behavior changes.

## Documentation Maintenance

The documentation in `/docs` is a living representation of the current architecture and behavior of the project.

Before changing complex business logic, consult the relevant documentation in `/docs`. The main entry point is `docs/README.md`.

Whenever a code change affects any of the following, update the relevant documentation in the same task:

- Application architecture or cross-app dependencies
- Database models, relationships, constraints, or queries
- Business logic or side effects
- State transitions
- POS workflows, order lifecycle, inventory, payments, or shifts
- Receipt/printing behavior
- Authentication or authorization
- Signals, middleware, or other hidden execution
- HTMX/frontend/backend interactions
- Important execution flows

Update existing documentation instead of creating duplicate pages. Do not regenerate unrelated documentation. If a workflow changes, update its execution-flow page. If a model or relationship changes, update the data-model page. If an app dependency changes, update the dependency page. If a state transition changes, update the state-machine page. If functionality is removed, update or remove obsolete documentation.

Documentation must describe the current implementation, not the intended implementation. Do not silently guess behavior. If the implementation remains genuinely unclear after tracing callers, callees, templates, URLs, models, signals, and configuration, mark the page with `⚠️ Requires verification` and explain the uncertainty.

The documentation index in `docs/README.md` must remain accurate. Add new documentation to the index and do not leave orphan pages.

## Architecture Decisions

### Printing

Three Xprinter thermal printers on the local network, each with a static IP:
- Cashier printer — customer receipt (USB to desktop)
- Kitchen printer — food order ticket, replaces URY's KOT display (LAN)
- Bar printer — drinks order ticket (LAN)

A lightweight Python print agent runs as a background service on the cashier desktop. After an order is saved, Django sends a print job payload to the agent via HTTP on localhost. The agent formats ESC/POS commands and sends them to the correct printer IP. LAN printers are identified by static IP — not hostname or DHCP address.

### Customer card / group ordering

Group ordering is first-class. The cashier raises the guest count with the **Guests stepper** in the cart header (always visible) — flipping the cart between flat (single) and grouped (split) presentation at any time. In grouped view the cart renders one **customer group** per customer (Customer 1, Customer 2, …): a tappable header (tap to make it the active guest) listing that guest's items with a per-guest subtotal, then the order grand total once at the bottom. Menu taps always add to the active guest.

**Data model:**
- `Order.guest_count` (Integer, default 1)
- `OrderItem.customer_index` (Integer, 1-based, default 1) — replaces any "seat tag" concept
- When `guest_count` is 1, `customer_index` is always 1 and the grouped UI is hidden

**Backend is one order, one total.** The split is presentation-only: the order settles as one document with one grand total and one payment event. `customer_index` is retained for per-customer analytics and ticket/receipt grouping. Items are never shared between customers — each line belongs to exactly one guest.

**Guests stepper guard:** Lowering the guest count below a guest who still has items is blocked (`Order.change_guest_count` raises; the cart shows an error banner "Remove Customer N's items first"). Raising is always allowed. This keeps per-customer analytics honest — no silent re-tagging of who ordered what.

**Receipts:** One receipt per order, grouping items by customer card with a per-customer subtotal, then the overall total:

```text
ORDER #0042
-----------------------------
Customer 1
  Jollof Rice       x1   1,500
  Chicken           x2   2,000
  Subtotal               3,500

Customer 2
  Fried Rice        x1   1,500
  Coke              x1     500
  Subtotal               2,000
-----------------------------
TOTAL                    5,500
```

**Kitchen and bar tickets** also group by `customer_index` so the kitchen knows which items plate together.

**Implementation notes:**
- The grouped UI is HTMX-driven: tapping a guest header sets the active card in the session (`pos_customer_card_activate`); subsequent item additions carry that index. The guest stepper posts `guest_delta` to `pos_order_update_meta`.
- Never use the word "seat" in the UI — use "Customer 1", "Customer 2", etc.
- Cards/groupings are ephemeral presentation; only `customer_index` on each `OrderItem` is persisted.

### Departmental split

Every menu item belongs to `FOOD` or `DRINKS`. A single order can contain both. On checkout, the order total is split by department and recorded separately. Daily reports show food and drinks revenue independently — supports the bar accounting separation.

### Document submit/cancel pattern

Replicate ERPNext's immutable financial workflow in Django:
- Orders, payments, and stock ledger entries have a `status` field with choices `DRAFT`, `SUBMITTED`, `CANCELLED`.
- Once submitted, records are never updated — only cancelled, which creates a reversal entry.
- This gives an immutable audit trail.
- Implement as: `status = models.CharField(choices=[DRAFT, SUBMITTED, CANCELLED])`

### Single-location settings

The app is designed for one restaurant, one location, one settings surface. The
`Restaurant` model is a singleton — one row ever, accessed via `Restaurant.load()`.
There is no `Branch` or `POSProfile` model; all terminal config (identity, active
menu, default warehouse, order-number behaviour) lives on `Restaurant`. Multi-branch
is deferred as separate paid work and is not half-supported now. Payment methods are
managed via `ModeOfPayment.enabled` + `is_default` (exactly one default);
`POSProfilePayment` no longer exists.

### Icons

Icons come from `django-hugeicons-stroke` (pure Python, inline SVG — no npm
package, no node_modules, nothing to add to Vite or static files). It is already
installed and registered as a template builtin, so the tag works in every
template without `{% load %}`:

```
{% hgi_stroke name="home-01" size="24" color="currentColor" stroke_width="2" %}
```

- Icon names are kebab-case, same naming as hugeicons.com (e.g. `home-01`, `search-01`, `notification-03`).
- Available params: `name` (required), `size` (px, default 24), `color` (HEX or CSS color, default `#000000`), `stroke_width` (default 2).
- There is **no `class` param** — for Tailwind sizing wrap the tag in a sized container, and use `color="currentColor"` so the icon inherits the text color.
- Never copy SVG markup into templates manually; never introduce a different icon library without flagging it first.

## Coding Preferences

- Only make changes that are requested or confidently understood as related to the request.
- When fixing an issue, exhaust the existing implementation before introducing a new pattern/technology. If you do introduce new, remove the old so there's no duplicate logic.
- Avoid scripts in files if the script is likely only run once.
- Avoid files over 200-300 lines — refactor at that point.
- Never add mock data to functions. Mocks only in tests or test-only utilities.
- Never overwrite `.env` without first asking and confirming.

When a decision requires user input, use the interactive `question` tool — never assume preferences, design choices, or scope. Present clickable choices with clear labels and descriptions.

## Python

- PEP 8 with 120 char line limit. Double quotes (ruff enforced). isort via ruff.
- Type hints in new code where not burdensome — not enforced on existing code.
- Python 3.14: **unparenthesized `except` with multiple exception types is valid** (PEP 758). `except ValueError, TypeError:` is equivalent to `except (ValueError, TypeError):` — not Python 2, not a `SyntaxError`. Parentheses still required with `as`: `except (ValueError, TypeError) as e:`. Do not "fix" unparenthesized forms unless adding `as`.
- Use Django ORM exclusively. Use `select_related`/`prefetch_related` to avoid N+1.
- Use function-based views by default.
- Use Django signals sparingly; document them well.
- Validate user input server-side. Handle errors explicitly, never silently.
- All models extend `apps.utils.models.BaseModel` (adds `created_at`, `updated_at`).
- The user model is `apps.users.models.CustomUser` — import directly.

## Django Templates (HTML)

- Two-space indent. Standard Django template syntax.
- Multi-line comments: `{% comment %}...{% endcomment %}`. `{# ... #}` is single-line only — never span multiple lines.
- Vite-built JS/CSS: `{% load django_vite %}` then `{% vite_asset %}`. React HMR needs `{% vite_react_refresh %}`.
- Non-vite images/JS/CSS: `{% static %}`.
- Page-level JS via Alpine.js; avoid inline `<script>` tags.
- Django 6.0 template partials: `{% partialdef %}`/`{% partial %}` inline in the template where used — keeps related markup together. Define partials inline, not in scattered files.
- `{% include %}` only for fragments genuinely shared across 3+ unrelated templates — put in `components/`. This is the exception, not the default.
- HTMX responses: use partials with `inline` or direct partial access — one template file serves both the full page and the HTMX fragment. No separate `_partial.html` per endpoint.
- Tailwind v4 utility classes only. **No DaisyUI in new RestPOS code** (it exists in Pegasus boilerplate but must not be used in POS or back-office templates). No inline `style=""` attributes.

## JavaScript

- ES6+ syntax. Two-space indent in JS/JSX/HTML. Single quotes. Semicolons. camelCase vars/funcs, PascalCase components. Explicit TS annotations.
- HTMX: follow progressive enhancement. Return minimal HTML fragments from server, never full pages.
- Alpine.js for client-side interactivity without server interaction.
- Avoid inline `<script>` tags where possible.
- Validate input client and server side. Handle errors explicitly in promise chains and async functions.
- Built with Vite, served via django-vite.

## Migrations

Never hand-write schema migrations. Workflow:
1. Write/modify models.
2. Run `uv run manage.py makemigrations`.
3. Review the generated file — check dependencies and destructive ops (field removal, NOT NULL with no default, renames that look like delete+add).
4. Run `uv run manage.py migrate`.

Hand-write only for: data migrations (`RunPython` with explicit forwards/backwards), raw SQL (`RunSQL` for DB-level indexes/constraints/triggers Django can't express), multi-step destructive changes (split into separate migrations to prevent data loss), and `SeparateDatabaseAndState`.

Hard rules: do NOT hand-write `CreateModel`/`AddField`/`AlterField`/`RemoveField`. Do NOT skip `makemigrations`. If a data migration accompanies a schema change, put it in a separate migration file after the schema migration.

## Documentation & Commit Standards

**Core rule:** Code explains HOW. Comments explain WHY. Docs state WHAT. Nothing else belongs.

**Inline comments:** Only for non-obvious logic (algorithms, workarounds, intentional quirks). Never restate what code says. Never explain framework behaviour. One line max — if you need two, refactor the code.

```text
BAD:  # Loop through all payments and add them to the list
GOOD: # Cash modes first — cashier scans left-to-right at speed

BAD:  # Django requires the form to call super().__init__() before field customisation
GOOD: (no comment — standard Django pattern)
```

**Docstrings:** Module: one line on what it contains. Class: one line on what it represents (omit if self-explanatory). Function: one line on what it returns/does, add a second line only for non-obvious params/returns. Never document WHY a business rule exists, HOW an external system works, or WHERE the decision is recorded (that's PLAN.md or git history). Never reference external systems, line numbers, or docs URLs.

**Commits:** `<type>: <what changed> [<scope> if non-obvious]`. Types: feat, fix, refactor, style, chore, docs. Subject 50 chars max, imperative mood, no full stop. No body unless future-you needs to understand a non-obvious decision. Never describe file changes (the diff shows that). Never restate framework mechanics.

**Smell test:** Before writing any comment/docstring/commit, ask "Would a competent Django developer need this to understand or use the code?" If no → delete. If yes → one line.

## Hard Rules — Never Do

- Modify anything inside `references/`
- Use `pip install` instead of `uv add`
- Import from `references/` into the Django project
- Use Django REST Framework, Vue, React, or Socket.io
- Use DaisyUI — Tailwind CSS only
- Use `FloatField` for money
- Use `CASCADE` delete on orders, payments, or stock ledger entries
- Invent a data model without first checking the ERPNext reference doctype
- Implement a POS API endpoint without first reading `ury_pos/api.py`
- Write more than one feature at a time — complete and confirm one before the next
- Run Playwright or browser-based tests only when the user explicitly requests them

## Skills

Load the relevant skill at the start of matching tasks (see `available_skills` in the system prompt):

- Django form or validation logic → `django-forms` (use `{% partialdef %}` not separate `_form.html` files)
- Django view, model, or ORM query → `django-patterns` (ignore its DRF/REST sections — the project is HTMX only)
- Any HTMX interaction → `htmx` (its `/api/` URL examples don't apply — RestPOS uses Django view URLs)
- Any UI component, page, or interface → `frontend-design` (Tailwind only, no DaisyUI)
- Auth, permissions, or security review → `django-security` (its HTTPS/SSL settings don't apply — the project runs on the local network)
- mypy type errors → `fix-types`
- Dependency upgrades → `upgrade-python-deps` or `upgrade-js-deps`

Project skill constraints override conflicting skill content. Activate all relevant skills together.
