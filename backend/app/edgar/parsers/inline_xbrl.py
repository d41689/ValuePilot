from __future__ import annotations

from dataclasses import dataclass
from datetime import date
import hashlib
import json
import io
import re
from typing import Any
import xml.etree.ElementTree as ET
from xml.parsers import expat

from bs4 import BeautifulSoup, Tag

_TYPED_MAX_DEPTH = 32
_TYPED_MAX_NODES = 1024
_TYPED_MAX_ATTRIBUTES = 2048
_TYPED_MAX_TEXT_BYTES = 65536
_XBRLI_URI = "http://www.xbrl.org/2003/instance"
_XBRLDI_URI = "http://xbrl.org/2006/xbrldi"
_INLINE_URIS = {"http://www.xbrl.org/2013/inlineXBRL", "http://www.xbrl.org/2020/inlineXBRL"}
_PROTECTED_LOCALS = {
    "context", "unit", "entity", "segment", "scenario", "period", "forever", "instant", "startDate", "endDate", "identifier", "measure", "divide",
    "unitNumerator", "unitDenominator", "explicitMember", "typedMember",
    "nonFraction", "nonNumeric", "continuation", "hidden", "references",
}


def _expanded_name(value: str) -> tuple[str, str]:
    return tuple(value[1:].split("}", 1)) if value.startswith("{") else ("", value)


def _normalized_safe_xml_bytes(content: bytes) -> bytes:
    bom_encoding: str | None = None
    bom_label: str | None = None
    if content.startswith(b"\x00\x00\xfe\xff"):
        bom_encoding, bom_label = "utf-32", "utf-32be"
    elif content.startswith(b"\xff\xfe\x00\x00"):
        bom_encoding, bom_label = "utf-32", "utf-32le"
    elif content.startswith(b"\xff\xfe"):
        bom_encoding, bom_label = "utf-16", "utf-16le"
    elif content.startswith(b"\xfe\xff"):
        bom_encoding, bom_label = "utf-16", "utf-16be"
    if bom_label and bom_label.startswith("utf-32"):
        bom_encoding = "utf-32"
    try:
        lexical = content.decode(bom_encoding or "utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        raise ValueError("unsafe_xml_encoding") from exc
    declaration = re.match(r"^\ufeff?\s*<\?xml\s+[^?]*\?>", lexical, re.IGNORECASE)
    if declaration:
        encoding_match = re.search(r"\bencoding\s*=\s*(['\"])([^'\"]+)\1", declaration.group(0), re.IGNORECASE)
        if encoding_match and bom_encoding:
            declared = encoding_match.group(2).lower().replace("_", "-")
            if bom_encoding == "utf-16" and declared not in {"utf-16", "utf-16le", "utf-16be"}:
                raise ValueError("xml_encoding_bom_mismatch")
            if bom_encoding == "utf-32" and declared not in {"utf-32", "utf-32le", "utf-32be"}:
                raise ValueError("xml_encoding_bom_mismatch")
            if declared.endswith(("le", "be")) and declared != bom_label:
                raise ValueError("xml_encoding_bom_mismatch")
        if bom_encoding == "utf-32":
            token = declaration.group(0)
            if encoding_match:
                start, end = encoding_match.span(2)
                token = token[:start] + "UTF-8" + token[end:]
            lexical = token.lstrip("\ufeff") + lexical[declaration.end():]
    return lexical.encode("utf-8") if bom_encoding == "utf-32" else content


def safe_xml_preflight(content: bytes) -> tuple[tuple[str, str], bytes]:
    if len(content) > 20 * 1024 * 1024:
        raise ValueError("xml_resource_limit")
    parse_content = _normalized_safe_xml_bytes(content)
    elements = attrs = text_bytes = namespaces = depth = 0
    root_name: tuple[str, str] | None = None
    parser = expat.ParserCreate(namespace_separator="}")
    parser.SetParamEntityParsing(expat.XML_PARAM_ENTITY_PARSING_NEVER)

    def expanded(raw: str) -> tuple[str, str]:
        if "}" in raw:
            uri, local = raw.split("}", 1)
            return uri, local
        return "", raw
    def reject_declaration(*_args: Any) -> None:
        raise ValueError("unsafe_xml_declaration")
    def start_namespace(_prefix: str | None, _uri: str) -> None:
        nonlocal namespaces
        namespaces += 1
        if namespaces > 8192: raise ValueError("xml_resource_limit")
    def start(raw: str, attributes: dict[str, str]) -> None:
        nonlocal elements, attrs, depth, root_name
        elements += 1; attrs += len(attributes); depth += 1
        if root_name is None: root_name = expanded(raw)
        if elements > 200000 or attrs > 400000 or depth > 128:
            raise ValueError("xml_resource_limit")
    def end(_raw: str) -> None:
        nonlocal depth
        depth -= 1
    def text(value: str) -> None:
        nonlocal text_bytes
        text_bytes += len(value.encode("utf-8"))
        if text_bytes > 10 * 1024 * 1024: raise ValueError("xml_resource_limit")
    parser.StartNamespaceDeclHandler = start_namespace
    parser.StartElementHandler = start
    parser.EndElementHandler = end
    parser.CharacterDataHandler = text
    parser.StartDoctypeDeclHandler = reject_declaration
    parser.EntityDeclHandler = reject_declaration
    parser.ExternalEntityRefHandler = lambda *_args: 0
    try:
        for offset in range(0, len(parse_content), 65536):
            parser.Parse(parse_content[offset:offset + 65536], False)
        parser.Parse(b"", True)
    except expat.ExpatError as exc:
        raise ValueError("xml_parse_failed") from exc
    if root_name is None: raise ValueError("xml_parse_failed")
    return root_name, parse_content


def safe_xml_root_name(content: bytes) -> tuple[str, str]:
    return safe_xml_preflight(content)[0]


def _strict_inline_xml_signatures(content: bytes) -> tuple[list[tuple[str | None, str, str | None, str | None]], set[str], set[str]]:
    try:
        safe_xml_root_name(content)
    except ValueError as exc:
        raise ValueError("inline_xhtml_xml_authority_unavailable") from exc
    pending: list[tuple[str, str]] = []
    scopes: list[dict[str, str]] = [{}]
    facts: list[tuple[str | None, str, str | None, str | None]] = []
    contexts: set[str] = set(); units: set[str] = set()
    elements = attrs = text_bytes = 0
    try:
        iterator = ET.iterparse(io.BytesIO(content), events=("start-ns", "start", "end"))
        for event, value in iterator:
            if event == "start-ns":
                pending.append((value[0] or "", value[1]))
                if len(pending) + sum(len(item) for item in scopes) > 8192:
                    raise ValueError("inline_xhtml_resource_limit")
                continue
            if event == "start":
                elements += 1; attrs += len(value.attrib)
                if elements > 200000 or attrs > 400000 or len(scopes) > 128:
                    raise ValueError("inline_xhtml_resource_limit")
                scope = dict(scopes[-1]); scope.update(pending); pending.clear(); scopes.append(scope)
                uri, local = _expanded_name(value.tag)
                expected = (_XBRLI_URI if local in {"context", "unit", "entity", "segment", "scenario", "period", "forever", "instant", "startDate", "endDate", "identifier", "measure", "divide", "unitNumerator", "unitDenominator"}
                            else _XBRLDI_URI if local in {"explicitMember", "typedMember"}
                            else "inline" if local in {"nonFraction", "nonNumeric", "continuation", "hidden", "references"} else None)
                if local in _PROTECTED_LOCALS and not (uri == expected or expected == "inline" and uri in _INLINE_URIS):
                    raise ValueError("invalid_inline_xbrl_structural_namespace")
                if uri == _XBRLI_URI and local == "context":
                    identifier = value.get("id")
                    if not identifier or identifier in contexts: raise ValueError("duplicate_xbrl_context_id")
                    contexts.add(identifier)
                elif uri == _XBRLI_URI and local == "unit":
                    identifier = value.get("id")
                    if not identifier or identifier in units: raise ValueError("duplicate_xbrl_unit_id")
                    units.add(identifier)
                elif uri in _INLINE_URIS and local in {"nonFraction", "nonNumeric"}:
                    lexical = value.get("name")
                    if not lexical: raise ValueError("inline_xbrl_fact_missing_name")
                    prefix = lexical.split(":", 1)[0] if ":" in lexical else ""
                    taxonomy_uri = scope.get(prefix)
                    if not taxonomy_uri: raise ValueError("undeclared_concept_qname_prefix")
                    facts.append((value.get("id"), f"{{{taxonomy_uri}}}{lexical.split(':', 1)[-1]}", value.get("contextRef"), value.get("unitRef")))
            else:
                text_bytes += len((value.text or "").encode()) + len((value.tail or "").encode())
                if text_bytes > 10 * 1024 * 1024: raise ValueError("inline_xhtml_resource_limit")
                scopes.pop()
                value.clear()
    except ET.ParseError as exc:
        raise ValueError("inline_xhtml_xml_authority_unavailable") from exc
    return facts, contexts, units


@dataclass(frozen=True)
class ParsedInlineXbrlFact:
    concept: str
    concept_namespace_uri: str | None
    context_id: str | None
    unit_id: str | None
    unit_measure: str | None
    unit_numerator: tuple[dict[str, str | None], ...]
    unit_denominator: tuple[dict[str, str | None], ...]
    raw_value: str | None
    transformation_format: str | None
    language: str | None
    continued_at: str | None
    decimals: str | None
    scale: int | None
    sign: str | None
    is_nil: bool
    period_instant: date | None
    period_start: date | None
    period_end: date | None
    entity_identifier: str | None
    dimensions: dict[str, str]
    dimensions_structured: tuple[dict[str, Any], ...]
    locator: dict[str, Any]


def _local_name(tag: Tag) -> str:
    return str(tag.name or "").split(":")[-1].lower()


def _attr(tag: Tag, name: str) -> str | None:
    wanted = name.lower()
    for key, value in tag.attrs.items():
        if str(key).lower() == wanted:
            if isinstance(value, list):
                return " ".join(str(item) for item in value)
            return str(value)
    return None


def _first_descendant(tag: Tag, local_name: str) -> Tag | None:
    return tag.find(lambda item: isinstance(item, Tag) and _local_name(item) == local_name)


def _date_text(tag: Tag | None) -> date | None:
    if tag is None:
        return None
    try:
        return date.fromisoformat(tag.get_text(strip=True))
    except ValueError:
        return None


def _namespace_map_for_tag(tag: Tag) -> dict[str, str]:
    ancestors = [item for item in tag.parents if isinstance(item, Tag)]
    namespaces: dict[str, str] = {}
    for item in [*reversed(ancestors), tag]:
        for key, value in item.attrs.items():
            raw_key = str(key).lower()
            if raw_key == "xmlns":
                namespaces[""] = str(value)
            elif raw_key.startswith("xmlns:"):
                namespaces[raw_key.split(":", 1)[1]] = str(value)
    return namespaces


def _typed_node_from_tag(tag: Tag, *, depth: int = 0) -> dict[str, Any]:
    if depth > 32:
        raise ValueError("typed_dimension_resource_limit")
    namespaces = _namespace_map_for_tag(tag)
    name = _qname(_attr(tag, "name") or str(tag.name), namespaces)
    attributes = []
    for raw_name, raw_value in tag.attrs.items():
        lexical = str(raw_name)
        if lexical == "xmlns" or lexical.startswith("xmlns:"):
            continue
        attributes.append({"name": _qname(lexical, namespaces), "value": str(raw_value)})
    children = [_typed_node_from_tag(child, depth=depth + 1) for child in tag.children if isinstance(child, Tag)]
    if len(children) > 256 or len(attributes) > 64:
        raise ValueError("typed_dimension_resource_limit")
    return {"name": name, "attributes": attributes, "text": str(tag.string) if tag.string and not children else "", "tail": "", "children": children}


def _typed_payload(structure: dict[str, Any]) -> tuple[str, str]:
    canonical = json.dumps(structure, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    if len(canonical.encode()) > 65536:
        raise ValueError("typed_dimension_resource_limit")
    return canonical, hashlib.sha256(canonical.encode()).hexdigest()


def _inline_xml_typed_authority(content: bytes) -> dict[str, tuple[dict[str, Any], ...]]:
    pending: list[tuple[str, str]] = []
    stack: list[dict[str, str]] = [{}]
    scopes: dict[int, dict[str, str]] = {}
    budget = {"nodes": 0, "attributes": 0, "bytes": 0}
    def qname(value: str, scope: dict[str, str]) -> dict[str, str | None]:
        if value.startswith("{"):
            uri, local = value[1:].split("}", 1)
            prefix = next((key or None for key, candidate in scope.items() if candidate == uri), None)
            return {"namespace_uri": uri, "local_name": local, "prefix": prefix}
        result = _qname(value, scope)
        if not result["namespace_uri"]:
            raise ValueError("undeclared_dimension_qname_prefix")
        return result
    def node(element: ET.Element, depth: int = 0) -> dict[str, Any]:
        budget["nodes"] += 1; budget["attributes"] += len(element.attrib)
        budget["bytes"] += len((element.text or "").encode()) + len((element.tail or "").encode())
        budget["bytes"] += sum(len(value.encode()) for value in element.attrib.values())
        if (depth > _TYPED_MAX_DEPTH or budget["nodes"] > _TYPED_MAX_NODES
                or budget["attributes"] > _TYPED_MAX_ATTRIBUTES
                or budget["bytes"] > _TYPED_MAX_TEXT_BYTES):
            raise ValueError("typed_dimension_resource_limit")
        scope = scopes[id(element)]
        return {"name": qname(element.tag, scope), "attributes": [
            {"name": qname(name, scope) if name.startswith("{") else {
                "namespace_uri": None, "local_name": name, "prefix": None}, "value": value}
            for name, value in element.attrib.items()
        ], "text": element.text or "", "tail": element.tail or "",
            "children": [node(child, depth + 1) for child in element]}

    result_lists: dict[str, list[dict[str, Any]]] = {}
    context_stack: list[str | None] = [None]
    typed_depth = 0
    try:
        for event, value in ET.iterparse(io.BytesIO(content), events=("start-ns", "start", "end")):
            if event == "start-ns":
                pending.append((value[0] or "", value[1])); continue
            if event == "start":
                scope = dict(stack[-1]); scope.update(pending); pending.clear(); stack.append(scope)
                uri, local = _expanded_name(value.tag)
                current_context = value.get("id") if uri == _XBRLI_URI and local == "context" else context_stack[-1]
                context_stack.append(current_context)
                if uri == _XBRLDI_URI and local == "typedMember": typed_depth = 1
                elif typed_depth: typed_depth += 1
                if typed_depth: scopes[id(value)] = scope
                continue
            uri, local = _expanded_name(value.tag)
            if uri == _XBRLDI_URI and local == "typedMember":
                children = list(value)
                if len(children) != 1 or not context_stack[-1]:
                    raise ValueError("invalid_typed_dimension_structure")
                axis = qname(value.get("dimension", ""), scopes[id(value)])
                structure = node(children[0]); canonical, digest = _typed_payload(structure)
                result_lists.setdefault(context_stack[-1] or "", []).append({
                    "kind": "typed", "axis": axis, "typed_child": structure["name"],
                    "typed_structure": structure, "typed_canonical": canonical,
                    "typed_content_sha256": digest})
                for descendant in value.iter(): scopes.pop(id(descendant), None)
                typed_depth = 0; value.clear()
            elif typed_depth:
                typed_depth -= 1
            else:
                value.clear()
            stack.pop(); context_stack.pop()
    except ET.ParseError as exc:
        raise ValueError("inline_typed_dimension_xml_authority_unavailable") from exc
    return {key: tuple(value) for key, value in result_lists.items()}


def _context_map(soup: BeautifulSoup, *, strict: bool) -> dict[str, dict[str, Any]]:
    contexts: dict[str, dict[str, Any]] = {}
    for context in soup.find_all(lambda item: isinstance(item, Tag) and _local_name(item) == "context"):
        context_id = _attr(context, "id")
        if not context_id:
            continue
        if strict and context_id in contexts:
            raise ValueError("duplicate_xbrl_context_id")
        dimensions: dict[str, str] = {}
        structured_dimensions: list[dict[str, Any]] = []
        for member in context.find_all(
            lambda item: isinstance(item, Tag)
            and _local_name(item) in {"explicitmember", "typedmember"}
        ):
            dimension = _attr(member, "dimension")
            if dimension:
                namespaces = _namespace_map_for_tag(member)
                axis = _qname(dimension, namespaces)
                if strict and not axis["namespace_uri"]:
                    raise ValueError("undeclared_dimension_qname_prefix")
                dimensions[dimension] = member.get_text(" ", strip=True)
                if _local_name(member) == "explicitmember":
                    member_qname = _qname(member.get_text(strip=True), namespaces)
                    if strict and not member_qname["namespace_uri"]:
                        raise ValueError("undeclared_member_qname_prefix")
                    structured_dimensions.append(
                        {"kind": "explicit", "axis": axis, "member": member_qname}
                    )
                else:
                    child_tags = [child for child in member.children if isinstance(child, Tag)]
                    if strict and len(child_tags) != 1:
                        raise ValueError("invalid_typed_dimension_structure")
                    if child_tags:
                        child = child_tags[0]
                        child_name = _attr(child, "name") or str(child.name)
                        child_qname = _qname(child_name, _namespace_map_for_tag(child))
                        typed_structure = _typed_node_from_tag(child)
                        typed_canonical, typed_digest = _typed_payload(typed_structure)
                        structured_dimensions.append(
                            {
                                "kind": "typed",
                                "axis": axis,
                                "typed_child": child_qname,
                                "typed_structure": typed_structure,
                                "typed_canonical": typed_canonical,
                                "typed_content_sha256": typed_digest,
                            }
                        )
        contexts[context_id] = {
            "period_instant": _date_text(_first_descendant(context, "instant")),
            "period_start": _date_text(_first_descendant(context, "startdate")),
            "period_end": _date_text(_first_descendant(context, "enddate")),
            "entity_identifier": (
                _first_descendant(context, "identifier").get_text(strip=True)
                if _first_descendant(context, "identifier")
                else None
            ),
            "dimensions": dimensions,
            "dimensions_structured": tuple(structured_dimensions),
        }
    return contexts


def _qname(value: str, namespaces: dict[str, str]) -> dict[str, str | None]:
    prefix, local_name = value.split(":", 1) if ":" in value else (None, value)
    return {
        "namespace_uri": namespaces.get(prefix.lower()) if prefix else namespaces.get(""),
        "local_name": local_name,
        "prefix": prefix,
    }


def _unit_map(
    soup: BeautifulSoup, *, strict: bool
) -> dict[
    str,
    tuple[
        str,
        tuple[dict[str, str | None], ...],
        tuple[dict[str, str | None], ...],
    ],
]:
    units = {}
    for unit in soup.find_all(lambda item: isinstance(item, Tag) and _local_name(item) == "unit"):
        unit_id = _attr(unit, "id")
        if not unit_id:
            continue
        if strict and unit_id in units:
            raise ValueError("duplicate_xbrl_unit_id")

        def measures_within(container: Tag | None) -> list[str]:
            if container is None:
                return []
            return [
                measure.get_text(strip=True)
                for measure in container.find_all(
                    lambda item: isinstance(item, Tag) and _local_name(item) == "measure"
                )
            ]

        divide = _first_descendant(unit, "divide")
        if divide is not None:
            numerator = measures_within(_first_descendant(divide, "unitnumerator"))
            denominator = measures_within(_first_descendant(divide, "unitdenominator"))
            if numerator and denominator:
                units[unit_id] = (
                    f"{'*'.join(numerator)}/{'*'.join(denominator)}",
                    tuple(_qname(value, _namespace_map_for_tag(measure)) for value, measure in zip(numerator, _first_descendant(divide, "unitnumerator").find_all(lambda item: isinstance(item, Tag) and _local_name(item) == "measure"))),
                    tuple(_qname(value, _namespace_map_for_tag(measure)) for value, measure in zip(denominator, _first_descendant(divide, "unitdenominator").find_all(lambda item: isinstance(item, Tag) and _local_name(item) == "measure"))),
                )
                continue
            if strict:
                raise ValueError("invalid_xbrl_divide_unit")
        measures = measures_within(unit)
        measure_tags = unit.find_all(
            lambda item: isinstance(item, Tag) and _local_name(item) == "measure"
        )
        qnames = tuple(
            _qname(value, _namespace_map_for_tag(measure))
            for value, measure in zip(measures, measure_tags)
        )
        if strict and any(not item["namespace_uri"] for item in qnames):
            raise ValueError("undeclared_unit_qname_prefix")
        units[unit_id] = ("*".join(measures) if measures else unit_id, qnames, ())
    return units


def _namespace_map(soup: BeautifulSoup) -> dict[str, str]:
    namespaces: dict[str, str] = {}
    root = soup.find("html")
    if root is None:
        return namespaces
    for key, value in root.attrs.items():
        raw_key = str(key).lower()
        if raw_key.startswith("xmlns:"):
            namespaces[raw_key.split(":", 1)[1]] = str(value)
    return namespaces


def parse_inline_xbrl(
    content: bytes, *, artifact_id: int, strict: bool = False
) -> list[ParsedInlineXbrlFact]:
    xml_fact_signatures: list[tuple[str | None, str, str | None, str | None]] = []
    xml_context_ids: set[str] = set()
    xml_unit_ids: set[str] = set()
    if strict:
        _, content = safe_xml_preflight(content)
        xml_fact_signatures, xml_context_ids, xml_unit_ids = _strict_inline_xml_signatures(content)
    soup = BeautifulSoup(content, "html.parser")
    contexts = _context_map(soup, strict=strict)
    if strict and (set(contexts) != xml_context_ids):
        raise ValueError("inline_xhtml_context_authority_mismatch")
    if strict:
        typed_context_ids: set[str] = set()
        for member in soup.find_all(lambda item: isinstance(item, Tag) and _local_name(item) == "typedmember"):
            owner = member.find_parent(lambda item: isinstance(item, Tag) and _local_name(item) == "context")
            if owner is None or not _attr(owner, "id"):
                raise ValueError("inline_typed_dimension_xml_authority_mismatch")
            typed_context_ids.add(_attr(owner, "id") or "")
        if typed_context_ids:
            xml_typed = _inline_xml_typed_authority(content)
            if set(xml_typed) != typed_context_ids:
                raise ValueError("inline_typed_dimension_xml_authority_mismatch")
            for context_id in typed_context_ids:
                existing = contexts.get(context_id or "")
                if existing is None:
                    raise ValueError("inline_typed_dimension_xml_authority_mismatch")
                explicit = tuple(item for item in existing["dimensions_structured"] if item["kind"] == "explicit")
                existing["dimensions_structured"] = explicit + xml_typed[context_id or ""]
    units = _unit_map(soup, strict=strict)
    if strict and set(units) != xml_unit_ids:
        raise ValueError("inline_xhtml_unit_authority_mismatch")
    results: list[ParsedInlineXbrlFact] = []
    html_facts = soup.find_all(
            lambda item: isinstance(item, Tag)
            and _local_name(item) in {"nonfraction", "nonnumeric"}
        )
    if strict:
        html_signatures = []
        for fact in html_facts:
            concept = _attr(fact, "name") or ""
            namespace = _namespace_map_for_tag(fact).get(concept.split(":", 1)[0].lower() if ":" in concept else "")
            html_signatures.append((_attr(fact, "id"), f"{{{namespace}}}{concept.split(':', 1)[-1]}", _attr(fact, "contextref"), _attr(fact, "unitref")))
        if html_signatures != xml_fact_signatures:
            raise ValueError("inline_xhtml_fact_authority_mismatch")
    for ordinal, fact in enumerate(html_facts, start=1):
        concept = _attr(fact, "name")
        if not concept:
            continue
        context_id = _attr(fact, "contextref")
        context = contexts.get(context_id or "", {})
        if strict and not context:
            raise ValueError("unknown_xbrl_context_ref")
        unit_id = _attr(fact, "unitref")
        if strict and unit_id is not None and unit_id not in units:
            raise ValueError("unknown_xbrl_unit_ref")
        concept_namespaces = _namespace_map_for_tag(fact)
        concept_namespace = (
            concept_namespaces.get(concept.split(":", 1)[0].lower())
            if ":" in concept
            else concept_namespaces.get("")
        )
        if strict and not concept_namespace:
            raise ValueError("undeclared_concept_qname_prefix")
        raw_value = fact.get_text(" ", strip=True) or None
        nearby = fact.parent.get_text(" ", strip=True)[:500] if fact.parent else (raw_value or "")
        scale_raw = _attr(fact, "scale")
        try:
            scale = int(scale_raw) if scale_raw is not None else None
        except ValueError:
            scale = None
        nil_raw = (_attr(fact, "xsi:nil") or _attr(fact, "nil") or "").lower()
        element_id = _attr(fact, "id")
        is_hidden = fact.find_parent(
            lambda item: isinstance(item, Tag)
            and _local_name(item) == "hidden"
        ) is not None
        locator = {
            "artifact_id": artifact_id,
            "element_id": element_id,
            "dom_ordinal": ordinal,
            "locator_type": "inline_xbrl_html",
            "nearby_text_snippet": nearby,
            "nearby_text_sha256": hashlib.sha256(nearby.encode("utf-8")).hexdigest(),
            "is_hidden": is_hidden,
        }
        results.append(
            ParsedInlineXbrlFact(
                concept=concept,
                concept_namespace_uri=concept_namespace,
                context_id=context_id,
                unit_id=unit_id,
                unit_measure=(units.get(unit_id or "") or (None, (), ()))[0],
                unit_numerator=(units.get(unit_id or "") or (None, (), ()))[1],
                unit_denominator=(units.get(unit_id or "") or (None, (), ()))[2],
                raw_value=raw_value,
                transformation_format=_attr(fact, "format"),
                language=_attr(fact, "xml:lang") or _attr(fact, "lang"),
                continued_at=_attr(fact, "continuedat"),
                decimals=_attr(fact, "decimals"),
                scale=scale,
                sign=_attr(fact, "sign"),
                is_nil=nil_raw in {"true", "1"},
                period_instant=context.get("period_instant"),
                period_start=context.get("period_start"),
                period_end=context.get("period_end"),
                entity_identifier=context.get("entity_identifier"),
                dimensions=dict(context.get("dimensions") or {}),
                dimensions_structured=tuple(
                    context.get("dimensions_structured") or ()
                ),
                locator=locator,
            )
        )
    return results


def parse_standalone_xbrl(content: bytes, *, artifact_id: int) -> list[ParsedInlineXbrlFact]:
    root_name, content = safe_xml_preflight(content)
    if root_name != (_XBRLI_URI, "xbrl"):
        raise ValueError("standalone_xbrl_root_required")
    pending_namespaces: list[tuple[str, str]] = []
    namespace_stack: list[dict[str, str]] = [{}]
    element_namespaces: dict[int, dict[str, str]] = {}
    iterator = ET.iterparse(
        io.BytesIO(content), events=("start-ns", "start", "end")
    )
    for event, value in iterator:
        if event == "start-ns":
            prefix, uri = value
            pending_namespaces.append((prefix or "", uri))
        elif event == "start":
            in_scope = dict(namespace_stack[-1])
            in_scope.update(pending_namespaces)
            pending_namespaces.clear()
            namespace_stack.append(in_scope)
            element_namespaces[id(value)] = in_scope
        else:
            namespace_stack.pop()
    root = iterator.root
    xbrli = "http://www.xbrl.org/2003/instance"
    xsi = "http://www.w3.org/2001/XMLSchema-instance"

    def lexical_name(element: ET.Element) -> tuple[str, str]:
        tag = element.tag
        uri, local = tag[1:].split("}", 1) if tag.startswith("{") else ("", tag)
        reverse = {
            namespace_uri: prefix
            for prefix, namespace_uri in element_namespaces[id(element)].items()
        }
        prefix = reverse.get(uri)
        return (f"{prefix}:{local}" if prefix else local, uri)

    typed_budget = {"nodes": 0, "attributes": 0, "bytes": 0}
    contexts: dict[str, dict[str, Any]] = {}
    for context in root.findall(f".//{{{xbrli}}}context"):
        context_id = context.get("id")
        if not context_id:
            continue
        if context_id in contexts:
            raise ValueError("duplicate_xbrl_context_id")
        dimensions: dict[str, str] = {}
        structured_dimensions: list[dict[str, Any]] = []
        for member in context.iter():
            member_uri, member_local = _expanded_name(member.tag)
            if member_local in {"explicitMember", "typedMember"} and member_uri != _XBRLDI_URI:
                raise ValueError("invalid_xbrldi_structural_namespace")
            if member_uri == _XBRLDI_URI and member_local in {"explicitMember", "typedMember"}:
                if member.get("dimension"):
                    dimension_qname = _qname(
                        member.get("dimension", ""), element_namespaces[id(member)]
                    )
                    if not dimension_qname["namespace_uri"]:
                        raise ValueError("undeclared_dimension_qname_prefix")
                    if member_local == "explicitMember":
                        member_qname = _qname(
                            " ".join(member.itertext()).strip(),
                            element_namespaces[id(member)],
                        )
                        if not member_qname["namespace_uri"]:
                            raise ValueError("undeclared_member_qname_prefix")
                        structured_dimensions.append(
                            {"kind": "explicit", "axis": dimension_qname, "member": member_qname}
                        )
                    else:
                        typed_children = list(member)
                        if len(typed_children) != 1:
                            raise ValueError("invalid_typed_dimension_structure")
                        typed_child = typed_children[0]
                        typed_name, typed_uri = lexical_name(typed_child)
                        def typed_node(element: ElementTree.Element, depth: int = 0) -> dict[str, Any]:
                            typed_budget["nodes"] += 1
                            typed_budget["attributes"] += len(element.attrib)
                            typed_budget["bytes"] += len((element.text or "").encode()) + len((element.tail or "").encode())
                            typed_budget["bytes"] += sum(len(value.encode()) for value in element.attrib.values())
                            if (depth > _TYPED_MAX_DEPTH or typed_budget["nodes"] > _TYPED_MAX_NODES
                                    or typed_budget["attributes"] > _TYPED_MAX_ATTRIBUTES
                                    or typed_budget["bytes"] > _TYPED_MAX_TEXT_BYTES
                                    or len(list(element)) > 256 or len(element.attrib) > 64):
                                raise ValueError("typed_dimension_resource_limit")
                            def expanded(value: str) -> dict[str, str | None]:
                                if value.startswith("{"):
                                    uri, local = value[1:].split("}", 1)
                                    return {"namespace_uri": uri, "local_name": local, "prefix": None}
                                return _qname(value, element_namespaces[id(element)])
                            return {
                                "name": expanded(element.tag),
                                "attributes": [
                                    {"name": expanded(name), "value": value}
                                    for name, value in element.attrib.items()
                                ],
                                "text": element.text or "",
                                "tail": element.tail or "",
                                "children": [typed_node(child, depth + 1) for child in element],
                            }
                        typed_structure = typed_node(typed_child)
                        typed_canonical, typed_digest = _typed_payload(typed_structure)
                        structured_dimensions.append(
                            {
                                "kind": "typed",
                                "axis": dimension_qname,
                                "typed_child": {
                                    "namespace_uri": typed_uri,
                                    "local_name": typed_name.split(":", 1)[-1],
                                    "prefix": typed_name.split(":", 1)[0] if ":" in typed_name else None,
                                },
                                "typed_structure": typed_structure,
                                "typed_canonical": typed_canonical,
                                "typed_content_sha256": typed_digest,
                            }
                        )
                    dimensions[member.get("dimension", "")] = " ".join(member.itertext()).strip()
        def parsed_date(name: str) -> date | None:
            node = context.find(f".//{{{xbrli}}}{name}")
            try:
                return date.fromisoformat((node.text or "").strip()) if node is not None else None
            except ValueError:
                return None
        identifier = context.find(f".//{{{xbrli}}}identifier")
        contexts[context_id] = {
            "period_instant": parsed_date("instant"),
            "period_start": parsed_date("startDate"),
            "period_end": parsed_date("endDate"),
            "entity_identifier": (
                (identifier.text or "").strip() if identifier is not None else None
            ),
            "dimensions": dimensions,
            "dimensions_structured": tuple(structured_dimensions),
        }

    units = {}
    for unit in root.findall(f".//{{{xbrli}}}unit"):
        unit_id = unit.get("id")
        if not unit_id:
            continue
        if unit_id in units:
            raise ValueError("duplicate_xbrl_unit_id")
        numerator_node = unit.find(f".//{{{xbrli}}}unitNumerator")
        denominator_node = unit.find(f".//{{{xbrli}}}unitDenominator")
        def measures(node: ET.Element | None) -> list[str]:
            return [(item.text or "").strip() for item in (node.findall(f".//{{{xbrli}}}measure") if node is not None else [])]
        divide = unit.find(f".//{{{xbrli}}}divide")
        numerator = measures(numerator_node) if numerator_node is not None else measures(unit)
        denominator = measures(denominator_node)
        if divide is not None and (not numerator or not denominator):
            raise ValueError("invalid_xbrl_divide_unit")
        if divide is None and denominator:
            raise ValueError("invalid_xbrl_divide_unit")
        measure_elements = (
            list(numerator_node.findall(f".//{{{xbrli}}}measure"))
            if numerator_node is not None
            else list(unit.findall(f".//{{{xbrli}}}measure"))
        )
        denominator_elements = (
            list(denominator_node.findall(f".//{{{xbrli}}}measure"))
            if denominator_node is not None
            else []
        )
        numerator_qnames = tuple(
            _qname(value, element_namespaces[id(element)])
            for value, element in zip(numerator, measure_elements)
        )
        denominator_qnames = tuple(
            _qname(value, element_namespaces[id(element)])
            for value, element in zip(denominator, denominator_elements)
        )
        if any(not item["namespace_uri"] for item in (*numerator_qnames, *denominator_qnames)):
            raise ValueError("undeclared_unit_qname_prefix")
        display = "*".join(numerator) + (("/" + "*".join(denominator)) if denominator else "")
        units[unit_id] = (display, numerator_qnames, denominator_qnames)

    structural_uris = {xbrli, "http://xbrl.org/2006/xbrldi", "http://www.xbrl.org/2003/linkbase"}
    results = []
    for element in root.iter():
        context_id = element.get("contextRef")
        concept, namespace_uri = lexical_name(element)
        if not context_id or namespace_uri in structural_uris:
            continue
        context = contexts.get(context_id, {})
        if not context:
            raise ValueError("unknown_xbrl_context_ref")
        unit_id = element.get("unitRef")
        if unit_id is not None and unit_id not in units:
            raise ValueError("unknown_xbrl_unit_ref")
        unit = units.get(unit_id or "", (None, (), ()))
        raw_value = " ".join(element.itertext()).strip() or None
        ordinal = len(results) + 1
        nearby = raw_value or ""
        results.append(
            ParsedInlineXbrlFact(
                concept=concept,
                concept_namespace_uri=namespace_uri or None,
                context_id=context_id,
                unit_id=unit_id,
                unit_measure=unit[0],
                unit_numerator=unit[1],
                unit_denominator=unit[2],
                raw_value=raw_value,
                transformation_format=None,
                language=element.get("{http://www.w3.org/XML/1998/namespace}lang"),
                continued_at=None,
                decimals=element.get("decimals"),
                scale=(
                    int(element.get("scale"))
                    if (element.get("scale") or "").lstrip("-").isdigit()
                    else None
                ),
                sign=element.get("sign"),
                is_nil=(element.get(f"{{{xsi}}}nil") or "").lower()
                in {"true", "1"},
                period_instant=context.get("period_instant"),
                period_start=context.get("period_start"),
                period_end=context.get("period_end"),
                entity_identifier=context.get("entity_identifier"),
                dimensions=dict(context.get("dimensions") or {}),
                dimensions_structured=tuple(
                    context.get("dimensions_structured") or ()
                ),
                locator={
                    "artifact_id": artifact_id,
                    "element_id": element.get("id"),
                    "xml_ordinal": ordinal,
                    "locator_type": "standalone_xbrl_xml",
                    "nearby_text_snippet": nearby[:500],
                    "nearby_text_sha256": hashlib.sha256(
                        nearby[:500].encode()
                    ).hexdigest(),
                },
            )
        )
    return results
