# Training Job Failure Recovery

**Facility:** dc-tokyo-01 | **Owner:** ml-platform / gpu-infra | **Last updated:** 2026-03-22

## Overview

Large-scale distributed training jobs across the dc-tokyo-01 GPU cluster fail for a variety of reasons. This runbook covers the most common failure modes, how to diagnose them, and the standard recovery procedure. All job failures generate an alert to the ml-platform on-call; hardware-related failures also page gpu-infra.

## Common Failure Modes

### NCCL Timeout

Symptoms: Job hangs, then fails with `NCCL WARN Timeout` or `NCCL ERROR: unhandled system error`. Typically caused by a network issue or a single slow/dead GPU in the communicator group.

Diagnosis:
```
# Check NCCL debug output (set NCCL_DEBUG=INFO on relaunch)
grep -i "nccl" /var/log/slurm/job-<jobid>.out

# Check InfiniBand port health
ibstat | grep -E "State|Rate"
ibdiagnet --ls 10
```

Action: Identify the failing node. If a single node is responsible, cordon it (see node_health_check runbook) and requeue the job. If the issue is fabric-wide, escalate to network-ops.

### Out of Memory (OOM)

Symptoms: Job killed with `CUDA out of memory` or kernel OOM killer invocation. Check `dmesg | grep -i oom` on the host.

Action: Verify no other processes are consuming GPU memory (`nvidia-smi`). If the node is clean, the job itself needs tuning -- notify the submitting team. If a leaked process is found, kill it, log the PID and owner, and requeue.

### Checkpoint Failure

Symptoms: Job fails during save with I/O errors or `OSError: [Errno 28] No space left on device`.

Action: Check the shared filesystem (`df -h /mnt/lustre-scratch`). If usage > 90%, alert storage-team to purge expired checkpoints. Verify the user's quota with `lfs quota -u <user> /mnt/lustre-scratch`.

## Checkpoint Recovery Procedure

1. Identify the last successful checkpoint: `ls -lt /mnt/lustre-scratch/<project>/checkpoints/ | head -5`
2. Validate checkpoint integrity: `python -c "import torch; torch.load('<ckpt>', map_location='cpu')"`
3. Update the job submission script to set `--resume-from=<last-good-ckpt>`
4. Requeue: `scontrol requeue <jobid>` or resubmit via `sbatch`

## Job Requeue Policy

- Jobs that fail due to infrastructure issues are automatically eligible for requeue with priority boost
- The ml-platform team maintains a requeue budget of 3 automatic retries per job; after that, manual investigation is required
- All requeues are logged in the `#training-ops` Slack channel with the failure reason and affected nodes
