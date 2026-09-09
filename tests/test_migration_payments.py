import unittest
from importlib import import_module
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import click

from cli import utils
from cli.commands import utils as commands_utils
from cli.commands.client import _utils as client_utils
from cli.services.contracts.filecoin_pay import FileCoinPay

init_deals = import_module("cli.commands.client.init_deals")

# pylint: disable=protected-access


OWNER = "0x1111111111111111111111111111111111111111"
OPERATOR = "0x2222222222222222222222222222222222222222"
TOKEN_ADDRESS = "0x3333333333333333333333333333333333333333"
FILECOIN_PAY_ADDRESS = "0x4444444444444444444444444444444444444444"


def tx(tx_hash):
    return SimpleNamespace(tx_hash=tx_hash)


def deal_view():
    return SimpleNamespace(
        deal=SimpleNamespace(
            deal_id=7,
            validator_address=OPERATOR,
        ),
        terms=SimpleNamespace(requested_size_bytes=32 * 1024 ** 3),
        payment=SimpleNamespace(
            payment_token=TOKEN_ADDRESS,
            price_per_32_gib_per_month=1_500_000,
        ),
    )


class InitDealFundingTests(unittest.TestCase):
    def setUp(self):
        self.deal = deal_view()
        self.token = MagicMock()
        self.token.address.return_value = TOKEN_ADDRESS
        self.token.decimals.return_value = 6
        self.token.symbol.return_value = "USDFC"
        self.signer = MagicMock()
        self.signer.address.return_value = OWNER

    def patches(self, available_funds):
        return [
            patch.object(init_deals, "PoRepMarketViewHelper", return_value=SimpleNamespace(get_deal_view=MagicMock(return_value=self.deal))),
            patch.object(init_deals, "ERC20Contract", return_value=self.token),
            patch.object(
                client_utils,
                "get_filecoinpay_funding_quote",
                return_value=client_utils.FileCoinPayFundingQuote(
                    required_amount=1_500_000,
                    available_funds=available_funds,
                    deposit_amount=max(1_500_000 - available_funds, 0),
                ),
            ),
            patch.object(init_deals, "PoRepMarket", return_value=SimpleNamespace(get_sector_size_bytes=MagicMock(return_value=32 * 1024 ** 3))),
            patch.object(init_deals, "ValidatorFactory", return_value=SimpleNamespace(get_instance=MagicMock(return_value=OPERATOR))),
            patch.object(init_deals, "client_address", return_value=OWNER),
            patch.object(init_deals, "client_signer", return_value=self.signer),
        ]

    def test_existing_available_funds_need_no_deposit(self):
        patches = self.patches(1_500_000)
        with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5], patches[6], \
                patch.object(client_utils, "deposit_to_filecoinpay") as deposit:
            result = init_deals._deposit_for_deal(7, prompt=False)

        self.assertIsNone(result)
        deposit.assert_not_called()

    def test_deposits_only_30_day_shortfall(self):
        patches = self.patches(500_000)
        with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5], patches[6], \
                patch.object(client_utils, "deposit_to_filecoinpay", return_value="deposit-tx") as deposit:
            result = init_deals._deposit_for_deal(7, prompt=False)

        self.assertEqual(result, "deposit-tx")
        deposit.assert_called_once_with(
            1_000_000,
            self.token,
            owner=OWNER,
            signer=self.signer,
            prompt=False,
        )

    def test_already_initialized_deal_skips_every_initialization_action(self):
        initialized = deal_view()
        initialized.deal.client_address = OWNER
        initialized.deal.rail_id = 42

        with patch.object(
                init_deals,
                "PoRepMarketViewHelper",
                return_value=SimpleNamespace(get_deal_view=MagicMock(return_value=initialized))), \
                patch.object(init_deals, "client_address", return_value=OWNER), \
                patch.object(init_deals, "_deploy_and_set_validator") as deploy_validator, \
                patch.object(init_deals, "_deposit_for_deal") as deposit, \
                patch.object(init_deals, "_approve_operator") as approve_operator, \
                patch.object(init_deals, "_initialize_rail") as initialize_rail, \
                patch.object(client_utils, "get_filecoinpay_funding_quote") as quote:
            init_deals._initialize_deal(7)

        deploy_validator.assert_not_called()
        quote.assert_not_called()
        deposit.assert_not_called()
        approve_operator.assert_not_called()
        initialize_rail.assert_not_called()


class StandardErc20FundingTests(unittest.TestCase):
    def setUp(self):
        self.signer = MagicMock()
        self.signer.address.return_value = OWNER
        self.token = MagicMock()
        self.token.address.return_value = TOKEN_ADDRESS
        self.token.decimals.return_value = 6
        self.token.symbol.return_value = "USDFC"
        self.token.balance_of.return_value = 2_000_000
        self.token.allowance.return_value = 0
        self.token.approve.return_value = tx("approve-tx")
        self.filecoin_pay = MagicMock()
        self.filecoin_pay.address.return_value = FILECOIN_PAY_ADDRESS
        self.filecoin_pay.deposit.return_value = tx("deposit-tx")

    def test_quotes_shortfall_from_unlocked_account_funds(self):
        self.filecoin_pay.get_account_info_if_settled.return_value = SimpleNamespace(
            available_funds=750_000,
        )

        with patch.object(client_utils, "FileCoinPay", return_value=self.filecoin_pay):
            quote = client_utils.get_filecoinpay_funding_quote(1_500_000, self.token, OWNER)

        self.assertEqual(quote.required_amount, 1_500_000)
        self.assertEqual(quote.available_funds, 750_000)
        self.assertEqual(quote.deposit_amount, 750_000)
        self.filecoin_pay.get_account_info_if_settled.assert_called_once_with(TOKEN_ADDRESS, OWNER)

    def test_quote_uses_available_funds_after_simulated_accrual(self):
        self.filecoin_pay.get_account_info_if_settled.return_value = SimpleNamespace(
            available_funds=250_000,
        )

        with patch.object(client_utils, "FileCoinPay", return_value=self.filecoin_pay):
            quote = client_utils.get_filecoinpay_funding_quote(1_500_000, self.token, OWNER)

        self.assertEqual(quote.deposit_amount, 1_250_000)
        self.filecoin_pay.get_account.assert_not_called()

    def test_account_info_wrapper_maps_projected_available_funds(self):
        service = object.__new__(FileCoinPay)
        service.contract = MagicMock()
        service.call_contract = MagicMock(return_value=(99, 2_000_000, 250_000, 12))

        account = service.get_account_info_if_settled(TOKEN_ADDRESS, OWNER)

        self.assertEqual(account.funded_until_epoch, 99)
        self.assertEqual(account.current_funds, 2_000_000)
        self.assertEqual(account.available_funds, 250_000)
        self.assertEqual(account.current_lockup_rate, 12)
        service.contract.functions.getAccountInfoIfSettled.assert_called_once_with(TOKEN_ADDRESS, OWNER)

    def test_uses_erc20_approve_then_standard_deposit_with_exact_amount(self):
        with patch.object(client_utils, "FileCoinPay", return_value=self.filecoin_pay), \
                patch.object(client_utils.click, "echo") as echo:
            result = client_utils.deposit_to_filecoinpay(
                1_500_000,
                self.token,
                owner=OWNER,
                signer=self.signer,
                prompt=False,
            )

        self.assertEqual(result, "deposit-tx")
        self.token.approve.assert_called_once_with(FILECOIN_PAY_ADDRESS, 1_500_000, self.signer)
        self.filecoin_pay.deposit.assert_called_once_with(TOKEN_ADDRESS, OWNER, 1_500_000, self.signer)
        output = "\n".join(call.args[0] for call in echo.call_args_list if call.args)
        self.assertIn("Deposited 1.500000 USDFC", output)

    def test_reuses_sufficient_erc20_allowance(self):
        self.token.allowance.return_value = 1_500_000

        with patch.object(client_utils, "FileCoinPay", return_value=self.filecoin_pay):
            client_utils.deposit_to_filecoinpay(
                1_500_000,
                self.token,
                owner=OWNER,
                signer=self.signer,
                prompt=False,
            )

        self.token.approve.assert_not_called()
        self.filecoin_pay.deposit.assert_called_once()

    def test_rejects_signer_that_does_not_own_account(self):
        self.signer.address.return_value = OPERATOR

        with self.assertRaises(click.ClickException), \
                patch.object(client_utils, "FileCoinPay", return_value=self.filecoin_pay):
            client_utils.deposit_to_filecoinpay(
                1,
                self.token,
                owner=OWNER,
                signer=self.signer,
                prompt=False,
            )

        self.token.approve.assert_not_called()
        self.filecoin_pay.deposit.assert_not_called()


class OperatorApprovalTests(unittest.TestCase):
    def setUp(self):
        self.signer = MagicMock()
        self.signer.address.return_value = OWNER
        self.token = MagicMock()
        self.token.address.return_value = TOKEN_ADDRESS
        self.filecoin_pay = MagicMock()
        self.filecoin_pay.get_operator_approval.return_value = SimpleNamespace(
            is_approved=False,
            rate_allowance=0,
            lockup_allowance=0,
            max_lockup_period=0,
        )
        self.filecoin_pay.set_operator_approval.return_value = tx("operator-tx")

    def test_sets_new_operator_approval_in_separate_transaction(self):
        with patch.object(client_utils, "FileCoinPay", return_value=self.filecoin_pay):
            result = client_utils.approve_filecoinpay_operator(
                self.token,
                OPERATOR,
                OWNER,
                self.signer,
                prompt=False,
            )

        self.assertEqual(result, "operator-tx")
        self.filecoin_pay.set_operator_approval.assert_called_once_with(
            TOKEN_ADDRESS,
            OPERATOR,
            True,
            utils.MAX_UINT256,
            utils.MAX_UINT256,
            utils.MAX_UINT256,
            self.signer,
        )

    def test_existing_operator_approval_is_not_repeated(self):
        self.filecoin_pay.get_operator_approval.return_value = SimpleNamespace(
            is_approved=True,
            rate_allowance=utils.MAX_UINT256,
            lockup_allowance=utils.MAX_UINT256,
            max_lockup_period=utils.MAX_UINT256,
        )

        with patch.object(client_utils, "FileCoinPay", return_value=self.filecoin_pay):
            result = client_utils.approve_filecoinpay_operator(
                self.token,
                OPERATOR,
                OWNER,
                self.signer,
                prompt=False,
            )

        self.assertIsNone(result)
        self.filecoin_pay.set_operator_approval.assert_not_called()

    def test_existing_low_allowances_are_updated(self):
        self.filecoin_pay.get_operator_approval.return_value = SimpleNamespace(
            is_approved=True,
            rate_allowance=1,
            lockup_allowance=2,
            max_lockup_period=3,
        )

        with patch.object(client_utils, "FileCoinPay", return_value=self.filecoin_pay):
            client_utils.approve_filecoinpay_operator(
                self.token,
                OPERATOR,
                OWNER,
                self.signer,
                prompt=False,
            )

        self.filecoin_pay.set_operator_approval.assert_called_once()


class LegacyClaimVisibilityTests(unittest.TestCase):
    def test_fetches_all_provider_claims_then_intersects_confirmed_ids(self):
        deal = SimpleNamespace(provider_id=1234)
        web3 = MagicMock()
        web3.state_get_claims.return_value = {
            "10": {"Client": 999},
            "11": {"Client": 888},
        }

        with patch.object(commands_utils, "get_deal_claim_ids", return_value=[10]), \
                patch.object(commands_utils, "Web3Service", return_value=web3):
            claims = commands_utils.get_deal_claims(deal)

        self.assertEqual(claims, {"10": {"Client": 999}})
        web3.state_get_claims.assert_called_once_with(1234)


if __name__ == "__main__":
    unittest.main()
