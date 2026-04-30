# Filecoin PoRep Market tooling CLI

[![cli/test.sh](https://github.com/pingwindyktator/filecoin-porep-market-tooling/actions/workflows/test-sh.yml/badge.svg)](https://github.com/pingwindyktator/filecoin-porep-market-tooling/actions/workflows/test-sh.yml)
[![Code linters](https://github.com/pingwindyktator/filecoin-porep-market-tooling/actions/workflows/lint.yml/badge.svg)](https://github.com/pingwindyktator/filecoin-porep-market-tooling/actions/workflows/lint.yml)
[![CodeQL](https://github.com/pingwindyktator/filecoin-porep-market-tooling/actions/workflows/github-code-scanning/codeql/badge.svg)](https://github.com/pingwindyktator/filecoin-porep-market-tooling/actions/workflows/github-code-scanning/codeql)
[![Copilot code review](https://github.com/pingwindyktator/filecoin-porep-market-tooling/actions/workflows/copilot-pull-request-reviewer/copilot-pull-request-reviewer/badge.svg)](https://github.com/pingwindyktator/filecoin-porep-market-tooling/actions/workflows/copilot-pull-request-reviewer/copilot-pull-request-reviewer)

Python3 CLI tool for interacting with [Filecoin PoRep Market](https://github.com/fidlabs/porep-market) smart contracts
using [Click](https://click.palletsprojects.com/en/stable/#), [Web3](https://web3py.readthedocs.io/en/stable/) and [psycopg](https://www.psycopg.org/docs/). \
Developed for admins, clients, and SPs to **manage their market interactions** from command line.

## Installation

**Use python >= 3.10**

```bash
python3 -m pip install -r requirements.txt
cp .env.mainnet .env
```

## Running the CLI

Make sure you have the required environment variables (see `.env`). \
Run the script: `python3 ./porep_tooling_cli.py` and follow help prompts.

## Important notes

- The app **does not store any state** locally - all state is retrieved from the blockchain by design.
- The app stores all blockchain transaction logs to `logs/`.
- Default behaviour is to wait for each transaction to succeed after sending it.
- The app operates on EVM 0x-addresses and **FEVM smart contract** and does not fully support Filecoin f-addresses.
- There are 3 ways of providing the user's private key for blockchain transactions and the priority is as follows:
    1. `[ADMIN|CLIENT|SP]_PRIVATE_KEY` variable in the system environment variables,
    2. `[ADMIN|CLIENT|SP]_PRIVATE_KEY` variable in the local `.env` file,
    3. if non of those are set, the app will prompt the user to input the private key for required operations in a secure manner.
- The app expects the private key to be 32-byte raw private key (hex, 0x-prefixed).
- Read-only commands do not require private key set, though some of them require user's address (`client --address` and `sp --organization`).
- Rule of thumb: the private key you set is the one that signs and sends transactions, \
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
- The app does not log any sensitive information neither to the console nor to the log files. 
  All transaction logs are stored without any sensitive information.

## Typical SP workflow

1. IMPORTANT: interaction with the chain requires the private key for the message sender, so for security do not use your miner wallet for sending commands to the Peer-to-pool PoRep Market. Instead you will need to create a miner controller wallet. If you already have one and want to reuse it, that’s fine. However for most efficiency, we recommend you create a new wallet, and register it as a controller wallet for all the miners you will be using in P2PP. The Market then uses controller status to verify that the command sender is authorised to send commands on behalf of your miner. 

Follow the steps here: [https://lotus.filecoin.io/storage-providers/operate/addresses/#control-addresses](https://lotus.filecoin.io/storage-providers/operate/addresses/#control-addresses):

2. Export the private key of your newly created wallet  
```bash
lotus wallet export <your-wallet-address-from-above> | xxd -r -p | jq -r '.PrivateKey' | base64 -d | xxd -p -c 32
```

3\. Clone this repo to download our CLI tool that will allow you to pull outstanding deals and onboard them: [https://github.com/fidlabs/filecoin-porep-market-tooling\#](https://github.com/fidlabs/filecoin-porep-market-tooling#)` NOTE: this repo is still heavily developed and continuously improved so please make sure to do git pull from inside the folder with the code to ensure you have the latest version of the code. 
```bash
gh repo clone fidlabs/filecoin-porep-market-tooling
```
4\. Go into your local copy of the tool and install dependencies:
```bash
python3 -m pip install -r requirements.txt
```
5\. Then copy the manifest file
```bash
cp .env.mainnet .env
```
6\.  Edit the ./env   file:

 * put in the secret key of the controller wallet from step 2 
```bash
#Private key used in SP operations
#Set this if you want to interact with the system as a storage provider (organization)
#This address needs to be the controlling address of provider\_id you want to manage in the SPRegistry contract
#See https://lotus.filecoin.io/storage-providers/operate/addresses/\#control-addresses
#32-byte raw private key (hex, 0x-prefixed)

SP_PRIVATE_KEY=<your miner controller wallet from step 2>
```
* Add your SP organization address in 0x (ethereum) format
```bash
#Organization address to manage SPs from
# You must have the SP_PRIVATE_KEY of an organization controlling address set to perform SP management operations

SP_ORGANIZATION=<your organization address converted to ETH format>
```
> NOTE: `<address you registered as your org address>` is the ethereum version of the address you gave as your org address. So if you registered f1cjn5vml22avryge434bj66tjrdir7gjgrbo4vpa, you can go to [https://filfox.info/en/address/f1cjn5vml22avryge434bj66tjrdir7gjgrbo4vpa](https://filfox.info/en/address/f1cjn5vml22avryge434bj66tjrdir7gjgrbo4vpa) and look up the ID of that address: `f03767689`, then go to [https://beryx.io/address\_converter](https://beryx.io/address_converter) and convert it to `0xff00000000000000000000000000000000397d89` 

7\. Ensure the file permissions on .env prevent the reading of this value by any user other than the one that runs the tooling. Assuming you are already logged in as the correct user, that would be:  
```bash
chmod 600 .env 
```
8\. Optional but very useful for downloading the deals: Install Aria2:
* On Mac `brew install aria2  `
* On Debian/Ubuntu: `sudo apt install aria2 ` 
* On Arch: `sudo pacman -S aria2`

9\. Now you should be ready to run the tools.

* To find deals allocated to you
```bash
python3 ./porep_tooling_cli.py sp get-deals
```

* Deals have 3 states:  
  * **Proposed:** The data is prepared and the client has submitted a deal proposal with all required metadata and SLA requirements.  
  * **Accepted:** The Storage Provider has accepted the deal. At this stage, the deal is waiting for the client to make the DataCap allocation. 
  * **Completed:** The client has made the DataCap allocation. The deal is now ready to be onboarded by the Storage Provider.  
* Deals in completed state are ready for onboarding. The deal includes a `manifest_url` entry: this tells you where the Singularity manifest is. All the CAR files referenced are then available for pulling from the standard location of `<manifest_ip>:7777/piece/<CID>`   
* Deals in accepted state need to be accepted. Assuming you are happy to accept the deal on the terms offered, run:
```bash   
  $ python3 ./porep_tooling_cli.py sp --address <address you registered as your org address> accept-deal <dealID you want to accept>
```
* Then check back a few minutes later   
* To download all the deals that are allocated to you and COMPLETED run:
```bash
python3 ./porep_tooling_cli.py sp get-deals completed
python3 ./porep_tooling_cli.py sp onboard-data <DEAL ID> --output-dir <your dir>
``` 
* Get the allocation IDs:
```bash
python3 ./porep_tooling_cli.py sp get-allocations <DEAL ID> --output-dir <your dir>
``` 
*  And claim deals:
 ```bash
python3 ./porep_tooling_cli.py sp claim-allocations curio <DEAL ID> 
``` 

7\. To get full list of commands for the tooling:
 ```bash
python3 ./porep_tooling_cli.py sp --help
 
Usage: porep_tooling_cli.py sp [OPTIONS] COMMAND [ARGS]...

  Storage Provider commands for interacting with the PoRep Market.

Options:
  --organization TEXT  Organization address to manage SPs from.  [env var: SP_ORGANIZATION]
  --confirm-info       Confirm current account info before executing command.  [default: false]
  --help               Show this message and exit.

Commands:
  accept-deal            Accept a deal proposal.
  claim-allocations      Interactively claim DDO allocations for a deal using the specified software.
  get-allocations        Get client allocations for a deal.
  get-deals              Get deals for the current SP.
  get-registered-info    Get PoRep Market registered info for the SP.
  info                   Display the current SP info.
  is-authorized          Check if your private key is authorized to manage deals for the given Storage...
  manage-proposed-deals  Interactively manage proposed deals.
  onboard-data           Download data for a deal using aria2 downloader.
  reject-deal            Reject a deal proposal.
  wait                   Wait for all pending transactions from the current private key to be mined and exit.
```


## Glossary

\# TODO

## Developing new CLI commands

- See files in `cli/commands` for examples of how to implement new commands.
- Keep the code clean and simple, follow the existing patterns and best practices.
- Use `Exception` (`ValueError`, `RuntimeError`, ...) for internal-like errors (things that "should not happen")
  and `click.ClickException` for user-like errors (things that happens "because of the user").
- Use `click.echo` for all user-facing output and `logger` for file logging.
- For read-only commands, print the output in json format for easy parsing by other tools.
