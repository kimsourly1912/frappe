# Shared test fixtures used across this app's test_*.py files. Not itself a test
# module (no "test_" prefix, so it isn't picked up by test discovery) -- just the
# repeated setup (owner/staff users, a restaurant, staff membership) that's used
# by three or more doctypes' tests now.

import frappe


def make_owner(prefix: str = "owner"):
	email = f"{prefix}-{frappe.generate_hash(length=8)}@example.test"
	user = frappe.get_doc(
		{
			"doctype": "User",
			"email": email,
			"first_name": prefix,
			"send_welcome_email": 0,
		}
	).insert(ignore_permissions=True)
	user.add_roles("Restaurant Owner")
	return user


def make_staff_user(prefix: str = "staff"):
	email = f"{prefix}-{frappe.generate_hash(length=8)}@example.test"
	return frappe.get_doc(
		{
			"doctype": "User",
			"email": email,
			"first_name": prefix,
			"send_welcome_email": 0,
		}
	).insert(ignore_permissions=True)


def make_restaurant_for_owner(owner_email: str, restaurant_limit: int = 5):
	plan = frappe.get_doc(
		{
			"doctype": "Subscription Plan",
			"plan_name": f"Test Plan {frappe.generate_hash(length=8)}",
			"restaurant_limit": restaurant_limit,
		}
	).insert(ignore_permissions=True)
	sub = frappe.get_doc(
		{"doctype": "Owner Subscription", "owner_user": owner_email, "plan": plan.name}
	).insert(ignore_permissions=True)

	frappe.set_user(owner_email)
	try:
		restaurant = frappe.get_doc(
			{
				"doctype": "Restaurant",
				"restaurant_name": f"Test Restaurant {frappe.generate_hash(length=6)}",
				"owner_subscription": sub.name,
			}
		).insert()
	finally:
		frappe.set_user("Administrator")
	return restaurant


def add_member(restaurant: str, user: str, role: str, *, as_user: str | None = None):
	frappe.set_user(as_user or frappe.session.user)
	try:
		return frappe.get_doc(
			{
				"doctype": "Restaurant Member",
				"restaurant": restaurant,
				"user": user,
				"role": role,
			}
		).insert()
	finally:
		frappe.set_user("Administrator")
