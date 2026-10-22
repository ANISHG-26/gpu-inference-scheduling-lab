#!/bin/sh
# Prepared fixed teaching input; submit only after Slurm compatibility acceptance.
#SBATCH --job-name=lab-short-cpu
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=1
#SBATCH --mem=64M
#SBATCH --time=00:01:00
set -eu
sleep 20
