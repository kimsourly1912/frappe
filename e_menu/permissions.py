# Restaurant-level authorization helpers.
#
# Platform admins (System Manager) are exempt from every check below and see
# everything -- see docs/permissions.md. Everyone else's access to Owner
# Subscription / Restaurant records is scoped to rows they actually own, enforced
# here at two levels: permission_query_conditions (list/report views) and
# has_permission (single-document read/write checks). Neither layer is a substitute
# for the write-path validation in each DocType's controller -- see restaurant.py
# and owner_subscription.py for the corresponding validate() checks.

import frappe


def _is_platform_admin(user: str) -> bool:
	return user == "Administrator" or "System Manager" in frappe.get_roles(user)


def get_permission_query_conditions_for_owner_subscription(user: str | None = None) -> str:
	user = user or frappe.session.user
	if _is_platform_admin(user):
		return ""
	return f"(`tabOwner Subscription`.owner_user = {frappe.db.escape(user)})"


def has_permission_owner_subscription(doc, ptype: str | None = None, user: str | None = None) -> bool:
	user = user or frappe.session.user
	if _is_platform_admin(user):
		return True
	return doc.owner_user == user


def get_permission_query_conditions_for_restaurant(user: str | None = None) -> str:
	user = user or frappe.session.user
	if _is_platform_admin(user):
		return ""
	return f"(`tabRestaurant`.owner_user = {frappe.db.escape(user)})"


def has_permission_restaurant(doc, ptype: str | None = None, user: str | None = None) -> bool:
	user = user or frappe.session.user
	if _is_platform_admin(user):
		return True
	if ptype == "create":
		# doc.owner_user is fetch_from("owner_subscription.owner_user") -- it isn't
		# populated yet at this point in the insert lifecycle (fetch_from runs during
		# validate, which happens after this check). The base DocType permission
		# (Restaurant Owner: create=1) plus the authoritative ownership check in
		# Restaurant.validate() (validate_actor_owns_subscription) are what actually
		# gate creation -- this hook only narrows read/write/delete on existing docs.
		return True
	return doc.owner_user == user
