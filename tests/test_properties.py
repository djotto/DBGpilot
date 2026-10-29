import base64
import json
import xml.etree.ElementTree as ET

from hypothesis import given, strategies as st
import pytest

from dbgpilot import ProtocolError
from dbgpilot.models import TypeMapping, parse_property
from .helpers import xml


@given(st.binary(max_size=4096))
def test_binary_and_text_strings_round_trip(data):
    node = xml("property", name="$data", fullname="$data", type="string", size=len(data), encoding="base64")
    node.text = base64.b64encode(data).decode()
    prop = parse_property(node)
    assert prop.raw_value == data
    if isinstance(prop.value, str):
        assert prop.value.encode("utf-8") == data
    else:
        assert prop.value == data
    assert not prop.value_truncated
    json.dumps(prop.to_dict(), allow_nan=False)


@given(st.integers(min_value=-(2 ** 512), max_value=2 ** 512))
def test_integer_values_are_integers(number):
    node = xml("property", name="$n", type="int")
    node.text = str(number)
    assert parse_property(node).value == number


@pytest.mark.parametrize("kind,text,expected", [
    ("bool", "1", True), ("bool", "0", False), ("null", "", None),
    ("uninitialized", "", None), ("float", "1.25", 1.25),
])
def test_scalar_types(kind, text, expected):
    node = xml("property", type=kind)
    node.text = text
    prop = parse_property(node)
    assert prop.value == expected
    assert prop.type == kind


def empty_property(kind, *, extended=False):
    node = xml("property", type=kind)
    if kind == "array":
        node.set("children", "0")
        node.set("numchildren", "0")
    else:
        node.set("size", "0")
    if extended:
        for field in ("name", "fullname"):
            child = xml(field, encoding="base64")
            child.text = base64.b64encode(b"$value").decode()
            node.append(child)
        if kind == "string":
            node.append(xml("value", encoding="base64"))
    else:
        node.set("name", "$value")
        node.set("fullname", "$value")
        if kind == "string":
            node.set("encoding", "base64")
    return node


@pytest.mark.parametrize("extended", [False, True], ids=["standard", "extended"])
@pytest.mark.parametrize("mapped", [False, True], ids=["no-typemap", "typemap"])
def test_empty_array_has_no_scalar_value_with_or_without_typemap(mapped, extended):
    mappings = {"array": TypeMapping("array", "hash")} if mapped else None
    prop = parse_property(empty_property("array", extended=extended), mappings)
    assert prop.type == "array"
    assert prop.name == prop.fullname == "$value"
    assert prop.common_type == ("hash" if mapped else None)
    assert prop.value is None
    assert prop.raw_value is None
    assert prop.children == () and prop.total_children == 0 and not prop.has_children
    assert prop.to_dict()["value"] is None


@pytest.mark.parametrize("extended", [False, True], ids=["standard", "extended"])
@pytest.mark.parametrize("mapped", [False, True], ids=["no-typemap", "typemap"])
def test_empty_string_remains_a_scalar_with_or_without_typemap(mapped, extended):
    mappings = {"string": TypeMapping("string", "string")} if mapped else None
    prop = parse_property(empty_property("string", extended=extended), mappings)
    assert prop.type == "string"
    assert prop.name == prop.fullname == "$value"
    assert prop.value == "" and prop.raw_value == b""
    assert prop.to_dict()["value"] == ""


def test_typemap_preserves_nested_empty_arrays_and_empty_strings():
    node = xml("property", type="array", children=1, numchildren=2)
    node.extend([empty_property("array"), empty_property("string")])
    prop = parse_property(node, {
        "array": TypeMapping("array", "hash"),
        "string": TypeMapping("string", "string"),
    })
    assert prop.value is None and prop.raw_value is None
    assert prop.has_children and prop.total_children == len(prop.children) == 2
    array, string = prop.children
    assert array.value is None and array.raw_value is None
    assert string.value == "" and string.raw_value == b""


@pytest.mark.parametrize("kind,text", [("int", "oops"), ("bool", "yes"), ("float", "oops")])
def test_malformed_scalars(kind, text):
    node = xml("property", type=kind)
    node.text = text
    with pytest.raises(ProtocolError):
        parse_property(node)


def test_extended_properties_names_classnames_and_binary_values():
    node = xml("property", type="object", children="1", numchildren="1")
    for name, value in [("name", b"$obj"), ("fullname", b"$obj"), ("classname", b"Example")]:
        child = ET.SubElement(node, name, encoding="base64")
        child.text = base64.b64encode(value).decode()
    prop = ET.SubElement(node, "property", type="string", size="2")
    for name, value in [("name", b"a\0b"), ("fullname", b'$obj["a\\0b"]'), ("value", b"\xff\0")]:
        child = ET.SubElement(prop, name, encoding="base64")
        child.text = base64.b64encode(value).decode()
    # All elements on the wire belong to the DBGp namespace.
    for child in node.iter():
        if not child.tag.startswith("{"):
            child.tag = "{urn:debugger_protocol_v1}" + child.tag
    parsed = parse_property(node)
    assert parsed.classname == "Example"
    assert parsed.type == "object"
    assert parsed.children[0].name == "a\0b"
    assert parsed.children[0].value == b"\xff\0"
    assert parsed.to_dict()["children"][0]["value"] == {"encoding": "base64", "data": "/wA="}


def test_truncation_and_paging_are_explicit():
    string = xml("property", type="string", size=100)
    string.text = "hello"
    assert parse_property(string).value_truncated
    array = xml("property", type="array", children=1, numchildren=50, page=1, pagesize=10)
    prop = parse_property(array)
    assert prop.children_truncated
    assert prop.total_children == 50
    assert prop.page == 1
    assert prop.page_size == 10


@pytest.mark.parametrize("text", ["INF", "-INF", "NAN"])
def test_nonfinite_numbers_have_json_safe_representation(text):
    node = xml("property", type="float")
    node.text = text
    json.dumps(parse_property(node).to_dict(), allow_nan=False)
