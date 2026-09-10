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
	},
});
