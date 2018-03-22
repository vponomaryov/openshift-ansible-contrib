#! /bin/bash
#
# List of expected input args:
# - $1 is an env dir, i.e '/home/username/.../.tox/ocp3.6'
# - $2 is a tag to checkout from,
#   i.e. 'openshift-ansible-3.6.173.0.96-1' for OCP v3.6
#   See list of tags here: https://github.com/openshift/openshift-ansible/tags

OPENSHIFT_ANSIBLE_GIT_URL='git://github.com/openshift/openshift-ansible.git'
TARGET_DIR=$1/usr/share/ansible/openshift-ansible
TAG=$2

if [ -z "$TAG" ]; then
    # NOTE(vponomar): get latest tag by 3.X branch
    TAG=$(git ls-remote --tags $OPENSHIFT_ANSIBLE_GIT_URL \
        "refs/tags/openshift-ansible-$(echo $1 | grep -oE '[^tox\/ocp]+$').*" \
        | grep -v "\{\}" | sort -t / -k 3 -V | tail -n 1 | awk '{print $2}' )
    echo "Custom Git tag hasn't been specified, using latest Git tag '$TAG'"
else
    echo "Using custom Git tag '$TAG'"
fi

if [[ ! -d $TARGET_DIR ]]; then
    mkdir -p $TARGET_DIR
    git clone $OPENSHIFT_ANSIBLE_GIT_URL --single-branch --branch $TAG $TARGET_DIR
else
    cd $TARGET_DIR
    git fetch -t --all
    git reset --hard $TAG
fi
