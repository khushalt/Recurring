# -*- coding: utf-8 -*-
# Copyright (c) 2015, Indictrans and contributors
# For license information, please see license.txt
from __future__ import unicode_literals
import frappe
from frappe import _
from frappe.utils import flt, cstr, cint
from frappe.model.document import Document

def validate_recurring_invoice(self, method):
	if self.is_recurring:
		set_advances(self)

def set_advances(self):
		"""Returns list of advances against Account, Party, Reference"""
		res = self.get_advance_entries()
		jv_cntr = 0
		self.set("advances", [])
		for d in res:
			jv_cntr += 1
			if jv_cntr == 1:
				self.append("advances", {
					"doctype": self.doctype + " Advance",
					"reference_type": d.reference_type,
					"reference_name": d.reference_name,
					"reference_row": d.reference_row,
					"remarks": d.remarks,
					"advance_amount": flt(d.amount),
					"allocated_amount": self.outstanding_amount
				})

def get_advance_entries(self, include_unallocated=True):
		if self.doctype == "Sales Invoice":
			party_account = self.debit_to
			party_type = "Customer"
			party = self.customer
			amount_field = "credit_in_account_currency"
			order_field = "sales_order"
			order_doctype = "Sales Order"
		else:
			party_account = self.credit_to
			party_type = "Supplier"
			party = self.supplier
			amount_field = "debit_in_account_currency"
			order_field = "purchase_order"
			order_doctype = "Purchase Order"

		order_list = list(set([d.get(order_field)
			for d in self.get("items") if d.get(order_field)]))

		journal_entries = get_advance_journal_entries(party_type, party, party_account,
			amount_field, order_doctype, order_list, include_unallocated)

		payment_entries = get_advance_payment_entries(party_type, party, party_account,
			order_doctype, order_list, include_unallocated)

		res = journal_entries + payment_entries

		return res

def get_advance_payment_entries(party_type, party, party_account,
		order_doctype, order_list=None, include_unallocated=True, against_all_orders=False):
	party_account_field = "paid_from" if party_type == "Customer" else "paid_to"
	payment_type = "Receive" if party_type == "Customer" else "Pay"
	payment_entries_against_order, unallocated_payment_entries = [], []

	if order_list or against_all_orders:
		if order_list:
			reference_condition = " and t2.reference_name in ({0})"\
				.format(', '.join(['%s'] * len(order_list)))
		else:
			reference_condition = ""
			order_list = []

		payment_entries_against_order = frappe.db.sql("""
			select
				"Payment Entry" as reference_type, t1.name as reference_name,
				t1.remarks, t2.allocated_amount as amount, t2.name as reference_row,
				t2.reference_name as against_order, t1.posting_date
			from `tabPayment Entry` t1, `tabPayment Entry Reference` t2
			where
				t1.name = t2.parent and t1.{0} = %s and t1.payment_type = %s
				and t1.party_type = %s and t1.party = %s and t1.docstatus = 1
				and t2.reference_doctype = %s {1}
		""".format(party_account_field, reference_condition),
		[party_account, payment_type, party_type, party, order_doctype] + order_list, as_dict=1)

	if include_unallocated:
		unallocated_payment_entries = frappe.db.sql("""
				select "Payment Entry" as reference_type, name as reference_name,
				remarks, unallocated_amount as amount
				from `tabPayment Entry`
				where
					{0} = %s and party_type = %s and party = %s and payment_type = %s
					and docstatus = 1 and unallocated_amount > 0
			""".format(party_account_field), (party_account, party_type, party, payment_type), as_dict=1)

	return list(payment_entries_against_order) + list(unallocated_payment_entries)


def get_advance_journal_entries(party_type, party, party_account, amount_field,
		order_doctype, order_list, include_unallocated=True):

	dr_or_cr = "credit_in_account_currency" if party_type=="Customer" else "debit_in_account_currency"

	conditions = []
	if include_unallocated:
		conditions.append("ifnull(t2.reference_name, '')=''")

	if order_list:
		order_condition = ', '.join(['%s'] * len(order_list))
		conditions.append(" (t2.reference_type = '{0}' and ifnull(t2.reference_name, '') in ({1}))"\
			.format(order_doctype, order_condition))

	reference_condition = " and (" + " or ".join(conditions) + ")" if conditions else ""

	journal_entries = frappe.db.sql("""
		select
			"Journal Entry" as reference_type, t1.name as reference_name,
			t1.remark as remarks, t2.{0} as amount, t2.name as reference_row,
			t2.reference_name as against_order
		from
			`tabJournal Entry` t1, `tabJournal Entry Account` t2
		where
			t1.name = t2.parent and t2.account = %s
			and t2.party_type = %s and t2.party = %s
			and t2.is_advance = 'Yes' and t1.docstatus = 1
			and {1} > 0 {2}
		order by t1.posting_date""".format(amount_field, dr_or_cr, reference_condition),
		[party_account, party_type, party] + order_list, as_dict=1)

	return list(journal_entries)