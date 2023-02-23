#!/bin/bash

set -e -o pipefail

_clean () {
    echo "Killing nextflow..."
    kill -TERM $_nf_pid
    wait $_nf_pid
    code=$?
    exit $code
}

module load $_NEXTFLOW_MODULE
nextflow $@ & _nf_pid=$!

trap _clean EXIT

wait $_nf_pid
exit $?
