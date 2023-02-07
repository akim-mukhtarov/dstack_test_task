#!/bin/bash

mkdir -p /etc/systemd/system/docker.service.d/
touch /etc/systemd/system/docker.service.d/aws-credentials.conf

cat << EOT >> /etc/systemd/system/docker.service.d/aws-credentials.conf
[Service]
Environment="AWS_ACCESS_KEY_ID=$1"
Environment="AWS_SECRET_ACCESS_KEY=$2"
EOT
# Restart docker to let it know about AWS credentials
sudo systemctl daemon-reload
sudo service docker restart

