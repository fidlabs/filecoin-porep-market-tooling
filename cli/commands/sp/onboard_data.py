from pathlib import Path

import click

from cli.commands.sp import deal_onboarding


@click.command(context_settings=dict(ignore_unknown_options=True, allow_extra_args=True))
@click.argument("deal_id", type=click.IntRange(min=0))
@click.option("--output-dir", type=click.Path(file_okay=False), required=True, help="Directory to save downloaded pieces.")
@click.option("--host", help="Host to use for .car files download.  [default: same host as manifest URL]")
@click.option("--port", default=7777, type=click.IntRange(min=1, max=65535), show_default=True,
              help="Port to use for .car files download.")
@click.pass_context
# TODO add commP files verification after download
def onboard_data(ctx, deal_id: int, output_dir: str, port: int, host: str | None = None):
    """
    \b
    Download data for a deal using aria2 downloader.

    \b
    Unknown [OPTIONS] are passed directly to aria2c, allowing for flexible configuration.
    See aria2c --help for available options.

    DEAL_ID - ID of the deal to download pieces for.

    \b
    See https://aria2.github.io/ and https://github.com/aria2/aria2 for more information about aria2 and installation instructions.
    """

    deal_onboarding.download_deal_data(
        deal_id,
        Path(output_dir).resolve(),
        host=host,
        port=port,
        aria2c_extra_args=ctx.args,
        interactive=True,
    )
