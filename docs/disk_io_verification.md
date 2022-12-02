# Disk IO Verification
Continuum includes the option to set the disk read/write throughput speed for the virtual machines it creates.
The following configuration file parameters are available, in MB/s, with default values of 0 for unlimited:
* cloud_read_speed
* edge_read_speed
* endpoint_read_speed 
* cloud_write_speed
* edge_write_speed
* endpoint_write_speed

The following code is an example of how to benchmark read/write throughput speed inside the VMs.
```bash
# Pick the drive you want to benchmark
# The default disk in the VMs is /dev/vda1, which we use for this example
sudo lsblk

# Benchmark read speed using hdparm
sudo hdparm -Ttv /dev/vda1

# Benchmark write speed using dd
sudo su
cd /tmp
mkdir mnt
mount /dev/vda1 ./mnt
sync
echo 3 > /proc/sys/vm/drop_caches
dd if=/dev/zero of=/tmp/mnt/temp oflag=direct bs=128k count=16k
rm -f /tmp/mnt/temp
umount ./mnt
rm -f ./mnt
```