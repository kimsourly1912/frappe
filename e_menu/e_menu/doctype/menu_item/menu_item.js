// Copyright (c) 2026, E-menu and contributors
// For license information, please see license.txt

// UX convenience only -- the server independently enforces (and re-checks on save)
// that a Menu Item's category belongs to the same restaurant. See menu_item.py.
frappe.ui.form.on("Menu Item", {
	restaurant(frm) {
		frm.set_query("category", () => ({
			filters: { restaurant: frm.doc.restaurant },
		}));
	},
});
