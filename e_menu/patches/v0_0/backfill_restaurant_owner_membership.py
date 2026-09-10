import frappe


def execute():
	"""Restaurant.after_insert (Slice 2) auto-creates an OWNER Restaurant Member row
	for every new restaurant -- but any Restaurant created before that hook existed
	(e.g. during Slice 1) has none. Without it, that restaurant's own subscription
	owner would be locked out of restaurant-staff actions (inviting staff, etc.)
	since those are gated by restaurant-level membership, not the Restaurant Owner
	platform role alone. Idempotent: safe to re-run."""
	for restaurant in frappe.get_all("Restaurant", fields=["name", "owner_user"]):
		if not restaurant.owner_user:
			continue
		if frappe.db.exists(
			"Restaurant Member",
			{"restaurant": restaurant.name, "role": "OWNER", "status": "Active"},
		):
			continue
		frappe.get_doc(
			{
				"doctype": "Restaurant Member",
				"restaurant": restaurant.name,
				"user": restaurant.owner_user,
				"role": "OWNER",
				"status": "Active",
			}
		).insert(ignore_permissions=True)
	frappe.db.commit()
