# Copyright (c) 2026, E-menu and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document


class Restaurant(Document):
	def validate(self):
		self.validate_owner_subscription_is_active()
		self.validate_actor_owns_subscription()
		if self.is_new():
			self.enforce_restaurant_limit()
			self.set_public_id()

	def after_insert(self):
		"""A restaurant always starts with exactly one staff member: its
		subscription owner, as OWNER. See RestaurantMember._is_owner_bootstrap()
		for the matching authorization exception this relies on -- there is no
		Restaurant Member row yet to authorize against otherwise."""
		frappe.get_doc(
			{
				"doctype": "Restaurant Member",
				"restaurant": self.name,
				"user": self.owner_user,
				"role": "OWNER",
			}
		).insert(ignore_permissions=True)

	def validate_owner_subscription_is_active(self):
		status = frappe.db.get_value("Owner Subscription", self.owner_subscription, "status")
		if status != "Active":
			frappe.throw(
				_(
					"Cannot create or update a restaurant under Owner Subscription {0} "
					"because its status is {1}, not Active."
				).format(self.owner_subscription, status)
			)

	def validate_actor_owns_subscription(self):
		"""A client-supplied owner_subscription is never sufficient authorization by
		itself -- the acting user must actually be the owner on that subscription,
		unless they are a platform administrator (System Manager)."""
		if frappe.session.user == "Administrator" or "System Manager" in frappe.get_roles(
			frappe.session.user
		):
			return
		if not (self.is_new() or self.has_value_changed("owner_subscription")):
			return
		subscription_owner = frappe.db.get_value(
			"Owner Subscription", self.owner_subscription, "owner_user"
		)
		if subscription_owner != frappe.session.user:
			frappe.throw(
				_("You are not the owner of subscription {0}.").format(self.owner_subscription),
				frappe.PermissionError,
			)

	def enforce_restaurant_limit(self):
		"""Server-side restaurant limit enforcement -- never rely on the UI hiding a
		button. Locks the Owner Subscription row (SELECT ... FOR UPDATE) for the
		duration of the transaction so two concurrent restaurant-creation requests
		under the same subscription can't both slip past the check."""
		restaurant_limit = frappe.db.get_value(
			"Owner Subscription", self.owner_subscription, "restaurant_limit", for_update=True
		)
		existing = frappe.db.count("Restaurant", {"owner_subscription": self.owner_subscription})
		if existing >= restaurant_limit:
			frappe.throw(
				_(
					"Restaurant limit reached for subscription {0} ({1} of {2} used). "
					"Upgrade the plan to create more restaurants."
				).format(self.owner_subscription, existing, restaurant_limit)
			)

	def set_public_id(self):
		"""A stable, non-sequential identifier safe to expose in customer-facing
		QR/menu URLs later (Slice 4+) -- never the internal, sequential document name."""
		if not self.public_id:
			self.public_id = frappe.generate_hash(length=16)
