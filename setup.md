# Raspberry pi remote boot setup

The goal of this guide is to configure a (or multiple) raspberry pi(s) for netbooting.
The raspberry pi will be using an Ubuntu 20.04 LTS 64-bit ARM distribution (https://cdimage.ubuntu.com/releases/20.04/release/ubuntu-20.04.4-live-server-arm64.iso).
However, in principle, any distro that is supported for the raspberry pi can be used, although they may require small adjustments.
Note: KVM requires a 64-bit kernel. This means that if you want to run virtual machines, make sure that your distro supports 64-bit. I would not recommend running any virtual machine without KVM on a raspberry pi. Also, be aware that the official raspbian distro uses 32-bit by default.

If you are using Ubuntu you must also disable `unattended-upgrade` since it will interfere with this setup and possibly break it later on.
The best way I have found to do this is to use `dpkg-reconfigure unattended-upgrades`, select no and then reboot.

## Enabling and configuring netboot

Before the raspberry pi can be booted remotely, it first needs to be booted and configured with an sd card.
Unfortunately, since raspi-config is not supported on Ubunutu, there is no clear way to enable netbooting on Ubunutu.
To circumvent this, I used the official raspbian distro and used raspi-config, which will show a menu where netbooting can be enabled.

Originally, I used the official raspbian distro for enabling and configuring netbooting.
I have not tested performing this operation under another distro.
If the setup does not work, I recommend using the official raspbian distro and to enable netbooting using `raspi-config`.
Then follow the rest of this section and rewrite the sd card with your prefered distro.

To enable netbooting and support multiple pi's on one TFTP server, it is necessary to flash the eeprom with `rpi-eeprom-config --edit`.
This will show a configuration file that needs to be edited to look similar to this:
```
BOOT_UART=0
WAKE_ON_GPIO=1
POWER_OFF_ON_HALT=0
                                                                              
                                                                              
                                                                              
                                                                              
                                                                              
                                                                              
                                                                              
                                                                              
                                                                              
                                                                              
                                                                             
                                                                              
             
[all]
BOOT_ORDER=0xf21
TFTP_PREFIX=1
TFTP_PREFIX_STR=pi0/
```

The `BOOT_ORDER` specifies that it will first try the sd card, then try booting over the network and repeat.
The `TFTP_PREFIX` and `TFTP_PREFIX_STR` specify where in the root of the TFTP server the boot files are located.
In this case it will look at: `[TFTP_ROOT]/pi0/`.
If this is not setup appropriately every raspberry pi will use the same boot files.
For more information visit https://www.raspberrypi.com/documentation/computers/raspberry-pi.html and look under the section `Raspberry Pi 4 Bootloader Configuration`

## Jacob's guide

From this point onward I will rely heavily on Jacob's guide for netbooting on the raspberry pi (https://jacobrsnyder.com/2021/01/20/network-booting-a-raspberry-pi-with-docker-support/).
Since this guide already has most of the information I will only briefly mention the relevant parts of the guide and point out some caveats.
If you require a more detailed explanation I will refer you to the aforementioned guide.

## ISCSI

ISCSI must be installed on both the server and the raspberry pi.
I use `open-iscsi`.
The initiator name can be found and edited in `/etc/iscsi/initiatorname.iscsi`.

After ISCSI is installed, the kernel must be updated to use it while booting.
`touch /etc/iscsi/iscsi.initramfs
update-initramfs -v -k `uname -r` -c`

On some distro's (not for Ubuntu) the following may also be required.
`sed 's/ib_iser/\#ib_iser/' /lib/modules-load.d/open-iscsi.conf > /lib/modules-load.d/open-iscsi.conf`

For configuring ISCSI on the host I found this article about it on archlinux wiki to be quite helpful (https://wiki.archlinux.org/title/ISCSI/LIO).
The article explains how to configure ISCSI to provide an image file for other systems.
As an example, I will show my iscsi setup which is configured to work with three raspberry pi's.
`/> ls
o- / ...................................................................................................... [...]
  o- backstores ........................................................................................... [...]
  | o- block ............................................................................... [Storage Objects: 0]
  | o- fileio .............................................................................. [Storage Objects: 3]
  | | o- pi_fs0 ....................................... [/home/felix/pi_store/fs0 (31.2GiB) write-back activated]
  | | | o- alua ................................................................................ [ALUA Groups: 1]
  | | |   o- default_tg_pt_gp .................................................... [ALUA state: Active/optimized]
  | | o- pi_fs1 ....................................... [/home/felix/pi_store/fs1 (31.2GiB) write-back activated]
  | | | o- alua ................................................................................ [ALUA Groups: 1]
  | | |   o- default_tg_pt_gp .................................................... [ALUA state: Active/optimized]
  | | o- pi_fs2 ....................................... [/home/felix/pi_store/fs2 (31.2GiB) write-back activated]
  | |   o- alua ................................................................................ [ALUA Groups: 1]
  | |     o- default_tg_pt_gp .................................................... [ALUA state: Active/optimized]
  | o- pscsi ............................................................................... [Storage Objects: 0]
  | o- ramdisk ............................................................................. [Storage Objects: 0]
  o- iscsi ......................................................................................... [Targets: 3]
  | o- iqn.1993-08.org.debian:01:3f9e982e36d8 ......................................................... [TPGs: 1]
  | | o- tpg1 ............................................................................ [no-gen-acls, no-auth]
  | |   o- acls ....................................................................................... [ACLs: 1]
  | |   | o- iqn.1993-08.org.debian:01:3f9e982e36d8 ............................................ [Mapped LUNs: 1]
  | |   |   o- mapped_lun0 ............................................................ [lun0 fileio/pi_fs1 (rw)]
  | |   o- luns ....................................................................................... [LUNs: 1]
  | |   | o- lun0 ................................. [fileio/pi_fs1 (/home/felix/pi_store/fs1) (default_tg_pt_gp)]
  | |   o- portals ................................................................................. [Portals: 1]
  | |     o- 0.0.0.0:3260 .................................................................................. [OK]
  | o- iqn.1993-08.org.debian:01:a8884c66dbf .......................................................... [TPGs: 1]
  | | o- tpg1 ............................................................................ [no-gen-acls, no-auth]
  | |   o- acls ....................................................................................... [ACLs: 1]
  | |   | o- iqn.1993-08.org.debian:01:a8884c66dbf ............................................. [Mapped LUNs: 1]
  | |   |   o- mapped_lun0 ............................................................ [lun0 fileio/pi_fs2 (rw)]
  | |   o- luns ....................................................................................... [LUNs: 1]
  | |   | o- lun0 ................................. [fileio/pi_fs2 (/home/felix/pi_store/fs2) (default_tg_pt_gp)]
  | |   o- portals ................................................................................. [Portals: 1]
  | |     o- 0.0.0.0:3260 .................................................................................. [OK]
  | o- iqn.1993-08.org.debian:01:c6823d458078 ......................................................... [TPGs: 1]
  |   o- tpg1 ............................................................................ [no-gen-acls, no-auth]
  |     o- acls ....................................................................................... [ACLs: 1]
  |     | o- iqn.1993-08.org.debian:01:c6823d458078 ............................................ [Mapped LUNs: 1]
  |     |   o- mapped_lun0 ............................................................ [lun0 fileio/pi_fs0 (rw)]
  |     o- luns ....................................................................................... [LUNs: 1]
  |     | o- lun0 ................................. [fileio/pi_fs0 (/home/felix/pi_store/fs0) (default_tg_pt_gp)]
  |     o- portals ................................................................................. [Portals: 1]
  |       o- 0.0.0.0:3260 .................................................................................. [OK]
  o- loopback ...................................................................................... [Targets: 0]
  o- vhost ......................................................................................... [Targets: 0]
  o- xen-pvscsi .................................................................................... [Targets: 0]`

## Final changes on the raspberry pi

Once ISCSI is setup, you can discover targets and mount them on the pi with the following commands:
`iscsiadm --mode discovery --portal target_ip --type sendtargets
iscsiadm -m node --target targetname --portal target_ip -o new`
More info can be found on the following article: https://wiki.archlinux.org/title/Open-iSCSI

Now, format and mount the ISCSI target and copy the filesystem into it.
`rsync -avhP --exclude /boot --exclude /proc --exclude /sys --exclude /dev --exclude /mnt / /mnt/
mkdir /mnt/{dev,proc,sys,boot,mnt}`

Then modify fstab on the ISCSI target to look like so:
`
UUID=fe5d08b1-fc3a-4e83-be4c-7feff6ebdc16 / ext4 defaults,noatime 0 1
192.168.0.101:/home/felix/pi_store/boot_dir/pi0 /boot nfs4 defaults,noatime 0 2
`

The first line refers to the ISCSI target which will be mounted as root.
The second line refers to the boot directory and requires nfs on the raspberry pi and an nfs server.
The second line can be ignored if you are not concerned about updating the raspberry pi.
If you do want to update the raspberry pi (or just change some files under the `/boot` directory) you can look at Jacob's guide to see how to setup NFS for this purpose.

The boot configuration in `/boot/config.txt` must now be updated to use the correct kernel image
For Ubunutu I added the following:
`[pi4]
kernel=vmlinuz
initramfs initrd.img followkernel
`

Lastly, you must specify where the root partition is when the raspberry pi is booting up in `/boot/cmdline.txt`.
`
console=serial0,115200 console=tty1 ip=::::{PI HOSTNAME}:eth0:dhcp root=UUID={UUID} rootfstype=ext4 elevator=deadline fsck.repair=yes rootwait ISCSI_INITIATOR={INITIATOR IQN} ISCSI_TARGET_NAME={TARGET IQN} ISCSI_TARGET_IP={TARGET IP} ISCSI_TARGET_PORT=3260 rw
`

## Dnsmasq and TFTP

Dnsmasq will act as the TFTP server and deliver the files that are required for booting the raspberry pi.
Configuring dnsmasq for this can be done in `/etc/dnsmasq.conf` and is rather simple.
Here is an example from my own dnsmasq configuration file:
```
port=0
dhcp-range=192.168.0.255,proxy
log-dhcp
enable-tftp
tftp-root=/home/felix/pi_store/boot_dir/
pxe-service=0,"Raspberry Pi Boot"
```

Now it is time to copy the boot directory from the raspberry pi to the corresponding boot directory on the TFTP server, depending on what you specified as `tftp-root` in dnsmasq and `TFTP_PREFIX_STR` on the raspberry pi.

On Ubuntu many important files are placed under the `/boot/firmware` directory.
However, the raspberry pi will not look there when starting up and thus fail to boot.
The easiest way to fix this is to copy the files under `/boot/firmware` to `/boot`.
However, this will have to be redone after a system update.
A more permanent way to fix this would be to create symbolic links from `/boot/` to `/boot/firmware` for each relevant file.

Now you should be able to boot the raspberry pi without an sd card.

For debugging `/var/log/daemon.log` contains logging information when a raspberry pi attempts to gather their files from the TFTP server.
