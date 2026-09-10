# Development environment

This document records the environment decisions for E-menu and gives you the commands
for day-to-day development. Read it before touching bench.

## Pinned versions

| Component | Version | Why |
|---|---|---|
| Frappe Framework | **v15** (latest, `version-15` branch, currently 15.120.x) | See "Why v15, not v16" below. |
| Python | **3.12** | Within Frappe v15's supported range (`>=3.10,<3.15`); a current, non-EOL interpreter. |
| Node.js | **20+** (22 used in dev) | Frappe v15 requires Node `>=18`. |
| MariaDB | **10.11** (Ubuntu 24.04 `noble` default) | Officially supported DB for Frappe. Postgres was not chosen — no requirement in this product needs it, and MariaDB is Frappe's better-tested default. |
| Redis | **7.x** | Used for cache, queue, and Socket.IO pub/sub — all native Frappe infrastructure. |
| bench CLI | **5.x** (`frappe-bench` on PyPI) | The standard Frappe bench manager. |

### Why v15, not v16

Frappe v16 (`version-16` branch, currently 16.33.x) is stable and production-ready — but
its `pyproject.toml` pins `requires-python = ">=3.14,<3.15"`, i.e. it **requires Python
3.14 exactly**. Python 3.14 is very new (released Oct 2025) and was not reliably
obtainable as a final, stable build in the environment this project was bootstrapped in
(only a release-candidate build was available through the one working installer path;
the OS package repository that ships it was blocked by network policy). Shipping a new
production app on an RC-grade interpreter contradicts the goal of a production-sensible
default.

Frappe v15 is a mature, actively patched release (120+ patch releases) with a Python
range (`3.10`–`3.14`) that's comfortably satisfiable with stock, final-release
interpreters. **Decision: pin Frappe v15 for this project.** Revisit this once Python
3.14 is trivially available in your target deployment environment (it likely will be by
the time this matters) and the team wants v16's features.

This is recorded here as an explicit, documented technical decision (per the "Known /
Assumption / Needs verification" framing) — not an oversight:
- **Known:** v16 requires Python 3.14 exactly; v15 supports 3.10–3.14.
- **Assumption:** a real developer machine (WSL2/Ubuntu, or a Frappe dev container) will
  have easier access to whatever Python build channel it needs than this bootstrap
  environment did — re-evaluate v16 there if desired.
- **Needs verification:** if you deliberately want v16, confirm your target host can
  install a final (non-RC) Python 3.14 before switching.

### Why MariaDB, not PostgreSQL

Frappe officially supports both, but MariaDB is the more battle-tested default across
the Frappe ecosystem (most production Frappe/ERPNext deployments run it), and nothing in
E-menu's requirements (JSON columns, full-text search, decimal money math) needs
Postgres-specific features. Using the default keeps us aligned with upstream docs,
tooling (`bench`), and troubleshooting resources.

### Why one Frappe site for many restaurants (not one site per tenant)

The spec explicitly calls this out, and the codebase follows it: **`Restaurant` is the
tenant boundary, not the Frappe site.** One SaaS site serves every restaurant. Site-per-
tenant would mean provisioning a new MariaDB database and Frappe site per restaurant
signup — heavy operational overhead for what is, functionally, row-level multi-tenancy
(a `restaurant` foreign key + server-side scoping is sufficient and is how virtually
every comparable SaaS is built on Frappe). See
[architecture.md](architecture.md#multi-tenancy-model) for how tenant isolation is
enforced.

## Where to develop: this container vs. your own machine

**This repository was bootstrapped inside a cloud Linux container** (the Claude Code
Remote session), not on a Windows machine — so no WSL2/Docker setup was needed *here*.
The commands below were run directly against Ubuntu 24.04 in that container, and the
bench + site described in "Verifying it runs" live only in that ephemeral container
(bench, MariaDB, Redis, and the site are **not** part of this git repository — only the
`e_menu` app source is).

**For your own Windows 11 machine**, the current (2026) Frappe-recommended path is:

**WSL2 + Ubuntu 24.04 LTS.** This is what the instructions below assume once you're on
your own machine. Frappe/bench is developed and tested against Linux; native Windows is
not supported and Docker Desktop-for-dev adds a layer of indirection (slower file I/O
across the container boundary, extra complexity debugging) that isn't worth it for daily
app development. WSL2 gives you a real Linux filesystem and kernel with near-native
performance, integrates with VS Code (Remote-WSL extension), and is what most of the
Frappe community uses on Windows.

1. Install WSL2 + Ubuntu 24.04 (from an elevated PowerShell): `wsl --install -d Ubuntu-24.04`, then reboot if prompted.
2. Open the Ubuntu shell and update: `sudo apt update && sudo apt upgrade -y`
3. Follow "Setting up a bench from scratch" below **inside the WSL2 Ubuntu shell**, not
   in Windows PowerShell/cmd.
4. Clone this repo *inside* the WSL2 filesystem (e.g. `~/e_menu`), not under `/mnt/c/...`
   — cross-filesystem I/O between Windows and WSL2 is slow and will make `bench build`
   and `bench start` noticeably slower.

If you'd rather containerize instead of using WSL2 directly, Frappe publishes an
official VS Code dev-container setup (`frappe_docker`'s `devcontainer-example`) — it's a
reasonable alternative but is not what this project's instructions below are written
against.

## Setting up a bench from scratch

These are the commands that were actually run to bootstrap this project (adjust package
manager commands if your distro isn't Debian/Ubuntu-based).

```bash
# 1. System dependencies
sudo apt update
sudo apt install -y mariadb-server mariadb-client libmysqlclient-dev \
    python3.12-dev python3.12-venv python3-pip build-essential pkg-config \
    libssl-dev libffi-dev libjpeg-dev zlib1g-dev redis-server cron \
    wkhtmltopdf xfonts-75dpi xfonts-base git curl

# Node.js 20+ and yarn are required too — install via nvm or your distro's Node 20/22 package,
# then: npm install -g yarn

# 2. MariaDB: set utf8mb4 as server default (required by Frappe)
#    In /etc/mysql/mariadb.conf.d/50-server.cnf under [mysqld]:
#      character-set-server = utf8mb4
#      collation-server     = utf8mb4_unicode_ci
sudo service mariadb restart
sudo mysql -u root -e "ALTER USER 'root'@'localhost' IDENTIFIED BY '<your-root-password>';"

# 3. Install the bench CLI
pip3 install --user frappe-bench   # add --break-system-packages if your distro's pip requires it

# 4. Initialize the bench (pulls Frappe v15, installs Python + JS deps, builds assets)
bench init --frappe-branch version-15 --python python3.12 --dev frappe-bench
cd frappe-bench

# 5. Create a site
bench new-site emenu.localhost \
    --mariadb-root-password '<your-root-password>' \
    --admin-password '<your-admin-password>'

# 6. Get this app into the bench and install it on the site
bench get-app e_menu <path-or-git-url-to-this-repo>
bench --site emenu.localhost install-app e_menu

# 7. Run it
bench start
# Desk:   http://emenu.localhost:8000  (add "127.0.0.1 emenu.localhost" to /etc/hosts,
#          or just use http://localhost:8000 with Host header handling — bench's dev
#          server resolves *.localhost automatically on most systems)
```

> **Important:** never run `bench` commands as `root`. Bench refuses (by design — it
> drops privileges to a configured `frappe_user`). Create a normal user, give it `sudo`
> for the system-level steps (MariaDB/package installs), and run all `bench`/`git`
> commands as that user.

### Environment note (this sandbox only)

While bootstrapping in the container this project started in, `frappe`'s `package.json`
pins one dependency (`air-datepicker`) via a `github:` tarball URL, and that
container's network egress policy blocked GitHub tarball downloads for repos outside
this session's allow-list. It was resolved by pointing that one dependency at the
identical version (`2.2.3`) published on the public npm registry instead — same package
name, same exact version, sourced from npm rather than GitHub. **This is very likely a
sandbox-specific restriction, not a general problem** — on a normal WSL2/cloud dev
machine with normal GitHub access, `bench init` should complete without this patch. If
you hit the same `403` fetching `codeload.github.com`, apply the same one-line fix
locally in your own bench's `apps/frappe/package.json` before `yarn install`.

## Daily development commands

```bash
cd frappe-bench

bench start                                  # run web + workers + queue + socketio (dev)
bench --site emenu.localhost console         # Python REPL with frappe context loaded
bench --site emenu.localhost migrate         # apply DocType/schema changes after bench get-app / pulls
bench build --app e_menu                     # rebuild this app's JS/CSS assets
bench --site emenu.localhost list-apps       # confirm installed apps + versions

# Enable tests once per site (Frappe ships this off by default)
bench --site emenu.localhost set-config allow_tests true

# Run this app's tests
bench --site emenu.localhost run-tests --app e_menu

# Seed demo data (idempotent): 3 subscription plans, a demo owner
# (owner@example.com / e_menu_demo) on the Free plan, and one restaurant
# ("Angkor Cafe") -- also prints a live proof that a second restaurant is
# rejected server-side.
bench --site emenu.localhost execute e_menu.e_menu.demo.create_demo_data

# Create a new DocType/report/page (interactive wizard)
bench --site emenu.localhost console
# or: bench make-doctype (inside apps/e_menu, module-scoped)
```

`developer_mode` is enabled on the dev site (`sites/common_site_config.json` →
`"developer_mode": 1`), which is required to create/edit DocTypes as code (JSON +
Python) rather than only through the database.

## Verifying it runs (Slice 0 acceptance)

```bash
bench --site emenu.localhost list-apps
# -> frappe 15.120.1 version-15
#    e_menu 0.0.1    develop

curl -H "Host: emenu.localhost" http://127.0.0.1:8000/api/method/frappe.ping
# -> {"message":"pong"}

curl -H "Host: emenu.localhost" http://127.0.0.1:8000/login
# -> HTTP 200, renders the Frappe login page
```

All three were confirmed during Slice 0 bootstrap.

## Verifying it runs (Slice 1 acceptance)

```bash
bench --site emenu.localhost execute e_menu.e_menu.demo.create_demo_data
# -> creates Free/Starter/Business plans, owner@example.com on Free (limit=1),
#    one restaurant, and prints confirmation that a second one is rejected

bench --site emenu.localhost run-tests --app e_menu
# -> Ran 12 tests ... OK
#    (restaurant-limit enforcement, tenant isolation, cross-owner rejection,
#    inactive-subscription rejection, platform-admin bypass, snapshot/override
#    behavior, duplicate-active-subscription rejection, System User requirement)
```

Also verified live over real HTTP (not just `bench console`/unit tests) during Slice 1:
sign in as `owner@example.com`, `GET /api/resource/Restaurant` returns only that owner's
restaurant, a second `POST /api/resource/Restaurant` under the same subscription returns
HTTP 417 with a clear `ValidationError`, and `GET /api/resource/Subscription Plan` is
403 for the owner but 200 for `Administrator`.

## Verifying it runs (Slice 2 acceptance)

```bash
bench --site emenu.localhost execute e_menu.e_menu.demo.create_demo_data
# -> (re-running is safe/idempotent) also invites a Manager, Cashier, and Kitchen
#    staff member to Angkor Cafe, creates a second unrelated restaurant ("Spice
#    Garden"), and prints confirmation that Angkor Cafe's cashier cannot list or
#    directly read Spice Garden

bench --site emenu.localhost run-tests --app e_menu
# -> Ran 24 tests ... OK
#    (12 from Slice 1, plus: auto-created OWNER membership on restaurant creation,
#    automatic Restaurant Staff role grant, owner/manager can invite staff,
#    cashier/kitchen/non-members cannot, duplicate membership rejected, last-active-
#    OWNER protection, manager can write a Restaurant but cashier cannot, and the
#    core acceptance test: Restaurant A staff cannot list, read, or invite staff
#    into Restaurant B)
```

Also verified live over real HTTP during Slice 2: signed in as `cashier@example.com`
(staff only at Angkor Cafe), `GET /api/resource/Restaurant` returns only Angkor Cafe,
directly `GET`-ing Spice Garden returns HTTP 403, and calling the `invite_staff`
whitelisted method against either restaurant returns HTTP 403 for the cashier but HTTP
200 for `manager@example.com` against Angkor Cafe (the restaurant they actually work at).

## Owner registration: what's automatic vs. manual in Slice 1

Per the spec, "use Frappe's native User/authentication system" — there is no custom
auth code anywhere in this app. What's automatic today, and what's still a manual
platform-admin step:

- **Sign in, "manage profile":** fully native — any Frappe `User` can log in and edit
  their own profile via Desk's "My Settings". No app code involved.
- **Account creation:** in v1, a platform admin creates the owner's `User` (Desk → New
  User) and assigns the `Restaurant Owner` role. Frappe's built-in self-service `/signup`
  page could do the account-creation half automatically (flip `Website Settings →
  disable_signup` off), but a self-registered user lands as a `Website User` with no
  Desk access — a platform admin would still need to grant the `Restaurant Owner` role
  before that account could do anything restaurant-related. Deliberately deferred rather
  than half-building an onboarding flow; revisit when onboarding UX is actually in scope.
- **Owner Subscription assignment:** manual by design for v1 (see `domain-model.md`) —
  a platform admin links a `User` to a `Subscription Plan`.

## Restaurant staff: what's built in Slice 2

`Restaurant Member` (the join between `User` and `Restaurant` carrying the
restaurant-level `OWNER`/`MANAGER`/`CASHIER`/`KITCHEN` role — distinct from the
platform-level `Restaurant Owner` Frappe Role from Slice 1; see `permissions.md`) is
implemented, along with:
- `invite_staff(restaurant, email, role)` — the owner/manager-facing action to add
  staff, creating their `User` if needed.
- Automatic `OWNER` membership + `Restaurant Staff` Desk-access role whenever a
  restaurant is created or someone is invited.
- A restaurant always keeps at least one active `OWNER` (can't disable the last one).
- `Restaurant` read/write access extended from "just the subscription owner" (Slice 1)
  to "any active staff member can read; OWNER/MANAGER can also write".

## Verifying it runs (Slice 3 acceptance)

```bash
bench --site emenu.localhost execute e_menu.e_menu.demo.create_demo_data
# -> (still idempotent) also creates Food/Drinks categories and Fried Rice ($3.50) /
#    Iced Coffee ($1.50) menu items for Angkor Cafe, and prints confirmation that
#    Angkor Cafe cannot use a category from Spice Garden

bench --site emenu.localhost run-tests --app e_menu
# -> Ran 39 tests ... OK
#    (24 from Slices 1-2, plus: owner/manager can create categories and items,
#    cashier/kitchen cannot, category names unique per restaurant but may repeat
#    across restaurants, menu items require non-negative price, tenant isolation
#    for both Menu Category and Menu Item, and the core acceptance test: a Menu
#    Item can never reference a Menu Category from a different restaurant)
```

Also verified live over real HTTP during Slice 3: signed in as the demo owner,
`GET /api/resource/Menu Item` returns Angkor Cafe's two seeded items; signed in as
`manager@example.com`, `POST /api/resource/Menu Item` succeeds (200); signed in as
`cashier@example.com`, the same `POST` on `Menu Category` returns HTTP 403; and a
`POST /api/resource/Menu Item` referencing a category from a different restaurant
returns HTTP 417 with a clear `ValidationError`.

## Menu management: what's built in Slice 3

`Menu Category` and `Menu Item` (`e_menu/e_menu/doctype/menu_category/`,
`.../menu_item/`) reuse the exact restaurant-level authorization mechanism from Slice 2
— see `permissions.md` → "Extending this to new restaurant-scoped DocTypes" — rather
than inventing anything new: any active staff member reads the menu, `OWNER`/`MANAGER`
manage it, `CASHIER`/`KITCHEN` don't. The one new rule is the cross-restaurant integrity
check on `Menu Item.category` (see `domain-model.md`).

Test fixtures shared across three-plus doctype test files (owner/staff/restaurant setup)
were extracted into `e_menu/e_menu/testing.py` at this point, replacing per-file copies.

## What's next: Slice 4

Slice 4 implements tables and QR codes: `Restaurant Table` with a secure, unguessable
`qr_token` (never the sequential internal document name), QR code generation, and the
public QR URL shape. Acceptance: scanning a QR resolves exactly one active
Restaurant + Table; invalid/deactivated tokens fail safely. See
[domain-model.md](domain-model.md) for the planned shape.
