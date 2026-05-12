from ._client import client, info, wait
from .deposit_amount import deposit_amount
from .deposit_for_deals import deposit_for_deals
from .get_deals import get_deal
from .get_deals import get_deals
from .get_filecoinpay_account import get_filecoinpay_account
from .init_accepted_deals import init_accepted_deals
from .make_allocations import make_allocations
from .propose_deal_from_manifest import propose_deal_from_manifest
from .complete_deal import complete_deal

client.add_command(get_deal)
client.add_command(deposit_amount)
client.add_command(info)
client.add_command(wait)
client.add_command(get_deals)
client.add_command(get_filecoinpay_account)
client.add_command(propose_deal_from_manifest)
client.add_command(init_accepted_deals)
client.add_command(deposit_for_deals)
client.add_command(make_allocations)
client.add_command(complete_deal)

