#!/bin/bash

set -e -o pipefail

module load petasuite
echo "CMD: petasuite $@"
petasuite $@
