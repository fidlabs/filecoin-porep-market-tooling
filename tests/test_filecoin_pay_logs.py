import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock

from cli.services.contracts.filecoin_pay import FileCoinPay
from cli.services.web3_service import EthAddress

TOKEN = EthAddress("0x80B98d3aa09ffff255c3ba4A241111Ff1262F045")
CLIENT = EthAddress("0x1111111111111111111111111111111111111111")
PAYEE = EthAddress("0x2222222222222222222222222222222222222222")
OTHER = EthAddress("0x3333333333333333333333333333333333333333")


def filecoin_pay(calls=None, logs=None) -> FileCoinPay:
    # a FileCoinPay without RPC: contract calls and event logs come from the given stubs
    pay = FileCoinPay.__new__(FileCoinPay)
    pay.call_contract = lambda call: calls.pop(0)
    pay.contract = MagicMock()
    for event, entries in (logs or {}).items():
        getattr(pay.contract.events, event).return_value.get_logs.side_effect = entries
    return pay


class _LogArgs(SimpleNamespace):
    # web3 event args support both attribute and item access (`from` is a keyword, so it is read as args["from"])
    def __getitem__(self, key):
        return getattr(self, key)


def log(**args):
    return SimpleNamespace(args=_LogArgs(**args))


class FileCoinPayLogTests(unittest.TestCase):
    def test_payer_rails_are_read_across_short_and_empty_pages(self):
        # the contract skips finalized rails inside a page, so pages can be short or empty before the end
        pay = filecoin_pay(calls=[([(1, False, 0)], 100, 250), ([], 200, 250), ([(7, False, 0), (9, False, 0)], 300, 250)])
        self.assertEqual(pay.get_payer_rail_ids(TOKEN, PAYEE), [1, 7, 9])

    def test_payer_rails_stop_if_the_offset_does_not_advance(self):
        pay = filecoin_pay(calls=[([(1, False, 0)], 0, 5)])
        self.assertEqual(pay.get_payer_rail_ids(TOKEN, PAYEE), [1])

    def test_deposits_count_only_client_to_payee(self):
        entries = [log(amount=5, **{"from": CLIENT, "to": PAYEE}),
                   log(amount=7, **{"from": OTHER, "to": PAYEE}),
                   log(amount=11, **{"from": CLIENT, "to": OTHER})]
        pay = filecoin_pay(logs={"DepositRecorded": [entries]})
        self.assertEqual(pay.get_deposited_amount(TOKEN, CLIENT, PAYEE, 100, 200), 5)

    def test_one_time_payments_sum_the_gross_amount_on_the_given_rails(self):
        entries = [log(railId=7, netPayeeAmount=90, operatorCommission=0, networkFee=10),
                   log(railId=8, netPayeeAmount=1000, operatorCommission=0, networkFee=0)]
        pay = filecoin_pay(logs={"RailOneTimePaymentProcessed": [entries]})
        self.assertEqual(pay.get_one_time_payments([7], 100, 200), 100)
        _, kwargs = pay.contract.events.RailOneTimePaymentProcessed.return_value.get_logs.call_args
        self.assertEqual(kwargs["argument_filters"], {"railId": [7]})

    def test_many_rails_are_filtered_locally(self):
        rails = list(range(60))
        entries = [log(railId=59, netPayeeAmount=3, operatorCommission=1, networkFee=1),
                   log(railId=99, netPayeeAmount=50, operatorCommission=0, networkFee=0)]
        pay = filecoin_pay(logs={"RailOneTimePaymentProcessed": [entries]})
        self.assertEqual(pay.get_one_time_payments(rails, 100, 200), 5)
        _, kwargs = pay.contract.events.RailOneTimePaymentProcessed.return_value.get_logs.call_args
        self.assertIsNone(kwargs["argument_filters"])


if __name__ == "__main__":
    unittest.main()
