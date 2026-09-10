# Copyright (c) 2026, E-menu and Contributors
# See license.txt

import frappe
from frappe.tests.utils import FrappeTestCase

from e_menu.e_menu.doctype.restaurant_table.restaurant_table import resolve_qr
from e_menu.e_menu.testing import add_member, make_owner, make_restaurant_for_owner, make_staff_user


def make_table(restaurant, table_name, *, as_user=None):
	frappe.set_user(as_user or frappe.session.user)
	try:
		return frappe.get_doc(
			{
				"doctype": "Restaurant Table",
				"restaurant": restaurant,
				"table_name": table_name,
			}
		).insert()
	finally:
		frappe.set_user("Administrator")


class TestRestaurantTable(FrappeTestCase):
	def tearDown(self):
		frappe.set_user("Administrator")

	def test_owner_can_create_table(self):
		owner = make_owner()
		restaurant = make_restaurant_for_owner(owner.name)
		table = make_table(restaurant.name, "T01", as_user=owner.name)
		self.assertEqual(table.restaurant, restaurant.name)
		self.assertEqual(table.status, "Active")

	def test_manager_can_create_table(self):
		owner = make_owner()
		restaurant = make_restaurant_for_owner(owner.name)
		manager = make_staff_user("manager")
		add_member(restaurant.name, manager.name, "MANAGER", as_user=owner.name)
		table = make_table(restaurant.name, "T01", as_user=manager.name)
		self.assertTrue(table.name)

	def test_cashier_cannot_create_table(self):
		owner = make_owner()
		restaurant = make_restaurant_for_owner(owner.name)
		cashier = make_staff_user("cashier")
		add_member(restaurant.name, cashier.name, "CASHIER", as_user=owner.name)
		with self.assertRaises(frappe.PermissionError):
			make_table(restaurant.name, "T01", as_user=cashier.name)

	def test_kitchen_cannot_create_table(self):
		owner = make_owner()
		restaurant = make_restaurant_for_owner(owner.name)
		kitchen = make_staff_user("kitchen")
		add_member(restaurant.name, kitchen.name, "KITCHEN", as_user=owner.name)
		with self.assertRaises(frappe.PermissionError):
			make_table(restaurant.name, "T01", as_user=kitchen.name)

	def test_table_name_unique_per_restaurant(self):
		owner = make_owner()
		restaurant = make_restaurant_for_owner(owner.name)
		make_table(restaurant.name, "T01", as_user=owner.name)
		with self.assertRaises(frappe.ValidationError):
			make_table(restaurant.name, "T01", as_user=owner.name)

	def test_table_name_can_repeat_across_restaurants(self):
		owner_a = make_owner()
		restaurant_a = make_restaurant_for_owner(owner_a.name)
		owner_b = make_owner()
		restaurant_b = make_restaurant_for_owner(owner_b.name)
		table_a = make_table(restaurant_a.name, "T01", as_user=owner_a.name)
		table_b = make_table(restaurant_b.name, "T01", as_user=owner_b.name)
		self.assertNotEqual(table_a.name, table_b.name)

	def test_qr_token_is_secure_and_unique(self):
		owner = make_owner()
		restaurant = make_restaurant_for_owner(owner.name)
		table_1 = make_table(restaurant.name, "T01", as_user=owner.name)
		table_2 = make_table(restaurant.name, "T02", as_user=owner.name)

		self.assertEqual(len(table_1.qr_token), 24)
		self.assertNotEqual(table_1.qr_token, table_2.qr_token)
		# not the internal document name
		self.assertNotEqual(table_1.qr_token, table_1.name)

	def test_qr_code_and_menu_url_generated(self):
		owner = make_owner()
		restaurant = make_restaurant_for_owner(owner.name)
		table = make_table(restaurant.name, "T01", as_user=owner.name)
		table.reload()

		self.assertTrue(table.qr_code)
		self.assertTrue(table.menu_url)
		self.assertIn(f"/menu/{restaurant.public_id}/{table.qr_token}", table.menu_url)
		self.assertTrue(frappe.db.exists("File", {"file_url": table.qr_code, "attached_to_name": table.name}))

	def test_staff_of_other_restaurant_cannot_read_table(self):
		owner_a = make_owner()
		restaurant_a = make_restaurant_for_owner(owner_a.name)
		table_a = make_table(restaurant_a.name, "T01", as_user=owner_a.name)

		owner_b = make_owner()
		make_restaurant_for_owner(owner_b.name)

		frappe.set_user(owner_b.name)
		try:
			visible = frappe.get_list("Restaurant Table", pluck="name")
			self.assertNotIn(table_a.name, visible)
			with self.assertRaises(frappe.PermissionError):
				frappe.get_doc("Restaurant Table", table_a.name).check_permission("read")
		finally:
			frappe.set_user("Administrator")

	def test_resolve_qr_succeeds_for_active_restaurant_and_table(self):
		"""Core Slice 4 acceptance: scanning a QR resolves exactly one active
		Restaurant + Table."""
		owner = make_owner()
		restaurant = make_restaurant_for_owner(owner.name)
		table = make_table(restaurant.name, "T01", as_user=owner.name)

		frappe.set_user("Guest")
		try:
			result = resolve_qr(restaurant.public_id, table.qr_token)
		finally:
			frappe.set_user("Administrator")

		self.assertEqual(result["restaurant"], restaurant.name)
		self.assertEqual(result["table"], table.name)

	def test_resolve_qr_fails_for_wrong_token(self):
		owner = make_owner()
		restaurant = make_restaurant_for_owner(owner.name)
		make_table(restaurant.name, "T01", as_user=owner.name)

		frappe.set_user("Guest")
		try:
			with self.assertRaises(frappe.DoesNotExistError):
				resolve_qr(restaurant.public_id, "not-a-real-token")
		finally:
			frappe.set_user("Administrator")

	def test_resolve_qr_fails_for_unknown_public_id(self):
		owner = make_owner()
		restaurant = make_restaurant_for_owner(owner.name)
		table = make_table(restaurant.name, "T01", as_user=owner.name)

		frappe.set_user("Guest")
		try:
			with self.assertRaises(frappe.DoesNotExistError):
				resolve_qr("not-a-real-public-id", table.qr_token)
		finally:
			frappe.set_user("Administrator")

	def test_resolve_qr_fails_for_inactive_table(self):
		"""Invalid/deactivated tokens fail safely (Slice 4 acceptance)."""
		owner = make_owner()
		restaurant = make_restaurant_for_owner(owner.name)
		table = make_table(restaurant.name, "T01", as_user=owner.name)

		frappe.set_user(owner.name)
		try:
			table.status = "Inactive"
			table.save()
		finally:
			frappe.set_user("Administrator")

		frappe.set_user("Guest")
		try:
			with self.assertRaises(frappe.DoesNotExistError):
				resolve_qr(restaurant.public_id, table.qr_token)
		finally:
			frappe.set_user("Administrator")

	def test_resolve_qr_fails_for_inactive_restaurant(self):
		owner = make_owner()
		restaurant = make_restaurant_for_owner(owner.name)
		table = make_table(restaurant.name, "T01", as_user=owner.name)
		frappe.db.set_value("Restaurant", restaurant.name, "status", "Inactive")

		frappe.set_user("Guest")
		try:
			with self.assertRaises(frappe.DoesNotExistError):
				resolve_qr(restaurant.public_id, table.qr_token)
		finally:
			frappe.set_user("Administrator")

	def test_resolve_qr_fails_for_table_from_different_restaurant(self):
		"""A table's qr_token must match its own restaurant's public_id -- can't mix
		and match a valid token with a different (even valid) restaurant."""
		owner_a = make_owner()
		restaurant_a = make_restaurant_for_owner(owner_a.name)
		owner_b = make_owner()
		restaurant_b = make_restaurant_for_owner(owner_b.name)
		table_b = make_table(restaurant_b.name, "T01", as_user=owner_b.name)

		frappe.set_user("Guest")
		try:
			with self.assertRaises(frappe.DoesNotExistError):
				resolve_qr(restaurant_a.public_id, table_b.qr_token)
		finally:
			frappe.set_user("Administrator")
