import click
from eth_hash.backends.pycryptodome import keccak256

from cli import utils
from cli.commands.admin._admin import admin_signer
from cli.services.contracts.access_control_upgradeable import AccessControlUpgradeable
from cli.services.web3_service import EthAddress


@click.command()
@click.argument("contract_address")
@click.argument("role")
@click.argument("account")
def set_role(contract_address: str, role: str, account: str):
    """
    Grant a role to an address on a contract that implements AccessControlUpgradeable.

    CONTRACT_ADDRESS - The address of the contract to modify role on. Can be any format possible.
    ROLE - The role to modify. Must be a hex string, a decimal string, or an alphanumeric string.
    ACCOUNT - The address to grant the role to. Can be any format possible.
    """

    _contract_address = EthAddress.from_any(contract_address)
    _account = EthAddress.from_any(account)
    contract = AccessControlUpgradeable(_contract_address)

    if role.startswith("0x"):
        role_bytes = utils.uint_to_bytes(int(role, 16), 32)
    elif role.isdigit():
        role_bytes = utils.uint_to_bytes(int(role), 32)
    elif role.isalpha():
        role_bytes = keccak256(role.encode("utf-8"))
    else:
        raise ValueError("Role must be a hex string, a decimal string, or an alphanumeric string")

    account_str = f"{account} ({_account})" if account != _account else account
    contract_address_str = f"{contract_address} ({_contract_address})" if contract_address != _contract_address else contract_address

    utils.confirm(f"Setting role {role} ({role_bytes.hex()}) for address {account_str} on contract {contract_address_str}",
                  abort=True)

    tx_hash = contract.grant_role(role_bytes, _account, admin_signer())

    click.echo(f"Role set: {tx_hash}")
