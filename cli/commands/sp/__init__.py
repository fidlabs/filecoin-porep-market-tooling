from ._sp import info, sp, wait
from .claim_allocations import claim_allocations
from .get_allocations import get_allocations
from .get_claims import get_claims
from .get_deals import get_deal, get_deal_manifest, get_deal_rail, get_deals
from .get_filecoinpay_account import get_filecoinpay_account
from .get_offers import get_offers, get_offer
from .get_sps import get_sps
from .is_authorized import is_authorized
from .onboard_data import onboard_data
from .pause_block_sp import pause_sp, unpause_sp, block_sp, unblock_sp
from .register_sp import register_sp
from .set_offer_active import set_offer_active
from .withdraw_from_filecoinpay import withdraw_from_filecoinpay

sp.add_command(register_sp)
sp.add_command(get_offers)
sp.add_command(get_offer)
sp.add_command(set_offer_active)
sp.add_command(pause_sp)
sp.add_command(unpause_sp)
sp.add_command(block_sp)
sp.add_command(unblock_sp)
sp.add_command(get_deal_manifest)
sp.add_command(get_deal_rail)
sp.add_command(get_claims)
sp.add_command(get_deal)
sp.add_command(is_authorized)
sp.add_command(claim_allocations)
sp.add_command(info)
sp.add_command(wait)
sp.add_command(onboard_data)
sp.add_command(get_deals)
sp.add_command(get_sps)
sp.add_command(get_allocations)
sp.add_command(withdraw_from_filecoinpay)
sp.add_command(get_filecoinpay_account)
