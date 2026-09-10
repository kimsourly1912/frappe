# Public, unauthenticated customer menu page -- reached by scanning a table's QR
# code (see docs/architecture.md -> Customer-facing UI). Route is declared in
# hooks.py (website_route_rules): /menu/<public_id>/<table_token> -> this page,
# with public_id/table_token landing in frappe.form_dict via Frappe's own dynamic
# route matching (frappe/website/router.py: evaluate_dynamic_routes).

import frappe
from frappe import _

from e_menu.e_menu.doctype.restaurant_table.restaurant_table import resolve_qr

no_cache = 1


def get_context(context):
	public_id = frappe.form_dict.get("public_id")
	table_token = frappe.form_dict.get("table_token")

	try:
		resolved = resolve_qr(public_id, table_token)
	except frappe.DoesNotExistError:
		# Same fail-safe posture as resolve_qr itself: one generic, friendly state
		# for every invalid/deactivated case -- never reveals which part failed.
		context.is_valid = False
		context.title = _("Menu Unavailable")
		context.http_status_code = 404
		return context

	context.is_valid = True
	context.title = resolved["restaurant_name"]
	context.restaurant = resolved["restaurant"]
	context.table = resolved["table"]
	context.restaurant_name = resolved["restaurant_name"]
	context.table_name = resolved["table_name"]
	context.table_token = table_token
	context.categories = get_available_menu(resolved["restaurant"])
	return context


def get_available_menu(restaurant: str) -> list[dict]:
	"""Active categories, each carrying only its available items. A category with
	no currently-available items is omitted -- an empty section heading isn't
	useful to a customer deciding what to order."""
	categories = frappe.get_all(
		"Menu Category",
		filters={"restaurant": restaurant, "is_active": 1},
		fields=["name", "category_name", "description", "image"],
		order_by="sort_order asc, category_name asc",
	)

	menu = []
	for category in categories:
		items = frappe.get_all(
			"Menu Item",
			filters={"restaurant": restaurant, "category": category.name, "is_available": 1},
			fields=["name", "item_name", "description", "image", "price"],
			order_by="sort_order asc, item_name asc",
		)
		if not items:
			continue
		# NOT "items" -- frappe.get_all returns dict-like rows, and `dict` already
		# has a real .items() method, which would silently shadow this key when
		# accessed as category.items in the Jinja template (Jinja tries attribute
		# access before subscript access).
		category["menu_items"] = items
		menu.append(category)
	return menu
