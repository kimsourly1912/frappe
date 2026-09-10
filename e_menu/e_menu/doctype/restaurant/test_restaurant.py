# Copyright (c) 2026, E-menu and Contributors
# See license.txt

import frappe
from frappe.tests.utils import FrappeTestCase


def make_user(prefix="owner"):
	email = f"{prefix}-{frappe.generate_hash(length=8)}@example.test"
	user = frappe.get_doc(
		{
			"doctype": "User",
			"email": email,
			"first_name": prefix,
			"user_type": "System User",
			"send_welcome_email": 0,
		}
	).insert(ignore_permissions=True)
	user.add_roles("Restaurant Owner")
	return user


def make_plan(restaurant_limit):
	return frappe.get_doc(
		{
			"doctype": "Subscription Plan",
			"plan_name": f"Test Plan {frappe.generate_hash(length=8)}",
			"restaurant_limit": restaurant_limit,
		}
	).insert(ignore_permissions=True)


def make_subscription(owner_email, plan_name, status="Active"):
	return frappe.get_doc(
		{
			"doctype": "Owner Subscription",
			"owner_user": owner_email,
			"plan": plan_name,
			"status": status,
		}
	).insert(ignore_permissions=True)


def make_restaurant(restaurant_name, owner_subscription):
	return frappe.get_doc(
		{
			"doctype": "Restaurant",
			"restaurant_name": restaurant_name,
			"owner_subscription": owner_subscription,
		}
	).insert()


class TestRestaurant(FrappeTestCase):
	def tearDown(self):
		frappe.set_user("Administrator")

	def test_owner_can_create_restaurant_within_limit(self):
		plan = make_plan(1)
		owner = make_user()
		sub = make_subscription(owner.name, plan.name)

		frappe.set_user(owner.name)
		restaurant = make_restaurant("Angkor Cafe", sub.name)

		self.assertEqual(restaurant.owner_user, owner.name)
		self.assertTrue(restaurant.public_id)
		self.assertEqual(len(restaurant.public_id), 16)

	def test_restaurant_limit_enforced_server_side(self):
		"""Core Slice 1 acceptance: a plan with restaurant_limit=1 allows exactly one
		restaurant and rejects a second, on the server -- not just in the UI."""
		plan = make_plan(1)
		owner = make_user()
		sub = make_subscription(owner.name, plan.name)

		frappe.set_user(owner.name)
		make_restaurant("Restaurant A", sub.name)

		with self.assertRaises(frappe.ValidationError):
			make_restaurant("Restaurant B", sub.name)

		# still exactly one restaurant on this subscription
		self.assertEqual(frappe.db.count("Restaurant", {"owner_subscription": sub.name}), 1)

	def test_deactivated_restaurant_still_counts_against_limit(self):
		"""Deactivating a restaurant is not a loophole to bypass the plan limit --
		see docs/domain-model.md: prefer status over destructive deletion."""
		plan = make_plan(1)
		owner = make_user()
		sub = make_subscription(owner.name, plan.name)

		frappe.set_user(owner.name)
		restaurant = make_restaurant("Restaurant A", sub.name)
		restaurant.status = "Inactive"
		restaurant.save()

		with self.assertRaises(frappe.ValidationError):
			make_restaurant("Restaurant B", sub.name)

	def test_cannot_create_restaurant_for_another_owners_subscription(self):
		"""A client-supplied owner_subscription is never sufficient authorization by
		itself -- the acting user must actually own that subscription."""
		plan = make_plan(5)
		owner_a = make_user("owner-a")
		owner_b = make_user("owner-b")
		sub_a = make_subscription(owner_a.name, plan.name)

		frappe.set_user(owner_b.name)
		with self.assertRaises(frappe.PermissionError):
			make_restaurant("Should Not Be Created", sub_a.name)

		self.assertEqual(frappe.db.count("Restaurant", {"owner_subscription": sub_a.name}), 0)

	def test_cannot_create_restaurant_under_inactive_subscription(self):
		plan = make_plan(5)
		owner = make_user()
		sub = make_subscription(owner.name, plan.name, status="Suspended")

		frappe.set_user(owner.name)
		with self.assertRaises(frappe.ValidationError):
			make_restaurant("Should Not Be Created", sub.name)

	def test_platform_admin_can_create_restaurant_for_any_owner(self):
		"""Platform admins (System Manager) are the one explicit exception -- e.g. for
		support -- and bypass the ownership check (but not the limit check)."""
		plan = make_plan(1)
		owner = make_user()
		sub = make_subscription(owner.name, plan.name)

		# frappe.set_user not called: bench run-tests executes as Administrator.
		restaurant = make_restaurant("Support Created", sub.name)
		self.assertEqual(restaurant.owner_user, owner.name)

	def test_tenant_isolation_in_list_and_direct_access(self):
		plan = make_plan(5)
		owner_a = make_user("owner-a")
		owner_b = make_user("owner-b")
		sub_a = make_subscription(owner_a.name, plan.name)
		sub_b = make_subscription(owner_b.name, plan.name)

		frappe.set_user(owner_a.name)
		restaurant_a = make_restaurant("Owner A Restaurant", sub_a.name)

		frappe.set_user(owner_b.name)
		restaurant_b = make_restaurant("Owner B Restaurant", sub_b.name)

		# Owner B's list view must not include owner A's restaurant...
		visible_names = frappe.get_list("Restaurant", pluck="name")
		self.assertIn(restaurant_b.name, visible_names)
		self.assertNotIn(restaurant_a.name, visible_names)

		# ...and direct access to owner A's restaurant document is denied, not just
		# hidden from lists.
		with self.assertRaises(frappe.PermissionError):
			frappe.get_doc("Restaurant", restaurant_a.name).check_permission("read")
