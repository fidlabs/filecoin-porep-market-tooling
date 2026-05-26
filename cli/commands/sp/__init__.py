from ._sp import sp, info, wait
from .accept_deal import accept_deal
from .claim_allocations import claim_allocations
from .get_allocations import get_allocations
from .get_claims import get_claims
from .get_deals import get_deal, get_deal_manifest, get_deal_rail, get_deals
from .get_filecoinpay_account import get_filecoinpay_account
from .get_registered_info import get_registered_info
from .is_authorized import is_authorized
from .manage_proposed_deals import manage_proposed_deals
from .onboard_data import onboard_data
from .reject_deal import reject_deal
from .withdraw_from_filecoinpay import withdraw_from_filecoinpay

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
sp.add_command(accept_deal)
sp.add_command(reject_deal)
sp.add_command(manage_proposed_deals)
sp.add_command(get_registered_info)
sp.add_command(get_allocations)
sp.add_command(withdraw_from_filecoinpay)
sp.add_command(get_filecoinpay_account)
