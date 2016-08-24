#! /bin/sh -e

sudo docker build -f jenkins-check-Dockerfile  -t fm-orchestrator/jenkins-check-24 .
sudo docker run fm-orchestrator/jenkins-check-24
