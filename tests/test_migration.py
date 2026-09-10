import unittest
import json
from collections.abc import Mapping
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import cbor2
from click.testing import CliRunner
from eth_abi import encode
from web3 import Web3

from cli.commands.client.migration import _account_funding_by_token
from cli.services.contracts.legacy_porep_market import LegacyValidator
from cli.services.contracts.porep_market import PoRepMarketDealState, PoRepMarketDealType
from cli.services.migration import (
    CLAIM_ROUNDING_RESERVE_EPOCHS,
    PREPARATION_BUFFER_EPOCHS,
    Claim,
    MigrationError,
    MigrationMarker,
    MigrationPair,
    MigrationProvenanceUnavailable,
    MigrationService,
    build_adoption_plan,
    migration_manifest_location,
    parse_migration_marker,
)
from cli.services.web3_service import ActorId, EthAddress, Web3Service

MARKET = EthAddress("0x1111111111111111111111111111111111111111")
CLIENT_A = EthAddress("0x2222222222222222222222222222222222222222")
CLIENT_B = EthAddress("0x3333333333333333333333333333333333333333")
TOKEN = EthAddress("0x4444444444444444444444444444444444444444")

class MigrationTests(unittest.TestCase):
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

    @staticmethod
    def claim(claim_id=10, term_max=600_000, term_start=100, size=32):
        return Claim(
            claim_id=claim_id,
            provider=ActorId(1234),
            client=ActorId(5678),
            data="baga-piece",
            size=size,
            term_min=518_400,
            term_max=term_max,
            term_start=term_start,
            sector=claim_id + 100,
        )

    def test_marker_round_trip_preserves_original_url_and_query(self):
        marker = MigrationMarker(314, MARKET, 9)
        location = migration_manifest_location("https://example.test/manifest.json?x=1", marker)
        self.assertEqual(parse_migration_marker(location), marker)
        self.assertTrue(location.startswith("https://example.test/manifest.json?x=1#"))
        self.assertTrue(migration_manifest_location("HTTP://EXAMPLE.test/path?", marker).startswith(
            "HTTP://EXAMPLE.test/path?#"
        ))

    def test_direct_creation_binds_real_abi_request_and_event_slis(self):
        from cli.services import migration as migration_service_module

        abi_path = Path("cli/services/contracts/abi/PoRepMarket.json")
        contract = Web3().eth.contract(address=MARKET, abi=json.loads(abi_path.read_text()))
        request_slis = (8000, 1_000_000, 500, 90)
        manifest_hash = b"\x01" * 32
        manifest_location = "https://example.test/manifest"
        request = (
            manifest_hash,
            32,
            100,
            manifest_location,
            TOKEN,
            180,
            PoRepMarketDealType.PUBLIC.value,
            request_slis,
        )
        calldata = contract.encode_abi("proposeDealWithSpecificOffer", args=[7, request, CLIENT_A])
        event_topic = Web3.keccak(
            text="DealCreated(uint256,address,uint64,(uint16,uint64,uint16,uint8),bytes32,string,uint256,uint256)"
        )
        raw_log = {
            "address": MARKET,
            "topics": [
                event_topic,
                (9).to_bytes(32, "big"),
                bytes.fromhex(CLIENT_A[2:]).rjust(32, b"\x00"),
                (1234).to_bytes(32, "big"),
            ],
            "data": encode(
                ["(uint16,uint64,uint16,uint8)", "bytes32", "string", "uint256", "uint256"],
                [request_slis, manifest_hash, manifest_location, 32, 500],
            ),
            "blockNumber": 500,
            "transactionHash": b"\x02" * 32,
            "transactionIndex": 0,
            "blockHash": b"\x03" * 32,
            "logIndex": 0,
            "removed": False,
        }
        decoded_log = contract.events.DealCreated().process_log(raw_log)
        self.assertIsInstance(decoded_log["args"]["requirements"], Mapping)
        contract.events.DealCreated = MagicMock(return_value=SimpleNamespace(
            get_logs=MagicMock(return_value=[decoded_log])
        ))
        target = SimpleNamespace(
            deal=SimpleNamespace(
                deal_id=9,
                client_address=CLIENT_A,
                provider_id=ActorId(1234),
                proposed_at_epoch=500,
                offer_id=7,
                deal_type=PoRepMarketDealType.PUBLIC,
            ),
            data=SimpleNamespace(manifest_hash=manifest_hash, manifest_location=manifest_location),
            terms=SimpleNamespace(requested_size_bytes=32),
            payment=SimpleNamespace(payment_token=TOKEN, price_per_32_gib_per_month=90),
            required_slis=SimpleNamespace(
                retrievability_bps=9000,
                bandwidth_bytes_per_second=2_000_000,
                latency_ms=250,
                indexing_pct=95,
            ),
        )
        service = object.__new__(MigrationService)
        service.view_helper = SimpleNamespace(
            porep_market_contract=MagicMock(return_value=MARKET)
        )
        service.web3 = SimpleNamespace(
            get_transaction=MagicMock(return_value={"to": MARKET, "input": calldata}),
            w3=MagicMock(return_value=SimpleNamespace(
                eth=SimpleNamespace(get_transaction_receipt=MagicMock(return_value={"status": 1}))
            )),
        )
        pair = MigrationPair(MigrationMarker(314, MARKET, 1), SimpleNamespace(), target)
        with patch.object(migration_service_module, "PoRepMarket", return_value=SimpleNamespace(
            contract=contract
        )):
            service.verify_direct_creation(pair)
            target.data.manifest_location += "#forged"
            with self.assertRaises(MigrationError):
                service.verify_direct_creation(pair)
            target.data.manifest_location = manifest_location
            with patch.object(contract, "decode_function_input", return_value=(
                SimpleNamespace(fn_name="proposeDeal"), {}
            )), self.assertRaises(MigrationError):
                service.verify_direct_creation(pair)

    def test_marker_rejects_existing_or_conflicting_fragments(self):
        with self.assertRaises(MigrationError):
            migration_manifest_location("https://example.test/x#old", MigrationMarker(314, MARKET, 1))
        with self.assertRaises(MigrationError):
            migration_manifest_location("https://example.test/x#", MigrationMarker(314, MARKET, 1))
        with self.assertRaises(MigrationError):
            parse_migration_marker("https://example.test/x#porep-migration=v2:314:0x0:1")

    def test_missing_claims_generate_uint_cbor_and_exact_datacap_amount(self):
        claim = self.claim(term_max=1_000)
        plan = build_adoption_plan([claim], [], [], target_epoch=10_000, current_epoch=500)
        expected_term = 10_000 + CLAIM_ROUNDING_RESERVE_EPOCHS - claim.term_start + 1
        self.assertEqual(cbor2.loads(plan.operator_data), [[], [[1234, 10, expected_term]]])
        self.assertEqual(plan.datacap_amount, claim.size * 10 ** 18)
        self.assertGreater(expected_term, claim.term_max)

    def test_pending_and_confirmed_union_is_complete_without_recharge(self):
        claims = [self.claim(10), self.claim(11)]
        plan = build_adoption_plan(claims, [10], [11], target_epoch=500_000, current_epoch=1_000)
        self.assertTrue(plan.complete)
        self.assertEqual(plan.datacap_amount, 0)
        self.assertEqual(cbor2.loads(plan.operator_data), [[], []])

    def test_bounded_batch_refresh_recomputes_terms_and_checks_receipt_state(self):
        original = self.claim(term_max=1_000)
        baseline = build_adoption_plan([original], [], [], target_epoch=10_000, current_epoch=500)
        planned_batch = baseline.batches()[0]

        def raw(term_max=20_000, data=original.data):
            return {
                "Provider": int(original.provider),
                "Client": int(original.client),
                "Data": data,
                "Size": original.size,
                "TermMin": original.term_min,
                "TermMax": term_max,
                "TermStart": original.term_start,
                "Sector": original.sector,
            }

        service = object.__new__(MigrationService)
        service.web3 = SimpleNamespace(
            get_tipset_key=MagicMock(return_value=[{"/": "tipset"}]),
            get_block_number=MagicMock(return_value=500),
            state_get_claims=MagicMock(return_value={"10": raw()}),
        )
        service.source_market = SimpleNamespace(get_client_contract=MagicMock(return_value=SimpleNamespace(
            is_claim_terminated=MagicMock(return_value=False)
        )))
        service._qualify_source_rail = MagicMock()
        service._qualify_claim_sectors = MagicMock()
        pair = SimpleNamespace(
            source=SimpleNamespace(provider=original.provider),
            target=SimpleNamespace(deal=SimpleNamespace(
                deal_id=9,
                evidence_adapter_address=MARKET,
                proposed_at_epoch=500,
            )),
        )

        refreshed = service.validate_outgoing_batch(pair, baseline, planned_batch)

        self.assertEqual(refreshed.extensions[0].new_term_max, 20_001)
        self.assertEqual(cbor2.loads(refreshed.operator_data), [[], [[1234, 10, 20_001]]])
        service._qualify_claim_sectors.assert_called_once()

        service.web3.state_get_claims.return_value = {"10": raw(data="changed-piece")}
        with self.assertRaisesRegex(MigrationError, "identity changed"):
            service.validate_outgoing_batch(pair, baseline, planned_batch)

        service.web3.state_get_claims.return_value = {"10": raw(term_max=20_001)}
        adapter = SimpleNamespace(
            get_allocation_ids_per_deal=MagicMock(return_value=([10], 1)),
            get_claim_ids=MagicMock(return_value=([], 0)),
            get_allocated_bytes=MagicMock(return_value=original.size),
        )
        from cli.services import migration as migration_service_module
        with patch.object(migration_service_module, "DataCapEvidenceAdapter", return_value=adapter):
            service.validate_batch_receipt(pair, baseline, refreshed)
            service.web3.state_get_claims.return_value = {"10": raw(term_max=20_000)}
            with self.assertRaisesRegex(MigrationError, "required term"):
                service.validate_batch_receipt(pair, baseline, refreshed)

        service._qualify_source_rail.reset_mock()
        service.web3.get_block_number.return_value = 500 + PREPARATION_BUFFER_EPOCHS + 1
        with self.assertRaisesRegex(MigrationError, "passed its fixed preparation deadline"):
            service.validate_outgoing_batch(pair, baseline, planned_batch)
        service._qualify_source_rail.assert_not_called()

        service.web3.get_block_number.return_value = 500
        service._qualify_source_rail.side_effect = MigrationError("V1 rail stopped")
        with self.assertRaisesRegex(MigrationError, "V1 rail stopped"):
            service.validate_outgoing_batch(pair, baseline, planned_batch)

    def test_foreign_or_insufficient_registered_claim_fails(self):
        with self.assertRaises(MigrationError):
            build_adoption_plan([self.claim()], [99], [], target_epoch=500_000, current_epoch=1_000)
        with self.assertRaises(MigrationError):
            build_adoption_plan(
                [self.claim(term_max=2_000)], [10], [], target_epoch=500_000, current_epoch=1_000
            )

    def test_scoped_discovery_continues_after_bad_deal_and_isolates_duplicate_source(self):
        marker1 = MigrationMarker(314, MARKET, 1)
        marker3 = MigrationMarker(314, MARKET, 3)

        def view(target_id, client, location):
            return SimpleNamespace(
                deal=SimpleNamespace(deal_id=target_id, client_address=client, provider_id=ActorId(1234)),
                data=SimpleNamespace(manifest_location=location),
            )

        views = [
            view(10, CLIENT_A, migration_manifest_location("https://a/1", marker1)),
            view(11, CLIENT_A, "https://a/bad#wrong"),
            view(12, CLIENT_A, migration_manifest_location("https://a/3", marker3)),
            view(13, CLIENT_B, migration_manifest_location("https://b/3", marker3)),
            view(14, CLIENT_B, "https://b/bad#wrong"),
        ]
        service = object.__new__(MigrationService)
        service.web3 = self.web3
        service.source_chain_id = 314
        service.trusted_source_market = MARKET
        service.view_helper = SimpleNamespace(get_deal_views=MagicMock(return_value=views))
        service.source_market = SimpleNamespace(get_deal=MagicMock(side_effect=lambda deal_id: f"source-{deal_id}"))
        service.discovery_errors = []
        service.validate_pair = MagicMock()
        service._validate_migration_policy = MagicMock()
        service.verify_direct_creation = MagicMock()

        pairs = service.discover(client=CLIENT_A)

        self.assertEqual([pair.target.deal.deal_id for pair in pairs], [10])
        self.assertTrue(any("V2 11" in error for error in service.discovery_errors))
        self.assertTrue(any("V2 12" in error and "ambiguous" in error for error in service.discovery_errors))
        self.assertFalse(any("V2 14" in error for error in service.discovery_errors))

    def test_unverifiable_matching_reference_blocks_duplicate_proposal(self):
        marker = MigrationMarker(314, MARKET, 3)
        view = SimpleNamespace(
            deal=SimpleNamespace(deal_id=10),
            data=SimpleNamespace(manifest_location=migration_manifest_location("https://a/10", marker)),
        )
        service = object.__new__(MigrationService)
        service.source_chain_id = 314
        service.trusted_source_market = MARKET
        service.view_helper = SimpleNamespace(get_deal_views=MagicMock(return_value=[view]))
        service.source_market = SimpleNamespace(get_deal=MagicMock(return_value="source"))
        service.validate_pair = MagicMock()
        service._validate_migration_policy = MagicMock()
        service.verify_direct_creation = MagicMock(
            side_effect=MigrationProvenanceUnavailable("receipt RPC unavailable")
        )

        with self.assertRaisesRegex(MigrationProvenanceUnavailable, "receipt RPC unavailable"):
            service.source_reference_targets(3)

    def test_untrusted_copy_does_not_block_scoped_discovery(self):
        marker = MigrationMarker(314, MARKET, 3)

        def view(target_id, client):
            return SimpleNamespace(
                deal=SimpleNamespace(deal_id=target_id, client_address=client, provider_id=ActorId(1234)),
                data=SimpleNamespace(manifest_location=migration_manifest_location(f"https://a/{target_id}", marker)),
            )

        views = [view(10, CLIENT_A), view(11, CLIENT_B)]
        service = object.__new__(MigrationService)
        service.web3 = self.web3
        service.source_chain_id = 314
        service.trusted_source_market = MARKET
        service.view_helper = SimpleNamespace(get_deal_views=MagicMock(return_value=views))
        service.source_market = SimpleNamespace(get_deal=MagicMock(return_value="source"))
        service.discovery_errors = []
        service.validate_pair = MagicMock()
        service._validate_migration_policy = MagicMock()
        service.verify_direct_creation = MagicMock(
            side_effect=lambda pair: (_ for _ in ()).throw(MigrationError("not direct admin"))
            if pair.target.deal.deal_id == 11 else None
        )

        pairs = service.discover(client=CLIENT_A)

        self.assertEqual([pair.target.deal.deal_id for pair in pairs], [10])
        self.assertFalse(any("ambiguous" in error for error in service.discovery_errors))
        self.assertEqual(service.source_reference_targets(3), [10])

    def test_account_funding_counts_prepared_accepted_and_active_obligations(self):
        def view(state, requested, price, rate, deal_id=1, rail_id=0):
            return SimpleNamespace(
                deal=SimpleNamespace(
                    client_address=CLIENT_A, state=state, deal_id=deal_id, rail_id=rail_id
                ),
                terms=SimpleNamespace(requested_size_bytes=requested),
                payment=SimpleNamespace(
                    payment_token=TOKEN,
                    price_per_32_gib_per_month=price,
                    rail_max_rate_per_epoch=rate,
                ),
            )

        views = [
            view(PoRepMarketDealState.ACCEPTED, 33, 7, 0),
            view(PoRepMarketDealState.ACCEPTED, 3_200, 700, 0, deal_id=99),
            view(PoRepMarketDealState.ACTIVE, 32, 0, 3),
            view(PoRepMarketDealState.FINALIZED, 32, 100, 100),
        ]
        account = SimpleNamespace(current_lockup_rate=3, funded_until_epoch=90)
        with patch("cli.commands.client.migration.PoRepMarket") as market, \
                patch("cli.commands.client.migration.PoRepMarketViewHelper") as helper, \
                patch("cli.commands.client.migration.FileCoinPay") as pay, \
                patch("cli.commands.client.migration.Web3Service") as web3:
            market.return_value.get_sector_size_bytes.return_value = 32
            market.return_value.get_epochs_in_month.return_value = 100
            helper.return_value.get_deal_views.return_value = views
            pay.return_value.get_account_info_if_settled.return_value = account
            web3.return_value.get_block_number.return_value = 100

            totals = _account_funding_by_token(CLIENT_A, {TOKEN}, {1})

        requirement = totals[TOKEN]
        self.assertEqual(requirement.activation_reserve, 100)
        self.assertEqual(requirement.spending, 400)
        self.assertEqual(requirement.catch_up, 30)
        self.assertEqual(requirement.total, 530)

    def test_legacy_end_epoch_log_scan_uses_reverse_bounded_ranges(self):
        event = MagicMock()
        event.get_logs.side_effect = [[], [{"args": {"endEpoch": 8_888}}]]
        validator = object.__new__(LegacyValidator)
        validator.contract = SimpleNamespace(
            events=SimpleNamespace(DealEndEpochUpdated=MagicMock(return_value=event))
        )

        self.assertEqual(validator.deal_end_epoch(7, 1_000, 5_000, chunk_size=2_000), 8_888)
        self.assertEqual(event.get_logs.call_args_list[0].kwargs["from_block"], 3_001)
        self.assertEqual(event.get_logs.call_args_list[1].kwargs["from_block"], 1_001)

    @staticmethod
    def _proposal_objects():
        source = SimpleNamespace(
            deal_id=1,
            provider=ActorId(1234),
            client=CLIENT_A,
            size_bytes=32,
            duration_days=365,
            price_per_32_gib_per_month=50,
            requirements="legacy-slis",
            manifest_hash=b"\x01" * 32,
            manifest_location="https://example.test/manifest",
            rail_id=8,
        )
        payment = SimpleNamespace(token=TOKEN, active=True, price_per_32_gib_per_month=100)
        offer = SimpleNamespace(
            active=True,
            provider_id=ActorId(1234),
            payments=[payment],
            terms=SimpleNamespace(
                min_size_bytes=0,
                max_size_bytes=0,
                min_duration_epochs=0,
                max_duration_epochs=0,
            ),
            slis=SimpleNamespace(
                retrievability_bps=8000,
                bandwidth_bytes_per_second=1_000_000,
                latency_ms=500,
                indexing_pct=90,
            ),
        )
        return source, offer

    def test_propose_rejects_invalid_global_adapter_before_signer_or_broadcast(self):
        from scripts.migrations import v1_to_v2

        source, offer = self._proposal_objects()
        service = SimpleNamespace(
            source_chain_id=314,
            trusted_source_market=MARKET,
            source_inventory=MagicMock(return_value=(source, [self.claim()])),
            source_reference_targets=MagicMock(return_value=[]),
        )
        market = SimpleNamespace(
            get_epochs_in_month=MagicMock(return_value=86_400),
            get_global_evidence_adapter_address=MagicMock(return_value=CLIENT_B),
            address=MagicMock(return_value=MARKET),
            propose_deal_with_specific_offer=MagicMock(),
        )
        adapter = SimpleNamespace(evidence_type=MagicMock(return_value=SimpleNamespace(value=20)))
        token = SimpleNamespace(decimals=MagicMock(return_value=18), symbol=MagicMock(return_value="TOKEN"))
        with patch.object(v1_to_v2, "migration_service", return_value=service), \
                patch.object(v1_to_v2, "SPRegistry", return_value=SimpleNamespace(
                    get_offer_view=MagicMock(return_value=offer)
                )), \
                patch.object(v1_to_v2, "PoRepMarket", return_value=market), \
                patch.object(v1_to_v2, "DataCapEvidenceAdapter", return_value=adapter), \
                patch.object(v1_to_v2, "FileCoinPay", return_value=SimpleNamespace(
                    get_rail=MagicMock(return_value=SimpleNamespace(token=TOKEN))
                )), \
                patch.object(v1_to_v2, "ERC20Contract", return_value=token), \
                patch.object(v1_to_v2.utils, "get_env_required", return_value=TOKEN), \
                patch.object(v1_to_v2._admin, "admin_signer") as signer:
            result = CliRunner().invoke(v1_to_v2.migrations, ["--yes", "propose", "1", "7"])

        self.assertNotEqual(result.exit_code, 0)
        self.assertIn("not DataCap type 10", result.output)
        signer.assert_not_called()
        market.propose_deal_with_specific_offer.assert_not_called()

    def test_close_service_step_requires_completed_admin_prerequisites(self):
        from scripts.migrations import v1_to_v2

        pair = SimpleNamespace(
            source=SimpleNamespace(
                validator=CLIENT_B,
                client=CLIENT_A,
                rail_id=9,
                deal_id=3,
                proposed_at_epoch=1,
            ),
            target=SimpleNamespace(deal=SimpleNamespace(deal_id=10)),
        )
        service = SimpleNamespace(discover=MagicMock(return_value=[pair]), discovery_errors=[])
        validator = SimpleNamespace(
            min_epochs_between_settlements=MagicMock(return_value=2),
            deal_end_epoch=MagicMock(return_value=200),
            disable_future_rail_payments=MagicMock(),
        )
        pay = SimpleNamespace(get_rail=MagicMock(return_value=SimpleNamespace(
            lockup_period=0,
            end_epoch=0,
            from_address=CLIENT_A,
            to_address=CLIENT_B,
            token=TOKEN,
            operator=CLIENT_B,
            validator=CLIENT_B,
            payment_rate=1,
        )))
        with patch.object(v1_to_v2, "migration_service", return_value=service), \
                patch.object(v1_to_v2, "_validate_active_target", side_effect=lambda _, pair: pair), \
                patch.object(v1_to_v2, "OperationalLegacyValidator", return_value=validator), \
                patch.object(v1_to_v2, "OperationalFileCoinPay", return_value=pay), \
                patch.object(v1_to_v2, "is_dry_run", return_value=False), \
                patch.object(v1_to_v2, "Web3Service", return_value=SimpleNamespace(
                    get_block_number=MagicMock(return_value=100),
                    ensure_no_pending_transactions=MagicMock(),
                )):
            result = CliRunner().invoke(
                v1_to_v2.migrations,
                ["--yes", "close-v1-if-v2-active", "--step", "service", "10"],
            )

        self.assertNotEqual(result.exit_code, 0)
        self.assertIn("admin close prerequisites", result.output)
        validator.disable_future_rail_payments.assert_not_called()

    def test_close_resume_accepts_authoritative_finalized_event(self):
        from scripts.migrations import v1_to_v2

        pair = SimpleNamespace(
            source=SimpleNamespace(validator=CLIENT_B, rail_id=9, deal_id=3, proposed_at_epoch=1),
            target=SimpleNamespace(deal=SimpleNamespace(deal_id=10)),
        )
        service = SimpleNamespace(discover=MagicMock(return_value=[pair]), discovery_errors=[])
        pay = SimpleNamespace(
            get_rail=MagicMock(side_effect=RuntimeError("gone")),
            is_rail_finalized=MagicMock(return_value=True),
        )
        with patch.object(v1_to_v2, "migration_service", return_value=service), \
                patch.object(v1_to_v2, "_validate_active_target", side_effect=lambda _, pair: pair), \
                patch.object(v1_to_v2, "OperationalLegacyValidator"), \
                patch.object(v1_to_v2, "OperationalFileCoinPay", return_value=pay), \
                patch.object(v1_to_v2.Web3Service, "get_block_number", return_value=100), \
                patch.object(v1_to_v2, "is_dry_run", return_value=False):
            result = CliRunner().invoke(v1_to_v2.migrations, ["--yes", "close-v1-if-v2-active", "10"])

        self.assertEqual(result.exit_code, 0, result.output)
        self.assertIn("rail already finalized", result.output)

    def test_sp_extension_requires_chain_confirmation(self):
        from cli.commands.sp import migration as sp

        claim = SimpleNamespace(claim_id=7, sector=0, end_epoch=1_001)
        plan = SimpleNamespace(source_claims=(claim,), extensions=(), target_ids={7}, sector_target_epoch=1_000)
        pair = SimpleNamespace(
            source=SimpleNamespace(provider=ActorId(1234)),
            target=SimpleNamespace(deal=SimpleNamespace(deal_id=10, provider_id=ActorId(1234))),
        )
        service = SimpleNamespace(adoption_plan=MagicMock(return_value=plan))
        # name, initial expiration, readback, pending before/after, dry run, exit code, subprocess calls
        cases = [
            ("already done", 1000, 1000, False, False, False, 0, 0),
            ("preview", 999, 999, False, False, True, 0, 1),
            ("pending before", 999, 999, True, False, False, 1, 0),
            ("pending after", 999, 999, False, True, False, 1, 2),
            ("unknown result", 999, 999, False, False, False, 1, 2),
            ("confirmed", 999, 1000, False, False, False, 0, 2),
        ]
        for name, initial, readback, before, after, dry_run, exit_code, calls in cases:
            web3 = SimpleNamespace(mpool_pending_method=MagicMock(side_effect=[
                [{"Message": {}}] if before else [], [{"Message": {}}] if after else [],
            ]))
            with self.subTest(name=name), \
                    patch.object(sp, "migration_pairs", return_value=(service, [pair])), \
                    patch.object(sp, "_organization_providers", return_value={ActorId(1234)}), \
                    patch.object(sp, "_sector_expirations", side_effect=[{0: initial}, {0: readback}]), \
                    patch.object(sp.shutil, "which", return_value="/bin/echo"), \
                    patch.object(sp.os.path, "isfile", return_value=True), \
                    patch.object(sp.subprocess, "run", return_value=SimpleNamespace(
                        returncode=0, stdout="estimated gas", stderr=""
                    )) as run, \
                    patch.object(sp.utils, "confirm", return_value=True), \
                    patch.object(sp, "is_dry_run", return_value=dry_run), \
                    patch.object(sp, "Web3Service", return_value=web3):
                result = CliRunner().invoke(sp.extend_deal_sectors, ["10"])
            self.assertEqual(result.exit_code, exit_code, result.output)
            self.assertEqual(run.call_count, calls)
            if calls == 2:
                self.assertIn("--really-do-it", run.call_args.args[0])
                self.assertEqual(run.call_args.args[0][1:3], ["--actor", "f01234"])

    def test_root_migration_status_uses_common_filters_without_sp_context(self):
        import importlib

        from cli import cli as root_cli

        common = importlib.import_module("cli.commands.migration_status")
        with patch.object(common, "migration_pairs", return_value=(MagicMock(), [])) as pairs, \
                patch.object(common, "print_status"):
            result = CliRunner().invoke(
                root_cli,
                [
                    "migration-status",
                    "--client-address", str(CLIENT_A),
                    "--provider-id", "f01234",
                ],
            )

        self.assertEqual(result.exit_code, 0, result.output)
        pairs.assert_called_once_with(client=CLIENT_A, provider=ActorId(1234), deal_id=None)

    def test_prepare_pending_wallet_failure_prints_summary_before_any_deal_send(self):
        import importlib

        client_migration = importlib.import_module("cli.commands.client.migration")
        pairs = [
            SimpleNamespace(target=SimpleNamespace(deal=SimpleNamespace(
                deal_id=deal_id, state=PoRepMarketDealState.ACCEPTED
            ))) for deal_id in (10, 11)
        ]
        service = SimpleNamespace(adoption_plan=MagicMock(return_value=SimpleNamespace(extensions=())))
        signer = SimpleNamespace(address=MagicMock(return_value=CLIENT_A))
        web3 = SimpleNamespace(ensure_no_pending_transactions=MagicMock(
            side_effect=RuntimeError("pending wallet transaction")
        ))
        with patch.object(client_migration, "migration_pairs", return_value=(service, pairs)), \
                patch.object(client_migration, "_validate_prepared_rail", return_value=None), \
                patch.object(client_migration, "_funding_by_token", return_value={}), \
                patch.object(client_migration, "client_address", return_value=CLIENT_A), \
                patch.object(client_migration, "client_signer", return_value=signer), \
                patch.object(client_migration, "Web3Service", return_value=web3), \
                patch.object(client_migration.utils, "confirm", return_value=True), \
                patch.object(client_migration, "ValidatorFactory") as factory:
            result = CliRunner().invoke(client_migration.prepare_migration)

        self.assertNotEqual(result.exit_code, 0)
        self.assertIn("Preparation summary: planned=2", result.output)
        factory.assert_not_called()

    def test_prepare_refreshed_invalid_rail_waits_without_approval_or_send(self):
        from cli.commands.client import migration as client_migration

        target = SimpleNamespace(deal=SimpleNamespace(
            deal_id=10,
            state=PoRepMarketDealState.ACCEPTED,
            rail_id=1,
        ))
        pair = MigrationPair(MigrationMarker(314, MARKET, 1), SimpleNamespace(), target)
        plan = SimpleNamespace(extensions=(), complete=True)
        service = SimpleNamespace(adoption_plan=MagicMock(return_value=plan))
        signer = SimpleNamespace(address=MagicMock(return_value=CLIENT_A))
        approval = MagicMock()
        adapter = MagicMock()
        factory = MagicMock()
        with patch.object(client_migration, "migration_pairs", return_value=(service, [pair])), \
                patch.object(
                    client_migration,
                    "_validate_prepared_rail",
                    side_effect=[SimpleNamespace(), MigrationError("refreshed rail identity changed")],
                ), \
                patch.object(client_migration, "_funding_by_token", return_value={}), \
                patch.object(client_migration, "client_address", return_value=CLIENT_A), \
                patch.object(client_migration, "client_signer", return_value=signer), \
                patch.object(client_migration, "Web3Service", return_value=SimpleNamespace(
                    ensure_no_pending_transactions=MagicMock()
                )), \
                patch.object(client_migration, "PoRepMarketViewHelper", return_value=SimpleNamespace(
                    get_deal_view=MagicMock(return_value=target)
                )), \
                patch.object(
                    client_migration.client_utils,
                    "approve_filecoinpay_operator",
                    approval,
                ), \
                patch.object(client_migration, "DataCapEvidenceAdapter", adapter), \
                patch.object(client_migration, "ValidatorFactory", factory), \
                patch.object(client_migration.utils, "confirm", return_value=True):
            result = CliRunner().invoke(client_migration.prepare_migration)

        self.assertEqual(result.exit_code, 0, result.output)
        self.assertIn("refreshed preflight failed: refreshed rail identity changed", result.output)
        self.assertIn("completed=0, skipped=0, waiting=1", result.output)
        approval.assert_not_called()
        adapter.assert_not_called()
        factory.assert_not_called()

    def test_prepare_mixed_batch_continues_after_deterministic_claim_preflight_failure(self):
        from cli.commands.client import migration as client_migration

        def target(deal_id):
            return SimpleNamespace(
                deal=SimpleNamespace(
                    deal_id=deal_id,
                    state=PoRepMarketDealState.ACCEPTED,
                    rail_id=1,
                    validator_address=CLIENT_B,
                    evidence_adapter_address=MARKET,
                ),
                payment=SimpleNamespace(payment_token=TOKEN),
            )

        marker = MigrationMarker(314, MARKET, 1)
        pairs = [MigrationPair(marker, SimpleNamespace(), target(deal_id)) for deal_id in (10, 11)]
        extension = SimpleNamespace(claim_id=7)
        failing_plan = SimpleNamespace(
            extensions=(extension,),
            complete=False,
            batches=MagicMock(return_value=[SimpleNamespace(extensions=(extension,))]),
        )
        successful_plan = SimpleNamespace(extensions=(), complete=True)
        service = SimpleNamespace(
            adoption_plan=MagicMock(side_effect=[
                failing_plan,
                successful_plan,
                failing_plan,
                successful_plan,
            ]),
            validate_outgoing_batch=MagicMock(side_effect=lambda _pair, _plan, batch: batch),
            validate_batch_receipt=MagicMock(),
            transfer_params=MagicMock(return_value=SimpleNamespace(to=(b"\x00\x06",), amount=(b"x", False), operator_data=b"x")),
        )
        operation = SimpleNamespace(
            call=MagicMock(side_effect=RuntimeError("deterministic revert")),
            estimate_gas=MagicMock(),
        )
        adapter = SimpleNamespace(
            contract=SimpleNamespace(functions=SimpleNamespace(
                submitDataCapBatch=MagicMock(return_value=operation)
            )),
            submit_datacap_batch=MagicMock(),
        )
        helper = MagicMock()
        helper.get_deal_view.side_effect = lambda deal_id: target(deal_id)
        signer = SimpleNamespace(address=MagicMock(return_value=CLIENT_A))
        with patch.object(client_migration, "migration_pairs", return_value=(service, pairs)), \
                patch.object(client_migration, "_validate_prepared_rail", return_value=SimpleNamespace()), \
                patch.object(client_migration, "_funding_by_token", return_value={}), \
                patch.object(client_migration, "client_address", return_value=CLIENT_A), \
                patch.object(client_migration, "client_signer", return_value=signer), \
                patch.object(client_migration, "Web3Service", return_value=SimpleNamespace(
                    ensure_no_pending_transactions=MagicMock()
                )), \
                patch.object(client_migration, "PoRepMarketViewHelper", return_value=helper), \
                patch.object(client_migration, "DataCapEvidenceAdapter", return_value=adapter), \
                patch.object(client_migration.client_utils, "approve_filecoinpay_operator", return_value=None), \
                patch.object(client_migration.utils, "confirm", return_value=True):
            result = CliRunner().invoke(client_migration.prepare_migration)

        self.assertEqual(result.exit_code, 0, result.output)
        self.assertIn("claim batch preflight failed: deterministic revert", result.output)
        self.assertIn("completed=0, skipped=1, waiting=1", result.output)
        adapter.submit_datacap_batch.assert_not_called()

    def test_prepare_large_deal_uses_three_full_scans_and_bounded_batch_checks(self):
        from cli.commands.client import migration as client_migration

        claims = [self.claim(claim_id=claim_id, size=1) for claim_id in range(1, 1_394)]
        initial = build_adoption_plan(claims, [], [], target_epoch=500_000, current_epoch=1_000)
        complete = initial.__class__(
            source_claims=initial.source_claims,
            target_ids=frozenset(claim.claim_id for claim in claims),
            extensions=(),
            operator_data=cbor2.dumps([[], []], canonical=True),
            datacap_amount=0,
            sector_target_epoch=initial.sector_target_epoch,
        )
        target = SimpleNamespace(
            deal=SimpleNamespace(
                deal_id=10,
                state=PoRepMarketDealState.ACCEPTED,
                rail_id=1,
                validator_address=CLIENT_B,
                evidence_adapter_address=MARKET,
            ),
            payment=SimpleNamespace(payment_token=TOKEN),
        )
        pair = MigrationPair(MigrationMarker(314, MARKET, 1), SimpleNamespace(), target)
        service = SimpleNamespace(
            adoption_plan=MagicMock(side_effect=[initial, initial, complete]),
            validate_outgoing_batch=MagicMock(side_effect=lambda _pair, _plan, batch: batch),
            validate_batch_receipt=MagicMock(),
            transfer_params=MagicMock(return_value=SimpleNamespace(
                to=(b"\x00\x06",), amount=(b"x", False), operator_data=b"x"
            )),
        )
        operation = SimpleNamespace(call=MagicMock(), estimate_gas=MagicMock())
        adapter = SimpleNamespace(
            contract=SimpleNamespace(functions=SimpleNamespace(
                submitDataCapBatch=MagicMock(return_value=operation)
            )),
            submit_datacap_batch=MagicMock(return_value="0xabc"),
        )
        signer = SimpleNamespace(address=MagicMock(return_value=CLIENT_A))
        with patch.object(client_migration, "migration_pairs", return_value=(service, [pair])), \
                patch.object(client_migration, "_validate_prepared_rail", return_value=SimpleNamespace()), \
                patch.object(client_migration, "_funding_by_token", return_value={}), \
                patch.object(client_migration, "client_address", return_value=CLIENT_A), \
                patch.object(client_migration, "client_signer", return_value=signer), \
                patch.object(client_migration, "Web3Service", return_value=SimpleNamespace(
                    ensure_no_pending_transactions=MagicMock()
                )), \
                patch.object(client_migration, "PoRepMarketViewHelper", return_value=SimpleNamespace(
                    get_deal_view=MagicMock(return_value=target)
                )), \
                patch.object(client_migration, "DataCapEvidenceAdapter", return_value=adapter), \
                patch.object(client_migration.client_utils, "approve_filecoinpay_operator", return_value=None), \
                patch.object(client_migration.utils, "confirm", return_value=True):
            result = CliRunner().invoke(client_migration.prepare_migration)

        self.assertEqual(result.exit_code, 0, result.output)
        self.assertEqual(service.adoption_plan.call_count, 3)
        self.assertEqual(service.validate_outgoing_batch.call_count, 14)
        self.assertEqual(service.validate_batch_receipt.call_count, 14)
        self.assertEqual(adapter.submit_datacap_batch.call_count, 14)

    def test_finish_mixed_batch_continues_but_uncertain_send_stops_with_summary(self):
        from cli.commands.client import migration as client_migration

        pairs = [SimpleNamespace(target=SimpleNamespace(deal=SimpleNamespace(
            deal_id=deal_id, state=PoRepMarketDealState.ACCEPTED
        ))) for deal_id in (10, 11)]
        first_adapter = SimpleNamespace(
            is_datacap_posting_finished=MagicMock(return_value=False),
            finish_datacap_posting=MagicMock(return_value=""),
        )
        second_adapter = SimpleNamespace(
            is_datacap_posting_finished=MagicMock(side_effect=[False, False, True]),
            finish_datacap_posting=MagicMock(return_value="0xabc"),
        )
        preflights = [
            (pairs[0], first_adapter),
            (pairs[1], second_adapter),
            (pairs[0], first_adapter),
        ]
        signer = SimpleNamespace(address=MagicMock(return_value=CLIENT_A))
        with patch.object(client_migration, "migration_pairs", return_value=(MagicMock(), pairs)), \
                patch.object(client_migration, "_finish_preflight", side_effect=preflights), \
                patch.object(client_migration, "client_address", return_value=CLIENT_A), \
                patch.object(client_migration, "client_signer", return_value=signer), \
                patch.object(client_migration, "Web3Service", return_value=SimpleNamespace(
                    ensure_no_pending_transactions=MagicMock()
                )), \
                patch.object(client_migration.utils, "confirm", return_value=True):
            result = CliRunner().invoke(client_migration.finish_migration)

        self.assertNotEqual(result.exit_code, 0)
        self.assertIn("returned no authoritative transaction hash", result.output)
        self.assertIn("Finish summary: planned=2, completed=0", result.output)
        second_adapter.finish_datacap_posting.assert_not_called()

    def test_finish_mixed_batch_continues_after_refreshed_preflight_failure(self):
        from cli.commands.client import migration as client_migration

        pairs = [SimpleNamespace(target=SimpleNamespace(deal=SimpleNamespace(
            deal_id=deal_id, state=PoRepMarketDealState.ACCEPTED
        ))) for deal_id in (10, 11)]
        first_adapter = SimpleNamespace(is_datacap_posting_finished=MagicMock(return_value=False))
        second_adapter = SimpleNamespace(
            is_datacap_posting_finished=MagicMock(side_effect=[False, False, True]),
            finish_datacap_posting=MagicMock(return_value="0xabc"),
        )
        preflights = [
            (pairs[0], first_adapter),
            (pairs[1], second_adapter),
            MigrationError("state changed before signing"),
            (pairs[1], second_adapter),
        ]
        signer = SimpleNamespace(address=MagicMock(return_value=CLIENT_A))
        with patch.object(client_migration, "migration_pairs", return_value=(MagicMock(), pairs)), \
                patch.object(client_migration, "_finish_preflight", side_effect=preflights), \
                patch.object(client_migration, "client_address", return_value=CLIENT_A), \
                patch.object(client_migration, "client_signer", return_value=signer), \
                patch.object(client_migration, "Web3Service", return_value=SimpleNamespace(
                    ensure_no_pending_transactions=MagicMock()
                )), \
                patch.object(client_migration.utils, "confirm", return_value=True):
            result = CliRunner().invoke(client_migration.finish_migration)

        self.assertEqual(result.exit_code, 0, result.output)
        self.assertIn("refreshed preflight failed: state changed before signing", result.output)
        self.assertIn("completed=1, skipped=0, waiting=1", result.output)
        second_adapter.finish_datacap_posting.assert_called_once()

    def test_cross_adapter_collision_is_checked_across_rotated_datacap_adapters(self):
        from cli.services import migration as migration_service_module

        adapter_a_address = EthAddress("0x5555555555555555555555555555555555555555")
        adapter_b_address = EthAddress("0x6666666666666666666666666666666666666666")
        views = [
            SimpleNamespace(deal=SimpleNamespace(deal_id=10, evidence_adapter_address=adapter_a_address)),
            SimpleNamespace(deal=SimpleNamespace(deal_id=11, evidence_adapter_address=adapter_b_address)),
        ]

        def adapter(ids):
            return SimpleNamespace(
                evidence_type=MagicMock(return_value=SimpleNamespace(value=10)),
                get_porep_market_contract_address=MagicMock(return_value=MARKET),
                get_allocation_ids_per_deal=MagicMock(return_value=([], 0)),
                get_claim_ids=MagicMock(return_value=(ids, len(ids))),
            )

        adapters = {adapter_a_address: adapter([10]), adapter_b_address: adapter([10])}
        service = object.__new__(MigrationService)
        service.view_helper = SimpleNamespace(
            get_deal_views=MagicMock(return_value=views),
            porep_market_contract=MagicMock(return_value=MARKET),
        )
        with patch.object(
                migration_service_module,
                "DataCapEvidenceAdapter",
                side_effect=lambda address: adapters[address]), \
                self.assertRaisesRegex(MigrationError, "assigned to other V2 deals"):
            service._reject_cross_deal_ids({10}, 10)

    def test_cross_adapter_classification_and_binding_reads_fail_closed(self):
        from cli.services import migration as migration_service_module

        address = EthAddress("0x5555555555555555555555555555555555555555")
        service = object.__new__(MigrationService)
        service.view_helper = SimpleNamespace(
            get_deal_views=MagicMock(return_value=[SimpleNamespace(
                deal=SimpleNamespace(deal_id=10, evidence_adapter_address=address)
            )]),
            porep_market_contract=MagicMock(return_value=MARKET),
        )
        unreadable_type = SimpleNamespace(
            evidence_type=MagicMock(side_effect=RuntimeError("type RPC unavailable"))
        )
        with patch.object(
                migration_service_module, "DataCapEvidenceAdapter", return_value=unreadable_type), \
                self.assertRaisesRegex(MigrationError, "Cannot classify V2 evidence adapter"):
            service._reject_cross_deal_ids({10}, 10)

        unreadable_binding = SimpleNamespace(
            evidence_type=MagicMock(return_value=SimpleNamespace(value=10)),
            get_porep_market_contract_address=MagicMock(
                side_effect=RuntimeError("binding RPC unavailable")
            ),
        )
        with patch.object(
                migration_service_module, "DataCapEvidenceAdapter", return_value=unreadable_binding), \
                self.assertRaisesRegex(MigrationError, "Cannot verify DataCap adapter"):
            service._reject_cross_deal_ids({10}, 10)

    def test_prepare_print_only_never_loads_signer(self):
        from cli.commands.client import migration as client_migration

        with patch.object(client_migration, "client_address", return_value=CLIENT_A), \
                patch.object(client_migration, "migration_pairs", return_value=(MagicMock(), [])), \
                patch.object(client_migration, "_funding_by_token", return_value={}), \
                patch.object(client_migration, "client_signer") as signer:
            result = CliRunner().invoke(client_migration.prepare_migration, ["--print-only"])

        self.assertEqual(result.exit_code, 0, result.output)
        signer.assert_not_called()

if __name__ == "__main__":
    unittest.main()
