# Development seed/demo data. Idempotent -- safe to run against a fresh or an
# already-seeded site. Not for production use (creates a known demo password).
#
# Usage (from the bench directory):
#   bench --site <site> execute e_menu.demo.create_demo_data

import frappe

DEMO_OWNER_EMAIL = "owner@example.com"
DEMO_OWNER_PASSWORD = "e_menu_demo"


def create_demo_data():
	create_plans()
	owner = create_demo_owner()
	subscription = create_demo_subscription(owner)
	create_demo_restaurant(subscription)
	demonstrate_limit_enforcement(subscription)
	frappe.db.commit()
	print("\nDemo data ready.")
	print(f"Sign in as: {DEMO_OWNER_EMAIL} / {DEMO_OWNER_PASSWORD}")


def create_plans():
	plans = [
		("Free", 1, "Single restaurant, for trying out E-menu."),
		("Starter", 3, "Up to 3 restaurants."),
		("Business", 10, "Higher-volume restaurant groups (limit configurable by admin)."),
	]
	for plan_name, restaurant_limit, description in plans:
		if frappe.db.exists("Subscription Plan", plan_name):
			continue
		frappe.get_doc(
			{
				"doctype": "Subscription Plan",
				"plan_name": plan_name,
				"restaurant_limit": restaurant_limit,
				"description": description,
			}
		).insert(ignore_permissions=True)
		print(f"Created Subscription Plan: {plan_name} (limit={restaurant_limit})")


def create_demo_owner():
	if frappe.db.exists("User", DEMO_OWNER_EMAIL):
		user = frappe.get_doc("User", DEMO_OWNER_EMAIL)
	else:
		user = frappe.get_doc(
			{
				"doctype": "User",
				"email": DEMO_OWNER_EMAIL,
				"first_name": "Demo",
				"last_name": "Owner",
				"send_welcome_email": 0,
			}
		).insert(ignore_permissions=True)
		print(f"Created demo owner User: {DEMO_OWNER_EMAIL}")

	if "Restaurant Owner" not in frappe.get_roles(user.name):
		user.add_roles("Restaurant Owner")
		print("Granted Restaurant Owner role (this also gives Desk access)")

	user.reload()
	user.new_password = DEMO_OWNER_PASSWORD
	user.save(ignore_permissions=True)
	return user


def create_demo_subscription(owner):
	existing = frappe.db.exists("Owner Subscription", {"owner_user": owner.name, "status": "Active"})
	if existing:
		return frappe.get_doc("Owner Subscription", existing)
	sub = frappe.get_doc(
		{
			"doctype": "Owner Subscription",
			"owner_user": owner.name,
			"plan": "Free",
		}
	).insert(ignore_permissions=True)
	print(f"Created Owner Subscription {sub.name} for {owner.name} on Free plan (limit={sub.restaurant_limit})")
	return sub


def create_demo_restaurant(subscription):
	existing = frappe.db.exists(
		"Restaurant", {"owner_subscription": subscription.name, "restaurant_name": "Angkor Cafe"}
	)
	if existing:
		return frappe.get_doc("Restaurant", existing)

	frappe.set_user(subscription.owner_user)
	try:
		restaurant = frappe.get_doc(
			{
				"doctype": "Restaurant",
				"restaurant_name": "Angkor Cafe",
				"owner_subscription": subscription.name,
			}
		).insert()
	finally:
		frappe.set_user("Administrator")
	print(f"Created Restaurant {restaurant.name} 'Angkor Cafe' as the demo owner (public_id={restaurant.public_id})")
	return restaurant


def demonstrate_limit_enforcement(subscription):
	"""Proves the Slice 1 acceptance criterion live: a second restaurant under a
	limit=1 subscription is rejected server-side. Doesn't create anything."""
	frappe.set_user(subscription.owner_user)
	try:
		frappe.get_doc(
			{
				"doctype": "Restaurant",
				"restaurant_name": "Second Restaurant (should fail)",
				"owner_subscription": subscription.name,
			}
		).insert()
	except frappe.ValidationError as e:
		print(f"Confirmed server-side limit enforcement -- second restaurant rejected: {e}")
	else:
		print("WARNING: second restaurant was NOT rejected -- limit enforcement may be broken.")
	finally:
		frappe.set_user("Administrator")
