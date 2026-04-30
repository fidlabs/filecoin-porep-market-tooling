from ._admin import admin, info, wait
from .block_sp import block_sp
from .get_db_sps import get_db_sps
from .get_deals import get_deals
from .get_devnet_sps import get_devnet_sps
from .get_registered_sps import get_registered_sps
from .pause_sp import pause_sp
from .register_sps import register_db_sps, register_devnet_sps
from .terminate_deal import terminate_deal
from .unblock_sp import unblock_sp
from .unpause_sp import unpause_sp

admin.add_command(terminate_deal)
admin.add_command(block_sp)
admin.add_command(unblock_sp)
admin.add_command(pause_sp)
admin.add_command(unpause_sp)
admin.add_command(info)
admin.add_command(wait)
admin.add_command(get_devnet_sps)
admin.add_command(get_deals)
admin.add_command(get_db_sps)
admin.add_command(get_registered_sps)
admin.add_command(register_db_sps)
admin.add_command(register_devnet_sps)
