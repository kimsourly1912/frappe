# Permissions: platform vs. restaurant-level

> **Status:** Slice 0 — no roles or DocTypes exist yet. This documents the model that
> Slices 1–2 implement. Kept close to `architecture.md`'s summary but detailed enough
> to implement against directly.

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

## Restaurant-level authorization

### Roles (initial set)

| Role | Intent |
|---|---|
| `OWNER` | Full control of the restaurant: menu, staff, tables, all order/payment actions. |
| `MANAGER` | Same operational scope as owner minus platform/business-critical settings (exact boundary refined in Slice 2/3 as real screens exist). |
| `CASHIER` | Order/payment operations: accept/reject, mark served, confirm manual payments. No menu/staff management. |
| `KITCHEN` | Order fulfillment only: see accepted orders, mark preparing/ready. No access to menu editing, staff, tables, or payment confirmation. |

### How a request is authorized

1. Resolve `frappe.session.user`.
2. Resolve the `restaurant` the request targets (from the document being read/written,
   or an explicit parameter on a whitelisted API method).
3. Look up an **active** `Restaurant Member` row for `(user, restaurant)`.
   - No active row → reject (`frappe.PermissionError`), regardless of what the request
     body claims about the restaurant. **A client-supplied `restaurant` field is never
     sufficient for authorization by itself** — it only says which restaurant's
     membership to check.
   - Active row found → check `role` against what the specific action requires (e.g.
     `manage_staff` requires OWNER/MANAGER; `mark_ready` accepts KITCHEN too).
4. Platform admins (`System Manager`) bypass step 3 and may act on any restaurant — this
   is the one explicit, intentional exception, used for support/admin tooling only.

This check happens in **every** write path that touches restaurant-owned data: DocType
`validate()`/`before_save()` controllers for direct document writes, and inside
whitelisted API methods for actions that aren't plain CRUD (e.g. `Order.accept()`).
List views and reports are additionally scoped with Frappe **permission query
conditions** so staff simply never see rows for restaurants they don't belong to — but
that's a UX/performance filter, not the security boundary; the write-path check is.

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
substitute for the server-side restaurant-membership check above, and Slice 0/1/2
deliberately don't introduce them yet — per the project's "don't add abstractions before
the concrete need exists" principle, they'll be added if/when a screen's permission
logic actually gets unwieldy without them, not preemptively.
