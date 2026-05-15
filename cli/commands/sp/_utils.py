import click

from cli import utils
from cli.commands import utils as commands_utils
from cli.commands.sp._sp import sp_private_key, sp_address
from cli.services.contracts.client_contract import ClientContract
from cli.services.contracts.filecoin_pay import FileCoinPay
from cli.services.contracts.usdc_token import USDCToken
from cli.services.contracts.porep_market import PoRepMarketDealState, PoRepMarketDealProposal, PoRepMarket
from cli.services.web3_service import Web3Service, EthAddress


def accept_deal(deal: PoRepMarketDealProposal, confirm_session_id: str | None = None) -> str:
    if deal.state != PoRepMarketDealState.PROPOSED:
        raise click.ClickException(f"Deal ID {deal.deal_id} is in state {deal.state} != PROPOSED")

    utils.confirm(f"Accepting deal ID {deal.deal_id}: {deal}", default=True, abort=True, session_id=confirm_session_id)

    tx_hash = PoRepMarket().accept_deal(deal.deal_id, sp_private_key())
    click.echo(f"Deal ID {deal.deal_id} accepted: {tx_hash}")

    return tx_hash


def reject_deal(deal: PoRepMarketDealProposal, confirm_session_id: str | None = None) -> str:
    if deal.state != PoRepMarketDealState.PROPOSED:
        raise click.ClickException(f"Deal ID {deal.deal_id} is in state {deal.state} != PROPOSED")

    utils.confirm(f"Rejecting deal ID {deal.deal_id}: {deal}", default=True, abort=True, session_id=confirm_session_id)

    tx_hash = PoRepMarket().reject_deal(deal.deal_id, sp_private_key())
    click.echo(f"Deal ID {deal.deal_id} rejected: {tx_hash}")

    return tx_hash


def get_deal_allocations(deal: PoRepMarketDealProposal) -> list[dict]:
    manifest = commands_utils.fetch_manifest(deal.manifest_location, show_manifest=False, quiet=True, retries=10)
    pieces = manifest[0]["pieces"]

    deal_allocations = ClientContract().get_client_allocation_ids_per_deal(deal.deal_id)
    state_allocations = Web3Service().state_get_allocations(ClientContract().address().to_actor_id())

    return commands_utils.match_deal_allocations(pieces, state_allocations, deal_allocations)


def get_deal_allocations_by_id(deal_id: int) -> list[dict]:
    return get_deal_allocations(PoRepMarket().get_deal_proposal(deal_id))

def get_balance(address: EthAddress) -> dict:
    usdc = USDCToken()
    return {
        "address": address,
        "token": usdc.balance_of(address),
        "filecoin_pay": FileCoinPay().get_account(usdc.address(), address).funds,
    }

def print_balance(snap: dict) -> None:
    usdc = USDCToken()
    decimals = usdc.decimals()
    name = usdc.name()
    click.echo(utils.json_pretty({
        "address": str(snap["address"]),
        "token": f"{utils.str_from_wei(snap['token'], decimals)} {name}",
        "filecoin_pay": f"{utils.str_from_wei(snap['filecoin_pay'], decimals)} {name}",
    }))


def print_delta(before: dict, after: dict) -> None:
    usdc = USDCToken()
    decimals = usdc.decimals()
    name = usdc.name()
    erc20_diff = after["token"] - before["token"]
    fp_diff = after["filecoin_pay"] - before["filecoin_pay"]

    def _format_sign(val):
        return "+" if val >= 0 else ""

    click.echo(utils.json_pretty({
        "address": str(before["address"]),
        "token": f"{_format_sign(erc20_diff)}{utils.str_from_wei(erc20_diff, decimals)} {name}",
        "filecoin_pay": f"{_format_sign(fp_diff)}{utils.str_from_wei(fp_diff, decimals)} {name}",
    }))


def withdraw(amount):
    sp = sp_address()

    click.echo("\n=== Balances BEFORE ===")
    before = get_balance(sp)
    print_balance(before)

    FileCoinPay().withdraw(amount, USDCToken().address(), sp_private_key())

    click.echo("\n=== Balances AFTER ===")
    after = get_balance(sp)
    print_balance(after)

    click.echo("\n=== Delta ===")
    print_delta(before, after)


def withdraw_to(amount, to_address: EthAddress):
    click.echo("\n=== Balances BEFORE ===")
    to_before = get_balance(to_address)
    print_balance(to_before)

    FileCoinPay().withdraw_to(to_address, amount, USDCToken().address(), sp_private_key())

    click.echo("\n=== Balances AFTER ===")
    to_after = get_balance(to_address)
    print_balance(to_after)

    click.echo("\n=== Delta ===")
    print_delta(to_before, to_after)

