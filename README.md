# E-menu

E-menu is a B2B SaaS platform for restaurants. Restaurant owners register, manage one or
more restaurants according to their subscription plan, manage menus and staff, generate
QR codes for tables, and receive customer orders. Customers order by scanning a table QR
code — no account required.

E-menu is built as a custom [Frappe](https://frappeframework.com) app (`e_menu`) on top
of Frappe Framework v15. It reuses Frappe's authentication, users, roles, permissions,
DocTypes, REST API, background jobs, and Desk admin UI instead of rebuilding them.

**Status:** Slice 1 (SaaS ownership) complete. `Subscription Plan`, `Owner Subscription`,
and `Restaurant` are implemented, with server-side restaurant-limit enforcement and
tenant-isolated access. See [docs/development.md](docs/development.md) for the delivery
plan and what's next.

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
│   ├── www/                   # public web routes (customer-facing pages, later slices)
│   └── e_menu/                # "E Menu" module: DocTypes + demo.py (seed data)
│       ├── doctype/
│       │   ├── subscription_plan/
│       │   ├── owner_subscription/
│       │   └── restaurant/
│       └── demo.py
├── docs/
│   ├── architecture.md      # layered architecture, tenancy model
│   ├── domain-model.md      # planned DocTypes & ER diagram
│   ├── permissions.md       # platform vs restaurant-level authorization
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
