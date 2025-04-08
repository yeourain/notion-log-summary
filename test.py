from notion_client import Client
from collections import defaultdict
import os

# ✅ 환경변수에서 Notion 정보 가져오기
NOTION_TOKEN = os.environ["NOTION_TOKEN"]
LOG_DB_ID = os.environ["LOG_DB_ID"]
SUMMARY_DB_ID = os.environ["SUMMARY_DB_ID"]

notion = Client(auth=NOTION_TOKEN)

# ✅ 긴 텍스트를 2000자 이하로 잘라주는 함수
def split_long_text(text, max_length=2000):
    return [text[i:i+max_length] for i in range(0, len(text), max_length)]

# ✅ 모든 Log 레코드 가져오기
def get_log_entries():
    results = []
    cursor = None
    while True:
        response = notion.databases.query(database_id=LOG_DB_ID, start_cursor=cursor)
        results.extend(response["results"])
        if not response.get("has_more"):
            break
        cursor = response["next_cursor"]
    return results

# ✅ Summary에 이미 존재하는 (이름+날짜) 확인
def find_existing_summary(name, date):
    res = notion.databases.query(
        database_id=SUMMARY_DB_ID,
        filter={
            "and": [
                {"property": "이름", "title": {"equals": name}},
                {"property": "날짜", "date": {"equals": date}}
            ]
        }
    )
    return res["results"][0] if res["results"] else None

# ✅ 메인 실행 함수
def main():
    logs = get_log_entries()
    grouped = defaultdict(list)

    for log in logs:
        props = log["properties"]

        # 필수 필드 확인
        name_field = props.get("PK", {}).get("title", [])
        date_field = props.get("날짜", {}).get("date", {})

        if not name_field or not date_field:
            continue  # 이름 or 날짜가 없으면 스킵

        name = name_field[0]["plain_text"]
        date = date_field.get("start")
        if not name or not date:
            continue

        grouped[(name, date)].append(log)

    # ✅ 그룹별 Summary 생성 또는 업데이트
    for (name, date), entries in grouped.items():
        total_hours = 0
        project_list = set()
        task_summary = []

        for e in entries:
            p = e["properties"]
            
            # 🔒 근무시간: None 처리
            hour = p.get("근무시간", {}).get("number")
            total_hours += hour if hour else 0

            # ✅ [여기!] 총합 시간 제한 (8시간 초과시 자름)
            total_hours = min(total_hours, 8)

            # 프로젝트명
            proj = p.get("프로젝트명", {}).get("rich_text", [])
            if proj:
                project_list.add(proj[0]["plain_text"])

            # 업무명 + 업무요약
            task_title = p.get("업무명", {}).get("rich_text", [])
            task_detail = p.get("업무내용", {}).get("rich_text", [])
            task_line = ""
            if task_title:
                task_line += task_title[0]["plain_text"]
            if task_detail:
                task_line += " | " + task_detail[0]["plain_text"]
            if task_line:
                task_summary.append(task_line)

        # ✅ 근무시간 기준으로 Select 상태 결정
        if total_hours == 8:
            status = "✅ 정상"
        elif total_hours < 8:
            status = "⚠️ 미달"
        else:
            status = "🔥 초과"

         # ✅ 업무 요약 나누기 (2000자 제한 대응)
        long_summary = "\n".join(task_summary)
        rich_text_chunks = [{"text": {"content": chunk}} for chunk in split_long_text(long_summary)]

        # ✅ Summary용 속성 구성
        summary_props = {
            "이름": {"title": [{"text": {"content": name}}]},
            "날짜": {"date": {"start": date}},
            "총합 시간": {"number": total_hours},
            "프로젝트 목록": {"rich_text": [{"text": {"content": ", ".join(project_list)}}]},
            "업무 요약": {"rich_text": rich_text_chunks},
            "정상 여부": {"select": {"name": status}}
        }

        # ✅ 기존에 있으면 업데이트, 없으면 새로 생성
        existing = find_existing_summary(name, date)
        if existing:
            notion.pages.update(page_id=existing["id"], properties=summary_props)
        else:
            notion.pages.create(parent={"database_id": SUMMARY_DB_ID}, properties=summary_props)

if __name__ == "__main__":
    main()
