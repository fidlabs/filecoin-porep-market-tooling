import sys

import click

from cli import utils
from cli.commands import utils as commands_utils
from cli.commands.client import _utils as client_utils
from cli.commands.client._client import client_address, client_signer
from cli.services.contracts.erc20_contract import ERC20Contract
from cli.services.contracts.filecoin_pay import FileCoinPay
from cli.services.contracts.filecoinpay_validator import FileCoinPayValidator
from cli.services.contracts.porep_market import PoRepMarketDeal, PoRepMarketDealState, PoRepMarket
from cli.services.contracts.porep_market_view_helper import PoRepMarketViewHelper
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
    2. fund the FileCoinPay account and approve the validator as operator,
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
            _initialize_deal(deal.deal_id)
        except click.ClickException as e:
            e.show()
            continue
        except click.Abort:
            click.echo("\nSkipped this deal.")
            continue

    click.echo("\n\nAll done!")
    click.echo(f"\nRun `{sys.argv[0]} client deposit-for-deals` to make sure you have enough FileCoinPay funds deposited for all your deals.")


def _initialize_deal(deal_id: int) -> None:
    deal = PoRepMarketViewHelper().get_deal_view(deal_id).deal

    if deal.client_address != client_address():
        raise click.ClickException(f"Deal ID {deal_id} client address {deal.client_address} "
                                   f"does not match with connected client address {client_address()}")

    if deal.rail_id:
        click.echo(f"Deal ID {deal_id} already has FileCoinPay rail {deal.rail_id}; no initialization needed")
        return

    _deploy_and_set_validator(deal_id)
    Web3Service().wait_for_pending_transactions(client_address())

    _deposit_for_deal(deal_id)
    Web3Service().wait_for_pending_transactions(client_address())

    _approve_operator(deal_id)
    Web3Service().wait_for_pending_transactions(client_address())

    _initialize_rail(deal_id)
    Web3Service().wait_for_pending_transactions(client_address())


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


def _deposit_for_deal(deal_id: int, prompt: bool = True) -> str | None:
    deal = PoRepMarketViewHelper().get_deal_view(deal_id)
    payment_token = ERC20Contract(deal.payment.payment_token)

    if not __get_validator_address_for_deal(deal.deal):
        raise click.ClickException(f"Validator not found for deal ID {deal.deal.deal_id}, cannot deposit")

    token_decimals = payment_token.decimals()
    token_symbol = payment_token.symbol()

    required_amount = commands_utils.calculate_deposit_amount(
        deal.terms.requested_size_bytes,
        deal.payment.price_per_32_gib_per_month,
        PoRepMarket().get_sector_size_bytes(),
        deposit_for_months=1,
    )
    funding_quote = client_utils.get_filecoinpay_funding_quote(required_amount, payment_token, client_address())
    deposit_amount = funding_quote.deposit_amount
    deposit_amount_str = utils.str_from_wei(deposit_amount, token_decimals)
    required_amount_str = utils.str_from_wei(required_amount, token_decimals)
    available_funds_str = utils.str_from_wei(funding_quote.available_funds, token_decimals)

    click.echo(f"\nFileCoinPay available funds: {available_funds_str} {token_symbol}")
    click.echo(f"Required funds for deal ID {deal.deal.deal_id} for 30 days: {required_amount_str} {token_symbol}")

    if deposit_amount <= 0:
        click.echo(f"Existing FileCoinPay funds cover deal ID {deal.deal.deal_id}; no deposit needed")
        return None

    click.echo(f"FileCoinPay funding shortfall: {deposit_amount_str} {token_symbol}")
    return client_utils.deposit_to_filecoinpay(
        deposit_amount,
        payment_token,
        owner=client_address(),
        signer=client_signer(),
        prompt=prompt,
    )


def _approve_operator(deal_id: int, prompt: bool = True) -> str | None:
    deal = PoRepMarketViewHelper().get_deal_view(deal_id)

    if not __get_validator_address_for_deal(deal.deal):
        raise click.ClickException(f"Validator not found for deal ID {deal.deal.deal_id}, cannot approve operator")

    return client_utils.approve_filecoinpay_operator(
        ERC20Contract(deal.payment.payment_token),
        deal.deal.validator_address,
        client_address(),
        client_signer(),
        prompt=prompt,
    )


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
