# Copyright (c) 2026, E-menu and Contributors
# See license.txt

import frappe
from frappe.tests.utils import FrappeTestCase

from e_menu.e_menu.doctype.menu_category.test_menu_category import make_category
from e_menu.e_menu.doctype.menu_item.test_menu_item import make_item
from e_menu.e_menu.doctype.restaurant_table.test_restaurant_table import make_table
from e_menu.e_menu.testing import make_owner, make_restaurant_for_owner
from e_menu.www.menu import get_available_menu, get_context


class TestPublicMenuPage(FrappeTestCase):
	def tearDown(self):
		frappe.set_user("Administrator")
		frappe.local.form_dict.clear()

	def _setup_restaurant_with_menu(self):
		owner = make_owner()
		restaurant = make_restaurant_for_owner(owner.name)
		active_category = make_category(restaurant.name, "Food", as_user=owner.name)
		empty_category = make_category(restaurant.name, "Empty Category", as_user=owner.name)
		inactive_category = make_category(restaurant.name, "Old Category", as_user=owner.name)
		frappe.db.set_value("Menu Category", inactive_category.name, "is_active", 0)

		make_item(restaurant.name, active_category.name, "Fried Rice", 3.5, as_user=owner.name)
		unavailable_item = make_item(
			restaurant.name, active_category.name, "Out of Stock", 5, as_user=owner.name
		)
		unavailable_item.is_available = 0
		frappe.set_user(owner.name)
		try:
			unavailable_item.save()
		finally:
			frappe.set_user("Administrator")

		return owner, restaurant, active_category, empty_category

	def test_get_available_menu_shape(self):
		owner, restaurant, active_category, empty_category = self._setup_restaurant_with_menu()

		menu = get_available_menu(restaurant.name)

		category_names = [c.category_name for c in menu]
		self.assertIn("Food", category_names)
		# empty and inactive categories are excluded entirely
		self.assertNotIn("Empty Category", category_names)
		self.assertNotIn("Old Category", category_names)

		food = next(c for c in menu if c.category_name == "Food")
		item_names = [i.item_name for i in food.menu_items]
		self.assertIn("Fried Rice", item_names)
		# unavailable items are excluded
		self.assertNotIn("Out of Stock", item_names)

	def test_get_context_resolves_valid_qr(self):
		owner = make_owner()
		restaurant = make_restaurant_for_owner(owner.name)
		table = make_table(restaurant.name, "T01", as_user=owner.name)
		make_category(restaurant.name, "Food", as_user=owner.name)

		frappe.set_user("Guest")
		frappe.local.form_dict.public_id = restaurant.public_id
		frappe.local.form_dict.table_token = table.qr_token
		try:
			context = get_context(frappe._dict())
		finally:
			frappe.set_user("Administrator")

		self.assertTrue(context.is_valid)
		self.assertEqual(context.restaurant, restaurant.name)
		self.assertEqual(context.table, table.name)
		self.assertEqual(context.table_name, "T01")

	def test_get_context_fails_safely_for_invalid_token(self):
		owner = make_owner()
		restaurant = make_restaurant_for_owner(owner.name)
		make_table(restaurant.name, "T01", as_user=owner.name)

		frappe.set_user("Guest")
		frappe.local.form_dict.public_id = restaurant.public_id
		frappe.local.form_dict.table_token = "not-a-real-token"
		try:
			context = get_context(frappe._dict())
		finally:
			frappe.set_user("Administrator")

		self.assertFalse(context.is_valid)
		self.assertEqual(context.http_status_code, 404)
		# never leaks category/item data for an unresolved table
		self.assertNotIn("categories", context)

	def test_get_context_fails_safely_for_deactivated_table(self):
		owner = make_owner()
		restaurant = make_restaurant_for_owner(owner.name)
		table = make_table(restaurant.name, "T01", as_user=owner.name)
		frappe.db.set_value("Restaurant Table", table.name, "status", "Inactive")

		frappe.set_user("Guest")
		frappe.local.form_dict.public_id = restaurant.public_id
		frappe.local.form_dict.table_token = table.qr_token
		try:
			context = get_context(frappe._dict())
		finally:
			frappe.set_user("Administrator")

		self.assertFalse(context.is_valid)
		self.assertEqual(context.http_status_code, 404)
