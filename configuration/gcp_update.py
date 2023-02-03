"""\
Update GCP information for all GCP configs
"""

import os
import sys
import argparse

# pylint: disable=import-error,wrong-import-position

sys.path.append(os.path.abspath("../infrastructure"))

import machine as m

# pylint: enable=import-error,wrong-import-position


def get_files(base="."):
    """Get all .cfg files in the /configuration folder

    Args:
        base (str, optional): Base directory to start searching from. Defaults to ".".

    Returns:
        list(str): List of all .cfg files found
    """
    target_files = []
    for folder, nested_folders, files in os.walk(base):
        # Add files in current folder
        for file in files:
            if ".cfg" in file:
                target_files.append("%s/%s" % (folder, file))

        # Go to nested folders
        if folder != base:
            for nested_folder in nested_folders:
                nested_files = get_files(base="%s/%s" % (folder, nested_folder))
                target_files += nested_files

    if "./template.cfg" in target_files:
        target_files.remove("./template.cfg")

    return target_files


def update_files(files, target, replace, reset):
    """Update all occurences of <existing string> to <new string> in selected .cfg files

    Args:
        files (list(str)): .cfg files to replace strings in
        target (_type_): Target string to replace
        replace (_type_): String to replace target with
        reset (_type_): Instead of setting a new value, replace with an empty string
    """
    print("Apply filter: Update %s to %s" % (target, replace))
    commands = []
    for file in files:
        # sed -i '/I want to replace this/c\With  this' file.txt
        replace_str = '%s = "%s"' % (target, replace)
        if reset:
            replace_str = "%s =" % (target)

        # pylint: disable=anomalous-backslash-in-string
        filter_str = "'/%s/c\%s'" % (target, replace_str)
        # pylint: enable=anomalous-backslash-in-string

        commands.append("sed -i %s %s" % (filter_str, file))

    machine = m.Machine("", True)
    results = machine.process(None, commands, shell=True)

    stop = False
    for output, error in results:
        if output != []:
            print("[ERROR] OUTPUT: %s" % ("".join(output)))
            stop = True
        if error != []:
            print("[ERROR] ERROR: %s" % ("".join(error)))
            stop = True

    if stop:
        print("Detected an error, stop")
        sys.exit()


def main(args):
    """Replace all lines with <target string> with <new string> for all .cfg files

    Args:
        args (Namespace): Argparse namespace
    """
    # Get all .cfg files
    print("Gather a list of all .cfg files")
    files = get_files()

    # Edit particular config arguments
    if args.region or args.reset:
        update_files(files, "gcp_region", args.region, args.reset)

    if args.zone or args.reset:
        update_files(files, "gcp_zone", args.zone, args.reset)

    if args.pid or args.reset:
        update_files(files, "gcp_project", args.pid, args.reset)

    if args.cred or args.reset:
        update_files(files, "gcp_credentials", args.cred, args.reset)


if __name__ == "__main__":
    parser_obj = argparse.ArgumentParser()
    parser_obj.add_argument("--region", type=str, help="GCP Region (e.g., europe-west4)")
    parser_obj.add_argument("--zone", type=str, help="GCP ZONE (e.g., europe-west4-a)")
    parser_obj.add_argument(
        "--pid", type=str, help="GCP projectID (e.g., continuum-project-123456)"
    )
    parser_obj.add_argument(
        "--cred",
        type=str,
        help="GCP credentials file (e.g., ~/.ssh/continuum-project-123456-123a456bc78d.json)",
    )
    parser_obj.add_argument("--reset", action="store_true", help="Empty all parameter values")

    arguments = parser_obj.parse_args()

    main(arguments)
