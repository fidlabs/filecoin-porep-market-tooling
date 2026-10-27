import click

from cli.services.cid_converter import piece_cid_v1_to_v2


@click.command()
@click.argument("cidv1")
@click.argument("filesize", type=click.IntRange(min=1))
def cidv1_to_cidv2(cidv1: str, filesize: int):
    """
    Convert CIDv1 to CIDv2.

    \b
    CIDV1 - CIDv1 string to convert.
    FILESIZE - Size of the piece in bytes.
    """

    click.echo(piece_cid_v1_to_v2(cidv1, filesize))
