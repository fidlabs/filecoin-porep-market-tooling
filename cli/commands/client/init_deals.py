import sys

import click

from cli import utils
from cli.commands import utils as commands_utils
from cli.commands.client import _utils as client_utils
from cli.commands.client._client import client_address, client_signer
from cli.services.contracts.filecoin_pay import FileCoinPay
from cli.services.contracts.filecoinpay_validator import FileCoinPayValidator
from cli.services.contracts.porep_market import PoRepMarketDeal, PoRepMarketDealState, PoRepMarket
from cli.services.contracts.porep_market_view_helper import PoRepMarketViewHelper
from cli.services.contracts.usdc_token import USDCToken
from cli.services.contracts.validator_factory import ValidatorFactory
from cli.services.self_update import SelfUpdateService
from cli.services.web3_service import Web3Service


@click.command()
@click.argument("deal_id", type=click.IntRange(min=1), required=False)
def init_deals(deal_id: int | None = None):
    """
    Interactively initialize ACCEPTED deals.

    DEAL_ID - Optional deal ID to initialize. If not provided, will initialize all ACCEPTED deals for the client address.

    \b
    1. Deploy and initialize validator,
    2. deposit FileCoinPay funds and approve operator,
    3. initialize FileCoinPay rail.
    """

    SelfUpdateService.check_and_prompt(manual=False)
    Web3Service().wait_for_pending_transactions(client_address())

    if deal_id is not None:
        deal = PoRepMarketViewHelper().get_deal_view(deal_id)

        if deal.deal.client_address != client_address():
            raise click.ClickException(f"Deal ID {deal_id} client address {deal.deal.client_address} "
                                       f"does not match with connected client address {client_address()}")

        if deal.deal.state != PoRepMarketDealState.ACCEPTED:
            raise click.ClickException(f"Deal ID {deal_id} is in state {deal.deal.state} != ACCEPTED")

        accepted_deals = [deal.deal]
    else:
        accepted_deals = commands_utils.get_client_deals(client_address(), PoRepMarketDealState.ACCEPTED)
        click.echo(f"Found {len(accepted_deals)} ACCEPTED deals for client address {client_address()}")

    for deal in accepted_deals:
        assert deal.deal_id
        click.echo(f"\nDeal ID {deal.deal_id}: {utils.json_pretty(deal)}")

        try:
            _deploy_and_set_validator(deal.deal_id)
            Web3Service().wait_for_pending_transactions(client_address())

            _deposit_and_approve_operator(deal.deal_id)
            Web3Service().wait_for_pending_transactions(client_address())

            _initialize_rail(deal.deal_id)
            Web3Service().wait_for_pending_transactions(client_address())
        except click.ClickException as e:
            e.show()
            continue
        except click.Abort:
            click.echo("\nSkipped this deal.")
            continue

    click.echo("\n\nAll done!")
    click.echo(f"\nRun `{sys.argv[0]} client deposit-for-deals` to make sure you have enough FileCoinPay funds deposited for all your deals.")


def _deploy_and_set_validator(deal_id: int):
    deal = PoRepMarketViewHelper().get_deal_view(deal_id)

    if deal.deal.client_address != client_address():
        raise click.ClickException(f"Deal ID {deal_id} client address {deal.deal.client_address} does not match from address {client_address()}")

    if deal.deal.state != PoRepMarketDealState.ACCEPTED:
        raise click.ClickException(f"Deal ID {deal.deal.deal_id} is in state {deal.deal.state} != ACCEPTED")

    if __get_validator_address_for_deal(deal.deal):
        click.echo(f"\nValidator already set for deal ID {deal.deal.deal_id}: {deal.deal.validator_address}")
        return

    utils.confirm(f"\nDeploy and set validator for deal ID {deal.deal.deal_id}?", default=True, abort=True)

    tx_hash = ValidatorFactory().create(deal.deal.deal_id, client_signer()).tx_hash
    click.echo(f"Validator deployed for deal ID {deal.deal.deal_id}: {tx_hash}")


def _deposit_and_approve_operator(deal_id: int):
    deal = PoRepMarketViewHelper().get_deal_view(deal_id)
    payment_token = USDCToken(deal.payment.payment_token)

    if not __get_validator_address_for_deal(deal.deal):
        raise click.ClickException(f"Validator not found for deal ID {deal.deal.deal_id}, cannot deposit and approve operator")

    operator_approval = FileCoinPay().get_operator_approval(payment_token.address(),
                                                            client_address(),
                                                            deal.deal.validator_address)

    if operator_approval.is_approved:
        click.echo(f"\nOperator already approved for deal ID {deal.deal.deal_id}: {operator_approval}")
        return

    token_decimals = payment_token.decimals()
    token_symbol = payment_token.symbol()

    filecoinpay_account = FileCoinPay().get_account(payment_token.address(), client_address())
    filecoinpay_available_funds = filecoinpay_account.funds - filecoinpay_account.lockup_current
    filecoinpay_available_funds_str = utils.str_from_wei(filecoinpay_available_funds, token_decimals)

    token_balance = payment_token.balance_of(client_address())
    token_balance_str = utils.str_from_wei(token_balance, token_decimals)

    deposit_amount = commands_utils.calculate_deposit_amount(deal.terms.requested_size_bytes,
                                                             deal.payment.price_per_32_gib_per_month,
                                                             PoRepMarket().get_sector_size_bytes())
    deposit_amount_str = utils.str_from_wei(deposit_amount, token_decimals)

    if token_balance < deposit_amount:
        raise click.ClickException(f"Address {client_address()} {token_symbol} balance {token_balance_str} is "
                                   f"less than required deposit {deposit_amount_str} {token_symbol} for deal ID {deal.deal.deal_id}")

    # These parameters control operator approval limits in the FileCoinPay contract, not EIP-2612 permits
    # Setting all three to MAX_UINT256 grants the operator unrestricted control over payment rates, fund lockup amounts, and lockup periods
    # Once we set those params, we cannot increase them
    rate_allowance = utils.MAX_UINT256
    lockup_allowance = utils.MAX_UINT256
    max_lockup_period = utils.MAX_UINT256

    # TODO LATER deposit 0 if enough filecoinpay funds? deposit only missing funds?
    # This code now deposit full deposit_amount for the deal only logging the filecoinpay_available_funds
    # This is intentional
    utils.confirm(
        f"\nDeposit {deposit_amount_str} {token_symbol} for deal ID {deal.deal.deal_id} from address {client_address()} and approve operator\n"
        f"  Current token balance: {token_balance_str} {token_symbol}\n"
        f"  Current FileCoinPay account available funds: {filecoinpay_available_funds_str} {token_symbol}\n"
        f"  Operator (Validator) address: {deal.deal.validator_address}\n"
        f"  Rate allowance: {'MAX_UINT256' if rate_allowance == utils.MAX_UINT256 else rate_allowance}\n"
        f"  Lockup allowance: {'MAX_UINT256' if lockup_allowance == utils.MAX_UINT256 else lockup_allowance}\n"
        f"  Max lockup period: {'MAX_UINT256' if max_lockup_period == utils.MAX_UINT256 else max_lockup_period}", abort=True)

    click.echo()

    permit_deadline = client_utils.get_filecoin_permit_deadline()
    signed_msg = client_utils.sign_filecoinpay_permit(deposit_amount, permit_deadline, payment_token)

    tx_hash = FileCoinPay().deposit_with_permit_and_approve_operator(payment_token.address(),
                                                                     client_address(),
                                                                     deposit_amount,
                                                                     permit_deadline,
                                                                     signed_msg.v, utils.uint_to_bytes(signed_msg.r), utils.uint_to_bytes(signed_msg.s),
                                                                     deal.deal.validator_address,
                                                                     rate_allowance,
                                                                     lockup_allowance,
                                                                     max_lockup_period,
                                                                     client_signer()).tx_hash

    click.echo(f"Deposited {deposit_amount_str} {token_symbol} and operator approved for deal ID {deal.deal.deal_id}: {tx_hash}")


def _initialize_rail(deal_id: int):
    deal = PoRepMarketViewHelper().get_deal_view(deal_id)

    if not __get_validator_address_for_deal(deal.deal):
        raise click.ClickException(f"Validator not found for deal ID {deal.deal.deal_id}, cannot initialize rail")

    operator_approval = FileCoinPay().get_operator_approval(deal.payment.payment_token,
                                                            client_address(),
                                                            deal.deal.validator_address)

    if not operator_approval.is_approved:
        raise click.ClickException(f"Operator not approved for deal ID {deal.deal.deal_id}, cannot initialize rail")

    if deal.deal.rail_id:
        click.echo(f"\nRail already initialized for deal ID {deal.deal.deal_id}: {deal.deal.rail_id}")
        return

    utils.confirm(f"\nInitialize FileCoinPay rail for deal ID {deal.deal.deal_id}?", default=True, abort=True)

    tx_hash = FileCoinPayValidator(deal.deal.validator_address).create_rail(client_signer()).tx_hash

    click.echo(f"FileCoinPay rail initialized for deal ID {deal.deal.deal_id}: {tx_hash}")


def __get_validator_address_for_deal(deal: PoRepMarketDeal) -> str:
    result = ValidatorFactory().get_instance(deal.deal_id)

    if result != deal.validator_address:
        raise click.ClickException(f"Validator address {result} does not match expected {deal.validator_address} for deal ID {deal.deal_id}")

    return result
