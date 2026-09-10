# Copyright (c) 2026, E-menu and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document

from e_menu.permissions import MANAGING_ROLES, get_active_restaurant_role


class RestaurantMember(Document):
	def validate(self):
		self.validate_unique_membership()
		self.validate_actor_can_manage_staff()
		self.validate_not_removing_last_owner()

	def after_insert(self):
		self.sync_frappe_role()

	def on_update(self):
		self.sync_frappe_role()

	def validate_unique_membership(self):
		duplicate = frappe.db.exists(
			"Restaurant Member",
			{"restaurant": self.restaurant, "user": self.user, "name": ["!=", self.name or ""]},
		)
		if duplicate:
			frappe.throw(
				_(
					"{0} is already a member of restaurant {1} ({2}). Edit that membership "
					"instead of creating a new one."
				).format(self.user, self.restaurant, duplicate)
			)

	def validate_actor_can_manage_staff(self):
		"""Only an OWNER or MANAGER at this restaurant (or a platform admin) may
		create/edit its staff roster -- restaurant-level authorization, not a
		DocType-level permission (see docs/permissions.md)."""
		if frappe.session.user == "Administrator" or "System Manager" in frappe.get_roles(
			frappe.session.user
		):
			return
		if self._is_owner_bootstrap():
			return
		actor_role = get_active_restaurant_role(frappe.session.user, self.restaurant)
		if actor_role not in MANAGING_ROLES:
			frappe.throw(
				_("You must be an OWNER or MANAGER at {0} to manage its staff.").format(self.restaurant),
				frappe.PermissionError,
			)

	def _is_owner_bootstrap(self) -> bool:
		"""A restaurant's very first (OWNER) membership is created automatically when
		the restaurant itself is created (see Restaurant.after_insert) -- at that
		point no Restaurant Member row exists yet to authorize against. The
		subscription owner creating their own first OWNER row for their own new
		restaurant is the one explicit bootstrapping exception."""
		if not (self.is_new() and self.role == "OWNER" and self.user == frappe.session.user):
			return False
		restaurant_owner = frappe.db.get_value("Restaurant", self.restaurant, "owner_user")
		if restaurant_owner != frappe.session.user:
			return False
		return not frappe.db.exists(
			"Restaurant Member", {"restaurant": self.restaurant, "status": "Active"}
		)

	def validate_not_removing_last_owner(self):
		"""A restaurant must always keep at least one active OWNER -- otherwise
		nobody could manage its staff (or, later, its menu/tables) again without
		platform-admin intervention."""
		before = self.get_doc_before_save()
		if not before:
			return
		was_active_owner = before.role == "OWNER" and before.status == "Active"
		if not was_active_owner:
			return
		still_active_owner = self.role == "OWNER" and self.status == "Active"
		if still_active_owner:
			return
		other_active_owners = frappe.db.count(
			"Restaurant Member",
			{
				"restaurant": self.restaurant,
				"role": "OWNER",
				"status": "Active",
				"name": ["!=", self.name],
			},
		)
		if other_active_owners == 0:
			frappe.throw(
				_(
					"Cannot remove the last active OWNER of restaurant {0}. "
					"Assign another OWNER first."
				).format(self.restaurant)
			)

	def sync_frappe_role(self):
		"""Being active restaurant staff, in any role, is what grants Desk access --
		see docs/permissions.md. Additive only: disabling one membership never
		strips the role, in case the same user has Desk access via another active
		membership elsewhere.

		Saved with ignore_permissions=True deliberately: this is the system granting
		a role as a consequence of a validated membership, not the acting user
		editing their own roles -- Frappe's User doctype blocks a user from
		self-escalating their own roles child table even via User.add_roles(), which
		calls plain self.save() and would otherwise fail here when the newly-added
		staff member is also the currently logged-in session user (e.g. the owner
		bootstrap path in Restaurant.after_insert)."""
		if self.status != "Active":
			return
		if "Restaurant Staff" not in frappe.get_roles(self.user):
			user = frappe.get_doc("User", self.user)
			user.append_roles("Restaurant Staff")
			user.save(ignore_permissions=True)


@frappe.whitelist()
def invite_staff(restaurant: str, email: str, role: str, first_name: str | None = None) -> dict:
	"""Owner/Manager-facing action: add a person as restaurant staff, creating their
	User account if it doesn't exist yet. Authorization mirrors
	RestaurantMember.validate_actor_can_manage_staff() -- checked explicitly here
	first so an unauthorized caller can't cause a User to be created at all."""
	if not (
		frappe.session.user == "Administrator"
		or "System Manager" in frappe.get_roles(frappe.session.user)
		or get_active_restaurant_role(frappe.session.user, restaurant) in MANAGING_ROLES
	):
		frappe.throw(
			_("You must be an OWNER or MANAGER at {0} to invite staff.").format(restaurant),
			frappe.PermissionError,
		)

	email = email.strip().lower()
	if not frappe.db.exists("User", email):
		frappe.get_doc(
			{
				"doctype": "User",
				"email": email,
				"first_name": first_name or email.split("@")[0],
				"send_welcome_email": 0,
			}
		).insert(ignore_permissions=True)

	member = frappe.get_doc(
		{
			"doctype": "Restaurant Member",
			"restaurant": restaurant,
			"user": email,
			"role": role,
		}
	).insert(ignore_permissions=True)
	return member.as_dict()
