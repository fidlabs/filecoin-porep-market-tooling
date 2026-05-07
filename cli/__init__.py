from cli import commands
from ._cli import cli

cli.add_command(commands.admin)
cli.add_command(commands.client)
cli.add_command(commands.convert)
cli.add_command(commands.sp)
cli.add_command(commands.info)
