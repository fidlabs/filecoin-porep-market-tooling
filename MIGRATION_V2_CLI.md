# CLI → PoRep Market V2 — lista zmian

Źródło: `fidlabs/porep-market`. Stan na 2026-07-02.

Każdy kontrakt: najpierw zmiany już w `main`, potem podsekcje **PR-y w toku** (nazwa + link + różnica vs `main`). Funkcje podane z argumentami i zwrotką. Pozycje z PRek mogą się jeszcze zmienić przed mergem.

Otwarte PRki:
- [#99 [ClientSC] Add DC allocation status](https://github.com/fidlabs/porep-market/pull/99) — MERGEABLE; DataCapEvidenceAdapter.
- [#98 Move validateSettlement to PoRepMarket](https://github.com/fidlabs/porep-market/pull/98) — MERGEABLE; PoRepMarket + Validator.
- [#95 Add DealView read APIs](https://github.com/fidlabs/porep-market/pull/95) — MERGEABLE; PoRepMarket.
- [#94 [ClientSC] Implement activateEvidence](https://github.com/fidlabs/porep-market/pull/94) — **CONFLICTING**; DataCapEvidenceAdapter.
- [#90 Implement SPRegistry V2 offer matching](https://github.com/fidlabs/porep-market/pull/90) — **CONFLICTING**; SPRegistry, PoRepMarket, Validator, DataCapEvidenceAdapter.
- [#82 [Validator] Remove the Client SC from the Validator](https://github.com/fidlabs/porep-market/pull/82) — **CONFLICTING**; Validator.

Domergowane od poprzedniej wersji dokumentu: #92 (`getSizeOfAllocations`→`getAllocatedBytes`), #87 (`submitEvidenceBatch`), #93 (Validator `NAME`/`DESCRIPTION`).

---

## Wspólne / ABI

- Wygenerować od nowa wszystkie ABI w `cli/services/contracts/abi/`.
- `Client.json` → usunąć, dodać `DataCapEvidenceAdapter.json` (+ `IStorageEvidenceAdapter`).
- Deal rozbity na osobne gettery (wszystkie `(dealId)`), zamiast jednego `getDealProposal`:
  - `getDeal(dealId) → Deal{dealId, client, provider FilActorId, offerId, state uint8, evidenceAdapter address, validator address, railId}`
  - `getDealData(dealId) → {manifestHash bytes32, manifestLocation string}`
  - `getDealTerms(dealId) → {requestedSizeBytes, durationEpochs uint64}`
  - `getDealTiming(dealId) → {proposedAtEpoch, expiresAtEpoch}`
  - `getDealService(dealId) → {serviceStartEpoch, serviceEndEpoch}`
  - `getDealCapacity(dealId) → {reservedBytes, committedBytes}`
  - `getDealPayment(dealId) → {paymentToken, payee, pricePer32GiBPerMonth, billed32GiBUnits, railMaxRatePerEpoch}`
  - `getDealSLIs(dealId) → SLIThresholds`
  - **Uwaga:** [#95] dodaje `getDealView` — jedno wywołanie zamiast powyższych ośmiu (patrz PoRepMarket).
- `SLIThresholds` (dwa typy):
  - `SharedTypes.SLIThresholds{retrievabilityBps uint16, bandwidthBytesPerSecond uint64, latencyMs uint16, indexingPct uint8}` — SPRegistry/PoRepMarket.
  - `SLITypes.SLIThresholds{retrievabilityBps uint16, bandwidthMbps uint16, latencyMs uint16, indexingPct uint8}`.
  - Pole CLI `bandwidth_mbps` rozjeżdża się z `SharedTypes` (bytes/s) — ujednolicić.

---

## PoRepMarket (`porep_market.py`)

### Zmiany w `main`
- `PoRepMarketDealState`: nowe kody (gapped uint8) — `NONE=0, PROPOSED=10, ACCEPTED=20, ACTIVE=30, FINALIZED=40, REJECTED=50, EXPIRED=60, TERMINATED=70`. Doszły `ACTIVE`/`EXPIRED`, `COMPLETED`→`FINALIZED`. Poprawić enum + porównania w komendach.
- `proposeDeal(request)` — `request = DealRequest{manifestHash bytes32, requestedSizeBytes uint256, maxPricePer32GiBPerMonth uint256, manifestLocation string, paymentToken address, durationDays uint32, requiredSLIs SLIThresholds}`. Doszły wymagane `manifestHash` i `paymentToken`; brak osobnego structu `terms`.
- `getDealProposal(dealId)` — **usunięte** → gettery `getDeal*` (sekcja Wspólne).
- `getCompletedDeals()` — **usunięte** → `getDeals()` / `getDealsForOrganizationByState(organization, state)`.
- `completeDeal(dealId)` → `finalizeDeal(dealId)`.
- `terminateDeal(dealId, terminator, endEpoch)` → `terminateDeal(dealId, endEpoch)` (bez `terminator`).
- `getDealsForOrganizationByState(organization address, state uint8) → Deal[]` — nowy `Deal[]`, `state` = nowe kody uint8.
- `getClientSmartContract()` — **usunięte** → `getGlobalEvidenceAdapter() → address` / `getDealEvidenceAdapter(dealId) → address`.
- `setDealCompletionPadding`/`getDealCompletionPadding` → `setDealActivationPadding(padding uint256)` / `getDealActivationPadding() → uint256`.
- Bez zmian: `acceptDeal(dealId)`, `rejectDeal(dealId)`, `rejectAcceptedDeal(dealId)`, `updateRailId(dealId, railId)`, `getDeals() → Deal[]`, `getSPRegistryContract() → address`, `getValidatorFactoryContract() → address`, stałe `EPOCHS_IN_MONTH()`/`SECTOR_SIZE()`/`MAX_DEAL_DURATION_DAYS()`.
- Nowe do dodania:
  - `activatePayment(dealId)` (rola `POREP_SERVICE_ROLE`)
  - `submitEvidenceBatch(dealId, evidenceData bytes) → ActivationDecision{coveredBytes, reasonCode uint16, result uint8}`
  - `activateEvidence(dealId, evidenceData bytes) → ActivationDecision`
  - `refreshEvidenceStatus(dealId, evidenceData bytes) → EvidenceStatus{activeCoveredBytes, lastEvidenceRefreshEpoch, reasonCode uint16, result uint8}`
  - `currentEvidenceStatus(dealId) → EvidenceStatus`
  - `updateValidator(dealId)`
  - `rejectExpiredDeal(dealId)`
  - `getDealExpiration() → uint256` / `setNewDealExpiration(newDealExpiration uint256)`
  - `getManifestLocation(dealId) → string` / `updateManifestLocation(dealId, newManifestLocation string)`
  - `MIN_DEAL_DURATION_DAYS() → uint32` (=180)

### PR-y w toku
- **[#95 DealView read APIs](https://github.com/fidlabs/porep-market/pull/95)** (MERGEABLE) — różnica vs `main`: zagregowane odczyty, upraszcza serwis (zamiast 8 getterów):
  - `getDealView(dealId) → DealView{deal Deal, data DealData, requiredSLIs SLIThresholds, terms DealTerms, timing DealTiming, service DealService, capacity DealCapacity, payment DealPayment, providerOrganization address, evidenceStatus EvidenceStatus}`
  - `getDealViews(offset uint256, limit uint256) → DealView[]`
  - `getDealCount() → uint256`
  - `getDealIds(offset uint256, limit uint256) → uint256[]`
  - `getDealIdsByState(state uint8, offset uint256, limit uint256) → uint256[]`
  - **Wpływ na CLI:** `PoRepMarketDealProposal` można odtworzyć z jednego `getDealView` (+ `providerOrganization` gratis); paginacja zamiast pobierania wszystkiego.
- **[#98 Move validateSettlement to PoRepMarket](https://github.com/fidlabs/porep-market/pull/98)** (MERGEABLE) — różnica vs `main`: dochodzi `validateDealSettlement(dealId, proposedAmount, fromEpoch, toEpoch)` na PoRepMarket; logika settlement przenoszona z Validatora. Głównie wewn. — CLI raczej nie woła, ale zaktualizować ABI.
- **[#90 SPRegistry V2 offer matching](https://github.com/fidlabs/porep-market/pull/90)** (CONFLICTING) — różnica vs `main`: `proposeDeal` przestaje brać `paymentToken` z requestu — market rezerwuje ofertę w SPRegistry i bierze `offerId`+`paymentToken` z `ProviderDealSelection`; deal niesie realny `offerId` (w `main` zawsze 0).

## Client → DataCapEvidenceAdapter (`client_contract.py`)

### Zmiany w `main`
- Cały kontrakt → `DataCapEvidenceAdapter`. Adres: `getGlobalEvidenceAdapter()` / `getDealEvidenceAdapter(dealId)` (nie `getClientSmartContract`).
- `transfer(params, dealId)` → `submitDataCapBatch(params TransferParams, dealId)` (`TransferParams{to FilAddress, amount BigInt, operatorData bytes}`).
- `getClientAllocationIdsPerDeal(dealId)` → `getAllocationIdsPerDeal(dealId, offset uint256, limit uint256) → (ids FilActorId[], sumOfAllocations uint256)`.
- `getSizeOfAllocations(dealId)` → **`getAllocatedBytes(dealId) → uint256`** (rename, #92 już w `main`) — poprawić `get_size_of_allocations` w serwisie + `client/make_allocations.py` i `client/_utils.py`.
- Bez zmian: `rescueDealAllocations(dealId, params TransferParams)`.
- Nowe:
  - `getClaimIds(dealId, offset uint256, limit uint256) → (ids FilActorId[], sumOfClaims uint256)`
  - `isOperational() → bool`
  - `evidenceType() → uint8`
  - `isDataSizeMatching(dealId) → bool` (tylko validator deala)
  - `terminatedClaims(claimId uint64) → bool`
  - `claimsTerminatedEarly(claims uint64[])` (rola `TERMINATION_ORACLE`)
  - `getPoRepMarketAddress() → address`
  - `disableAdapter()` (admin)
- N/A dla CLI (kompletność): `handle_filecoin_method(method uint64, inputCodec uint64, params bytes) → (exitCode uint32, codec uint64, data bytes)` — receiver hook FRC-46; `initialize(...)` — deploy.
- Role (przez `AccessControlUpgradeable.grant_role`): `RESCUE_ROLE`, `TERMINATION_ORACLE`, `UPGRADER_ROLE`.

### PR-y w toku
- **[#99 Add DC allocation status](https://github.com/fidlabs/porep-market/pull/99)** (MERGEABLE) — różnica vs `main`: nowy krok w flow klienta — po wrzuceniu batchy DataCap trzeba domknąć posting:
  - `finishDataCapPosting(dealId)` (klient; wymaga deal w ACCEPTED + adapter operational; blokuje kolejne `submitDataCapBatch`)
  - `isDataCapPostingFinished(dealId) → bool`
  - `getDealAllocationStatus(dealId) → uint8 status`
  - **Wpływ na CLI:** `client/make_allocations.py` musi po ostatnim batchu wołać `finishDataCapPosting`; `submitEvidenceBatch` dopiero po zakończonym postingu.
- **[#94 Implement activateEvidence](https://github.com/fidlabs/porep-market/pull/94)** (CONFLICTING) — różnica vs `main`: realna implementacja `activateEvidence(context ActivationContext, evidenceData bytes) → ActivationDecision` na adapterze (na `main` może być jeszcze stub). CLI woła wariant marketowy `(dealId, evidenceData)`.
- **[#90 SPRegistry V2 offer matching](https://github.com/fidlabs/porep-market/pull/90)** (CONFLICTING) — różnica vs `main`: dopięcie sygnatur evidence + kosmetyka, bez wpływu na zewn. API CLI.

## SPRegistry (`sp_registry.py`)

### Zmiany w `main`
- `capabilities` używa `SharedTypes.SLIThresholds` (`bandwidthBytesPerSecond` uint64) — poprawić `SPRegistrySLIThresholds.bandwidth_mbps`.
- `ProviderInfo{organization, payee, paused, blocked, capabilities SLIThresholds, availableBytes, committedBytes, pendingBytes, pricePerSectorPerMonth, minDealDurationDays uint32, maxDealDurationDays uint32}` — kolejność pól bez zmian.
- Bez zmian: `registerProviderFor(provider FilActorId, organization address, capabilities SLIThresholds, availableBytes, pricePerSectorPerMonth, payee address, minDealDurationDays, maxDealDurationDays)`, `setPrice(provider, pricePerSectorPerMonth)`, `setCapabilities(provider, capabilities)`, `setDealDurationLimits(provider, minDealDurationDays uint32, maxDealDurationDays uint32)`, `getProviderInfo(provider) → ProviderInfo`, `getProviders() → FilActorId[]`, `getProvidersByOrganization(organization) → FilActorId[]`, `block/unblock/pause/unpauseProvider(provider)`, `updateAvailableSpace(provider, availableBytes)`, `isAuthorizedForProvider(caller address, provider) → bool`.
- Nowe w `main` (opcjonalne): `getCommittedProviders() → FilActorId[]`, `getPayee(provider) → address`, `setToleranceBps(bps uint256)`/`getToleranceBps() → uint256`, `commitCapacity(provider, estimatedSizeBytes, actualSizeBytes)`, `releaseCapacity(provider, sizeBytes)`/`releasePendingCapacity(provider, sizeBytes)`, `getProviderForDeal(requirements SLIThresholds, terms SLITypes.DealTerms) → (provider FilActorId, autoApprove bool, organization address)`.

### PR-y w toku
- **[#90 SPRegistry V2 offer matching](https://github.com/fidlabs/porep-market/pull/90)** (CONFLICTING) — różnica vs `main` (DUŻA przebudowa na model ofertowy):
  - Provider odchudzony: `registerProviderFor(provider FilActorId, organization address, availableBytes uint256, payee address)` — bez `capabilities`, `price`, `min/maxDealDuration`.
  - Usunięte z providera: `setPrice`, `setCapabilities`, `setDealDurationLimits` (cena/SLI/duration/rozmiar → do **Offer**).
  - `ProviderInfo` rozbity — pojemność przez `getProviderCapacity(provider) → ProviderCapacityInfo{availableBytes, committedBytes, pendingBytes}`. Przepisać `SPRegistryProviderInfo.from_web3`.
  - Oferty:
    - `createOffer(name string, terms OfferTerms, slis SLIThresholds, payments OfferPaymentInput[]) → offerId uint256` (`OfferTerms{minSizeBytes, maxSizeBytes, minDurationEpochs uint64, maxDurationEpochs uint64}` — duration w epokach)
    - `setOfferActive(offerId, active bool)`, `setOfferName(offerId, name string)`, `setOfferPayment(offerId, token address, active bool, pricePer32GiBPerMonth uint256)`
    - `getOffer(offerId) → OfferInfo{provider FilActorId, active bool}`, `getOfferTerms(offerId) → OfferTerms`, `getOfferSLIs(offerId) → SLIThresholds`, `getOfferPayment(offerId, token address) → OfferPayment{active bool, pricePer32GiBPerMonth uint256}`
    - `getOffersByProvider(provider) → uint256[]`, `getActiveOffersByProvider(provider) → uint256[]`, `getActiveOffers() → uint256[]`
  - Multi-token: `setPaymentToken(token address, allowed bool, minPricePer32GiBPerMonth uint256)`, `getPaymentTokens() → address[]`, `getPaymentTokenConfig(token address) → TokenConfig{allowed bool, minPricePer32GiBPerMonth uint256}`.
  - Matching: `previewProviderForDeal(request DealRequest)`, `reserveProviderForDeal(request DealRequest)`, `previewOfferForDeal(offerId, request DealRequest)`, `reserveOfferForDeal(offerId, request DealRequest) → (selection ProviderDealSelection, reason uint16)`.
  - `releaseCapacity`/`releasePendingCapacity` — doszedł arg `manifestHash bytes32`. `isManifestAssignedToProvider(manifestHash bytes32, provider) → bool`.
  - `setMatchPriceBandBps(bps uint256)`/`getMatchPriceBandBps() → uint256`.
  - **Wpływ na CLI:** `register_provider_for`, `set_price`, `set_capabilities`, `set_deal_duration_limits` oraz `admin register-db-sps` → przepisać na onboarding providera + osobne `createOffer`.

## Validator (`filecoinpay_validator.py`)

### Zmiany w `main`
- `createRail(token IERC20)` — bez zmian.
- `terminateRail()` — **brak** w V2. Wczesna terminacja: `earlyRailTermination()` (rola `POREP_SERVICE_ROLE`); zakończenie deala: `finalizeDeal()`.
- Status raila wg `RailStatus` (`NONE=0, PREPARED=10, ACTIVE=20, TERMINATED=100`).
- Nowe: `getRailStatus() → uint8`, `getMinEpochsBetweenSettlements() → uint256`, `setMinEpochsBetweenSettlements(minEpochs uint256)`, `modifyRailPayment(newRate uint256)`, `updateLockupPeriod(newLockupPeriod uint256)` (admin).
- Nowe stałe (#93 w `main`): `NAME() → "FCSS"`, `DESCRIPTION() → "Filecoin Cold Storage Service"`.

### PR-y w toku
- **[#98 Move validateSettlement to PoRepMarket](https://github.com/fidlabs/porep-market/pull/98)** (MERGEABLE) — różnica vs `main`: `validatePayment(railId, proposedAmount, fromEpoch, toEpoch, rate)` przestaje używać `rate` (deleguje do `PoRepMarket.validateDealSettlement`). CLI raczej nie woła — zaktualizować ABI.
- **[#90 SPRegistry V2 offer matching](https://github.com/fidlabs/porep-market/pull/90)** (CONFLICTING) — różnica vs `main`: **`createRail(token IERC20)` → `createRail()`** (bez tokena; token z payment ofery). Dotyka `FileCoinPayValidator.create_rail(token_address)` i `client/init_accepted_deals.py`.
- **[#82 Validator bez ClientSC](https://github.com/fidlabs/porep-market/pull/82)** (CONFLICTING) — różnica vs `main`: Validator woła PoRepMarket (`IPoRepMarketSettlement`) zamiast ClientSC; usunięte ~9 funkcji z `IValidator`, odchudzony `Validator.sol`. Sygnatury niestabilne — analiza po rebase+merge. Uwaga: częściowo pokrywa się z #98.

## ValidatorFactory (`validator_factory.py`)

### Zmiany w `main`
- `create(dealId)`, `getInstance(dealId) → address` — bez zmian.
- Nowe (opcjonalnie): `isValidatorContract(contractAddress address) → bool`, `getBeacon() → address`.

### PR-y w toku
- Brak otwartych PRek dotykających tego kontraktu.

## SLIScorer / SLIOracle

### Zmiany w `main`
- Brak serwisów w CLI (tylko ABI). Jeśli dojdą:
  - SLIScorer: `calculateScore(dealId, required SLIThresholds) → score uint256` (0–100).
  - SLIOracle: `setSLI(dealId, slis SLIThresholds)`, `getAttestation(dealId) → Attestation{lastUpdate, slis SLIThresholds}`.
  - Teraz per-deal, nie per-provider.

### PR-y w toku
- Brak otwartych PRek dotykających tych kontraktów.

---

## Komendy CLI do poprawki (konsekwencje powyższego)

- `client/complete_deal.py` → `finalize_deal` (`finalizeDeal(dealId)`).
- `client/make_allocations.py` → `submitDataCapBatch(params, dealId)` zamiast `transfer`; `getAllocatedBytes`; [#99] po ostatnim batchu `finishDataCapPosting(dealId)`.
- `client/propose_deal_from_manifest.py` → nowy `DealRequest` (manifestHash + paymentToken), `bandwidth_mbps`→bytes/s; [#90] token z ofery.
- `client/deposit_for_deals.py`, `client/init_accepted_deals.py`, `client/get_deals.py`, `client/reject_deal.py` → `get_deal_proposal`→gettery `getDeal*` (lub [#95] `getDealView`), nowe stany; [#90] `create_rail()` bez tokena.
- `client/_utils.py`, `admin/*` → `get_size_of_allocations`→`getAllocatedBytes`.
- `admin/get_deals.py`, `admin/terminate_deal.py` → nowe stany, `terminateDeal(dealId, endEpoch)` bez `terminator`, `terminate_rail`→`earlyRailTermination()`/`finalizeDeal()`; [#95] paginacja `getDealIds*`/`getDealViews`.
- `admin/set_completion_padding.py` → `setDealActivationPadding(padding)`.
- `admin/register-db-sps`, `admin/_utils.py` → `bandwidth_mbps`→bytes/s; [#90] rozdzielić rejestrację providera od `createOffer`.
