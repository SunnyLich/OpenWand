"""Exact Writer/Impress text Rewrite through LibreOffice's bundled UNO runtime."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys

import uno  # type: ignore[import-not-found]


def _desktop(pipe_name: str = "", port: int = 0):
    local = uno.getComponentContext()
    resolver = local.ServiceManager.createInstanceWithContext(
        "com.sun.star.bridge.UnoUrlResolver",
        local,
    )
    if pipe_name:
        endpoint = f"uno:pipe,name={pipe_name};urp;StarOffice.ComponentContext"
    elif port > 0:
        endpoint = f"uno:socket,host=127.0.0.1,port={port};urp;StarOffice.ComponentContext"
    else:
        raise RuntimeError("No LibreOffice Rewrite endpoint was supplied.")
    context = resolver.resolve(endpoint)
    return context.ServiceManager.createInstanceWithContext(
        "com.sun.star.frame.Desktop",
        context,
    )


def _base_title(value: str) -> str:
    text = " ".join(str(value or "").split())
    return re.sub(
        r"\s+(?:\u2014|\u2013|-)\s+LibreOffice.*$",
        "",
        text,
        flags=re.IGNORECASE,
    ).casefold()


def _find_document(desktop, title: str, surface: str):
    service = {
        "writer": "com.sun.star.text.TextDocument",
        "impress": "com.sun.star.presentation.PresentationDocument",
    }[surface]
    expected = _base_title(title)
    matches = []
    enumeration = desktop.Components.createEnumeration()
    while enumeration.hasMoreElements():
        component = enumeration.nextElement()
        try:
            supported = bool(component.supportsService(service))
        except Exception:
            supported = False
        if supported and _base_title(getattr(component, "Title", "")) == expected:
            matches.append(component)
    if len(matches) != 1:
        raise RuntimeError(
            f"Expected one matching LibreOffice {surface.title()} document, found {len(matches)}."
        )
    return matches[0]


def _range_candidates(selection):
    if selection is None:
        return []
    if all(hasattr(selection, name) for name in ("getString", "getText", "getStart")):
        return [selection]
    candidates = []
    try:
        for index in range(int(selection.getCount())):
            item = selection.getByIndex(index)
            if all(hasattr(item, name) for name in ("getString", "getText", "getStart")):
                candidates.append(item)
    except Exception:
        pass
    return candidates


def _writer_containers(document):
    yield "body", "", document.Text
    try:
        frames = document.TextFrames
        for name in frames.getElementNames():
            frame = frames.getByName(name)
            yield "frame", str(name), frame.Text
    except Exception:
        pass
    try:
        tables = document.TextTables
        for table_name in tables.getElementNames():
            table = tables.getByName(table_name)
            for cell_name in table.getCellNames():
                yield "table_cell", f"{table_name}:{cell_name}", table.getCellByName(cell_name)
    except Exception:
        pass


def _shape_children(shape):
    try:
        for index in range(int(shape.getCount())):
            yield index, shape.getByIndex(index)
    except Exception:
        return


def _impress_shapes(document):
    pages = document.DrawPages
    for page_index in range(int(pages.getCount())):
        page = pages.getByIndex(page_index)
        for shape_index in range(int(page.getCount())):
            shape = page.getByIndex(shape_index)
            yield from _walk_shape(page_index, (shape_index,), shape)


def _walk_shape(page_index: int, path: tuple[int, ...], shape):
    try:
        _text_string(shape)
        shape.createTextCursor()
        yield page_index, path, shape
    except Exception:
        pass
    for child_index, child in _shape_children(shape):
        yield from _walk_shape(page_index, path + (child_index,), child)


def _same_uno(left, right) -> bool:
    try:
        return bool(left == right)
    except Exception:
        return False


def _offset_for_range(container, text_range) -> int:
    cursor = container.createTextCursor()
    cursor.gotoRange(text_range.getStart(), True)
    return len(str(cursor.getString() or ""))


def _text_string(container) -> str:
    try:
        return str(container.getString() or "")
    except Exception:
        return str(container.String or "")


def _writer_snapshot(document, selected_text: str) -> dict:
    ranges = _range_candidates(document.CurrentController.getSelection())
    if len(ranges) != 1:
        raise RuntimeError("Select one editable Writer text range before starting Rewrite.")
    text_range = ranges[0]
    actual = str(text_range.getString() or "")
    if not actual:
        raise RuntimeError("Writer returned an empty selected text range.")
    container = text_range.getText()
    matches = [
        (kind, name, candidate)
        for kind, name, candidate in _writer_containers(document)
        if _same_uno(candidate, container)
    ]
    if len(matches) != 1:
        raise RuntimeError("Writer did not expose one stable selected text container.")
    kind, name, candidate = matches[0]
    container_text = _text_string(candidate)
    start = _offset_for_range(candidate, text_range)
    if container_text[start : start + len(actual)] != actual:
        raise RuntimeError("Writer's selected range did not match its document container.")
    if selected_text and actual.strip() != str(selected_text).strip():
        raise RuntimeError("Writer's native selection changed while Rewrite was opening.")
    return _snapshot_payload(
        "writer",
        document,
        kind,
        name,
        0,
        (),
        start,
        actual,
        container_text,
    )


def _impress_snapshot(document, selected_text: str) -> dict:
    selection = document.CurrentController.getSelection()
    ranges = _range_candidates(selection)
    if len(ranges) == 1:
        text_range = ranges[0]
        actual = str(text_range.getString() or "")
        range_container = text_range.getText()
        matches = [
            (page, path, shape)
            for page, path, shape in _impress_shapes(document)
            if _same_uno(shape, range_container)
        ]
        if (
            actual
            and len(matches) == 1
            and (not selected_text or actual.strip() == str(selected_text).strip())
        ):
            page, path, shape = matches[0]
            container_text = _text_string(shape)
            start = _offset_for_range(shape, text_range)
            return _snapshot_payload(
                "impress",
                document,
                "shape",
                str(getattr(shape, "Name", "") or ""),
                page,
                path,
                start,
                actual,
                container_text,
            )

    wanted = str(selected_text or "")
    if not wanted:
        raise RuntimeError("Select editable text in one Impress shape before starting Rewrite.")
    matches = []
    seen = []
    for page, path, shape in _impress_shapes(document):
        text = _text_string(shape)
        seen.append((page, path, text[:80]))
        start = text.find(wanted)
        if start >= 0 and text.find(wanted, start + 1) < 0:
            matches.append((page, path, shape, start, text))
    if len(matches) != 1:
        raise RuntimeError(
            "Impress did not expose one unambiguous selected text shape "
            f"(matches={len(matches)}, text_shapes={seen[:12]!r})."
        )
    page, path, shape, start, container_text = matches[0]
    return _snapshot_payload(
        "impress",
        document,
        "shape",
        str(getattr(shape, "Name", "") or ""),
        page,
        path,
        start,
        wanted,
        container_text,
    )


def _snapshot_payload(
    surface,
    document,
    container_kind,
    container_name,
    page_index,
    shape_path,
    start,
    selected_text,
    container_text,
):
    payload = {
        "surface": surface,
        "document_title": str(getattr(document, "Title", "") or ""),
        "container_kind": container_kind,
        "container_name": container_name,
        "page_index": int(page_index),
        "shape_path": list(shape_path),
        "start": int(start),
        "length": len(selected_text),
        "selected_text": selected_text,
        "container_text": container_text,
    }
    payload["fingerprint"] = _fingerprint(payload)
    return payload


def _fingerprint(payload: dict) -> str:
    stable = {
        key: payload.get(key)
        for key in (
            "surface",
            "document_title",
            "container_kind",
            "container_name",
            "page_index",
            "shape_path",
            "start",
            "length",
            "selected_text",
            "container_text",
        )
    }
    return hashlib.sha256(
        json.dumps(stable, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def snapshot(pipe_name: str, surface: str, title: str, selected_text: str) -> dict:
    document = _find_document(_desktop(pipe_name), title, surface)
    if surface == "writer":
        return {"ok": True, "snapshot": _writer_snapshot(document, selected_text)}
    return {"ok": True, "snapshot": _impress_snapshot(document, selected_text)}


def _writer_container(document, kind: str, name: str):
    matches = [
        candidate
        for candidate_kind, candidate_name, candidate in _writer_containers(document)
        if candidate_kind == kind and candidate_name == name
    ]
    if len(matches) != 1:
        raise RuntimeError("The captured Writer text container is no longer present.")
    return matches[0]


def _shape_at_path(document, page_index: int, path):
    pages = document.DrawPages
    if not 0 <= int(page_index) < int(pages.getCount()):
        raise RuntimeError("The captured Impress slide is no longer present.")
    value = pages.getByIndex(int(page_index))
    for index in path:
        value = value.getByIndex(int(index))
    try:
        _text_string(value)
        value.createTextCursor()
    except Exception as exc:
        raise RuntimeError("The captured Impress shape is no longer editable text.") from exc
    return value


def apply(pipe_name: str, plan: dict, *, port: int = 0) -> dict:
    snapshot_value = dict(plan.get("snapshot") or {})
    replacement = str(plan.get("replacement_text") or "")
    if not replacement:
        raise RuntimeError("LibreOffice Rewrite requires a non-empty replacement.")
    surface = str(snapshot_value.get("surface") or "")
    document = _find_document(
        _desktop(pipe_name, port),
        str(snapshot_value.get("document_title") or ""),
        surface,
    )
    if _fingerprint(snapshot_value) != str(snapshot_value.get("fingerprint") or ""):
        raise RuntimeError("The LibreOffice Rewrite target fingerprint is invalid.")
    if surface == "writer":
        container = _writer_container(
            document,
            str(snapshot_value.get("container_kind") or ""),
            str(snapshot_value.get("container_name") or ""),
        )
    elif surface == "impress":
        container = _shape_at_path(
            document,
            int(snapshot_value.get("page_index") or 0),
            tuple(snapshot_value.get("shape_path") or ()),
        )
    else:
        raise RuntimeError("The LibreOffice Rewrite surface is unsupported.")

    before = _text_string(container)
    if before != str(snapshot_value.get("container_text") or ""):
        raise RuntimeError("LibreOffice changed after preview; the exact Rewrite target was not edited.")
    start = int(snapshot_value.get("start") or 0)
    length = int(snapshot_value.get("length") or 0)
    selected = str(snapshot_value.get("selected_text") or "")
    if before[start : start + length] != selected:
        raise RuntimeError("LibreOffice's selected range changed after preview.")
    manager = document.getUndoManager()
    context_open = False
    try:
        manager.enterUndoContext("Wisp: exact Rewrite")
        context_open = True
        cursor = container.createTextCursor()
        cursor.gotoStart(False)
        if start:
            cursor.goRight(start, False)
        cursor.goRight(length, True)
        if str(cursor.getString() or "") != selected:
            raise RuntimeError("LibreOffice could not rebind the exact selected range.")
        cursor.setString(replacement)
        manager.leaveUndoContext()
        context_open = False
        expected = before[:start] + replacement + before[start + length :]
        if _text_string(container) != expected:
            raise RuntimeError("LibreOffice did not verify the exact replacement.")
    except Exception:
        if context_open:
            manager.leaveUndoContext()
        if manager.isUndoPossible():
            manager.undo()
        raise
    return {"ok": True, "status": "applied", "verification": True}


def main() -> int:
    parser = argparse.ArgumentParser()
    endpoint = parser.add_mutually_exclusive_group(required=True)
    endpoint.add_argument("--pipe", default="")
    endpoint.add_argument("--port", type=int, default=0)
    parser.add_argument("--mode", choices=("snapshot", "apply"), required=True)
    parser.add_argument("--surface", choices=("writer", "impress"), default="writer")
    parser.add_argument("--title", default="")
    parser.add_argument("--selected-text", default="")
    parser.add_argument("--plan-json", default="{}")
    args = parser.parse_args()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    try:
        if args.mode == "snapshot":
            if args.port:
                document = _find_document(_desktop(port=args.port), args.title, args.surface)
                captured = (
                    _writer_snapshot(document, args.selected_text)
                    if args.surface == "writer"
                    else _impress_snapshot(document, args.selected_text)
                )
                result = {"ok": True, "snapshot": captured}
            else:
                result = snapshot(args.pipe, args.surface, args.title, args.selected_text)
        else:
            result = apply(args.pipe, json.loads(args.plan_json), port=args.port)
    except Exception as exc:
        result = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
    print(json.dumps(result, ensure_ascii=False), flush=True)
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
