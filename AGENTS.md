# Codebase Guidelines

## Architecture

- This is a Django project built on Python 3.14.
- User authentication uses `django-allauth`.
- The front end is mostly standard Django views and templates.
- HTMX and Alpine.js are used to provide single-page-app user experience with Django templates.
  HTMX is used for interactions which require accessing the backend, and Alpine.js is used for
  browser-only interactions.
- JavaScript files are kept in the `/assets/` folder and built by vite.
  JavaScript code is typically loaded via the static files framework inside Django templates using `django-vite`.
- The frontend communicates with the backend via HTMX requests to Django views — no separate API layer in Phase 1.
- The front end uses Tailwind (Version 4), Alpine.js for client-side interactivity, and SweetAlerts for toasts and pop-up dialogs.
- The main database is Postgres.
- Celery is used for background jobs and scheduled tasks.
- Redis is used as the default cache, and the message broker for Celery (if enabled).

## Commands you can run

The following commands can be used for various tools and workflows.
A `Makefile` is provided to help centralize commands:

```bash
make  # List available commands
```

### First-time Setup

```bash
make init
```

### Starting the Application

Start background services:

```bash
make start     # Run in foreground with logs
make start-bg  # Run in background
```

Start the app:

```bash
make dev       # Run in foreground with logs
```

Access the app at http://localhost:8000

### Stopping Services

Stop background services:

```bash
make stop
```

## Common Commands

### Development

```bash
make shell            # Open Python / Django shell
make dbshell          # Open PostgreSQL shell
make manage ARGS='command'  # Run any Django management command
```

### Database

```bash
make migrations       # Create new migrations
make migrate          # Apply migrations
```

### Testing

```bash
make test                              # Run all tests
make test ARGS='apps.module.tests.test_file'  # Run specific test
make test ARGS='path.to.test --keepdb'        # Run with options
```

### Python Code Quality

```bash
make ruff-format      # Format code
make ruff-lint        # Lint and auto-fix
make ruff             # Run both format and lint
```
### Python

```bash
make uv add '<package>'         # Add a new package
make uv run '<command> <args>'  # Run a Python command
```

### Frontend

```bash
make npm-install      # Install npm packages
make npm-install package-name  # Install specific package
make npm-uninstall package-name  # Uninstall package
make npm-dev          # Run the Vite development server
make npm-build        # Build for production
make npm-type-check   # Run TypeScript type checking
```

Note: Vite runs automatically with hot-reload when using `make dev`.

### Code generation

```bash
make uv run 'pegasus startapp <app_name> <Model1> <Model2Name>'  # Start a new Django app (models are optional)
```

## General Coding Preferences

- Always prefer simple solutions.
- Avoid duplication of code whenever possible, which means checking for other areas of the codebase that might already have similar code and functionality.
- You are careful to only make changes that are requested or you are confident are well understood and related to the change being requested.
- When fixing an issue or bug, do not introduce a new pattern or technology without first exhausting all options for the existing implementation. And if you finally do this, make sure to remove the old implementation afterwards so we don’t have duplicate logic.
- Keep the codebase clean and organized.
- Avoid writing scripts in files if possible, especially if the script is likely only to be run once.
- Try to avoid having files over 200-300 lines of code. Refactor at that point.
- Don't ever add mock data to functions. Only add mocks to tests or utilities that are only used by tests.
- Always think about what other areas of code might be affected by any changes made.
- Never overwrite my .env file without first asking and confirming.
- Keep responses concise and to the point, unless the user asks otherwise.

## PLANNING MODE

- Always ask clarifying questions.
- Never assume design, tech stack, or features.
- Use deep-dive sub-agents to assist with research.
- Use deep-dive sub-agents to review the different aspects of your plan before presenting it to the user.

## CHANGE / EDIT MODE

- Never implement features yourself if possible — use sub-agents.
- Identify changes from the plan.
- Sub-agents to implement features that can be implemented in parallel, using sub-agents efficiently.
- Use the best model for the task.

## Python Code Guidelines

### Code Style

- Follow PEP 8 with 120 character line limit.
- Use double quotes for Python strings (ruff enforced).
- Sort imports with isort (via ruff).
- Try to use type hints in new code. However, strict type-checking is not enforced and you can leave them out if it's burdensome.
  There is no need to add type hints to existing code if it does not already use them.

### Python 3.14 syntax notes

- **Unparenthesized `except` with multiple exception types is valid** (PEP 758, Python 3.14+).
  `except ValueError, TypeError:` is equivalent to `except (ValueError, TypeError):` — it is **not**
  Python 2 syntax and will **not** raise a `SyntaxError`. Parentheses are still required when using
  `as` (e.g. `except (ValueError, TypeError) as e:`). Do not "fix" unparenthesized forms unless an
  `as` clause is being added.

### Preferred Practices

- Use Django signals sparingly and document them well.
- Always use the Django ORM if possible. Use best practices like lazily evaluating querysets
  and selecting or prefetching related objects when necessary.
- Use function-based views by default.
- Always validate user input server-side.
- Handle errors explicitly, avoid silent failures.

#### Django models

- All Django models should extend `apps.utils.models.BaseModel` (which adds `created_at` and `updated_at` fields).
- The project's user model is `apps.users.models.CustomUser` and should be imported directly.

## Django Template Coding Guidelines for HTML files

- Indent templates with two spaces.
- Use standard Django template syntax.
- For multi-line comments, use `{% comment %}...{% endcomment %}`. The `{# ... #}` syntax is single-line only and does NOT work across multiple lines — never write `{# first line\n   second line #}`.
- JavaScript and CSS files built with vite should be included with the `{% vite_asset %}` template tag provided by `django-vite` (must have `{% load django_vite %}` at the top of the template)
- Any react components also need `{% vite_react_refresh %}` for Vite + React's HMR functionality, from the same `django_vite` template library)
- Use the Django `{% static %}` tag for loading images and external JavaScript / CSS files not managed by vite.
- Prefer using alpine.js for page-level JavaScript, and avoid inline `<script>` tags where possible.
- Use Django 6.0 template partials (`{% partialdef %}` / `{% partial %}`) for reusable
  template fragments. Define partials inline in the template where they're used — this keeps
  related markup together and avoids scattering fragments across files.
- Only use `{% include %}` when a fragment is genuinely shared across multiple unrelated
  templates (e.g. a form widget used in 3+ different pages). In that case, put the shared
  fragment in a `components/` folder. This should be the exception, not the default.
- For HTMX responses, use template partials with the `inline` option or direct partial access —
  one template file serves both the full page render and the HTMX fragment response. This
  avoids the need for separate `_partial.html` files for every HTMX endpoint.
- Use TailwindCSS utility classes for all styling. Do not use DaisyUI in new RestPOS code.
  (DaisyUI exists in the Pegasus boilerplate templates but must not be used in POS or
  back-office templates.)

## JavaScript Code Guidelines

### Code Style

- Use ES6+ syntax for JavaScript code.
- Use 2 spaces for indentation in JavaScript, JSX, and HTML files.
- Use single quotes for JavaScript strings.
- End statements with semicolons.
- Use camelCase for variable and function names.
- Use PascalCase for component names (React).
- Use explicit type annotations in TypeScript files.
- Use ES6 import/export syntax for module management.

### Preferred Practices
- When using HTMX, follow progressive enhancement patterns.
- Use Alpine.js for client-side interactivity that doesn't require server interaction.
- Avoid inline `<script>` tags wherever posisble.
- Validate user input on both client and server side.
- Handle errors explicitly in promise chains and async functions.

### Build System

- Code is bundled using vite and served with `django-vite`.

---

## RestPOS Project Overview

**RestPOS** is a custom restaurant POS and management system built for a Nigerian restaurant. It is a Django + HTMX web application.

**Client context:**
- Three thermal printers: cashier receipt, kitchen ticket, bar ticket
- Bar is a separate business entity sharing the same cashier — sales must be tracked separately per department (food vs drinks)

**Build philosophy:**
- Carbon copy of how ERPNext and URY implement each feature, ported to Django
- Do not invent architecture — always look at the reference codebase first
- Deviations from the reference must be explicitly justified in a code comment

---

## Workspace Structure

```
RestPOS/                              ← project root (this folder)
├── AGENTS.md                         ← this file (project + codebase rules)
├── PLAN.md                           ← feature implementation plan
├── FEATURES.md                       ← feature spec extracted from URY/ERPNext
├── references/                       ← READ ONLY — never modify anything here
│   ├── erpnext-develop/              ← ERPNext source (main branch)
│   └── ury-develop/                  ← URY source (main branch)
├── .venv/                            ← virtual environment
├── pyproject.toml                    ← dependencies (managed with uv)
├── manage.py
└── restpos/                          ← Django project folder
```

**CRITICAL — Reference codebase rules:**
- `references/erpnext-develop/` and `references/ury-develop/` are READ ONLY
- Never write, edit, create, or delete any file inside `references/`
- Never import from `references/` into the Django project
- Use reference files ONLY to read, study, and port logic into Django
- Always check the reference codebase before implementing any feature

---

## Tech Stack

| Layer | Technology |
|---|---|
| Backend framework | Django (latest stable) |
| Frontend | Django templates + HTMX + Tailwind CSS + Alpine.js + SweetAlerts |
| Database | PostgreSQL |
| Package manager | uv (pyproject.toml) |
| Python version | 3.14 |
| Task queue | Celery + Redis (for periodic background tasks) |
| Thermal printing | Local Python print agent (ESC/POS over LAN) |
| MCP tools available | Playwright, Brave Search |

**What is explicitly NOT used in Phase 1:**
- Django REST Framework — no JSON API layer in phase 1
- Vue, React, or any JS framework — HTMX only
- Socket.io — not needed, kitchen uses printer tickets not a display screen
- QZ Tray — replaced by a local Python print agent
- DaisyUI — pure Tailwind CSS only

**Phase 2 stack (future — do not build now):**
The cloud-hosted, offline-capable version will use Django + Django REST
Framework as the API backend and Vue 3 as the frontend. Do not introduce DRF
or Vue into Phase 1 under any circumstances.

---

## Architecture Decisions

### Two-phase build

**Phase 1 (current):** Local network only. Django runs on the cashier desktop.
All operations (ordering, printing, inventory, reports) work entirely on the
local network. No internet required for anything. Owner accesses back office
from any device on the same WiFi network inside the restaurant.

**Phase 2 (future):** Cloud-based with offline-mode functionality

Do not build Phase 2 architecture into Phase 1.

### Printing architecture

Three Xprinter thermal printers (LAN model), each assigned a static IP on
the local network:
- Cashier printer — customer receipt
- Kitchen printer — food order ticket (replaces URY's KOT display)
- Bar printer — drinks order ticket

A lightweight Python print agent runs as a background service on the cashier
desktop. After an order is saved, Django sends a print job payload to the
agent via HTTP on localhost. The agent formats ESC/POS commands and sends them
to the correct printer IP.

The cashier receipt printer connects via USB to the desktop. The kitchen and
bar printers connect via LAN (ethernet) with static IP addresses on the local
network. Each LAN printer is identified by its static IP — not by hostname or
DHCP-assigned address.

### Customer card / group ordering

Group ordering is a first-class feature, not an afterthought. The model is
inspired by Poster POS's guest count approach but more polished by default.

**How it works:**

When placing an order, the cashier is prompted whether the order is for a
single customer or a group. If a group, the cashier specifies the number of
customers. The order screen renders one **customer card** per customer (e.g.
Customer 1, Customer 2, Customer 3). The cashier clicks a card to make it
active, then adds items — every item added goes to the active card. Switching
cards switches whose items are being built.

**Data model:**

- `Order` has a `guest_count` integer field (default 1)
- `OrderItem` has a `customer_index` integer field (1-based, default 1) —
  this replaces the earlier "seat tag" concept entirely
- When `guest_count` is 1, `customer_index` is always 1 and the customer card
  UI is hidden — single customer flow is identical to a standard POS

**Receipt behaviour:**

A single receipt prints for the whole order regardless of group size. The
receipt body groups items by customer card with a subtotal per customer, then
shows the overall total at the bottom. Example:

```
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

**Kitchen and bar ticket behaviour:**

Kitchen and bar tickets also group by customer index so the kitchen knows
which items belong together on the same tray. Items with the same
`customer_index` are plated together.

**Implementation notes:**

- The customer card UI is an HTMX-driven panel on the POS screen — clicking
  a card sends an HTMX request that sets the active card in the session, all
  subsequent item additions carry that card's index
- Do not use the word "seat" anywhere in the UI — use "Customer 1",
  "Customer 2" etc.
- Customer cards are ephemeral to the order — they are not saved as separate
  records, only `customer_index` on each `OrderItem` is persisted

### Departmental split

Every menu item belongs to a department: `FOOD` or `DRINKS`. A single order
can contain both. On checkout, the order total is split by department and
recorded separately. Daily reports show food revenue and drinks revenue
independently. This supports the client's bar accounting separation.

### Document submit/cancel pattern

ERPNext uses an immutable submit/cancel workflow on financial documents.
Replicate this in Django:
- Orders, payments, and stock ledger entries have a `status` field
- Once submitted, records are never updated — only cancelled (which creates
  a reversal entry)
- This gives an immutable audit trail — critical for financial integrity
- Implement as: `status = models.CharField(choices=[DRAFT, SUBMITTED, CANCELLED])`

---

## Reference Codebase Navigation

When implementing any feature, always read the reference in this order:

**Step 1 — Find the ERPNext doctype:**
```
references/erpnext-develop/erpnext/accounts/doctype/    ← financial documents
references/erpnext-develop/erpnext/stock/doctype/       ← inventory
references/erpnext-develop/erpnext/selling/doctype/     ← sales documents
```
Read the `.json` file for the doctype — the `fields` array is the data model.
Read the `.py` file for business logic (validate, before_insert, on_submit etc.)

**Step 2 — Find the URY adaptation:**
```
references/ury-develop/ury/ury/doctype/                 ← URY custom doctypes
references/ury-develop/ury/ury_pos/api.py                ← POS API (722 lines) — read this fully
references/ury-develop/ury/ury/hooks/                   ← document event handlers
references/ury-develop/pos/src/                         ← React POS frontend (for UI logic reference)
references/ury-develop/URYMosaic/src/                   ← Vue kitchen display (reference only)
```

**Step 3 — Port to Django:**
Translate the ERPNext doctype fields to a Django model. Apply URY's
restaurant-specific logic as model methods or Django signals. Document any
deviations.

---

## Key Reference Files (read these first before any implementation)

These are the most important files in the reference codebases:

| File | Why it matters |
|---|---|
| `references/ury-develop/ury/ury_pos/api.py` | Complete POS API — every endpoint your frontend needs |
| `references/erpnext-develop/erpnext/stock/doctype/stock_ledger_entry/stock_ledger_entry.json` | Core inventory model |
| `references/erpnext-develop/erpnext/accounts/doctype/pos_invoice/pos_invoice.json` | Order/invoice model |
| `references/erpnext-develop/erpnext/accounts/doctype/payment_entry/payment_entry.json` | Payment model |
| `references/ury-develop/ury/ury/doctype/ury_order/ury_order.json` | URY order model |
| `references/ury-develop/ury/ury/doctype/ury_kot/ury_kot.json` | Kitchen ticket model |
| `references/ury-develop/ury/ury/doctype/ury_printer_settings/ury_printer_settings.json` | Printer config model |
| `references/ury-develop/ury/ury/hooks/ury_pos_invoice.py` | Order event logic |

---

## Django App Structure

```
RestPOS/
└── restpos/
    ├── apps/
    │   ├── menu/           ← menu items, categories, courses, pricing
    │   ├── orders/         ← orders, order items, customer cards, KOT dispatch
    │   ├── payments/       ← payment entries, payment modes, shift closing
    │   ├── inventory/      ← stock ledger, ingredients, stock movements
    │   ├── printing/       ← print agent client, ticket formatting, printer config
    │   ├── reports/        ← daily P&L, sales reports, department split
    │   ├── staff/          ← users, roles, shifts, cashier sessions
    │   └── settings/       ← restaurant config, branch, room, table setup
    └── templates/
        ├── pos/            ← cashier-facing POS screen templates
        └── backoffice/     ← manager/owner back office templates
```

Each app maps directly to a URY module. When creating a new app, check if
there is a corresponding URY doctype folder first.

---

## PLAN.md and FEATURES.md Protocol

`FEATURES.md` — the extracted feature spec from URY and ERPNext, categorized by backend and frontend(specifically referring to the ui/ux).
`PLAN.md` — the implementation plan for each feature.

Before implementing any feature:
1. Check `FEATURES.md` — confirm the feature is documented
2. Check `PLAN.md` — read the implementation plan for that feature
3. Read the reference files listed in the plan
4. Implement exactly as the plan describes
5. If the plan is missing or incomplete, stop and flag it — do not guess

When writing to `PLAN.md` for a new feature, always include:
- ERPNext reference file(s) consulted
- URY reference file(s) consulted
- Django model fields (translated from doctype JSON)
- Business logic rules (translated from doctype Python)
- HTMX frontend behaviour
- Deviations from reference and why

---

## What Agents Must Never Do

- Modify anything inside `references/`
- Use `pip install` instead of `uv add`
- Import from `references/` into the Django project
- Use Django REST Framework, Vue, React, or Socket.io
- Use DaisyUI — pure Tailwind CSS only
- Use `FloatField` for money
- Use `CASCADE` delete on orders, payments, or stock ledger entries
- Invent a data model without first checking the ERPNext reference doctype
- Implement a POS API endpoint without first reading `ury_pos/api.py`
- Write more than one feature at a time — always complete and confirm
  one feature before moving to the next, except if necessary

---

## Skills

The following skills are installed and available in `.claude/skills/` (project level)
and `~/.agents/skills/` (global level). Always load the relevant skill before implementing
features — they contain battle-tested patterns that prevent common mistakes.

### When to Load Skills

- Building any Django form or validation logic → load `django-forms`
- Building any Django view, model, or ORM query → load `django-patterns`
  (Note: the skill's DRF sections do NOT apply to Phase 1 — HTMX only)
- Implementing any HTMX interaction → load `htmx`
- Building any UI component, page, or interface → load `frontend-design`
- Setting up auth, permissions, or reviewing security → load `django-security`
- Upgrading dependencies → load `upgrade-python-deps` or `upgrade-js-deps`
- Fixing mypy type errors → load `fix-types`

### Project-Level Skills (in `.claude/skills/`)

| Skill | Purpose |
|---|---|
| django-forms | ModelForm patterns, validation, clean methods, HTMX form submission |
| django-patterns | Django architecture, ORM best practices, caching, signals (DRF sections overridden for Phase 1) |
| django-security | Security best practices, auth, CSRF, XSS prevention |
| frontend-design | Distinctive visual design guidance, typography, color theming |
| htmx | HTMX request attributes, swap strategies, triggers, CSRF handling |
| fix-types | Interactive mypy type checking fixes |
| pegasus-projects | Pegasus CLI operations |
| upgrade-pegasus | Pegasus version upgrades |
| resolve-pegasus-conflicts | Pegasus upgrade merge conflict resolution |
| upgrade-python-deps | Python dependency upgrades via uv |
| upgrade-js-deps | JavaScript dependency upgrades via npm |

### Skill Constraints for RestPOS Phase 1

Each project-level skill has a "RestPOS Project Constraints" section at the top
that overrides any conflicting content. Key constraints:

- `django-patterns`: Ignore all DRF/REST API sections — Phase 1 uses HTMX + Django views only
- `django-forms`: Use `{% partialdef %}` (Django 6.0 template partials) instead of separate
  `_form.html` files where possible
- `htmx`: URL examples use `/api/` paths — RestPOS uses Django view URLs, not REST API endpoints
- `django-security`: HTTPS/SSL settings are for Phase 2 — Phase 1 is local network only
- `frontend-design`: All styling is Tailwind CSS only — no DaisyUI in new RestPOS code
