# Copyright (c) 2026, E-menu and Contributors
# See license.txt

import frappe
from frappe.tests.utils import FrappeTestCase

from e_menu.e_menu.testing import add_member, make_owner, make_restaurant_for_owner, make_staff_user


def make_category(restaurant, category_name, *, as_user=None):
	frappe.set_user(as_user or frappe.session.user)
	try:
		return frappe.get_doc(
			{
				"doctype": "Menu Category",
				"restaurant": restaurant,
				"category_name": category_name,
			}
		).insert()
	finally:
		frappe.set_user("Administrator")


class TestMenuCategory(FrappeTestCase):
	def tearDown(self):
		frappe.set_user("Administrator")

	def test_owner_can_create_category(self):
		owner = make_owner()
		restaurant = make_restaurant_for_owner(owner.name)
		category = make_category(restaurant.name, "Drinks", as_user=owner.name)
		self.assertEqual(category.restaurant, restaurant.name)

	def test_manager_can_create_category(self):
		owner = make_owner()
		restaurant = make_restaurant_for_owner(owner.name)
		manager = make_staff_user("manager")
		add_member(restaurant.name, manager.name, "MANAGER", as_user=owner.name)

		category = make_category(restaurant.name, "Food", as_user=manager.name)
		self.assertEqual(category.category_name, "Food")

	def test_cashier_cannot_create_category(self):
		owner = make_owner()
		restaurant = make_restaurant_for_owner(owner.name)
		cashier = make_staff_user("cashier")
		add_member(restaurant.name, cashier.name, "CASHIER", as_user=owner.name)

		with self.assertRaises(frappe.PermissionError):
			make_category(restaurant.name, "Should Not Exist", as_user=cashier.name)

	def test_kitchen_cannot_create_category(self):
		owner = make_owner()
		restaurant = make_restaurant_for_owner(owner.name)
		kitchen = make_staff_user("kitchen")
		add_member(restaurant.name, kitchen.name, "KITCHEN", as_user=owner.name)

		with self.assertRaises(frappe.PermissionError):
			make_category(restaurant.name, "Should Not Exist", as_user=kitchen.name)

	def test_category_name_unique_per_restaurant(self):
		owner = make_owner()
		restaurant = make_restaurant_for_owner(owner.name)
		make_category(restaurant.name, "Drinks", as_user=owner.name)

		with self.assertRaises(frappe.ValidationError):
			make_category(restaurant.name, "Drinks", as_user=owner.name)

	def test_category_name_can_repeat_across_restaurants(self):
		owner_a = make_owner()
		restaurant_a = make_restaurant_for_owner(owner_a.name)
		owner_b = make_owner()
		restaurant_b = make_restaurant_for_owner(owner_b.name)

		category_a = make_category(restaurant_a.name, "Drinks", as_user=owner_a.name)
		category_b = make_category(restaurant_b.name, "Drinks", as_user=owner_b.name)
		self.assertNotEqual(category_a.name, category_b.name)

	def test_staff_of_other_restaurant_cannot_read_category(self):
		owner_a = make_owner()
		restaurant_a = make_restaurant_for_owner(owner_a.name)
		category_a = make_category(restaurant_a.name, "Drinks", as_user=owner_a.name)

		owner_b = make_owner()
		restaurant_b = make_restaurant_for_owner(owner_b.name)

		frappe.set_user(owner_b.name)
		try:
			visible = frappe.get_list("Menu Category", pluck="name")
			self.assertNotIn(category_a.name, visible)
			with self.assertRaises(frappe.PermissionError):
				frappe.get_doc("Menu Category", category_a.name).check_permission("read")
		finally:
			frappe.set_user("Administrator")

	def test_platform_admin_can_manage_any_category(self):
		owner = make_owner()
		restaurant = make_restaurant_for_owner(owner.name)
		# Administrator (System Manager) acting without being restaurant staff.
		category = make_category(restaurant.name, "Admin Created")
		self.assertTrue(category.name)
