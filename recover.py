import argparse
import glob
import logging
import os
import subprocess
import time

import yaml

import kubernetes
from kubernetes.client.models import (
    V1ObjectMeta, V1ResourceRequirements,
    V1PersistentVolumeClaim, V1PersistentVolumeClaimSpec,
)
import kubernetes.client
from kubernetes.client.rest import ApiException



def make_pvc(old_pvc, storage_class):
    pvc = V1PersistentVolumeClaim()
    pvc.kind = "PersistentVolumeClaim"
    pvc.api_version = "v1"
    pvc.metadata = V1ObjectMeta()
    pvc.metadata.name = old_pvc['metadata']['name'] 
    username = old_pvc['metadata']['annotations']['hub.jupyter.org/username']
    pvc.metadata.annotations = {
        'hub.jupyter.org/username': username 
    }
    pvc.metadata.labels = old_pvc['metadata']['labels'].copy()
    pvc.spec = V1PersistentVolumeClaimSpec()
    pvc.spec.access_modes = old_pvc['spec']['accessModes'].copy()
    pvc.spec.resources = V1ResourceRequirements()
    pvc.spec.resources.requests = {
        "storage": old_pvc['spec']['resources']['requests']['storage']
    }
    if storage_class:
        pvc.metadata.annotations.update(
            {"volume.beta.kubernetes.io/storage-class": storage_class}
        )
        pvc.spec.storage_class_name = storage_class
    return pvc


def main():
    logging.basicConfig(level=logging.INFO)
    parser = argparse.ArgumentParser()
    parser.add_argument("pvc", help="YAML file with the PVC description")
    parser.add_argument("--namespace", "-n",
                        help="namespace to consider (all if unspecified)")
    parser.add_argument("--storage-class", "-s",
                        help="storage class for PVC")
    parser.add_argument("--backup-path", help="where the backup is",
                        default=".")
    parser.add_argument("--overwrite", help="Overwrite existing PVC",
                        action="store_true")
    args = parser.parse_args()

    kubernetes.config.load_incluster_config()
    v1 = kubernetes.client.CoreV1Api()
    pvcs = {}
    with open(args.pvc, 'r') as f:
        pvcs = yaml.safe_load(f.read())

    count = 0
    for old_pvc in pvcs['items']:
        if old_pvc['kind'] != 'PersistentVolumeClaim':
            continue
        md = old_pvc['metadata']
        namespace = md['namespace']
        if args.namespace and namespace != args.namespace:
            continue
        username = md.get('annotations', {}).get('hub.jupyter.org/username')
        if not username:
            continue
        logging.info("PVC: %s", md['name'])
        try:
            new_pvc = v1.create_namespaced_persistent_volume_claim(
                namespace=namespace,
                body=make_pvc(old_pvc, args.storage_class)
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
        # now wait until the volume is there and copy files 
        vol_ready = False
        while not vol_ready:
            pvc = v1.read_namespaced_persistent_volume_claim(
                    name=md['name'],
                    namespace=namespace
            )
            if pvc.spec.volume_name:
                vol = v1.read_persistent_volume(name=pvc.spec.volume_name) 
                # this is very NFS specific, will change quite a lot with 
                # any other kind of storage
                dest_path = vol.spec.nfs.path
                logging.info("Destination path: %s" % dest_path)
                vol_ready = True
                break
            time.sleep(3)
        # src_path is discovered as "namespace-<id>-pvc-<some number>"
        base_path = os.path.join(args.backup_path, '%s-%s-pvc-*'
                                                    % (namespace, md['name']))
        src_path = glob.glob(base_path).pop()
        logging.info("Will restore storage of user %s at %s from %s",
                     username, dest_path, src_path)
        sts = subprocess.call("tar -cf - -C %s . | tar -xf - -C %s"
                              % (src_path, dest_path), shell=True)
        if sts != 0:
            logging.error("*" * 80)
            logging.error("*" * 80)
            logging.error("Something went wrong: %s, "
                          "please manually copy contents" % e)
        count = count + 1
    logging.info("Restored %d users" % count)

if __name__ == "__main__":
    main()
