# Architecture

> **Status:** Slice 0 — this document describes the target architecture for the whole
> project. As of Slice 0 no business DocTypes exist yet; this is the design that Slices
> 1–8 will implement incrementally. Each section notes what's actually built today.

## Principle: use Frappe, don't rebuild Frappe

Before adding any custom infrastructure, the standing question is: **does Frappe already
provide this?** Authentication, users, roles/permissions, REST API, file storage,
background jobs, scheduled tasks, CSRF/session security, email, audit fields (`owner`,
`creation`, `modified`, `modified_by`), and document lifecycle hooks are all native
Frappe capabilities. E-menu is built as a set of DocTypes, server-side controllers, and
a thin customer-facing web layer on top — not a parallel framework.

All business logic lives inside `apps/e_menu` (this repository). Frappe core
(`apps/frappe`) is never modified; any customization goes through hooks
(`e_menu/hooks.py`), not patches to framework source.

## Layered request flow

```
Request
   │
   ▼
Authentication (Frappe session / API key — native)
   │
   ▼
Request Context (frappe.session.user, resolved Restaurant Member if applicable)
   │
   ▼
Authorization
   ├─ Platform-level: Frappe Role ("System Manager" = platform admin)
   └─ Restaurant-level: Restaurant Member.role (OWNER/MANAGER/CASHIER/KITCHEN)
   │
   ▼
Feature API (whitelisted methods / REST on DocTypes)
   │
   ▼
Service / controller logic (DocType controllers, e.g. Order.accept())
   │
   ▼
Database (MariaDB, via Frappe ORM)
```

The customer-facing QR/menu/ordering flow (Slices 4–6) bypasses the "Authentication"
step entirely — those requests are unauthenticated by design (Frappe `Guest` role) and
instead get their authorization from a **table QR token**, not a logged-in user. See
[permissions.md](permissions.md) for how that's scoped safely.

## Multi-tenancy model

**`Restaurant` is the tenant boundary — not the Frappe site.** One SaaS Frappe site
serves every restaurant on the platform (see
[development.md](development.md#why-one-frappe-site-for-many-restaurants-not-one-site-per-tenant)
for why site-per-tenant was rejected).

```
User (Frappe)
   │  1..N — a person can be linked to multiple restaurants with different roles
   ▼
Restaurant Member  (user, restaurant, role, status)
   │  N..1
   ▼
Restaurant   ◄── owned by an Owner Subscription (owner, plan, restaurant_limit)
   │
   ├── Menu Category      (restaurant-scoped)
   ├── Menu Item           (restaurant-scoped; category must belong to same restaurant)
   ├── Restaurant Table    (restaurant-scoped; carries the public QR token)
   ├── Order                (restaurant-scoped, table-scoped)
   │     └── Order Item     (snapshots menu item name/price at order time)
   └── Payment              (restaurant-scoped, order-scoped)
```

Every restaurant-owned DocType carries a mandatory `restaurant` Link field. Two
enforcement layers protect the tenant boundary, because **UI-only filtering is not a
security boundary**:

1. **Query-level scoping** — Frappe permission query conditions restrict list views and
   report queries to restaurants the current user is a member of (platform admins are
   exempt).
2. **Write-level validation** — every DocType controller's `validate()` re-checks, on the
   server, that the acting user has an active `Restaurant Member` row for the
   `restaurant` on the document being written (not just that the field is present). A
   request that supplies `restaurant = <restaurant the user doesn't belong to>` is
   rejected, never silently reassigned or trusted.

See [permissions.md](permissions.md) for the full platform-vs-restaurant permission
model.

## Platform permissions vs. restaurant-level authorization

These are deliberately two different, non-overlapping mechanisms:

- **Platform permissions** — ordinary Frappe roles (`System Manager` = platform admin,
  with access to every restaurant for support/config; everyone else effectively has no
  useful platform-wide role). Enforced via standard Frappe DocType permissions.
- **Restaurant-level authorization** — `Restaurant Member.role` (OWNER / MANAGER /
  CASHIER / KITCHEN), scoped to one `(user, restaurant)` pair. A single Frappe user can
  hold different restaurant roles at different restaurants simultaneously. This can't be
  expressed as a single global Frappe Role, so it's enforced with explicit server-side
  checks in controllers/whitelisted methods, backed by permission query conditions for
  list/report scoping.

Frappe v15/v16 custom permission "actions" (e.g. `accept_order`, `manage_staff`) are
available and may be used later for finer-grained UI affordances, but the authoritative
check is always the server-side restaurant-membership-and-role check — never a UI-only
gate.

## Money and totals — *implemented, Slice 6*

All currency fields use Frappe's `Currency` fieldtype, backed by fixed-precision
`decimal(21,9)` database columns (verified, not assumed — see `domain-model.md`) and
`flt()`-rounded arithmetic — not native floating-point comparisons, and not Python's
`decimal.Decimal` either (non-idiomatic here; Frappe's own native mechanism already
satisfies "currency-safe" at the storage layer). Order totals are **always recomputed
server-side** from the authoritative `Menu Item` price at order-submission time, in one
place (`Order.snapshot_and_calculate_items`) — a client-supplied price or total is
never read at all, let alone trusted. See `domain-model.md` → `Order / Order Item` for
the full design.

## Payments

Payment provider integration is provider-neutral by design: a `Payment` DocType records
`provider`, `provider_reference`, `method`, `amount`, `status`, decoupled from `Order`
lifecycle logic. `Order` never talks to a payment gateway directly — a payment provider
plugs in behind the `Payment` boundary. See [domain-model.md](domain-model.md) for the
planned shape; the abstraction is built in Slice 8, manual payment first in Slice 7.

## Customer-facing UI — *implemented, Slice 5*

The customer QR/menu/cart experience is **not** Frappe Desk. It's a single, standalone
Frappe website page: `e_menu/www/menu.py` + `www/menu.html`, mapped from
`/menu/<public_id>/<table_token>` via a `website_route_rules` hook, using the exact same
server-side session-less, token-scoped authorization described above (it calls
`resolve_qr` from Slice 4 directly).

**Decision: server-rendered Jinja page, not a bundled SPA, not Frappe UI.** Evaluated
per the project's "built-in → official integration → small dependency → custom" order:

- A **Frappe website page** (Jinja `www/` template + plain CSS/JS) is Frappe's own
  built-in mechanism for exactly this — an unauthenticated, public, mobile-friendly
  page — and needs no build step beyond what the app already has. `website_route_rules`
  is the documented, idiomatic way to give a `www/` page dynamic URL segments;
  `frappe.get_all` in `get_context()` covers the data fetch; standard Jinja
  autoescaping covers XSS on owner-entered menu text. Nothing about this flow (browse a
  short, mostly-static menu; hold a small cart in memory) needs a client-side router,
  component framework, or reactive state library.
- **Frappe UI** (the Vue component library + Vite-based frontend the Frappe team uses
  for apps like Helpdesk) is real and official, but it's sized for building an entire
  rich application shell — it would add a whole separate `frontend/` build pipeline
  (Node/Vite, its own `package.json`, a dev server proxied through Frappe) for a single
  page with one interaction pattern (tap to add, view a running total). That's the
  "don't add abstractions before the concrete need exists" line: if E-menu later needs
  a genuinely app-like customer experience (saved order history, live order-status
  push, multi-step checkout flows), revisit — that's a real trigger, not a preemptive one.
- A **custom SPA in a separate repository** is explicitly ruled out by the product
  spec ("do NOT create a separate frontend repository unless there is a strong
  reason") and there isn't one here.

**Standalone, not extending the default website theme.** `www/menu.html` does not
`{% extends "templates/web.html" %}` (the pattern most `frappe/www/*.html` files use,
which pulls in the site navbar/footer/Bootstrap theme) — it's a bare `<!DOCTYPE html>`
document with its own `<head>`/mobile-first CSS, the same pattern Frappe core itself
uses for `www/app.html` (the Desk shell) and `www/printview.html`. A restaurant's
customer page shouldn't carry E-menu's own website chrome.

**Cart is a client-side concern for this slice.** Vanilla JS (no framework), state held
in a plain object, persisted to `localStorage` keyed by the table's `qr_token` (so
reloading the same table's page restores the cart, and different tables/restaurants on
the same device never mix carts). There is deliberately no submit action yet — building
the cart is the literal Slice 5 scope per the product spec's flow diagram; "submit
order" is Slice 6, which will add a real endpoint and move cart submission to
server-verified state rather than trusting anything client-side (see "Money and totals"
below — the same rule applies here: nothing the customer's browser computed is ever
trusted for the actual order total).

`get_context()` fails exactly like `resolve_qr` does — one generic "menu unavailable"
page (HTTP 404) for every invalid/deactivated case, never revealing which part failed —
but renders it as a normal, on-brand page rather than a raw API error, since a human
is looking at it.

## Repository boundary

This repository holds only `apps/e_menu` — the custom Frappe app — plus this project's
own docs. It does **not** hold Frappe Framework, a bench, generated assets, `node_modules`,
databases, Redis data, or site secrets. See
[development.md](development.md#setting-up-a-bench-from-scratch) for how to stand up a
throwaway bench that installs this app, and the repository's `.gitignore` for what's
deliberately excluded.
