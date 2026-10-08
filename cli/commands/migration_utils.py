import click

from cli import utils
from cli.services.contracts.erc20_contract import ERC20Contract
from cli.services.contracts.filecoin_pay import FileCoinPayRailView
from cli.services.migration import EPOCHS_IN_DAY, MigrationError, MigrationPair, MigrationService
from cli.services.web3_service import EthAddress

_TOKEN_INFO: dict[EthAddress, tuple[str, int]] = {}


def migration_service() -> MigrationService:
    try:
        return MigrationService(
            utils.get_env_required("POREP_MARKET_V1", required_type=EthAddress.from_any),
            source_chain_id=utils.get_env_required("POREP_MARKET_V1_CHAIN_ID", required_type=int),
        )
    except MigrationError as exc:
        raise click.ClickException(str(exc)) from exc


def load_pair(service: MigrationService, target_deal_id: int, source_deal_id: int, require_paying: bool = True) -> MigrationPair:
    try:
        return service.pair(target_deal_id, source_deal_id, require_paying=require_paying)
    except MigrationError as exc:
        raise click.ClickException(str(exc)) from exc


def token_info(token: EthAddress) -> tuple[str, int]:
    if token not in _TOKEN_INFO:
        contract = ERC20Contract(token)
        _TOKEN_INFO[token] = (contract.symbol(), contract.decimals())
    return _TOKEN_INFO[token]


def epochs_to_days(epochs: int) -> str:
    return f"{epochs / EPOCHS_IN_DAY:.1f} day(s)"


def gib(size_bytes: int) -> str:
    return f"{size_bytes / 2 ** 30:.2f} GiB"


def rail_daily_cost(rail: FileCoinPayRailView) -> str:
    symbol, decimals = token_info(rail.token)
    return f"{utils.str_from_wei(rail.payment_rate * EPOCHS_IN_DAY, decimals)} {symbol}/day"


def describe_rail(rail_id: int, rail: FileCoinPayRailView, current_epoch: int) -> str:
    lag = current_epoch - rail.settled_up_to
    state = f"terminated, ends at epoch {rail.end_epoch}" if rail.end_epoch else "open"
    return (f"rail {rail_id}: {state}, {rail_daily_cost(rail)}, "
            f"settled up to epoch {rail.settled_up_to} ({epochs_to_days(lag)} behind)")
