# Disk IO Verification

Continuum YAML VM specs can constrain virtual disk throughput per cluster. The
active keys live under `infrastructure.clusters[].resources.vms.spec`:

- `storage_read_mbps`
- `storage_write_mbps`

Both values are in MB/s. A value of `0.0` means unlimited, which is also the
parser default when the key is omitted.

Example:

```yaml
infrastructure:
  clusters:
    - id: cloud-1
      tier: cloud
      resources:
        vms:
          count: 1
          spec:
            cores: 2
            memory_gb: 4
            storage_read_mbps: 100.0
            storage_write_mbps: 50.0
```

To verify behavior inside a retained VM, first find the SSH hint in
`<base_path>/.continuum/logs/` or inspect `<base_path>/.continuum/state.json`.
Then run a simple guest-side check:

```bash
sudo lsblk
sudo hdparm -Ttv /dev/vda1

sudo mkdir -p /tmp/continuum-disk-check
sudo mount /dev/vda1 /tmp/continuum-disk-check
sync
sudo sh -c 'echo 3 > /proc/sys/vm/drop_caches'
sudo dd if=/dev/zero of=/tmp/continuum-disk-check/temp oflag=direct bs=128k count=16k
sudo rm -f /tmp/continuum-disk-check/temp
sudo umount /tmp/continuum-disk-check
sudo rmdir /tmp/continuum-disk-check
```

Use this as a manual diagnostic only. It is not part of the cloud-safe static
audit or the default smoke success contract.
