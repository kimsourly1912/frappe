# Copyright (c) 2026, E-menu and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document


class MenuItem(Document):
	def validate(self):
		self.validate_category_belongs_to_same_restaurant()

	def validate_category_belongs_to_same_restaurant(self):
		"""Core integrity rule (see docs/domain-model.md): a Menu Item belonging to
		Restaurant A can never reference a Menu Category from Restaurant B, even if
		the acting user somehow has access to both (e.g. a platform admin). This is
		a data-integrity invariant, not an authorization check, so it applies
		regardless of who's making the request."""
		category_restaurant = frappe.db.get_value("Menu Category", self.category, "restaurant")
		if category_restaurant != self.restaurant:
			frappe.throw(
				_(
					"Category {0} belongs to restaurant {1}, not {2}. A menu item must "
					"use a category from its own restaurant."
				).format(self.category, category_restaurant, self.restaurant)
			)
