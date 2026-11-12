from django.test import TestCase

from calcrule_commission.calculation_rule import CommissionCalculationRule
from calcrule_commission.converters import PremiumToBillItemConverter
from contribution.models import Premium
from contribution_plan.models import PaymentPlan


class CommissionCalculationRuleTest(TestCase):
    """OP-3322: a payment plan without calculation_rule params gives no commission."""

    rule = CommissionCalculationRule

    def test_commission_without_calculation_rule_params(self):
        for json_ext in (None, {}, {"other": 1}, '{"other": 1}'):
            with self.subTest(json_ext=json_ext):
                commission = self.rule.calculate(Premium(amount=200), payment_plan=PaymentPlan(json_ext=json_ext))
                self.assertEqual(commission, 0)

    def test_commission_from_rate(self):
        payment_plan = PaymentPlan(json_ext={"calculation_rule": {"commission_rate": 5}})
        self.assertEqual(self.rule.calculate(Premium(amount=200), payment_plan=payment_plan), 10)

    def test_bill_line_discount_without_calculation_rule_params(self):
        for json_ext in (None, {"other": 1}):
            with self.subTest(json_ext=json_ext):
                line = {}
                PremiumToBillItemConverter.build_discount(line, PaymentPlan(json_ext=json_ext))
                self.assertEqual(line["discount"], 0)

    def test_bill_line_carries_the_commission_once(self):
        """The rate is applied to the unit price only; the line is not discounted again."""
        payment_plan = PaymentPlan(json_ext={"calculation_rule": {"commission_rate": 5}})
        commission = self.rule.calculate(Premium(amount=200), payment_plan=payment_plan)
        line = {"quantity": 1}
        PremiumToBillItemConverter.build_unit_price(line, commission)
        PremiumToBillItemConverter.build_discount(line, payment_plan)
        PremiumToBillItemConverter.build_amounts(line)

        self.assertEqual(line["discount"], 0)
        self.assertEqual(line["amount_total"], 10)
