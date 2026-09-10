// Copyright (c) 2026, E-menu and contributors
// For license information, please see license.txt

// Staff's operational order screen: buttons that call the whitelisted status-
// transition methods on the Order document (Desk-native access -- see docs/
// architecture.md). Which buttons are visible varies by current status; whether
// they succeed is still enforced server-side per role (order.py -> ACTION_ROLES),
// so a button being visible doesn't guarantee the click will be allowed -- Frappe
// surfaces the resulting PermissionError as a normal error dialog either way.

const ORDER_ACTIONS_BY_STATUS = {
	PENDING: [
		["Accept", "accept", "primary"],
		["Reject", "reject", "danger"],
		["Cancel", "cancel", null],
	],
	ACCEPTED: [
		["Start Preparing", "start_preparing", "primary"],
		["Cancel", "cancel", null],
	],
	PREPARING: [
		["Mark Ready", "mark_ready", "primary"],
		["Cancel", "cancel", null],
	],
	READY: [["Mark Served", "mark_served", "primary"]],
	SERVED: [["Complete", "complete", "primary"]],
};

frappe.ui.form.on("Order", {
	refresh(frm) {
		if (frm.is_new()) return;
		const actions = ORDER_ACTIONS_BY_STATUS[frm.doc.status] || [];
		actions.forEach(([label, method]) => {
			frm.add_custom_button(__(label), () => {
				frappe.confirm(__("{0} order {1}?", [label, frm.doc.name]), () => {
					frm.call(method).then(() => frm.reload_doc());
				});
			});
		});

		// Payment is a separate DocType (Payment) driving payment_status -- Order
		// never records payments itself, see docs/architecture.md -> Payments. This
		// calls a plain whitelisted function (frappe.call), not a document method
		// (frm.call), since confirm_manual_payment creates a new Payment rather than
		// acting on this Order.
		const paid = frm.doc.payment_status === "Paid";
		const closedOut = ["CANCELLED", "REJECTED"].includes(frm.doc.status);
		if (!paid && !closedOut) {
			frm.add_custom_button(__("Confirm Payment"), () => {
				frappe.prompt(
					{
						fieldname: "method",
						fieldtype: "Select",
						options: "CASH\nCARD\nOTHER",
						label: __("Payment Method"),
						reqd: 1,
					},
					(values) => {
						frappe.call({
							method: "e_menu.e_menu.doctype.payment.payment.confirm_manual_payment",
							args: { order: frm.doc.name, method: values.method },
						}).then(() => frm.reload_doc());
					},
					__("Confirm Payment for {0}", [frm.doc.name])
				);
			});
		}
	},
});
