# Filecoin PoRep Market tooling CLI

[![cli/test.sh](https://github.com/fidlabs/filecoin-porep-market-tooling/actions/workflows/test-sh.yml/badge.svg)](https://github.com/fidlabs/filecoin-porep-market-tooling/actions/workflows/test-sh.yml)
[![Code linters](https://github.com/fidlabs/filecoin-porep-market-tooling/actions/workflows/lint.yml/badge.svg)](https://github.com/fidlabs/filecoin-porep-market-tooling/actions/workflows/lint.yml)
[![CodeQL](https://github.com/fidlabs/filecoin-porep-market-tooling/actions/workflows/github-code-scanning/codeql/badge.svg)](https://github.com/fidlabs/filecoin-porep-market-tooling/actions/workflows/github-code-scanning/codeql)
[![Copilot code review](https://github.com/fidlabs/filecoin-porep-market-tooling/actions/workflows/copilot-pull-request-reviewer/copilot-pull-request-reviewer/badge.svg)](https://github.com/fidlabs/filecoin-porep-market-tooling/actions/workflows/copilot-pull-request-reviewer/copilot-pull-request-reviewer)

Python3 CLI tool for interacting with [Filecoin PoRep Market](https://github.com/fidlabs/porep-market) smart contracts
using [Click](https://click.palletsprojects.com/en/stable/#), [Web3](https://web3py.readthedocs.io/en/stable/) and [psycopg](https://www.psycopg.org/docs/). \
Developed for admins, clients, and SPs to **manage their market interactions** from command line.

## Installation

**Use python >= 3.10**

```bash
python3 --version
git clone https://github.com/fidlabs/filecoin-porep-market-tooling && cd filecoin-porep-market-tooling
python3 -m pip install -r requirements.txt
cp .env.mainnet .env
```

## Running the CLI

Make sure you have the required environment variables set (see `.env`). \
Run the script: `python3 ./porep_tooling_cli.py` and follow help prompts.

## Important notes

- The app **does not store any state** locally - all state is retrieved from the blockchain by design.
- The app stores all blockchain transaction logs to `logs/`.
- Default behaviour is to wait for each transaction to succeed after sending it.
- The app operates on **FEVM smart contracts** (thus EVM 0x-addresses) but fully supports Filecoin f-addresses with proper conversion.
- There are multiple ways of providing the user's private key for blockchain transactions and the priority is as follows:
    1. `[ADMIN|CLIENT|SP]_PRIVATE_KEY` variable in the system environment variables or in the local `.env` file,
    2. `[ADMIN|CLIENT|SP]_LOTUS_WALLET` and `[ADMIN|CLIENT|SP]_LOTUS_TOKEN` variables when using Lotus wallet,
    3. if non of those are set, the app will prompt the user to input the private key for required operations in a secure manner.
- Read-only commands do not require private key / lotus wallet set, though some of them require user's address (`client --address` and `sp --organization`).
- Rule of thumb: the private key / lotus wallet you set is the one that signs and sends transactions, \
  so always use the one with correct permissions / approvals / rights for the transaction you want to send.
- Make sure the address for blockchain transactions you use has enough FIL for gas fees and is **initialized on the Filecoin network**.
- The app prints output of read-only commands in json format to be easily parsable by other tools.
- PoRep Market smart contracts supports only 32 GiB sectors.
- PoRep Market smart contracts assumes a month is always 30 days.

## Security considerations

- All blockchain transactions **require manual user confirmation** before sending. There is no option to override this. \
  If you decline the final confirmation, the command falls back to dry-run behavior without broadcasting the transaction.
- The app runs locally and does not transmit any data to external servers besides blockchain.
  All interactions are between the user's machine and the provided `RPC_URL` blockchain.
- The app does not log any sensitive information to the console or to the log files.
  All transaction logs are stored without any sensitive information.
- When using Lotus wallet for blockcain transaction signing, the **private key never leaves the Lotus wallet** and is not exposed to the app. \
  This is the recommended way of using the app.

## Typical SP workflow

1. **IMPORTANT**: interaction with the chain requires the private key for the message sender,
   so for security do not use your miner wallet for sending commands to the Peer-to-pool PoRep Market. \
   Instead you will need to create a miner controller wallet. If you already have one and want to reuse it, that’s fine. \
   However for most efficiency, we recommend you create a new wallet, and register it as a controller wallet for all the miners you will be using in P2PP. \
   The Market then uses controller status to verify that the command sender is authorised to send commands on behalf of your miner. \
   Follow the steps here:
   [https://lotus.filecoin.io/storage-providers/operate/addresses/#control-addresses](https://lotus.filecoin.io/storage-providers/operate/addresses/#control-addresses)
2. Export the private key of your newly created wallet. The value you store in `SP_PRIVATE_KEY`
   must be this exported private key in 32-byte hex format with a `0x` prefix — **not** the wallet
   address you pass to `lotus wallet export`:
   ```bash
   lotus wallet export <your-wallet-address-from-above> | xxd -r -p | jq -r '.PrivateKey' | base64 -d | xxd -p -c 32 | sed 's/^/0x/'
   ```

3. Clone this repo to download our CLI tool that will allow you to pull outstanding deals and onboard them:
   [https://github.com/fidlabs/filecoin-porep-market-tooling](https://github.com/fidlabs/filecoin-porep-market-tooling) \
   NOTE: this repo is still heavily developed and continuously improved so please make sure to do `git pull` from inside the folder with the code
   to ensure you have the latest version of the code.
   ```bash
   git clone https://github.com/fidlabs/filecoin-porep-market-tooling
   ```

4. Go into your local copy of the tool and install dependencies:
   ```bash
   python3 -m pip install -r requirements.txt
   ```

5. Then copy the config file:
   ```bash
   cp .env.mainnet .env
   ```

6. Edit the `.env` file:
    - put in the secret key of the controller wallet from step 2:
      ```bash
      # Private key used in SP operations
      # Set this if you want to interact with the system as a storage provider (organization)
      # This address needs to be the controlling address of provider_id you want to manage in the SPRegistry contract
      # See https://lotus.filecoin.io/storage-providers/operate/addresses/#control-addresses
      # 32-byte raw private key (hex, 0x-prefixed)
      
      SP_PRIVATE_KEY=<your miner controller wallet from step 2>
      ```

    - add your SP organization address:
      ```bash
      # Organization address to manage SPs from
      # You must have the SP_PRIVATE_KEY of an organization controlling address set to perform SP management operations
      
      SP_ORGANIZATION=<your organization address>
      ```

7. Ensure the file permissions on `.env` prevent the reading of this value by any user other than the one that runs the tooling.
   Assuming you are already logged in as the correct user, that would be:
   ```bash
   chmod 600 .env 
   ```

8. Optional but very useful for downloading the deals: install aria2:
    - on Mac `brew install aria2`
    - on Debian/Ubuntu: `sudo apt install aria2`
    - on Arch: `sudo pacman -S aria2`

9. Now you should be ready to run the tools.
    - to find deals allocated to you:
      ```bash
      python3 ./porep_tooling_cli.py sp get-deals
      ```

    - deals have 3 states that are interesting for SPs:
        * **PROPOSED:** The data is prepared and the client has submitted a deal proposal with all required metadata and SLA requirements.
        * **ACCEPTED:** The Storage Provider has accepted the deal. At this stage, the deal is waiting for the client to make the DataCap allocation.
        * **COMPLETED:** The client has made the DataCap allocation. The deal is now ready to be onboarded by the Storage Provider.
    - deals in `COMPLETED` state are ready for onboarding. The deal includes a `manifest_location` entry: this tells you where the Singularity manifest is. \
      All the `.car` files referenced are then available for pulling from the standard location of `<manifest_ip>:7777/piece/<CID>`.

    - deals in `PROPOSED` state need to be accepted. Assuming you are happy to accept the deal on the terms offered, run:
      ```bash   
        python3 ./porep_tooling_cli.py sp accept-deal <dealID you want to accept>
      ```
      then check back a few minutes later.

    - to download the deal that is allocated to you and in `COMPLETED` state run:
      ```bash
      python3 ./porep_tooling_cli.py sp get-deals completed
      python3 ./porep_tooling_cli.py sp onboard-data <DEAL ID> --output-dir <your dir>
      ``` 

    - get the allocation IDs:
      ```bash
      python3 ./porep_tooling_cli.py sp get-allocations <DEAL ID>
      ``` 

    - and claim deals:
      ```bash
      python3 ./porep_tooling_cli.py sp claim-allocations curio <DEAL ID> 
      ```

10. To get full list of commands for the tooling:
    ```bash
    python3 ./porep_tooling_cli.py sp --help
    ```

## Developing new CLI commands

- See files in `cli/commands` for examples of how to implement new commands.
- Keep the code clean and simple, follow the existing patterns and best practices.
- Use `Exception` (`ValueError`, `RuntimeError`, ...) for internal-like errors (things that "should not happen")
  and `click.ClickException` for user-like errors (things that happens "because of the user").
- Use `click.echo` for all user-facing output and `logger` for file logging.
- For read-only commands, print the output in json format for easy parsing by other tools.
