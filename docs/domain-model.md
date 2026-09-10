# Domain model

> **Status:** Slice 6 — `Subscription Plan` through `Restaurant Table` (Slices 1-4) plus
> `Order`/`Order Item` (Slice 6) are implemented (fields/behavior below reflect actual
> code, not just the plan). The public customer menu page (Slice 5, no new DocTypes —
> see `architecture.md` → Customer-facing UI) now submits real orders. `Payment` is still
> the planned shape baselined from the product spec — treat that field list as a
> starting point, not a frozen schema.

## Entity-relationship overview

```mermaid
erDiagram
    SUBSCRIPTION_PLAN ||--o{ OWNER_SUBSCRIPTION : "grants"
    USER ||--o| OWNER_SUBSCRIPTION : "holds (owner)"
    OWNER_SUBSCRIPTION ||--o{ RESTAURANT : "limits/owns"
    USER ||--o{ RESTAURANT_MEMBER : "is linked via"
    RESTAURANT ||--o{ RESTAURANT_MEMBER : "has staff"
    RESTAURANT ||--o{ MENU_CATEGORY : "owns"
    RESTAURANT ||--o{ MENU_ITEM : "owns"
    MENU_CATEGORY ||--o{ MENU_ITEM : "groups"
    RESTAURANT ||--o{ RESTAURANT_TABLE : "owns"
    RESTAURANT ||--o{ ORDER_ : "receives"
    RESTAURANT_TABLE ||--o{ ORDER_ : "source of"
    ORDER_ ||--o{ ORDER_ITEM : "contains"
    MENU_ITEM ||--o{ ORDER_ITEM : "referenced by (snapshot)"
    ORDER_ ||--o{ PAYMENT : "settled by"

    SUBSCRIPTION_PLAN {
        string plan_name
        int restaurant_limit
        currency price
    }
    OWNER_SUBSCRIPTION {
        link owner_user "User"
        link plan "Subscription Plan"
        int restaurant_limit "snapshot from plan at assignment time"
        string status "Active/Suspended/Cancelled"
    }
    RESTAURANT {
        string restaurant_name
        string public_id "stable, non-sequential public identifier"
        link owner_subscription
        link owner_user "fetch_from owner_subscription.owner_user"
        string status "Active/Inactive"
    }
    RESTAURANT_MEMBER {
        link restaurant
        link user
        string role "OWNER/MANAGER/CASHIER/KITCHEN"
        string status
    }
    MENU_CATEGORY {
        link restaurant
        string category_name
        int sort_order
        bool is_active
    }
    MENU_ITEM {
        link restaurant
        link category
        string item_name
        currency price
        bool is_available
        bool is_featured
        int sort_order
    }
    RESTAURANT_TABLE {
        link restaurant
        string table_name
        string qr_token "secure, unguessable, unique"
        string status
    }
    ORDER_ {
        link restaurant
        link table
        string status
        currency subtotal
        currency total
        string payment_status
        string payment_method
    }
    ORDER_ITEM {
        link order
        link menu_item
        string item_name_snapshot
        currency unit_price_snapshot
        int quantity
        currency line_total
    }
    PAYMENT {
        link restaurant
        link order
        string provider
        string provider_reference
        string method
        currency amount
        string status
        datetime paid_at
    }
```

(Entity/field names above are illustrative Doctype names; Frappe's actual DocType
names use Title Case with spaces, e.g. `Owner Subscription`, `Restaurant Member`. The
diagram uses `snake_case`/`ORDER_` only because Mermaid reserves the word `ORDER`.)

## Planned DocTypes and design notes

### Subscription Plan — *Slice 1, implemented*
Platform-defined (`System Manager` only — no permission row exists for any other role,
so this is a hard DocType-level restriction, not just a UI hint). Fields: `plan_name`
(autoname, unique), `restaurant_limit` (Int, non-negative), `is_active` (Check),
`description`. `restaurant_limit` is the single enforced constraint for v1; billing
integration is deliberately out of scope until a real provider is chosen (see
architecture.md → Payments for the analogous provider-neutral pattern this will likely
follow).

### Owner Subscription — *Slice 1, implemented*
Links one `User` (`owner_user` — named that, not `owner`, because `owner` is Frappe's
own built-in "created-by" audit field on every document) to one `Subscription Plan`.
Manually assigned by a platform admin for v1 (no self-serve billing yet — see
`permissions.md` for what "manually assigned" means for who can create one).
`restaurant_limit` is **snapshotted** onto the Owner Subscription when it's created or
when its `plan` link changes, rather than always read live from the Plan — so changing a
Plan's limit later doesn't retroactively change limits for owners already on a (possibly
grandfathered) subscription, and a platform admin can freely override the number for one
owner without it snapping back. `status` (`Active`/`Suspended`/`Cancelled`) — only one
`Active` subscription per `owner_user` is allowed at a time (enforced in `validate()`);
older subscriptions are kept as history rather than deleted. The owner must be a Frappe
`User` with `user_type = System User` (Desk access) — enforced in `validate()`, because
Frappe derives `user_type` from whether the user holds any `desk_access` role, so a user
with no relevant role would silently become a Website User regardless of what's set
directly on the field.

**Enforcement:** `Restaurant.validate()` locks the Owner Subscription row (`SELECT ...
FOR UPDATE`), counts the owner's current restaurants (all statuses — see below) against
`Owner Subscription.restaurant_limit`, and raises `frappe.ValidationError` server-side
before insert — verified via both `bench run-tests` and a live HTTP `POST
/api/resource/Restaurant` call, not just the Desk UI disabling a button.

### Restaurant — *Slice 1, implemented*
The tenant boundary. Fields: `restaurant_name`, `owner_subscription` (Link, required),
`owner_user` (Link, read-only, `fetch_from: owner_subscription.owner_user` — denormalized
so the permission query condition doesn't need a JOIN), `public_id` (Data, read-only,
unique, a 16-char random hash generated once in `validate()`), `status`
(`Active`/`Inactive`). `public_id` is distinct from the Frappe `name` (autoname
`REST-.#####`) — a non-sequential, non-guessable identifier safe to expose in
customer-facing QR URLs later (`/menu/<public_id>/<table_token>`, Slice 4+), so internal
sequential document IDs are never exposed to the public internet.

Two independent server-side checks run in `Restaurant.validate()`, both proven with
automated tests (`bench --site <site> run-tests --app e_menu`):
- **Ownership:** the acting user must be `owner_subscription.owner_user`, unless they're
  a platform admin (`System Manager`) — a client can't just supply someone else's
  `owner_subscription` and have it accepted.
- **Limit:** existing restaurants under that subscription (counted regardless of
  `status` — deactivating one is not a loophole to free up a slot, matching "prefer
  deactivation over deletion") must be below `restaurant_limit`.

### Restaurant Member — *Slice 2, implemented*
The join between `User` and `Restaurant`, carrying the **restaurant-level** role
(`OWNER` / `MANAGER` / `CASHIER` / `KITCHEN`) — distinct from Frappe's own system roles
(see `permissions.md` for the full distinction). Fields: `restaurant`, `user`, `role`
(Select), `status` (`Active`/`Disabled`). One `(restaurant, user)` pair may only have one
membership row ever (enforced in `validate()`) — reactivate/change the existing row
rather than inserting a new one; a user *can* have multiple rows across *different*
restaurants, each with an independent role.

Business rules, all in `RestaurantMember.validate()` and proven by automated tests:
- **Who can manage staff:** creating or editing a membership row requires the acting
  user to already be `OWNER` or `MANAGER` at that restaurant (or a platform admin) — see
  `permissions.md` for the one bootstrapping exception (a restaurant's very first OWNER
  row, created automatically).
- **At least one active OWNER:** disabling a membership, or changing its role away from
  `OWNER`, is rejected if it would leave the restaurant with zero active OWNERs.
- **Desk access is additive:** gaining any active membership grants the `Restaurant
  Staff` Frappe Role (`e_menu.e_menu.doctype.restaurant_member.restaurant_member.RestaurantMember.sync_frappe_role`);
  disabling one membership never revokes it, in case the user has Desk access via
  another active membership elsewhere.

`Restaurant.after_insert` automatically creates the restaurant's first `Restaurant
Member` row (`role=OWNER`, for `owner_subscription.owner_user`) — every restaurant has
at least one staff member (its creator) from the moment it exists. A one-time patch
(`e_menu/patches/v0_0/backfill_restaurant_owner_membership.py`) backfills this for
restaurants created in Slice 1, before this hook existed.

**`invite_staff(restaurant, email, role, first_name=None)`** (whitelisted, in
`restaurant_member.py`) is the owner/manager-facing "invite staff" action: creates the
`User` if the email doesn't exist yet, then the `Restaurant Member` row — the one
whitelisted business action for this slice, per the "don't over-engineer the first
version" guidance in the spec (no custom permission-type framework, just an explicit
server-side role check mirroring `validate_actor_can_manage_staff`).

**Restaurant access was extended in this slice** (`e_menu/permissions.py`): originally
(Slice 1) only `owner_subscription.owner_user` could read/write a `Restaurant`. Now any
active staff member can *read* it, and `OWNER`/`MANAGER` can also *write* it —
`CASHIER`/`KITCHEN` remain read-only on the `Restaurant` record itself (they still get
full read/write on whatever their role needs in later slices, e.g. orders).

### Menu Category / Menu Item — *Slice 3, implemented*
Both restaurant-scoped, fieldnames `category_name`/`item_name` (not `name` — Frappe's
own autoname field, same reason `owner_user` isn't called `owner`; see Slice 1).

**Menu Category:** `restaurant`, `category_name`, `description`, `image` (`Attach
Image` — native Frappe file upload, no custom file-handling code), `sort_order`,
`is_active`. Name unique **per restaurant** (not globally), via an explicit `validate()`
query check (Frappe's declarative `unique` field option is a global DB constraint, which
would incorrectly block Restaurant A and B from both having a "Drinks" category) —
MariaDB's `utf8mb4_unicode_ci` collation (see `development.md`) makes the comparison
case-insensitive for free.

**Menu Item:** `restaurant`, `category` (Link), `item_name`, `description`, `image`,
`price` (Currency, non-negative), `is_available`, `is_featured`, `sort_order`. **Core
integrity rule, enforced server-side in `MenuItem.validate()`:** a Menu Item's `category`
must belong to the *same* `restaurant` as the item itself — checked unconditionally
(even for a platform admin), because this is a data-integrity invariant, not an
authorization rule. Proven by automated tests and live over real HTTP
(`POST /api/resource/Menu Item` with a cross-restaurant `category` returns HTTP 417).
A matching client-side `frm.set_query()` filter on the `category` field (Desk UX only,
not a security control) keeps the picker showing only same-restaurant categories.

**Authorization** (`e_menu/permissions.py`, generalized into
`_restaurant_scoped_has_permission`/`_restaurant_scoped_query_conditions` since this is
now the third DocType with the same shape — see `Restaurant Member` above): any active
staff member of the restaurant can read; `OWNER`/`MANAGER` can also create/write/delete.
`CASHIER`/`KITCHEN` are read-only on the menu itself, matching `permissions.md`'s stated
role intent (they need to *see* prices/items, not edit them).

Variants/add-ons are intentionally not modeled in v1; the schema doesn't need to
anticipate them beyond "don't do anything that would make adding them later a rewrite"
(e.g. don't hardcode a single flat price string anywhere outside `Menu Item.price`).

### Restaurant Table — *Slice 4, implemented*
Fields: `restaurant`, `table_name` (unique per restaurant, same pattern as `Menu
Category.category_name`), `status` (`Active`/`Inactive`), `qr_token` (read-only, a
24-char random hash — more entropy than `Restaurant.public_id`'s 16, because this token
is the closest thing an anonymous customer has to an authorization credential in Slices
5+, not just an anti-enumeration measure), `qr_code` (`Attach Image`, auto-generated),
`menu_url` (read-only, the exact URL the QR encodes, shown for convenience/copy-paste).

`qr_token` is generated once in `before_insert` and never changes — it is **not** the
Frappe document `name`/internal ID (same reasoning as `Restaurant.public_id`: never
expose sequential internal IDs publicly). Deactivating a table (`status → Inactive`)
rather than deleting it is what will preserve historical `Order` references once `Order`
exists (Slice 6) — Frappe's link-field `on_delete` behavior would otherwise either block
deletion or null out history; soft-deactivation avoids both problems and matches the
product requirement directly. (Deletion is technically still permitted for `OWNER`/
`MANAGER` in Slice 4, since nothing references a table yet — this will need revisiting
once `Order` links to `Restaurant Table`, likely by removing `delete` from the base
`Restaurant Staff` permission grant.)

`generate_qr_code()` (`Restaurant Table.after_insert`) renders the QR with the
[`qrcode`](https://pypi.org/project/qrcode/) package — pinned in `pyproject.toml` — and
stores it as a public `File` attached to the `qr_code` field, encoding
`{site_url}/menu/{restaurant.public_id}/{table.qr_token}` (via `frappe.utils.get_url()`,
not a hardcoded domain). This is a small, well-established dependency, not a custom QR
encoder — Frappe has no native QR generation and hand-rolling one would be absurd.

**`resolve_qr(public_id, table_token)`** (whitelisted, `allow_guest=True`, in
`restaurant_table.py`) is the server-side mechanism behind the Slice 4 acceptance
criterion: it resolves exactly one active `Restaurant` + `Restaurant Table`, or fails
with the *same generic error* for every failure case (unknown `public_id`, unknown or
mismatched `table_token`, an inactive restaurant, or an inactive table) — deliberately
not distinguishing *why* it failed, so a client can't enumerate restaurants/tables by
probing. This function only resolves identity; it deliberately does **not** render a
menu or any customer-facing page — that's Slice 5's scope, built on top of this.

### Order / Order Item — *Slice 6, implemented*
**Order Item is a child table of Order** (`istable=1`), not an independent top-level
DocType, exactly as planned: order items have no independent lifecycle (never queried,
listed, or permission-checked on their own), and Frappe's child-table mechanism gives
atomic parent+children saves for free — a single `order.insert()` either creates the
whole order or none of it, matching "order creation should be atomic" without any
hand-rolled transaction code. `Order Item` has no `permissions` of its own; access is
entirely governed by the parent `Order`.

**Fields.** `Order`: `restaurant`, `table` (Link → `Restaurant Table`), `status`
(read-only — see below), `items` (Table), `subtotal`, `total` (both read-only,
`Currency`), `payment_method` (`MANUAL`/`ONLINE`, set once at submission),
`payment_status` (`Unpaid`/`Paid`, read-only — the field exists now per the spec's
suggested shape, but nothing sets it to `Paid` yet; that's `Payment`, Slice 7). No
separate `order_number` field — the autoname (`ORD-.#####`) already *is* a stable,
readable order number, so a redundant field would just be two names for the same thing.
`Order Item`: `menu_item` (Link), `item_name_snapshot`, `unit_price_snapshot`
(read-only, both set from the live `Menu Item` only once, at order creation),
`quantity` (≥ 1), `line_total` (read-only), `customer_note`.

**Money is `Currency`/`flt()`, not `float` arithmetic treated carelessly, and never
Python's `decimal.Decimal`.** The spec says "never use floating-point money
calculations" — Frappe's `Currency` fields are backed by `decimal(21,9)` **database
columns** (verified: `DESCRIBE` on an existing Currency column), not floating-point SQL
types, and `frappe.utils.flt()` rounds consistently at the field's configured precision
during application-level arithmetic. That combination is Frappe's own native,
idiomatic answer to "currency-safe values" — used the same way throughout ERPNext's
entire accounting stack — so introducing `decimal.Decimal` on top of it would be
non-idiomatic and add serialization complexity for no real safety gain.

**Totals are computed exactly once, entirely server-side, in one place:**
`Order.snapshot_and_calculate_items()`, called from `validate()` only when
`self.is_new()`. For every line: re-reads the `Menu Item` fresh from the database
(never trusts a client-supplied `menu_item.price`/name/line total), rejects it if it
doesn't belong to this order's own `restaurant` (the same cross-tenant integrity rule
as `Menu Item.category`) or isn't currently `is_available`, and only then sets
`item_name_snapshot`/`unit_price_snapshot`/`line_total`. `subtotal`/`total` are the sum
of the (now server-computed) line totals. This is the one authoritative place — not
`submit_order()` (below), which deliberately never reads the client's price at all, so
there's nothing for that entry point to get wrong even if a future caller tried.

**`submit_order(public_id, table_token, items, payment_method)`** (`order.py`,
`@frappe.whitelist(allow_guest=True)`) is the customer-facing entry point: resolves
`restaurant`/`table` via `resolve_qr` (Slice 4, never from the request body directly),
builds the `Order` + child rows from `{menu_item, quantity, customer_note}` only, and
inserts with `ignore_permissions=True` (Guest has no restaurant membership to check
against — `resolve_qr`'s successful resolution already *is* the authorization, the same
pattern as `Restaurant.after_insert`'s membership bootstrap and `invite_staff`).

**Order lifecycle** is an explicit state machine —
`PENDING → ACCEPTED → PREPARING → READY → SERVED → COMPLETED`, plus terminal
`REJECTED` (from `PENDING` only) and `CANCELLED` (from `PENDING`/`ACCEPTED`/`PREPARING`
— cancelling stops making sense once food is ready/served) — implemented as named,
individually `@frappe.whitelist()`-ed instance methods (`accept()`, `reject()`,
`start_preparing()`, `mark_ready()`, `mark_served()`, `complete()`, `cancel()`), never a
generic "PATCH status to anything" endpoint. Each shares a private `_transition()`
helper that checks the acting user's restaurant-level role against `ACTION_ROLES` for
that specific action, then checks the order's current status is in that action's
allowed source set, then writes with `self.db_set("status", ...)` — deliberately
**not** `self.save()`, so the transition never re-runs `validate()` (and its item/total
recalculation) and is unaffected by `Order.validate()`'s blanket rejection of direct
edits (next paragraph). Role-to-action mapping matches `permissions.md`'s stated
intent: `CASHIER` handles front-of-house (`accept`/`reject`/`mark_served`/`complete`/
`cancel`), `KITCHEN` handles fulfillment (`start_preparing`/`mark_ready`) only,
`OWNER`/`MANAGER` can do everything.

**An existing Order can never be edited directly — not even by a platform admin.**
`Order.validate()` unconditionally rejects any `.save()` on a non-new order
(`reject_direct_edit`). This is stronger than "don't let staff hand-edit `status`": see
`permissions.md` for why it has to be unconditional — `has_permission_order` grants
"write" broadly to any active staff member (a Frappe framework requirement, not a
choice: `frm.call()`/the `run_method` REST endpoint both require `has_permission
("write")` just to *invoke* a whitelisted instance method), so this blanket
`validate()` guard is the actual thing standing between that broad grant and a generic
PATCH endpoint for order contents.

**Staff operational screen**: plain Frappe Desk, not a custom page. `order.js` adds
status-appropriate action buttons (`frm.add_custom_button` calling `frm.call(method)`)
to the standard document form — no new UI framework, no dashboard/kanban view, matching
the "don't add abstractions before the concrete need exists" principle. Desk's existing
list view (already restaurant-scoped, from `permission_query_conditions`) is "see
incoming orders"; the form + action buttons are "move it through valid states". If a
faster multi-order-at-a-glance view becomes a real need later, that's a concrete
trigger to revisit — not a preemptive one.

### Payment — *Slice 7 (manual) / Slice 8 (provider abstraction)*
Restaurant- and order-scoped. `provider` distinguishes `MANUAL` from named online
providers; `provider_reference` holds the gateway's own transaction id for online
payments. An order's `payment_status` only flips to paid once a `Payment` row reaches
`PAID` status — for online payments, that transition is driven by a server-verified
callback/webhook/reconciliation call, **never** by the customer's browser reaching a
"success" redirect page. See architecture.md → Payments for the abstraction boundary.

## Explicitly deferred / not modeled in v1

- Billing/subscription payment integration (Owner Subscription assignment is manual).
- Menu item variants and add-ons.
- Real online payment gateway integration (Slice 8 ships a mock/test provider only).
- `Restaurant Settings` as a separate DocType — not introduced until a concrete need
  for restaurant-level configuration beyond what fits on `Restaurant` itself appears
  (per the "don't add abstractions before the pattern exists" principle).
