from notion_client import Client
from collections import defaultdict
import os
import re

notion = Client(auth=os.environ["NOTION_TOKEN"])
LOG_DB_ID = os.environ["LOG_DB_ID"]
SUMMARY_DB_ID = os.environ["SUMMARY_DB_ID"]

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

def parse_name_date(pk_str):
    # Ex: '@Thone Thone Win Maw _ @2025년 4월 7일 _ 월'
    match = re.match(r'@(.+?) _ @(\d{4}년 \d{1,2}월 \d{1,2}일)', pk_str)
    if match:
        name = match.group(1).strip()
        date = match.group(2).replace('년 ', '-').replace('월 ', '-').replace('일', '')
        return name, date
    return None, None

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

def main():
    logs = get_log_entries()
    grouped = defaultdict(list)

    for log in logs:
        props = log["properties"]
        pk = props["Aa PK"]["title"][0]["plain_text"]
        name, date = parse_name_date(pk)
        if not name or not date:
            continue
        grouped[(name, date)].append(log)

    for (name, date), entries in grouped.items():
        total_hours = 0
        project_list = set()
        task_summary = []

        for e in entries:
            p = e["properties"]
            hours = p["근무시간"]["number"]
            total_hours += hours or 0

            # 프로젝트명 링크 or 텍스트
            project_url = p["프로젝트명"]["url"] or ""
            project_list.add(project_url)

            task_title = p["업무명"]["rich_text"]
            task_detail = p["업무내용"]["rich_text"]
            task_str = ""
            if task_title:
                task_str += task_title[0]["plain_text"]
            if task_detail:
                task_str += " | " + task_detail[0]["plain_text"]
            task_summary.append(task_str)

        정상 = total_hours >= 8

        summary_props = {
            "이름": {"title": [{"text": {"content": name}}]},
            "날짜": {"date": {"start": date}},
            "총합 시간": {"number": total_hours},
            "프로젝트 목록": {"rich_text": [{"text": {"content": ", ".join(project_list)}}]},
            "업무 요약": {"rich_text": [{"text": {"content": "\n".join(task_summary)}}]},
            "정상 여부": {"checkbox": 정상}
        }

        existing = find_existing_summary(name, date)
        if existing:
            notion.pages.update(page_id=existing["id"], properties=summary_props)
        else:
            notion.pages.create(parent={"database_id": SUMMARY_DB_ID}, properties=summary_props)

if __name__ == "__main__":
    main()
