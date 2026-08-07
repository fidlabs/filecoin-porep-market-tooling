from ._admin import admin, info, wait
from .get_db_offers import get_db_offers, get_mocked_offers
from .get_db_sps import get_db_sps, get_mocked_sps
from .get_deals import get_deal, get_deal_manifest, get_deal_rail, get_deals
from .get_offers import get_offers, get_offer
from .get_sps import get_sps
from .pause_block_sp import pause_sp, unpause_sp, block_sp, unblock_sp
from .register_sps import register_db_sps, register_mocked_sps
from .set_completion_padding import set_completion_padding
from .set_offer_active import set_offer_active
from .set_role import set_role, has_role
from .terminate_deal import terminate_deal

admin.add_command(has_role)
admin.add_command(get_offer)
admin.add_command(get_db_offers)
admin.add_command(set_role)
admin.add_command(get_deal_rail)
admin.add_command(get_deal_manifest)
admin.add_command(get_deal)
admin.add_command(terminate_deal)
admin.add_command(block_sp)
admin.add_command(unblock_sp)
admin.add_command(pause_sp)
admin.add_command(unpause_sp)
admin.add_command(info)
admin.add_command(wait)
admin.add_command(get_mocked_sps)
admin.add_command(get_mocked_offers)
admin.add_command(get_deals)
admin.add_command(get_db_sps)
admin.add_command(get_sps)
admin.add_command(register_db_sps)
admin.add_command(register_mocked_sps)
admin.add_command(set_completion_padding)
admin.add_command(set_offer_active)
admin.add_command(get_offers)
