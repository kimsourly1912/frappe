# Copyright (c) 2026, E-menu and Contributors
# See license.txt

import frappe
from frappe.tests.utils import FrappeTestCase

from e_menu.e_menu.doctype.restaurant_member.restaurant_member import invite_staff
from e_menu.e_menu.testing import add_member, make_owner, make_restaurant_for_owner, make_staff_user


class TestRestaurantMember(FrappeTestCase):
	def tearDown(self):
		frappe.set_user("Administrator")

	def test_creating_restaurant_auto_creates_owner_membership(self):
		owner = make_owner()
		restaurant = make_restaurant_for_owner(owner.name)

		member = frappe.get_doc(
			"Restaurant Member", {"restaurant": restaurant.name, "user": owner.name}
		)
		self.assertEqual(member.role, "OWNER")
		self.assertEqual(member.status, "Active")

	def test_owner_gets_restaurant_staff_role_automatically(self):
		owner = make_owner()
		make_restaurant_for_owner(owner.name)
		self.assertIn("Restaurant Staff", frappe.get_roles(owner.name))

	def test_owner_can_invite_staff_via_api(self):
		owner = make_owner()
		restaurant = make_restaurant_for_owner(owner.name)

		frappe.set_user(owner.name)
		try:
			result = invite_staff(restaurant.name, "new-cashier@example.test", "CASHIER")
		finally:
			frappe.set_user("Administrator")

		self.assertEqual(result["role"], "CASHIER")
		self.assertTrue(frappe.db.exists("User", "new-cashier@example.test"))
		self.assertIn("Restaurant Staff", frappe.get_roles("new-cashier@example.test"))

	def test_manager_can_invite_staff(self):
		owner = make_owner()
		restaurant = make_restaurant_for_owner(owner.name)
		manager = make_staff_user("manager")
		add_member(restaurant.name, manager.name, "MANAGER", as_user=owner.name)

		frappe.set_user(manager.name)
		try:
			result = invite_staff(restaurant.name, "hired-by-manager@example.test", "KITCHEN")
		finally:
			frappe.set_user("Administrator")
		self.assertEqual(result["role"], "KITCHEN")

	def test_cashier_cannot_invite_staff(self):
		owner = make_owner()
		restaurant = make_restaurant_for_owner(owner.name)
		cashier = make_staff_user("cashier")
		add_member(restaurant.name, cashier.name, "CASHIER", as_user=owner.name)

		frappe.set_user(cashier.name)
		try:
			with self.assertRaises(frappe.PermissionError):
				invite_staff(restaurant.name, "should-not-exist@example.test", "KITCHEN")
		finally:
			frappe.set_user("Administrator")
		self.assertFalse(frappe.db.exists("User", "should-not-exist@example.test"))

	def test_kitchen_cannot_invite_staff(self):
		owner = make_owner()
		restaurant = make_restaurant_for_owner(owner.name)
		kitchen = make_staff_user("kitchen")
		add_member(restaurant.name, kitchen.name, "KITCHEN", as_user=owner.name)

		frappe.set_user(kitchen.name)
		try:
			with self.assertRaises(frappe.PermissionError):
				invite_staff(restaurant.name, "should-not-exist-2@example.test", "CASHIER")
		finally:
			frappe.set_user("Administrator")

	def test_non_member_cannot_invite_staff(self):
		owner_a = make_owner()
		restaurant_a = make_restaurant_for_owner(owner_a.name)
		owner_b = make_owner()  # owns a different restaurant, no relation to A

		frappe.set_user(owner_b.name)
		try:
			with self.assertRaises(frappe.PermissionError):
				invite_staff(restaurant_a.name, "outsider-invite@example.test", "CASHIER")
		finally:
			frappe.set_user("Administrator")

	def test_duplicate_membership_rejected(self):
		owner = make_owner()
		restaurant = make_restaurant_for_owner(owner.name)
		staff = make_staff_user()
		add_member(restaurant.name, staff.name, "CASHIER", as_user=owner.name)

		with self.assertRaises(frappe.ValidationError):
			add_member(restaurant.name, staff.name, "KITCHEN", as_user=owner.name)

	def test_cannot_disable_last_active_owner(self):
		owner = make_owner()
		restaurant = make_restaurant_for_owner(owner.name)
		owner_member = frappe.get_doc(
			"Restaurant Member", {"restaurant": restaurant.name, "user": owner.name}
		)

		frappe.set_user(owner.name)
		try:
			owner_member.status = "Disabled"
			with self.assertRaises(frappe.ValidationError):
				owner_member.save()
		finally:
			frappe.set_user("Administrator")

	def test_can_disable_an_owner_once_another_owner_exists(self):
		owner = make_owner()
		restaurant = make_restaurant_for_owner(owner.name)
		second_owner = make_staff_user("second-owner")
		add_member(restaurant.name, second_owner.name, "OWNER", as_user=owner.name)

		owner_member = frappe.get_doc(
			"Restaurant Member", {"restaurant": restaurant.name, "user": owner.name}
		)
		frappe.set_user(second_owner.name)
		try:
			owner_member.status = "Disabled"
			owner_member.save()
		finally:
			frappe.set_user("Administrator")
		self.assertEqual(frappe.db.get_value("Restaurant Member", owner_member.name, "status"), "Disabled")

	def test_staff_of_one_restaurant_cannot_access_another(self):
		"""Core Slice 2 acceptance: Restaurant A staff cannot access Restaurant B
		resources."""
		owner_a = make_owner()
		restaurant_a = make_restaurant_for_owner(owner_a.name)
		cashier_a = make_staff_user("cashier-a")
		add_member(restaurant_a.name, cashier_a.name, "CASHIER", as_user=owner_a.name)

		owner_b = make_owner()
		restaurant_b = make_restaurant_for_owner(owner_b.name)

		frappe.set_user(cashier_a.name)

		# cannot directly read restaurant B
		with self.assertRaises(frappe.PermissionError):
			frappe.get_doc("Restaurant", restaurant_b.name).check_permission("read")

		# restaurant B never appears in list views
		visible_restaurants = frappe.get_list("Restaurant", pluck="name")
		self.assertIn(restaurant_a.name, visible_restaurants)
		self.assertNotIn(restaurant_b.name, visible_restaurants)

		# restaurant B's staff roster never appears in list views
		visible_member_restaurants = set(frappe.get_list("Restaurant Member", pluck="restaurant"))
		self.assertEqual(visible_member_restaurants, {restaurant_a.name})

		# cannot invite staff into restaurant B
		with self.assertRaises(frappe.PermissionError):
			invite_staff(restaurant_b.name, "leak-attempt@example.test", "CASHIER")

	def test_manager_can_write_restaurant_but_cashier_cannot(self):
		owner = make_owner()
		restaurant = make_restaurant_for_owner(owner.name)
		manager = make_staff_user("manager")
		cashier = make_staff_user("cashier")
		add_member(restaurant.name, manager.name, "MANAGER", as_user=owner.name)
		add_member(restaurant.name, cashier.name, "CASHIER", as_user=owner.name)

		frappe.set_user(manager.name)
		doc = frappe.get_doc("Restaurant", restaurant.name)
		doc.restaurant_name = "Renamed By Manager"
		doc.save()
		self.assertEqual(
			frappe.db.get_value("Restaurant", restaurant.name, "restaurant_name"), "Renamed By Manager"
		)

		frappe.set_user(cashier.name)
		doc = frappe.get_doc("Restaurant", restaurant.name)  # read is allowed
		doc.restaurant_name = "Should Not Save"
		with self.assertRaises(frappe.PermissionError):
			doc.save()
