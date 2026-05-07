import click

from cli import utils
from cli.commands import utils as commands_utils
from cli.commands.sp import _utils as sp_utils
from cli.commands.sp._sp import sp_private_key, sp_organization_address
from cli.services.web3_service import EthAddress, Web3Service


# TODO LATER print deals states at the end?
@click.command()
@click.argument("action", required=False, type=click.Choice(["accept", "reject"], case_sensitive=False))
def manage_proposed_deals(action: str | None):
    """
    Interactively manage proposed deals. Either accept or reject each proposed deal manually or based on provided ACTION argument.

    ACTION - Action to perform on proposed deals.
    """

    Web3Service().wait_for_pending_transactions(EthAddress.from_private_key(sp_private_key()))
    deals = commands_utils.get_all_deals(sp_utils.PoRepMarketDealState.PROPOSED, sp_organization_address())

    click.echo(f"Found {len(deals)} proposed deals.")

    for deal in deals:
        answer = action or utils.confirm_str(f"\nNew deal id {deal.deal_id}: {deal}",
                                             valid_answers=["accept", "reject", "skip"],
                                             default="skip")

        try:
            if answer in ["accept"]:
                click.echo()
                sp_utils.accept_deal(deal, confirm_session_id="manage-proposed-deals-accept")

            elif answer in ["reject"]:
                click.echo()
                sp_utils.reject_deal(deal, confirm_session_id="manage-proposed-deals-reject")

            elif answer in ["skip"]:
                continue
        #
        except click.ClickException as e:
            e.show()
            continue
        except click.Abort:
            click.echo("\nSkipped this deal.")
            continue

    click.echo("\n\nAll done!")
