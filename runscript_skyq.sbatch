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

PROJECT_DIR="/lustre/work/nimcclur/skyq"

echo "[$(date)] SkyQ started"
echo "Job ID: ${SLURM_JOB_ID}"
echo "Node: $(hostname)"
echo "Project directory: ${PROJECT_DIR}"

cd "$PROJECT_DIR" || exit 1
source "$PROJECT_DIR/skyq_source.sh"

echo "Working directory: $(pwd)"
echo "Python executable: $(which python)"
echo "Python version: $(python --version)"

python -u -m bin.runscript

echo "[$(date)] SkyQ finished"
