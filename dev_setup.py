import os
import stat


def main():
    """Create a pre-commit hook for this repo, which runs code linters and formatters automatically before commits"""
    content = """\
#!/bin/sh

# Check python
for i in $(find ./ -type f -name "*.py"); do
    pylint --rcfile=./sysconfig/pylintrc $i
done

black ./

# Check Ansible YAML files
yamllint --strict --config-data "{extends: default, rules: {line-length: {max: 100}}}" ./
ansible-lint --profile production --strict"""

    target = ".git/hooks/pre-commit"
    f = open(target, mode="w")
    f.write(content)
    f.close()

    st = os.stat(target)
    os.chmod(target, st.st_mode | stat.S_IEXEC)


if __name__ == "__main__":
    main()
