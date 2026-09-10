# Copyright (c) 2026, E-menu and Contributors
# See license.txt

import frappe
from frappe.tests.utils import FrappeTestCase

from e_menu.e_menu.doctype.menu_category.test_menu_category import make_category
from e_menu.e_menu.testing import add_member, make_owner, make_restaurant_for_owner, make_staff_user


def make_item(restaurant, category, item_name, price=3.5, *, as_user=None):
	frappe.set_user(as_user or frappe.session.user)
	try:
		return frappe.get_doc(
			{
				"doctype": "Menu Item",
				"restaurant": restaurant,
				"category": category,
				"item_name": item_name,
				"price": price,
			}
		).insert()
	finally:
		frappe.set_user("Administrator")


class TestMenuItem(FrappeTestCase):
	def tearDown(self):
		frappe.set_user("Administrator")

	def test_owner_can_create_menu_item(self):
		owner = make_owner()
		restaurant = make_restaurant_for_owner(owner.name)
		category = make_category(restaurant.name, "Food", as_user=owner.name)

		item = make_item(restaurant.name, category.name, "Fried Rice", 3.5, as_user=owner.name)
		self.assertEqual(item.item_name, "Fried Rice")
		self.assertEqual(item.is_available, 1)

	def test_manager_can_create_menu_item(self):
		owner = make_owner()
		restaurant = make_restaurant_for_owner(owner.name)
		category = make_category(restaurant.name, "Drinks", as_user=owner.name)
		manager = make_staff_user("manager")
		add_member(restaurant.name, manager.name, "MANAGER", as_user=owner.name)

		item = make_item(restaurant.name, category.name, "Iced Coffee", 1.5, as_user=manager.name)
		self.assertEqual(item.item_name, "Iced Coffee")

	def test_cashier_cannot_create_menu_item(self):
		owner = make_owner()
		restaurant = make_restaurant_for_owner(owner.name)
		category = make_category(restaurant.name, "Food", as_user=owner.name)
		cashier = make_staff_user("cashier")
		add_member(restaurant.name, cashier.name, "CASHIER", as_user=owner.name)

		with self.assertRaises(frappe.PermissionError):
			make_item(restaurant.name, category.name, "Should Not Exist", 1, as_user=cashier.name)

	def test_kitchen_cannot_update_menu_item(self):
		owner = make_owner()
		restaurant = make_restaurant_for_owner(owner.name)
		category = make_category(restaurant.name, "Food", as_user=owner.name)
		kitchen = make_staff_user("kitchen")
		add_member(restaurant.name, kitchen.name, "KITCHEN", as_user=owner.name)
		item = make_item(restaurant.name, category.name, "Fried Rice", 3.5, as_user=owner.name)

		frappe.set_user(kitchen.name)
		try:
			doc = frappe.get_doc("Menu Item", item.name)  # read is allowed
			doc.is_available = 0
			with self.assertRaises(frappe.PermissionError):
				doc.save()
		finally:
			frappe.set_user("Administrator")

	def test_menu_item_cannot_reference_other_restaurants_category(self):
		"""Core Slice 3 acceptance: a Menu Item belonging to Restaurant A can never
		reference a Menu Category from Restaurant B."""
		owner_a = make_owner()
		restaurant_a = make_restaurant_for_owner(owner_a.name)
		owner_b = make_owner()
		restaurant_b = make_restaurant_for_owner(owner_b.name)
		category_b = make_category(restaurant_b.name, "Drinks", as_user=owner_b.name)

		with self.assertRaises(frappe.ValidationError):
			make_item(restaurant_a.name, category_b.name, "Cross Restaurant Item", 1, as_user="Administrator")

	def test_menu_item_price_must_be_non_negative(self):
		owner = make_owner()
		restaurant = make_restaurant_for_owner(owner.name)
		category = make_category(restaurant.name, "Food", as_user=owner.name)

		with self.assertRaises(frappe.ValidationError):
			make_item(restaurant.name, category.name, "Negative Price", -1, as_user=owner.name)

	def test_staff_of_other_restaurant_cannot_read_menu_item(self):
		owner_a = make_owner()
		restaurant_a = make_restaurant_for_owner(owner_a.name)
		category_a = make_category(restaurant_a.name, "Food", as_user=owner_a.name)
		item_a = make_item(restaurant_a.name, category_a.name, "Fried Rice", 3.5, as_user=owner_a.name)

		owner_b = make_owner()
		restaurant_b = make_restaurant_for_owner(owner_b.name)

		frappe.set_user(owner_b.name)
		try:
			visible = frappe.get_list("Menu Item", pluck="name")
			self.assertNotIn(item_a.name, visible)
			with self.assertRaises(frappe.PermissionError):
				frappe.get_doc("Menu Item", item_a.name).check_permission("read")
		finally:
			frappe.set_user("Administrator")
