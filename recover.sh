#!/bin/sh

set -x

# Get stuff from restic
mkdir /backup
restic restore latest --target /backup

# and now do the python magic
python /usr/local/bin/recover.py --backup-path /backup/exports/ --namespace "$NAMESPACE" --target-namespace "$TARGET_NAMESPACE" /backup/exports/pvc
