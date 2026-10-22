from collections.abc import Callable
from decimal import ROUND_CEILING, Decimal, localcontext

import click

from cli import utils
from cli.services.contracts.filecoin_pay import FileCoinPay
from cli.services.web3_service import EthAddress, Web3Service

# FCSS repair funding, read from chain by both sides (the CLI keeps no local state):
#  - deposited: the client's FileCoinPay deposits into the new SP's payee account since the deal was proposed
#    (`client pay-repair-retrieval`),
#  - spent: the payee's one-time rail payments since then, i.e. what retrieval-client has paid sp-proxies from that account.
# deposited - spent is what the client has funded and the SP has not yet spent, so it caps the SP's repair download
# (see `sp onboard-data`). Both sums cover every deal between the same client and payee in that window, so concurrent
# repairs between them share one budget.

LOGS_BLOCK_RANGE = 2000  # initial eth_getLogs block range (LOGS_BLOCK_RANGE env overrides); halved on each RPC error
MIN_LOGS_BLOCK_RANGE = 50  # below this, give up and fail closed


class FundingHistoryUnavailable(Exception):
    pass


# quotes are decimal USDFC strings; funding is in base units (rounded up, so funding never falls short of the quote)
def tokens_to_base_units(amount: Decimal, decimals: int) -> int:
    with localcontext() as ctx:
        ctx.prec = 100
        return int(amount.scaleb(decimals).to_integral_value(rounding=ROUND_CEILING))


# exact decimal string of a base-unit amount (utils.str_from_wei goes through float)
def base_units_str(amount: int, decimals: int) -> str:
    text = format(Decimal(amount).scaleb(-decimals), "f")
    return text.rstrip("0").rstrip(".") if "." in text else text


@utils.json_dataclass()
class RepairFunding:
    deposited: int
    spent: int

    @property
    def available(self) -> int:
        return max(self.deposited - self.spent, 0)


# RPC providers limit eth_getLogs block ranges differently, so the range starts at LOGS_BLOCK_RANGE (env) and is halved on
# any error; errors a smaller range can't fix (e.g. a lookback limit for older deals) end in FundingHistoryUnavailable.
def _sum_logs(get_amount: Callable[[int, int], int], since_block: int, what: str) -> int:
    latest_block = Web3Service().get_block_number()
    block_range = utils.get_env_required("LOGS_BLOCK_RANGE", default=LOGS_BLOCK_RANGE, required_type=int)
    start = since_block
    total = 0

    while start <= latest_block:
        end = min(start + block_range - 1, latest_block)

        # noinspection PyBroadException
        try:
            total += get_amount(start, end)
            start = end + 1

        # pylint: disable=broad-exception-caught
        except Exception as e:
            block_range //= 2

            if block_range < MIN_LOGS_BLOCK_RANGE:
                raise FundingHistoryUnavailable(f"RPC could not serve {what} logs for epochs {start}-{end}: {e}") from e

    return total


def get_repair_deposits(token: EthAddress, client: EthAddress, payee: EthAddress, since_block: int) -> int:
    filecoin_pay = FileCoinPay()
    return _sum_logs(lambda start, end: filecoin_pay.get_deposited_amount(token, client, payee, start, end), since_block, "deposit")


# retrieval-client pays each sp-proxy with one-time payments on a rail where the payee's account is the payer
def get_repair_spending(token: EthAddress, payee: EthAddress, since_block: int) -> int:
    filecoin_pay = FileCoinPay()

    try:
        rail_ids = filecoin_pay.get_payer_rail_ids(token, payee)

    # pylint: disable=broad-exception-caught
    except Exception as e:
        raise FundingHistoryUnavailable(f"RPC could not list the FileCoinPay rails paid by {payee}: {e}") from e

    if not rail_ids:
        return 0

    return _sum_logs(lambda start, end: filecoin_pay.get_one_time_payments(rail_ids, start, end), since_block, "rail payment")


def get_repair_funding(token: EthAddress, client: EthAddress, payee: EthAddress, since_block: int) -> RepairFunding:
    click.echo(f"\nChecking repair funding of {payee} by {client} since epoch {since_block}...")

    # noinspection PyArgumentList
    return RepairFunding(deposited=get_repair_deposits(token, client, payee, since_block),
                         spent=get_repair_spending(token, payee, since_block))
