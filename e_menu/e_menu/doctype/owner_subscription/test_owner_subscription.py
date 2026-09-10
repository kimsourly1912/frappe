# Copyright (c) 2026, E-menu and Contributors
# See license.txt

import frappe
from frappe.tests.utils import FrappeTestCase


def make_user(prefix="owner", grant_desk_access=True):
	"""grant_desk_access=True assigns the Restaurant Owner role (desk_access=1),
	which is what actually makes Frappe treat the user as a System User -- see
	User.validate(): user_type is derived from has_desk_access(), not set directly.
	Pass False to get a Website User with no desk access, for negative tests."""
	email = f"{prefix}-{frappe.generate_hash(length=8)}@example.test"
	user = frappe.get_doc(
		{
			"doctype": "User",
			"email": email,
			"first_name": prefix,
			"send_welcome_email": 0,
		}
	).insert(ignore_permissions=True)
	if grant_desk_access:
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


class TestOwnerSubscription(FrappeTestCase):
	def tearDown(self):
		frappe.set_user("Administrator")

	def test_restaurant_limit_snapshotted_from_plan_on_create(self):
		plan = make_plan(3)
		owner = make_user()

		sub = frappe.get_doc(
			{
				"doctype": "Owner Subscription",
				"owner_user": owner.name,
				"plan": plan.name,
			}
		).insert(ignore_permissions=True)

		self.assertEqual(sub.restaurant_limit, 3)

	def test_admin_override_survives_unrelated_edits(self):
		"""Snapshot-on-create doesn't mean 'always synced to the plan' -- a platform
		admin's manual override for one owner must stick until the plan link itself
		changes again."""
		plan = make_plan(3)
		owner = make_user()
		sub = frappe.get_doc(
			{
				"doctype": "Owner Subscription",
				"owner_user": owner.name,
				"plan": plan.name,
			}
		).insert(ignore_permissions=True)

		sub.restaurant_limit = 10
		sub.save(ignore_permissions=True)
		self.assertEqual(sub.restaurant_limit, 10)

		# unrelated field edit -- override must survive
		sub.status = "Suspended"
		sub.save(ignore_permissions=True)
		self.assertEqual(sub.restaurant_limit, 10)

		# re-pointing to a (different) plan re-snapshots the limit
		other_plan = make_plan(7)
		sub.plan = other_plan.name
		sub.status = "Active"
		sub.save(ignore_permissions=True)
		self.assertEqual(sub.restaurant_limit, 7)

	def test_duplicate_active_subscription_rejected(self):
		plan = make_plan(3)
		owner = make_user()

		frappe.get_doc(
			{"doctype": "Owner Subscription", "owner_user": owner.name, "plan": plan.name}
		).insert(ignore_permissions=True)

		with self.assertRaises(frappe.ValidationError):
			frappe.get_doc(
				{"doctype": "Owner Subscription", "owner_user": owner.name, "plan": plan.name}
			).insert(ignore_permissions=True)

	def test_second_subscription_allowed_once_first_is_cancelled(self):
		plan = make_plan(3)
		owner = make_user()

		first = frappe.get_doc(
			{"doctype": "Owner Subscription", "owner_user": owner.name, "plan": plan.name}
		).insert(ignore_permissions=True)
		first.status = "Cancelled"
		first.save(ignore_permissions=True)

		second = frappe.get_doc(
			{"doctype": "Owner Subscription", "owner_user": owner.name, "plan": plan.name}
		).insert(ignore_permissions=True)
		self.assertTrue(second.name)

	def test_owner_must_be_system_user(self):
		plan = make_plan(3)
		website_user = make_user(grant_desk_access=False)

		with self.assertRaises(frappe.ValidationError):
			frappe.get_doc(
				{
					"doctype": "Owner Subscription",
					"owner_user": website_user.name,
					"plan": plan.name,
				}
			).insert(ignore_permissions=True)
