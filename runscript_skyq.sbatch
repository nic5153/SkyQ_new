#!/bin/bash
#SBATCH --job-name=skyq
#SBATCH --partition=quanah
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=1
#SBATCH --time=01:00:00
#SBATCH --output=logs/%x_%j.out
#SBATCH --error=logs/%x_%j.err

set -e

PROJECT_DIR="/lustre/scratch/nimcclur/skyq"

cd "$PROJECT_DIR" || exit 1
source "$PROJECT_DIR/skyq_source.sh"

python -m bin.runscript.py
