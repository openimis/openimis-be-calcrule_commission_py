import json

from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ValidationError
from gettext import gettext as _

from calcrule_commission.apps import AbsStrategy
from calcrule_commission.config import CLASS_RULE_PARAM_VALIDATION, \
    DESCRIPTION_CONTRIBUTION_VALUATION, FROM_TO
from calcrule_commission.converters import \
    BatchRunToBillConverter, PremiumToBillItemConverter
from contribution_plan.models import PaymentPlan
from core.signals import *
from core import datetime
from core.models import User, Officer
from invoice.services import BillService
from policy.models import Policy
from claim_batch.services import get_products_from_work_data
from product.models import Product


class CommissionCalculationRule(AbsStrategy):
    version = 1
    uuid = "a64c5d26-ed8e-42de-8bdd-3b52e806c3a8"
    calculation_rule_name = "payment: commission"
    description = DESCRIPTION_CONTRIBUTION_VALUATION
    impacted_class_parameter = CLASS_RULE_PARAM_VALIDATION
    date_valid_from = datetime.datetime(2000, 1, 1)
    date_valid_to = None
    status = "active"
    from_to = FROM_TO
    type = "account_payable"
    sub_type = "commissions"


    @classmethod
    def active_for_object(cls, instance, context, type="account_payable", sub_type="commissions"):
        return instance.__class__.__name__ == "PaymentPlan" \
               and context in ["BatchValuate"] \
               and cls.check_calculation(instance)

    @classmethod
    def check_calculation(cls, instance):
        class_name = instance.__class__.__name__
        match = False
        if class_name == "ABCMeta":
            match = str(cls.uuid) == str(instance.uuid)
        elif class_name == "PaymentPlan":
            match = cls.uuid == str(instance.calculation)
        elif class_name == "BatchRun":
            # BatchRun → Product or Location if no prodcut
            match = cls.check_calculation(instance.location)
        elif class_name == "Location":
            #  location → ProductS (Product also related to Region if the location is a district)
            if instance.type in ["D", "R"]:
                products = Product.objects.filter(location=instance, validity_to__isnull=True)
                for product in products:
                    if cls.check_calculation(product):
                        match = True
                        break
        elif class_name == "Product":
            # if product → paymentPlans
            payment_plans = PaymentPlan.objects.filter(benefit_plan=instance, is_deleted=False)
            for pp in payment_plans:
                if cls.check_calculation(pp):
                    match = True
                    break
        return match

    @classmethod
    def calculate(cls, instance, **kwargs):
        context = kwargs.get('context', None)
        if instance.__class__.__name__ == "Premium":
            return cls._calculate_commision(instance, **kwargs)
        if instance.__class__.__name__ == "PaymentPlan":
            if context == "BatchValuate":
                return cls._calculate_batch_valuate(instance, **kwargs)
        elif context == "BatchPayment":
            pass
        elif context == "IndividualPayment":
            pass
        elif context == "IndividualValuation":
            pass

    @classmethod
    def get_linked_class(cls, sender, class_name, **kwargs):
        list_class = super().get_linked_class(sender, class_name, **kwargs)

        # because we have calculation in PaymentPlan
        #  as uuid - we have to consider this case
        if class_name == "PaymentPlan":
            list_class.append("Calculation")
        return list_class

    @classmethod
    def convert(cls, instance, convert_to, **kwargs):
        results = {}
        context = kwargs.get('context', None)
        if context == 'BatchValuate':
            officer = kwargs.get('officer', None)
            policies = kwargs.get('policies', None)
            payment_plan = kwargs.get('payment_plan', None)
            convert_from = instance.__class__.__name__
            if convert_from == "BatchRun":
                results = cls._convert_commision(instance, officer, policies, payment_plan)
            results['user'] = kwargs.get('user', None)
            BillService.bill_create(convert_results=results)
        return results

    @classmethod
    def _get_batch_run_parameters(cls, **kwargs):
        audit_user_id = kwargs.get('audit_user_id', None)
        product_id = kwargs.get('product_id', None)
        start_date = kwargs.get('start_date', None)
        end_date = kwargs.get('end_date', None)
        work_data = kwargs.get('work_data', None)
        if work_data:
            batch_run = work_data['created_run']
        else:
            batch_run = None
        return audit_user_id, product_id, start_date, end_date, batch_run, work_data

    @classmethod
    def _calculate_commision(cls, instance, **kwargs):
        payment_plan = kwargs.get('payment_plan', None)
        if payment_plan:
            pp_params = payment_plan.json_ext
            if isinstance(pp_params, str):
                pp_params = json.loads(pp_params)
            if pp_params:
                pp_params = pp_params["calculation_rule"] if "calculation_rule" in pp_params else None
            commission_rate = 0
            if "commission_rate" in pp_params:
                commission_rate = float(pp_params["commission_rate"])
            return float(instance.amount) * (commission_rate / 100)
        else:
            return 0

    @classmethod
    def _calculate_batch_valuate(cls, instance, **kwargs):
        context = kwargs.get('context', None)
        audit_user_id, product_id, start_date, end_date, batch_run, work_data = \
            cls._get_batch_run_parameters(**kwargs)
        if not work_data:
            work_data = kwargs.get('work_data', None)
        if work_data:
            # Adapt work data to use products list (support for multi-product batches
            # instead of location_id). The trigger scopes this per payment_plan.
            products = get_products_from_work_data(work_data)
            # Prefer this payment plan's own benefit_plan (the product) for this context.
            product = getattr(instance, 'benefit_plan', None) or (products[0] if products else None)

            # if this is trigerred by batch_run - take user data from audit_user_id
            user = User.objects.filter(i_user__id=audit_user_id).first()
            if user is None:
                raise ValidationError(_("Such User does not exist"))

            contributions = work_data['contributions']
            # get the policies based on premiums/contributions from batch run - work data
            policies = Policy.objects.filter(
                premiums__in=list(contributions.values_list('id', flat=True)),
                validity_to__isnull=True
            )
            officers = Officer.objects.filter(
                policies__in=list(policies.values_list('id', flat=True)),
                validity_to__isnull=True
            )

            for officer in officers:
                cls.run_convert(
                    instance=batch_run,
                    convert_to='Bill',
                    officer=officer,
                    policies=policies,
                    user=user,
                    payment_plan=instance,
                    context=context
                )

        return "conversion finished 'commision'"

    @classmethod
    def _convert_commision(cls, instance, officer,  policies, payment_plan):
        bill = BatchRunToBillConverter.to_bill_obj(
            batch_run=instance,
            officer=officer,
            payment_plan=payment_plan
        )
        bill_line_items = []
        # collect policies related to enrolment officer (EO)
        policies = policies.filter(officer=officer)

        for policy in policies:
            premiums = policy.premiums.filter(validity_to__isnull=True)
            for premium in premiums:
                commission_value = cls.calculate(instance=premium, payment_plan=payment_plan, context='BatchValuate')
                bill_line_item = PremiumToBillItemConverter.to_bill_line_item_obj(
                    batch_run=instance,
                    premium=premium,
                    payment_plan=payment_plan,
                    commission_value=commission_value
                )
                bill_line_items.append(bill_line_item)

        return {
            'bill_data': bill,
            'bill_data_line': bill_line_items,
            'type_conversion': 'batch run officer - bill'
        }
