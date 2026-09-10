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
	return f"""(`tabRestaurant`.owner_user = {escaped_user}
		or `tabRestaurant`.name in (
			select restaurant from `tabRestaurant Member`
			where user = {escaped_user} and status = 'Active'
		))"""


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
	user = user or frappe.session.user
	if is_platform_admin(user):
		return ""
	escaped_user = frappe.db.escape(user)
	return f"""(`tabRestaurant Member`.restaurant in (
		select restaurant from `tabRestaurant Member`
		where user = {escaped_user} and status = 'Active'
	))"""


def has_permission_restaurant_member(doc, ptype: str | None = None, user: str | None = None) -> bool:
	user = user or frappe.session.user
	if is_platform_admin(user):
		return True
	if ptype == "create":
		# Restaurant Member.validate() (validate_actor_can_manage_staff) is the
		# authoritative check for who may actually create a membership row.
		return True
	role = get_active_restaurant_role(user, doc.restaurant)
	if role is None:
		return False
	if ptype == "read":
		return True
	# write/delete (changing someone's role, disabling them): OWNER/MANAGER only --
	# also enforced in Restaurant Member.validate(), this is the read/write gate.
	return role in MANAGING_ROLES
