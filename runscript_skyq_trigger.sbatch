#!/bin/bash
#SBATCH --job-name=skyq-trigger
#SBATCH --partition=quanah
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=1
#SBATCH --time=24:00:00
#SBATCH --output=logs/%x_%j.out
#SBATCH --error=logs/%x_%j.err

set -e

PROJECT_DIR="/lustre/work/nimcclur/skyq"
CHECK_SECONDS="${SKYQ_TRIGGER_CHECK_SECONDS:-300}"

echo "[$(date)] SkyQ trigger started"
echo "Job ID: ${SLURM_JOB_ID}"
echo "Node: $(hostname)"
echo "Project directory: ${PROJECT_DIR}"
echo "Check interval: ${CHECK_SECONDS} seconds"

cd "$PROJECT_DIR" || exit 1
source "$PROJECT_DIR/skyq_source.sh"

while true; do
        echo "[$(date)] Checking for new SkyQ submissions"
        python -u -m bin.trigger_skyq
        sleep "$CHECK_SECONDS"
done
