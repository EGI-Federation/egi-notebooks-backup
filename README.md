# egi-notebooks-backup

Notebook configuration is completely stored in github repository, the service can
be re-created on a running k8s cluster by installing the helm charts with the
configuration in the different directories.

However, user data requires to be backed up and restored in case of issues
with the backing volumes.

**CURRENT SOLUTION IS DEEPLY TIED TO THE NFS VOLUMES USED!**

## Daily backup

A helm chart is provided to perform daily backup of the user volumes. This
chart creates a k8s cron job that will take care of:
- Dumping the k8s information about the existing pvc for the cluster
- Backing up with [restic](https://restic.net/) the NFS share where the
  k8s pv are hosted.

## Recovering user data

This is not included in the helm chart as it is meant to be manually triggered
by the Notebooks admin.
