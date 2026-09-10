# Copyright (c) 2026, E-menu and contributors
# For license information, please see license.txt

import io

import frappe
import qrcode
from frappe import _
from frappe.model.document import Document
from frappe.utils import get_url


class RestaurantTable(Document):
	def validate(self):
		self.validate_unique_table_name_per_restaurant()

	def before_insert(self):
		self.set_qr_token()

	def after_insert(self):
		self.generate_qr_code()

	def validate_unique_table_name_per_restaurant(self):
		duplicate = frappe.db.exists(
			"Restaurant Table",
			{
				"restaurant": self.restaurant,
				"table_name": self.table_name,
				"name": ["!=", self.name or ""],
			},
		)
		if duplicate:
			frappe.throw(
				_("Restaurant {0} already has a table named {1} ({2}).").format(
					self.restaurant, self.table_name, duplicate
				)
			)

	def set_qr_token(self):
		"""A secure, unguessable, table-specific identifier -- never the internal
		document name. Combined with the restaurant's public_id, this is the only
		"authorization" an anonymous customer has for the ordering flow (Slice 5+),
		so it needs real entropy, not just uniqueness."""
		if not self.qr_token:
			self.qr_token = frappe.generate_hash(length=24)

	def get_menu_url(self) -> str:
		public_id = frappe.db.get_value("Restaurant", self.restaurant, "public_id")
		return f"{get_url()}/menu/{public_id}/{self.qr_token}"

	def generate_qr_code(self):
		"""Renders the printable QR image once, right after the table (and its
		qr_token) are created. Stored as a public File -- the image is only ever a
		visual encoding of a URL that's meant to be public once Slice 5 builds the
		page it points to, so there's nothing to protect by making it private."""
		menu_url = self.get_menu_url()
		image = qrcode.make(menu_url)
		buffer = io.BytesIO()
		image.save(buffer, format="PNG")

		file_doc = frappe.get_doc(
			{
				"doctype": "File",
				"file_name": f"{self.name}-qr.png",
				"attached_to_doctype": self.doctype,
				"attached_to_name": self.name,
				"attached_to_field": "qr_code",
				"content": buffer.getvalue(),
				"is_private": 0,
			}
		).insert(ignore_permissions=True)

		# db_set (not a raw frappe.db.set_value) so the in-memory doc's `modified`
		# timestamp stays in sync with what's now in the database -- otherwise a
		# caller holding the object returned by insert() would hit a
		# TimestampMismatchError on their next .save().
		self.db_set({"qr_code": file_doc.file_url, "menu_url": menu_url})


@frappe.whitelist(allow_guest=True, methods=["GET"])
def resolve_qr(public_id: str, table_token: str) -> dict:
	"""Resolves a scanned QR code to exactly one active Restaurant + Table --
	the server-side mechanism behind the Slice 4 acceptance criterion. Fails
	safely: an invalid public_id, an invalid table_token, a table belonging to a
	different restaurant, or either side being Inactive all produce the exact
	same generic error, so a client can't enumerate which restaurants/tables
	exist or distinguish "wrong token" from "deactivated" by probing.

	This only resolves identity -- browsing the actual menu (categories, items,
	cart) is Slice 5's public web layer, built on top of this."""
	restaurant = frappe.db.get_value(
		"Restaurant",
		{"public_id": public_id, "status": "Active"},
		["name", "restaurant_name"],
		as_dict=True,
	)
	table = None
	if restaurant:
		table = frappe.db.get_value(
			"Restaurant Table",
			{"restaurant": restaurant.name, "qr_token": table_token, "status": "Active"},
			["name", "table_name"],
			as_dict=True,
		)

	if not restaurant or not table:
		frappe.throw(_("Invalid or expired QR code."), frappe.DoesNotExistError)

	return {
		"restaurant": restaurant.name,
		"restaurant_name": restaurant.restaurant_name,
		"table": table.name,
		"table_name": table.table_name,
	}
