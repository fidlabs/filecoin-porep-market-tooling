from ._client import client, info, wait
from .deposit_amount import deposit_amount
from .deposit_for_deals import deposit_for_deals, deposit_for_whole_deal
from .get_deals import get_deal, get_deal_manifest, get_deal_rail, get_deals
from .get_filecoinpay_account import get_filecoinpay_account
from .init_deals import init_deals
from .make_allocations import make_allocations
from .propose_deal import propose_deal, propose_deal_mocked
from .sign_retrieval_voucher import sign_retrieval_voucher
from .validate_manifest import validate_manifest
from .withdraw_from_filecoinpay import withdraw_from_filecoinpay

client.add_command(validate_manifest)
client.add_command(get_deal_manifest)
client.add_command(get_deal_rail)
client.add_command(get_deal)
client.add_command(deposit_amount)
client.add_command(info)
client.add_command(wait)
client.add_command(get_deals)
client.add_command(get_filecoinpay_account)
client.add_command(propose_deal)
client.add_command(propose_deal_mocked)
client.add_command(init_deals)
client.add_command(deposit_for_deals)
client.add_command(deposit_for_whole_deal)
client.add_command(make_allocations)
client.add_command(withdraw_from_filecoinpay)
client.add_command(sign_retrieval_voucher)
