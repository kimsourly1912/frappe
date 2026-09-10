# Permissions: platform vs. restaurant-level

> **Status:** Slice 6 — every layer below is implemented: `System Manager` (platform),
> `Restaurant Owner` (SaaS account-level), `Restaurant Member` with its per-restaurant
> `OWNER`/`MANAGER`/`CASHIER`/`KITCHEN` roles plus the `Restaurant Staff` Frappe Role,
> and customer-facing `Guest` access (QR resolution, menu browsing, now order
> submission). `Order` (Slice 6) needed a genuinely different `has_permission` shape
> from every other restaurant-scoped DocType — see "Order: action-based writes, not
> field-based" below, a new, important addition if you've read this file before. Three
> Frappe Roles exist (`System Manager`, `Restaurant Owner`, `Restaurant Staff`)
> alongside the *separate* concept of a `Restaurant Member.role` value — see the "Don't
> confuse these" callouts below if you're new to this file.

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

### Extending this to new restaurant-scoped DocTypes — *pattern established in Slice 3*

`Menu Category` and `Menu Item` (Slice 3) were the third and fourth DocTypes needing
"any active staff member reads, OWNER/MANAGER writes" — at that point the shape was
extracted into two generic helpers in `e_menu/permissions.py`, used by (or wrapped by)
every restaurant-scoped DocType's own hook functions:

- `_restaurant_scoped_query_conditions(table, user)` — the `permission_query_conditions`
  shape, for any DocType with a plain `restaurant` Link field.
- `_restaurant_scoped_has_permission(doc, ptype, user)` — the matching `has_permission`
  shape: read for any active staff member of `doc.restaurant`, write/create/delete
  restricted to `OWNER`/`MANAGER`.

This assumes `restaurant` is a **plain field**, populated directly from the request —
not a `fetch_from` field like `Restaurant.owner_user`, which isn't populated yet at the
point Frappe checks create-permission (see `Restaurant`'s entry above for why that one
needed a `ptype == "create"` special case instead). `Restaurant Table` (Slice 4) reused
both helpers with zero new permission code — confirming the pattern holds for a fifth
DocType. `Order` (Slice 6) is the first one that genuinely doesn't fit — see the next
section — because its write model isn't "edit fields you're allowed to edit" at all.

### Order: action-based writes, not field-based — *Slice 6*

`Order` does **not** use `_restaurant_scoped_has_permission`. Its `get_permission_query_conditions_for_order`
still reuses `_restaurant_scoped_query_conditions` (list-view scoping is unchanged: any
active staff member sees their restaurant's orders), but `has_permission_order` is
hand-written, for a reason worth understanding if you touch this file again:

**An Order is never edited by directly setting fields — ever, for anyone, admins
included.** `Order.validate()` (`reject_direct_edit`) unconditionally throws on any
`.save()` of an existing order. The only legitimate mutations are creation
(`submit_order`, Guest, `ignore_permissions=True`) and the seven named action methods
(`accept`, `reject`, `start_preparing`, `mark_ready`, `mark_served`, `complete`,
`cancel`), which write via `self.db_set(...)` — bypassing `validate()` entirely, so
`reject_direct_edit` never blocks them.

Given that, you'd expect `has_permission_order` to grant **no** restaurant role
"write" at all (mirroring the read-only stance the very first version of this section
took). It can't, for a Frappe-framework reason, not a design choice: **calling *any*
whitelisted instance method through Frappe's own `run_method` convention — both the
REST endpoint (`POST /api/resource/<doctype>/<name>?run_method=...`,
`frappe/api/v1.py:execute_doc_method`) and Desk's `frm.call()`, which is what
`order.js`'s action buttons use — requires `has_permission("write")` before the method
even runs.** This was discovered by testing, not anticipated: the first version of
`has_permission_order` returned `False` for every `ptype` except `"read"`, which
correctly blocked field edits but also silently blocked staff from calling `accept()`/
`mark_ready()`/etc. at all, with a generic `frappe.PermissionError: Not permitted`
that has nothing to do with `ACTION_ROLES`.

The fix: `has_permission_order` grants `"write"` broadly to any active staff member
(same as `"read"`) — this only clears the *framework's* gate to attempt calling a
method at all. Two things do the actual, meaningful authorization:
- **Per-action role checks** (`Order._transition`, checked against `ACTION_ROLES`) —
  *which* action a *which* role may call (`KITCHEN` can't `accept`, `CASHIER` can't
  `start_preparing`, etc.).
- **`reject_direct_edit`** — the thing that stops the broad `"write"` grant from
  becoming a generic PATCH endpoint for order contents, since it blocks every write
  path except the db_set-based action methods, unconditionally.

Neither of those is expressible as a `has_permission` boolean — this is exactly the
"if a DocType needs different read/write boundaries... write that DocType's own
`has_permission` function" case this section already anticipated before Slice 6 landed.

### Cross-restaurant reference integrity — *implemented, Slice 3*

Some checks aren't about "who can act" but "does this data make sense" — e.g. a `Menu
Item.category` must belong to the same restaurant as the `Menu Item` itself
(`MenuItem.validate_category_belongs_to_same_restaurant`). These are enforced in the
same `validate()` methods, independent of the membership check, because they're
invariants of the data model, not permissions per se — the check runs even for a
platform admin, unlike every authorization check above. See `domain-model.md` for the
specific integrity rules per DocType.

## Customer-facing (unauthenticated) access — *implemented, Slices 4-6*

Customers never log in — requests from the QR/menu/ordering flow run as Frappe's
built-in `Guest` role. Their "authorization" isn't role-based at all: it's **scoped by
possession of a valid table QR token**.

`resolve_qr(public_id, table_token)` (`e_menu.e_menu.doctype.restaurant_table
.restaurant_table.resolve_qr`, `@frappe.whitelist(allow_guest=True)`) is this
mechanism's server-side entry point today:

- resolves `restaurant` + `table` strictly from the `public_id`/`qr_token` in the
  request (never from a client-supplied internal document ID directly — the token pair
  is the only trusted input),
- rejects if either side doesn't match an **active** restaurant and an **active**
  table belonging to *that* restaurant, with one identical generic error for every
  failure case (see `domain-model.md` for why — no enumeration by probing),
- is reachable with **zero cookies/session** (verified live: a plain unauthenticated
  `curl` succeeds for a valid token pair, HTTP 404 for an invalid one).

It only resolves *identity* — it doesn't return menu contents or accept an order.

**`e_menu/www/menu.py` (Slice 5)** is the actual public page, built on top of that
resolution: its `get_context()` calls `resolve_qr` directly (not via HTTP — it's a
plain Python function underneath the `@frappe.whitelist` decorator) and, only on
success, queries active `Menu Category`/available `Menu Item` rows scoped to the
resolved `restaurant` — using `frappe.get_all`, which does **not** go through
`permission_query_conditions` (that's for `frappe.get_list`/API access checked against
`frappe.session.user`'s permissions; here there's no restaurant-membership to check
against for `Guest`, resolution via `resolve_qr` already *is* the authorization). The
page never accepts a client-supplied `restaurant`/`category`/`item` id from the
request — everything it renders is scoped to the one `restaurant` the QR resolved to.
Still nothing else on `Restaurant`/`Menu Item`/etc. is reachable by `Guest` through the
normal DocType API — only this one purpose-built, read-only path.

**`submit_order` (Slice 6)** follows the identical shape: `allow_guest=True`, resolves
`(restaurant, table)` via `resolve_qr` and only that resolution (never a client-supplied
`restaurant`/`table` id), and creates with `ignore_permissions=True` since `Guest` has
no restaurant membership for the base permission grid to check in the first place. See
`domain-model.md` for why prices/names are never trusted from the request either. The
cart itself stays client-side (Slice 5's `localStorage`-backed JS) right up until this
one submission call — see `architecture.md` → Customer-facing UI.

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
