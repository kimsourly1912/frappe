# Copyright (c) 2026, E-menu and Contributors
# See license.txt

import frappe
from frappe.tests.utils import FrappeTestCase

from e_menu.e_menu.doctype.order.test_order import place_order, setup_restaurant_with_menu_and_table
from e_menu.e_menu.doctype.payment.payment import confirm_manual_payment
from e_menu.e_menu.testing import add_member, make_staff_user


class TestPaymentConfirmation(FrappeTestCase):
	def tearDown(self):
		frappe.set_user("Administrator")

	def _staff(self, restaurant, owner, role):
		user = make_staff_user(role.lower())
		add_member(restaurant.name, user.name, role, as_user=owner.name)
		return user

	def test_cashier_can_confirm_manual_payment(self):
		owner, restaurant, category, item, table = setup_restaurant_with_menu_and_table()
		cashier = self._staff(restaurant, owner, "CASHIER")
		order = place_order(restaurant, table, item, qty=2)

		frappe.set_user(cashier.name)
		try:
			result = confirm_manual_payment(order.name, "CASH")
		finally:
			frappe.set_user("Administrator")

		payment = frappe.get_doc("Payment", result["payment"])
		self.assertEqual(payment.status, "PAID")
		self.assertEqual(payment.provider, "MANUAL")
		self.assertEqual(payment.method, "CASH")
		self.assertEqual(payment.restaurant, restaurant.name)
		self.assertEqual(float(payment.amount), float(order.total))
		self.assertEqual(frappe.db.get_value("Order", order.name, "payment_status"), "Paid")

	def test_owner_can_confirm_manual_payment(self):
		owner, restaurant, category, item, table = setup_restaurant_with_menu_and_table()
		order = place_order(restaurant, table, item)

		frappe.set_user(owner.name)
		try:
			confirm_manual_payment(order.name, "CARD")
		finally:
			frappe.set_user("Administrator")
		self.assertEqual(frappe.db.get_value("Order", order.name, "payment_status"), "Paid")

	def test_kitchen_cannot_confirm_payment(self):
		owner, restaurant, category, item, table = setup_restaurant_with_menu_and_table()
		kitchen = self._staff(restaurant, owner, "KITCHEN")
		order = place_order(restaurant, table, item)

		frappe.set_user(kitchen.name)
		try:
			with self.assertRaises(frappe.PermissionError):
				confirm_manual_payment(order.name, "CASH")
		finally:
			frappe.set_user("Administrator")

	def test_cannot_confirm_payment_twice(self):
		owner, restaurant, category, item, table = setup_restaurant_with_menu_and_table()
		order = place_order(restaurant, table, item)

		frappe.set_user(owner.name)
		try:
			confirm_manual_payment(order.name, "CASH")
			with self.assertRaises(frappe.ValidationError):
				confirm_manual_payment(order.name, "CASH")
		finally:
			frappe.set_user("Administrator")

	def test_cannot_confirm_payment_for_cancelled_order(self):
		owner, restaurant, category, item, table = setup_restaurant_with_menu_and_table()
		order = place_order(restaurant, table, item)

		frappe.set_user(owner.name)
		try:
			order.cancel()
			with self.assertRaises(frappe.ValidationError):
				confirm_manual_payment(order.name, "CASH")
		finally:
			frappe.set_user("Administrator")

	def test_invalid_method_rejected(self):
		owner, restaurant, category, item, table = setup_restaurant_with_menu_and_table()
		order = place_order(restaurant, table, item)

		frappe.set_user(owner.name)
		try:
			with self.assertRaises(frappe.ValidationError):
				confirm_manual_payment(order.name, "BITCOIN")
		finally:
			frappe.set_user("Administrator")

	def test_amount_ignores_client_supplied_value(self):
		"""Never trust a client-supplied amount -- even a direct Payment.insert()
		(bypassing confirm_manual_payment entirely, and its own role check) gets its
		amount overwritten from the order's own total by
		Payment.link_and_validate_order, mirroring
		test_order_ignores_client_supplied_price. ignore_permissions=True here
		isolates that from the separate question of who's allowed to create a
		Payment at all (base DocType permissions withhold "create" from Restaurant
		Staff entirely -- confirm_manual_payment is the only sanctioned path)."""
		owner, restaurant, category, item, table = setup_restaurant_with_menu_and_table()
		order = place_order(restaurant, table, item)

		payment = frappe.get_doc(
			{
				"doctype": "Payment",
				"order": order.name,
				"provider": "MANUAL",
				"method": "CASH",
				"amount": 0.01,
				"status": "PAID",
			}
		).insert(ignore_permissions=True)
		self.assertEqual(float(payment.amount), float(order.total))

	def test_payment_cannot_be_edited_directly(self):
		owner, restaurant, category, item, table = setup_restaurant_with_menu_and_table()
		order = place_order(restaurant, table, item)

		frappe.set_user(owner.name)
		try:
			confirm_manual_payment(order.name, "CASH")
		finally:
			frappe.set_user("Administrator")

		payment = frappe.get_doc("Payment", frappe.get_all("Payment", filters={"order": order.name})[0].name)
		payment.method = "CARD"
		with self.assertRaises(frappe.ValidationError):
			payment.save(ignore_permissions=True)

	def test_staff_of_other_restaurant_cannot_read_payment(self):
		owner_a, restaurant_a, category_a, item_a, table_a = setup_restaurant_with_menu_and_table()
		order_a = place_order(restaurant_a, table_a, item_a)
		frappe.set_user(owner_a.name)
		try:
			result = confirm_manual_payment(order_a.name, "CASH")
		finally:
			frappe.set_user("Administrator")

		owner_b, restaurant_b, category_b, item_b, table_b = setup_restaurant_with_menu_and_table()

		frappe.set_user(owner_b.name)
		try:
			visible = frappe.get_list("Payment", pluck="name")
			self.assertNotIn(result["payment"], visible)
			with self.assertRaises(frappe.PermissionError):
				frappe.get_doc("Payment", result["payment"]).check_permission("read")
		finally:
			frappe.set_user("Administrator")

	def test_staff_cannot_create_payment_directly(self):
		"""Base DocType permissions withhold "create" from Restaurant Staff entirely
		-- confirm_manual_payment (ignore_permissions=True, after its own role
		check) is the only sanctioned way a Payment ever gets created, even for an
		OWNER who is otherwise allowed to confirm payment through that API."""
		owner, restaurant, category, item, table = setup_restaurant_with_menu_and_table()
		order = place_order(restaurant, table, item)

		frappe.set_user(owner.name)
		try:
			with self.assertRaises(frappe.PermissionError):
				frappe.get_doc(
					{
						"doctype": "Payment",
						"order": order.name,
						"provider": "MANUAL",
						"method": "CASH",
						"status": "PAID",
					}
				).insert()
		finally:
			frappe.set_user("Administrator")

	def test_platform_admin_can_confirm_payment_for_any_restaurant(self):
		owner, restaurant, category, item, table = setup_restaurant_with_menu_and_table()
		order = place_order(restaurant, table, item)
		# Administrator, not restaurant staff at all.
		confirm_manual_payment(order.name, "CASH")
		self.assertEqual(frappe.db.get_value("Order", order.name, "payment_status"), "Paid")
