"""
Utility to recover data from restic.
"""

import argparse
import fnmatch
import logging
import os
import shutil
import subprocess
import sys
import time

import kubernetes
import kubernetes.client
import yaml
from kubernetes.client.models import (
    V1ObjectMeta,
    V1PersistentVolumeClaim,
    V1PersistentVolumeClaimSpec,
    V1ResourceRequirements,
)
from kubernetes.client.rest import ApiException

LOCAL_RESTORE_PATH = "/exports/recover-cache"


def make_pvc(old_pvc, storage_class):
    """Construct persistent volume claim python object for Kubernetes."""
    pvc = V1PersistentVolumeClaim()
    pvc.kind = "PersistentVolumeClaim"
    pvc.api_version = "v1"
    pvc.metadata = V1ObjectMeta()
    pvc.metadata.name = old_pvc["metadata"]["name"]
    username = old_pvc["metadata"]["annotations"]["hub.jupyter.org/username"]
    pvc.metadata.annotations = {"hub.jupyter.org/username": username}
    pvc.metadata.labels = old_pvc["metadata"]["labels"].copy()
    pvc.spec = V1PersistentVolumeClaimSpec()
    pvc.spec.access_modes = old_pvc["spec"]["accessModes"].copy()
    pvc.spec.resources = V1ResourceRequirements()
    pvc.spec.resources.requests = {
        "storage": old_pvc["spec"]["resources"]["requests"]["storage"]
    }
    if storage_class:
        pvc.metadata.annotations.update(
            {"volume.beta.kubernetes.io/storage-class": storage_class}
        )
        pvc.spec.storage_class_name = storage_class
    return pvc


def restic(args, dry_run=0):
    """Call restic command."""
    cmd = ["restic"] + args
    logging.info("shell: %s", " ".join(cmd))
    if dry_run:
        result = subprocess.CompletedProcess(args=cmd, stdout=b"", returncode=0)
    else:
        result = subprocess.run(cmd, capture_output=True, check=False)
        if result.returncode != 0:
            logging.error(
                "shell: %s => return code %d", " ".join(cmd), result.returncode
            )
    return result


def main():
    """Recover data from restic."""
    logging.basicConfig(level=logging.INFO)
    parser = argparse.ArgumentParser()
    parser.add_argument("pvc", help="YAML file with the PVC description")
    parser.add_argument(
        "--namespace", "-n", help="namespace to consider (all if unspecified)"
    )
    parser.add_argument("--storage-class", "-s", help="storage class for PVC")
    parser.add_argument(
        "--remote-backup-path",
        help="where the backup is in the repository",
        default="/exports",
    )
    parser.add_argument(
        "--overwrite", help="Overwrite existing PVC", action="store_true"
    )
    parser.add_argument(
        "--skip-data",
        help="Do not restore data, only volumes metadata",
        action="store_true",
    )
    parser.add_argument(
        "--target-namespace", "-t", help="target namespace (no change if unspecified)"
    )
    parser.add_argument("--dry-run", action="store_true", help="Simulated run")
    args = parser.parse_args()

    result = restic(["ls", "-q", "latest", args.remote_backup_path], dry_run=False)
    if result.returncode != 0:
        logging.error("Initial restic command failed")
        sys.exit(result.returncode)
    old_paths = [
        os.path.relpath(line, args.remote_backup_path)
        for line in result.stdout.decode("utf-8").splitlines()
    ]
    for p in old_paths:
        logging.debug("Found path in restic: %s", p)

    kubernetes.config.load_incluster_config()
    v1 = kubernetes.client.CoreV1Api()
    pvcs = {}
    with open(args.pvc, "r", encoding="utf-8") as f:
        pvcs = yaml.safe_load(f.read())

    if not args.dry_run:
        os.makedirs(LOCAL_RESTORE_PATH, exist_ok=True)

    count = 0
    for old_pvc in pvcs["items"]:
        if old_pvc["kind"] != "PersistentVolumeClaim":
            continue
        md = old_pvc["metadata"]
        namespace = md["namespace"]
        if args.namespace and namespace != args.namespace:
            continue
        if args.target_namespace:
            target_namespace = args.target_namespace
        else:
            target_namespace = namespace
        username = md.get("annotations", {}).get("hub.jupyter.org/username")
        if not username:
            continue
        logging.info("PVC: %s", md["name"])
        pvc = make_pvc(old_pvc, args.storage_class)
        try:
            if not args.dry_run:
                v1.create_namespaced_persistent_volume_claim(
                    namespace=target_namespace, body=pvc
                )
        except ApiException as e:
            if e.status == 409:
                if args.overwrite:
                    logging.info("PVC is already there, but restoring again")
                else:
                    # skip it, assume was copied before
                    logging.info("PVC is already there, ignoring")
                    continue
            else:
                raise e
        if args.dry_run:
            dest_path = os.path.join("/exports", "fake-" + md["name"])
        else:
            dest_path = None
            # now wait until the volume is there and copy files
            vol_ready = False
            while not vol_ready:
                pvc = v1.read_namespaced_persistent_volume_claim(
                    name=md["name"], namespace=target_namespace
                )
                if pvc.spec.volume_name:
                    vol = v1.read_persistent_volume(name=pvc.spec.volume_name)
                    # this is very NFS specific, will change quite a lot with
                    # any other kind of storage
                    dest_path = vol.spec.nfs.path
                    logging.info("Destination path: %s", dest_path)
                    vol_ready = True
                    break
                time.sleep(0.5)
        # src_path is discovered as "namespace-<id>-pvc-<some number>"
        base_path = f"{namespace}-{md['name']}-pvc-*"
        matched = fnmatch.filter(old_paths, base_path)
        logging.debug("Matching %s => %s", base_path, matched)
        if len(matched) == 0:
            logging.error("*" * 80)
            logging.error(
                "Source path for volume %s of user %s not found", md["name"], username
            )
            continue
        if dest_path is None:
            logging.error("*" * 80)
            logging.error(
                "Destination path for volume %s of user %s not found",
                md["name"],
                username,
            )
            continue
        src_path = os.path.join(args.remote_backup_path, matched.pop())
        logging.info(
            "%s restore storage of user %s at %s from %s",
            "Won't" if args.skip_data else "Will",
            username,
            dest_path,
            src_path,
        )
        if not args.skip_data:
            result = restic(
                [
                    "restore",
                    "latest",
                    "--include",
                    src_path,
                    "--target",
                    LOCAL_RESTORE_PATH,
                ],
                dry_run=args.dry_run,
            )
            if result.returncode != 0:
                logging.error("*" * 80)
                logging.error(
                    "Something went wrong with volume %s of user %s",
                    md["name"],
                    username,
                )
            if not dest_path or dest_path == "/":
                logging.error("*" * 80)
                logging.error(
                    "Wrong destination directory for volume %s of user %s",
                    md["name"],
                    username,
                )
                continue
            if os.path.exists(dest_path):
                logging.info("Removing %s", dest_path)
                if not args.dry_run:
                    shutil.rmtree(dest_path)
            restored_path = LOCAL_RESTORE_PATH + src_path
            logging.info("Moving %s to %s", restored_path, dest_path)
            if not args.dry_run:
                shutil.move(restored_path, dest_path)
        count = count + 1
    logging.info("Restored %d users", count)


if __name__ == "__main__":
    main()
