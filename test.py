from notion_client import Client
from collections import defaultdict
from datetime import datetime
import os

# ✅ 환경변수에서 Notion 정보 가져오기
NOTION_TOKEN = os.environ["NOTION_TOKEN"]
LOG_DB_ID = os.environ["LOG_DB_ID"]
SUMMARY_DB_ID = os.environ["SUMMARY_DB_ID"]

notion = Client(auth=NOTION_TOKEN)

# ✅ 긴 텍스트를 2000자 이하로 잘라주는 함수
def split_long_text(text, max_length=2000):
    return [text[i:i+max_length] for i in range(0, len(text), max_length)]

# ✅ 관계형 페이지에서 title 속성 추출 (프로젝트명용)
def get_title_from_page(page):
    for key, prop in page["properties"].items():
        if prop.get("type") == "title":
            title_data = prop.get("title")
            if title_data:
                return title_data[0]["plain_text"]
    return None

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
    project_cache = {}

    for log in logs:
        props = log["properties"]
        name_field = props.get("PK", {}).get("title", [])
        date_field = props.get("날짜", {}).get("date", {})

        if not name_field or not date_field:
            continue

        name = name_field[0]["plain_text"]
        date = date_field.get("start")
        if not name or not date:
            continue

        log_date = datetime.strptime(date, "%Y-%m-%d")
        today = datetime.today()
        if log_date.year != today.year or log_date.month != today.month:
            continue

        grouped[(name, date)].append(log)

    # ✅ 그룹별 Summary 생성 또는 업데이트
    for (name, date), entries in grouped.items():
        total_hours = 0
        project_list = set()
        task_summary = []

        # ✅ 그룹, 팀 정보 추출 (첫 번째 entry 기준)
        group = ""
        team = ""
        if entries:
            first_props = entries[0]["properties"]
            group = first_props.get("GROUP", {}).get("select", {}).get("name", "")
            team = first_props.get("TEAM", {}).get("select", {}).get("name", "")

        for e in entries:
            p = e["properties"]
            hour = p.get("근무시간", {}).get("number")
            hour = hour if hour else 0
            total_hours += hour

            relations = p.get("프로젝트명", {}).get("relation", [])
            related_titles = []

            for rel in relations:
                pid = rel["id"]
                if pid in project_cache:
                    title = project_cache[pid]
                else:
                    try:
                        page = notion.pages.retrieve(pid)
                        title = get_title_from_page(page)
                        project_cache[pid] = title
                    except Exception as err:
                        print(f"❌ 프로젝트 조회 실패: {pid} → {err}")
                        title = None

                if title:
                    project_list.add(title)
                    related_titles.append(title)

            split_hour = hour / len(related_titles) if related_titles else 0

            task_title = p.get("업무명", {}).get("rich_text", [])
            task_detail = p.get("업무내용", {}).get("rich_text", [])
            for proj in related_titles:
                task_line = f"[({split_hour:.1f}) {proj}]\n"
                if task_title:
                    task_line += task_title[0]["plain_text"]
                if task_detail:
                    task_line += " | " + task_detail[0]["plain_text"]
                if task_line:
                    task_summary.append(task_line + "\n")

        total_hours = min(total_hours, 8)

        status = "✅ 정상" if total_hours == 8 else "⚠️ 미달" if total_hours < 8 else "🔥 초과"

        long_summary = "\n".join(task_summary)
        rich_text_chunks = [{"text": {"content": chunk}} for chunk in split_long_text(long_summary)]

        # ✅ 기본 Summary 속성
        summary_props = {
            "이름": {"title": [{"text": {"content": name}}]},
            "날짜": {"date": {"start": date}},
            "총합 시간": {"number": total_hours},
            "프로젝트 목록": {"rich_text": [{"text": {"content": ", ".join(project_list)}}]},
            "업무 요약": {"rich_text": rich_text_chunks},
            "정상 여부": {"select": {"name": status}},
        }

        # ✅ 그룹/팀 속성은 값 있을 때만 추가
        if group:
            summary_props["그룹"] = {"select": {"name": group}}
        if team:
            summary_props["팀"] = {"select": {"name": team}}

        # ✅ 업데이트 시 "이름" 필드 제거 (Notion 제한 때문)
        existing = find_existing_summary(name, date)
        if existing:
            update_props = summary_props.copy()
            update_props.pop("이름", None)
            notion.pages.update(page_id=existing["id"], properties=update_props)
        else:
            notion.pages.create(parent={"database_id": SUMMARY_DB_ID}, properties=summary_props)

if __name__ == "__main__":
    main()
