#!/bin/bash

set -e -o pipefail

module load spring
echo "CMD: spring $@"
spring $@
