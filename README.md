# E-menu

E-menu is a B2B SaaS platform for restaurants. Restaurant owners register, manage one or
more restaurants according to their subscription plan, manage menus and staff, generate
QR codes for tables, and receive customer orders. Customers order by scanning a table QR
code — no account required.

E-menu is built as a custom [Frappe](https://frappeframework.com) app (`e_menu`) on top
of Frappe Framework v15. It reuses Frappe's authentication, users, roles, permissions,
DocTypes, REST API, background jobs, and Desk admin UI instead of rebuilding them.

**Status:** Slice 6 (ordering) complete. Customers can scan a table's QR, browse a
live mobile-first menu (`/menu/<public_id>/<table_token>`), and submit a real order
with server-computed, currency-safe totals — no login, no Desk. Restaurant staff see
incoming orders and move them through an explicit lifecycle
(`PENDING → ACCEPTED → PREPARING → READY → SERVED → COMPLETED`, plus `REJECTED`/
`CANCELLED`) via role-gated action buttons on the standard Desk form. See
[docs/development.md](docs/development.md) for the delivery plan and what's next.

## Repository scope

This repository contains **only the `e_menu` Frappe app** (this directory *is* the app
root — `e_menu/` below is the Python package). It does not contain Frappe Framework
itself or a full bench. See [docs/development.md](docs/development.md) for why, and for
how to stand up a bench locally that installs this app.

```
.
├── e_menu/                 # the Frappe app package
│   ├── hooks.py             # app metadata & integration points
│   ├── modules.txt          # Frappe modules owned by this app
│   ├── permissions.py       # restaurant-level query conditions & has_permission hooks
│   ├── config/               # desk sidebar config
│   ├── patches/              # data migration patches
│   ├── public/                # static assets (css/js)
│   ├── templates/            # Jinja templates / web pages
│   ├── www/                   # public customer pages (no Desk, no login)
│   │   ├── menu.py             # /menu/<public_id>/<table_token> -- get_context()
│   │   ├── menu.html           # standalone mobile-first page + cart JS
│   │   └── test_menu.py
│   ├── patches/v0_0/          # e.g. backfill_restaurant_owner_membership
│   └── e_menu/                # "E Menu" module: DocTypes + demo.py (seed data)
│       ├── doctype/
│       │   ├── subscription_plan/
│       │   ├── owner_subscription/
│       │   ├── restaurant/
│       │   ├── restaurant_member/   # + invite_staff() whitelisted API
│       │   ├── menu_category/
│       │   ├── menu_item/
│       │   ├── restaurant_table/    # + resolve_qr() whitelisted, allow_guest API
│       │   ├── order/               # + submit_order() (Guest) + accept/reject/... actions
│       │   └── order_item/          # child table of Order
│       ├── testing.py         # shared test fixtures (owner/staff/restaurant helpers)
│       └── demo.py
├── docs/
│   ├── architecture.md      # layered architecture, tenancy model
│   ├── domain-model.md      # implemented + planned DocTypes & ER diagram
│   ├── permissions.md       # platform vs. account vs. restaurant-level authorization
│   └── development.md       # environment setup & daily dev commands
├── pyproject.toml
├── license.txt
└── README.md
```

## Quick start

See [docs/development.md](docs/development.md) for full setup instructions (environment
choice, bench init, site creation) and the day-to-day commands you'll use once the bench
exists.

```bash
# from inside an existing bench directory
bench get-app e_menu /path/to/this/repo   # or a git URL
bench --site <site> install-app e_menu
bench start
```

## Documentation

- [docs/architecture.md](docs/architecture.md) — layered architecture, multi-tenancy model
- [docs/domain-model.md](docs/domain-model.md) — DocTypes (implemented + planned) and their relationships
- [docs/permissions.md](docs/permissions.md) — platform vs. account vs. restaurant-level authorization
- [docs/development.md](docs/development.md) — environment setup, daily commands, decisions log

## License

Proprietary. See [license.txt](license.txt).
