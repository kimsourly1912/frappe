# Development seed/demo data. Idempotent -- safe to run against a fresh or an
# already-seeded site. Not for production use (creates known demo passwords).
#
# Usage (from the bench directory):
#   bench --site <site> execute e_menu.e_menu.demo.create_demo_data

import frappe

from e_menu.e_menu.doctype.order.order import submit_order
from e_menu.e_menu.doctype.payment.payment import confirm_manual_payment
from e_menu.e_menu.doctype.restaurant_member.restaurant_member import invite_staff
from e_menu.e_menu.doctype.restaurant_table.restaurant_table import resolve_qr

DEMO_OWNER_EMAIL = "owner@example.com"
DEMO_OWNER_PASSWORD = "e_menu_demo"
DEMO_STAFF_PASSWORD = "e_menu_demo"

DEMO_STAFF = [
	("manager@example.com", "MANAGER", "Demo", "Manager"),
	("cashier@example.com", "CASHIER", "Demo", "Cashier"),
	("kitchen@example.com", "KITCHEN", "Demo", "Kitchen"),
]


DEMO_CATEGORIES = ["Food", "Drinks"]
DEMO_ITEMS = [
	# (category, item_name, price)
	("Food", "Fried Rice", 3.50),
	("Drinks", "Iced Coffee", 1.50),
]


def create_demo_data():
	create_plans()
	owner = create_demo_owner()
	subscription = create_demo_subscription(owner)
	restaurant = create_demo_restaurant(subscription)
	demonstrate_limit_enforcement(subscription)
	create_demo_staff(restaurant)
	create_demo_menu(restaurant)
	tables = create_demo_tables(restaurant)

	second_owner, second_restaurant = create_second_demo_restaurant()
	demonstrate_cross_restaurant_isolation(restaurant, second_restaurant)
	demonstrate_cross_restaurant_menu_reference_rejected(restaurant, second_restaurant)
	demonstrate_qr_resolution(restaurant, tables["T01"])

	fried_rice = frappe.get_doc("Menu Item", {"restaurant": restaurant.name, "item_name": "Fried Rice"})
	order = create_demo_order(restaurant, tables["T01"], fried_rice)
	demonstrate_order_lifecycle(order)
	demonstrate_payment_confirmation(order)

	frappe.db.commit()
	print("\nDemo data ready.")
	print(f"Owner:   {DEMO_OWNER_EMAIL} / {DEMO_OWNER_PASSWORD}  ({restaurant.restaurant_name})")
	for email, role, *_rest in DEMO_STAFF:
		print(f"{role.title():<8} {email} / {DEMO_STAFF_PASSWORD}  ({restaurant.restaurant_name})")
	print(f"Owner:   {second_owner} / {DEMO_OWNER_PASSWORD}  ({second_restaurant.restaurant_name})")
	for table_name, table in tables.items():
		print(f"Table {table_name}: {table.menu_url}")


def create_plans():
	plans = [
		("Free", 1, "Single restaurant, for trying out E-menu."),
		("Starter", 3, "Up to 3 restaurants."),
		("Business", 10, "Higher-volume restaurant groups (limit configurable by admin)."),
	]
	for plan_name, restaurant_limit, description in plans:
		if frappe.db.exists("Subscription Plan", plan_name):
			continue
		frappe.get_doc(
			{
				"doctype": "Subscription Plan",
				"plan_name": plan_name,
				"restaurant_limit": restaurant_limit,
				"description": description,
			}
		).insert(ignore_permissions=True)
		print(f"Created Subscription Plan: {plan_name} (limit={restaurant_limit})")


def create_demo_owner():
	if frappe.db.exists("User", DEMO_OWNER_EMAIL):
		user = frappe.get_doc("User", DEMO_OWNER_EMAIL)
	else:
		user = frappe.get_doc(
			{
				"doctype": "User",
				"email": DEMO_OWNER_EMAIL,
				"first_name": "Demo",
				"last_name": "Owner",
				"send_welcome_email": 0,
			}
		).insert(ignore_permissions=True)
		print(f"Created demo owner User: {DEMO_OWNER_EMAIL}")

	if "Restaurant Owner" not in frappe.get_roles(user.name):
		user.add_roles("Restaurant Owner")
		print("Granted Restaurant Owner role (this also gives Desk access)")

	user.reload()
	user.new_password = DEMO_OWNER_PASSWORD
	user.save(ignore_permissions=True)
	return user


def create_demo_subscription(owner):
	existing = frappe.db.exists("Owner Subscription", {"owner_user": owner.name, "status": "Active"})
	if existing:
		return frappe.get_doc("Owner Subscription", existing)
	sub = frappe.get_doc(
		{
			"doctype": "Owner Subscription",
			"owner_user": owner.name,
			"plan": "Free",
		}
	).insert(ignore_permissions=True)
	print(f"Created Owner Subscription {sub.name} for {owner.name} on Free plan (limit={sub.restaurant_limit})")
	return sub


def create_demo_restaurant(subscription):
	existing = frappe.db.exists(
		"Restaurant", {"owner_subscription": subscription.name, "restaurant_name": "Angkor Cafe"}
	)
	if existing:
		return frappe.get_doc("Restaurant", existing)

	frappe.set_user(subscription.owner_user)
	try:
		restaurant = frappe.get_doc(
			{
				"doctype": "Restaurant",
				"restaurant_name": "Angkor Cafe",
				"owner_subscription": subscription.name,
			}
		).insert()
	finally:
		frappe.set_user("Administrator")
	print(f"Created Restaurant {restaurant.name} 'Angkor Cafe' as the demo owner (public_id={restaurant.public_id})")
	return restaurant


def demonstrate_limit_enforcement(subscription):
	"""Proves the Slice 1 acceptance criterion live: a second restaurant under a
	limit=1 subscription is rejected server-side. Doesn't create anything."""
	frappe.set_user(subscription.owner_user)
	try:
		frappe.get_doc(
			{
				"doctype": "Restaurant",
				"restaurant_name": "Second Restaurant (should fail)",
				"owner_subscription": subscription.name,
			}
		).insert()
	except frappe.ValidationError as e:
		print(f"Confirmed server-side limit enforcement -- second restaurant rejected: {e}")
	else:
		print("WARNING: second restaurant was NOT rejected -- limit enforcement may be broken.")
	finally:
		frappe.set_user("Administrator")


def create_demo_staff(restaurant):
	"""Owner invites a Manager, Cashier, and Kitchen staff member -- exercises the
	real invite_staff() API as the owner, then sets a known demo password on each
	new User so they can be signed in as directly for the demo."""
	frappe.set_user(restaurant.owner_user)
	try:
		for email, role, first_name, last_name in DEMO_STAFF:
			if frappe.db.exists("Restaurant Member", {"restaurant": restaurant.name, "user": email}):
				continue
			invite_staff(restaurant.name, email, role, first_name=first_name)
			print(f"Invited {email} to {restaurant.restaurant_name} as {role}")
	finally:
		frappe.set_user("Administrator")

	for email, role, first_name, last_name in DEMO_STAFF:
		user = frappe.get_doc("User", email)
		user.last_name = user.last_name or last_name
		user.new_password = DEMO_STAFF_PASSWORD
		user.save(ignore_permissions=True)


def create_second_demo_restaurant():
	"""A second, unrelated owner+restaurant -- exists purely to demonstrate that
	Angkor Cafe's staff cannot reach it (the Slice 2 acceptance criterion)."""
	email = "owner2@example.com"
	if frappe.db.exists("User", email):
		owner = frappe.get_doc("User", email)
	else:
		owner = frappe.get_doc(
			{
				"doctype": "User",
				"email": email,
				"first_name": "Second",
				"last_name": "Owner",
				"send_welcome_email": 0,
			}
		).insert(ignore_permissions=True)
	if "Restaurant Owner" not in frappe.get_roles(owner.name):
		owner.add_roles("Restaurant Owner")
	owner.reload()
	owner.new_password = DEMO_OWNER_PASSWORD
	owner.save(ignore_permissions=True)

	existing_sub = frappe.db.exists("Owner Subscription", {"owner_user": owner.name, "status": "Active"})
	if existing_sub:
		sub = frappe.get_doc("Owner Subscription", existing_sub)
	else:
		sub = frappe.get_doc(
			{"doctype": "Owner Subscription", "owner_user": owner.name, "plan": "Starter"}
		).insert(ignore_permissions=True)
		print(f"Created Owner Subscription {sub.name} for {owner.name} on Starter plan")

	existing_restaurant = frappe.db.exists(
		"Restaurant", {"owner_subscription": sub.name, "restaurant_name": "Spice Garden"}
	)
	if existing_restaurant:
		return owner.name, frappe.get_doc("Restaurant", existing_restaurant)

	frappe.set_user(owner.name)
	try:
		restaurant = frappe.get_doc(
			{
				"doctype": "Restaurant",
				"restaurant_name": "Spice Garden",
				"owner_subscription": sub.name,
			}
		).insert()
	finally:
		frappe.set_user("Administrator")
	print(f"Created Restaurant {restaurant.name} 'Spice Garden' for the second demo owner")
	return owner.name, restaurant


def demonstrate_cross_restaurant_isolation(restaurant_a, restaurant_b):
	"""Proves the Slice 2 acceptance criterion live: Angkor Cafe's cashier cannot
	read Spice Garden, and Spice Garden never appears in their restaurant list."""
	cashier_email = "cashier@example.com"
	frappe.set_user(cashier_email)
	try:
		visible = frappe.get_list("Restaurant", pluck="name")
		leaked = restaurant_b.name in visible
		try:
			frappe.get_doc("Restaurant", restaurant_b.name).check_permission("read")
			direct_access_blocked = False
		except frappe.PermissionError:
			direct_access_blocked = True
	finally:
		frappe.set_user("Administrator")

	if not leaked and direct_access_blocked:
		print(
			f"Confirmed tenant isolation -- {cashier_email} (staff at {restaurant_a.restaurant_name}) "
			f"cannot list or directly read {restaurant_b.restaurant_name}."
		)
	else:
		print("WARNING: cross-restaurant isolation may be broken -- see leaked/direct_access_blocked above.")


def create_demo_menu(restaurant):
	"""Food/Drinks categories with Fried Rice and Iced Coffee, created as the owner
	(exercising the real create paths, not ignore_permissions)."""
	frappe.set_user(restaurant.owner_user)
	try:
		categories = {}
		for category_name in DEMO_CATEGORIES:
			existing = frappe.db.exists(
				"Menu Category", {"restaurant": restaurant.name, "category_name": category_name}
			)
			if existing:
				categories[category_name] = existing
				continue
			category = frappe.get_doc(
				{
					"doctype": "Menu Category",
					"restaurant": restaurant.name,
					"category_name": category_name,
				}
			).insert()
			categories[category_name] = category.name
			print(f"Created Menu Category '{category_name}' for {restaurant.restaurant_name}")

		for category_name, item_name, price in DEMO_ITEMS:
			if frappe.db.exists(
				"Menu Item", {"restaurant": restaurant.name, "item_name": item_name}
			):
				continue
			frappe.get_doc(
				{
					"doctype": "Menu Item",
					"restaurant": restaurant.name,
					"category": categories[category_name],
					"item_name": item_name,
					"price": price,
				}
			).insert()
			print(f"Created Menu Item '{item_name}' (${price}) in '{category_name}'")
	finally:
		frappe.set_user("Administrator")
	return categories


def demonstrate_cross_restaurant_menu_reference_rejected(restaurant_a, restaurant_b):
	"""Proves the Slice 3 acceptance criterion live: a Menu Item belonging to
	Restaurant A can never reference a Menu Category from Restaurant B."""
	category_b_name = frappe.db.exists(
		"Menu Category", {"restaurant": restaurant_b.name, "category_name": "House Category"}
	)
	if not category_b_name:
		frappe.set_user(restaurant_b.owner_user)
		try:
			category_b_name = frappe.get_doc(
				{
					"doctype": "Menu Category",
					"restaurant": restaurant_b.name,
					"category_name": "House Category",
				}
			).insert().name
		finally:
			frappe.set_user("Administrator")

	frappe.set_user(restaurant_a.owner_user)
	try:
		frappe.get_doc(
			{
				"doctype": "Menu Item",
				"restaurant": restaurant_a.name,
				"category": category_b_name,
				"item_name": "Should Not Be Created",
				"price": 1,
			}
		).insert()
	except frappe.ValidationError as e:
		print(
			f"Confirmed cross-restaurant menu integrity -- {restaurant_a.restaurant_name} "
			f"cannot use a category from {restaurant_b.restaurant_name}: {e}"
		)
	else:
		print("WARNING: cross-restaurant category reference was NOT rejected -- integrity check may be broken.")
	finally:
		frappe.set_user("Administrator")


def create_demo_tables(restaurant):
	frappe.set_user(restaurant.owner_user)
	try:
		tables = {}
		for table_name in ("T01", "T02"):
			existing = frappe.db.exists(
				"Restaurant Table", {"restaurant": restaurant.name, "table_name": table_name}
			)
			if existing:
				tables[table_name] = frappe.get_doc("Restaurant Table", existing)
				continue
			table = frappe.get_doc(
				{
					"doctype": "Restaurant Table",
					"restaurant": restaurant.name,
					"table_name": table_name,
				}
			).insert()
			tables[table_name] = table
			print(f"Created Restaurant Table '{table_name}' for {restaurant.restaurant_name}: {table.menu_url}")
	finally:
		frappe.set_user("Administrator")
	return tables


def demonstrate_qr_resolution(restaurant, table):
	"""Proves the Slice 4 acceptance criterion live: scanning table T01's QR
	resolves exactly one active Restaurant + Table, and a bad/deactivated token
	fails safely with a generic error (no restaurant/table enumeration)."""
	frappe.set_user("Guest")
	try:
		result = resolve_qr(restaurant.public_id, table.qr_token)
		print(
			f"Confirmed QR resolution -- table {table.table_name}'s QR resolves to "
			f"{result['restaurant_name']} / {result['table_name']}."
		)
		try:
			resolve_qr(restaurant.public_id, "not-a-real-token")
			print("WARNING: an invalid table token was NOT rejected -- QR resolution may be broken.")
		except frappe.DoesNotExistError:
			print("Confirmed invalid QR tokens fail safely (generic 'not found', no enumeration).")
	finally:
		frappe.set_user("Administrator")


def create_demo_order(restaurant, table, item):
	"""A customer (Guest) submits an order -- idempotent by reusing any existing
	order already on this table rather than piling up duplicates on re-runs."""
	existing = frappe.db.exists("Order", {"restaurant": restaurant.name, "table": table.name})
	if existing:
		return frappe.get_doc("Order", existing)

	frappe.set_user("Guest")
	try:
		result = submit_order(
			restaurant.public_id,
			table.qr_token,
			[{"menu_item": item.name, "quantity": 2}],
			payment_method="MANUAL",
		)
	finally:
		frappe.set_user("Administrator")
	order = frappe.get_doc("Order", result["order"])
	print(
		f"Customer submitted {order.name} at {restaurant.restaurant_name} table "
		f"{table.table_name}: 2x {item.item_name} = ${order.total}"
	)
	return order


def demonstrate_order_lifecycle(order):
	"""Proves the Slice 6 acceptance criterion live: authorized staff move an
	order through valid states (cashier accepts, kitchen prepares, cashier
	serves/completes), and an invalid transition is rejected."""
	if order.status != "PENDING":
		print(f"{order.name} is already {order.status} -- skipping lifecycle demo (idempotent re-run).")
		return

	cashier, kitchen = "cashier@example.com", "kitchen@example.com"

	frappe.set_user(cashier)
	try:
		order.accept()
	finally:
		frappe.set_user("Administrator")
	print(f"Cashier accepted {order.name}")

	frappe.set_user(kitchen)
	try:
		order.start_preparing()
		order.mark_ready()
	finally:
		frappe.set_user("Administrator")
	print(f"Kitchen moved {order.name}: PREPARING -> READY")

	frappe.set_user(cashier)
	try:
		order.mark_served()
		order.complete()
	finally:
		frappe.set_user("Administrator")
	print(f"Cashier moved {order.name}: SERVED -> COMPLETED")

	frappe.set_user(cashier)
	try:
		order.complete()
	except frappe.ValidationError as e:
		print(f"Confirmed invalid transition rejected -- can't complete a COMPLETED order: {e}")
	else:
		print("WARNING: an invalid order transition was NOT rejected -- state machine may be broken.")
	finally:
		frappe.set_user("Administrator")


def demonstrate_payment_confirmation(order):
	"""Proves the Slice 7 acceptance criterion live: a cashier confirms manual
	payment for the order, Order.payment_status flips to Paid (via Payment.
	on_update, never edited on Order directly), and a second confirmation attempt
	on an already-paid order is rejected."""
	if frappe.db.get_value("Order", order.name, "payment_status") == "Paid":
		print(f"{order.name} is already Paid -- skipping payment demo (idempotent re-run).")
		return

	cashier = "cashier@example.com"
	frappe.set_user(cashier)
	try:
		result = confirm_manual_payment(order.name, "CASH")
	finally:
		frappe.set_user("Administrator")
	print(f"Cashier confirmed manual payment {result['payment']} for {order.name} (${order.total}, CASH)")

	frappe.set_user(cashier)
	try:
		confirm_manual_payment(order.name, "CASH")
	except frappe.ValidationError as e:
		print(f"Confirmed an already-paid order cannot be paid again: {e}")
	else:
		print("WARNING: a second payment confirmation was NOT rejected -- payment integrity may be broken.")
	finally:
		frappe.set_user("Administrator")
