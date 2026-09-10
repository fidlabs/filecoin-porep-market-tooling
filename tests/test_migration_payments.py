from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, patch

import click

from cli import utils
from cli.commands.client import _migration_payments as payments


OWNER = "0x1111111111111111111111111111111111111111"
OTHER = "0x2222222222222222222222222222222222222222"
TOKEN = "0x3333333333333333333333333333333333333333"
PAY = "0x4444444444444444444444444444444444444444"


class MigrationPaymentsTests(unittest.TestCase):
    def setUp(self):
        self.signer = MagicMock()
        self.signer.address.return_value = OWNER
        self.token = MagicMock()
        self.token.address.return_value = TOKEN
        self.token.balance_of.return_value = 2_000_000
        self.token.allowance.return_value = 0
        self.pay = MagicMock()
        self.pay.address.return_value = PAY
        self.pay.deposit.return_value = SimpleNamespace(tx_hash="deposit")
        self.pay.set_operator_approval.return_value = SimpleNamespace(tx_hash="approval")
        self.pay.get_operator_approval.return_value = SimpleNamespace(
            is_approved=False, rate_allowance=0, lockup_allowance=0, max_lockup_period=0
        )

    def test_shortfall_reuses_projected_available_funds(self):
        for available, expected in [(0, 1_500_000), (500_000, 1_000_000), (2_000_000, 0)]:
            self.pay.get_account_info_if_settled.return_value = SimpleNamespace(available_funds=available)
            with self.subTest(available=available), patch.object(payments, "FileCoinPay", return_value=self.pay):
                self.assertEqual(payments.funding_shortfall(1_500_000, self.token, OWNER), expected)

    def test_standard_deposit_uses_shortfall_amount_and_existing_allowance(self):
        self.token.allowance.return_value = 1_000_000
        with patch.object(payments, "FileCoinPay", return_value=self.pay):
            result = payments.deposit_to_filecoinpay(1_000_000, self.token, OWNER, self.signer)
        self.assertEqual(result, "deposit")
        self.token.approve.assert_not_called()
        self.pay.deposit.assert_called_once_with(TOKEN, OWNER, 1_000_000, self.signer)

    def test_standard_deposit_approves_and_rejects_insufficient_funds(self):
        with patch.object(payments, "FileCoinPay", return_value=self.pay):
            payments.deposit_to_filecoinpay(1_000_000, self.token, OWNER, self.signer)
        self.token.approve.assert_called_once_with(PAY, 1_000_000, self.signer)

        self.token.balance_of.return_value = 1
        with self.assertRaisesRegex(click.ClickException, "Insufficient token balance"):
            payments.deposit_to_filecoinpay(2, self.token, OWNER, self.signer)

    def test_owner_guard_prevents_payment_writes(self):
        self.signer.address.return_value = OTHER
        with patch.object(payments, "FileCoinPay", return_value=self.pay), self.assertRaises(click.ClickException):
            payments.deposit_to_filecoinpay(1, self.token, OWNER, self.signer)
        self.token.approve.assert_not_called()
        self.pay.deposit.assert_not_called()

    def test_operator_approval_is_idempotent_only_at_maximum_limits(self):
        self.pay.get_operator_approval.return_value = SimpleNamespace(
            is_approved=True,
            rate_allowance=utils.MAX_UINT256,
            lockup_allowance=utils.MAX_UINT256,
            max_lockup_period=utils.MAX_UINT256,
        )
        with patch.object(payments, "FileCoinPay", return_value=self.pay):
            self.assertIsNone(payments.approve_filecoinpay_operator(self.token, OTHER, OWNER, self.signer))
        self.pay.set_operator_approval.assert_not_called()
        self.pay.get_operator_approval.return_value.is_approved = False
        with patch.object(payments, "FileCoinPay", return_value=self.pay):
            payments.approve_filecoinpay_operator(self.token, OTHER, OWNER, self.signer)
        self.pay.set_operator_approval.assert_called_once_with(
            TOKEN, OTHER, True, utils.MAX_UINT256, utils.MAX_UINT256, utils.MAX_UINT256, self.signer
        )


if __name__ == "__main__":
    unittest.main()
