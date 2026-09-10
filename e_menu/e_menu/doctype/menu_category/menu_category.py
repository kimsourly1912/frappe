# Copyright (c) 2026, E-menu and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document


class MenuCategory(Document):
	def validate(self):
		self.validate_unique_category_name_per_restaurant()

	def validate_unique_category_name_per_restaurant(self):
		"""Category names are unique per restaurant, not globally -- Restaurant A and
		Restaurant B can both have a "Drinks" category. MariaDB's utf8mb4_unicode_ci
		collation (see docs/development.md) makes this comparison case-insensitive
		for free, matching how a human would judge two names "the same"."""
		duplicate = frappe.db.exists(
			"Menu Category",
			{
				"restaurant": self.restaurant,
				"category_name": self.category_name,
				"name": ["!=", self.name or ""],
			},
		)
		if duplicate:
			frappe.throw(
				_(
					"Restaurant {0} already has a category named {1} ({2}). Category "
					"names must be unique within a restaurant."
				).format(self.restaurant, self.category_name, duplicate)
			)
