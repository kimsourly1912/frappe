# Copyright (c) 2026, E-menu and Contributors
# See license.txt

import frappe
from frappe.tests.utils import FrappeTestCase

from e_menu.e_menu.doctype.menu_category.test_menu_category import make_category
from e_menu.e_menu.doctype.menu_item.test_menu_item import make_item
from e_menu.e_menu.doctype.order.order import submit_order
from e_menu.e_menu.doctype.restaurant_table.test_restaurant_table import make_table
from e_menu.e_menu.testing import add_member, make_owner, make_restaurant_for_owner, make_staff_user


def setup_restaurant_with_menu_and_table():
	owner = make_owner()
	restaurant = make_restaurant_for_owner(owner.name)
	category = make_category(restaurant.name, "Food", as_user=owner.name)
	item = make_item(restaurant.name, category.name, "Fried Rice", 3.5, as_user=owner.name)
	table = make_table(restaurant.name, "T01", as_user=owner.name)
	return owner, restaurant, category, item, table


def place_order(restaurant, table, item, qty=1, payment_method="MANUAL"):
	frappe.set_user("Guest")
	try:
		result = submit_order(
			restaurant.public_id,
			table.qr_token,
			[{"menu_item": item.name, "quantity": qty}],
			payment_method=payment_method,
		)
	finally:
		frappe.set_user("Administrator")
	return frappe.get_doc("Order", result["order"])


class TestOrderSubmission(FrappeTestCase):
	def tearDown(self):
		frappe.set_user("Administrator")

	def test_customer_can_submit_order(self):
		owner, restaurant, category, item, table = setup_restaurant_with_menu_and_table()
		order = place_order(restaurant, table, item, qty=2)

		self.assertEqual(order.status, "PENDING")
		self.assertEqual(order.restaurant, restaurant.name)
		self.assertEqual(order.table, table.name)
		self.assertEqual(len(order.items), 1)
		self.assertEqual(order.items[0].item_name_snapshot, "Fried Rice")
		self.assertEqual(float(order.items[0].unit_price_snapshot), 3.5)
		self.assertEqual(float(order.items[0].line_total), 7.0)
		self.assertEqual(float(order.subtotal), 7.0)
		self.assertEqual(float(order.total), 7.0)

	def test_order_ignores_client_supplied_price(self):
		"""Never trust client totals -- the server recomputes from the authoritative
		Menu Item price no matter what the request claims."""
		owner, restaurant, category, item, table = setup_restaurant_with_menu_and_table()
		frappe.set_user("Guest")
		try:
			result = submit_order(
				restaurant.public_id,
				table.qr_token,
				[{"menu_item": item.name, "quantity": 1, "price": 0.01, "unit_price_snapshot": 0.01}],
			)
		finally:
			frappe.set_user("Administrator")
		order = frappe.get_doc("Order", result["order"])
		self.assertEqual(float(order.total), 3.5)

	def test_cannot_submit_order_with_unavailable_item(self):
		owner, restaurant, category, item, table = setup_restaurant_with_menu_and_table()
		frappe.db.set_value("Menu Item", item.name, "is_available", 0)

		with self.assertRaises(frappe.ValidationError):
			place_order(restaurant, table, item)

	def test_cannot_submit_order_with_cross_restaurant_menu_item(self):
		owner_a, restaurant_a, category_a, item_a, table_a = setup_restaurant_with_menu_and_table()
		owner_b, restaurant_b, category_b, item_b, table_b = setup_restaurant_with_menu_and_table()

		with self.assertRaises(frappe.ValidationError):
			place_order(restaurant_a, table_a, item_b)

	def test_cannot_submit_order_with_invalid_qr(self):
		owner, restaurant, category, item, table = setup_restaurant_with_menu_and_table()
		frappe.set_user("Guest")
		try:
			with self.assertRaises(frappe.DoesNotExistError):
				submit_order(restaurant.public_id, "not-a-real-token", [{"menu_item": item.name, "quantity": 1}])
		finally:
			frappe.set_user("Administrator")

	def test_empty_cart_rejected(self):
		owner, restaurant, category, item, table = setup_restaurant_with_menu_and_table()
		frappe.set_user("Guest")
		try:
			with self.assertRaises(frappe.ValidationError):
				submit_order(restaurant.public_id, table.qr_token, [])
		finally:
			frappe.set_user("Administrator")

	def test_quantity_must_be_at_least_one(self):
		owner, restaurant, category, item, table = setup_restaurant_with_menu_and_table()
		with self.assertRaises(frappe.ValidationError):
			place_order(restaurant, table, item, qty=0)

	def test_invalid_payment_method_rejected(self):
		owner, restaurant, category, item, table = setup_restaurant_with_menu_and_table()
		with self.assertRaises(frappe.ValidationError):
			place_order(restaurant, table, item, payment_method="CRYPTO")


class TestOrderLifecycle(FrappeTestCase):
	def tearDown(self):
		frappe.set_user("Administrator")

	def _staff(self, restaurant, owner, role):
		user = make_staff_user(role.lower())
		add_member(restaurant.name, user.name, role, as_user=owner.name)
		return user

	def test_owner_can_accept_order(self):
		owner, restaurant, category, item, table = setup_restaurant_with_menu_and_table()
		order = place_order(restaurant, table, item)

		frappe.set_user(owner.name)
		try:
			order.accept()
		finally:
			frappe.set_user("Administrator")
		self.assertEqual(frappe.db.get_value("Order", order.name, "status"), "ACCEPTED")

	def test_cannot_accept_already_accepted_order(self):
		owner, restaurant, category, item, table = setup_restaurant_with_menu_and_table()
		order = place_order(restaurant, table, item)
		frappe.set_user(owner.name)
		try:
			order.accept()
			with self.assertRaises(frappe.ValidationError):
				order.accept()
		finally:
			frappe.set_user("Administrator")

	def test_kitchen_can_start_preparing_and_mark_ready_but_not_accept(self):
		owner, restaurant, category, item, table = setup_restaurant_with_menu_and_table()
		kitchen = self._staff(restaurant, owner, "KITCHEN")
		order = place_order(restaurant, table, item)

		frappe.set_user(kitchen.name)
		try:
			with self.assertRaises(frappe.PermissionError):
				order.accept()
		finally:
			frappe.set_user("Administrator")

		frappe.set_user(owner.name)
		try:
			order.accept()
		finally:
			frappe.set_user("Administrator")

		frappe.set_user(kitchen.name)
		try:
			order.start_preparing()
			order.mark_ready()
		finally:
			frappe.set_user("Administrator")
		self.assertEqual(frappe.db.get_value("Order", order.name, "status"), "READY")

	def test_cashier_cannot_start_preparing(self):
		owner, restaurant, category, item, table = setup_restaurant_with_menu_and_table()
		cashier = self._staff(restaurant, owner, "CASHIER")
		order = place_order(restaurant, table, item)

		frappe.set_user(owner.name)
		try:
			order.accept()
		finally:
			frappe.set_user("Administrator")

		frappe.set_user(cashier.name)
		try:
			with self.assertRaises(frappe.PermissionError):
				order.start_preparing()
		finally:
			frappe.set_user("Administrator")

	def test_full_happy_path(self):
		owner, restaurant, category, item, table = setup_restaurant_with_menu_and_table()
		kitchen = self._staff(restaurant, owner, "KITCHEN")
		cashier = self._staff(restaurant, owner, "CASHIER")
		order = place_order(restaurant, table, item)

		frappe.set_user(cashier.name)
		try:
			order.accept()
		finally:
			frappe.set_user("Administrator")

		frappe.set_user(kitchen.name)
		try:
			order.start_preparing()
			order.mark_ready()
		finally:
			frappe.set_user("Administrator")

		frappe.set_user(cashier.name)
		try:
			order.mark_served()
			order.complete()
		finally:
			frappe.set_user("Administrator")

		self.assertEqual(frappe.db.get_value("Order", order.name, "status"), "COMPLETED")

	def test_reject_only_from_pending(self):
		owner, restaurant, category, item, table = setup_restaurant_with_menu_and_table()
		order = place_order(restaurant, table, item)
		frappe.set_user(owner.name)
		try:
			order.accept()
			with self.assertRaises(frappe.ValidationError):
				order.reject()
		finally:
			frappe.set_user("Administrator")

	def test_cancel_allowed_from_pending_accepted_preparing(self):
		owner, restaurant, category, item, table = setup_restaurant_with_menu_and_table()

		order = place_order(restaurant, table, item)
		frappe.set_user(owner.name)
		try:
			order.cancel()
		finally:
			frappe.set_user("Administrator")
		self.assertEqual(frappe.db.get_value("Order", order.name, "status"), "CANCELLED")

	def test_cannot_cancel_from_ready_or_served(self):
		owner, restaurant, category, item, table = setup_restaurant_with_menu_and_table()
		order = place_order(restaurant, table, item)
		frappe.set_user(owner.name)
		try:
			order.accept()
			order.start_preparing()
			order.mark_ready()
			with self.assertRaises(frappe.ValidationError):
				order.cancel()
		finally:
			frappe.set_user("Administrator")

	def test_cannot_change_status_directly_via_save(self):
		owner, restaurant, category, item, table = setup_restaurant_with_menu_and_table()
		order = place_order(restaurant, table, item)
		order.status = "COMPLETED"
		with self.assertRaises(frappe.ValidationError):
			order.save(ignore_permissions=True)

	def test_staff_of_other_restaurant_cannot_read_or_transition_order(self):
		"""Tenant isolation for orders, mirroring every other restaurant-scoped
		DocType's acceptance test."""
		owner_a, restaurant_a, category_a, item_a, table_a = setup_restaurant_with_menu_and_table()
		order_a = place_order(restaurant_a, table_a, item_a)

		owner_b, restaurant_b, category_b, item_b, table_b = setup_restaurant_with_menu_and_table()

		frappe.set_user(owner_b.name)
		try:
			visible = frappe.get_list("Order", pluck="name")
			self.assertNotIn(order_a.name, visible)
			with self.assertRaises(frappe.PermissionError):
				frappe.get_doc("Order", order_a.name).check_permission("read")
			with self.assertRaises(frappe.PermissionError):
				order_a.accept()
		finally:
			frappe.set_user("Administrator")

	def test_platform_admin_can_transition_any_order(self):
		owner, restaurant, category, item, table = setup_restaurant_with_menu_and_table()
		order = place_order(restaurant, table, item)
		# Administrator, not restaurant staff at all.
		order.accept()
		self.assertEqual(frappe.db.get_value("Order", order.name, "status"), "ACCEPTED")
