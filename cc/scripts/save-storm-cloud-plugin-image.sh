#!/bin/bash
# This script saves the StormHub Cloud Docker image as a tar file
# Depends on the StormHub Cloud image being built first

echo "Saving StormHub Cloud Docker image as a tar file"
docker save cc-stormhub-cloud -o stormhub-cloud.tar