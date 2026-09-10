# Permissions: platform vs. restaurant-level

> **Status:** Slice 2 — all three layers below are implemented: `System Manager`
> (platform), `Restaurant Owner` (SaaS account-level), and `Restaurant Member` with its
> per-restaurant `OWNER`/`MANAGER`/`CASHIER`/`KITCHEN` roles plus the `Restaurant Staff`
> Frappe Role. Three Frappe Roles now exist (`System Manager`, `Restaurant Owner`,
> `Restaurant Staff`) alongside the *separate* concept of a `Restaurant Member.role`
> value — see the "Don't confuse these" callouts below if you're new to this file.

## Two separate authorization mechanisms

E-menu deliberately keeps two authorization concerns apart, because they answer
different questions and don't share a shape:

| | Platform permissions | Restaurant-level authorization |
|---|---|---|
| Answers | "Can this user administer the platform?" | "What can this user do **at this specific restaurant**?" |
| Mechanism | Native Frappe Role (`System Manager`) | `Restaurant Member.role`, scoped to `(user, restaurant)` |
| Cardinality | One role, global | Many rows — one user can hold different roles at different restaurants |
| Enforced by | Standard Frappe DocType permissions | Explicit server-side checks + permission query conditions |

A single global Frappe Role **cannot** express "MANAGER at Restaurant A, CASHIER at
Restaurant B for the same person" — that's exactly why `Restaurant Member` exists as its
own DocType rather than trying to force restaurant roles into Frappe's role system.

## Platform permissions

- **System Manager** (Frappe's built-in administrative role): platform administrators.
  Can manage `Subscription Plan`, `Owner Subscription`, view/manage all `Restaurant`
  records and their owned data, and handle support/troubleshooting across tenants.
  Enforced with ordinary Frappe DocType permission rules — no custom code needed here.
- Everyone else (shop owners, restaurant staff) has **no platform-wide role** relevant
  to restaurant data — their access is entirely determined by restaurant membership
  (below). They may still be a Frappe `User` with the base `All`/`Desk User` roles
  needed to log in and use the Desk UI for the screens they're allowed to see.

## SaaS account-level authorization (`Restaurant Owner` role) — *Slice 1*

Between "platform admin" and "restaurant staff" sits a third, narrower concept:
**is this user a paying SaaS customer who may hold an `Owner Subscription` and create
`Restaurant` records at all?** That's what the Frappe Role `Restaurant Owner`
(`desk_access = 1`) answers. It is intentionally a *platform*-scoped role (assigned once
per SaaS account, not per restaurant) — don't confuse it with the *restaurant-scoped*
`OWNER` value of `Restaurant Member.role` introduced in Slice 2, described below. They
usually apply to the same person (the person who owns the subscription is normally also
the operational `OWNER` of every restaurant they create), but they're enforced by two
completely different mechanisms:

| | `Restaurant Owner` (Frappe Role) | `Restaurant Member.role = OWNER` (Slice 2) |
|---|---|---|
| Scope | Whole SaaS account (one `Owner Subscription`) | One specific restaurant |
| Grants | Desk access; base create/read/write on `Restaurant`, read on `Owner Subscription` | Full operational control at that one restaurant (menu, staff, orders...) |
| A user could have it and still... | ...own zero restaurants yet, or have hit their plan limit | ...simultaneously be `CASHIER` at a *different* restaurant they don't own |

Standard Frappe DocType permissions grant `Restaurant Owner` base `create`/`read`/`write`
on `Restaurant` and `read` on `Owner Subscription` — deliberately **no** `create`/`write`
on `Owner Subscription` (assignment stays admin-managed for v1) and **no** `delete` on
`Restaurant` (deactivate via `status`, don't destroy history). (Slice 2 also gave the
*separate* `Restaurant Staff` role — see below — base `read`/`write` on `Restaurant`, no
`create`: only a subscription owner creates restaurants; staff join an existing one.)
Those base grants are then narrowed to "only rows this user actually owns or works at"
by two more hooks, both in `e_menu/permissions.py`:

- **`permission_query_conditions`** — scopes list/report views (`owner_user = <user>`).
- **`has_permission`** — scopes direct single-document read/write. For `create` on
  `Restaurant` specifically, this hook always returns `True` for a non-admin: the
  document's `owner_user` is a `fetch_from` field that isn't populated yet at the point
  Frappe checks create-permission (fetch happens during `validate()`, which runs after),
  so the *real* ownership check for creation lives in `Restaurant.validate()`
  (`validate_actor_owns_subscription`) instead — see `domain-model.md`. This is a
  concrete instance of the general rule stated in `architecture.md`: **UI-only/query-only
  filtering is not a security boundary; the write-path check in the controller is.**

## Restaurant-level authorization — *Slice 2, implemented*

### Roles

| Role | Intent |
|---|---|
| `OWNER` | Full control of the restaurant: menu, staff, tables, all order/payment actions. |
| `MANAGER` | Same operational scope as owner minus platform/business-critical settings (exact boundary refined in Slice 3+ as real screens exist). |
| `CASHIER` | Order/payment operations: accept/reject, mark served, confirm manual payments. No menu/staff management. |
| `KITCHEN` | Order fulfillment only: see accepted orders, mark preparing/ready. No access to menu editing, staff, tables, or payment confirmation. |

These are **`Restaurant Member.role` values (a Select field), not Frappe Roles.** Don't
confuse `Restaurant Member.role = "OWNER"` (one specific restaurant) with the Frappe Role
`Restaurant Owner` (the whole SaaS account, described above) — see the comparison table
above for how they differ.

### The `Restaurant Staff` Frappe Role

Every restaurant persona (`OWNER`/`MANAGER`/`CASHIER`/`KITCHEN` alike) also needs *some*
Frappe-level Desk-access role — that's `Restaurant Staff` (`desk_access = 1`), granted
automatically (`RestaurantMember.sync_frappe_role`, additive-only) the moment a user
gets any active `Restaurant Member` row, at any restaurant, in any role. It's a coarse
"has Desk access because they work at *a* restaurant somewhere" gate; it carries base
`read`/`write` on `Restaurant` and `Restaurant Member` (see above) but **grants no
restaurant-specific distinction by itself** — a `KITCHEN` worker and an `OWNER` hold the
exact same Frappe Role. All of the real, role-specific narrowing (can this `CASHIER`
write to *this* `Restaurant`? can this `KITCHEN` worker invite staff?) happens via the
mechanism below, never via `Restaurant Staff`'s own DocType permission grants.

### How a request is authorized

The shared helper is `e_menu.permissions.get_active_restaurant_role(user, restaurant)`
— the restaurant-scoped counterpart to `frappe.get_roles()`. Every check follows the
same shape:

1. Resolve `frappe.session.user`.
2. Resolve the `restaurant` the request targets (a field on the document, or an explicit
   parameter on a whitelisted API method like `invite_staff`).
3. Call `get_active_restaurant_role(user, restaurant)`.
   - `None` (no active `Restaurant Member` row) → reject (`frappe.PermissionError`),
     regardless of what the request body claims about the restaurant. **A
     client-supplied `restaurant` field is never sufficient for authorization by
     itself** — it only says which restaurant's membership to check.
   - A role → check it against what the specific action requires. Implemented so far:
     `MANAGING_ROLES = ("OWNER", "MANAGER")` gates writing a `Restaurant` record and
     managing its staff roster (`RestaurantMember.validate_actor_can_manage_staff`,
     `invite_staff`); any active role (including `CASHIER`/`KITCHEN`) is enough to
     *read* the restaurant and its staff list.
4. Platform admins (`System Manager`) bypass step 3 and may act on any restaurant — this
   is the one explicit, intentional exception, used for support/admin tooling only.
5. **One bootstrapping exception:** a restaurant's very first `Restaurant Member` row
   (`role=OWNER`, for the subscription owner) is created automatically by
   `Restaurant.after_insert` — at that instant no membership row exists yet to check
   against, so `RestaurantMember._is_owner_bootstrap()` recognizes this one specific
   case (new row, role OWNER, `user == restaurant.owner_user == frappe.session.user`, no
   existing active member) and allows it. Every other membership change goes through the
   normal OWNER/MANAGER check.

This check happens in **every** write path that touches restaurant-owned data: DocType
`validate()` controllers for direct document writes (`Restaurant.validate()`,
`RestaurantMember.validate()`), and inside whitelisted API methods for actions that
aren't plain CRUD (`invite_staff`; `Order.accept()` etc. will follow the same pattern in
later slices). List views and reports are additionally scoped with Frappe **permission
query conditions** so staff simply never see rows for restaurants they don't belong to —
but that's a UX/performance filter, not the security boundary; the write-path check is.
Proven end-to-end for Slice 2 both by `bench run-tests --app e_menu` and live over real
HTTP (login as staff, list/read/invite calls against a restaurant they don't belong to).

A restaurant is also never left without anyone able to manage it:
`RestaurantMember.validate_not_removing_last_owner` rejects disabling (or role-changing
away from `OWNER`) the last active `OWNER` membership of a restaurant.

### Cross-restaurant reference integrity

Some checks aren't about "who can act" but "does this data make sense" — e.g. a `Menu
Item.category` must belong to the same restaurant as the `Menu Item` itself. These are
enforced in the same `validate()` methods, independent of the membership check, because
they're invariants of the data model, not permissions per se. See `domain-model.md` for
the specific integrity rules per DocType.

## Customer-facing (unauthenticated) access

Customers never log in — requests from the QR/menu/ordering flow run as Frappe's
built-in `Guest` role. Their "authorization" isn't role-based at all: it's **scoped by
possession of a valid table QR token**. The public menu/order endpoints:

- resolve `restaurant` + `table` strictly from the `qr_token` in the URL (never from a
  client-supplied restaurant/table ID directly — the token is the only trusted input),
- reject if the token doesn't match an active table on an active restaurant,
- allow only a narrow set of actions (browse active categories/available items, submit
  an order to *that* table) — nothing else on the `Restaurant`/`Menu Item`/etc. DocTypes
  is reachable by `Guest`.

Full mechanics land in Slice 4 (QR/token design) and Slice 5 (public menu routes).

## Frappe v15/v16 custom permission "actions"

Frappe supports declaring custom permission actions beyond the standard
read/write/create/delete/submit/cancel set (e.g. `accept_order`, `mark_served`,
`void_item`, `manage_staff`). These may be used later purely as a way to express
role-gating on Desk UI buttons/menu entries more declaratively. They are **not** a
substitute for the server-side restaurant-membership check above, and Slices 0–2
deliberately don't introduce them yet — `invite_staff`'s authorization is a plain
explicit `get_active_restaurant_role(...) in MANAGING_ROLES` check, not a custom
permission type. Per the project's "don't add abstractions before the concrete need
exists" principle, they'll be added if/when a screen's permission logic actually gets
unwieldy without them, not preemptively.
