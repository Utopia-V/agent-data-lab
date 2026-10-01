import csv
import json
from pathlib import Path
import tempfile
import unittest

from agent_data_lab.fee_reference import audit,rate_delta


class MonthlyDependency(unittest.TestCase):
    def test_another_day_changes_the_monthly_condition_but_another_merchant_does_not(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary)
            (root/'merchant_data.json').write_text(json.dumps([{'merchant':'A','account_type':'R','merchant_category_code':100,'capture_delay':'1'}]))
            common={'card_scheme':'S','account_type':[],'merchant_category_code':[],
                'capture_delay':None,'monthly_fraud_level':None,'is_credit':None,'aci':[],
                'intracountry':None,'fixed_amount':0.1,'rate':5}
            (root/'fees.json').write_text(json.dumps([dict(common,ID=42,monthly_volume='<100k'),dict(common,ID=43,monthly_volume='100k-1m')]))
            payment={'merchant':'A','year':'2023','day_of_year':'10','eur_amount':'30.00','has_fraudulent_dispute':'False',
                'card_scheme':'S','aci':'A','is_credit':'False','issuing_country':'NL','acquirer_country':'NL'}
            rows=[payment,dict(payment,day_of_year='20',eur_amount='20.00'),dict(payment,merchant='B',eur_amount='1000000.00')]
            def save():
                with (root/'payments.csv').open('w') as file:
                    writer=csv.DictWriter(file,fieldnames=list(payment));writer.writeheader();writer.writerows(rows)
            save()
            before=audit(root,'A',1,10)
            self.assertEqual([(r['fee_id'],r['transactions'],r['amount_eur']) for r in before],[(42,1,'30.00')])
            self.assertEqual(rate_delta(root,'A',1,42,1),'-0.02000000000000')
            rows.append(dict(payment,day_of_year='20',eur_amount='100000.00'));save()
            after=audit(root,'A',1,10)
            self.assertEqual([(r['fee_id'],r['transactions'],r['amount_eur']) for r in after],[(43,1,'30.00')])


if __name__=='__main__':unittest.main()
