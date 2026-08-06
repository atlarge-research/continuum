"""Small helpers shared by Terraform configuration generators."""

from __future__ import annotations


def hcl_string_literal(value: str) -> str:
    """Return a Python string encoded as one quoted HCL string literal."""
    if not isinstance(value, str):
        raise TypeError("HCL string literal value must be a string")

    escaped = []
    for index, character in enumerate(value):
        if character == '"':
            escaped.append('\\"')
        elif character == "\\":
            escaped.append("\\\\")
        elif character == "\n":
            escaped.append("\\n")
        elif character == "\r":
            escaped.append("\\r")
        elif character == "\t":
            escaped.append("\\t")
        elif character == "$" and index + 1 < len(value) and value[index + 1] == "{":
            escaped.append("$$")
        elif character == "%" and index + 1 < len(value) and value[index + 1] == "{":
            escaped.append("%%")
        elif ord(character) < 0x20 or 0x7F <= ord(character) <= 0x9F:
            escaped.append("\\u%04x" % (ord(character),))
        else:
            escaped.append(character)

    return '"%s"' % ("".join(escaped),)
