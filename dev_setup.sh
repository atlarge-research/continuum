#!/bin/bash

cat <<EOF > .git/hooks/pre-commit
#!/bin/sh

# Check python
for i in $(find ./ -type f -name "*.py"); do
    pylint --rcfile=./sysconfig/pylintrc
done

black ./

# Check Ansible YAML files
yamllint --strict --config-data "{extends: default, rules: {line-length: {max: 100}}}" ./
ansible-lint --profile production --strict
EOF

chmod +x .git/hooks/pre-commit
