import copy


def _format_weight(text, weight, model_hint=""):
    # V1: use A1111-like (text:1.2) convention.
    try:
        w = float(weight)
    except Exception:
        return text
    if abs(w - 1.0) < 1e-6:
        return text
    return f"({text}:{w:.3g})"


def _render_segments(store, segments, variables, model_hint="", trace=None):
    trace = trace if trace is not None else []
    out = []
    for seg in segments or []:
        if not isinstance(seg, dict):
            continue
        t = seg.get("type")
        if t in ("literal", "sep"):
            txt = seg.get("text") or ""
            out.append(str(txt))
            continue
        if t == "slot":
            name = seg.get("name") or ""
            val = variables.get(name, "")
            out.append(str(val))
            trace.append({"type": "slot", "name": name, "value": val})
            continue
        if t == "ref":
            ref = seg.get("id") or seg.get("ref")
            if not ref:
                continue
            try:
                frag = store.get_fragment(ref)
                txt = frag.get("text") or ""
            except Exception:
                txt = ""
            if not txt:
                trace.append({"type": "fragment_ref_unresolved", "ref": ref})
                continue
            weight = seg.get("weight", 1.0)
            txt2 = _format_weight(txt, weight, model_hint=model_hint)
            out.append(txt2)
            trace.append({"type": "fragment_ref", "ref": ref, "text": txt2})
            continue
        trace.append({"type": "unknown_segment", "segment": seg})
    return "".join(out)


def assemble_entry(store, entry, variables_override=None, model_hint=""):
    """
    Assemble a final positive/negative prompt from an entry.
    V1 implementation: prioritizes entry.raw, with optional variable override.
    """
    variables_override = variables_override or {}
    variables = copy.deepcopy(entry.get("variables") or {})
    for k, v in variables_override.items():
        variables[k] = v

    positive = ""
    negative = ""

    # Apply fragment refs if present
    trace = []

    # Template PromptIR base (optional)
    template_id = entry.get("template_id")
    if template_id:
        try:
            tpl = store.get_template(template_id)
            ir = tpl.get("ir") or {}
            if isinstance(ir, dict):
                positive = _render_segments(store, ir.get("segments"), variables, model_hint=model_hint, trace=trace).strip()
                negative = _render_segments(
                    store, ir.get("negative_segments"), variables, model_hint=model_hint, trace=trace
                ).strip()
                trace.append({"type": "template_applied", "template_id": template_id})
        except Exception as e:
            trace.append({"type": "template_error", "template_id": template_id, "error": str(e)})

    # Entry raw as append layer
    raw_pos = (entry.get("raw") or {}).get("positive", "") or ""
    raw_neg = (entry.get("raw") or {}).get("negative", "") or ""
    if raw_pos:
        positive = (positive + ", " + raw_pos).strip(", ")
    if raw_neg:
        negative = (negative + ", " + raw_neg).strip(", ")

    fragments = entry.get("fragments") or []
    for frag in fragments:
        # frag can be {"ref": "...", "weight": 1.2} or raw string.
        if isinstance(frag, str):
            positive = (positive + ", " + frag).strip(", ")
            trace.append({"type": "fragment_literal", "value": frag})
            continue
        if not isinstance(frag, dict):
            continue
        ref = frag.get("ref") or frag.get("id")
        if not ref:
            continue
        text = frag.get("text")
        if not text:
            try:
                db_frag = store.get_fragment(ref)
                text = db_frag.get("text") or ""
            except Exception:
                text = ""
        if not text:
            trace.append({"type": "fragment_ref_unresolved", "ref": ref})
            continue
        text2 = _format_weight(text, frag.get("weight", 1.0), model_hint=model_hint)
        positive = (positive + ", " + text2).strip(", ")
        trace.append({"type": "fragment_resolved", "ref": ref, "text": text2})

    for k, v in variables.items():
        placeholder = "{" + str(k) + "}"
        positive = positive.replace(placeholder, str(v))
        negative = negative.replace(placeholder, str(v))

    return {"positive": positive, "negative": negative, "trace": trace}
