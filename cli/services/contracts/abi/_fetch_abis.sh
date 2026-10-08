#!/bin/bash

curl -s https://api.github.com/repos/fidlabs/porep-market/contents/abis?ref=main | jq -r '.[] | select(.name | endswith(".json")) | .download_url' | xargs -n1 curl -LO
