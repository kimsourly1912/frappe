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

## Money and totals

All currency fields use Frappe's `Currency`/`Float`-with-precision fields backed by
`flt()`/decimal-safe rounding — never native floating point comparisons for money.
Order totals are **always recomputed server-side** from the authoritative `Menu Item`
price at order-submission time; a client-supplied price or total is never trusted (see
`domain-model.md` → `Order Item` for the price-snapshot design once Slice 6 lands).

## Payments

Payment provider integration is provider-neutral by design: a `Payment` DocType records
`provider`, `provider_reference`, `method`, `amount`, `status`, decoupled from `Order`
lifecycle logic. `Order` never talks to a payment gateway directly — a payment provider
plugs in behind the `Payment` boundary. See [domain-model.md](domain-model.md) for the
planned shape; the abstraction is built in Slice 8, manual payment first in Slice 7.

## Customer-facing UI

The customer QR/menu/cart/order experience is **not** Frappe Desk. It's a small,
mobile-first web app served from this app's `www/` (Jinja-rendered pages) or a bundled
JS entry point under `public/`, using the exact same server-side session-less,
token-scoped authorization described above. The concrete mechanism (server-rendered
Jinja vs. a bundled SPA) is decided in Slice 5, once the ordering API shape (Slice 6
depends on it existing first, so Slice 5 builds against a stub) is clearer — this file
will be updated then with the final choice and why.

## Repository boundary

This repository holds only `apps/e_menu` — the custom Frappe app — plus this project's
own docs. It does **not** hold Frappe Framework, a bench, generated assets, `node_modules`,
databases, Redis data, or site secrets. See
[development.md](development.md#setting-up-a-bench-from-scratch) for how to stand up a
throwaway bench that installs this app, and the repository's `.gitignore` for what's
deliberately excluded.
