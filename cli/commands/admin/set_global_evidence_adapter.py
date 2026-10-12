import click

from cli import utils
from cli.commands import utils as commands_utils
from cli.commands.admin._admin import admin_address, admin_signer
from cli.services.contracts.porep_market import PoRepMarket
from cli.services.contracts.sector_evidence_adapter import SectorEvidenceAdapter
from cli.services.self_update import SelfUpdateService
from cli.services.web3_service import EthAddress, Web3Service


@click.command()
@click.argument("evidence_adapter_address")
def set_global_evidence_adapter(evidence_adapter_address: str):
    """
    Set the evidence adapter assigned to newly created deals. Existing deals keep their evidence adapter.

    EVIDENCE_ADAPTER_ADDRESS - Address of the evidence adapter to be set.
    """

    SelfUpdateService.check_and_prompt(manual=False)
    Web3Service().wait_for_pending_transactions(admin_address())

    _evidence_adapter_address = EthAddress.from_any(evidence_adapter_address)
    new_evidence_adapter = SectorEvidenceAdapter(_evidence_adapter_address)

    if new_evidence_adapter.get_porep_market_contract_address() != PoRepMarket().address():
        raise click.ClickException(f"Evidence adapter {_evidence_adapter_address} is not connected to PoRep Market {PoRepMarket().address()}")

    if not new_evidence_adapter.is_operational():
        raise click.ClickException(f"Evidence adapter {_evidence_adapter_address} is not operational")

    current_address = PoRepMarket().get_global_evidence_adapter_address()
    utils.confirm(f"Setting new global evidence adapter. "
                  f"Current: {current_address} ({commands_utils.get_evidence_type(current_address)}) -> "
                  f"New: {_evidence_adapter_address} ({new_evidence_adapter.get_evidence_type()})", abort=True)

    tx_hash = PoRepMarket().set_global_evidence_adapter(_evidence_adapter_address, admin_signer()).tx_hash
    click.echo(f"New global evidence adapter set: {tx_hash}")
