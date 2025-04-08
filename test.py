def main():
    logs = get_log_entries()
    grouped = defaultdict(list)

    for log in logs:
        props = log["properties"]

        # ✅ PK 필드 예외 처리
        pk_field = props.get("PK", {}).get("title", [])
        if not pk_field:
            continue  # PK 필드가 비었으면 스킵

        pk_text = pk_field[0].get("plain_text", "")
        name, date = parse_name_date(pk_text)
        if not name or not date:
            continue  # 이름 또는 날짜 추출 실패 → 스킵

        grouped[(name, date)].append(log)
