# Copyright (c) 2026, E-menu and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt

from e_menu.e_menu.doctype.restaurant_table.restaurant_table import resolve_qr
from e_menu.permissions import get_active_restaurant_role, is_platform_admin

# Action name -> restaurant-level roles allowed to perform it. Matches the role
# intent from docs/permissions.md: CASHIER handles front-of-house (accept/reject/
# serve/complete/cancel), KITCHEN handles fulfillment (start_preparing/mark_ready)
# only. OWNER/MANAGER can do everything.
ACTION_ROLES = {
	"accept": ("OWNER", "MANAGER", "CASHIER"),
	"reject": ("OWNER", "MANAGER", "CASHIER"),
	"start_preparing": ("OWNER", "MANAGER", "KITCHEN"),
	"mark_ready": ("OWNER", "MANAGER", "KITCHEN"),
	"mark_served": ("OWNER", "MANAGER", "CASHIER"),
	"complete": ("OWNER", "MANAGER", "CASHIER"),
	"cancel": ("OWNER", "MANAGER", "CASHIER"),
}


class Order(Document):
	def validate(self):
		if self.is_new():
			self.snapshot_and_calculate_items()
		else:
			self.reject_direct_edit()

	def snapshot_and_calculate_items(self):
		"""The single, authoritative place order totals are computed -- never trusts
		a client-supplied price, name, or total (see docs/architecture.md -> Money
		and totals). Re-reads each Menu Item fresh from the database, regardless of
		what the request body claimed, and rejects anything that doesn't belong to
		this order's own restaurant or isn't currently available."""
		if not self.items:
			frappe.throw(_("An order must have at least one item."))

		subtotal = 0
		for item in self.items:
			menu_item = frappe.db.get_value(
				"Menu Item",
				item.menu_item,
				["item_name", "price", "restaurant", "is_available"],
				as_dict=True,
			)
			if not menu_item:
				frappe.throw(_("Menu Item {0} does not exist.").format(item.menu_item))
			if menu_item.restaurant != self.restaurant:
				frappe.throw(
					_("Menu Item {0} does not belong to restaurant {1}.").format(
						item.menu_item, self.restaurant
					)
				)
			if not menu_item.is_available:
				frappe.throw(_("{0} is no longer available.").format(menu_item.item_name))
			if flt(item.quantity) < 1:
				frappe.throw(_("Quantity for {0} must be at least 1.").format(menu_item.item_name))

			item.item_name_snapshot = menu_item.item_name
			item.unit_price_snapshot = menu_item.price
			item.line_total = flt(menu_item.price) * flt(item.quantity)
			subtotal += item.line_total

		self.subtotal = subtotal
		# no tax/discount/service-charge modeling yet -- total is just the subtotal,
		# kept as a separate field so adding those later doesn't need a schema change.
		self.total = subtotal

	def reject_direct_edit(self):
		"""An existing Order is never saved directly -- not by staff, not even by a
		platform admin. Every legitimate mutation after creation is one of the
		action methods below, which use db_set() (bypassing validate() entirely),
		not self.save(). This is deliberately unconditional (not just "status
		changed"): has_permission_order grants "write" broadly to any active staff
		member, because Frappe's own run_method REST/Desk convention
		(frappe/api/v1.py execute_doc_method, and Desk's frm.call()) requires
		has_permission("write") just to *invoke* a whitelisted instance method --
		this check is what actually stops that broad grant from turning into a
		generic PATCH endpoint for order contents."""
		frappe.throw(
			_(
				"Orders cannot be edited directly after creation. Use the specific "
				"order actions (accept, start_preparing, mark_ready, mark_served, "
				"complete, reject, cancel) instead."
			)
		)

	def _transition(self, action: str, allowed_from: tuple[str, ...], target_status: str):
		user = frappe.session.user
		if not (is_platform_admin(user) or get_active_restaurant_role(user, self.restaurant) in ACTION_ROLES[action]):
			frappe.throw(
				_("You are not authorized to {0} this order.").format(action.replace("_", " ")),
				frappe.PermissionError,
			)
		if self.status not in allowed_from:
			frappe.throw(
				_("Cannot {0} an order with status {1}.").format(action.replace("_", " "), self.status)
			)
		self.db_set("status", target_status)
		return {"name": self.name, "status": target_status}

	@frappe.whitelist()
	def accept(self):
		return self._transition("accept", ("PENDING",), "ACCEPTED")

	@frappe.whitelist()
	def reject(self):
		return self._transition("reject", ("PENDING",), "REJECTED")

	@frappe.whitelist()
	def start_preparing(self):
		return self._transition("start_preparing", ("ACCEPTED",), "PREPARING")

	@frappe.whitelist()
	def mark_ready(self):
		return self._transition("mark_ready", ("PREPARING",), "READY")

	@frappe.whitelist()
	def mark_served(self):
		return self._transition("mark_served", ("READY",), "SERVED")

	@frappe.whitelist()
	def complete(self):
		return self._transition("complete", ("SERVED",), "COMPLETED")

	@frappe.whitelist()
	def cancel(self):
		return self._transition("cancel", ("PENDING", "ACCEPTED", "PREPARING"), "CANCELLED")


@frappe.whitelist(allow_guest=True, methods=["POST"])
def submit_order(public_id: str, table_token: str, items: list, payment_method: str = "MANUAL") -> dict:
	"""Customer-facing order submission -- the Slice 6 counterpart to Slice 5's
	read-only menu page. restaurant/table are resolved the exact same way
	(resolve_qr), never taken from the request body directly. `items` is a list of
	{"menu_item": <Menu Item name>, "quantity": <int>, "customer_note": <str, optional>}
	-- price and item name are never read from here; Order.snapshot_and_calculate_items
	re-fetches them from the database unconditionally."""
	if not items:
		frappe.throw(_("Your cart is empty."))
	if payment_method not in ("MANUAL", "ONLINE"):
		frappe.throw(_("Invalid payment method."))

	resolved = resolve_qr(public_id, table_token)

	order = frappe.get_doc(
		{
			"doctype": "Order",
			"restaurant": resolved["restaurant"],
			"table": resolved["table"],
			"payment_method": payment_method,
			"items": [
				{
					"menu_item": row.get("menu_item"),
					"quantity": row.get("quantity"),
					"customer_note": row.get("customer_note"),
				}
				for row in items
			],
		}
	)
	order.insert(ignore_permissions=True)

	return {
		"order": order.name,
		"status": order.status,
		"subtotal": order.subtotal,
		"total": order.total,
	}
