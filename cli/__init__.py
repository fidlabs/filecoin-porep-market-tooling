from cli import commands

from ._cli import cli
from .migration.status import migration_status

cli.add_command(commands.admin)
cli.add_command(commands.client)
cli.add_command(commands.convert)
cli.add_command(commands.sp)
cli.add_command(commands.config)
cli.add_command(commands.self_update)
cli.add_command(migration_status)
cli.add_command(commands.test)
cli.add_command(commands.cidv1_to_cidv2)
