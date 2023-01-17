#!/bin/bash

set -e -o pipefail

if [[ -d "${_MODULES_INIT}" ]]; then
    echo "rnaseq.modules_init does not exist."
    exit 1
else
    source "${_MODULES_INIT}"
    module load petasuite
    petasuite $@
fi
