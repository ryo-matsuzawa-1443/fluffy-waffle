import streamlit as st
from notion_client import Client
from sentence_transformers import SentenceTransformer, util
import pandas as pd
import os

NOTION_TOKEN = os.environ.get("NOTION_TOKEN")
AZS_DB_ID = "02c8dffa2f6e45c1898c36b04503bd23"
RELATION_PROP_NAME = "AZS DB"

# -------------------------------
# ✅ モデルの自動ダウンロード＋キャッシュ読み込み
# -------------------------------
MODEL_NAME = 'paraphrase-MiniLM-L6-v2'
MODEL_DIR = './.cache_model'

if not os.path.exists(MODEL_DIR):
    st.info("🤖 モデルを初回ダウンロード中です。少しお待ちください...")
    model = SentenceTransformer(MODEL_NAME)
    model.save(MODEL_DIR)
else:
    model = SentenceTransformer(MODEL_DIR)

# -------------------------------
# 🔧 関数：URLからDB IDを抽出
# -------------------------------
def extract_db_id(notion_url):
    try:
        return notion_url.split("/")[-1].split("?")[0]
    except:
        return None

# -------------------------------
# 🔧 関数：100件以上取得対応
# -------------------------------
def get_database_items(notion, db_id):
    results = []
    next_cursor = None

    while True:
        response = notion.databases.query(
            database_id=db_id,
            start_cursor=next_cursor
        ) if next_cursor else notion.databases.query(database_id=db_id)

        results.extend(response["results"])

        if response.get("has_more"):
            next_cursor = response["next_cursor"]
        else:
            break

    return results

# -------------------------------
# 🔧 関数：マッチング実行
# -------------------------------
def run_matching(PJ_DB_ID, threshold):
    notion = Client(auth=NOTION_TOKEN)

    azs_items = get_database_items(notion, AZS_DB_ID)
    PJ_items = get_database_items(notion, PJ_DB_ID)

    azs_names, azs_pages = [], {}
    for item in azs_items:
        name = item["properties"].get("部屋名", {}).get("title", [])
        if name:
            text = name[0]["text"]["content"]
            azs_names.append(text)
            azs_pages[text] = item["id"]

    PJ_names, PJ_pages = [], {}
    for item in PJ_items:
        name = item["properties"].get("室名", {}).get("title", [])
        if name:
            text = name[0]["text"]["content"]
            PJ_names.append(text)
            PJ_pages[text] = item["id"]

    azs_embeddings = model.encode(azs_names, convert_to_tensor=True)
    pj_embeddings = model.encode(PJ_names, convert_to_tensor=True)

    cosine_scores = util.pytorch_cos_sim(pj_embeddings, azs_embeddings)

    approved_matches = []
    pending_matches = []

    for i, PJ_name in enumerate(PJ_names):
        score_row = cosine_scores[i]
        best_index = int(score_row.argmax())
        best_score = float(score_row[best_index])
        best_match = azs_names[best_index]

        match_info = {
            "室名": PJ_name,
            "マッチした部屋名": best_match,
            "類似度": int(best_score * 100),
            "AZSページID": azs_pages[best_match],
            "検証ページID": PJ_pages[PJ_name],
        }

        if match_info["類似度"] >= threshold:
            approved_matches.append(match_info)
        else:
            pending_matches.append(match_info)

    for match in approved_matches:
        notion.pages.update(
            page_id=match["検証ページID"],
            properties={RELATION_PROP_NAME: {
                "relation": [{"id": match["AZSページID"]}]
            }}
        )
        st.write(f'✔️ {match["室名"]} → {match["マッチした部屋名"]}（スコア: {match["類似度"]}）')

    df_pending = pd.DataFrame(pending_matches)
    df_approved = pd.DataFrame(approved_matches)

    df_pending.to_csv("pending_matches.csv", index=False, encoding='utf-8-sig')
    df_approved.to_csv("approved_matches.csv", index=False, encoding='utf-8-sig')

    if pending_matches:
        st.warning("⚠️ 類似度が低く保留された室名あり（保留マッチングCSV を確認）")
        st.dataframe(df_pending)
    else:
        st.success("🎉 すべての室名が自動マッチされました！")

    with open("approved_matches.csv", "rb") as f:
        st.download_button(
            label="📥 承認済みマッチングCSVをダウンロード",
            data=f,
            file_name="approved_matches.csv",
            mime="text/csv"
        )

    with open("pending_matches.csv", "rb") as f:
        st.download_button(
            label="📥 保留マッチングCSVをダウンロード",
            data=f,
            file_name="pending_matches.csv",
            mime="text/csv"
        )

# -------------------------------
# 🖼️ Streamlit UI
# -------------------------------
st.title("🏗️ Notion 室名AIマッチングツール")

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
