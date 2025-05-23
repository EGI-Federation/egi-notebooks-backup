# egi-notebooks-backup

Notebook configuration is completely stored in GitHub repository, the service can
be re-created on a running k8s cluster by installing the helm charts with the
configuration in the different directories.

However, user data requires to be backed up and restored in case of issues
with the backing volumes.

**CURRENT SOLUTION IS DEEPLY TIED TO THE NFS VOLUMES USED IN OUR DEPLOYMENT!**

## Daily backup

A helm chart is provided to perform daily backup of the user volumes. This
chart creates a k8s cron job that will take care of:

- Dumping the k8s information about the existing pvc for the cluster
- Backing up with [restic](https://restic.net/) the NFS share where the
  k8s pv are hosted.

### Pre-requisites

- A initialised restic repository (sftp is assumed in the helm chart for the
  time being)

```console
$ restic -v init --repo <the repo>
enter password for new repository:
enter password again:
created restic repository ff9e0a30f5 at sftp:centos@134.158.151.166:/backups/notebooks

Please note that knowledge of your password is required to access
the repository. Losing your password means that your data is
irrecoverably lost.
```

The private key of user and public key of hosts must be specified in the chart
configuration when installing.

- Host where the NFS is hosted labeled so the pod can run there (helm defaults
  to `nfs-server=true`)

## Recovering user data

This is not included in the helm chart as it is meant to be manually triggered
by the Notebooks admin. For convenience some k8s objects are included in the
recovery directory, these will require:

- Secrets similar to the one in the helm chart:

```shell
kubectl create secret generic restic-ssh --from-file=id_rsa --from-file=known_hosts

kubectl create secret generic restic-password --from-literal=password=<some secret>
```

- Create rbac roles for giving permission to create pvc's:

```shell
kubectl apply -f recovery/rbac.yaml
```

- Tune the job to use the namespaces you want to recover and apply:

```shell
kubectl apply -f recovery/job.yaml
```

- Enjoy the recovery process!

```shell
kubectl logs -f <your recovery-pod>
```
