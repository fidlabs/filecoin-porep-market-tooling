import os
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import cbor2
import click
from click.testing import CliRunner

from cli.commands.client.migration import adopt_v1_claims, close_v1_deal, finish_migration
from cli.commands.sp.migration import _run_sptool, extend_deal_sectors, sector_expirations
from cli.services.contract_service import ContractService
from cli.services.contracts.datacap_evidence_adapter import DataCapEvidenceType
from cli.services.contracts.filecoinpay_validator import FileCoinPayRailStatus
from cli.services.contracts.legacy_porep_market import LegacyDeal
from cli.services.contracts.porep_market import PoRepMarketDealState
from cli.services.migration import (
    CLAIM_TERM_RESERVE_EPOCHS,
    DATACAP_PRECISION,
    EPOCHS_IN_DAY,
    MAXIMUM_VERIFIED_ALLOCATION_TERM,
    AdoptionPlan,
    Claim,
    ClaimExtension,
    MigrationError,
    MigrationPair,
    MigrationService,
    adapter_claim_ids,
    build_adoption_plan,
    claim_extension_cbor,
    extension_term_max,
    open_rail,
    sector_target_epoch,
    size_within_padding,
)
from cli.services.web3_service import ActorId, EthAddress, Web3Service

MARKET = EthAddress("0x1111111111111111111111111111111111111111")
CLIENT = EthAddress("0x2222222222222222222222222222222222222222")
OTHER = EthAddress("0x3333333333333333333333333333333333333333")
ADAPTER = EthAddress("0x4444444444444444444444444444444444444444")
VALIDATOR = EthAddress("0x5555555555555555555555555555555555555555")
TOKEN = EthAddress("0x6666666666666666666666666666666666666666")
EPOCH = 1000


def make_claim(claim_id=10, term_max=600_000, term_start=100, size=32, sector=None):
    return Claim(claim_id, ActorId(1234), ActorId(5678), "baga-piece", size, 518_400, term_max, term_start,
                 claim_id + 100 if sector is None else sector)


def rpc_claim(**overrides):
    data = {"Provider": 1234, "Client": 5678, "Data": {"/": "baga-piece"}, "Size": 32, "TermMin": 518_400, "TermMax": 600_000,
            "TermStart": 100, "Sector": 7}
    data.update(overrides)
    return data


def make_source(state=LegacyDeal.COMPLETED, rail_id=5, size=64, client=CLIENT, deal_id=3):
    return LegacyDeal(deal_id=deal_id, client=client, provider=ActorId(1234), requirements=(0, 0, 0, 0), size_bytes=size,
                      price_per_32_gib_per_month=1, duration_days=180, validator=VALIDATOR, state=state, rail_id=rail_id,
                      proposed_at_epoch=1, manifest_location="loc", manifest_hash=b"\x00" * 32)


def make_rail(end_epoch=0, payment_rate=10 ** 12, settled_up_to=EPOCH - 100):
    return SimpleNamespace(token=TOKEN, payment_rate=payment_rate, lockup_period=30 * EPOCHS_IN_DAY, settled_up_to=settled_up_to,
                           end_epoch=end_epoch)


def make_target(state=PoRepMarketDealState.ACCEPTED, client=CLIENT, provider=1234, rail_id=0, requested=64):
    deal = SimpleNamespace(deal_id=9, client_address=client, provider_id=ActorId(provider), state=state,
                           evidence_adapter_address=ADAPTER, validator_address=VALIDATOR, rail_id=rail_id)
    return SimpleNamespace(deal=deal, terms=SimpleNamespace(requested_size_bytes=requested, duration_epochs=180 * EPOCHS_IN_DAY),
                           service=SimpleNamespace(service_start_epoch=500, service_end_epoch=500 + 180 * EPOCHS_IN_DAY))


def paged(ids):
    return lambda deal_id, offset, limit: (ids[offset:offset + limit], len(ids))


def make_adapter(pending=(), confirmed=(), allocated=0):
    adapter = MagicMock()
    adapter.get_allocation_ids_per_deal.side_effect = paged(list(pending))
    adapter.get_claim_ids.side_effect = paged(list(confirmed))
    adapter.get_allocated_bytes.return_value = allocated
    adapter.is_datacap_posting_finished.return_value = False
    adapter.is_operational.return_value = True
    return adapter


def make_plan(registered=(), claims=None):
    claims = claims or [make_claim(10), make_claim(11)]
    return build_adoption_plan(claims, list(registered), EPOCH)


class Web3Singleton(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.previous_web3 = Web3Service._instance
        cls.web3 = MagicMock()
        cls.web3.get_chain_id.return_value = 314
        cls.web3.get_network_name.return_value = "Filecoin Mainnet"
        Web3Service._instance = cls.web3

    @classmethod
    def tearDownClass(cls):
        Web3Service._instance = cls.previous_web3


class PlanTests(Web3Singleton):
    def test_extension_term_max_formula(self):
        claim = make_claim(term_start=100)
        expected = EPOCH + MAXIMUM_VERIFIED_ALLOCATION_TERM - 100 - EPOCHS_IN_DAY
        self.assertEqual(extension_term_max(claim, EPOCH), expected)
        self.assertEqual(CLAIM_TERM_RESERVE_EPOCHS, EPOCHS_IN_DAY)

    def test_extension_term_max_rejects_expired_claim(self):
        claim = make_claim(term_start=100, term_max=500)
        with self.assertRaisesRegex(MigrationError, "expired"):
            extension_term_max(claim, 600)
        with self.assertRaisesRegex(MigrationError, "expired"):
            extension_term_max(claim, 601)
        self.assertGreater(extension_term_max(claim, 599), claim.term_max)

    def test_extension_term_max_rejects_already_extended_claim(self):
        limit = EPOCH + MAXIMUM_VERIFIED_ALLOCATION_TERM - 100 - EPOCHS_IN_DAY
        with self.assertRaisesRegex(MigrationError, "nothing left to extend"):
            extension_term_max(make_claim(term_max=limit), EPOCH)
        with self.assertRaisesRegex(MigrationError, "nothing left to extend"):
            extension_term_max(make_claim(term_max=limit + 1), EPOCH)
        self.assertEqual(extension_term_max(make_claim(term_max=limit - 1), EPOCH), limit)

    def test_build_plan_skips_registered_ids(self):
        plan = make_plan(registered=[10])
        self.assertEqual([extension.claim_id for extension in plan.extensions], [11])
        self.assertEqual(plan.registered_ids, frozenset({10}))
        self.assertFalse(plan.complete)

    def test_build_plan_rejects_bad_inputs(self):
        claims = [make_claim(10), make_claim(11)]
        with self.assertRaisesRegex(MigrationError, "do not belong"):
            build_adoption_plan(claims, [10, 99], EPOCH)
        with self.assertRaisesRegex(MigrationError, "empty or duplicated"):
            build_adoption_plan([], [], EPOCH)
        with self.assertRaisesRegex(MigrationError, "empty or duplicated"):
            build_adoption_plan([make_claim(10), make_claim(10)], [], EPOCH)
        with self.assertRaisesRegex(MigrationError, "duplicate claim IDs"):
            build_adoption_plan(claims, [10, 10], EPOCH)

    def test_plan_complete_only_when_all_registered(self):
        self.assertTrue(make_plan(registered=[10, 11]).complete)
        self.assertFalse(make_plan(registered=[10]).complete)
        self.assertFalse(make_plan(registered=[]).complete)

    def test_operator_data_round_trip(self):
        plan = make_plan(registered=[11])
        expected_term = extension_term_max(make_claim(10), EPOCH)
        self.assertEqual(cbor2.loads(plan.operator_data), [[], [[1234, 10, expected_term]]])
        self.assertEqual(cbor2.loads(claim_extension_cbor([])), [[], []])

    def test_cbor_rejects_values_outside_uint64(self):
        for extension in (ClaimExtension(ActorId(1234), 2 ** 64, 5, 32), ClaimExtension(ActorId(1234), 1, -1, 32),
                          ClaimExtension(ActorId(1234), 1, 2 ** 64, 32)):
            with self.assertRaisesRegex(MigrationError, "uint64"):
                claim_extension_cbor([extension])

    def test_datacap_amount_and_transfer_params(self):
        plan = make_plan(claims=[make_claim(10, size=32), make_claim(11, size=64)])
        self.assertEqual(plan.datacap_amount, 96 * DATACAP_PRECISION)
        params = MigrationService.transfer_params(plan)
        amount = 96 * DATACAP_PRECISION
        self.assertEqual(params.amount, (amount.to_bytes((amount.bit_length() + 7) // 8, "big"), False))
        self.assertEqual(int.from_bytes(params.amount[0], "big"), amount)
        self.assertEqual(params.to, (b"\x00\x06",))
        self.assertEqual(params.operator_data, plan.operator_data)

    def test_batches_split_extensions_and_reject_bad_size(self):
        claims = [make_claim(claim_id) for claim_id in range(10, 15)]
        plan = make_plan(claims=claims)
        batches = plan.batches(2)
        self.assertEqual([len(batch.extensions) for batch in batches], [2, 2, 1])
        self.assertEqual([e.claim_id for batch in batches for e in batch.extensions], [10, 11, 12, 13, 14])
        self.assertTrue(all(batch.source_claims == plan.source_claims for batch in batches))
        for size in (0, -1):
            with self.assertRaises(ValueError):
                plan.batches(size)

    def test_size_within_padding_boundaries(self):
        self.assertTrue(size_within_padding(900, 1000, 1000))
        self.assertFalse(size_within_padding(899, 1000, 1000))
        self.assertTrue(size_within_padding(1100, 1000, 1000))
        self.assertFalse(size_within_padding(1101, 1000, 1000))
        self.assertTrue(size_within_padding(1000, 1000, 0))
        self.assertFalse(size_within_padding(1001, 1000, 0))


class AdapterIdTests(Web3Singleton):
    def test_pagination_over_two_pages(self):
        pending = list(range(1, 601))
        adapter = make_adapter(pending=pending, confirmed=[1000, 1001])
        self.assertEqual(adapter_claim_ids(adapter, 9), pending + [1000, 1001])
        self.assertEqual(adapter.get_allocation_ids_per_deal.call_count, 2)
        adapter.get_allocation_ids_per_deal.assert_any_call(9, 500, 500)

    def test_overlap_between_pending_and_confirmed_raises(self):
        with self.assertRaisesRegex(MigrationError, "repeats IDs"):
            adapter_claim_ids(make_adapter(pending=[1, 2], confirmed=[2, 3]), 9)


class OpenRailTests(Web3Singleton):
    def test_open_rail(self):
        rail = make_rail()
        with patch("cli.services.migration.FileCoinPay") as pay:
            pay.return_value.get_rail.return_value = rail
            self.assertIs(open_rail(5), rail)
            pay.return_value.get_rail.assert_called_once_with(5)

    def test_open_rail_returns_none_for_finalized_rail(self):
        with patch("cli.services.migration.FileCoinPay") as pay:
            pay.return_value.get_rail.side_effect = click.ClickException("execution reverted: RailInactiveOrSettled(5)")
            self.assertIsNone(open_rail(5))

    def test_open_rail_reraises_other_errors(self):
        with patch("cli.services.migration.FileCoinPay") as pay:
            pay.return_value.get_rail.side_effect = click.ClickException("Web3 RPC error: timeout")
            with self.assertRaisesRegex(click.ClickException, "timeout"):
                open_rail(5)

    def test_sector_target_epoch(self):
        target = make_target(state=PoRepMarketDealState.ACTIVE)
        self.assertEqual(sector_target_epoch(target, EPOCH), target.service.service_end_epoch + 30 * EPOCHS_IN_DAY)
        target = make_target(state=PoRepMarketDealState.ACCEPTED)
        self.assertEqual(sector_target_epoch(target, EPOCH), EPOCH + 180 * EPOCHS_IN_DAY + 60 * EPOCHS_IN_DAY)


class ServiceTests(Web3Singleton):
    def make_service(self, source_chain_id=314, connected=314):
        web3 = MagicMock()
        web3.get_chain_id.return_value = connected
        web3.get_block_number.return_value = EPOCH
        with patch("cli.services.migration.LegacyPoRepMarket"):
            service = MigrationService(MARKET, source_chain_id, web3=web3, view_helper=MagicMock())
        service.source_market = MagicMock()
        return service

    def make_pair(self, target=None, source=None):
        return MigrationPair(source or make_source(), make_rail(), target or make_target())

    def test_chain_id_guard(self):
        with self.assertRaisesRegex(MigrationError, "does not match"):
            self.make_service(source_chain_id=314159, connected=314)
        self.assertIsInstance(self.make_service(source_chain_id=314, connected=314), MigrationService)

    def test_qualify_source(self):
        service = self.make_service()
        rail = make_rail()
        with patch.object(service, "source_rail", return_value=rail):
            self.assertIs(service.qualify_source(make_source()), rail)
            with self.assertRaisesRegex(MigrationError, "not Completed"):
                service.qualify_source(make_source(state=1))
        with patch.object(service, "source_rail", return_value=make_rail(end_epoch=5)), \
                self.assertRaisesRegex(MigrationError, "already terminated"):
            service.qualify_source(make_source())
        with patch.object(service, "source_rail", return_value=make_rail(payment_rate=0)), \
                self.assertRaisesRegex(MigrationError, "not paying"):
            service.qualify_source(make_source())
        with patch.object(service, "source_rail", return_value=None), self.assertRaisesRegex(MigrationError, "settled and finalized"):
            service.qualify_source(make_source())

    def test_source_rail_requires_rail_id(self):
        with self.assertRaisesRegex(MigrationError, "has no payment rail"):
            MigrationService.source_rail(make_source(rail_id=0))
        with patch("cli.services.migration.open_rail", return_value=None) as opened:
            self.assertIsNone(MigrationService.source_rail(make_source()))
        opened.assert_called_once_with(5)

    def test_open_source_deals_selects_paying_open_and_terminated_rails(self):
        service = self.make_service()
        deals = [
            make_source(deal_id=1, rail_id=11),                                  # open, paying
            make_source(deal_id=2, rail_id=12, state=LegacyDeal.TERMINATED),     # terminated, still paying
            make_source(deal_id=3, rail_id=13),                                  # rate cut to zero
            make_source(deal_id=4, rail_id=14),                                  # finalized
            make_source(deal_id=5, rail_id=15, state=1),                         # other state
            make_source(deal_id=6, rail_id=0),                                   # no rail
            make_source(deal_id=7, rail_id=17, client=OTHER),                    # other client
        ]
        rails = {11: make_rail(), 12: make_rail(end_epoch=EPOCH), 13: make_rail(payment_rate=0), 14: None, 15: make_rail(), 17: make_rail()}
        service.source_market.get_deals.return_value = deals
        with patch("cli.services.migration.open_rail", side_effect=lambda rail_id: rails[rail_id]) as opened:
            result = service.open_source_deals()
            self.assertEqual([(deal.deal_id, rail) for deal, rail in result], [(1, rails[11]), (2, rails[12]), (7, rails[17])])
            self.assertEqual([deal.deal_id for deal, _ in service.open_source_deals(CLIENT)], [1, 2])
            self.assertEqual([deal.deal_id for deal, _ in service.open_source_deals(OTHER)], [7])
            self.assertNotIn(15, [call.args[0] for call in opened.call_args_list])
            self.assertNotIn(0, [call.args[0] for call in opened.call_args_list])

    def source_claims_fixture(self, rpc=None, ids=(10, 11), allocated=64, terminated=()):
        service = self.make_service()
        client = service.source_market.get_client_contract.return_value
        client.allocation_ids.return_value = list(ids)
        client.allocated_size.return_value = allocated
        client.address.return_value.to_actor_id.return_value = ActorId(5678)
        client.is_claim_terminated.side_effect = lambda claim_id: claim_id in terminated
        service.web3.get_tipset_key.return_value = [{"/": "tip"}]
        service.web3.state_get_claims.return_value = (
            {"10": rpc_claim(Sector=7), "11": rpc_claim(Sector=8)} if rpc is None else rpc
        )
        return service

    def test_source_claims_parses_rpc(self):
        claims = self.source_claims_fixture().source_claims(make_source())
        self.assertEqual([claim.claim_id for claim in claims], [10, 11])
        self.assertEqual(claims[0], Claim(10, ActorId(1234), ActorId(5678), "baga-piece", 32, 518_400, 600_000, 100, 7))

    def test_source_claims_rejections(self):
        source = make_source()
        cases = {
            "do not equal the 32 bytes recorded": self.source_claims_fixture(allocated=32),
            "missing from provider": self.source_claims_fixture(rpc={"10": rpc_claim()}),
            "marked terminated": self.source_claims_fixture(terminated=(11,)),
            "belongs to client actor": self.source_claims_fixture(rpc={"10": rpc_claim(), "11": rpc_claim(Client=999)}),
            "belongs to provider": self.source_claims_fixture(rpc={"10": rpc_claim(), "11": rpc_claim(Provider=999)}),
            "do not equal the 64 bytes recorded": self.source_claims_fixture(rpc={"10": rpc_claim(), "11": rpc_claim(Size=16)}),
            "no claims or duplicate": self.source_claims_fixture(ids=(10, 10)),
        }
        for message, service in cases.items():
            with self.subTest(message), self.assertRaisesRegex(MigrationError, message):
                service.source_claims(source)

    def test_source_claims_compares_with_recorded_allocation_not_deal_size(self):
        # V1 accepted completion within a padding, so the recorded allocation may differ from the proposed size
        claims = self.source_claims_fixture(allocated=64).source_claims(make_source(size=70))
        self.assertEqual(sum(claim.size for claim in claims), 64)

    def test_source_claim_ids_and_adoption_progress(self):
        service = self.make_service()
        service.source_market.get_client_contract.return_value.allocation_ids.return_value = [10, 11]
        self.assertEqual(service.source_claim_ids(make_source()), [10, 11])
        service.source_market.get_client_contract.return_value.allocation_ids.assert_called_with(3)
        with patch("cli.services.migration.DataCapEvidenceAdapter", return_value=make_adapter(pending=[10], confirmed=[30])) as adapter_class:
            self.assertEqual(service.adoption_progress(self.make_pair()), ({10, 11}, {10, 30}))
        adapter_class.assert_called_once_with(ADAPTER)

    def test_pair_rejects_client_and_provider_mismatch(self):
        service = self.make_service()
        service.source_deal = MagicMock(return_value=make_source())
        service.view_helper.get_deal_view.return_value = make_target(client=OTHER)
        with self.assertRaisesRegex(MigrationError, "client .* differs"):
            service.pair(9, 3)
        service.view_helper.get_deal_view.return_value = make_target(provider=4321)
        with self.assertRaisesRegex(MigrationError, "provider .* differs"):
            service.pair(9, 3)

    def test_pair_returns_pair_when_matching(self):
        service = self.make_service()
        service.source_deal = MagicMock(return_value=make_source())
        service.view_helper.get_deal_view.return_value = make_target()
        rail = make_rail()
        with patch.object(service, "source_rail", return_value=rail):
            pair = service.pair(9, 3, require_paying=False)
        self.assertIs(pair.source_rail, rail)

    def test_pair_without_requirement_allows_finalized_rail(self):
        service = self.make_service()
        service.source_deal = MagicMock(return_value=make_source())
        service.view_helper.get_deal_view.return_value = make_target()
        with patch.object(service, "source_rail", return_value=None):
            self.assertIsNone(service.pair(9, 3, require_paying=False).source_rail)
            with self.assertRaisesRegex(MigrationError, "settled and finalized"):
                service.pair(9, 3)

    def adoption_service(self, adapter=None, claims=None, padding=1000):
        service = self.make_service()
        adapter = adapter or make_adapter(pending=[10], allocated=32)
        service.adapter = MagicMock(return_value=adapter)
        service.source_claims = MagicMock(return_value=claims or [make_claim(10), make_claim(11)])
        patcher = patch("cli.services.migration.PoRepMarket")
        patcher.start().return_value.get_deal_activation_padding.return_value = padding
        self.addCleanup(patcher.stop)
        return service, adapter

    def test_adoption_plan_happy_path(self):
        service, adapter = self.adoption_service()
        plan = service.adoption_plan(self.make_pair())
        self.assertEqual([extension.claim_id for extension in plan.extensions], [11])
        self.assertEqual(plan.registered_ids, frozenset({10}))
        adapter.get_allocated_bytes.assert_called_once_with(9)

    def test_adoption_plan_rejects_registered_byte_mismatch(self):
        service, _ = self.adoption_service(adapter=make_adapter(pending=[10], allocated=1))
        with self.assertRaisesRegex(MigrationError, "records 1 bytes"):
            service.adoption_plan(self.make_pair())

    def test_adoption_plan_rejects_wrong_target_state(self):
        service, _ = self.adoption_service()
        with self.assertRaisesRegex(MigrationError, "expected ACCEPTED"):
            service.adoption_plan(self.make_pair(target=make_target(state=PoRepMarketDealState.ACTIVE)))

    def test_adoption_plan_rejects_finished_posting(self):
        adapter = make_adapter(pending=[10], allocated=32)
        adapter.is_datacap_posting_finished.return_value = True
        service, _ = self.adoption_service(adapter=adapter)
        with self.assertRaisesRegex(MigrationError, "already finished"):
            service.adoption_plan(self.make_pair())

    def test_adoption_plan_operational_flag(self):
        adapter = make_adapter(pending=[10], allocated=32)
        adapter.is_operational.return_value = False
        service, _ = self.adoption_service(adapter=adapter)
        with self.assertRaisesRegex(MigrationError, "not operational"):
            service.adoption_plan(self.make_pair())
        self.assertFalse(service.adoption_plan(self.make_pair(), require_operational=False).complete)

    def test_adoption_plan_rejects_size_outside_padding(self):
        service, _ = self.adoption_service()
        with self.assertRaisesRegex(MigrationError, "not within"):
            service.adoption_plan(self.make_pair(target=make_target(requested=100)))
        service.adoption_plan(self.make_pair(target=make_target(requested=70)))

    def test_adapter_checks_market_and_evidence_type(self):
        service = self.make_service()
        pair = self.make_pair()
        with patch("cli.services.migration.DataCapEvidenceAdapter") as adapter_class:
            adapter = adapter_class.return_value
            adapter.get_porep_market_contract_address.return_value = MARKET
            service.view_helper.porep_market_contract.return_value = OTHER
            with self.assertRaisesRegex(MigrationError, "different PoRep Market"):
                service.adapter(pair)
            service.view_helper.porep_market_contract.return_value = MARKET
            adapter.evidence_type.return_value = DataCapEvidenceType.VERIF_REG_CLAIMS
            self.assertIs(service.adapter(pair), adapter)

    def receipt_fixture(self, registered, allocated, term_max):
        service = self.make_service()
        service.web3.state_get_claims.return_value = {"10": rpc_claim(TermMax=term_max)}
        plan = make_plan(registered=[11])
        batch = AdoptionPlan(plan.source_claims, plan.registered_ids, plan.extensions[:0] + (
            ClaimExtension(ActorId(1234), 10, 700_000, 32),))
        patcher = patch("cli.services.migration.DataCapEvidenceAdapter", return_value=make_adapter(pending=registered, allocated=allocated))
        patcher.start()
        self.addCleanup(patcher.stop)
        return service, plan, batch

    def test_validate_batch_receipt(self):
        pair = self.make_pair()
        service, plan, batch = self.receipt_fixture([11], 32, 700_000)
        with self.assertRaisesRegex(MigrationError, "did not register"):
            service.validate_batch_receipt(pair, plan, batch)
        service, plan, batch = self.receipt_fixture([10, 11], 64, 600_000)
        with self.assertRaisesRegex(MigrationError, "was not extended"):
            service.validate_batch_receipt(pair, plan, batch)
        service, plan, batch = self.receipt_fixture([10, 11], 64, 700_000)
        service.validate_batch_receipt(pair, plan, batch)

    def test_pair_by_claims_maps_v2_to_v1_by_intersection(self):
        service = self.make_service()
        client = service.source_market.get_client_contract.return_value
        client.allocation_ids.side_effect = lambda deal_id: {3: [10, 11], 4: [20]}[deal_id]
        adapters = {EthAddress("0x7777777777777777777777777777777777777777"): make_adapter(pending=[20]),
                    EthAddress("0x8888888888888888888888888888888888888888"): make_adapter(pending=[10], confirmed=[30]),
                    EthAddress("0x9999999999999999999999999999999999999999"): make_adapter()}

        def view(deal_id, adapter_address):
            target = make_target()
            target.deal.deal_id = deal_id
            target.deal.evidence_adapter_address = adapter_address
            return target

        addresses = list(adapters)
        targets = [view(101, addresses[0]), view(102, addresses[1]), view(103, addresses[2]), view(104, EthAddress(EthAddress.ZERO_ADDRESS))]
        first = make_source()
        sources = [first, LegacyDeal(**{**first.__dict__, "deal_id": 4})]
        with patch("cli.services.migration.DataCapEvidenceAdapter", side_effect=lambda address: adapters[address]):
            self.assertEqual(service.pair_by_claims(targets, sources), {101: 4, 102: 3})


class ClientCommandTests(Web3Singleton):
    def setUp(self):
        self.runner = CliRunner()
        self.signer = MagicMock(side_effect=AssertionError("signer must not be loaded"))
        self.service = MagicMock()
        self.service.web3.get_block_number.return_value = EPOCH
        self.service.transfer_params = MigrationService.transfer_params
        for target, value in (("cli.commands.client.migration.client_signer", self.signer),
                              ("cli.commands.client.migration.client_address", MagicMock(return_value=CLIENT)),
                              ("cli.commands.client.migration.migration_service", MagicMock(return_value=self.service)),
                              ("cli.commands.migration_utils.token_info", MagicMock(return_value=("USDFC", 18)))):
            patcher = patch(target, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def set_pair(self, target=None, source=None, rail=None, finalized=False):
        pair = MigrationPair(source or make_source(), None if finalized else rail or make_rail(), target or make_target())
        patcher = patch("cli.commands.client.migration.load_pair", return_value=pair)
        self.load_pair = patcher.start()
        self.addCleanup(patcher.stop)
        return pair

    def patch_module(self, name, **kwargs):
        patcher = patch(f"cli.commands.client.migration.{name}", **kwargs)
        mock = patcher.start()
        self.addCleanup(patcher.stop)
        return mock

    def test_adopt_print_only_shows_plan_without_signer(self):
        self.set_pair(target=make_target(rail_id=7))
        self.service.adoption_plan.return_value = make_plan(registered=[10])
        adapter = self.patch_module("DataCapEvidenceAdapter").return_value
        adapter.estimate_gas.return_value = 123
        result = self.runner.invoke(adopt_v1_claims, ["9", "3", "--print-only"])
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertIn("to adopt now: 1", result.output)
        self.assertIn("batch 1: 1 claim(s), estimated gas 123", result.output)
        adapter.call_contract.assert_called_once()
        adapter.submit_datacap_batch.assert_not_called()
        self.signer.assert_not_called()

    def test_adopt_complete_plan_reports_registered(self):
        self.set_pair()
        self.service.adoption_plan.return_value = make_plan(registered=[10, 11])
        adapter_class = self.patch_module("DataCapEvidenceAdapter")
        result = self.runner.invoke(adopt_v1_claims, ["9", "3"])
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertIn("All V1 claims are registered", result.output)
        self.assertIn("finish-migration 9 3", result.output)
        self.assertNotIn("init-deal", result.output)
        adapter_class.assert_not_called()
        self.signer.assert_not_called()

    def test_adopt_without_v2_rail_stops_before_preflight(self):
        self.set_pair(target=make_target(rail_id=0))
        self.service.adoption_plan.return_value = make_plan(registered=[10])
        adapter_class = self.patch_module("DataCapEvidenceAdapter")
        result = self.runner.invoke(adopt_v1_claims, ["9", "3", "--print-only"])
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertIn("has no payment rail yet; run", result.output)
        self.assertIn("init-deal 9", result.output)
        adapter_class.return_value.call_contract.assert_not_called()
        adapter_class.return_value.estimate_gas.assert_not_called()
        self.signer.assert_not_called()

        result = self.runner.invoke(adopt_v1_claims, ["9", "3"])
        self.assertNotEqual(result.exit_code, 0)
        self.assertIn("has no payment rail yet; run", result.output)
        self.assertIn("init-deal 9", result.output)
        adapter_class.return_value.call_contract.assert_not_called()
        self.signer.assert_not_called()

    def test_adopt_rejects_other_clients_deal(self):
        self.set_pair(source=make_source(client=OTHER))
        result = self.runner.invoke(adopt_v1_claims, ["9", "3", "--print-only"])
        self.assertNotEqual(result.exit_code, 0)
        self.assertIn("not " + CLIENT, result.output)

    def finish_fixture(self, rail_id=7, rail_status=FileCoinPayRailStatus.PREPARED, plan=None):
        self.set_pair(target=make_target(rail_id=rail_id))
        self.service.adoption_plan.return_value = plan or make_plan(registered=[10, 11])
        adapter = self.patch_module("DataCapEvidenceAdapter").return_value
        adapter.is_datacap_posting_finished.return_value = False
        adapter.get_allocated_bytes.return_value = 64
        self.patch_module("FileCoinPayValidator").return_value.get_rail_status.return_value = rail_status
        self.patch_module("PoRepMarket").return_value.get_deal_activation_padding.return_value = 1000
        return adapter

    def test_finish_refuses_without_rail(self):
        self.finish_fixture(rail_id=0)
        result = self.runner.invoke(finish_migration, ["9", "3"])
        self.assertNotEqual(result.exit_code, 0)
        self.assertIn("init-deal", result.output)

    def test_finish_refuses_unprepared_rail(self):
        self.finish_fixture(rail_status=FileCoinPayRailStatus.NONE)
        result = self.runner.invoke(finish_migration, ["9", "3"])
        self.assertNotEqual(result.exit_code, 0)
        self.assertIn("expected PREPARED", result.output)

    def test_finish_refuses_incomplete_plan(self):
        self.finish_fixture(plan=make_plan(registered=[10]))
        result = self.runner.invoke(finish_migration, ["9", "3"])
        self.assertNotEqual(result.exit_code, 0)
        self.assertIn("1 V1 claim(s) are not registered", result.output)
        self.signer.assert_not_called()

    def test_finish_print_only_ready(self):
        adapter = self.finish_fixture()
        result = self.runner.invoke(finish_migration, ["9", "3", "--print-only"])
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertIn("Ready to finish DataCap posting", result.output)
        self.load_pair.assert_called_once_with(self.service, 9, 3, require_paying=False)
        adapter.finish_datacap_posting.assert_not_called()
        self.signer.assert_not_called()

    def test_finish_dry_run_acts_as_print_only(self):
        adapter = self.finish_fixture()
        self.patch_module("is_dry_run", return_value=True)
        result = self.runner.invoke(finish_migration, ["9", "3"])
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertIn("Dry-run mode: acting as --print-only", result.output)
        self.assertIn("Ready to finish DataCap posting", result.output)
        adapter.finish_datacap_posting.assert_not_called()
        self.signer.assert_not_called()

    def close_fixture(self, rail=None, progress=None, target=None, finalized=False):
        self.set_pair(target=target or make_target(state=PoRepMarketDealState.ACTIVE), rail=rail, finalized=finalized)
        self.service.adoption_progress.return_value = progress or ({10, 11}, {10, 11})
        return self.patch_module("FileCoinPay").return_value

    def test_close_requires_v2_deal_id(self):
        pay = self.close_fixture(rail=make_rail())
        result = self.runner.invoke(close_v1_deal, ["3"])
        self.assertEqual(result.exit_code, 2, result.output)
        self.assertIn("--v2-deal-id", result.output)
        pay.call_contract.assert_not_called()
        self.signer.assert_not_called()

    def test_close_refuses_when_v2_does_not_hold_all_claims(self):
        pay = self.close_fixture(rail=make_rail(), progress=({10, 11}, {10}))
        result = self.runner.invoke(close_v1_deal, ["3", "--v2-deal-id", "9"])
        self.assertNotEqual(result.exit_code, 0)
        self.assertIn("holds 1/2 claims", result.output)
        self.assertIn("strand", result.output)
        pay.call_contract.assert_not_called()
        self.signer.assert_not_called()

    def test_close_terminates_open_rail(self):
        pay = self.close_fixture(rail=make_rail(end_epoch=0))
        result = self.runner.invoke(close_v1_deal, ["3", "--v2-deal-id", "9", "--print-only"])
        self.assertEqual(result.exit_code, 0, result.output)
        self.load_pair.assert_called_once_with(self.service, 9, 3, require_paying=False)
        pay.contract.functions.terminateRail.assert_called_once_with(5)
        pay.contract.functions.settleTerminatedRailWithoutValidation.assert_not_called()
        pay.call_contract.assert_called_once()
        self.assertIn("holds all 2 V1 claims", result.output)
        self.assertIn("Ready to terminate rail 5", result.output)
        self.signer.assert_not_called()

    def test_close_dry_run_acts_as_print_only(self):
        pay = self.close_fixture(rail=make_rail(end_epoch=0))
        self.patch_module("is_dry_run", return_value=True)
        result = self.runner.invoke(close_v1_deal, ["3", "--v2-deal-id", "9"])
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertIn("Dry-run mode: acting as --print-only", result.output)
        self.assertIn("Ready to terminate rail 5", result.output)
        pay.terminate_rail.assert_not_called()
        self.signer.assert_not_called()

    def test_close_sends_termination_and_reads_back_end_epoch(self):
        pay = self.close_fixture(rail=make_rail(end_epoch=0))
        pay.terminate_rail.return_value.tx_hash = "0xabc"
        self.patch_module("open_rail", return_value=make_rail(end_epoch=EPOCH + 30 * EPOCHS_IN_DAY))
        self.patch_module("utils.confirm", return_value=True)
        self.signer.side_effect = None
        result = self.runner.invoke(close_v1_deal, ["3", "--v2-deal-id", "9"])
        self.assertEqual(result.exit_code, 0, result.output)
        pay.terminate_rail.assert_called_once_with(5, self.signer.return_value)
        self.assertIn(f"Payments stop at epoch {EPOCH + 30 * EPOCHS_IN_DAY}", result.output)

    def test_close_waits_while_terminated_rail_still_pays(self):
        pay = self.close_fixture(rail=make_rail(end_epoch=EPOCH + 100))
        result = self.runner.invoke(close_v1_deal, ["3", "--v2-deal-id", "9"])
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertIn("still paying until", result.output)
        pay.call_contract.assert_not_called()
        self.signer.assert_not_called()

    def test_close_settles_after_end_epoch(self):
        pay = self.close_fixture(rail=make_rail(end_epoch=EPOCH - 100))
        result = self.runner.invoke(close_v1_deal, ["3", "--v2-deal-id", "9", "--print-only"])
        self.assertEqual(result.exit_code, 0, result.output)
        pay.contract.functions.settleTerminatedRailWithoutValidation.assert_called_once_with(5)
        pay.contract.functions.terminateRail.assert_not_called()
        self.assertIn("Ready to settle and finalize rail 5", result.output)

    def test_close_reports_already_settled_rail(self):
        pay = self.close_fixture(finalized=True)
        result = self.runner.invoke(close_v1_deal, ["3", "--v2-deal-id", "9"])
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertIn("already settled and finalized; nothing to do", result.output)
        pay.call_contract.assert_not_called()
        self.signer.assert_not_called()

    def test_close_refuses_when_v2_not_active(self):
        pay = self.close_fixture(rail=make_rail(), target=make_target(state=PoRepMarketDealState.ACCEPTED))
        result = self.runner.invoke(close_v1_deal, ["3", "--v2-deal-id", "9"])
        self.assertNotEqual(result.exit_code, 0)
        self.assertIn("not ACTIVE", result.output)
        pay.call_contract.assert_not_called()
        self.signer.assert_not_called()

    def test_close_termination_shortfall_prints_exact_deposit(self):
        pay = self.close_fixture(rail=make_rail(end_epoch=0))
        pay.call_contract.side_effect = click.ClickException("execution reverted")
        pay.get_account_info_if_settled.return_value = SimpleNamespace(current_funds=0, available_funds=0, funded_until_epoch=EPOCH - 10,
                                                                       current_lockup_rate=11)
        self.patch_module("token_info", return_value=("USDFC", 6))
        result = self.runner.invoke(close_v1_deal, ["3", "--v2-deal-id", "9", "--print-only"])
        self.assertNotEqual(result.exit_code, 0)
        # 11 units/epoch * (10 epochs behind + one day) = 31790 units
        self.assertEqual(11 * (10 + EPOCHS_IN_DAY), 31790)
        self.assertIn("Deposit 0.03179 USDFC with", result.output)
        self.assertIn("Cannot terminate rail 5 right now", result.output)
        self.signer.assert_not_called()


class SpCommandTests(Web3Singleton):
    @staticmethod
    def sptool_run(returncode=0, stdout="", stderr=""):
        return patch("cli.commands.sp.migration.subprocess.run", return_value=SimpleNamespace(returncode=returncode, stdout=stdout, stderr=stderr))

    def test_run_sptool_fails_when_every_sector_is_skipped(self):
        output = "skipping sector 7: claim ends too early\nSkipping sector 8: claim ends too early\n"
        with self.sptool_run(stdout=output), self.assertRaisesRegex(click.ClickException, "would skip every sector"):
            _run_sptool(["sptool"], 2)

    def test_run_sptool_returns_output_when_some_sectors_are_skipped(self):
        output = "skipping sector 7: claim ends too early\nextended 1 sector\n"
        with self.sptool_run(stdout=output):
            self.assertEqual(_run_sptool(["sptool"], 2), output.strip())

    def test_run_sptool_reports_failure(self):
        with self.sptool_run(returncode=1, stderr="boom"), self.assertRaisesRegex(click.ClickException, r"sptool failed \(1\)"):
            _run_sptool(["sptool"], 2)

    def test_sector_expirations(self):
        web3 = MagicMock()
        web3.state_sector_get_info.side_effect = lambda provider, sector: None if sector == 9 else {"Expiration": sector * 10}
        with patch("cli.commands.sp.migration.Web3Service", return_value=web3):
            self.assertEqual(sector_expirations(ActorId(1234), {8, 7}), {7: 70, 8: 80})
            with self.assertRaisesRegex(MigrationError, "not live on chain"):
                sector_expirations(ActorId(1234), {7, 9})

    def test_extend_deal_sectors_print_only_writes_below_target_sectors(self):
        web3 = MagicMock()
        web3.get_block_number.return_value = EPOCH
        web3.state_get_claims.return_value = {"10": rpc_claim(Sector=7), "11": rpc_claim(Sector=8)}
        web3.state_sector_get_info.side_effect = lambda provider, sector: {"Expiration": 2_000 if sector == 7 else 9_000_000}
        target = make_target(state=PoRepMarketDealState.ACTIVE)
        for name, kwargs in (("Web3Service", {"return_value": web3}), ("adapter_claim_ids", {"return_value": [10, 11]}),
                             ("DataCapEvidenceAdapter", {}), ("sp_organization_address", {"return_value": CLIENT})):
            patcher = patch(f"cli.commands.sp.migration.{name}", **kwargs)
            patcher.start()
            self.addCleanup(patcher.stop)
        for name in ("PoRepMarketViewHelper", "SPRegistry"):
            patcher = patch(f"cli.commands.sp.migration.{name}")
            mock = patcher.start()
            self.addCleanup(patcher.stop)
            if name == "SPRegistry":
                mock.return_value.get_provider_views_by_organization.return_value = [SimpleNamespace(provider_id=ActorId(1234))]
            else:
                mock.return_value.get_deal_view.return_value = target

        with tempfile.TemporaryDirectory() as directory, patch("cli.commands.sp.migration.subprocess.run") as run:
            sector_file = os.path.join(directory, "sectors.txt")
            result = CliRunner().invoke(extend_deal_sectors, ["9", "--print-only", "--target-epoch", "100000", "--sector-file", sector_file])
            run.assert_not_called()
            self.assertEqual(result.exit_code, 0, result.output)
            with open(sector_file, encoding="utf-8") as file:
                self.assertEqual(file.read(), "7\n")
        self.assertIn("sptool command: sptool --actor f01234 sectors extend --sector-file", result.output)
        self.assertIn("--new-expiration 100000 --tolerance 0 --really-do-it", result.output)


class ContractServiceBatchTests(unittest.TestCase):
    def test_pending_transaction_in_batch_mode_is_a_click_exception(self):
        service = object.__new__(ContractService)
        service.web3 = MagicMock()
        service.web3.ensure_no_pending_transactions.side_effect = RuntimeError("1 pending transaction")
        signer = MagicMock()
        with ContractService.batch_confirmation(), self.assertRaisesRegex(click.ClickException, "1 pending transaction"):
            service.sign_and_send_tx(MagicMock(), signer)
        service.web3.ensure_no_pending_transactions.assert_called_once_with(signer.address.return_value)
        signer.sign_transaction.assert_not_called()


if __name__ == "__main__":
    unittest.main()
