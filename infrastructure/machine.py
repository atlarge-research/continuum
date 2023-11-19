"""\


Define Machine object and functions to work with this object
The Machine object represents a physical machine used to run this benchmark
"""


class Machine:
    """Class representing provisioned machines on cloud, edge, and endpoint, running on hosts"""

    def __init__(self, layer, provider, base=False):
        """Create the Machine object

        Args:
            layer (dict): Layer this machine is part of (cloud/edge/endpoint).
            provider (dict): Provider that provisions this machine
            base (bool, optional): Is this a base machine? Defaults to False
        """
        self.name = ""  # Name of the user and of the machine
        self.ip = ""
        self.ip_internal = ""  # ip is used for external communication, ip_internal between machines
        self.ssh = ""  # user@ip

        # The layer and provider this machine is provisioned on/with
        # These are dicts, specific parts of the global config
        self.layer = layer
        self.provider = provider

        # The machine can be a base machine or a 'normal' machine
        # Base machines are used to download and install software once
        # Then, the resulting base VM image is shared between all 'normal' machines
        # Only those providers which support a structure with base images (also called backing
        # images) will create dedicated base machines (VMs). Other providers will use the same
        # machine for base and normal machines
        self.base = base

    def __repr__(self):
        """Returns this string when called as print(machine_object)"""
        return """
[ MACHINE ]
    SSH             %s
    NAME            %s
    IP              %s
    IP_INTERNAL     %s
    LAYER           %s
    PROVIDER        %s
    BASE            %s""" % (
            self.ssh,
            self.name,
            self.ip,
            self.ip_internal,
            self.layer["name"],
            self.provider["name"],
            self.base,
        )
