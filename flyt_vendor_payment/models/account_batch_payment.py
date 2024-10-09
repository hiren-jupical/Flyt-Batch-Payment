# -*- coding: utf-8 -*-
##############################################################################
#
#    Flyt Consulting AS
#    Copyright (C) 2019-Today Flyt Consulting AS.(<https://www.flytconsulting.no>).
#    Author: Flyt Consulting AS. (<https://www.flytconsulting.no>)
#    you can modify it under the terms of the GNU LESSER
#    GENERAL PUBLIC LICENSE (LGPL v3), Version 3.
#
#    It is forbidden to publish, distribute, sublicense, or sell copies
#    of the Software or modified copies of the Software.
#
#    This program is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#    GNU LESSER GENERAL PUBLIC LICENSE (LGPL v3) for more details.
#
#    You should have received a copy of the GNU LESSER GENERAL PUBLIC LICENSE
#    GENERAL PUBLIC LICENSE (LGPL v3) along with this program.
#    If not, see <http://www.gnu.org/licenses/>.
#
##############################################################################
from odoo import models, api, _
from odoo.exceptions import ValidationError, UserError

class AccountBatchPayment(models.Model):
    _inherit = 'account.batch.payment'

    @api.constrains('batch_type', 'journal_id', 'payment_ids')
    def _check_payments_constrains(self):
        
        for record in self:
            validation_msg = ""
            all_companies = set(record.payment_ids.mapped('company_id'))
            if len(all_companies) > 1:
                raise ValidationError(_("All payments in the batch must belong to the same company."))
            all_journals = set(record.payment_ids.mapped('journal_id'))
            if len(all_journals) > 1 or (record.payment_ids and record.payment_ids[:1].journal_id != record.journal_id):
                raise ValidationError(_("The journal of the batch payment and of the payments it contains must be the same."))
            all_types = set(record.payment_ids.mapped('payment_type'))
            if all_types and record.batch_type not in all_types:
                raise ValidationError(_("The batch must have the same type as the payments it contains."))
            all_payment_methods = record.payment_ids.payment_method_id
            if all_payment_methods and record.payment_method_id not in all_payment_methods:
                raise ValidationError(_("The batch must have the same payment method as the payments it contains."))
            payment_null = record.payment_ids.filtered(lambda p: p.amount == 0)
            if payment_null:
                raise ValidationError(_('You cannot add payments with zero amount in a Batch Payment.'))
            non_posted = record.payment_ids.filtered(lambda p: p.state != 'posted')
            if non_posted:
                raise ValidationError(_('You cannot add payments that are not posted.'))
            
            payment_ids = record.payment_ids.filtered(lambda x:x.partner_type == 'supplier')
            partners = payment_ids.mapped('partner_id')
            for partner in partners:
                refund_amount = sum(abs(x.amount_signed) for x in payment_ids.filtered(lambda x:x.partner_id.id==partner.id and x.payment_type == 'inbound'))
                bill_amount = sum(abs(x.amount_signed) for x in payment_ids.filtered(lambda x:x.partner_id.id==partner.id and x.payment_type == 'outbound'))
                if refund_amount > bill_amount:
                    refund_refs = "\n".join([f"{x.ref if x.ref else x.name}" for x in payment_ids.filtered(lambda x:x.partner_id.id==partner.id and x.payment_type == 'inbound')])
                    bill_refs = "\n".join([f"{x.ref if x.ref else x.name}" for x in payment_ids.filtered(lambda x:x.partner_id.id==partner.id and x.payment_type == 'outbound')])
                    
                    validation_msg += _(
                        "The total refund amount for partner %s exceeds their bill amount:\n%s\n%s"
                    ) % (partner.name, bill_refs, refund_refs) + "\n\n"

            if validation_msg:
                raise ValidationError(validation_msg.strip())


    @api.model_create_multi
    def create(self, vals_list):

        records = super(AccountBatchPayment,self).create(vals_list)
        for record in records:
            payment_ids = record.payment_ids.filtered(lambda x:x.partner_type == 'supplier' and x.payment_type == 'outbound')
            if payment_ids:
                record.batch_type = payment_ids[0].payment_type
        return records


class AccountMove(models.Model):
    _inherit = 'account.move'

    @api.model_create_multi
    def create(self, vals_list):
        records = super(AccountMove, self).create(vals_list)
        for record in records:
            if record.move_type == 'in_refund':
                if record.partner_id.bank_ids:
                    partner_bank = record.commercial_partner_id
                else:
                    partner_bank = record.bank_partner_id
                bank_ids = partner_bank.bank_ids.filtered(
                lambda bank: not bank.company_id or bank.company_id == record.company_id
                ).sorted(lambda bank: not bank.allow_out_payment)

                record.partner_bank_id = bank_ids[:1]
        return records

class AccountPayment(models.Model):
    _inherit = 'account.payment'

    @api.model_create_multi
    def create(self, vals_list):
        records = super(AccountPayment, self).create(vals_list)
        for record in records:
            if record.payment_type == 'inbound' and record.partner_type == 'supplier':
                record.partner_bank_id = record.partner_id.bank_ids[:1]._origin
        return records

    @api.depends('partner_id', 'company_id', 'payment_type', 'destination_journal_id', 'is_internal_transfer')
    def _compute_available_partner_bank_ids(self):
        for pay in self:
            if pay.payment_type == 'inbound' and pay.partner_type == 'supplier':
                pay.available_partner_bank_ids = pay.partner_id.bank_ids\
                        .filtered(lambda x: x.company_id.id in (False, pay.company_id.id))._origin
            elif pay.payment_type == 'inbound':
                pay.available_partner_bank_ids = pay.journal_id.bank_account_id
            elif pay.is_internal_transfer:
                pay.available_partner_bank_ids = pay.destination_journal_id.bank_account_id
            else:
                pay.available_partner_bank_ids = pay.partner_id.bank_ids\
                        .filtered(lambda x: x.company_id.id in (False, pay.company_id.id))._origin

