"""Create a pre-commit hook for this repo,
which runs code linters and formatters automatically before commits"""

import os
import stat


def main():
    """Generate the content of the pre-commit file, and create the file"""
    content = """\
#!/bin/sh
echo "-------------------------------"
echo "Black"
echo "-------------------------------"
black --line-length 100 ./

echo "-------------------------------"
echo "Pylint"
echo "-------------------------------"
for i in $(find ./ -type f -name "*.py"); do
    pylint --rcfile=./sysconfig/pylintrc $i
done

echo "-------------------------------"
echo "Yamllint"
echo "-------------------------------"
yamllint --strict -c ./sysconfig/yamllint.yaml ./

echo "-------------------------------"
echo "Ansible-lint"
echo "-------------------------------"
ansible-lint --profile production --strict"""

    target = ".git/hooks/pre-commit"
    with open(target, mode="w", encoding="utf-8") as f:
        f.write(content)
        f.close()

    st = os.stat(target)
    os.chmod(target, st.st_mode | stat.S_IEXEC)


if __name__ == "__main__":
    main()
