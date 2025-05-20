#!/bin/sh

set -x

# get Kubernetes metadata from restic
mkdir /backup
restic restore latest --include /exports/pvc --target /backup

# and now do the python magic
python /usr/local/bin/recover.py --backup-path /exports --namespace "$NAMESPACE" --target-namespace "$TARGET_NAMESPACE" /backup/exports/pvc "$@"
