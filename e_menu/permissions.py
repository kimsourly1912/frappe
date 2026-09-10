# Restaurant-level authorization helpers.
#
# Platform admins (System Manager) are exempt from every check below and see
# everything -- see docs/permissions.md. Everyone else's access is scoped to rows
# they actually own or are an active restaurant staff member of, enforced here at
# two levels: permission_query_conditions (list/report views) and has_permission
# (single-document read/write checks). Neither layer is a substitute for the
# write-path validation in each DocType's controller -- see restaurant.py,
# owner_subscription.py, and restaurant_member.py for the corresponding
# validate() checks.

import frappe

MANAGING_ROLES = ("OWNER", "MANAGER")


def is_platform_admin(user: str) -> bool:
	return user == "Administrator" or "System Manager" in frappe.get_roles(user)


def get_active_restaurant_role(user: str, restaurant: str) -> str | None:
	"""The user's restaurant-level role (OWNER/MANAGER/CASHIER/KITCHEN) at this one
	restaurant, or None if they have no active membership there. This is the
	restaurant-scoped counterpart to frappe.get_roles() -- see docs/permissions.md
	for why a single global Frappe Role can't express this."""
	return frappe.db.get_value(
		"Restaurant Member",
		{"restaurant": restaurant, "user": user, "status": "Active"},
		"role",
	)


def _active_membership_subquery(escaped_user: str) -> str:
	return (
		f"select restaurant from `tabRestaurant Member` "
		f"where user = {escaped_user} and status = 'Active'"
	)


def _restaurant_scoped_query_conditions(table: str, user: str | None = None) -> str:
	"""Shared permission_query_conditions shape for any DocType with a plain
	'restaurant' Link field (Restaurant Member, Menu Category, Menu Item, ...):
	visible to any active staff member of that restaurant. Restaurant itself is
	similar but also OR's in owner_user, so it isn't built on this helper."""
	user = user or frappe.session.user
	if is_platform_admin(user):
		return ""
	escaped_user = frappe.db.escape(user)
	return f"(`tab{table}`.restaurant in ({_active_membership_subquery(escaped_user)}))"


def _restaurant_scoped_has_permission(doc, ptype: str | None = None, user: str | None = None) -> bool:
	"""Shared has_permission shape for the same kind of DocType: read for any active
	staff member of doc.restaurant, write/create/delete for OWNER/MANAGER only.
	Assumes doc.restaurant is a plain field (not fetch_from), so it's already
	populated even on an in-memory, not-yet-inserted document -- unlike
	Restaurant.owner_user, there's no create-time timing issue to special-case."""
	user = user or frappe.session.user
	if is_platform_admin(user):
		return True
	role = get_active_restaurant_role(user, doc.restaurant)
	if role is None:
		return False
	if ptype == "read":
		return True
	return role in MANAGING_ROLES


def get_permission_query_conditions_for_owner_subscription(user: str | None = None) -> str:
	user = user or frappe.session.user
	if is_platform_admin(user):
		return ""
	return f"(`tabOwner Subscription`.owner_user = {frappe.db.escape(user)})"


def has_permission_owner_subscription(doc, ptype: str | None = None, user: str | None = None) -> bool:
	user = user or frappe.session.user
	if is_platform_admin(user):
		return True
	return doc.owner_user == user


def get_permission_query_conditions_for_restaurant(user: str | None = None) -> str:
	"""Visible to: the subscription owner, or any active restaurant staff member
	(any role) -- staff need to see the restaurant they work at, not just its owner."""
	user = user or frappe.session.user
	if is_platform_admin(user):
		return ""
	escaped_user = frappe.db.escape(user)
	return (
		f"(`tabRestaurant`.owner_user = {escaped_user} "
		f"or `tabRestaurant`.name in ({_active_membership_subquery(escaped_user)}))"
	)


def has_permission_restaurant(doc, ptype: str | None = None, user: str | None = None) -> bool:
	user = user or frappe.session.user
	if is_platform_admin(user):
		return True
	if ptype == "create":
		# doc.owner_user is fetch_from("owner_subscription.owner_user") -- it isn't
		# populated yet at this point in the insert lifecycle (fetch_from runs during
		# validate, which happens after this check). The base DocType permission
		# (Restaurant Owner: create=1) plus the authoritative ownership check in
		# Restaurant.validate() (validate_actor_owns_subscription) are what actually
		# gate creation -- this hook only narrows read/write/delete on existing docs.
		return True
	if doc.owner_user == user:
		return True
	role = get_active_restaurant_role(user, doc.name)
	if role is None:
		return False
	if ptype == "read":
		return True
	# write/delete on the Restaurant record itself (settings, not day-to-day
	# operations): OWNER/MANAGER only. CASHIER/KITCHEN can read but not edit.
	return role in MANAGING_ROLES


def get_permission_query_conditions_for_restaurant_member(user: str | None = None) -> str:
	"""Visible to: any active member of the same restaurant (so staff can see their
	own restaurant's roster) -- narrower than that (e.g. hiding colleagues' rows
	from CASHIER/KITCHEN) isn't a concrete requirement yet, so it isn't built."""
	return _restaurant_scoped_query_conditions("Restaurant Member", user)


def has_permission_restaurant_member(doc, ptype: str | None = None, user: str | None = None) -> bool:
	user = user or frappe.session.user
	if ptype == "create" and not is_platform_admin(user):
		# Restaurant Member.validate() (validate_actor_can_manage_staff) is the
		# authoritative check for who may actually create a membership row --
		# it also handles the owner-bootstrap exception, which doesn't fit this
		# generic shape.
		return True
	return _restaurant_scoped_has_permission(doc, ptype, user)


def get_permission_query_conditions_for_menu_category(user: str | None = None) -> str:
	return _restaurant_scoped_query_conditions("Menu Category", user)


def has_permission_menu_category(doc, ptype: str | None = None, user: str | None = None) -> bool:
	return _restaurant_scoped_has_permission(doc, ptype, user)


def get_permission_query_conditions_for_menu_item(user: str | None = None) -> str:
	return _restaurant_scoped_query_conditions("Menu Item", user)


def has_permission_menu_item(doc, ptype: str | None = None, user: str | None = None) -> bool:
	return _restaurant_scoped_has_permission(doc, ptype, user)


def get_permission_query_conditions_for_restaurant_table(user: str | None = None) -> str:
	return _restaurant_scoped_query_conditions("Restaurant Table", user)


def has_permission_restaurant_table(doc, ptype: str | None = None, user: str | None = None) -> bool:
	return _restaurant_scoped_has_permission(doc, ptype, user)


def get_permission_query_conditions_for_order(user: str | None = None) -> str:
	return _restaurant_scoped_query_conditions("Order", user)


def has_permission_order(doc, ptype: str | None = None, user: str | None = None) -> bool:
	"""Deliberately NOT built on _restaurant_scoped_has_permission: unlike Menu/
	Table, "write" here doesn't mean "can edit fields" -- Order.validate()
	(reject_direct_edit) unconditionally blocks saving an existing Order no matter
	who's asking, admins included. "write" is granted broadly to any active staff
	member purely because Frappe's own run_method REST/Desk convention
	(frappe/api/v1.py execute_doc_method, and Desk's frm.call()) requires
	has_permission("write") just to *invoke* a whitelisted instance method --
	without it, staff couldn't call accept()/mark_ready()/etc. at all. The actual
	per-action role check (who may call *which* action) happens inside
	Order._transition via ACTION_ROLES; reject_direct_edit is what stops this
	broad "write" grant from becoming a generic PATCH endpoint for order
	contents. Order is created by the customer (submit_order, Guest,
	ignore_permissions=True after its own QR-based resolution) -- no restaurant
	role ever gets "create" here."""
	user = user or frappe.session.user
	if is_platform_admin(user):
		return True
	if ptype not in ("read", "write"):
		return False
	return get_active_restaurant_role(user, doc.restaurant) is not None


def get_permission_query_conditions_for_payment(user: str | None = None) -> str:
	return _restaurant_scoped_query_conditions("Payment", user)


def has_permission_payment(doc, ptype: str | None = None, user: str | None = None) -> bool:
	"""Unlike Order, Payment exposes no whitelisted instance methods -- creation is
	a module-level function (confirm_manual_payment, ignore_permissions=True with
	its own role check) and Payment.reject_direct_edit blocks every resave -- so
	there's no run_method-style reason to grant "write" here. This only ever grants
	"read" to active restaurant staff; base DocType permissions already withhold
	create/write/delete from Restaurant Staff, and this hook adds the matching
	query-level read scoping (paired with get_permission_query_conditions_for_payment)."""
	user = user or frappe.session.user
	if is_platform_admin(user):
		return True
	if ptype != "read":
		return False
	return get_active_restaurant_role(user, doc.restaurant) is not None
