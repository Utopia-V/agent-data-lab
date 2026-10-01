"""Host-side reference for composed payment analysis; never mounted for models."""

import csv
from datetime import date,timedelta
from decimal import Decimal
import json
from pathlib import Path


CLARIFICATION="""
## Interpretation for the composed analysis experiment

Null and empty categorical restriction lists impose no restriction. Every row in
payments.csv is part of the analysis unless a question explicitly excludes it.
Monthly volume is the sum of eur_amount for the merchant in that natural calendar
month. Monthly fraud percentage is 100 times the fraudulent-dispute eur_amount
sum divided by the total eur_amount sum, using all rows in that merchant-month,
even when the requested result concerns only one day. Use the input decimal euro
amounts without rounding intermediate sums. A fee rule applies when all of its
specified restrictions hold. Returning applicable rule IDs means the union of
rules matching at least one transaction in the requested range. A per-rule audit
reports each applicable rule independently; it does not select a single winning
rule or add overlapping rules into an invoice total.
"""


def number(value):
    value=value.strip().lower().removesuffix('%')
    scale=1000 if value.endswith('k') else 1000000 if value.endswith('m') else 1
    return Decimal(value.removesuffix('k').removesuffix('m'))*scale


def in_range(constraint,value):
    if constraint is None: return True
    if constraint.startswith('<'): return value<number(constraint[1:])
    if constraint.startswith('>'): return value>number(constraint[1:])
    left,right=constraint.split('-')
    return number(left)<=value<=number(right)


def categorical(constraint,value):
    return constraint is None or constraint==[] or value in constraint


def audit(root,merchant_name,month,day=None):
    root=Path(root)
    merchant=next(row for row in json.loads((root/'merchant_data.json').read_text()) if row['merchant']==merchant_name)
    rules=json.loads((root/'fees.json').read_text(),parse_float=Decimal)
    with (root/'payments.csv').open() as source:
        payments=[row for row in csv.DictReader(source) if row['merchant']==merchant_name
            and row['year']=='2023' and (date(2023,1,1)+timedelta(days=int(row['day_of_year'])-1)).month==month]
    total=sum((Decimal(row['eur_amount']) for row in payments),Decimal(0))
    fraud=sum((Decimal(row['eur_amount']) for row in payments if row['has_fraudulent_dispute']=='True'),Decimal(0))
    fraud_percent=100*fraud/total if total else Decimal(0)
    candidates=[row for row in payments if day is None or int(row['day_of_year'])==day]
    result=[]
    for rule in rules:
        if not categorical(rule['account_type'],merchant['account_type']): continue
        if not categorical(rule['merchant_category_code'],merchant['merchant_category_code']):continue
        capture=rule['capture_delay'];actual_capture=merchant['capture_delay']
        if capture in {'manual','immediate'}:
            if capture!=actual_capture:continue
        elif capture is not None:
            if actual_capture in {'manual','immediate'} or not in_range(capture,Decimal(actual_capture)):continue
        if not in_range(rule['monthly_volume'],total) or not in_range(rule['monthly_fraud_level'],fraud_percent):continue
        matches=[]
        for row in candidates:
            if rule['card_scheme'] is not None and row['card_scheme']!=rule['card_scheme']:continue
            if not categorical(rule['aci'],row['aci']):continue
            if rule['is_credit'] is not None and rule['is_credit']!=(row['is_credit']=='True'):continue
            if rule['intracountry'] is not None and rule['intracountry']!=(row['issuing_country']==row['acquirer_country']):continue
            matches.append(row)
        if not matches:continue
        amount=sum((Decimal(row['eur_amount']) for row in matches),Decimal(0))
        fee=Decimal(rule['fixed_amount'])*len(matches)+Decimal(rule['rate'])*amount/10000
        result.append({'fee_id':rule['ID'],'card_scheme':rule['card_scheme'],'transactions':len(matches),
                       'amount_eur':format(amount,'.2f'),'fee_eur':format(fee,'.14f')})
    return sorted(result,key=lambda row:row['fee_id'])


def add_month_background(root):
    path=Path(root)/'payments.csv'
    with path.open() as source:
        reader=csv.DictReader(source);fields=reader.fieldnames
        row=next(row for row in reader if row['merchant']=='Belles_cookbook_store')
    row.update(psp_reference='90000000001',year='2023',day_of_year='20',eur_amount='1000000.00',
               has_fraudulent_dispute='False',is_refused_by_adyen='False')
    with path.open('a') as destination:
        csv.DictWriter(destination,fieldnames=fields).writerow(row)


def rate_delta(root,merchant,month,fee_id,new_rate):
    rows=audit(root,merchant,month)
    item=next((row for row in rows if row['fee_id']==fee_id),None)
    if item is None:return '0.00000000000000'
    rule=next(row for row in json.loads((Path(root)/'fees.json').read_text()) if row['ID']==fee_id)
    return format((Decimal(new_rate)-Decimal(rule['rate']))*Decimal(item['amount_eur'])/10000,'.14f')
