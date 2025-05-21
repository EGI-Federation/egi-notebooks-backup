FROM python:3.7-alpine

SHELL ["/bin/ash", "-o", "pipefail", "-c"]

# kubectl
RUN wget https://storage.googleapis.com/kubernetes-release/release/v1.14.2/bin/linux/amd64/kubectl \
        -nv -O /usr/local/bin/kubectl && chmod +x /usr/local/bin/kubectl

# restic
RUN wget https://github.com/restic/restic/releases/download/v0.9.5/restic_0.9.5_linux_amd64.bz2 -nv -O - \
      | bunzip2 > /usr/local/bin/restic && chmod +x /usr/local/bin/restic

# ssh is needed for restic
RUN apk --no-cache add openssh

# the backup script
COPY backup.sh /usr/local/bin/backup.sh

# the recovery part
COPY requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt
COPY recover.py /usr/local/bin
COPY recover.sh /usr/local/bin
