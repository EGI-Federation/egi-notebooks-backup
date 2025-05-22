#!/bin/sh

set -x

# produce a list of the PVCs for restoring
kubectl get pvc --all-namespaces -o yaml >"$NFS_PATH"/pvc

# Backup things (not prometheus...)
restic backup "$NFS_PATH" "$@"
