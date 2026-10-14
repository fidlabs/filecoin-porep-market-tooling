import importlib
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from click.testing import CliRunner

from cli.commands.client.make_allocations import make_allocations
from cli.services.contracts.porep_market import PoRepMarketDealState
from cli.services.web3_service import ActorId, EthAddress, Web3Service

CLIENT = EthAddress("0x2222222222222222222222222222222222222222")
ADAPTER = EthAddress("0x4444444444444444444444444444444444444444")
VALIDATOR = EthAddress("0x5555555555555555555555555555555555555555")
TOKEN = EthAddress("0x6666666666666666666666666666666666666666")
EPOCH = 1000
# the click command of the same name shadows the module as an attribute of its package, which
# patch("cli.commands.client.make_allocations.X") resolves to on Python 3.10
MODULE = importlib.import_module("cli.commands.client.make_allocations")


def claim(piece_cid, term_start=100, term_max=EPOCH):
    return {"Provider": 1234, "Client": 5678, "Data": {"/": piece_cid}, "Size": 32, "TermMin": 1, "TermMax": term_max,
            "TermStart": term_start, "Sector": 7}


class MakeAllocationsExistingPiecesTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.previous_web3 = Web3Service._instance
        cls.web3 = MagicMock()
        cls.web3.get_chain_id.return_value = 314
        cls.web3.get_network_name.return_value = "Filecoin Mainnet"
        cls.web3.get_block_number.return_value = EPOCH
        Web3Service._instance = cls.web3

    @classmethod
    def tearDownClass(cls):
        Web3Service._instance = cls.previous_web3

    def setUp(self):
        deal = SimpleNamespace(deal_id=9, client_address=CLIENT, provider_id=ActorId(1234), state=PoRepMarketDealState.ACCEPTED,
                               evidence_adapter_address=ADAPTER, validator_address=VALIDATOR, rail_id=7)
        view = SimpleNamespace(deal=deal, data=SimpleNamespace(manifest_location="https://example.com/manifest.json"),
                               payment=SimpleNamespace(payment_token=TOKEN),
                               terms=SimpleNamespace(duration_epochs=518_400, requested_size_bytes=64))
        self.adapter = MagicMock()
        self.adapter.is_datacap_posting_finished.return_value = False
        manifest = [{"pieces": [{"pieceCid": "baga-one", "pieceSize": 32, "pieceType": "data"},
                                {"pieceCid": "baga-two", "pieceSize": 32, "pieceType": "data"}]}]
        for target, value in (("SelfUpdateService", MagicMock()),
                              ("client_address", MagicMock(return_value=CLIENT)),
                              ("client_signer", MagicMock()),
                              ("PoRepMarketViewHelper", MagicMock(return_value=MagicMock(get_deal_view=MagicMock(return_value=view)))),
                              ("DataCapEvidenceAdapter", MagicMock(return_value=self.adapter)),
                              ("FileCoinPay", MagicMock(return_value=MagicMock(
                                  get_operator_approval=MagicMock(return_value=SimpleNamespace(is_approved=True))))),
                              ("PoRepMarket", MagicMock(return_value=MagicMock(get_epochs_in_month=MagicMock(return_value=86_400)))),
                              ("commands_utils.get_deal_allocations", MagicMock(return_value={})),
                              ("commands_utils.get_deal_claims", MagicMock(return_value={})),
                              ("commands_utils.fetch_manifest", MagicMock(return_value=(manifest, b"")))):
            owner, _, name = target.rpartition(".")
            patcher = patch.object(getattr(MODULE, owner) if owner else MODULE, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def invoke(self, *args):
        # declining the batch prompt stops the command right after the existing-pieces check
        return CliRunner().invoke(make_allocations, ["9", "--print-only", *args], input="n\n")

    def test_refuses_pieces_in_live_claims_of_the_provider(self):
        self.web3.state_get_claims.return_value = {"77": claim("baga-one"), "78": claim("baga-other")}
        result = self.invoke()
        self.assertEqual(result.exit_code, 1, result.output)
        self.assertNotIn("Continue with allocation", result.output)
        self.assertIn("1/2 pieces are already stored by provider f01234", result.output)
        self.assertIn("claim 77", result.output)
        self.adapter.submit_datacap_batch.assert_not_called()

    def test_ignores_claims_past_their_term(self):
        self.web3.state_get_claims.return_value = {"77": claim("baga-one", term_start=100, term_max=EPOCH - 101)}
        result = self.invoke()
        self.assertIn("Continue with allocation of remaining 2 pieces", result.output)
        self.assertNotIn("already stored", result.output)

    def test_flag_allows_a_second_copy(self):
        self.web3.state_get_claims.return_value = {"77": claim("baga-one"), "79": claim("baga-two")}
        result = self.invoke("--allow-existing-pieces")
        self.assertIn("Warning: 2/2 pieces are already stored", result.output)
        self.assertIn("Continue with allocation of remaining 2 pieces", result.output)


if __name__ == "__main__":
    unittest.main()
