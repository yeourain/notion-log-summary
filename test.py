import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from notion_client import Client
from collections import defaultdict
from datetime import datetime
import os

# ✅ 환경변수에서 Notion 정보 가져오기
NOTION_TOKEN = os.environ["NOTION_TOKEN"]
LOG_DB_ID = os.environ["LOG_DB_ID"]
SUMMARY_DB_ID = os.environ["SUMMARY_DB_ID"]
notion = Client(auth=NOTION_TOKEN)

def split_long_text(text, max_length=2000):
    return [text[i:i + max_length] for i in range(0, len(text), max_length)]

def get_title_from_page(page):
    for key, prop in page["properties"].items():
        if prop.get("type") == "title":
            title_data = prop.get("title")
            if title_data:
                return title_data[0]["plain_text"]
    return None

# ✅ 병렬 프로젝트 캐싱 (with 재시도)
def build_project_title_cache(logs):
    project_ids = set()
    for log in logs:
        relations = log["properties"].get("프로젝트명", {}).get("relation", [])
        for rel in relations:
            project_ids.add(rel["id"])

    cache = {}

    def fetch_title(pid):
        for _ in range(3):
            try:
                page = notion.pages.retrieve(pid)
                return pid, get_title_from_page(page)
            except Exception as e:
                print(f"⚠️ 프로젝트 조회 실패 {pid}, 재시도: {e}")
                time.sleep(1)
        return pid, None

    with ThreadPoolExecutor(max_workers=5) as executor:
        futures = [executor.submit(fetch_title, pid) for pid in project_ids]
        for future in as_completed(futures):
            pid, title = future.result()
            if title:
                cache[pid] = title

    return cache

# ✅ Summary 중복 확인 (with 재시도)
def find_existing_summary(name, date, retries=3, delay=2):
    for attempt in range(retries):
        try:
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
        except Exception as e:
            print(f"⚠️ 요약 조회 실패 (시도 {attempt+1}): {e}")
            time.sleep(delay)
    print("❌ 요약 최종 조회 실패 → name:", name, "/ date:", date)
    return None

def get_select_or_text(props, field_name):
    field = props.get(field_name, {})
    field_type = field.get("type", "")
    if field_type == "select":
        return field.get("select", {}).get("name", "")
    elif field_type == "rich_text":
        texts = field.get("rich_text", [])
        if texts:
            return texts[0].get("plain_text", "")
    return ""

# ✅ 직원페이지에서 그룹/팀 정보 (with 캐시 + 재시도)
def get_group_team_from_staff_page(staff_page_id, staff_cache):
    if staff_page_id in staff_cache:
        return staff_cache[staff_page_id]

    for _ in range(3):
        try:
            page = notion.pages.retrieve(staff_page_id)
            props = page["properties"]
            group = get_select_or_text(props, "그룹")
            team = get_select_or_text(props, "팀")
            staff_cache[staff_page_id] = (group, team)
            return group, team
        except Exception as e:
            print(f"⚠️ 직원페이지 조회 실패 {staff_page_id}, 재시도: {e}")
            time.sleep(1)

    staff_cache[staff_page_id] = ("", "")
    return "", ""

# ✅ Notion safe update/create
def safe_update_page(page_id, properties, retries=3, delay=2):
    for attempt in range(retries):
        try:
            notion.pages.update(page_id=page_id, properties=properties)
            return
        except Exception as e:
            print(f"⚠️ update 실패 (시도 {attempt + 1}): {e}")
            time.sleep(delay)
    print("❌ update 최종 실패")

def safe_create_page(database_id, properties, retries=3, delay=2):
    for attempt in range(retries):
        try:
            notion.pages.create(parent={"database_id": database_id}, properties=properties)
            return
        except Exception as e:
            print(f"⚠️ create 실패 (시도 {attempt + 1}): {e}")
            time.sleep(delay)
    print("❌ create 최종 실패")

# ✅ 전체 Log 조회
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

# ✅ 메인 실행
def main():
    logs = get_log_entries()
    grouped = defaultdict(list)

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

        grouped[(name, date)].append(log)

    project_cache = build_project_title_cache(logs)
    staff_cache = {}

    for (name, date), entries in grouped.items():
        total_hours = 0
        project_list = set()
        task_summary = []

        group = ""
        team = ""
        if entries:
            staff_relation = entries[0]["properties"].get("직원페이지", {}).get("relation", [])
            if staff_relation:
                staff_page_id = staff_relation[0]["id"]
                group, team = get_group_team_from_staff_page(staff_page_id, staff_cache)

        for e in entries:
            p = e["properties"]
            hour = p.get("근무시간", {}).get("number") or 0
            total_hours += hour

            relations = p.get("프로젝트명", {}).get("relation", [])
            related_titles = [project_cache.get(rel["id"]) for rel in relations if rel["id"] in project_cache]

            split_hour = hour / len(related_titles) if related_titles else 0

            task_title = p.get("업무명", {}).get("rich_text", [])
            task_detail = p.get("업무내용", {}).get("rich_text", [])
            for proj in related_titles:
                task_line = f"[({split_hour:.1f}) {proj}]\n"
                if task_title:
                    task_line += task_title[0]["plain_text"]
                if task_detail:
                    task_line += " | " + task_detail[0]["plain_text"]
                task_summary.append(task_line + "\n")
                project_list.add(proj)

        total_hours = min(total_hours, 8)
        status = "✅ 정상" if total_hours == 8 else "⚠️ 미달" if total_hours < 8 else "🔥 초과"
        long_summary = "\n".join(task_summary)
        rich_text_chunks = [{"text": {"content": chunk}} for chunk in split_long_text(long_summary)]

        summary_props = {
            "이름": {"title": [{"text": {"content": name}}]},
            "날짜": {"date": {"start": date}},
            "총합 시간": {"number": total_hours},
            "프로젝트 목록": {"rich_text": [{"text": {"content": ", ".join(project_list)}}]},
            "업무 요약": {"rich_text": rich_text_chunks},
            "정상 여부": {"select": {"name": status}},
        }

        if group:
            summary_props["그룹"] = {"select": {"name": group}}
        if team:
            summary_props["팀"] = {"select": {"name": team}}

        existing = find_existing_summary(name, date)
        if existing:
            update_props = summary_props.copy()
            update_props.pop("이름", None)
            safe_update_page(existing["id"], update_props)
        else:
            safe_create_page(SUMMARY_DB_ID, summary_props)

if __name__ == "__main__":
    main()
