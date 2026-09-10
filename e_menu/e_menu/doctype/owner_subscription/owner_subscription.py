# Copyright (c) 2026, E-menu and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document


class OwnerSubscription(Document):
	def validate(self):
		self.validate_owner_is_system_user()
		self.set_restaurant_limit_from_plan()
		self.validate_single_active_subscription_per_owner()

	def validate_owner_is_system_user(self):
		user_type = frappe.db.get_value("User", self.owner_user, "user_type")
		if user_type != "System User":
			frappe.throw(
				_(
					"{0} must be a System User (Desk access) before they can hold an "
					"Owner Subscription. Update the user's User Type first."
				).format(self.owner_user)
			)

	def set_restaurant_limit_from_plan(self):
		"""Snapshot the plan's restaurant_limit at assignment time (see
		docs/domain-model.md). Only auto-applied when the subscription is new or the
		plan link changes -- a platform admin may still freely override
		restaurant_limit afterwards for a specific owner."""
		if self.is_new() or self.has_value_changed("plan"):
			self.restaurant_limit = frappe.db.get_value("Subscription Plan", self.plan, "restaurant_limit")

	def validate_single_active_subscription_per_owner(self):
		"""One owner can only have one *active* subscription at a time -- multiple
		active subscriptions would make "the" restaurant_limit for that owner
		ambiguous. Older Cancelled/Suspended subscriptions are kept as history."""
		if self.status != "Active":
			return
		duplicate = frappe.db.exists(
			"Owner Subscription",
			{
				"owner_user": self.owner_user,
				"status": "Active",
				"name": ["!=", self.name or ""],
			},
		)
		if duplicate:
			frappe.throw(
				_("{0} already has an active subscription ({1}). Cancel or suspend it first.").format(
					self.owner_user, duplicate
				)
			)
