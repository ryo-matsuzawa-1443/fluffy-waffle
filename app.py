import streamlit as st
from notion_client import Client
from fuzzywuzzy import process
import pandas as pd
import os

NOTION_TOKEN = os.environ.get("NOTION_TOKEN")
AZS_DB_ID = "02c8dffa2f6e45c1898c36b04503bd23"  # 固定の参照元DB
RELATION_PROP_NAME = "AZS DB"

# URLからDB IDを抽出
def extract_db_id(notion_url):
    try:
        return notion_url.split("/")[-1].split("?")[0]
    except:
        return None

# ページネーション対応の関数
def get_database_items(notion, db_id):
    results = []
    try:
        response = notion.databases.query(database_id=db_id)
        results.extend(response["results"])

        while response.get("has_more"):
            response = notion.databases.query(
                database_id=db_id,
                start_cursor=response["next_cursor"]
            )
            results.extend(response["results"])
    except Exception as e:
        st.error(f"データ取得中にエラーが発生しました: {e}")

    return results

# マッチング処理
def run_matching(PJ_DB_ID, threshold):
    notion = Client(auth=NOTION_TOKEN)

    # データベースからアイテム取得（ページネーション対応）
    st.write("データベースからアイテムを取得中...（件数が多い場合、少し時間がかかります）")
    azs_items = get_database_items(notion, AZS_DB_ID)
    PJ_items = get_database_items(notion, PJ_DB_ID)

    azs_names = []
    azs_pages = {}
    for item in azs_items:
        name = item["properties"].get("部屋名", {}).get("title", [])
        if name:
            text = name[0]["text"]["content"]
            azs_names.append(text)
            azs_pages[text] = item["id"]

    PJ_names = []
    PJ_pages = {}
    for item in PJ_items:
        name = item["properties"].get("Name", {}).get("title", [])
        if name:
            text = name[0]["text"]["content"]
            PJ_names.append(text)
            PJ_pages[text] = item["id"]

    approved_matches = []
    pending_matches = []

    for PJ_name in PJ_names:
        best_match, score = process.extractOne(PJ_name, azs_names)
        match_info = {
            "室名": PJ_name,
            "マッチした部屋名": best_match,
            "類似度": score,
            "AZSページID": azs_pages[best_match],
            "検証ページID": PJ_pages[PJ_name],
            "ステータス": "マッチ" if score >= threshold else "保留"
        }

        if score >= threshold:
            approved_matches.append(match_info)
            # Notionのリレーションを更新
            notion.pages.update(
                page_id=match_info["検証ページID"],
                properties={RELATION_PROP_NAME: {
                    "relation": [{"id": match_info["AZSページID"]}]
                }}
            )
            st.write(f'✔️ {match_info["室名"]} → {match_info["マッチした部屋名"]}（スコア: {match_info["類似度"]}）')
        else:
            pending_matches.append(match_info)
            st.write(f'❌ {match_info["室名"]} → {match_info["マッチした部屋名"]}（スコア: {match_info["類似度"]}）')

    # 結果をCSVとしてまとめて出力
    df_matches = pd.DataFrame(approved_matches + pending_matches)
    df_matches.to_csv("matching_results.csv", index=False, encoding='utf-8-sig')

    # ステータス別のメッセージ表示
    if pending_matches:
        st.warning("⚠️ 類似度が低く保留された室名があります（CSVを確認）")
    else:
        st.success("🎉 すべての室名が自動マッチされました！")

    # CSVダウンロードボタン
    with open("matching_results.csv", "rb") as f:
        st.download_button(
            label="📥 マッチング結果CSVをダウンロード",
            data=f,
            file_name="matching_results.csv",
            mime="text/csv"
        )

# Streamlit UI部分
st.title("🏗️ Notion 室名自動マッチングツール")

url = st.text_input("🔗 PJデータベースのURLを入力してください")

threshold = st.slider(
    "📊 類似度のしきい値（この値以上をマッチング対象とします）",
    min_value=0,
    max_value=100,
    value=70,
    step=1,
)

if st.button("🚀 マッチング実行"):
    db_id = extract_db_id(url)
    if db_id:
        st.info(f"✅ DB ID 取得: {db_id}")
        run_matching(db_id, threshold)
    else:
        st.error("❌ 無効なURL形式です。NotionのデータベースURLを確認してください。")
