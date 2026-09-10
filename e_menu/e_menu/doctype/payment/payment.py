# Copyright (c) 2026, E-menu and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document

from e_menu.permissions import get_active_restaurant_role, is_platform_admin

# Who may confirm a manual payment -- front-of-house, matches Order's CASHIER-type
# actions (accept/mark_served/complete/cancel) in order.py's ACTION_ROLES. KITCHEN
# never touches payments.
CONFIRM_ROLES = ("OWNER", "MANAGER", "CASHIER")
METHODS = ("CASH", "CARD", "OTHER")


class Payment(Document):
	def validate(self):
		if self.is_new():
			self.link_and_validate_order()
		else:
			self.reject_direct_edit()

	def link_and_validate_order(self):
		"""Never trust a client-supplied restaurant or amount -- both are always
		derived here from the Order itself, the same rule Order.
		snapshot_and_calculate_items applies to menu item price/name. This runs for
		every insert regardless of caller, so it's a real defense-in-depth layer on
		top of confirm_manual_payment's own checks, not just a formality."""
		order = frappe.db.get_value(
			"Order", self.order, ["restaurant", "total", "status", "payment_status"], as_dict=True
		)
		if not order:
			frappe.throw(_("Order {0} does not exist.").format(self.order))
		if order.status in ("CANCELLED", "REJECTED"):
			frappe.throw(_("Cannot record a payment for a {0} order.").format(order.status))
		if order.payment_status == "Paid":
			frappe.throw(_("Order {0} is already paid.").format(self.order))
		self.restaurant = order.restaurant
		self.amount = order.total

	def reject_direct_edit(self):
		"""A Payment is a financial record: once created it's never resaved by a
		user, admins included -- matches Order.reject_direct_edit. A future
		provider-driven transition (Slice 8: PENDING -> PAID/FAILED via webhook)
		uses db_set(), which bypasses validate() entirely, so this rule doesn't need
		to change when that's added."""
		frappe.throw(_("Payments cannot be edited directly. They are immutable financial records."))

	def on_update(self):
		"""The one place Order.payment_status is ever set -- Order itself never
		talks to payment logic directly (see docs/architecture.md -> Payments).
		db_set() bypasses Order.validate() (reject_direct_edit), exactly like the
		order action methods do."""
		if self.status == "PAID":
			frappe.get_doc("Order", self.order).db_set("payment_status", "Paid")


@frappe.whitelist()
def confirm_manual_payment(order: str, method: str) -> dict:
	"""Staff-facing manual payment confirmation -- the Slice 7 counterpart to Slice
	6's submit_order. Requires login (not allow_guest) since this is an internal
	staff action, and checks the caller's restaurant role manually: a bare
	@frappe.whitelist() function gets no DocType permission check for free, the
	same reason submit_order checks resolve_qr's result itself rather than relying
	on has_permission. The amount is never accepted as a parameter here at all --
	Payment.link_and_validate_order derives it from the order's own total
	unconditionally, so there's no field for a client to override even if it
	wanted to."""
	if method not in METHODS:
		frappe.throw(_("Invalid payment method."))

	order_doc = frappe.get_doc("Order", order)
	user = frappe.session.user
	if not (is_platform_admin(user) or get_active_restaurant_role(user, order_doc.restaurant) in CONFIRM_ROLES):
		frappe.throw(_("You are not authorized to confirm payment for this order."), frappe.PermissionError)

	payment = frappe.get_doc(
		{
			"doctype": "Payment",
			"order": order_doc.name,
			"provider": "MANUAL",
			"method": method,
			"status": "PAID",
		}
	)
	payment.insert(ignore_permissions=True)

	return {"payment": payment.name, "order": order_doc.name, "status": payment.status}
