"""User dispositions are saved separately from immutable model assessments."""
DECISIONS = {"待处理", "要求修改", "接受风险", "升级审批", "补充材料", "判断有误"}


def validate_feedback(body, source_hash):
    if body.get("source_hash") != source_hash:
        raise ValueError("报告版本已变化，请刷新后再保存反馈")
    decision, note = body.get("decision"), body.get("note", "")
    if decision not in DECISIONS or not isinstance(note, str) or len(note) > 1000:
        raise ValueError("请选择有效处置方式，备注最多 1000 字")
    if decision not in {"待处理", "要求修改"} and not note.strip():
        raise ValueError("请补充处置理由或需要补充的材料")
    if type(body.get("revision")) is not int or body["revision"] < 0:
        raise ValueError("反馈版本无效，请刷新后重试")
    return decision, note.strip()


def feedback_state(store, aid):
    rows = store.all("SELECT risk_id,decision,note,source_hash,created,revision FROM risk_feedback WHERE artifact_id=? ORDER BY revision", (aid,))
    result = {}
    for row in rows:
        previous = result.get(row["risk_id"], {})
        result[row["risk_id"]] = {**row, "history": previous.get("history", []) + ([{k:v for k,v in previous.items() if k != "history"}] if previous else [])}
    return result
