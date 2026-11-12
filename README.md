# calcrule to calculate the EO commission calcultion

## description

This calculation will, for the selected level and product, calculate how much the insurance need to pay the commission to EO

it creates a bill based on the commissions part of the BR 

##design 

https://openimis.atlassian.net/wiki/spaces/OP/pages/3045818369/Payment+plan+calculation+rule+Commission

## Parameters
The commission is `calculation_rule.commission_rate` percent of each contribution (payment plan
`json_ext`). A payment plan without that parameter (or without `json_ext`) gives no commission
(0) instead of failing.
