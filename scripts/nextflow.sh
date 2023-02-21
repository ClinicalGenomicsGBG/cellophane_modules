#!/bin/bash
set -e -o pipefail

_clean () {
    echo "Killing nextflow..."
    kill -TERM $_nf_pid
    wait $_nf_pid
    code=$?
    exit $code
}

source ${_MODULES_INIT}
module load nextflow
HOME="$(pwd)" nextflow $@ & _nf_pid=$!

trap _clean EXIT

wait $_nf_pid
exit $?
