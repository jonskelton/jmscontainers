#!/bin/bash
# Runs as root inside the Ubuntu 24.04 container: install Podman 4.9.x and
# set up a rootless user, then hand off to qualify-user.sh as that user.
# Usage (from a rootless-Podman host):
#   podman run --rm --privileged --device /dev/fuse --security-opt label=disable \
#     -v "$(dirname "$0")":/qual:ro -v "$PWD/out":/out \
#     docker.io/library/ubuntu:24.04 bash /qual/qualify-podman-nested-ubuntu2404.sh
# Nested capture only — kernel-adjacent results need re-confirmation on a
# real Ubuntu 24.04 host (the planned CI integration job).
set -euxo pipefail

export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq podman uidmap fuse-overlayfs slirp4netns python3 >/dev/null

podman --version

# Rootless user with subordinate ID ranges. The outer (nested) container
# namespace only spans UIDs 0-65535, so the subordinate range must fit
# inside it — useradd's auto-allocated 165536+ range is unusable here.
useradd -m -u 1001 -s /bin/bash quser
sed -i '/^quser:/d' /etc/subuid /etc/subgid
echo 'quser:2000:63000' >> /etc/subuid
echo 'quser:2000:63000' >> /etc/subgid

mkdir -p /out
chown quser:quser /out

# Ubuntu's kernel.apparmor_restrict_unprivileged_userns is a host-kernel
# knob; inside this container we inherit the outer namespace setup.
su - quser -c 'bash /qual/qualify-podman.sh'
