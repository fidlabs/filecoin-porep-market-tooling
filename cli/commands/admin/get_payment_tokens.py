import click

from cli import utils
from cli.services.contracts.sp_registry import SPRegistry


@click.command()
def get_payment_tokens():
    """
    Get payment token configurations from the SPRegistry contract.
    """

    click.echo(utils.json_pretty([
        {
            "token_address": token,
            "config": SPRegistry().get_payment_token_config(token)
        }
        for token in SPRegistry().get_payment_tokens()
    ]))
